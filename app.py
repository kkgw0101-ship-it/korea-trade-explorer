"""한국 수출입 무역통계 인텔리전스 대시보드."""

from __future__ import annotations

import io
from datetime import date, timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import sample_data
import theme
from country_codes import COUNTRY_CODES
from hs_presets import HS_PRESETS
from market_data import (
    MARKET_SERIES,
    MarketDataError,
    fetch_fred_bundle,
    indexed_series,
    series_snapshot,
)
from trade_data import (
    TradeDataError,
    analysis_summary,
    fetch_trade,
    normalize_key,
    percent_change,
    prepare_periods,
)


st.set_page_config(
    page_title="Korea Trade Intelligence",
    page_icon="⚓",
    layout="wide",
    initial_sidebar_state="auto",
)
theme.inject()


def previous_month(today: date) -> date:
    return date(today.year, today.month, 1) - timedelta(days=1)


def format_money(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"${value / 1_000_000_000:,.2f}B"
    if absolute >= 1_000_000:
        return f"${value / 1_000_000:,.1f}M"
    if absolute >= 1_000:
        return f"${value / 1_000:,.1f}K"
    return f"${value:,.0f}"


def format_weight(value: float) -> str:
    tonnes = value / 1_000
    absolute = abs(tonnes)
    if absolute >= 1_000_000:
        return f"{tonnes / 1_000_000:,.2f}M t"
    if absolute >= 1_000:
        return f"{tonnes / 1_000:,.1f}K t"
    return f"{tonnes:,.1f} t"


def format_rate(value: float | None, *, prefix: str = "") -> tuple[str, str]:
    if value is None:
        return "비교 기간 부족", "neutral"
    sign = "+" if value >= 0 else ""
    tone = "positive" if value >= 0 else "negative"
    return f"{prefix}{sign}{value:,.1f}%", tone


def format_quote_change(value: float | None) -> tuple[str, str]:
    if value is None or pd.isna(value):
        return "• N/A", "neutral"
    if abs(value) < 0.05:
        return "• 0.0%", "neutral"
    arrow = "▲" if value > 0 else "▼"
    tone = "up" if value > 0 else "down"
    return f"{arrow} {abs(value):,.1f}%", tone


def format_market_value(series_id: str, value: float) -> str:
    metadata = MARKET_SERIES[series_id]
    return f"{value:{metadata['format']}}"


def filter_window(frame: pd.DataFrame, window: str, date_col: str) -> pd.DataFrame:
    if frame.empty or window == "ALL":
        return frame.copy()
    offsets = {"6M": pd.DateOffset(months=6), "1Y": pd.DateOffset(years=1), "3Y": pd.DateOffset(years=3)}
    latest = pd.Timestamp(frame[date_col].max())
    return frame.loc[frame[date_col] >= latest - offsets[window]].copy()


def trade_index_frame(periods: pd.DataFrame, window: str) -> pd.DataFrame:
    """금액·중량·단가를 첫 관측월=100으로 맞춘 비교 시계열."""
    selected = filter_window(periods, window, "period_date")
    definitions = {
        "수출금액": "export_usd",
        "수출중량": "export_wgt",
        "수출단가": "export_unit_usd",
    }
    pieces: list[pd.DataFrame] = []
    for label, column in definitions.items():
        part = selected[["period_date", "label", column]].dropna().copy()
        nonzero = part.loc[part[column] != 0, column]
        if part.empty or nonzero.empty:
            continue
        part["index"] = part[column] / float(nonzero.iloc[0]) * 100
        part["지표"] = label
        pieces.append(part.rename(columns={column: "actual"}))
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()


def get_deployed_key() -> str:
    try:
        return str(st.secrets.get("DATA_GO_KR_SERVICE_KEY", "")).strip()
    except Exception:
        return ""


def chart_style(chart: alt.Chart) -> alt.Chart:
    """모든 분석 차트에 동일한 KCC글라스 시각 규칙을 적용한다."""
    return (
        chart.configure_axis(
            labelColor=theme.MUTED,
            titleColor=theme.MUTED,
            gridColor="#E6EBF1",
            domainColor="#C9D2DE",
            tickColor="#C9D2DE",
            labelFont="IBM Plex Sans KR",
            titleFont="IBM Plex Sans KR",
        )
        .configure_legend(
            labelColor=theme.MUTED,
            labelFont="IBM Plex Sans KR",
            symbolStrokeWidth=3,
        )
        .configure_view(strokeWidth=0)
    )


@st.cache_data(ttl=3600, show_spinner=False)
def cached_trade(
    service_key: str,
    hs_code: str,
    country_code: str,
    start_ym: str,
    end_ym: str,
) -> pd.DataFrame:
    return fetch_trade(service_key, hs_code, country_code, start_ym, end_ym)


@st.cache_data(ttl=21600, show_spinner=False)
def cached_market_indicators() -> dict[str, pd.DataFrame]:
    """FRED 외부 시장지표를 6시간 동안 캐시한다."""
    return fetch_fred_bundle()


def load_sample(start_ym: str, end_ym: str, hs_code: str, country: str) -> pd.DataFrame:
    # 배포 중 app.py와 sample_data.py가 서로 다른 커밋이어도 동작하도록
    # 기존 3개 인자 API를 사용하고 상대국 표시는 호출부에서 보정한다.
    frame = sample_data.build(start_ym, end_ym, hs_code).copy()
    if "country" in frame.columns:
        frame["country"] = country
    return frame


def set_result(
    raw: pd.DataFrame,
    *,
    hs_code: str,
    hs_label: str,
    country: str,
    start_ym: str,
    end_ym: str,
    demo: bool,
) -> None:
    st.session_state["raw"] = raw
    st.session_state["periods"] = prepare_periods(raw)
    st.session_state["meta"] = {
        "hs": hs_code,
        "label": hs_label,
        "country": country,
        "start": start_ym,
        "end": end_ym,
    }
    st.session_state["demo"] = demo


today = date.today()
latest_complete = previous_month(today)
default_start_year = max(2000, latest_complete.year - 2)
deployed_key = get_deployed_key()
logo_uri = theme.asset_data_uri(
    Path(__file__).resolve().parent / "assets" / "kcc_glass_logo_fullcolor.svg"
)

with st.sidebar:
    st.markdown(
        "<div class='sidebar-brand'>"
        f"<img class='sidebar-logo' src='{logo_uri}' alt='KCC글라스'>"
        "<span>TRADE INTELLIGENCE PLATFORM</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown("### 분석 조건")
    st.caption("품목·상대국·기간을 설정하고 월별 통관실적을 분석합니다.")

    with st.form("query_form"):
        data_mode = st.radio(
            "데이터 모드",
            ["샘플로 둘러보기", "관세청 API 조회"],
            horizontal=True,
            help="샘플은 화면 검토용 가상 데이터이며 실제 통계가 아닙니다.",
        )

        preset_labels = [f"{item['code']} · {item['label']}" for item in HS_PRESETS]
        selected_preset = st.selectbox("기준 품목", preset_labels, index=0)
        custom_hs = st.text_input(
            "HS Code 직접 지정 (선택)",
            placeholder="예: 391810",
            help="입력하면 위 기준 품목보다 우선 적용됩니다.",
        )
        country_name = st.selectbox("상대국", list(COUNTRY_CODES), index=0)

        year_options = list(range(2000, latest_complete.year + 1))
        start_col, end_col = st.columns(2)
        with start_col:
            start_year = st.selectbox(
                "시작 연도", year_options, index=year_options.index(default_start_year)
            )
            start_month = st.selectbox("시작 월", list(range(1, 13)), index=0)
        with end_col:
            end_year = st.selectbox(
                "종료 연도", year_options, index=year_options.index(latest_complete.year)
            )
            end_month = st.selectbox(
                "종료 월", list(range(1, 13)), index=latest_complete.month - 1
            )

        supplied_key = st.text_input(
            "공공데이터포털 인증키",
            type="password",
            placeholder="일반 인증키(Decoding)를 붙여 넣으세요",
            help=(
                "샘플 모드에서도 키를 입력하면 실제 API 조회가 우선됩니다. "
                "입력값은 세션 밖에 저장하지 않습니다."
            ),
        )
        submitted = st.form_submit_button("분석 실행", type="primary", width="stretch")

    st.markdown(
        "<div class='sidebar-help'><b>데이터 해석 기준</b><br>"
        "수출은 FOB, 수입은 CIF 기준입니다. 금액은 USD, 중량은 kg이며 "
        "최근 월 수치는 추후 정정될 수 있습니다.</div>",
        unsafe_allow_html=True,
    )


selected_index = preset_labels.index(selected_preset)
preset = HS_PRESETS[selected_index]
hs_code = custom_hs.strip() or preset["code"]
hs_label = "직접 입력" if custom_hs.strip() else preset["label"]
start_ym = f"{start_year:04d}{start_month:02d}"
end_ym = f"{end_year:04d}{end_month:02d}"

if submitted:
    if not hs_code.isdigit() or len(hs_code) not in {2, 4, 6, 10}:
        st.sidebar.error("HS Code는 숫자 2·4·6·10자리로 입력해 주세요.")
    elif start_ym > end_ym:
        st.sidebar.error("시작 시점이 종료 시점보다 늦습니다.")
    elif data_mode == "관세청 API 조회" or supplied_key.strip():
        active_key = supplied_key.strip() or deployed_key
        if not active_key:
            st.sidebar.error("API 조회에는 공공데이터포털 인증키가 필요합니다.")
        else:
            with st.spinner("관세청 통관실적을 조회하고 월별로 정리하는 중입니다…"):
                try:
                    raw_result = cached_trade(
                        normalize_key(active_key),
                        hs_code,
                        COUNTRY_CODES[country_name],
                        start_ym,
                        end_ym,
                    )
                except TradeDataError as exc:
                    st.sidebar.error(str(exc))
                else:
                    set_result(
                        raw_result,
                        hs_code=hs_code,
                        hs_label=hs_label,
                        country=country_name,
                        start_ym=start_ym,
                        end_ym=end_ym,
                        demo=False,
                    )
    else:
        set_result(
            load_sample(start_ym, end_ym, hs_code, country_name),
            hs_code=hs_code,
            hs_label=hs_label,
            country=country_name,
            start_ym=start_ym,
            end_ym=end_ym,
            demo=True,
        )

if "periods" not in st.session_state:
    initial_start = f"{default_start_year:04d}01"
    initial_end = f"{latest_complete.year:04d}{latest_complete.month:02d}"
    set_result(
        load_sample(initial_start, initial_end, HS_PRESETS[0]["code"], "미국"),
        hs_code=HS_PRESETS[0]["code"],
        hs_label=HS_PRESETS[0]["label"],
        country="미국",
        start_ym=initial_start,
        end_ym=initial_end,
        demo=True,
    )

periods = st.session_state["periods"]
raw = st.session_state["raw"]
meta = st.session_state["meta"]
is_demo = st.session_state["demo"]

st.markdown(
    f"""
    <div class="masthead">
      <div class="brand-lockup">
        <img class="masthead-logo" src="{logo_uri}" alt="KCC글라스">
        <div class="brand-divider"></div>
        <div>
          <div class="eyebrow">Global Market Analytics</div>
          <h1>Trade Intelligence Platform</h1>
          <p>관세청 통관실적을 금액·물량·단가 관점에서 읽는 월별 수출입 분석 플랫폼</p>
        </div>
      </div>
      <div class="masthead-meta">
        <div class="eyebrow">Decision support</div>
        <div class="meta-copy">시장 모니터링 · 물량 진단 · 가격 포지셔닝</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

coverage = f"{meta['start'][:4]}.{int(meta['start'][4:]):02d}—{meta['end'][:4]}.{int(meta['end'][4:]):02d}"
st.markdown(
    "<div class='trust-strip'>"
    "<div class='trust-item'><div class='trust-label'>Source</div><div class='trust-value'>관세청 통관실적</div></div>"
    f"<div class='trust-item'><div class='trust-label'>Coverage</div><div class='trust-value'>{theme.esc(coverage)}</div></div>"
    "<div class='trust-item'><div class='trust-label'>Grain</div><div class='trust-value'>월별 · HS Code</div></div>"
    "<div class='trust-item'><div class='trust-label'>Lenses</div><div class='trust-value'>금액 · 중량 · 단가</div></div>"
    "</div>",
    unsafe_allow_html=True,
)

if is_demo:
    st.markdown(
        "<div class='status-banner'><span class='status-dot'></span><div>"
        "<b>현재 화면은 샘플 모드입니다.</b> 수치는 실제 통계가 아니며, 왼쪽에서 ‘관세청 API 조회’를 "
        "선택하면 공공데이터 기반 결과로 전환됩니다.</div></div>",
        unsafe_allow_html=True,
    )

if periods.empty:
    st.warning("선택한 조건에 월별 데이터가 없습니다. HS Code 자릿수를 줄이거나 기간을 넓혀 보세요.")
    st.stop()

summary = analysis_summary(periods)
latest_row = periods.iloc[-1]
prior_row = periods.iloc[-2] if len(periods) >= 2 else None
latest_unit_value = latest_row["export_unit_usd"]
unit_mom = (
    percent_change(float(latest_unit_value), float(prior_row["export_unit_usd"]))
    if prior_row is not None
    and pd.notna(latest_unit_value)
    and pd.notna(prior_row["export_unit_usd"])
    else None
)

market_error: str | None = None
try:
    market_frames = cached_market_indicators()
except MarketDataError as exc:
    market_frames = {}
    market_error = str(exc)
market_snapshots = {
    series_id: series_snapshot(frame) for series_id, frame in market_frames.items()
}

query_title = f"HS {meta['hs']} · {meta['label']}"
theme.section_title(
    query_title,
    f"상대국 {meta['country']} · {summary['months']}개월 관측 · 최신 관측월 {summary['latest_period']}",
)

value_change, value_tone = format_quote_change(summary["export_mom"])
weight_change, weight_tone = format_quote_change(summary["export_wgt_mom"])
unit_change, unit_tone = format_quote_change(unit_mom)
latest_balance = float(latest_row["balance_usd"])
ticker_items = [
    {
        "label": "수출 신고금액",
        "status": "MONTHLY CLOSE",
        "value": format_money(summary["latest_export"]),
        "change": value_change,
        "tone": value_tone,
    },
    {
        "label": "수출 중량",
        "status": "MONTHLY CLOSE",
        "value": format_weight(summary["latest_export_wgt"]),
        "change": weight_change,
        "tone": weight_tone,
    },
    {
        "label": "수출 신고단가",
        "status": "MONTHLY CLOSE",
        "value": f"${latest_unit_value:,.2f}/kg" if pd.notna(latest_unit_value) else "N/A",
        "change": unit_change,
        "tone": unit_tone,
    },
    {
        "label": "월 무역수지",
        "status": "MONTHLY CLOSE",
        "value": format_money(latest_balance),
        "change": "흑자" if latest_balance >= 0 else "적자",
        "tone": "up" if latest_balance >= 0 else "down",
    },
]
for series_id, snapshot in market_snapshots.items():
    if not snapshot:
        continue
    quote_change, quote_tone = format_quote_change(snapshot.get("change_pct"))
    metadata = MARKET_SERIES[series_id]
    ticker_items.append(
        {
            "label": metadata["name"],
            "status": metadata["frequency"],
            "value": format_market_value(series_id, float(snapshot["latest_value"])),
            "change": quote_change,
            "tone": quote_tone,
        }
    )
theme.market_tape(ticker_items)

growth_note, growth_tone = format_rate(summary["recent_12_growth"], prefix="직전 12개월 대비 ")
mom_note, mom_tone = format_rate(summary["export_mom"], prefix="전월 대비 ")
balance_tone = "positive" if summary["balance"] >= 0 else "negative"

st.markdown(
    "<div class='analysis-band'><strong>금액 성과 요약</strong>"
    "<span>VALUE LENS · CUSTOMS DECLARED VALUE</span></div>",
    unsafe_allow_html=True,
)
kpi_cols = st.columns(4)
with kpi_cols[0]:
    theme.kpi_card("01", "수출 신고금액 누계", format_money(summary["total_export"]), growth_note, growth_tone)
with kpi_cols[1]:
    theme.kpi_card("02", "수입 신고금액 누계", format_money(summary["total_import"]), "조회 기간 합계")
with kpi_cols[2]:
    balance_label = "흑자" if summary["balance"] >= 0 else "적자"
    theme.kpi_card("03", "무역수지", format_money(summary["balance"]), balance_label, balance_tone)
with kpi_cols[3]:
    theme.kpi_card("04", f"최근 월 수출금액 · {summary['latest_period']}", format_money(summary["latest_export"]), mom_note, mom_tone)

st.write("")
market_tab, amount_tab, weight_tab, balance_tab, data_tab, method_tab = st.tabs(
    ["Market Pulse", "금액 분석", "중량 분석", "수지 · 단가", "데이터", "해석 기준"]
)

with market_tab:
    observation_dates = [
        str(snapshot.get("latest_date"))
        for snapshot in market_snapshots.values()
        if snapshot and snapshot.get("latest_date")
    ]
    market_freshness = max(observation_dates) if observation_dates else "연결 대기"
    connection_copy = (
        f"EXTERNAL MARKET LATEST OBSERVATION · {market_freshness} · FRED 6H CACHE"
        if market_frames
        else "EXTERNAL MARKET DATA · TEMPORARILY UNAVAILABLE · TRADE DATA ACTIVE"
    )
    st.markdown(
        "<div class='market-status-row'>"
        f"<div class='market-status-left'><span class='market-live-dot{' offline' if not market_frames else ''}'></span>"
        f"<span>{'MARKET MONITOR ACTIVE' if market_frames else 'MARKET MONITOR DEGRADED'}</span></div>"
        f"<span>{theme.esc(connection_copy)}</span></div>",
        unsafe_allow_html=True,
    )

    terminal_col, signal_col = st.columns([2.2, 1], gap="large")
    with terminal_col:
        st.markdown("<div class='chart-heading'>수출 모멘텀 비교지수</div>", unsafe_allow_html=True)
        st.markdown(
            "<div class='chart-subtitle'>선택 구간의 첫 관측월=100 · 금액·중량·단가의 상대 흐름 비교</div>",
            unsafe_allow_html=True,
        )
        terminal_window = st.radio(
            "수출 모멘텀 조회 구간",
            ["6M", "1Y", "3Y", "ALL"],
            index=1,
            horizontal=True,
            label_visibility="collapsed",
            key="trade_terminal_window",
        )
        trade_index = trade_index_frame(periods, terminal_window)
        if trade_index.empty or trade_index["period_date"].nunique() < 2:
            st.info("선택 구간에 비교 가능한 관측값이 부족합니다.")
        else:
            terminal_nearest = alt.selection_point(
                nearest=True,
                on="pointerover",
                fields=["period_date"],
                empty=False,
                clear="pointerout",
            )
            terminal_colors = alt.Scale(
                domain=["수출금액", "수출중량", "수출단가"],
                range=[theme.EXPORT, theme.IMPORT, theme.BRAND_RED],
            )
            terminal_base = alt.Chart(trade_index).encode(
                x=alt.X(
                    "period_date:T",
                    title=None,
                    axis=alt.Axis(format="%y.%m", labelAngle=0, tickCount=8),
                )
            )
            terminal_lines = terminal_base.mark_line(strokeWidth=2.4).encode(
                y=alt.Y("index:Q", title="비교지수 (시작=100)", scale=alt.Scale(zero=False)),
                color=alt.Color("지표:N", scale=terminal_colors, legend=alt.Legend(title=None, orient="top")),
                tooltip=[
                    alt.Tooltip("label:N", title="기간"),
                    alt.Tooltip("지표:N"),
                    alt.Tooltip("index:Q", title="비교지수", format=",.1f"),
                    alt.Tooltip("actual:Q", title="원값", format=",.2f"),
                ],
            )
            terminal_selectors = terminal_base.mark_point(opacity=0).add_params(terminal_nearest)
            terminal_points = terminal_lines.mark_point(size=65, filled=True).encode(
                opacity=alt.condition(terminal_nearest, alt.value(1), alt.value(0))
            )
            terminal_rule = terminal_base.mark_rule(color=theme.INK, opacity=.24).encode(
                opacity=alt.condition(terminal_nearest, alt.value(.45), alt.value(0))
            ).transform_filter(terminal_nearest)
            terminal_latest = (
                trade_index.sort_values("period_date").groupby("지표", as_index=False).tail(1)
            )
            terminal_end_points = alt.Chart(terminal_latest).mark_point(size=54, filled=True).encode(
                x="period_date:T",
                y="index:Q",
                color=alt.Color("지표:N", scale=terminal_colors, legend=None),
            )
            terminal_end_labels = alt.Chart(terminal_latest).mark_text(
                align="left", dx=7, font="IBM Plex Mono", fontSize=10
            ).encode(
                x="period_date:T",
                y="index:Q",
                text=alt.Text("index:Q", format=",.1f"),
                color=alt.Color("지표:N", scale=terminal_colors, legend=None),
            )
            terminal_chart = (
                terminal_lines
                + terminal_selectors
                + terminal_points
                + terminal_rule
                + terminal_end_points
                + terminal_end_labels
            ).properties(height=350, padding={"right": 44})
            st.altair_chart(chart_style(terminal_chart), width="stretch")

    with signal_col:
        st.markdown("<div class='chart-heading'>LVT Market Signals</div>", unsafe_allow_html=True)
        st.markdown("<div class='chart-subtitle'>규칙 기반 모멘텀 스캔 · 투자 신호 아님</div>", unsafe_allow_html=True)
        volume_signal = summary.get("export_wgt_yoy")
        if volume_signal is None:
            theme.signal_card("VOLUME NEUTRAL", "물량 비교기간 부족", "전년 동월 관측값이 확보되면 물량 모멘텀을 표시합니다.", "neutral")
        else:
            theme.signal_card(
                "VOLUME UP" if volume_signal >= 0 else "VOLUME WATCH",
                f"수출중량 전년동월 대비 {volume_signal:+.1f}%",
                "신고금액과 분리해 실물 물동량의 방향을 보여줍니다.",
                "positive" if volume_signal >= 0 else "negative",
            )
        if unit_mom is None:
            theme.signal_card("PRICE NEUTRAL", "단가 비교기간 부족", "신고중량이 확보되면 kg당 단가 변화를 표시합니다.", "neutral")
        else:
            theme.signal_card(
                "PRICE UP" if unit_mom >= 0 else "PRICE WATCH",
                f"수출 신고단가 전월 대비 {unit_mom:+.1f}%",
                "금액 변화가 가격·품목 구성 측에서 발생했는지 확인하는 보조 신호입니다.",
                "positive" if unit_mom >= 0 else "negative",
            )
        housing = market_snapshots.get("HOUST", {})
        housing_change = housing.get("change_pct") if housing else None
        if housing_change is None:
            theme.signal_card("DEMAND OFFLINE", "미국 수요지표 연결 대기", "외부 연결 실패와 무관하게 무역 분석은 계속 사용할 수 있습니다.", "neutral")
        else:
            theme.signal_card(
                "DEMAND UP" if housing_change >= 0 else "DEMAND WATCH",
                f"미국 주택착공 전월 대비 {float(housing_change):+.1f}%",
                "LVT 최종 수요 환경을 읽기 위한 거시 보조지표이며 직접 매출 지표는 아닙니다.",
                "positive" if housing_change >= 0 else "negative",
            )

    st.write("")
    theme.section_title(
        "External Market Monitor",
        "환율·에너지·미국 주택시장의 최신 공개 관측값을 데이터 주기에 맞춰 표시합니다.",
    )
    if not market_frames:
        st.info(market_error or "외부 시장지표를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")
    else:
        market_name_to_id = {
            MARKET_SERIES[series_id]["name"]: series_id for series_id in market_frames
        }
        monitor_control, monitor_range = st.columns([2, 3])
        with monitor_control:
            selected_market_name = st.selectbox(
                "시장 지표",
                list(market_name_to_id),
                key="market_monitor_series",
            )
        with monitor_range:
            market_window = st.radio(
                "시장지표 조회 구간",
                ["6M", "1Y", "3Y", "ALL"],
                index=1,
                horizontal=True,
                label_visibility="collapsed",
                key="market_monitor_window",
            )

        selected_market_id = market_name_to_id[selected_market_name]
        selected_market_meta = MARKET_SERIES[selected_market_id]
        selected_snapshot = market_snapshots[selected_market_id]
        stat_values = [
            ("M1", f"Actual · {selected_market_meta['unit']}", format_market_value(selected_market_id, float(selected_snapshot["latest_value"])), str(selected_snapshot["latest_date"]), "neutral"),
            ("M2", selected_market_meta["change_label"], *format_rate(selected_snapshot.get("change_pct"))),
            ("M3", "1개월 변화", *format_rate(selected_snapshot.get("month_pct"))),
            ("M4", "1년 변화", *format_rate(selected_snapshot.get("year_pct"))),
        ]
        market_kpis = st.columns(4)
        for column, stat in zip(market_kpis, stat_values):
            with column:
                if stat[0] == "M1":
                    theme.kpi_card(stat[0], stat[1], stat[2], stat[3], stat[4])
                else:
                    theme.kpi_card(stat[0], stat[1], stat[2], "기준 관측값 대비", stat[3])

        selected_market = filter_window(market_frames[selected_market_id], market_window, "date")
        market_low = float(selected_market["value"].min())
        market_high = float(selected_market["value"].max())
        market_span = market_high - market_low
        market_padding = market_span * .08 if market_span > 0 else max(abs(market_high) * .05, 1)
        market_floor = market_low - market_padding
        market_ceiling = market_high + market_padding
        market_scale = alt.Scale(
            domain=[market_floor, market_ceiling],
            zero=False,
            nice=False,
        )
        market_nearest = alt.selection_point(
            nearest=True,
            on="pointerover",
            fields=["date"],
            empty=False,
            clear="pointerout",
        )
        market_base = alt.Chart(selected_market).encode(
            x=alt.X("date:T", title=None, axis=alt.Axis(format="%y.%m", labelAngle=0, tickCount=9))
        )
        market_area = market_base.mark_area(color=theme.EXPORT, opacity=.08).encode(
            y=alt.Y(
                "value:Q",
                title=selected_market_meta["unit"],
                scale=market_scale,
            ),
            y2=alt.Y2(datum=market_floor),
        )
        market_line = market_base.mark_line(color=theme.EXPORT, strokeWidth=2.4).encode(
            y=alt.Y("value:Q", title=selected_market_meta["unit"], scale=market_scale),
            tooltip=[
                alt.Tooltip("date:T", title="관측일", format="%Y.%m.%d"),
                alt.Tooltip("value:Q", title=selected_market_name, format=selected_market_meta["format"]),
            ],
        )
        market_selectors = market_base.mark_point(opacity=0).add_params(market_nearest)
        market_points = market_line.mark_point(size=68, filled=True).encode(
            opacity=alt.condition(market_nearest, alt.value(1), alt.value(0))
        )
        market_rule = market_base.mark_rule(color=theme.INK, opacity=.24).encode(
            opacity=alt.condition(market_nearest, alt.value(.45), alt.value(0))
        ).transform_filter(market_nearest)
        latest_market_point = selected_market.tail(1)
        market_last_point = alt.Chart(latest_market_point).mark_point(
            color=theme.BRAND_RED, size=75, filled=True
        ).encode(x="date:T", y="value:Q")
        market_last_label = alt.Chart(latest_market_point).mark_text(
            align="left", dx=8, color=theme.BRAND_RED, font="IBM Plex Mono", fontSize=11
        ).encode(
            x="date:T",
            y="value:Q",
            text=alt.Text("value:Q", format=selected_market_meta["format"]),
        )
        market_chart = (
            market_area
            + market_line
            + market_selectors
            + market_points
            + market_rule
            + market_last_point
            + market_last_label
        ).properties(height=310, padding={"right": 54})
        st.altair_chart(chart_style(market_chart), width="stretch")
        st.caption(
            f"Source: FRED · {selected_market_meta['description']} · "
            f"{selected_market_meta['frequency']} · 최신 관측 {selected_snapshot['latest_date']} · 변동 확인용 집중 축"
        )

with amount_tab:
    chart_col, insight_col = st.columns([2.15, 1], gap="large")
    with chart_col:
        st.markdown("<div class='chart-heading'>월별 수출입 신고금액 추이</div>", unsafe_allow_html=True)
        st.markdown(
            "<div class='chart-subtitle'>관세청 신고금액 기준 · 실선은 수출, 파선은 수입 · 단위 USD</div>",
            unsafe_allow_html=True,
        )
        trend_long = periods.melt(
            id_vars=["period_date", "label"],
            value_vars=["export_usd", "import_usd"],
            var_name="flow_key",
            value_name="value",
        )
        trend_long["구분"] = trend_long["flow_key"].map(
            {"export_usd": "수출", "import_usd": "수입"}
        )
        trend_chart = (
            alt.Chart(trend_long)
            .mark_line(strokeWidth=2.5)
            .encode(
                x=alt.X("period_date:T", title=None, axis=alt.Axis(format="%y.%m", labelAngle=0, tickCount=8)),
                y=alt.Y("value:Q", title="금액 (USD)", axis=alt.Axis(format="~s"), scale=alt.Scale(zero=True)),
                color=alt.Color(
                    "구분:N",
                    scale=alt.Scale(domain=["수출", "수입"], range=[theme.EXPORT, theme.IMPORT]),
                    legend=alt.Legend(title=None, orient="top", direction="horizontal"),
                ),
                strokeDash=alt.StrokeDash(
                    "구분:N", scale=alt.Scale(domain=["수출", "수입"], range=[[1, 0], [6, 4]]), legend=None
                ),
                tooltip=[
                    alt.Tooltip("label:N", title="기간"),
                    alt.Tooltip("구분:N"),
                    alt.Tooltip("value:Q", title="금액", format="$,.0f"),
                ],
            )
            .properties(height=350)
        )
        st.altair_chart(chart_style(trend_chart), width="stretch")

    with insight_col:
        st.markdown("<div class='chart-heading'>핵심 관찰</div>", unsafe_allow_html=True)
        st.markdown("<div class='chart-subtitle'>수치 변화의 빠른 스캔</div>", unsafe_allow_html=True)
        yoy_text, _ = format_rate(summary["export_yoy"])
        theme.insight_card(
            "Momentum",
            f"최근 월 수출 {yoy_text}",
            "전년 동월 비교가 가능한 경우 같은 계절의 기준점과 비교합니다.",
        )
        theme.insight_card(
            "Peak",
            f"수출 고점 {summary['peak_export_period']}",
            f"월 수출액 {format_money(summary['peak_export'])}로 조회 기간 중 가장 높았습니다.",
        )
        theme.insight_card(
            "Balance",
            f"적자 월 {summary['deficit_months']}개",
            f"전체 {summary['months']}개월 중 무역수지가 0 미만인 월의 수입니다.",
        )

    amount_yoy = periods[["period_date", "label", "export_usd"]].copy()
    amount_yoy["yoy"] = amount_yoy["export_usd"].pct_change(12) * 100
    amount_yoy = amount_yoy.dropna(subset=["yoy"])
    if not amount_yoy.empty:
        st.markdown("<div class='chart-heading'>수출 신고금액 전년동월 증감률</div>", unsafe_allow_html=True)
        st.markdown(
            "<div class='chart-subtitle'>계절성을 통제한 월별 성장 모멘텀 · 단위 %</div>",
            unsafe_allow_html=True,
        )
        amount_yoy_chart = (
            alt.Chart(amount_yoy)
            .mark_bar(size=12, cornerRadiusEnd=2)
            .encode(
                x=alt.X("period_date:T", title=None, axis=alt.Axis(format="%y.%m", labelAngle=0, tickCount=9)),
                y=alt.Y("yoy:Q", title="전년동월 대비 (%)"),
                color=alt.condition("datum.yoy >= 0", alt.value(theme.EXPORT), alt.value(theme.IMPORT)),
                tooltip=[
                    alt.Tooltip("label:N", title="기간"),
                    alt.Tooltip("yoy:Q", title="증감률", format="+.1f"),
                ],
            )
            .properties(height=190)
        )
        amount_zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=theme.INK, opacity=.4).encode(y="y:Q")
        st.altair_chart(chart_style(amount_yoy_chart + amount_zero), width="stretch")

with weight_tab:
    weight_growth_note, weight_growth_tone = format_rate(
        summary["recent_12_wgt_growth"], prefix="직전 12개월 대비 "
    )
    weight_mom_note, weight_mom_tone = format_rate(
        summary["export_wgt_mom"], prefix="전월 대비 "
    )
    st.markdown(
        "<div class='analysis-band'><strong>물량 성과 요약</strong>"
        "<span>VOLUME LENS · DECLARED NET WEIGHT</span></div>",
        unsafe_allow_html=True,
    )
    weight_kpis = st.columns(4)
    with weight_kpis[0]:
        theme.kpi_card(
            "V1", "수출 중량 누계", format_weight(summary["total_export_wgt"]),
            weight_growth_note, weight_growth_tone,
        )
    with weight_kpis[1]:
        theme.kpi_card(
            "V2", "수입 중량 누계", format_weight(summary["total_import_wgt"]), "조회 기간 합계"
        )
    with weight_kpis[2]:
        theme.kpi_card(
            "V3", f"최근 월 수출중량 · {summary['latest_period']}",
            format_weight(summary["latest_export_wgt"]), weight_mom_note, weight_mom_tone,
        )
    with weight_kpis[3]:
        theme.kpi_card(
            "V4", f"최근 월 수입중량 · {summary['latest_period']}",
            format_weight(summary["latest_import_wgt"]), "신고 순중량 기준",
        )

    st.write("")
    weight_chart_col, weight_insight_col = st.columns([2.15, 1], gap="large")
    with weight_chart_col:
        st.markdown("<div class='chart-heading'>월별 수출입 중량 추이</div>", unsafe_allow_html=True)
        st.markdown(
            "<div class='chart-subtitle'>신고 순중량 기준 · 실선은 수출, 파선은 수입 · 단위 kg</div>",
            unsafe_allow_html=True,
        )
        weight_long = periods.melt(
            id_vars=["period_date", "label"],
            value_vars=["export_wgt", "import_wgt"],
            var_name="flow_key",
            value_name="weight",
        )
        weight_long["구분"] = weight_long["flow_key"].map(
            {"export_wgt": "수출 중량", "import_wgt": "수입 중량"}
        )
        weight_chart = (
            alt.Chart(weight_long)
            .mark_line(strokeWidth=2.5)
            .encode(
                x=alt.X("period_date:T", title=None, axis=alt.Axis(format="%y.%m", labelAngle=0, tickCount=8)),
                y=alt.Y("weight:Q", title="중량 (kg)", axis=alt.Axis(format="~s"), scale=alt.Scale(zero=True)),
                color=alt.Color(
                    "구분:N",
                    scale=alt.Scale(
                        domain=["수출 중량", "수입 중량"], range=[theme.EXPORT, theme.IMPORT]
                    ),
                    legend=alt.Legend(title=None, orient="top", direction="horizontal"),
                ),
                strokeDash=alt.StrokeDash(
                    "구분:N",
                    scale=alt.Scale(domain=["수출 중량", "수입 중량"], range=[[1, 0], [6, 4]]),
                    legend=None,
                ),
                tooltip=[
                    alt.Tooltip("label:N", title="기간"),
                    alt.Tooltip("구분:N"),
                    alt.Tooltip("weight:Q", title="중량(kg)", format=",.0f"),
                ],
            )
            .properties(height=350)
        )
        st.altair_chart(chart_style(weight_chart), width="stretch")

    with weight_insight_col:
        st.markdown("<div class='chart-heading'>물량 관찰</div>", unsafe_allow_html=True)
        st.markdown("<div class='chart-subtitle'>금액과 분리한 실물 흐름 진단</div>", unsafe_allow_html=True)
        weight_yoy_text, _ = format_rate(summary["export_wgt_yoy"])
        latest_unit = periods.iloc[-1]["export_unit_usd"]
        latest_unit_text = f"${latest_unit:,.2f}/kg" if pd.notna(latest_unit) else "산출 불가"
        theme.insight_card(
            "Volume momentum",
            f"최근 월 수출중량 {weight_yoy_text}",
            "전년 동월과 비교해 계절성을 반영한 물량 방향을 확인합니다.",
        )
        theme.insight_card(
            "Volume peak",
            f"수출중량 고점 {summary['peak_export_wgt_period']}",
            f"월 수출중량 {format_weight(summary['peak_export_wgt'])}로 조회 기간 중 가장 높았습니다.",
        )
        theme.insight_card(
            "Unit value",
            f"최근 월 수출 신고단가 {latest_unit_text}",
            "금액 변화가 물량 또는 단가 중 어디에서 발생했는지 함께 해석합니다.",
        )

    weight_yoy = periods[["period_date", "label", "export_wgt"]].copy()
    weight_yoy["yoy"] = weight_yoy["export_wgt"].pct_change(12) * 100
    weight_yoy = weight_yoy.dropna(subset=["yoy"])
    if not weight_yoy.empty:
        st.markdown("<div class='chart-heading'>수출 중량 전년동월 증감률</div>", unsafe_allow_html=True)
        st.markdown(
            "<div class='chart-subtitle'>실물 물동량의 월별 성장 모멘텀 · 단위 %</div>",
            unsafe_allow_html=True,
        )
        weight_yoy_chart = (
            alt.Chart(weight_yoy)
            .mark_bar(size=12, cornerRadiusEnd=2)
            .encode(
                x=alt.X("period_date:T", title=None, axis=alt.Axis(format="%y.%m", labelAngle=0, tickCount=9)),
                y=alt.Y("yoy:Q", title="전년동월 대비 (%)"),
                color=alt.condition("datum.yoy >= 0", alt.value(theme.EXPORT), alt.value(theme.IMPORT)),
                tooltip=[
                    alt.Tooltip("label:N", title="기간"),
                    alt.Tooltip("yoy:Q", title="증감률", format="+.1f"),
                ],
            )
            .properties(height=190)
        )
        weight_zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=theme.INK, opacity=.4).encode(y="y:Q")
        st.altair_chart(chart_style(weight_yoy_chart + weight_zero), width="stretch")

with balance_tab:
    left_chart, right_chart = st.columns(2, gap="large")
    with left_chart:
        st.markdown("<div class='chart-heading'>월별 무역수지</div>", unsafe_allow_html=True)
        st.markdown(
            "<div class='chart-subtitle'>0선 위는 흑자, 아래는 적자 · 단위 USD</div>",
            unsafe_allow_html=True,
        )
        balance_chart = (
            alt.Chart(periods)
            .mark_bar(size=11, cornerRadiusEnd=2)
            .encode(
                x=alt.X("period_date:T", title=None, axis=alt.Axis(format="%y.%m", labelAngle=0, tickCount=7)),
                y=alt.Y("balance_usd:Q", title="무역수지 (USD)", axis=alt.Axis(format="~s")),
                color=alt.condition(
                    "datum.balance_usd >= 0", alt.value(theme.EXPORT), alt.value(theme.IMPORT)
                ),
                tooltip=[
                    alt.Tooltip("label:N", title="기간"),
                    alt.Tooltip("balance_usd:Q", title="무역수지", format="$,.0f"),
                ],
            )
            .properties(height=330)
        )
        zero_rule = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=theme.INK, opacity=.45).encode(y="y:Q")
        st.altair_chart(chart_style(balance_chart + zero_rule), width="stretch")

    with right_chart:
        st.markdown("<div class='chart-heading'>kg당 신고단가 추이</div>", unsafe_allow_html=True)
        st.markdown(
            "<div class='chart-subtitle'>신고금액 ÷ 신고중량 · 품질·규격·운임 차이를 포함할 수 있음</div>",
            unsafe_allow_html=True,
        )
        unit_long = periods.melt(
            id_vars=["period_date", "label"],
            value_vars=["export_unit_usd", "import_unit_usd"],
            var_name="unit_key",
            value_name="unit_value",
        ).dropna(subset=["unit_value"])
        unit_long["구분"] = unit_long["unit_key"].map(
            {"export_unit_usd": "수출 단가", "import_unit_usd": "수입 단가"}
        )
        if unit_long.empty:
            st.info("신고중량이 없어 kg당 단가를 계산할 수 없습니다.")
        else:
            unit_chart = (
                alt.Chart(unit_long)
                .mark_line(strokeWidth=2.2)
                .encode(
                    x=alt.X("period_date:T", title=None, axis=alt.Axis(format="%y.%m", labelAngle=0, tickCount=7)),
                    y=alt.Y("unit_value:Q", title="USD / kg", scale=alt.Scale(zero=False)),
                    color=alt.Color(
                        "구분:N",
                        scale=alt.Scale(
                            domain=["수출 단가", "수입 단가"], range=[theme.EXPORT, theme.IMPORT]
                        ),
                        legend=alt.Legend(title=None, orient="top"),
                    ),
                    strokeDash=alt.StrokeDash(
                        "구분:N",
                        scale=alt.Scale(domain=["수출 단가", "수입 단가"], range=[[1, 0], [6, 4]]),
                        legend=None,
                    ),
                    tooltip=[
                        alt.Tooltip("label:N", title="기간"),
                        alt.Tooltip("구분:N"),
                        alt.Tooltip("unit_value:Q", title="단가", format="$,.2f"),
                    ],
                )
                .properties(height=330)
            )
            st.altair_chart(chart_style(unit_chart), width="stretch")

with data_tab:
    theme.section_title("조회 데이터", "분석용 월 집계와 API 원자료를 구분해 확인하고 내려받을 수 있습니다.")
    view_mode = st.radio("표 기준", ["월별 집계", "API 원자료"], horizontal=True)
    if view_mode == "월별 집계":
        display_table = periods[
            [
                "label", "export_usd", "export_wgt", "import_usd", "import_wgt",
                "balance_usd", "export_unit_usd", "import_unit_usd",
            ]
        ].rename(
            columns={
                "label": "기간",
                "export_usd": "수출액(USD)",
                "export_wgt": "수출중량(kg)",
                "import_usd": "수입액(USD)",
                "import_wgt": "수입중량(kg)",
                "balance_usd": "무역수지(USD)",
                "export_unit_usd": "수출단가(USD/kg)",
                "import_unit_usd": "수입단가(USD/kg)",
            }
        )
    else:
        raw_columns = [
            col for col in [
                "period", "hs_cd", "item_name", "country", "country_cd",
                "export_usd", "export_wgt", "import_usd", "import_wgt", "balance_usd",
            ] if col in raw.columns
        ]
        display_table = raw[raw_columns].rename(
            columns={
                "period": "기간", "hs_cd": "HS", "item_name": "품목", "country": "국가",
                "country_cd": "국가코드", "export_usd": "수출액(USD)",
                "export_wgt": "수출중량(kg)", "import_usd": "수입액(USD)",
                "import_wgt": "수입중량(kg)", "balance_usd": "무역수지(USD)",
            }
        )

    st.dataframe(
        display_table,
        width="stretch",
        hide_index=True,
        column_config={
            col: st.column_config.NumberColumn(format="%,.2f" if "단가" in col else "%,.0f")
            for col in display_table.columns if display_table[col].dtype.kind in "fi"
        },
    )
    csv_buffer = io.StringIO()
    display_table.to_csv(csv_buffer, index=False)
    st.download_button(
        "CSV 내려받기",
        data=csv_buffer.getvalue().encode("utf-8-sig"),
        file_name=f"korea_trade_{meta['hs']}_{COUNTRY_CODES.get(meta['country'], 'all')}_{meta['start']}_{meta['end']}.csv",
        mime="text/csv",
    )

with method_tab:
    theme.section_title("지표 정의와 주의사항", "숫자를 비교하기 전에 반드시 확인해야 할 산식과 데이터 범위입니다.")
    method_left, method_right = st.columns(2, gap="large")
    with method_left:
        st.markdown(
            """
            **핵심 지표 정의**

            - **수출액**: 수출신고 기준 FOB 금액(USD)
            - **수입액**: 수입신고 기준 CIF 금액(USD)
            - **무역수지**: 수출액 − 수입액
            - **kg당 신고단가**: 신고금액 ÷ 신고중량
            - **최근 12개월 증감률**: 최근 12개월 합계와 직전 12개월 합계 비교
            - 화면의 금액은 관세청 신고금액이며 KCC글라스의 회계상 매출액과는 다릅니다.
            - **비교지수**: 선택 구간의 첫 유효 관측값을 100으로 환산한 상대 변화입니다.
            """
        )
    with method_right:
        st.markdown(
            """
            **해석 시 주의**

            - FOB와 CIF의 가격 기준이 달라 수출·수입 단가의 직접 비교에는 한계가 있습니다.
            - HS 2·4단위 조회는 여러 세부 품목을 포함하므로 월별로 합산합니다.
            - 최근 1~2개월 수치는 신고 정정과 반영 시차로 변경될 수 있습니다.
            - 신고단가는 품질, 규격, 운임, 환율과 품목 구성 변화의 영향을 함께 받습니다.
            - FRED 시장지표는 환율·유가가 일간, 주택착공이 월간이며 동일 시점의 실시간 값이 아닙니다.
            - 시장 신호는 규칙 기반 보조 해석이며 인과관계나 미래 실적을 의미하지 않습니다.
            """
        )
    st.info("이 대시보드는 시장 탐색과 1차 판단을 위한 도구입니다. 투자·계약 판단 전에는 원자료와 품목 분류를 재확인하세요.")

st.markdown(
    "<div class='source-note'>SOURCE · 공공데이터포털 / 관세청 품목별 국가별 수출입실적 · FRED 시장지표 &nbsp;·&nbsp; "
    "REFRESH · 무역 월간 / 외부지표 6시간 캐시, 지표별 일간·월간 관측 &nbsp;·&nbsp; "
    "METHOD · 월별 행 집계, 총계 행 제외, 무역수지 재계산, 비교구간 시작=100</div>",
    unsafe_allow_html=True,
)

"""한국 수출입 무역통계 인텔리전스 대시보드."""

from __future__ import annotations

import io
from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

import sample_data
import theme
from country_codes import COUNTRY_CODES
from hs_presets import HS_PRESETS
from trade_data import (
    TradeDataError,
    analysis_summary,
    fetch_trade,
    normalize_key,
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


def format_rate(value: float | None, *, prefix: str = "") -> tuple[str, str]:
    if value is None:
        return "비교 기간 부족", "neutral"
    sign = "+" if value >= 0 else ""
    tone = "positive" if value >= 0 else "negative"
    return f"{prefix}{sign}{value:,.1f}%", tone


def get_deployed_key() -> str:
    try:
        return str(st.secrets.get("DATA_GO_KR_SERVICE_KEY", "")).strip()
    except Exception:
        return ""


@st.cache_data(ttl=3600, show_spinner=False)
def cached_trade(
    service_key: str,
    hs_code: str,
    country_code: str,
    start_ym: str,
    end_ym: str,
) -> pd.DataFrame:
    return fetch_trade(service_key, hs_code, country_code, start_ym, end_ym)


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

with st.sidebar:
    st.markdown("<div class='sidebar-brand'>TRADE / INTELLIGENCE</div>", unsafe_allow_html=True)
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
            placeholder="배포 환경에 키가 없을 때만 입력",
            disabled=data_mode == "샘플로 둘러보기",
            help="일반 인증키(Decoding)를 사용합니다. 입력값은 세션 밖에 저장하지 않습니다.",
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
    elif data_mode == "관세청 API 조회":
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
    """
    <div class="masthead">
      <div class="brand-lockup">
        <div class="masthead-mark">KT</div>
        <div>
          <div class="eyebrow">Korea Trade Intelligence</div>
          <h1>한국 수출입 무역 인텔리전스</h1>
          <p>관세청 통관실적을 품목·시장·시간 관점에서 읽는 월별 분석 대시보드</p>
        </div>
      </div>
      <div class="masthead-meta">
        <div class="eyebrow">Decision support</div>
        <div class="meta-copy">시장 모니터링 · 사업 검토 · 원자료 추출</div>
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
    "<div class='trust-item'><div class='trust-label'>Units</div><div class='trust-value'>USD · kg</div></div>"
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
query_title = f"HS {meta['hs']} · {meta['label']}"
theme.section_title(
    query_title,
    f"상대국 {meta['country']} · {summary['months']}개월 관측 · 최신 관측월 {summary['latest_period']}",
)

growth_note, growth_tone = format_rate(summary["recent_12_growth"], prefix="직전 12개월 대비 ")
mom_note, mom_tone = format_rate(summary["export_mom"], prefix="전월 대비 ")
balance_tone = "positive" if summary["balance"] >= 0 else "negative"

kpi_cols = st.columns(4)
with kpi_cols[0]:
    theme.kpi_card("01", "수출 누계", format_money(summary["total_export"]), growth_note, growth_tone)
with kpi_cols[1]:
    theme.kpi_card("02", "수입 누계", format_money(summary["total_import"]), "조회 기간 합계")
with kpi_cols[2]:
    balance_label = "흑자" if summary["balance"] >= 0 else "적자"
    theme.kpi_card("03", "무역수지", format_money(summary["balance"]), balance_label, balance_tone)
with kpi_cols[3]:
    theme.kpi_card("04", f"최근 월 수출 · {summary['latest_period']}", format_money(summary["latest_export"]), mom_note, mom_tone)

st.write("")
overview_tab, balance_tab, data_tab, method_tab = st.tabs(
    ["시장 흐름", "수지 · 단가", "데이터", "해석 기준"]
)

with overview_tab:
    chart_col, insight_col = st.columns([2.15, 1], gap="large")
    with chart_col:
        st.markdown("<div class='chart-heading'>월별 수출입 금액 추이</div>", unsafe_allow_html=True)
        st.markdown(
            "<div class='chart-subtitle'>동일 축 비교 · 실선은 수출, 파선은 수입 · 단위 USD</div>",
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
        st.altair_chart(trend_chart, width="stretch")

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
        st.altair_chart(balance_chart + zero_rule, width="stretch")

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
            st.altair_chart(unit_chart, width="stretch")

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
            """
        )
    st.info("이 대시보드는 시장 탐색과 1차 판단을 위한 도구입니다. 투자·계약 판단 전에는 원자료와 품목 분류를 재확인하세요.")

st.markdown(
    "<div class='source-note'>SOURCE · 공공데이터포털 / 관세청 품목별 국가별 수출입실적 &nbsp;·&nbsp; "
    "REFRESH · 통상 매월 15일경 전월분 현행화 &nbsp;·&nbsp; "
    "METHOD · 월별 행 집계, 총계 행 제외, 무역수지 재계산</div>",
    unsafe_allow_html=True,
)

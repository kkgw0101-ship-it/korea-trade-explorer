"""
한국 수출입 무역통계 탐색기
Korea Trade Statistics Explorer

관세청 '품목별 국가별 수출입실적' 오픈 API를 이용해
HS Code 기준 수출입 추이를 조회하고 비교하는 개인 프로젝트.

데이터 출처: 공공데이터포털 (data.go.kr) — 관세청_품목별 국가별 수출입실적
"""

import io
import time
import xml.etree.ElementTree as ET
from datetime import date

import pandas as pd
import requests
import streamlit as st

import theme
from country_codes import COUNTRY_CODES
from hs_presets import HS_PRESETS

API_URL = "http://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"

# 관세청 응답 필드 → 내부 컬럼명
FIELD_MAP = {
    "year": "period",
    "statKor": "name_kr",
    "statCd": "stat_cd",
    "hsCd": "hs_cd",
    "expDlr": "export_usd_k",
    "expWgt": "export_wgt",
    "impDlr": "import_usd_k",
    "impWgt": "import_wgt",
    "balPayments": "balance_usd_k",
}

NUMERIC_COLS = [
    "export_usd_k",
    "export_wgt",
    "import_usd_k",
    "import_wgt",
    "balance_usd_k",
]


# ─────────────────────────────────────────────────────────────
# 데이터 조회
# ─────────────────────────────────────────────────────────────

def _to_number(raw):
    """관세청 응답의 숫자 문자열을 float으로. 콤마·공백·빈값 처리."""
    if raw is None:
        return 0.0
    text = str(raw).strip().replace(",", "")
    if text in ("", "-", "null", "None"):
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse_response(xml_text):
    """
    관세청 XML 응답을 DataFrame으로 변환.

    스키마가 바뀌어도 죽지 않도록 <item>의 모든 자식 태그를 일단 수집한 뒤
    알려진 필드만 매핑한다. 알 수 없는 태그는 원래 이름 그대로 남긴다.
    """
    root = ET.fromstring(xml_text)

    result_code = root.findtext(".//resultCode")
    result_msg = root.findtext(".//resultMsg") or ""
    if result_code is not None and result_code.strip() not in ("00", "0"):
        raise RuntimeError(f"[{result_code.strip()}] {result_msg.strip()}")

    rows = []
    for item in root.iter("item"):
        raw = {child.tag: (child.text or "").strip() for child in item}
        row = {}
        for tag, value in raw.items():
            row[FIELD_MAP.get(tag, tag)] = value
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = df[col].map(_to_number)
        else:
            df[col] = 0.0

    if "balance_usd_k" not in df.columns or df["balance_usd_k"].eq(0).all():
        df["balance_usd_k"] = df["export_usd_k"] - df["import_usd_k"]

    return df


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_trade(service_key, hs_code, start_ym, end_ym, country_code=""):
    """관세청 API 호출. 결과는 1시간 캐시 (월 1회 갱신되는 데이터라 넉넉히)."""
    params = {
        "serviceKey": service_key,
        "strtYymm": start_ym,
        "endYymm": end_ym,
        "hsSgn": hs_code,
    }
    if country_code:
        params["cntyCd"] = country_code

    last_error = None
    for attempt in range(3):
        try:
            resp = requests.get(API_URL, params=params, timeout=20)
            resp.raise_for_status()
            return parse_response(resp.text)
        except ET.ParseError:
            raise RuntimeError(
                "응답을 해석하지 못했습니다. 인증키가 올바른지, "
                "활용 신청이 승인되었는지 확인해 주세요."
            )
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(f"API 요청에 실패했습니다: {last_error}")


def split_total_and_periods(df):
    """
    관세청 응답에는 기간별 행과 '총계' 행이 섞여 있다.
    period가 숫자(YYYYMM 또는 YYYY)인 행만 시계열로 쓰고 나머지는 합계로 분리.
    """
    if df.empty or "period" not in df.columns:
        return df, pd.DataFrame()

    is_period = df["period"].astype(str).str.fullmatch(r"\d{4}(\d{2})?")
    return df[is_period].copy(), df[~is_period].copy()


def label_period(value):
    """202601 → 26년 1월, 2026 → 2026년"""
    text = str(value)
    if len(text) == 6:
        return f"{text[2:4]}년 {int(text[4:]):d}월"
    if len(text) == 4:
        return f"{text}년"
    return text


# ─────────────────────────────────────────────────────────────
# 화면
# ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="한국 수출입 무역통계 탐색기",
    page_icon="⚓",
    layout="wide",
)
theme.inject()

st.markdown(
    """
    <div class="masthead">
      <div class="masthead-mark">HS</div>
      <div>
        <h1>한국 수출입 무역통계 탐색기</h1>
        <p>관세청 통관실적 기준 · HS Code별 수출입 추이 조회</p>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### 조회 조건")

    service_key = st.text_input(
        "공공데이터포털 인증키",
        type="password",
        help="data.go.kr에서 '관세청_품목별 국가별 수출입실적' 활용 신청 후 발급받은 "
             "일반 인증키(Decoding)를 넣으세요. 비워두면 샘플 데이터로 화면을 둘러볼 수 있습니다.",
    )

    st.divider()

    preset_names = ["직접 입력"] + [f"{p['code']} · {p['label']}" for p in HS_PRESETS]
    picked = st.selectbox("품목 (HS Code)", preset_names)

    if picked == "직접 입력":
        hs_code = st.text_input("HS Code", value="3918", help="2 · 4 · 6 · 10단위 모두 가능")
        hs_label = ""
    else:
        preset = HS_PRESETS[preset_names.index(picked) - 1]
        hs_code = preset["code"]
        hs_label = preset["label"]
        st.caption(preset["note"])

    country_names = ["전체 국가"] + list(COUNTRY_CODES.keys())
    country_name = st.selectbox("상대국", country_names)
    country_code = COUNTRY_CODES.get(country_name, "")

    today = date.today()
    default_start = date(today.year - 3, 1, 1)

    col_a, col_b = st.columns(2)
    with col_a:
        start_year = st.number_input(
            "시작 연도", min_value=2000, max_value=today.year, value=default_start.year
        )
        start_month = st.number_input("시작 월", min_value=1, max_value=12, value=1)
    with col_b:
        end_year = st.number_input(
            "종료 연도", min_value=2000, max_value=today.year, value=today.year
        )
        end_month = st.number_input(
            "종료 월", min_value=1, max_value=12, value=max(1, today.month - 1)
        )

    start_ym = f"{start_year:04d}{start_month:02d}"
    end_ym = f"{end_year:04d}{end_month:02d}"

    run = st.button("조회", type="primary", width="stretch")

    st.divider()
    st.caption(
        "금액 단위는 천 달러(US$1,000), 중량은 kg입니다. "
        "수출은 FOB, 수입은 CIF 기준이며 매월 15일경 전월까지 자료가 현행화됩니다."
    )


if start_ym > end_ym:
    st.error("시작 시점이 종료 시점보다 늦습니다. 기간을 다시 선택해 주세요.")
    st.stop()

if not run and "df" not in st.session_state:
    st.info(
        "왼쪽에서 품목과 기간을 고르고 **조회**를 누르세요. "
        "인증키 없이 눌러도 샘플 데이터로 화면 구성을 볼 수 있습니다."
    )
    st.stop()

if run:
    if service_key.strip():
        try:
            with st.spinner("관세청 통계를 불러오는 중"):
                df = fetch_trade(
                    service_key.strip(), hs_code.strip(), start_ym, end_ym, country_code
                )
            st.session_state["demo"] = False
        except RuntimeError as exc:
            st.error(str(exc))
            st.stop()
    else:
        import sample_data

        df = sample_data.build(start_ym, end_ym, hs_code.strip())
        st.session_state["demo"] = True

    st.session_state["df"] = df
    st.session_state["meta"] = {
        "hs": hs_code.strip(),
        "label": hs_label,
        "country": country_name,
        "start": start_ym,
        "end": end_ym,
    }

df = st.session_state.get("df", pd.DataFrame())
meta = st.session_state.get("meta", {})
is_demo = st.session_state.get("demo", False)

if df.empty:
    st.warning(
        "해당 조건에 자료가 없습니다. HS Code 자릿수를 줄이거나 기간을 넓혀 보세요."
    )
    st.stop()

if is_demo:
    st.markdown(
        '<div class="demo-flag">샘플 데이터입니다. 실제 통계를 보려면 '
        '왼쪽에 인증키를 입력하세요.</div>',
        unsafe_allow_html=True,
    )

periods, totals = split_total_and_periods(df)

if periods.empty:
    periods = df.copy()

periods = periods.sort_values("period")
periods["label"] = periods["period"].map(label_period)

total_export = periods["export_usd_k"].sum()
total_import = periods["import_usd_k"].sum()
balance = total_export - total_import

heading = f"HS {meta.get('hs', '')}"
if meta.get("label"):
    heading += f" · {meta['label']}"
st.markdown(
    f"<div class='section-head'>{heading}"
    f"<span>{meta.get('country', '')} · "
    f"{label_period(meta.get('start', ''))} ~ {label_period(meta.get('end', ''))}</span></div>",
    unsafe_allow_html=True,
)

# 무역수지 저울 — 수출과 수입을 중심선 기준 반대 방향으로 그린다
theme.balance_scale(total_export, total_import)

col1, col2, col3 = st.columns(3)
col1.metric("수출 누계", f"{total_export/1000:,.1f}백만 $")
col2.metric("수입 누계", f"{total_import/1000:,.1f}백만 $")
col3.metric(
    "무역수지",
    f"{balance/1000:,.1f}백만 $",
    delta="흑자" if balance >= 0 else "적자",
    delta_color="normal" if balance >= 0 else "inverse",
)

st.markdown("<div class='rule'></div>", unsafe_allow_html=True)

tab_trend, tab_balance, tab_table = st.tabs(["추이", "수지", "원자료"])

with tab_trend:
    chart_df = periods.set_index("label")[["export_usd_k", "import_usd_k"]]
    chart_df.columns = ["수출", "수입"]
    st.line_chart(
        chart_df,
        height=380,
        color=[theme.EXPORT, theme.IMPORT],
    )
    st.caption("단위: 천 달러")

    if len(periods) >= 2:
        first, last = periods.iloc[0], periods.iloc[-1]
        if first["export_usd_k"] > 0:
            change = (last["export_usd_k"] / first["export_usd_k"] - 1) * 100
            direction = "늘었습니다" if change >= 0 else "줄었습니다"
            st.markdown(
                f"수출액은 {first['label']} 대비 {last['label']}에 "
                f"**{abs(change):,.1f}%** {direction}."
            )

with tab_balance:
    bal_df = periods.set_index("label")[["balance_usd_k"]]
    bal_df.columns = ["무역수지"]
    st.bar_chart(bal_df, height=380, color=theme.INK)
    st.caption("단위: 천 달러 · 0보다 크면 흑자")

    deficit_months = periods[periods["balance_usd_k"] < 0]
    if not deficit_months.empty:
        st.markdown(
            f"조회 기간 {len(periods)}개 구간 중 **{len(deficit_months)}개 구간**이 적자입니다."
        )

with tab_table:
    show_cols = [c for c in
                 ["label", "hs_cd", "name_kr", "export_usd_k", "export_wgt",
                  "import_usd_k", "import_wgt", "balance_usd_k"]
                 if c in periods.columns]
    renamed = {
        "label": "기간",
        "hs_cd": "HS",
        "name_kr": "품목/국가",
        "export_usd_k": "수출액(천$)",
        "export_wgt": "수출중량(kg)",
        "import_usd_k": "수입액(천$)",
        "import_wgt": "수입중량(kg)",
        "balance_usd_k": "무역수지(천$)",
    }
    table = periods[show_cols].rename(columns=renamed)
    st.dataframe(table, width="stretch", hide_index=True)

    buffer = io.StringIO()
    table.to_csv(buffer, index=False)
    st.download_button(
        "CSV로 내려받기",
        buffer.getvalue().encode("utf-8-sig"),
        file_name=f"trade_{meta.get('hs','')}_{meta.get('start','')}_{meta.get('end','')}.csv",
        mime="text/csv",
    )

st.markdown(
    "<div class='footnote'>데이터 출처: 공공데이터포털 · 관세청 품목별 국가별 수출입실적</div>",
    unsafe_allow_html=True,
)

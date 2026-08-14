"""
한국 수출입 무역통계 탐색기
Korea Trade Statistics Explorer

관세청 '품목별 국가별 수출입실적' 오픈 API(nitemtrade)를 이용해
HS Code 기준 수출입 추이를 조회하고 비교하는 개인 프로젝트.

데이터 출처: 공공데이터포털 (data.go.kr) — 관세청_품목별 국가별 수출입실적
"""

import io
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date

import pandas as pd
import requests
import streamlit as st

import theme
from country_codes import COUNTRY_CODES
from hs_presets import HS_PRESETS

API_URL = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"

# 관세청 응답 필드 → 내부 컬럼명 (기술문서 c) 응답 메시지 명세 기준)
FIELD_MAP = {
    "year": "period",              # 기간 — "2016.01" 또는 "총계"
    "statCdCntnKor1": "country",   # 국가명
    "statCd": "country_cd",        # 국가코드
    "statKor": "item_name",        # 품목명
    "hsCd": "hs_cd",               # HS코드
    "expWgt": "export_wgt",        # 수출중량 (kg)
    "expDlr": "export_usd",        # 수출금액 (달러)
    "impWgt": "import_wgt",        # 수입중량 (kg)
    "impDlr": "import_usd",        # 수입금액 (달러)
    "balPayments": "balance_usd",  # 무역수지 (달러)
}

NUMERIC_COLS = ["export_wgt", "export_usd", "import_wgt", "import_usd", "balance_usd"]

PERIOD_RE = re.compile(r"^(\d{4})[.\-/]?(\d{2})$")


# ─────────────────────────────────────────────────────────────
# 데이터 조회
# ─────────────────────────────────────────────────────────────

def normalize_key(raw_key):
    """
    인증키가 이미 URL 인코딩된 상태(%2F, %2B 등)면 원래 값으로 되돌린다.
    requests가 파라미터를 다시 인코딩하므로, 인코딩된 키를 그대로 넘기면
    %가 %25로 이중 인코딩되어 인증에 실패한다.
    """
    key = raw_key.strip()
    if "%" in key:
        return urllib.parse.unquote(key)
    return key


def _to_number(raw):
    """관세청 응답의 숫자 문자열을 float으로. 콤마·하이픈·빈값 처리."""
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

    두 종류의 에러 형식을 모두 확인한다.
      - 포털 레벨: <OpenAPI_ServiceResponse><cmmMsgHeader><returnReasonCode>
      - 기관 레벨: <response><header><resultCode>
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        raise RuntimeError(
            "응답을 해석하지 못했습니다. 인증키가 올바른지, "
            "활용 신청이 승인되었는지 확인해 주세요."
        )

    reason_code = root.findtext(".//returnReasonCode")
    if reason_code:
        auth_msg = root.findtext(".//returnAuthMsg") or ""
        hint = {
            "30": "등록되지 않은 인증키입니다. 발급 직후라면 반영에 최대 1시간이 걸립니다.",
            "22": "일일 요청 한도를 넘었습니다.",
            "31": "활용기간이 만료되었습니다.",
            "32": "등록되지 않은 IP입니다.",
        }.get(reason_code.strip(), "")
        raise RuntimeError(f"[{reason_code.strip()}] {auth_msg} {hint}".strip())

    result_code = root.findtext(".//resultCode")
    if result_code is not None and result_code.strip() not in ("00", "0"):
        result_msg = (root.findtext(".//resultMsg") or "").strip()
        raise RuntimeError(f"[{result_code.strip()}] {result_msg}")

    rows = []
    for item in root.iter("item"):
        raw = {child.tag: (child.text or "").strip() for child in item}
        rows.append({FIELD_MAP.get(tag, tag): value for tag, value in raw.items()})

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    for col in NUMERIC_COLS:
        df[col] = df[col].map(_to_number) if col in df.columns else 0.0

    return df


def year_chunks(start_ym, end_ym):
    """
    관세청 API는 조회기간이 1년을 넘으면 거부한다.
    연 단위로 잘라 (시작, 종료) 목록을 만든다.
    """
    start_y, start_m = int(start_ym[:4]), int(start_ym[4:])
    end_y, end_m = int(end_ym[:4]), int(end_ym[4:])

    chunks = []
    for year in range(start_y, end_y + 1):
        first = f"{year:04d}{start_m:02d}" if year == start_y else f"{year:04d}01"
        last = f"{year:04d}{end_m:02d}" if year == end_y else f"{year:04d}12"
        chunks.append((first, last))
    return chunks


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_chunk(service_key, hs_code, country_code, start_ym, end_ym):
    """구간 하나를 조회한다. 월 1회 갱신되는 데이터라 1시간 캐시."""
    params = {
        "serviceKey": service_key,
        "strtYymm": start_ym,
        "endYymm": end_ym,
        "cntyCd": country_code,
    }
    if hs_code:
        params["hsSgn"] = hs_code

    last_error = None
    for attempt in range(3):
        try:
            resp = requests.get(API_URL, params=params, timeout=20)
            resp.raise_for_status()
            return parse_response(resp.text)
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(f"API 요청에 실패했습니다: {last_error}")


def fetch_trade(service_key, hs_code, country_code, start_ym, end_ym, progress=None):
    """기간을 연 단위로 나눠 조회한 뒤 하나로 합친다."""
    chunks = year_chunks(start_ym, end_ym)
    frames = []

    for index, (first, last) in enumerate(chunks):
        if progress:
            progress.progress(
                (index + 1) / len(chunks),
                text=f"{first[:4]}년 자료를 불러오는 중 ({index + 1}/{len(chunks)})",
            )
        frames.append(fetch_chunk(service_key, hs_code, country_code, first, last))
        if index < len(chunks) - 1:
            time.sleep(0.2)  # 초당 30건 제한을 넉넉히 피한다

    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def split_periods(df):
    """기간별 행만 남기고 '총계' 행은 버린다 (구간을 합치면 총계가 중복되므로)."""
    if df.empty or "period" not in df.columns:
        return df
    keep = df["period"].astype(str).str.match(PERIOD_RE)
    return df[keep].copy()


def label_period(value):
    """2016.01 → 16년 1월"""
    match = PERIOD_RE.match(str(value).strip())
    if match:
        year, month = match.groups()
        return f"{year[2:]}년 {int(month):d}월"
    return str(value)


def sort_key(value):
    match = PERIOD_RE.match(str(value).strip())
    return int(match.group(1) + match.group(2)) if match else 0


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
        help="마이페이지 → 개발계정에서 '일반 인증키(Decoding)'를 복사해 넣으세요. "
             "비워두면 샘플 데이터로 화면을 둘러볼 수 있습니다.",
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

    country_name = st.selectbox("상대국", list(COUNTRY_CODES.keys()))
    country_code = COUNTRY_CODES[country_name]

    today = date.today()

    col_a, col_b = st.columns(2)
    with col_a:
        start_year = st.number_input(
            "시작 연도", min_value=2000, max_value=today.year, value=today.year - 2
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
        "금액 단위는 달러, 중량은 kg입니다. 수출은 FOB, 수입은 CIF 기준이며 "
        "매월 15일경 전월까지 자료가 현행화됩니다. "
        "API가 한 번에 1년까지만 조회를 허용해, 여러 해는 연 단위로 나눠 요청합니다."
    )


if start_ym > end_ym:
    st.error("시작 시점이 종료 시점보다 늦습니다. 기간을 다시 선택해 주세요.")
    st.stop()

if not run and "df" not in st.session_state:
    st.info(
        "왼쪽에서 품목과 상대국, 기간을 고르고 **조회**를 누르세요. "
        "인증키 없이 눌러도 샘플 데이터로 화면 구성을 볼 수 있습니다."
    )
    st.stop()

if run:
    if service_key.strip():
        bar = st.progress(0.0, text="조회를 준비하는 중")
        try:
            df = fetch_trade(
                normalize_key(service_key),
                hs_code.strip(),
                country_code,
                start_ym,
                end_ym,
                progress=bar,
            )
            st.session_state["demo"] = False
        except RuntimeError as exc:
            bar.empty()
            st.error(str(exc))
            st.stop()
        bar.empty()
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
    st.warning("해당 조건에 자료가 없습니다. HS Code 자릿수를 줄이거나 기간을 넓혀 보세요.")
    st.stop()

if is_demo:
    st.markdown(
        '<div class="demo-flag">샘플 데이터입니다. 실제 통계를 보려면 '
        '왼쪽에 인증키를 입력하세요.</div>',
        unsafe_allow_html=True,
    )

periods = split_periods(df)
if periods.empty:
    st.warning("기간별 자료가 없습니다. 조회 조건을 바꿔 보세요.")
    st.stop()

periods = periods.assign(_sort=periods["period"].map(sort_key)).sort_values("_sort")
periods["label"] = periods["period"].map(label_period)

total_export = periods["export_usd"].sum()
total_import = periods["import_usd"].sum()
balance = total_export - total_import

heading = f"HS {meta.get('hs', '')}" if meta.get("hs") else "전체 품목"
if meta.get("label"):
    heading += f" · {meta['label']}"
elif "item_name" in periods.columns:
    name = str(periods["item_name"].iloc[0])
    if name and name != "-":
        heading += f" · {name}"

st.markdown(
    f"<div class='section-head'>{heading}"
    f"<span>{meta.get('country', '')} · "
    f"{label_period(meta.get('start', ''))} ~ {label_period(meta.get('end', ''))}</span></div>",
    unsafe_allow_html=True,
)

theme.balance_scale(total_export, total_import)

col1, col2, col3 = st.columns(3)
col1.metric("수출 누계", f"{total_export/1_000_000:,.1f}백만 $")
col2.metric("수입 누계", f"{total_import/1_000_000:,.1f}백만 $")
col3.metric(
    "무역수지",
    f"{balance/1_000_000:,.1f}백만 $",
    delta="흑자" if balance >= 0 else "적자",
    delta_color="normal" if balance >= 0 else "inverse",
)

st.markdown("<div class='rule'></div>", unsafe_allow_html=True)

tab_trend, tab_balance, tab_price, tab_table = st.tabs(["추이", "수지", "단가", "원자료"])

with tab_trend:
    chart_df = periods.set_index("label")[["export_usd", "import_usd"]]
    chart_df.columns = ["수출", "수입"]
    st.line_chart(chart_df, height=380, color=[theme.EXPORT, theme.IMPORT])
    st.caption("단위: 달러")

    if len(periods) >= 2:
        first, last = periods.iloc[0], periods.iloc[-1]
        if first["export_usd"] > 0:
            change = (last["export_usd"] / first["export_usd"] - 1) * 100
            direction = "늘었습니다" if change >= 0 else "줄었습니다"
            st.markdown(
                f"수출액은 {first['label']} 대비 {last['label']}에 "
                f"**{abs(change):,.1f}%** {direction}."
            )

with tab_balance:
    bal_df = periods.set_index("label")[["balance_usd"]]
    bal_df.columns = ["무역수지"]
    st.bar_chart(bal_df, height=380, color=theme.INK)
    st.caption("단위: 달러 · 0보다 크면 흑자")

    deficit = periods[periods["balance_usd"] < 0]
    if not deficit.empty:
        st.markdown(
            f"조회 기간 {len(periods)}개월 중 **{len(deficit)}개월**이 적자입니다."
        )

with tab_price:
    # 금액을 중량으로 나눠 kg당 단가를 만든다. 중량이 0인 구간은 비워 둔다.
    unit = periods.copy()
    unit["수출 단가"] = (unit["export_usd"] / unit["export_wgt"]).where(unit["export_wgt"] > 0)
    unit["수입 단가"] = (unit["import_usd"] / unit["import_wgt"]).where(unit["import_wgt"] > 0)

    price_df = unit.set_index("label")[["수출 단가", "수입 단가"]]
    if price_df.notna().any().any():
        st.line_chart(price_df, height=380, color=[theme.EXPORT, theme.IMPORT])
        st.caption("단위: 달러/kg · 신고금액을 신고중량으로 나눈 값")
        avg_export = unit["수출 단가"].mean()
        if pd.notna(avg_export):
            st.markdown(f"조회 기간 평균 수출 단가는 **{avg_export:,.2f} $/kg** 입니다.")
    else:
        st.info("중량 자료가 없어 단가를 계산할 수 없습니다.")

with tab_table:
    show_cols = [c for c in
                 ["label", "hs_cd", "item_name", "country", "export_usd", "export_wgt",
                  "import_usd", "import_wgt", "balance_usd"]
                 if c in periods.columns]
    renamed = {
        "label": "기간",
        "hs_cd": "HS",
        "item_name": "품목",
        "country": "국가",
        "export_usd": "수출액($)",
        "export_wgt": "수출중량(kg)",
        "import_usd": "수입액($)",
        "import_wgt": "수입중량(kg)",
        "balance_usd": "무역수지($)",
    }
    table = periods[show_cols].rename(columns=renamed)
    st.dataframe(table, width="stretch", hide_index=True)

    buffer = io.StringIO()
    table.to_csv(buffer, index=False)
    st.download_button(
        "CSV로 내려받기",
        buffer.getvalue().encode("utf-8-sig"),
        file_name=f"trade_{meta.get('hs','all')}_{meta.get('country','')}"
                  f"_{meta.get('start','')}_{meta.get('end','')}.csv",
        mime="text/csv",
    )

st.markdown(
    "<div class='footnote'>데이터 출처: 공공데이터포털 · 관세청 품목별 국가별 수출입실적</div>",
    unsafe_allow_html=True,
)

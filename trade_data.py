"""관세청 무역통계 API 조회와 월별 분석을 위한 데이터 계층."""

from __future__ import annotations

import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable

import pandas as pd
import requests


API_URL = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"

FIELD_MAP = {
    "year": "period",
    "statCdCntnKor1": "country",
    "statCd": "country_cd",
    "statKor": "item_name",
    "hsCd": "hs_cd",
    "expWgt": "export_wgt",
    "expDlr": "export_usd",
    "impWgt": "import_wgt",
    "impDlr": "import_usd",
    "balPayments": "balance_usd",
}

NUMERIC_COLS = [
    "export_wgt",
    "export_usd",
    "import_wgt",
    "import_usd",
    "balance_usd",
]
TEXT_COLS = ["period", "country", "country_cd", "item_name", "hs_cd"]
PERIOD_RE = re.compile(r"^(\d{4})[.\-/]?(\d{2})$")


class TradeDataError(RuntimeError):
    """사용자에게 설명할 수 있는 조회·응답 오류."""


def normalize_key(raw_key: str) -> str:
    """URL 인코딩된 인증키를 requests에 전달할 원래 값으로 되돌린다."""
    key = raw_key.strip()
    return urllib.parse.unquote(key) if "%" in key else key


def to_number(raw: object) -> float:
    """관세청 숫자 문자열을 안전하게 float으로 변환한다."""
    if raw is None:
        return 0.0
    text = str(raw).strip().replace(",", "")
    if text in {"", "-", "null", "None"}:
        return 0.0
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def ensure_schema(frame: pd.DataFrame) -> pd.DataFrame:
    """빈 필드나 응답 스키마 변화가 있어도 분석 컬럼을 항상 보장한다."""
    if frame is None:
        frame = pd.DataFrame()
    result = frame.copy()
    for col in TEXT_COLS:
        if col not in result.columns:
            result[col] = ""
        result[col] = result[col].fillna("").astype(str)
    for col in NUMERIC_COLS:
        if col not in result.columns:
            result[col] = 0.0
        result[col] = result[col].map(to_number)
    # 일부 응답에 무역수지가 없거나 일관되지 않아도 표시 값은 금액으로 재계산한다.
    result["balance_usd"] = result["export_usd"] - result["import_usd"]
    return result


def parse_response(xml_text: str) -> pd.DataFrame:
    """관세청 XML 응답을 표준 스키마의 DataFrame으로 변환한다."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise TradeDataError(
            "응답을 해석하지 못했습니다. 인증키와 활용 신청 상태를 확인해 주세요."
        ) from exc

    reason_code = root.findtext(".//returnReasonCode")
    if reason_code:
        code = reason_code.strip()
        auth_msg = (root.findtext(".//returnAuthMsg") or "").strip()
        hint = {
            "30": "등록되지 않은 인증키입니다. 발급 직후라면 반영에 시간이 걸릴 수 있습니다.",
            "22": "일일 요청 한도를 넘었습니다.",
            "31": "활용기간이 만료되었습니다.",
            "32": "등록되지 않은 IP입니다.",
        }.get(code, "")
        raise TradeDataError(f"[{code}] {auth_msg} {hint}".strip())

    result_code = root.findtext(".//resultCode")
    if result_code is not None and result_code.strip() not in {"00", "0"}:
        message = (root.findtext(".//resultMsg") or "알 수 없는 API 오류").strip()
        raise TradeDataError(f"[{result_code.strip()}] {message}")

    rows: list[dict[str, str]] = []
    for item in root.iter("item"):
        raw = {child.tag: (child.text or "").strip() for child in item}
        rows.append({FIELD_MAP.get(tag, tag): value for tag, value in raw.items()})

    return ensure_schema(pd.DataFrame(rows))


def year_chunks(start_ym: str, end_ym: str) -> list[tuple[str, str]]:
    """1년 제한을 지키도록 조회 기간을 연도 경계에서 분할한다."""
    start_y, start_m = int(start_ym[:4]), int(start_ym[4:])
    end_y, end_m = int(end_ym[:4]), int(end_ym[4:])
    if (start_y, start_m) > (end_y, end_m):
        raise ValueError("시작 시점은 종료 시점보다 늦을 수 없습니다.")

    chunks = []
    for year in range(start_y, end_y + 1):
        first = f"{year:04d}{start_m:02d}" if year == start_y else f"{year:04d}01"
        last = f"{year:04d}{end_m:02d}" if year == end_y else f"{year:04d}12"
        chunks.append((first, last))
    return chunks


def fetch_chunk(
    service_key: str,
    hs_code: str,
    country_code: str,
    start_ym: str,
    end_ym: str,
    *,
    timeout: int = 20,
) -> pd.DataFrame:
    """하나의 연도 구간을 최대 3회 재시도해 조회한다."""
    params = {
        "serviceKey": service_key,
        "strtYymm": start_ym,
        "endYymm": end_ym,
        "cntyCd": country_code,
    }
    if hs_code:
        params["hsSgn"] = hs_code

    last_error: requests.RequestException | None = None
    for attempt in range(3):
        try:
            response = requests.get(API_URL, params=params, timeout=timeout)
            response.raise_for_status()
            return parse_response(response.text)
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.2 * (attempt + 1))
    raise TradeDataError(f"API 요청에 실패했습니다: {last_error}")


def fetch_trade(
    service_key: str,
    hs_code: str,
    country_code: str,
    start_ym: str,
    end_ym: str,
    *,
    progress: Callable[[int, int, str], None] | None = None,
) -> pd.DataFrame:
    """여러 연도 구간을 조회해 원자료 한 벌로 합친다."""
    chunks = year_chunks(start_ym, end_ym)
    frames: list[pd.DataFrame] = []
    for index, (first, last) in enumerate(chunks, start=1):
        if progress:
            progress(index, len(chunks), first[:4])
        chunk = fetch_chunk(service_key, hs_code, country_code, first, last)
        if not chunk.empty:
            frames.append(chunk)
        if index < len(chunks):
            time.sleep(0.2)
    if not frames:
        return ensure_schema(pd.DataFrame())
    return ensure_schema(pd.concat(frames, ignore_index=True))


def prepare_periods(frame: pd.DataFrame) -> pd.DataFrame:
    """총계 행을 제거하고 같은 월의 세부 품목 행을 월 단위로 집계한다."""
    clean = ensure_schema(frame)
    if clean.empty:
        return clean
    monthly = clean[clean["period"].str.match(PERIOD_RE)].copy()
    if monthly.empty:
        return monthly

    monthly["period"] = monthly["period"].str.replace(r"[\-/]", ".", regex=True)
    monthly["period_date"] = pd.to_datetime(monthly["period"], format="%Y.%m")
    aggregated = (
        monthly.groupby(["period", "period_date"], as_index=False)[NUMERIC_COLS]
        .sum()
        .sort_values("period_date")
    )
    aggregated["balance_usd"] = aggregated["export_usd"] - aggregated["import_usd"]
    aggregated["label"] = aggregated["period_date"].dt.strftime("%Y.%m")
    aggregated["export_unit_usd"] = (
        aggregated["export_usd"] / aggregated["export_wgt"].where(aggregated["export_wgt"] > 0)
    )
    aggregated["import_unit_usd"] = (
        aggregated["import_usd"] / aggregated["import_wgt"].where(aggregated["import_wgt"] > 0)
    )
    return aggregated.reset_index(drop=True)


def percent_change(current: float, previous: float) -> float | None:
    """분모가 0이면 None을 반환하는 증감률 계산."""
    if previous == 0:
        return None
    return (current / previous - 1) * 100


def analysis_summary(periods: pd.DataFrame) -> dict[str, float | int | str | None]:
    """KPI 카드와 설명에 공통으로 쓰는 요약 지표를 만든다."""
    if periods.empty:
        return {}
    total_export = float(periods["export_usd"].sum())
    total_import = float(periods["import_usd"].sum())
    total_export_wgt = float(periods["export_wgt"].sum())
    total_import_wgt = float(periods["import_wgt"].sum())
    latest = periods.iloc[-1]
    prior = periods.iloc[-2] if len(periods) >= 2 else None
    yoy = periods.iloc[-13] if len(periods) >= 13 else None
    recent_12 = periods.tail(12)
    previous_12 = periods.iloc[-24:-12] if len(periods) >= 24 else pd.DataFrame()
    return {
        "months": int(len(periods)),
        "total_export": total_export,
        "total_import": total_import,
        "balance": total_export - total_import,
        "total_export_wgt": total_export_wgt,
        "total_import_wgt": total_import_wgt,
        "latest_period": str(latest["label"]),
        "latest_export": float(latest["export_usd"]),
        "latest_import": float(latest["import_usd"]),
        "latest_export_wgt": float(latest["export_wgt"]),
        "latest_import_wgt": float(latest["import_wgt"]),
        "export_mom": percent_change(float(latest["export_usd"]), float(prior["export_usd"])) if prior is not None else None,
        "export_yoy": percent_change(float(latest["export_usd"]), float(yoy["export_usd"])) if yoy is not None else None,
        "export_wgt_mom": percent_change(float(latest["export_wgt"]), float(prior["export_wgt"])) if prior is not None else None,
        "export_wgt_yoy": percent_change(float(latest["export_wgt"]), float(yoy["export_wgt"])) if yoy is not None else None,
        "recent_12_export": float(recent_12["export_usd"].sum()),
        "recent_12_growth": percent_change(
            float(recent_12["export_usd"].sum()),
            float(previous_12["export_usd"].sum()),
        ) if not previous_12.empty else None,
        "recent_12_export_wgt": float(recent_12["export_wgt"].sum()),
        "recent_12_import_wgt": float(recent_12["import_wgt"].sum()),
        "recent_12_wgt_growth": percent_change(
            float(recent_12["export_wgt"].sum()),
            float(previous_12["export_wgt"].sum()),
        ) if not previous_12.empty else None,
        "deficit_months": int((periods["balance_usd"] < 0).sum()),
        "peak_export_period": str(periods.loc[periods["export_usd"].idxmax(), "label"]),
        "peak_export": float(periods["export_usd"].max()),
        "peak_export_wgt_period": str(periods.loc[periods["export_wgt"].idxmax(), "label"]),
        "peak_export_wgt": float(periods["export_wgt"].max()),
    }

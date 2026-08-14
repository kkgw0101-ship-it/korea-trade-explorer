"""외부 시장지표 조회와 시계열 요약을 위한 데이터 계층."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable, Iterable

import pandas as pd
import requests


FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

MARKET_SERIES = {
    "DEXKOUS": {
        "name": "USD/KRW",
        "description": "원/달러 환율",
        "unit": "KRW",
        "frequency": "DAILY CLOSE",
        "change_label": "전일 대비",
        "format": ",.2f",
    },
    "DCOILWTICO": {
        "name": "WTI",
        "description": "서부텍사스유 현물가격",
        "unit": "USD/bbl",
        "frequency": "DAILY CLOSE",
        "change_label": "전일 대비",
        "format": ",.2f",
    },
    "HOUST": {
        "name": "US Housing Starts",
        "description": "미국 주택착공",
        "unit": "K units SAAR",
        "frequency": "MONTHLY",
        "change_label": "전월 대비",
        "format": ",.0f",
    },
}


class MarketDataError(RuntimeError):
    """외부 시장지표를 안전하게 표시할 수 없을 때 사용하는 오류."""


def parse_fred_csv(csv_text: str) -> dict[str, pd.DataFrame]:
    """FRED graph CSV를 지표별 ``date``/``value`` 시계열로 변환한다."""
    try:
        raw = pd.read_csv(io.StringIO(csv_text))
    except Exception as exc:  # pandas 파서 오류를 사용자 메시지로 정규화한다.
        raise MarketDataError("FRED 응답을 표 형식으로 해석하지 못했습니다.") from exc

    date_candidates = [column for column in ("DATE", "observation_date") if column in raw]
    if not date_candidates:
        raise MarketDataError("FRED 응답에 날짜 컬럼이 없습니다.")

    date_col = date_candidates[0]
    raw[date_col] = pd.to_datetime(raw[date_col], errors="coerce")
    result: dict[str, pd.DataFrame] = {}
    for series_id in MARKET_SERIES:
        if series_id not in raw:
            continue
        values = pd.to_numeric(raw[series_id].replace(".", pd.NA), errors="coerce")
        frame = pd.DataFrame({"date": raw[date_col], "value": values}).dropna()
        frame = frame.sort_values("date").drop_duplicates("date", keep="last")
        if not frame.empty:
            result[series_id] = frame.reset_index(drop=True)
    return result


def parse_fred_payload(payload: bytes, content_type: str = "") -> dict[str, pd.DataFrame]:
    """단일 CSV 또는 주기별 CSV가 담긴 FRED ZIP 응답을 해석한다."""
    is_zip = "zip" in content_type.lower() or payload.startswith(b"PK")
    if not is_zip:
        return parse_fred_csv(payload.decode("utf-8-sig", errors="replace"))

    combined: dict[str, pd.DataFrame] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            for name in csv_names:
                text = archive.read(name).decode("utf-8-sig", errors="replace")
                combined.update(parse_fred_csv(text))
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise MarketDataError("FRED 압축 응답을 해석하지 못했습니다.") from exc
    return combined


def fetch_fred_bundle(
    series_ids: Iterable[str] | None = None,
    *,
    requester: Callable[..., requests.Response] = requests.get,
    timeout: int = 8,
) -> dict[str, pd.DataFrame]:
    """공용 FRED CSV에서 여러 지표를 한 요청으로 조회한다."""
    selected = list(series_ids or MARKET_SERIES)
    try:
        response = requester(
            FRED_CSV_URL,
            params={"id": ",".join(selected)},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise MarketDataError("외부 시장지표 연결이 일시적으로 지연되고 있습니다.") from exc

    parsed = parse_fred_payload(
        response.content,
        response.headers.get("content-type", ""),
    )
    available = {series_id: parsed[series_id] for series_id in selected if series_id in parsed}
    if not available:
        raise MarketDataError("사용 가능한 외부 시장지표가 없습니다.")
    return available


def percent_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current / previous - 1) * 100


def value_at_or_before(frame: pd.DataFrame, target: pd.Timestamp) -> float | None:
    eligible = frame.loc[frame["date"] <= target, "value"]
    return float(eligible.iloc[-1]) if not eligible.empty else None


def series_snapshot(frame: pd.DataFrame) -> dict[str, float | str | None]:
    """최신값과 전기·1개월·1년 변화율을 계산한다."""
    clean = frame.dropna(subset=["date", "value"]).sort_values("date")
    if clean.empty:
        return {}

    latest = clean.iloc[-1]
    previous = clean.iloc[-2] if len(clean) >= 2 else None
    latest_date = pd.Timestamp(latest["date"])
    latest_value = float(latest["value"])
    month_value = value_at_or_before(clean, latest_date - pd.DateOffset(months=1))
    year_value = value_at_or_before(clean, latest_date - pd.DateOffset(years=1))
    return {
        "latest_date": latest_date.strftime("%Y.%m.%d"),
        "latest_value": latest_value,
        "change": latest_value - float(previous["value"]) if previous is not None else None,
        "change_pct": percent_change(latest_value, float(previous["value"])) if previous is not None else None,
        "month_pct": percent_change(latest_value, month_value) if month_value is not None else None,
        "year_pct": percent_change(latest_value, year_value) if year_value is not None else None,
    }


def indexed_series(frame: pd.DataFrame) -> pd.DataFrame:
    """첫 유효 관측값을 100으로 변환한 비교용 시계열을 반환한다."""
    clean = frame.dropna(subset=["date", "value"]).sort_values("date").copy()
    if clean.empty:
        clean["index"] = pd.Series(dtype=float)
        return clean
    nonzero = clean.loc[clean["value"] != 0, "value"]
    if nonzero.empty:
        clean["index"] = pd.NA
        return clean
    clean["index"] = clean["value"] / float(nonzero.iloc[0]) * 100
    return clean

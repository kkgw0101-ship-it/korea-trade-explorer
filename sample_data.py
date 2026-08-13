"""
인증키가 없을 때 화면 구성을 확인하기 위한 샘플 데이터.
실제 통계가 아니며, HS Code를 시드로 삼아 매번 같은 값이 나오도록 했다.
"""

import math
import random

import pandas as pd


def _months(start_ym, end_ym):
    start_y, start_m = int(start_ym[:4]), int(start_ym[4:])
    end_y, end_m = int(end_ym[:4]), int(end_ym[4:])

    out = []
    year, month = start_y, start_m
    while (year, month) <= (end_y, end_m):
        out.append(f"{year:04d}{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


def build(start_ym, end_ym, hs_code):
    """계절성과 완만한 추세를 섞은 가짜 시계열을 만든다."""
    rng = random.Random(hs_code or "sample")
    periods = _months(start_ym, end_ym)

    base_export = rng.uniform(18_000, 65_000)
    base_import = rng.uniform(9_000, 48_000)
    export_drift = rng.uniform(-0.004, 0.011)
    import_drift = rng.uniform(-0.003, 0.009)

    rows = []
    for index, period in enumerate(periods):
        month = int(period[4:])
        season = 1 + 0.14 * math.sin((month - 3) / 12 * 2 * math.pi)

        export = base_export * (1 + export_drift) ** index * season
        export *= rng.uniform(0.9, 1.1)
        imp = base_import * (1 + import_drift) ** index * season
        imp *= rng.uniform(0.88, 1.12)

        rows.append(
            {
                "period": period,
                "hs_cd": hs_code,
                "name_kr": "샘플 품목",
                "export_usd_k": round(export, 1),
                "export_wgt": round(export * rng.uniform(700, 1300), 0),
                "import_usd_k": round(imp, 1),
                "import_wgt": round(imp * rng.uniform(700, 1300), 0),
                "balance_usd_k": round(export - imp, 1),
            }
        )

    return pd.DataFrame(rows)

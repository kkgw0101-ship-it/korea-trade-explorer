import io
import unittest
import zipfile

import pandas as pd

from market_data import indexed_series, parse_fred_csv, parse_fred_payload, series_snapshot


class MarketDataTests(unittest.TestCase):
    def setUp(self):
        self.csv_text = """DATE,DEXKOUS,DCOILWTICO,HOUST
2025-01-01,1450.0,70.0,1350
2025-02-01,1460.0,.,1375
2026-01-01,1500.0,75.0,1400
2026-02-01,1515.0,78.0,1420
"""

    def test_parse_fred_csv_handles_missing_observations(self):
        result = parse_fred_csv(self.csv_text)
        self.assertEqual(set(result), {"DEXKOUS", "DCOILWTICO", "HOUST"})
        self.assertEqual(len(result["DCOILWTICO"]), 3)
        self.assertEqual(result["DEXKOUS"].iloc[-1]["value"], 1515.0)

    def test_series_snapshot_calculates_period_changes(self):
        result = series_snapshot(parse_fred_csv(self.csv_text)["DEXKOUS"])
        self.assertEqual(result["latest_date"], "2026.02.01")
        self.assertAlmostEqual(result["change_pct"], 1.0)
        self.assertAlmostEqual(result["year_pct"], (1515 / 1460 - 1) * 100)

    def test_indexed_series_uses_first_nonzero_as_100(self):
        frame = pd.DataFrame(
            {"date": pd.to_datetime(["2025-01-01", "2025-02-01"]), "value": [20, 30]}
        )
        indexed = indexed_series(frame)
        self.assertEqual(indexed.iloc[0]["index"], 100)
        self.assertEqual(indexed.iloc[1]["index"], 150)

    def test_parse_fred_payload_combines_daily_and_monthly_zip(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("daily.csv", "observation_date,DEXKOUS\n2026-01-01,1500\n")
            archive.writestr("monthly.csv", "observation_date,HOUST\n2026-01-01,1400\n")
        result = parse_fred_payload(buffer.getvalue(), "application/zip")
        self.assertEqual(set(result), {"DEXKOUS", "HOUST"})


if __name__ == "__main__":
    unittest.main()

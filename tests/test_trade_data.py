import unittest

import pandas as pd

from sample_data import build
from trade_data import (
    TradeDataError,
    analysis_summary,
    ensure_schema,
    parse_response,
    prepare_periods,
    year_chunks,
)


class TradeDataTests(unittest.TestCase):
    def test_year_chunks_cross_year_boundary(self):
        self.assertEqual(
            year_chunks("202311", "202502"),
            [("202311", "202312"), ("202401", "202412"), ("202501", "202502")],
        )

    def test_parse_response_maps_and_converts_fields(self):
        xml = """
        <response><header><resultCode>00</resultCode></header><body><items><item>
          <year>2025.01</year><hsCd>3918</hsCd><statCd>US</statCd>
          <statCdCntnKor1>미국</statCdCntnKor1><statKor>바닥재</statKor>
          <expDlr>1,200</expDlr><expWgt>300</expWgt>
          <impDlr>400</impDlr><impWgt>100</impWgt><balPayments>800</balPayments>
        </item></items></body></response>
        """
        result = parse_response(xml)
        self.assertEqual(result.loc[0, "export_usd"], 1200.0)
        self.assertEqual(result.loc[0, "balance_usd"], 800.0)
        self.assertEqual(result.loc[0, "country"], "미국")

    def test_parse_response_raises_friendly_api_error(self):
        xml = """
        <OpenAPI_ServiceResponse><cmmMsgHeader>
          <returnReasonCode>30</returnReasonCode><returnAuthMsg>SERVICE KEY IS NOT REGISTERED</returnAuthMsg>
        </cmmMsgHeader></OpenAPI_ServiceResponse>
        """
        with self.assertRaises(TradeDataError):
            parse_response(xml)

    def test_ensure_schema_prevents_missing_measure_crash(self):
        result = ensure_schema(pd.DataFrame({"period": ["2025.01"]}))
        for column in ["export_usd", "import_usd", "balance_usd"]:
            self.assertIn(column, result.columns)
            self.assertEqual(result.loc[0, column], 0.0)

    def test_prepare_periods_removes_total_and_aggregates_duplicate_months(self):
        frame = pd.DataFrame(
            {
                "period": ["2025.01", "2025.01", "총계"],
                "export_usd": [100, 250, 350],
                "import_usd": [30, 50, 80],
                "export_wgt": [10, 25, 35],
                "import_wgt": [3, 5, 8],
            }
        )
        result = prepare_periods(frame)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.loc[0, "export_usd"], 350.0)
        self.assertEqual(result.loc[0, "balance_usd"], 270.0)
        self.assertEqual(result.loc[0, "export_unit_usd"], 10.0)

    def test_sample_pipeline_has_all_dashboard_metrics(self):
        raw = build("202401", "202512", "3918", "미국")
        periods = prepare_periods(raw)
        summary = analysis_summary(periods)
        self.assertEqual(summary["months"], 24)
        self.assertGreater(summary["total_export"], 0)
        self.assertGreater(summary["total_export_wgt"], 0)
        self.assertGreater(summary["latest_export_wgt"], 0)
        self.assertIsNotNone(summary["recent_12_growth"])
        self.assertIsNotNone(summary["recent_12_wgt_growth"])


if __name__ == "__main__":
    unittest.main()

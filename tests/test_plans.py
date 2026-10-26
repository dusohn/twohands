import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from refresh_jobis import forecast_document, load_settled_filings, load_settled_vat, normalize_plans
from save_plans_from_issue import extract_plans


class PlansTest(unittest.TestCase):
    def test_normalize_keeps_dated_supply_and_drops_blank_rows(self):
        document = normalize_plans(
            {
                "sales": [
                    {"date": "2027-04-30", "supply": 42000000, "note": "부가세 별도"},
                    {"date": "", "supply": "", "note": ""},
                ],
                "expenses": [{"date": "2026-10-30", "supply": 3000000, "note": "침대구입"}],
            }
        )
        self.assertEqual(document["sales"][0]["date"], "2027-04-30")
        self.assertEqual(len(document["sales"]), 1)
        self.assertEqual(document["expenses"][0]["note"], "침대구입")

    def test_normalize_rejects_a_partial_row(self):
        with self.assertRaises(ValueError):
            normalize_plans({"sales": [{"date": "2026-11-30", "supply": ""}], "expenses": []})

    def test_extract_plans_reads_the_json_fence(self):
        payload = extract_plans(
            "이 이슈를 제출하면 저장됩니다.\n\n```json\n"
            '{"sales": [], "expenses": [{"date": "2026-12-25", "supply": 1800000, "note": "현탁 핸드폰"}]}\n'
            "```\n"
        )
        self.assertEqual(payload["expenses"][0]["note"], "현탁 핸드폰")
        self.assertEqual(payload["expenses"][0]["supply"], 1800000)

    def test_rebuilt_forecast_keeps_settled_q3_vat_out_of_october(self):
        self.assertIn((2026, 10), load_settled_vat())
        updated = forecast_document(
            {
                "asOf": "2026-10-12",
                "cashNow": 10_000_000,
                "actuals": [
                    {
                        "year": 2026,
                        "month": 8,
                        "sales": 42_000_000,
                        "purchase": 0,
                        "card": 0,
                        "bankIn": 0,
                        "bankOut": 0,
                        "cardPaid": 0,
                        "vatPaid": 0,
                    },
                    {
                        "year": 2026,
                        "month": 9,
                        "sales": 0,
                        "purchase": 0,
                        "card": 0,
                        "bankIn": 0,
                        "bankOut": 0,
                        "cardPaid": 0,
                        "vatPaid": 0,
                    },
                    {
                        "year": 2026,
                        "month": 10,
                        "sales": 0,
                        "purchase": 0,
                        "card": 0,
                        "bankIn": 0,
                        "bankOut": 0,
                        "cardPaid": 0,
                        "vatPaid": 0,
                    },
                ],
                "balances": {},
                "assumptions": [],
                "rows": [],
            },
            {"sales": [], "expenses": []},
        )
        october = next(row for row in updated["rows"] if row["month"] == 10)
        self.assertEqual(october["bankOut"], 0)
        self.assertEqual(october["endCash"], 10_000_000)
        self.assertTrue(any("3,542,780" in item for item in updated["assumptions"]))

    def test_october_bank_withdrawal_is_the_q3_vat_payment(self):
        october_filing = next(item for item in load_settled_filings() if item["month"] == 10)
        self.assertEqual(october_filing["amount"], 3_542_780)
        updated = forecast_document(
            {
                "asOf": "2026-10-25",
                "cashNow": 30_028_613,
                "actuals": [
                    {
                        "year": 2026,
                        "month": 8,
                        "sales": 42_000_000,
                        "purchase": 0,
                        "card": 0,
                        "bankIn": 46_200_000,
                        "bankOut": 0,
                        "cardPaid": 0,
                        "vatPaid": 0,
                    },
                    {
                        "year": 2026,
                        "month": 9,
                        "sales": 0,
                        "purchase": 0,
                        "card": 2_949_981,
                        "bankIn": 0,
                        "bankOut": 0,
                        "cardPaid": 0,
                        "vatPaid": 0,
                    },
                    {
                        "year": 2026,
                        "month": 10,
                        "sales": 0,
                        "purchase": 0,
                        "card": 2_563_958,
                        "bankIn": 0,
                        "bankOut": 3_542_780,
                        "cardPaid": 0,
                        "vatPaid": 0,
                    },
                ],
                "balances": {},
                "rows": [],
            },
            {
                "sales": [],
                "expenses": [{"date": "2026-10-30", "supply": 4_500_000, "note": "침대구입"}],
            },
        )
        actual = next(row for row in updated["actuals"] if row["month"] == 10)
        forecast = next(row for row in updated["rows"] if row["month"] == 10)
        self.assertEqual(actual["vatPaid"], 3_542_780)
        self.assertEqual(forecast["bankOut"], 11_442_761)
        self.assertEqual(forecast["endCash"], 22_128_632)

    def test_saved_expense_is_paid_with_vat(self):
        cash = {
            "asOf": "2026-10-12",
            "cashNow": 10_000_000,
            "actuals": [
                {
                    "year": 2026,
                    "month": 10,
                    "sales": 0,
                    "purchase": 0,
                    "card": 0,
                    "bankIn": 0,
                    "bankOut": 0,
                    "cardPaid": 0,
                    "vatPaid": 0,
                }
            ],
            "balances": {},
            "plans": [],
            "expenses": [],
            "rows": [],
        }
        updated = forecast_document(
            cash,
            {
                "sales": [{"date": "2026-11-30", "supply": 1_000_000}],
                "expenses": [{"date": "2026-10-20", "supply": 2_000_000, "note": "외주"}],
            },
        )
        by = {(row["year"], row["month"]): row for row in updated["rows"]}
        self.assertEqual(by[(2026, 10)]["bankOut"], 2_200_000)
        self.assertEqual(by[(2026, 10)]["purchase"], 2_000_000)
        self.assertEqual(by[(2026, 10)]["endCash"], 7_800_000)
        self.assertEqual(by[(2026, 11)]["bankIn"], 1_100_000)
        self.assertEqual(updated["expenses"][0]["note"], "외주")
        self.assertEqual(cash["rows"], [])


if __name__ == "__main__":
    unittest.main()

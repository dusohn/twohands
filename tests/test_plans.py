import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from refresh_jobis import forecast_document, normalize_plans


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

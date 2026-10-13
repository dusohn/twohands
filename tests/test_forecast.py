import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from forecast import MonthActual, PlannedSale, apply_actual_balances, build_forecast


def month(year, month, sales=0, purchase=0, card=0, bank_in=0, bank_out=0, card_paid=0):
    return MonthActual(year, month, sales, purchase, card, bank_in, bank_out, card_paid)


class ForecastTest(unittest.TestCase):
    def test_october_2026_matches_the_agreed_ledger(self):
        actuals = [month(2026, m) for m in range(1, 7)]
        actuals += [
            month(2026, 7, purchase=414_600, bank_in=604_101, bank_out=179_780),
            month(2026, 8, sales=42_000_000, card=7_191_225, bank_in=46_202_125, bank_out=5_628_584),
            month(2026, 9, card=2_949_981, bank_in=35_948, bank_out=7_462_417, card_paid=7_456_887),
            month(2026, 10, card=1_627_595),
        ]
        balances = {
            (2026, 7): 424_321,
            (2026, 8): 40_997_862,
            (2026, 9): 33_571_393,
            (2026, 10): 33_571_393,
        }
        plans = [
            PlannedSale(2026, 11, 30, 56_000_000),
            PlannedSale(2027, 4, 30, 42_000_000),
        ]
        forecast = build_forecast(actuals, date(2026, 10, 12), 33_571_393, plans)
        apply_actual_balances(forecast["rows"], balances)
        self.assertEqual(forecast["currentMonthCard"], 4_204_620)
        self.assertEqual(forecast["baseExpense"], 3_577_301)
        by = {(row["year"], row["month"]): row for row in forecast["rows"]}
        self.assertEqual(by[(2026, 8)]["sales"], 42_000_000)
        self.assertEqual(by[(2026, 8)]["endCash"], 40_997_862)
        self.assertEqual(by[(2026, 9)]["status"], "실제")
        self.assertEqual(by[(2026, 10)]["status"], "진행")
        self.assertEqual(by[(2026, 10)]["card"], 4_204_620)
        self.assertEqual(by[(2026, 10)]["bankOut"], 2_949_981)
        self.assertEqual(by[(2026, 10)]["endCash"], 30_621_412)
        self.assertEqual(by[(2026, 11)]["status"], "예정")
        self.assertEqual(by[(2026, 11)]["bankIn"], 61_600_000)
        self.assertEqual(by[(2026, 11)]["endCash"], 88_016_792)
        self.assertEqual(by[(2026, 12)]["endCash"], 84_439_491)
        self.assertEqual(by[(2027, 1)]["bankOut"], 9_177_301)
        self.assertEqual(by[(2027, 1)]["endCash"], 75_262_190)
        self.assertEqual(by[(2027, 4)]["bankIn"], 46_200_000)
        self.assertEqual(by[(2027, 4)]["endCash"], 110_730_287)
        self.assertEqual(by[(2027, 7)]["bankOut"], 7_777_301)
        self.assertEqual(by[(2027, 7)]["endCash"], 95_798_384)
        self.assertEqual(by[(2029, 9)]["endCash"], 2_788_558)
        self.assertEqual(by[(2029, 10)]["endCash"], -788_743)
        self.assertEqual(forecast["depletion"], {"year": 2029, "month": 10, "day": 24})

    def test_booked_sale_is_not_added_twice(self):
        actuals = [month(2026, 11, sales=56_000_000, card=3_000_000, bank_in=61_600_000)]
        forecast = build_forecast(
            actuals,
            date(2026, 11, 30),
            80_000_000,
            [PlannedSale(2026, 11, 30, 56_000_000)],
        )
        november = forecast["rows"][0]
        self.assertEqual(november["status"], "실제")
        self.assertEqual(november["sales"], 56_000_000)


if __name__ == "__main__":
    unittest.main()

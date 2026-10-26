import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from forecast import (
    MonthActual,
    PlannedExpense,
    PlannedSale,
    apply_actual_balances,
    build_forecast,
    vat_due,
)


def month(year, month, sales=0, purchase=0, card=0, bank_in=0, bank_out=0, card_paid=0, vat_paid=0):
    return MonthActual(year, month, sales, purchase, card, bank_in, bank_out, card_paid, vat_paid)


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
        self.assertEqual(by[(2026, 10)]["bankOut"], 7_149_981)
        self.assertEqual(by[(2026, 10)]["endCash"], 26_421_412)
        self.assertEqual(by[(2026, 11)]["status"], "예정")
        self.assertEqual(by[(2026, 11)]["bankIn"], 61_600_000)
        self.assertEqual(by[(2026, 11)]["bankOut"], 4_204_620)
        self.assertEqual(by[(2026, 11)]["endCash"], 83_816_792)
        self.assertEqual(by[(2026, 12)]["endCash"], 80_239_491)
        self.assertEqual(by[(2027, 1)]["bankOut"], 9_177_301)
        self.assertEqual(by[(2027, 1)]["endCash"], 71_062_190)
        self.assertEqual(by[(2027, 4)]["bankIn"], 46_200_000)
        self.assertEqual(by[(2027, 4)]["bankOut"], 3_577_301)
        self.assertEqual(by[(2027, 4)]["endCash"], 106_530_287)
        self.assertEqual(by[(2027, 7)]["bankOut"], 7_777_301)
        self.assertEqual(by[(2027, 7)]["endCash"], 91_598_384)
        self.assertEqual(by[(2029, 8)]["endCash"], 2_165_859)
        self.assertEqual(by[(2029, 9)]["endCash"], -1_411_442)
        self.assertEqual(forecast["depletion"], {"year": 2029, "month": 9, "day": 18})

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

    def test_output_vat_is_paid_in_january_april_july_october(self):
        self.assertEqual(vat_due(2026, 2), (2026, 4))
        self.assertEqual(vat_due(2026, 5), (2026, 7))
        self.assertEqual(vat_due(2026, 8), (2026, 10))
        self.assertEqual(vat_due(2026, 11), (2027, 1))
        actuals = [
            month(2026, 2, sales=10_000_000),
            month(2026, 3),
        ]
        forecast = build_forecast(
            actuals,
            date(2026, 3, 15),
            20_000_000,
            [PlannedSale(2026, 3, 31, 5_000_000)],
        )
        by = {(row["year"], row["month"]): row for row in forecast["rows"]}
        self.assertEqual(by[(2026, 3)]["bankOut"], 0)
        self.assertEqual(by[(2026, 4)]["bankOut"], 1_500_000)
        self.assertEqual(by[(2026, 7)]["bankOut"], 0)

    def test_settled_july_to_september_vat_leaves_october_and_keeps_later_vat(self):
        actuals = [
            month(2026, 8, sales=42_000_000),
            month(2026, 9, card=2_949_981),
            month(2026, 10, card=2_563_958, bank_out=3_542_780),
        ]
        forecast = build_forecast(
            actuals,
            date(2026, 10, 25),
            30_028_613,
            [PlannedSale(2026, 11, 30, 56_000_000)],
            expenses=[PlannedExpense(2026, 10, 30, 4_500_000, "침대구입")],
            settled_vat=[(2026, 10)],
        )
        by = {(row["year"], row["month"]): row for row in forecast["rows"]}
        self.assertEqual(by[(2026, 10)]["bankOut"], 11_442_761)
        self.assertEqual(by[(2026, 10)]["endCash"], 22_128_632)
        self.assertEqual(by[(2027, 1)]["bankOut"], 8_664_645)

    def test_vat_already_paid_this_month_is_not_charged_again(self):
        actuals = [
            month(2026, 8, sales=42_000_000),
            month(2026, 9),
            month(2026, 10, bank_out=1_000_000, vat_paid=1_000_000),
        ]
        forecast = build_forecast(actuals, date(2026, 10, 12), 10_000_000, [])
        october = next(row for row in forecast["rows"] if row["month"] == 10)
        self.assertEqual(october["bankOut"], 4_200_000)
        self.assertEqual(october["endCash"], 6_800_000)

    def test_planned_expense_is_paid_with_vat_and_does_not_reduce_output_vat(self):
        forecast = build_forecast(
            [month(2026, 10)],
            date(2026, 10, 12),
            10_000_000,
            [PlannedSale(2026, 11, 30, 1_000_000)],
            expenses=[
                PlannedExpense(2026, 9, 30, 5_000_000),
                PlannedExpense(2026, 10, 20, 2_000_000),
                PlannedExpense(2026, 12, 15, 1_000_000, "외주"),
            ],
        )
        by = {(row["year"], row["month"]): row for row in forecast["rows"]}
        self.assertEqual(by[(2026, 10)]["status"], "예정")
        self.assertEqual(by[(2026, 10)]["purchase"], 2_000_000)
        self.assertEqual(by[(2026, 10)]["bankOut"], 2_200_000)
        self.assertEqual(by[(2026, 10)]["endCash"], 7_800_000)
        self.assertEqual(by[(2026, 11)]["bankIn"], 1_100_000)
        self.assertEqual(by[(2026, 12)]["status"], "예정")
        self.assertEqual(by[(2026, 12)]["purchase"], 1_000_000)
        self.assertEqual(by[(2026, 12)]["bankOut"], 1_100_000)
        self.assertEqual(by[(2026, 12)]["endCash"], 7_800_000)
        self.assertEqual(by[(2027, 1)]["bankOut"], 100_000)


if __name__ == "__main__":
    unittest.main()

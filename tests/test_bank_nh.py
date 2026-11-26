import json
import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from jobis_client import JobisClient
from refresh_jobis import (
    assemble_cashflow,
    fetch_jobis_cards,
    forecast_document,
    load_bank_nh,
    parse_bank_nh,
)

ROOT = Path(__file__).resolve().parents[1]


def _plans():
    return json.loads((ROOT / "data" / "plans.json").read_text(encoding="utf-8"))


def _month(year, month, **kwargs):
    row = {
        "year": year,
        "month": month,
        "sales": 0,
        "purchase": 0,
        "card": 0,
        "bankIn": 0,
        "bankOut": 0,
        "cardPaid": 0,
        "vatPaid": 0,
        "bankInLines": [],
        "bankOutLines": [],
        "endCash": 0,
    }
    row.update(kwargs)
    return row


def _previous():
    """Published shape on 2026-11-24, trimmed to the months the forecast reads."""
    return {
        "company": "주식회사 투핸즈",
        "source": "농협 통장 · 현대카드",
        "asOf": "2026-11-24",
        "currency": "KRW",
        "cashNow": 26_965_137,
        "actuals": [
            _month(2026, 8, card=7_191_225, bankIn=46_202_125, bankOut=5_628_584, cardPaid=5_628_584),
            _month(2026, 9, card=2_949_981, bankIn=35_948, bankOut=7_462_417, cardPaid=7_456_887),
            _month(
                2026,
                10,
                card=3_050_668,
                bankIn=29_135,
                bankOut=6_635_391,
                cardPaid=3_088_141,
                vatPaid=3_542_780,
                bankOutLines=[{"name": "부가세납부", "amount": 3_542_780}],
            ),
            _month(2026, 11, sales=56_000_000, card=7_992_038),
        ],
        "balances": {"2026-10": 26_965_137, "2026-11": 26_965_137},
        "cardMixMonth": "2026-11",
        "cardMix": [{"name": "항공사", "amount": 6_291_600}, {"name": "나머지", "amount": 1_700_438}],
        "cardMixSource": "현대카드 매출내역",
        "cardMixNote": "11월 25일 결제 예정 6,534,400원",
    }


def _today_bank():
    return {
        "account": "****6481",
        "queriedAt": "2026-11-25T13:43:24+09:00",
        "balance": 88_114_537,
        "available": 88_114_537,
        "transactions": [
            {
                "datetime": "2026-11-18T20:03:16+09:00",
                "deposit": 61_600_000,
                "withdrawal": 0,
                "balanceAfter": 88_114_537,
                "description": "E-하나은행",
                "memo": "(주)더린킨",
            },
            {
                "datetime": "2026-11-17T08:42:30+09:00",
                "deposit": 0,
                "withdrawal": 450_600,
                "balanceAfter": 26_514_537,
                "description": "실시간이체",
                "memo": "현대카드",
            },
        ],
    }


class BankFileTest(unittest.TestCase):
    def test_committed_file_is_a_masked_quick_lookup(self):
        bank = load_bank_nh()
        self.assertEqual(bank["account"], "****6481")
        self.assertEqual(bank["balance"], bank["available"])
        self.assertGreater(bank["balance"], 0)
        self.assertTrue(bank["transactions"])

    def test_seed_amounts_are_the_2026_11_26_lookup(self):
        bank = load_bank_nh()
        self.assertEqual(bank["queriedOn"].isoformat(), "2026-11-26")
        self.assertEqual(bank["balance"], 29_172_844)
        self.assertEqual(bank["transactions"][0]["description"], "정기예금")
        self.assertEqual(
            [(row["deposit"], row["withdrawal"], row["balanceAfter"], row["memo"]) for row in bank["transactions"]],
            [
                (0, 50_000_000, 29_172_844, "정기예금 가입 (1년, 만기 2027-11-25)"),
                (0, 8_919_693, 79_172_844, "현대카드대금"),
                (0, 22_000, 88_092_537, "NH기업카드"),
                (61_600_000, 0, 88_114_537, "(주)더린킨"),
                (0, 450_600, 26_514_537, "현대카드"),
            ],
        )

    def test_full_account_number_is_rejected_without_echoing_it(self):
        full = "3010987654321"
        with self.assertRaises(ValueError) as caught:
            parse_bank_nh({**_today_bank(), "account": full})
        self.assertNotIn(full, str(caught.exception))

    def test_timestamp_without_a_zone_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_bank_nh({**_today_bank(), "queriedAt": "2026-11-25T13:43:24"})

    def test_exact_duplicate_transactions_count_once(self):
        payload = _today_bank()
        payload["transactions"] = payload["transactions"] + [dict(payload["transactions"][0])]
        bank = parse_bank_nh(payload)
        self.assertEqual(len(bank["transactions"]), 2)


class RefreshTest(unittest.TestCase):
    def test_jobis_outage_keeps_cards_and_uses_the_nh_balance(self):
        previous = _previous()
        updated = assemble_cashflow(previous, _today_bank(), None, _plans())
        self.assertEqual(updated["cashNow"], 88_114_537)
        self.assertEqual(updated["asOf"], "2026-11-25")
        self.assertEqual(updated["source"], "농협 통장 · 현대카드")
        self.assertTrue(updated["cardFallback"])
        self.assertEqual(updated["cardAsOf"], "2026-11-24")
        self.assertEqual(updated["currentMonthCard"], 7_992_038)
        self.assertEqual(updated["baseExpense"], 4_397_291)
        self.assertEqual(sum(item["amount"] for item in updated["cardMix"]), 7_992_038)
        self.assertIn("6,534,400", updated["cardMixNote"])
        self.assertNotIn("자비스 숫자로", " ".join(updated["assumptions"]))
        self.assertIn(updated["depletion"]["year"], (2029,))

        november = next(row for row in updated["actuals"] if row["month"] == 11)
        self.assertEqual(november["bankIn"], 61_600_000)
        self.assertEqual(november["bankOut"], 450_600)
        self.assertEqual(november["cardPaid"], 450_600)
        self.assertEqual(november["sales"], 56_000_000)
        self.assertEqual(november["card"], 7_992_038)
        self.assertEqual(november["bankInLines"], [{"name": "(주)더린킨", "amount": 61_600_000}])
        self.assertEqual(november["bankOutLines"], [{"name": "현대카드", "amount": 450_600}])

        october = next(row for row in updated["actuals"] if row["month"] == 10)
        self.assertEqual(october["bankOut"], 6_635_391)
        self.assertEqual(october["vatPaid"], 3_542_780)
        self.assertEqual(october["bankOutLines"][0]["name"], "부가세납부")

        forecast = next(row for row in updated["rows"] if row["year"] == 2026 and row["month"] == 11)
        self.assertEqual(forecast["bankIn"], 61_600_000)
        self.assertEqual(forecast["bankOut"], 8_000_668)
        self.assertEqual(forecast["endCash"], 80_564_469)
        self.assertEqual([line["name"] for line in forecast["income"]], ["(주)더린킨"])
        self.assertNotIn("AX 중도금", [line["name"] for line in forecast["income"]])
        paid = next(line for line in forecast["expense"] if line["amount"] == 450_600)
        self.assertEqual(paid["name"], "현대카드")

        december = next(row for row in updated["rows"] if row["year"] == 2026 and row["month"] == 12)
        self.assertEqual(december["bankOut"], 7_992_038 + 1_980_000)
        self.assertEqual(previous["cashNow"], 26_965_137)
        self.assertEqual(previous["actuals"][-1]["bankIn"], 0)

    def test_newer_jobis_cards_do_not_replace_the_bank(self):
        cards = {
            "asOf": "2026-11-25",
            "cards": {(2026, 11): 8_100_000, (2026, 10): 3_050_668, (2026, 9): 2_949_981, (2026, 8): 7_191_225},
            "cardMix": [{"name": "항공", "amount": 8_100_000}],
            "cardMixMonth": "2026-10",
        }
        updated = assemble_cashflow(_previous(), _today_bank(), cards, _plans())
        self.assertEqual(updated["cashNow"], 88_114_537)
        self.assertFalse(updated["cardFallback"])
        self.assertEqual(updated["source"], "농협 통장 · 자비스 카드")
        self.assertEqual(updated["cardAsOf"], "2026-11-25")
        self.assertEqual(updated["cardMixSource"], "자비스 카드매입")
        self.assertEqual(updated["cardMixNote"], "")
        november = next(row for row in updated["actuals"] if row["month"] == 11)
        self.assertEqual(november["card"], 8_100_000)
        self.assertEqual(november["bankIn"], 61_600_000)
        self.assertEqual(november["bankOut"], 450_600)
        forecast = next(row for row in updated["rows"] if row["month"] == 11 and row["year"] == 2026)
        self.assertEqual(forecast["bankIn"], 61_600_000)

    def test_older_jobis_snapshot_does_not_replace_saved_cards_or_the_bank(self):
        cards = {
            "asOf": "2026-11-04",
            "cards": {(2026, 11): 6_546_300},
            "cardMix": [{"name": "기존", "amount": 1}],
            "cardMixMonth": "2026-10",
        }
        updated = assemble_cashflow(_previous(), _today_bank(), cards, _plans())
        self.assertTrue(updated["cardFallback"])
        self.assertEqual(updated["cashNow"], 88_114_537)
        self.assertEqual(updated["currentMonthCard"], 7_992_038)
        self.assertEqual(updated["cardMix"][0]["name"], "항공사")
        november = next(row for row in updated["rows"] if row["month"] == 11 and row["year"] == 2026)
        self.assertEqual(november["bankIn"], 61_600_000)

    def test_a_deposit_matching_a_plan_is_not_counted_twice(self):
        previous = _previous()
        previous["actuals"][-1]["sales"] = 0
        plans = {"sales": [{"date": "2026-11-30", "supply": 56_000_000, "note": "AX 중도금"}], "expenses": []}
        updated = assemble_cashflow(previous, _today_bank(), None, plans)
        november = next(row for row in updated["actuals"] if row["month"] == 11)
        self.assertEqual(november["sales"], 56_000_000)
        forecast = next(row for row in updated["rows"] if row["month"] == 11)
        self.assertEqual(forecast["bankIn"], 61_600_000)
        self.assertNotIn("AX 중도금", [line["name"] for line in forecast["income"]])

    def test_a_quiet_new_month_does_not_erase_history(self):
        previous = _previous()
        previous["actuals"][-1]["bankIn"] = 61_600_000
        previous["actuals"][-1]["bankOut"] = 450_600
        bank = parse_bank_nh(
            {
                "account": "****6481",
                "queriedAt": "2026-12-01T06:40:00+09:00",
                "balance": 88_000_000,
                "available": 88_000_000,
                "transactions": [],
            }
        )
        updated = assemble_cashflow(previous, bank, None, _plans())
        november = next(row for row in updated["actuals"] if row["month"] == 11)
        december = next(row for row in updated["actuals"] if row["month"] == 12)
        self.assertEqual(november["bankIn"], 61_600_000)
        self.assertEqual(november["bankOut"], 450_600)
        self.assertEqual(november["card"], 7_992_038)
        self.assertEqual(december["bankIn"], 0)
        self.assertEqual(december["bankOut"], 0)
        self.assertEqual(updated["cashNow"], 88_000_000)
        self.assertEqual(updated["balances"]["2026-12"], 88_000_000)

    def test_time_deposit_withdrawal_is_not_an_expense_and_returns_at_maturity(self):
        bank = {
            "account": "****6481",
            "queriedAt": "2026-11-26T09:19:05+09:00",
            "balance": 29_172_844,
            "available": 29_172_844,
            "transactions": [
                {
                    "datetime": "2026-11-26T09:19:00+09:00",
                    "deposit": 0,
                    "withdrawal": 50_000_000,
                    "balanceAfter": 29_172_844,
                    "description": "정기예금",
                    "memo": "정기예금 가입 (1년, 만기 2027-11-25)",
                },
                *_today_bank()["transactions"],
            ],
        }
        updated = assemble_cashflow(_previous(), bank, None, _plans())
        self.assertEqual(updated["cashNow"], 29_172_844)
        self.assertEqual(updated["totalFunds"], 79_172_844)
        self.assertEqual(updated["baseExpense"], 4_397_291)
        self.assertEqual(
            updated["deposits"],
            [
                {
                    "principal": 50_000_000,
                    "opened": "2026-11-26",
                    "maturity": "2027-11-25",
                    "note": "정기예금",
                }
            ],
        )
        november = next(row for row in updated["actuals"] if row["month"] == 11)
        self.assertEqual(november["bankOut"], 450_600)
        self.assertNotIn(50_000_000, [line["amount"] for line in november["bankOutLines"]])
        forecast = next(row for row in updated["rows"] if row["year"] == 2026 and row["month"] == 11)
        self.assertNotIn(50_000_000, [line["amount"] for line in forecast["expense"]])
        matured = next(row for row in updated["rows"] if row["year"] == 2027 and row["month"] == 11)
        self.assertEqual(matured["bankIn"], 50_000_000)
        self.assertEqual(matured["income"][0]["name"], "정기예금")
        self.assertEqual(matured["income"][0]["amount"], 50_000_000)
        self.assertIn("2027-11-25", matured["income"][0]["note"])
        self.assertIn("지출이 아닙니다", " ".join(updated["assumptions"]))

    def test_time_deposit_persists_when_the_bank_file_no_longer_lists_it(self):
        previous = _previous()
        previous["deposits"] = [
            {
                "principal": 50_000_000,
                "opened": "2026-11-26",
                "maturity": "2027-11-25",
                "note": "정기예금",
            }
        ]
        bank = parse_bank_nh(
            {
                "account": "****6481",
                "queriedAt": "2026-12-01T06:40:00+09:00",
                "balance": 29_000_000,
                "available": 29_000_000,
                "transactions": [],
            }
        )
        updated = assemble_cashflow(previous, bank, None, _plans())
        self.assertEqual(updated["cashNow"], 29_000_000)
        self.assertEqual(updated["totalFunds"], 79_000_000)
        self.assertEqual(updated["deposits"][0]["principal"], 50_000_000)
        matured = next(row for row in updated["rows"] if row["year"] == 2027 and row["month"] == 11)
        self.assertEqual(matured["bankIn"], 50_000_000)

    def test_matured_time_deposit_is_not_added_again(self):
        previous = _previous()
        previous["deposits"] = [
            {
                "principal": 50_000_000,
                "opened": "2026-11-26",
                "maturity": "2027-11-25",
                "note": "정기예금",
            }
        ]
        previous["asOf"] = "2027-11-25"
        previous["cashNow"] = 80_000_000
        # forecast_document needs actuals to include the as-of month
        previous["actuals"].append(_month(2027, 11))
        previous["balances"]["2027-11"] = 80_000_000
        updated = forecast_document(previous, {"sales": [], "expenses": []})
        self.assertEqual(updated["deposits"], [])
        self.assertEqual(updated["totalFunds"], 80_000_000)
        november = next(row for row in updated["rows"] if row["year"] == 2027 and row["month"] == 11)
        self.assertEqual(november["bankIn"], 0)

    def test_plan_rebuild_does_not_pull_bank_numbers_from_the_old_statement(self):
        cash = _previous()
        cash["cashNow"] = 123
        cash["asOf"] = "2026-11-20"
        cash["actuals"][-1]["bankIn"] = 10
        updated = forecast_document(cash, _plans())
        self.assertEqual(updated["cashNow"], 123)
        self.assertEqual(updated["actuals"][-1]["bankIn"], 10)
        self.assertNotIn("자비스 숫자로", " ".join(updated["assumptions"]))


class JobisOutageTest(unittest.TestCase):
    def test_empty_dashboard_body_does_not_fail_the_card_fetch(self):
        class Down(JobisClient):
            def __init__(self, email, password):
                self.email = email

            def login(self):
                return None

            def snapshot(self, today):
                json.loads("")

        with patch.dict(os.environ, {"JOBIS_EMAIL": "owner@example.com", "JOBIS_PASSWORD": "secret"}), patch(
            "refresh_jobis.JobisClient", Down
        ):
            self.assertIsNone(fetch_jobis_cards(date(2026, 11, 25)))

    def test_missing_credentials_keep_the_saved_cards(self):
        with patch.dict(os.environ, {"JOBIS_EMAIL": "", "JOBIS_PASSWORD": ""}):
            self.assertIsNone(fetch_jobis_cards(date(2026, 11, 25)))


if __name__ == "__main__":
    unittest.main()

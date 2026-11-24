import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from refresh_jobis import forecast_document

ROOT = Path(__file__).resolve().parents[1]


def _plans():
    return json.loads((ROOT / "data" / "plans.json").read_text(encoding="utf-8"))


def _jobis_snapshot():
    return {
        "asOf": "2026-11-04",
        "cashNow": 26_965_137,
        "source": "자비스",
        "actuals": [
            {
                "year": 2026,
                "month": 8,
                "sales": 42_000_000,
                "purchase": 0,
                "card": 7_191_225,
                "bankIn": 46_202_125,
                "bankOut": 5_628_584,
                "cardPaid": 5_628_584,
                "vatPaid": 0,
            },
            {
                "year": 2026,
                "month": 9,
                "sales": 0,
                "purchase": 0,
                "card": 2_949_981,
                "bankIn": 35_948,
                "bankOut": 7_462_417,
                "cardPaid": 7_456_887,
                "vatPaid": 0,
            },
            {
                "year": 2026,
                "month": 10,
                "sales": 0,
                "purchase": 0,
                "card": 3_050_668,
                "bankIn": 29_135,
                "bankOut": 6_635_391,
                "cardPaid": 3_088_141,
                "vatPaid": 3_542_780,
            },
            {
                "year": 2026,
                "month": 11,
                "sales": 0,
                "purchase": 0,
                "card": 6_546_300,
                "bankIn": 0,
                "bankOut": 0,
                "cardPaid": 0,
                "vatPaid": 0,
            },
        ],
        "balances": {"2026-10": 26_965_137, "2026-11": 26_965_137},
        "cardMix": [{"name": "기존", "amount": 1}],
        "cardMixMonth": "2026-10",
    }


class StatementTest(unittest.TestCase):
    def test_uploaded_statement_replaces_stale_november_until_jobis_is_newer(self):
        updated = forecast_document(_jobis_snapshot(), _plans())
        self.assertEqual(updated["asOf"], "2026-11-24")
        self.assertEqual(updated["cashNow"], 88_114_537)
        self.assertEqual(updated["source"], "농협 통장 · 현대카드")
        self.assertEqual(updated["currentMonthCard"], 7_992_038)
        self.assertEqual(updated["cardMixMonth"], "2026-11")
        self.assertEqual(sum(item["amount"] for item in updated["cardMix"]), 7_992_038)
        self.assertEqual(updated["cardMix"][0]["name"], "항공사")
        self.assertEqual(updated["cardMix"][0]["amount"], 6_291_600)
        self.assertIn("6,534,400", updated["cardMixNote"])
        self.assertIn("88,114,537", " ".join(updated["assumptions"]))

        november = next(row for row in updated["rows"] if row["year"] == 2026 and row["month"] == 11)
        self.assertEqual(november["bankIn"], 61_600_000)
        self.assertEqual(november["sales"], 56_000_000)
        self.assertEqual(november["card"], 7_992_038)
        self.assertEqual(november["bankOut"], 8_000_668)
        self.assertEqual(november["endCash"], 80_564_469)
        self.assertEqual([line["name"] for line in november["income"]], ["(주)더린킨"])
        self.assertEqual(november["income"][0]["amount"], 61_600_000)
        paid = next(line for line in november["expense"] if line["name"] == "현대카드 선결제")
        self.assertEqual(paid["amount"], 450_600)
        self.assertNotIn("AX 중도금", [line["name"] for line in november["income"]])

        december = next(row for row in updated["rows"] if row["year"] == 2026 and row["month"] == 12)
        self.assertEqual(december["bankOut"], 7_992_038 + 1_980_000)

        again = forecast_document(updated, _plans())
        november_again = next(row for row in again["rows"] if row["year"] == 2026 and row["month"] == 11)
        self.assertEqual(again["cashNow"], 88_114_537)
        self.assertEqual(november_again["bankIn"], 61_600_000)

    def test_newer_jobis_snapshot_keeps_its_own_figures(self):
        cash = _jobis_snapshot()
        cash["asOf"] = "2026-11-25"
        cash["cashNow"] = 90_000_000
        cash["actuals"][-1]["bankIn"] = 1_000
        cash["actuals"][-1]["card"] = 2_000
        updated = forecast_document(cash, _plans())
        self.assertEqual(updated["asOf"], "2026-11-25")
        self.assertEqual(updated["cashNow"], 90_000_000)
        self.assertEqual(updated["source"], "자비스")
        self.assertEqual(updated["cardMixMonth"], "2026-10")
        self.assertEqual(updated["cardMixNote"], "")
        november = next(row for row in updated["rows"] if row["month"] == 11 and row["year"] == 2026)
        self.assertEqual(november["bankIn"], 1_000 + 61_600_000)
        self.assertNotIn("올린 엑셀", " ".join(updated["assumptions"]))

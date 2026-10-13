#!/usr/bin/env python3
"""Refresh data/cashflow.json from Jobis. Credentials stay in the environment."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from forecast import MonthActual, PlannedSale, apply_actual_balances, build_forecast
from jobis_client import JobisClient

ROOT = Path(__file__).resolve().parents[1]
PLANS_PATH = ROOT / "data" / "plans.json"
OUTPUT_PATH = ROOT / "data" / "cashflow.json"
KST = ZoneInfo("Asia/Seoul")


def main() -> int:
    email = os.environ.get("JOBIS_EMAIL", "").strip()
    password = os.environ.get("JOBIS_PASSWORD", "")
    if not email or not password:
        print("JOBIS_EMAIL and JOBIS_PASSWORD are required", file=sys.stderr)
        return 2

    today = datetime.now(KST).date()
    client = JobisClient(email, password)
    client.login()
    snapshot = client.snapshot(today)
    plans = _load_plans()
    as_of = datetime.strptime(snapshot["asOf"], "%Y-%m-%d").date()
    actuals = [
        MonthActual(
            year=row["year"],
            month=row["month"],
            sales=row["sales"],
            purchase=row["purchase"],
            card=row["card"],
            bank_in=row["bankIn"],
            bank_out=row["bankOut"],
            card_paid=row["cardPaid"],
            vat_paid=row.get("vatPaid", 0),
        )
        for row in snapshot["months"]
    ]
    balances = {}
    for label, amount in snapshot["balances"].items():
        year, month = label.split("-")
        balances[(int(year), int(month))] = amount
    forecast = build_forecast(actuals, as_of, snapshot["cashNow"], plans)
    apply_actual_balances(forecast["rows"], balances)

    document = {
        "company": "주식회사 투핸즈",
        "source": "자비스",
        "asOf": snapshot["asOf"],
        "updatedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "currency": "KRW",
        "cashNow": snapshot["cashNow"],
        "baseExpense": forecast["baseExpense"],
        "currentMonthCard": forecast["currentMonthCard"],
        "monthComplete": forecast["monthComplete"],
        "depletion": forecast["depletion"],
        "plans": [
            {"date": f"{plan.year}-{plan.month:02d}-{plan.day:02d}", "supply": plan.supply}
            for plan in plans
        ],
        "cardMixMonth": snapshot["cardMixMonth"],
        "cardMix": snapshot["cardMix"],
        "assumptions": [
            "카드 대금은 사용 다음 달 통장 출금입니다.",
            "이번 달 카드 지출은 자비스 지출 리포트의 경과일을 월말로 늘린 금액입니다.",
            "그 다음 달부터의 월 지출은 지난달 카드와 이번 달 예상 카드의 평균입니다.",
            "예정 매출의 통장 입금은 공급가액에 부가세 10%를 더한 금액입니다.",
            "매출 부가세는 1월, 4월, 7월, 10월에 납부합니다. 1–3월분은 4월, 4–6월분은 7월, 7–9월분은 10월, 10–12월분은 다음 해 1월입니다.",
            "매입세액 공제는 빼지 않습니다. 이미 통장에서 나간 부가세는 다시 빼지 않습니다.",
            "예금 이자는 예상하지 않습니다. 예정 매출 외에 미래 매출은 0원입니다.",
        ],
        "rows": forecast["rows"],
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {OUTPUT_PATH.name} asOf={document['asOf']} cash={document['cashNow']} "
        f"base={document['baseExpense']} rows={len(document['rows'])}"
    )
    return 0


def _load_plans() -> list[PlannedSale]:
    if not PLANS_PATH.exists():
        return []
    payload = json.loads(PLANS_PATH.read_text(encoding="utf-8"))
    plans = []
    for item in payload.get("sales") or []:
        year, month, day = (int(part) for part in str(item["date"]).split("-"))
        plans.append(PlannedSale(year, month, day, int(item["supply"])))
    return plans


if __name__ == "__main__":
    raise SystemExit(main())

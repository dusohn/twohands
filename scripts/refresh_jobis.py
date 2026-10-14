#!/usr/bin/env python3
"""Refresh data/cashflow.json from Jobis. Credentials stay in the environment."""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from forecast import MonthActual, PlannedExpense, PlannedSale, apply_actual_balances, build_forecast
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
    plans_doc = (
        normalize_plans(json.loads(PLANS_PATH.read_text(encoding="utf-8")))
        if PLANS_PATH.exists()
        else {"sales": [], "expenses": []}
    )
    plans = [_sale(item) for item in plans_doc["sales"]]
    expenses = [_expense(item) for item in plans_doc["expenses"]]
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
    forecast = build_forecast(actuals, as_of, snapshot["cashNow"], plans, expenses=expenses)
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
        "plans": plans_doc["sales"],
        "expenses": plans_doc["expenses"],
        "actuals": snapshot["months"],
        "balances": snapshot["balances"],
        "cardMixMonth": snapshot["cardMixMonth"],
        "cardMix": snapshot["cardMix"],
        "assumptions": [
            "카드 대금은 사용 다음 달 통장 출금입니다.",
            "이번 달 카드 지출은 자비스 지출 리포트의 경과일을 월말로 늘린 금액입니다.",
            "그 다음 달부터의 월 지출은 지난달 카드와 이번 달 예상 카드의 평균입니다.",
            "예정 매출의 통장 입금은 공급가액에 부가세 10%를 더한 금액입니다.",
            "예정 지출의 통장 출금은 공급가액에 부가세 10%를 더한 금액입니다.",
            "예정 매출과 예정 지출은 화면에서 저장하면 data/plans.json에 기록됩니다.",
            "매출 부가세는 1월, 4월, 7월, 10월에 납부합니다. 1–3월분은 4월, 4–6월분은 7월, 7–9월분은 10월, 10–12월분은 다음 해 1월입니다.",
            "매입세액 공제는 빼지 않습니다. 이미 통장에서 나간 부가세는 다시 빼지 않습니다.",
            "예금 이자는 예상하지 않습니다. 예정 매출 외에 미래 매출은 0원이고, 예정 지출 외에 미래 매입은 0원입니다.",
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


def normalize_plans(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("plans must be an object")
    return {
        "sales": _plan_rows(payload.get("sales") or []),
        "expenses": _plan_rows(payload.get("expenses") or []),
    }


def _plan_rows(items: object) -> list[dict]:
    if not isinstance(items, list):
        raise ValueError("항목 목록이 올바르지 않습니다.")
    if len(items) > 50:
        raise ValueError("항목은 50개까지 입력합니다.")
    rows = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("항목 형식이 올바르지 않습니다.")
        plan_date = str(item.get("date") or "").strip()
        note = str(item.get("note") or "").strip()
        supply = item.get("supply")
        if plan_date == "" and note == "" and (supply is None or supply == ""):
            continue
        if not _valid_date(plan_date):
            raise ValueError("날짜는 YYYY-MM-DD로 입력합니다.")
        if isinstance(supply, bool) or not isinstance(supply, int) or supply <= 0:
            raise ValueError("공급가액은 0보다 큰 정수로 입력합니다.")
        if len(note) > 80:
            raise ValueError("메모는 80자까지 입력합니다.")
        row = {"date": plan_date, "supply": supply}
        if note:
            row["note"] = note
        rows.append(row)
    rows.sort(key=lambda row: (row["date"], row["supply"], row.get("note", "")))
    return rows


def _valid_date(value: str) -> bool:
    parts = value.split("-")
    if len(parts) != 3:
        return False
    try:
        year, month, day = (int(part) for part in parts)
    except ValueError:
        return False
    if f"{year:04d}-{month:02d}-{day:02d}" != value:
        return False
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def forecast_document(cash: dict, plans_doc: dict) -> dict:
    """Rebuild forecast rows from cashflow actuals and a plans document."""
    document = normalize_plans(plans_doc)
    if not cash.get("actuals"):
        raise ValueError("cashflow actuals are missing")
    sales = [_sale(item) for item in document["sales"]]
    expenses = [_expense(item) for item in document["expenses"]]
    actuals = [
        MonthActual(
            year=int(row["year"]),
            month=int(row["month"]),
            sales=int(row["sales"]),
            purchase=int(row["purchase"]),
            card=int(row["card"]),
            bank_in=int(row["bankIn"]),
            bank_out=int(row["bankOut"]),
            card_paid=int(row.get("cardPaid") or 0),
            vat_paid=int(row.get("vatPaid") or 0),
        )
        for row in cash["actuals"]
    ]
    as_of = datetime.strptime(cash["asOf"], "%Y-%m-%d").date()
    balances = {}
    for label, amount in (cash.get("balances") or {}).items():
        year, month = str(label).split("-")
        balances[(int(year), int(month))] = int(amount)
    forecast = build_forecast(actuals, as_of, int(cash["cashNow"]), sales, expenses=expenses)
    apply_actual_balances(forecast["rows"], balances)
    updated = dict(cash)
    updated["updatedAt"] = datetime.now(KST).isoformat(timespec="seconds")
    updated["baseExpense"] = forecast["baseExpense"]
    updated["currentMonthCard"] = forecast["currentMonthCard"]
    updated["monthComplete"] = forecast["monthComplete"]
    updated["depletion"] = forecast["depletion"]
    updated["plans"] = document["sales"]
    updated["expenses"] = document["expenses"]
    updated["rows"] = forecast["rows"]
    return updated


def save_plans(payload: dict) -> dict:
    """Write data/plans.json and refresh cashflow rows when actuals are stored."""
    document = normalize_plans(payload)
    PLANS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLANS_PATH.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cashflow = None
    if OUTPUT_PATH.exists():
        cash = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        if cash.get("actuals"):
            cashflow = forecast_document(cash, document)
            OUTPUT_PATH.write_text(json.dumps(cashflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "plans": document, "cashflow": cashflow}


def _sale(item: dict) -> PlannedSale:
    year, month, day = _date_parts(item["date"])
    return PlannedSale(year, month, day, int(item["supply"]))


def _expense(item: dict) -> PlannedExpense:
    year, month, day = _date_parts(item["date"])
    return PlannedExpense(year, month, day, int(item["supply"]), str(item.get("note") or ""))


def _date_parts(value: str) -> tuple[int, int, int]:
    year, month, day = (int(part) for part in str(value).split("-"))
    return year, month, day


if __name__ == "__main__":
    raise SystemExit(main())

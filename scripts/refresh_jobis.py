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
VAT_SETTLED_PATH = ROOT / "data" / "vat_settled.json"
STATEMENT_PATH = ROOT / "data" / "statement.json"
OUTPUT_PATH = ROOT / "data" / "cashflow.json"
KST = ZoneInfo("Asia/Seoul")
FILING_MONTHS = {1, 4, 7, 10}
ASSUMPTIONS = [
    "카드 대금은 사용 다음 달 통장 출금입니다.",
    "예상 카드 금액은 실제 발생한 최근 3개월 카드 지출의 평균입니다.",
    "이번 달 카드는 그 평균과 이미 쓴 금액 중 큰 금액으로 보고, 다음 달에 출금됩니다.",
    "예정 매출의 통장 입금은 공급가액에 부가세 10%를 더한 금액입니다.",
    "예정 지출의 통장 출금은 공급가액에 부가세 10%를 더한 금액입니다.",
    "예정 매출과 예정 지출은 화면에서 저장하면 data/plans.json에 기록됩니다.",
    "매출 부가세는 1월, 4월, 7월, 10월에 납부합니다. 1–3월분은 4월, 4–6월분은 7월, 7–9월분은 10월, 10–12월분은 다음 해 1월입니다.",
    "2026년 7–9월 매출 부가세는 10월 통장 출금 3,542,780원으로 이미 납부했습니다. 매출 공급가액의 10%를 그 위에 다시 빼지 않습니다.",
    "매입세액 공제는 빼지 않습니다. 이미 통장에서 나간 부가세는 다시 빼지 않습니다.",
    "예금 이자는 예상하지 않습니다. 예정 매출 외에 미래 매출은 0원이고, 예정 지출 외에 미래 매입은 0원입니다.",
]


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
    months = apply_known_vat_payments(snapshot["months"], load_settled_filings())
    balances = {}
    for label, amount in snapshot["balances"].items():
        year, month = label.split("-")
        balances[(int(year), int(month))] = amount
    overlaid = overlay_statement(
        months,
        as_of,
        int(snapshot["cashNow"]),
        balances,
        snapshot["cardMix"],
        snapshot["cardMixMonth"],
    )
    actuals = [_month_actual(row) for row in overlaid["months"]]
    forecast = build_forecast(
        actuals,
        overlaid["as_of"],
        overlaid["cash_now"],
        plans,
        expenses=expenses,
        settled_vat=load_settled_vat(),
    )
    apply_actual_balances(forecast["rows"], overlaid["balances"])

    document = {
        "company": "주식회사 투핸즈",
        "source": overlaid["source"],
        "asOf": overlaid["as_of"].isoformat(),
        "updatedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "currency": "KRW",
        "cashNow": overlaid["cash_now"],
        "baseExpense": forecast["baseExpense"],
        "currentMonthCard": forecast["currentMonthCard"],
        "monthComplete": forecast["monthComplete"],
        "depletion": forecast["depletion"],
        "plans": plans_doc["sales"],
        "expenses": plans_doc["expenses"],
        "actuals": overlaid["months"],
        "balances": {f"{year}-{month:02d}": amount for (year, month), amount in overlaid["balances"].items()},
        "cardMixMonth": overlaid["card_mix_month"],
        "cardMix": overlaid["card_mix"],
        "cardMixSource": overlaid["card_mix_source"],
        "cardMixNote": overlaid["card_mix_note"],
        "assumptions": ASSUMPTIONS + overlaid["assumptions"],
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
    months = apply_known_vat_payments(cash["actuals"], load_settled_filings())
    as_of = datetime.strptime(cash["asOf"], "%Y-%m-%d").date()
    balances = {}
    for label, amount in (cash.get("balances") or {}).items():
        year, month = str(label).split("-")
        balances[(int(year), int(month))] = int(amount)
    overlaid = overlay_statement(
        months,
        as_of,
        int(cash["cashNow"]),
        balances,
        cash.get("cardMix") or [],
        str(cash.get("cardMixMonth") or ""),
    )
    actuals = [_month_actual(row) for row in overlaid["months"]]
    forecast = build_forecast(
        actuals,
        overlaid["as_of"],
        overlaid["cash_now"],
        sales,
        expenses=expenses,
        settled_vat=load_settled_vat(),
    )
    apply_actual_balances(forecast["rows"], overlaid["balances"])
    updated = dict(cash)
    updated["updatedAt"] = datetime.now(KST).isoformat(timespec="seconds")
    updated["source"] = overlaid["source"] if overlaid["applied"] else cash.get("source") or "자비스"
    updated["asOf"] = overlaid["as_of"].isoformat()
    updated["cashNow"] = overlaid["cash_now"]
    updated["assumptions"] = ASSUMPTIONS + overlaid["assumptions"]
    updated["baseExpense"] = forecast["baseExpense"]
    updated["currentMonthCard"] = forecast["currentMonthCard"]
    updated["monthComplete"] = forecast["monthComplete"]
    updated["depletion"] = forecast["depletion"]
    updated["plans"] = document["sales"]
    updated["expenses"] = document["expenses"]
    updated["actuals"] = overlaid["months"]
    updated["balances"] = {f"{year}-{month:02d}": amount for (year, month), amount in overlaid["balances"].items()}
    updated["cardMix"] = overlaid["card_mix"]
    updated["cardMixMonth"] = overlaid["card_mix_month"]
    updated["cardMixSource"] = overlaid["card_mix_source"] if overlaid["applied"] else cash.get("cardMixSource") or "자비스 카드매입"
    updated["cardMixNote"] = overlaid["card_mix_note"] if overlaid["applied"] else cash.get("cardMixNote") or ""
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


def load_statement(path: Path | None = None) -> dict | None:
    """Bank and card statement used while Jobis is older than this file."""
    file = path or STATEMENT_PATH
    if not file.exists():
        return None
    payload = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("statement.json은 객체여야 합니다.")
    as_of = str(payload.get("asOf") or "")
    if not _valid_date(as_of):
        raise ValueError("statement.json의 asOf는 YYYY-MM-DD여야 합니다.")
    year = payload.get("year")
    month = payload.get("month")
    if isinstance(year, bool) or isinstance(month, bool) or not isinstance(year, int) or not isinstance(month, int):
        raise ValueError("statement.json의 연도와 월은 정수여야 합니다.")
    if not 1 <= month <= 12:
        raise ValueError("statement.json의 월이 올바르지 않습니다.")
    amounts = {}
    for key in ("cashNow", "sales", "bankIn", "bankOut", "card", "cardPaid"):
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"statement.json의 {key}는 0 이상의 정수여야 합니다.")
        amounts[key] = value
    if amounts["cardPaid"] > amounts["bankOut"]:
        raise ValueError("카드 선결제액은 그 달 통장 출금보다 클 수 없습니다.")
    return {
        "asOf": as_of,
        "year": year,
        "month": month,
        **amounts,
        "bankInLines": _statement_lines(payload.get("bankInLines"), amounts["bankIn"], "입금"),
        "bankOutLines": _statement_lines(payload.get("bankOutLines"), amounts["bankOut"], "출금"),
        "cardMix": _statement_lines(payload.get("cardMix"), amounts["card"], "카드"),
        "cardMixNote": str(payload.get("cardMixNote") or "").strip(),
        "note": str(payload.get("note") or "").strip(),
    }


def _statement_lines(lines: object, total: int, label: str) -> list[dict]:
    if not isinstance(lines, list):
        raise ValueError(f"statement.json의 {label} 목록이 올바르지 않습니다.")
    rows = []
    for item in lines:
        if not isinstance(item, dict):
            raise ValueError(f"statement.json의 {label} 항목 형식이 올바르지 않습니다.")
        name = str(item.get("name") or "").strip()
        amount = item.get("amount")
        if not name or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError(f"statement.json의 {label} 항목은 이름과 0보다 큰 금액이어야 합니다.")
        rows.append({"name": name, "amount": amount})
    if sum(row["amount"] for row in rows) != total:
        raise ValueError(f"statement.json의 {label} 합계가 맞지 않습니다.")
    return rows


def overlay_statement(
    months: list[dict],
    as_of: date,
    cash_now: int,
    balances: dict[tuple[int, int], int],
    card_mix: list,
    card_mix_month: str,
    path: Path | None = None,
) -> dict:
    """Use an uploaded statement when it is newer than the Jobis snapshot.

    A newer Jobis snapshot wins, so the excel figures drop out once Jobis is current.
    Applying the same statement again replaces the month with the same amounts.
    """
    statement = load_statement(path)
    result = {
        "months": months,
        "as_of": as_of,
        "cash_now": cash_now,
        "balances": balances,
        "card_mix": card_mix,
        "card_mix_month": card_mix_month,
        "source": "자비스",
        "card_mix_source": "자비스 카드매입",
        "card_mix_note": "",
        "assumptions": [],
        "applied": False,
    }
    if statement is None:
        return result
    stmt_date = datetime.strptime(statement["asOf"], "%Y-%m-%d").date()
    if stmt_date < as_of:
        return result
    if stmt_date == as_of and not _statement_already_applied(months, cash_now, statement):
        return result

    updated = months
    balances_out = balances
    current_cash = cash_now
    current_mix = card_mix
    current_mix_month = card_mix_month
    applied = False
    if stmt_date > as_of:
        updated = []
        found = False
        for row in months:
            copy = dict(row)
            if int(copy["year"]) == statement["year"] and int(copy["month"]) == statement["month"]:
                found = True
                copy["sales"] = statement["sales"]
                copy["bankIn"] = statement["bankIn"]
                copy["bankOut"] = statement["bankOut"]
                copy["card"] = statement["card"]
                copy["cardPaid"] = statement["cardPaid"]
                copy["bankInLines"] = statement["bankInLines"]
                copy["bankOutLines"] = statement["bankOutLines"]
                copy["endCash"] = statement["cashNow"]
            updated.append(copy)
        if not found:
            return result
        balances_out = dict(balances)
        balances_out[(statement["year"], statement["month"])] = statement["cashNow"]
        current_cash = statement["cashNow"]
        current_mix = statement["cardMix"]
        current_mix_month = f"{statement['year']}-{statement['month']:02d}"
        applied = True
    elif stmt_date == as_of:
        current_mix = statement["cardMix"]
        current_mix_month = f"{statement['year']}-{statement['month']:02d}"

    result.update(
        {
            "months": updated,
            "as_of": stmt_date if applied else as_of,
            "cash_now": current_cash,
            "balances": balances_out,
            "card_mix": current_mix,
            "card_mix_month": current_mix_month,
            "source": "농협 통장 · 현대카드",
            "card_mix_source": "현대카드 매출내역",
            "card_mix_note": statement["cardMixNote"],
            "assumptions": [statement["note"]] if statement["note"] else [],
            "applied": True,
        }
    )
    return result


def _statement_already_applied(months: list[dict], cash_now: int, statement: dict) -> bool:
    if cash_now != statement["cashNow"]:
        return False
    for row in months:
        if int(row["year"]) != statement["year"] or int(row["month"]) != statement["month"]:
            continue
        return (
            int(row.get("bankIn") or 0) == statement["bankIn"]
            and int(row.get("bankOut") or 0) == statement["bankOut"]
            and int(row.get("card") or 0) == statement["card"]
        )
    return False


def load_settled_filings(path: Path | None = None) -> list[dict]:
    """Filing months whose output VAT already left the bank."""
    file = path or VAT_SETTLED_PATH
    if not file.exists():
        return []
    payload = json.loads(file.read_text(encoding="utf-8"))
    filings = payload.get("filings") if isinstance(payload, dict) else None
    if not isinstance(filings, list):
        raise ValueError("vat_settled.json의 filings는 목록이어야 합니다.")
    settled: list[dict] = []
    for item in filings:
        if not isinstance(item, dict):
            raise ValueError("납부한 부가세 신고월 형식이 올바르지 않습니다.")
        year = item.get("year")
        month = item.get("month")
        if isinstance(year, bool) or isinstance(month, bool) or not isinstance(year, int) or not isinstance(month, int):
            raise ValueError("납부한 부가세의 연도와 월은 정수여야 합니다.")
        if month not in FILING_MONTHS:
            raise ValueError("납부한 부가세의 월은 1, 4, 7, 10 중 하나여야 합니다.")
        amount = item.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError("납부한 부가세 금액은 0보다 큰 정수여야 합니다.")
        settled.append({"year": year, "month": month, "amount": amount})
    return settled


def load_settled_vat(path: Path | None = None) -> list[tuple[int, int]]:
    return [(item["year"], item["month"]) for item in load_settled_filings(path)]


def apply_known_vat_payments(months: list[dict], filings: list[dict]) -> list[dict]:
    """Record a known VAT payment that Jobis did not classify as 부가세납부.

    The amount is already inside that month's bank withdrawal, so it is capped
    by bankOut and is not added to the forecast again.
    """
    paid = {(item["year"], item["month"]): item["amount"] for item in filings}
    stamped: list[dict] = []
    for row in months:
        copy = dict(row)
        amount = paid.get((int(copy["year"]), int(copy["month"])))
        if amount is not None:
            bank_out = int(copy.get("bankOut") or 0)
            current = int(copy.get("vatPaid") or 0)
            copy["vatPaid"] = min(bank_out, max(current, amount))
        stamped.append(copy)
    return stamped


def _month_actual(row: dict) -> MonthActual:
    return MonthActual(
        year=int(row["year"]),
        month=int(row["month"]),
        sales=int(row["sales"]),
        purchase=int(row["purchase"]),
        card=int(row["card"]),
        bank_in=int(row["bankIn"]),
        bank_out=int(row["bankOut"]),
        card_paid=int(row.get("cardPaid") or 0),
        vat_paid=int(row.get("vatPaid") or 0),
        bank_out_lines=_line_pairs(row.get("bankOutLines")),
        bank_in_lines=_line_pairs(row.get("bankInLines")),
    )


def _line_pairs(lines: object) -> tuple[tuple[str, int], ...]:
    if not isinstance(lines, list):
        return ()
    pairs = []
    for item in lines:
        if not isinstance(item, dict):
            continue
        amount = item.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            continue
        pairs.append((str(item.get("name") or "미분류"), amount))
    return tuple(pairs)


def _sale(item: dict) -> PlannedSale:
    year, month, day = _date_parts(item["date"])
    return PlannedSale(year, month, day, int(item["supply"]), str(item.get("note") or ""))


def _expense(item: dict) -> PlannedExpense:
    year, month, day = _date_parts(item["date"])
    return PlannedExpense(year, month, day, int(item["supply"]), str(item.get("note") or ""))


def _date_parts(value: str) -> tuple[int, int, int]:
    year, month, day = (int(part) for part in str(value).split("-"))
    return year, month, day


if __name__ == "__main__":
    raise SystemExit(main())

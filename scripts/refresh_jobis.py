#!/usr/bin/env python3
"""Refresh data/cashflow.json.

Bank balance and bank deposits/withdrawals come from data/bank_nh.json (농협
법인통장, masked account). Jobis is read only for card totals and the card
mix. A Jobis outage keeps the last saved card figures and still updates the
bank. Credentials stay in the environment and are never written to the repo.
"""

from __future__ import annotations

import json
from decimal import Decimal
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from forecast import (
    MonthActual,
    PlannedExpense,
    PlannedSale,
    TimeDeposit,
    apply_actual_balances,
    build_forecast,
    time_deposit_interest,
)
from jobis_client import JobisClient

ROOT = Path(__file__).resolve().parents[1]
PLANS_PATH = ROOT / "data" / "plans.json"
VAT_SETTLED_PATH = ROOT / "data" / "vat_settled.json"
DEPOSITS_PATH = ROOT / "data" / "deposits.json"
BANK_PATH = ROOT / "data" / "bank_nh.json"
OUTPUT_PATH = ROOT / "data" / "cashflow.json"
KST = ZoneInfo("Asia/Seoul")
FILING_MONTHS = {1, 4, 7, 10}
ACCOUNT_MASK = re.compile(r"^\*+\d{4}$")
MATURITY_RE = re.compile(r"만기\s*(\d{4}-\d{2}-\d{2})")
CARD_FALLBACK_NOTE = "이번 계산은 자비스를 읽지 못해, 카드 사용액과 카드 구성을 마지막으로 저장한 금액으로 유지합니다."
ASSUMPTIONS = [
    "통장 잔액과 통장 입출금은 농협 법인통장(****6481) 빠른조회입니다. 자비스의 통장 숫자는 쓰지 않습니다.",
    "카드 사용액은 자비스 카드 내역입니다. 자비스를 읽지 못하면 마지막으로 저장한 카드 금액을 유지합니다.",
    "카드 대금은 사용 다음 달 통장 출금입니다.",
    "예상 카드 금액은 실제 발생한 최근 3개월 카드 지출의 평균입니다.",
    "이번 달 카드는 그 평균과 이미 쓴 금액 중 큰 금액으로 보고, 다음 달에 출금됩니다.",
    "예정 매출의 통장 입금은 공급가액에 부가세 10%를 더한 금액입니다.",
    "예정 지출의 통장 출금은 공급가액에 부가세 10%를 더한 금액입니다.",
    "예정 매출과 예정 지출은 화면에서 저장하면 data/plans.json에 기록됩니다.",
    "매출 부가세는 1월, 4월, 7월, 10월에 납부합니다. 1–3월분은 4월, 4–6월분은 7월, 7–9월분은 10월, 10–12월분은 다음 해 1월입니다.",
    "2026년 7–9월 매출 부가세는 10월 통장 출금 3,542,780원으로 이미 납부했습니다. 매출 공급가액의 10%를 그 위에 다시 빼지 않습니다.",
    "매입세액 공제는 빼지 않습니다. 이미 통장에서 나간 부가세는 다시 빼지 않습니다.",
    "정기예금으로 적어 둔 이자만 만기에 넣고, 그 외 예금 이자는 예상하지 않습니다. 예정 매출 외에 미래 매출은 0원이고, 예정 지출 외에 미래 매입은 0원입니다.",
    "적요에 정기예금이 들어 있는 출금은 지출이 아닙니다. 원금과 세후 이자는 만기에 통장으로 돌아오는 것으로 보고, 세전 이자에서 법인세 원천징수 14%와 지방소득세 1.4%(합계 15.4%)를 뗍니다. 금리는 data/deposits.json에 둡니다.",
]


def main() -> int:
    if not OUTPUT_PATH.exists():
        print("data/cashflow.json is missing; refusing to drop the last saved card figures", file=sys.stderr)
        return 1
    try:
        bank = load_bank_nh()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"data/bank_nh.json: {exc}", file=sys.stderr)
        return 1

    previous = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    cards = fetch_jobis_cards(datetime.now(KST).date())
    document = assemble_cashflow(previous, bank, cards)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if document.get("cardFallback") and cards is not None:
        print("Jobis card data is older or empty; keeping the last saved card figures", file=sys.stderr)
    print(
        f"wrote {OUTPUT_PATH.name} asOf={document['asOf']} cash={document['cashNow']} "
        f"base={document['baseExpense']} rows={len(document['rows'])} "
        f"cards={'saved' if document.get('cardFallback') else 'jobis'}"
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


def forecast_document(cash: dict, plans_doc: dict, deposits_doc: list | dict | None = None) -> dict:
    """Rebuild forecast rows from cashflow actuals and a plans document.

    Bank figures already stored on the document stay as they are. This path
    does not read Jobis and does not replace the bank with a manual statement.
    """
    document = normalize_plans(plans_doc)
    if not cash.get("actuals"):
        raise ValueError("cashflow actuals are missing")
    sales = [_sale(item) for item in document["sales"]]
    expenses = [_expense(item) for item in document["expenses"]]
    months = apply_known_vat_payments(cash["actuals"], load_settled_filings())
    as_of = datetime.strptime(str(cash["asOf"])[:10], "%Y-%m-%d").date()
    balances = {}
    for label, amount in (cash.get("balances") or {}).items():
        year, month = str(label).split("-")
        balances[(int(year), int(month))] = int(amount)
    actuals = [_month_actual(row) for row in months]
    deposits = _active_deposits(
        _merge_deposit_items(cash.get("deposits") or [], _configured_deposits(deposits_doc)),
        as_of,
    )
    forecast = build_forecast(
        actuals,
        as_of,
        int(cash["cashNow"]),
        sales,
        expenses=expenses,
        settled_vat=load_settled_vat(),
        time_deposits=_time_deposit_models(deposits),
    )
    apply_actual_balances(forecast["rows"], balances)
    updated = dict(cash)
    updated["updatedAt"] = datetime.now(KST).isoformat(timespec="seconds")
    updated["asOf"] = as_of.isoformat()
    updated["cashNow"] = int(cash["cashNow"])
    assumptions = list(ASSUMPTIONS)
    if updated.get("cardFallback"):
        assumptions.append(CARD_FALLBACK_NOTE)
    updated["assumptions"] = assumptions
    updated["baseExpense"] = forecast["baseExpense"]
    updated["currentMonthCard"] = forecast["currentMonthCard"]
    updated["monthComplete"] = forecast["monthComplete"]
    updated["depletion"] = forecast["depletion"]
    updated["plans"] = document["sales"]
    updated["expenses"] = document["expenses"]
    updated["deposits"] = deposits
    updated["totalFunds"] = int(cash["cashNow"]) + sum(item["principal"] for item in deposits)
    updated["actuals"] = months
    updated["balances"] = {f"{year}-{month:02d}": amount for (year, month), amount in sorted(balances.items())}
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


def fetch_jobis_cards(today: date) -> dict | None:
    """Card totals and mix from Jobis. None when Jobis cannot be read.

    Bank rows in the snapshot are discarded by the caller. An empty dashboard
    body, a login failure, or missing credentials all return None.
    """
    email = os.environ.get("JOBIS_EMAIL", "").strip()
    password = os.environ.get("JOBIS_PASSWORD", "")
    if not email or not password:
        print("JOBIS_EMAIL and JOBIS_PASSWORD are missing; keeping the last saved card figures", file=sys.stderr)
        return None
    try:
        client = JobisClient(email, password)
        client.login()
        snapshot = client.snapshot(today)
    except Exception as exc:
        print(f"Jobis unavailable ({type(exc).__name__}); keeping the last saved card figures", file=sys.stderr)
        return None
    cards = {}
    for row in snapshot.get("months") or []:
        cards[(int(row["year"]), int(row["month"]))] = int(row.get("card") or 0)
    return {
        "asOf": str(snapshot.get("asOf") or "")[:10],
        "cards": cards,
        "cardMix": list(snapshot.get("cardMix") or []),
        "cardMixMonth": str(snapshot.get("cardMixMonth") or ""),
    }


def load_bank_nh(path: Path | None = None) -> dict:
    """Read the NH quick-lookup file. See the schema note on parse_bank_nh."""
    file = path or BANK_PATH
    payload = json.loads(file.read_text(encoding="utf-8"))
    return parse_bank_nh(payload)


def parse_bank_nh(payload: object) -> dict:
    """Normalize one NH 기업뱅킹 빠른조회 file.

    Schema:
      account       masked, stars plus the last four digits, e.g. "****6481"
      queriedAt     ISO 8601 with a timezone offset
      balance       ledger balance in won (this becomes cashNow)
      available     withdrawable balance in won
      transactions  full set for every month included, not a delta. The queried
                    month may be empty. Exact duplicates are ignored. Order does
                    not matter. Months absent from the list keep their last
                    published bank figures.
      each transaction:
        datetime, deposit, withdrawal, balanceAfter, description, memo
    The full account number, PIN, and business number must not appear.
    """
    if not isinstance(payload, dict):
        raise ValueError("bank_nh.json은 객체여야 합니다.")
    account = str(payload.get("account") or "").strip()
    if not ACCOUNT_MASK.fullmatch(account):
        raise ValueError("account는 마스킹된 끝 네 자리여야 합니다. 예: ****6481")
    queried_at = _parse_timestamptz(payload.get("queriedAt"), "queriedAt")
    raw_rows = payload.get("transactions")
    if not isinstance(raw_rows, list):
        raise ValueError("transactions는 목록이어야 합니다.")
    seen: set[tuple] = set()
    transactions = []
    for item in raw_rows:
        row = _parse_bank_tx(item)
        key = (
            row["datetime"],
            row["deposit"],
            row["withdrawal"],
            row["balanceAfter"],
            row["description"],
            row["memo"],
        )
        if key in seen:
            continue
        seen.add(key)
        transactions.append(row)
    return {
        "account": account,
        "queriedAt": queried_at.isoformat(timespec="seconds"),
        "queriedOn": queried_at.date(),
        "balance": _won_amount(payload.get("balance"), "balance"),
        "available": _won_amount(payload.get("available"), "available"),
        "transactions": transactions,
    }


def assemble_cashflow(
    previous: dict,
    bank: dict,
    cards: dict | None,
    plans_doc: dict | None = None,
    deposits_doc: list | dict | None = None,
) -> dict:
    """Build a cashflow document from the last file, the NH account, and optional Jobis cards."""
    if "queriedOn" not in bank:
        bank = parse_bank_nh(bank)
    if plans_doc is None:
        plans_doc = (
            json.loads(PLANS_PATH.read_text(encoding="utf-8"))
            if PLANS_PATH.exists()
            else {"sales": [], "expenses": []}
        )
    plans_doc = normalize_plans(plans_doc)
    configured = _configured_deposits(deposits_doc)
    merged = _merge_bank_and_cards(previous, bank, cards, plans_doc["sales"], configured)
    return forecast_document(merged, plans_doc, deposits_doc=configured)


def _merge_bank_and_cards(
    previous: dict,
    bank: dict,
    cards: dict | None,
    plan_sales: list[dict],
    configured: list[dict] | None = None,
) -> dict:
    months = [dict(row) for row in previous.get("actuals") or []]
    for row in months:
        row["bankInLines"] = [dict(item) for item in row.get("bankInLines") or []]
        row["bankOutLines"] = [dict(item) for item in row.get("bankOutLines") or []]
    balances = _balance_map(previous.get("balances") or {})
    queried = bank["queriedOn"]
    grouped: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for tx in bank["transactions"]:
        stamp = datetime.fromisoformat(tx["datetime"])
        grouped[(stamp.year, stamp.month)].append(tx)
    months = _ensure_months(months, queried, set(grouped))
    by_month = {(int(row["year"]), int(row["month"])): row for row in months}
    touched = set(grouped) | {(queried.year, queried.month)}
    for key in touched:
        row = by_month.get(key)
        if row is None:
            continue
        txns = grouped.get(key, [])
        live = bank["balance"] if key == (queried.year, queried.month) else None
        _fill_bank_row(row, txns, live)
        if live is not None:
            balances[key] = live
        elif txns:
            last = max(txns, key=lambda item: item["datetime"])
            balances[key] = int(last["balanceAfter"])
        _recognize_plan_deposits(row, txns, plan_sales)
    use_cards = _jobis_cards_usable(previous, cards)
    if use_cards and cards is not None:
        for row in months:
            key = (int(row["year"]), int(row["month"]))
            if key in cards["cards"]:
                row["card"] = int(cards["cards"][key])
        card_mix = [dict(item) for item in cards["cardMix"]]
        card_mix_month = cards["cardMixMonth"]
        card_mix_source = "자비스 카드매입"
        card_mix_note = ""
        card_as_of = cards["asOf"]
        source = "농협 통장 · 자비스 카드"
        card_fallback = False
    else:
        card_mix = [dict(item) for item in previous.get("cardMix") or []]
        card_mix_month = str(previous.get("cardMixMonth") or "")
        card_mix_source = str(previous.get("cardMixSource") or "현대카드 매출내역")
        card_mix_note = str(previous.get("cardMixNote") or "")
        stored = _stored_card_date(previous)
        card_as_of = stored.isoformat() if stored else ""
        source = "농협 통장 · 자비스 카드" if "자비스" in card_mix_source else "농협 통장 · 현대카드"
        card_fallback = True
    return {
        "company": previous.get("company") or "주식회사 투핸즈",
        "source": source,
        "asOf": queried.isoformat(),
        "currency": previous.get("currency") or "KRW",
        "cashNow": int(bank["balance"]),
        "deposits": _collect_time_deposits(previous, bank, queried, configured or []),
        "actuals": months,
        "balances": {f"{year}-{month:02d}": amount for (year, month), amount in sorted(balances.items())},
        "cardMix": card_mix,
        "cardMixMonth": card_mix_month,
        "cardMixSource": card_mix_source,
        "cardMixNote": card_mix_note,
        "cardAsOf": card_as_of,
        "cardFallback": card_fallback,
    }


def _jobis_cards_usable(previous: dict, cards: dict | None) -> bool:
    """Use Jobis cards only when the snapshot is at least as new as the saved card book."""
    if not cards or not _valid_date(str(cards.get("asOf") or "")):
        return False
    if _cards_look_empty(cards) and _previous_has_cards(previous):
        return False
    jobis_date = datetime.strptime(cards["asOf"], "%Y-%m-%d").date()
    stored = _stored_card_date(previous)
    if stored is not None and jobis_date < stored:
        return False
    return True


def _cards_look_empty(cards: dict) -> bool:
    if cards.get("cardMix"):
        return False
    return not any(int(amount) for amount in (cards.get("cards") or {}).values())


def _previous_has_cards(previous: dict) -> bool:
    if previous.get("cardMix"):
        return True
    return any(int(row.get("card") or 0) for row in previous.get("actuals") or [])


def _stored_card_date(previous: dict) -> date | None:
    """Date of the card figures already published. The bank asOf is not a card date."""
    raw = str(previous.get("cardAsOf") or "")
    if _valid_date(raw):
        return datetime.strptime(raw, "%Y-%m-%d").date()
    if previous.get("cardAsOf"):
        return None
    legacy = str(previous.get("asOf") or "")[:10]
    if _valid_date(legacy):
        return datetime.strptime(legacy, "%Y-%m-%d").date()
    return None


def _ensure_months(months: list[dict], queried: date, extra: set[tuple[int, int]]) -> list[dict]:
    by = {(int(row["year"]), int(row["month"])): row for row in months}
    keys = set(by) | set(extra) | {(queried.year, queried.month)}
    start = min(keys)
    end = (queried.year, queried.month)
    if end < start:
        end = start
    ordered = []
    cursor = start
    while cursor <= end:
        ordered.append(by.get(cursor) or _blank_month(*cursor))
        cursor = (cursor[0] + 1, 1) if cursor[1] == 12 else (cursor[0], cursor[1] + 1)
    return ordered


def _blank_month(year: int, month: int) -> dict:
    return {
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


def _fill_bank_row(row: dict, txns: list[dict], live_balance: int | None) -> None:
    incoming: dict[str, int] = defaultdict(int)
    outgoing: dict[str, int] = defaultdict(int)
    card_paid = 0
    vat_paid = 0
    for tx in txns:
        name = tx["memo"] or tx["description"] or "미분류"
        text = f"{tx['description']} {tx['memo']}"
        if tx["deposit"]:
            incoming[name] += tx["deposit"]
        if tx["withdrawal"] and "정기예금" not in text:
            outgoing[name] += tx["withdrawal"]
            if "카드" in text:
                card_paid += tx["withdrawal"]
            if "부가세" in text:
                vat_paid += tx["withdrawal"]
    row["bankIn"] = sum(incoming.values())
    row["bankOut"] = sum(outgoing.values())
    row["bankInLines"] = _sorted_lines(incoming)
    row["bankOutLines"] = _sorted_lines(outgoing)
    row["cardPaid"] = card_paid
    row["vatPaid"] = vat_paid
    if live_balance is not None:
        row["endCash"] = live_balance
    elif txns:
        last = max(txns, key=lambda item: item["datetime"])
        row["endCash"] = int(last["balanceAfter"])


def load_deposit_config(path: Path | None = None) -> list[dict]:
    """Rates and terms for time deposits. See data/deposits.json."""
    file = path or DEPOSITS_PATH
    if not file.exists():
        return []
    payload = json.loads(file.read_text(encoding="utf-8"))
    items = payload.get("deposits") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError("deposits.json의 deposits는 목록이어야 합니다.")
    return items


def _configured_deposits(deposits_doc: list | dict | None) -> list[dict]:
    if deposits_doc is None:
        return load_deposit_config()
    if isinstance(deposits_doc, dict):
        items = deposits_doc.get("deposits") or []
        if not isinstance(items, list):
            raise ValueError("deposits 목록이 올바르지 않습니다.")
        return items
    if not isinstance(deposits_doc, list):
        raise ValueError("deposits 목록이 올바르지 않습니다.")
    return deposits_doc


def _collect_time_deposits(
    previous: dict, bank: dict, as_of: date, configured: list[dict] | None = None
) -> list[dict]:
    """Time deposits from the bank file, the config, and the last cashflow."""
    return _active_deposits(
        _merge_deposit_items(
            list(previous.get("deposits") or []),
            _time_deposits_from_transactions(bank.get("transactions") or []),
            configured or [],
        ),
        as_of,
    )


def _merge_deposit_items(*groups: list) -> list[dict]:
    by_key: dict[tuple[str, int], dict] = {}
    for group in groups:
        for item in group:
            if not isinstance(item, dict):
                continue
            opened = str(item.get("opened") or "")
            principal = item.get("principal")
            if not _valid_date(opened) or not isinstance(principal, int) or isinstance(principal, bool) or principal <= 0:
                continue
            prev = by_key.get((opened, principal), {})
            merged = dict(prev)
            merged.update(item)
            by_key[(opened, principal)] = merged
    return list(by_key.values())


def _time_deposits_from_transactions(txns: list[dict]) -> list[dict]:
    found: list[dict] = []
    for tx in txns:
        if int(tx.get("withdrawal") or 0) <= 0:
            continue
        text = f"{tx.get('description') or ''} {tx.get('memo') or ''}"
        if "정기예금" not in text:
            continue
        match = MATURITY_RE.search(text)
        if not match or not _valid_date(match.group(1)):
            continue
        opened = datetime.fromisoformat(tx["datetime"]).date().isoformat()
        found.append(
            {
                "principal": int(tx["withdrawal"]),
                "opened": opened,
                "maturity": match.group(1),
                "note": "정기예금",
            }
        )
    return found


def _active_deposits(items: list, as_of: date) -> list[dict]:
    active: list[dict] = []
    seen: set[tuple[str, str, int]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        principal = item.get("principal")
        opened = str(item.get("opened") or "")
        maturity = str(item.get("maturity") or "")
        if not isinstance(principal, int) or isinstance(principal, bool) or principal <= 0:
            continue
        if not _valid_date(opened) or not _valid_date(maturity):
            continue
        if date.fromisoformat(opened) > as_of:
            continue
        if date.fromisoformat(maturity) <= as_of:
            continue
        key = (opened, maturity, principal)
        if key in seen:
            continue
        seen.add(key)
        row = {"principal": principal, "opened": opened, "maturity": maturity, "note": "정기예금"}
        note = str(item.get("note") or "").strip()
        if note:
            row["note"] = note
        rate = _parse_rate(item.get("rate"))
        if rate is not None:
            gross, tax, net = time_deposit_interest(principal, rate)
            row["rate"] = float(rate)
            row["grossInterest"] = gross
            row["withholding"] = tax
            row["netInterest"] = net
            row["maturityAmount"] = principal + net
        active.append(row)
    active.sort(key=lambda row: (row["opened"], row["maturity"], row["principal"]))
    return active


def _time_deposit_models(items: list[dict]) -> list[TimeDeposit]:
    return [
        TimeDeposit(
            principal=item["principal"],
            opened=date.fromisoformat(item["opened"]),
            maturity=date.fromisoformat(item["maturity"]),
            note=str(item.get("note") or "정기예금"),
            rate=_parse_rate(item.get("rate")),
            gross_interest=int(item.get("grossInterest") or 0),
            withholding=int(item.get("withholding") or 0),
            net_interest=int(item.get("netInterest") or 0),
        )
        for item in items
    ]


def _parse_rate(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError("정기예금 금리는 숫자여야 합니다.")
    rate = Decimal(str(value))
    if rate < 0:
        raise ValueError("정기예금 금리는 0 이상이어야 합니다.")
    return rate


def _recognize_plan_deposits(row: dict, txns: list[dict], plans: list) -> None:
    """A deposit equal to a plan's supply plus 10% VAT is that sale, already in the bank.

    Counting it again as a future deposit would double the cash. Sales already
    recorded on the month are kept when they are larger.
    """
    deposits = [int(tx["deposit"]) for tx in txns if int(tx["deposit"]) > 0]
    if not deposits or not isinstance(plans, list):
        return
    used: set[int] = set()
    recognized = 0
    key = (int(row["year"]), int(row["month"]))
    for item in plans:
        supply = item.get("supply") if isinstance(item, dict) else None
        if not isinstance(item, dict) or isinstance(supply, bool) or not isinstance(supply, int) or supply <= 0:
            continue
        if not _valid_date(str(item.get("date") or "")):
            continue
        plan = _sale(item)
        if (plan.year, plan.month) != key:
            continue
        for index, amount in enumerate(deposits):
            if index in used or amount != plan.gross:
                continue
            used.add(index)
            recognized += plan.supply
            break
    if recognized > int(row.get("sales") or 0):
        row["sales"] = recognized


def _sorted_lines(amounts: dict[str, int]) -> list[dict]:
    return [
        {"name": name, "amount": amount}
        for name, amount in sorted(amounts.items(), key=lambda item: (-item[1], item[0]))
        if amount
    ]


def _balance_map(balances: dict) -> dict[tuple[int, int], int]:
    parsed = {}
    for label, amount in balances.items():
        year, month = str(label).split("-")
        parsed[(int(year), int(month))] = int(amount)
    return parsed


def _parse_timestamptz(value: object, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{label}은 시간대가 있는 ISO 8601이어야 합니다.") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label}은 시간대가 있어야 합니다. 예: 2026-11-25T13:43:24+09:00")
    return parsed


def _parse_bank_tx(item: object) -> dict:
    if not isinstance(item, dict):
        raise ValueError("transactions 항목은 객체여야 합니다.")
    stamp = _parse_timestamptz(item.get("datetime"), "transactions.datetime")
    return {
        "datetime": stamp.isoformat(timespec="seconds"),
        "deposit": _won_amount(item.get("deposit"), "deposit", allow_negative=False),
        "withdrawal": _won_amount(item.get("withdrawal"), "withdrawal", allow_negative=False),
        "balanceAfter": _won_amount(item.get("balanceAfter"), "balanceAfter"),
        "description": str(item.get("description") or "").strip(),
        "memo": str(item.get("memo") or "").strip(),
    }


def _won_amount(value: object, label: str, allow_negative: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label}은 정수 원 금액이어야 합니다.")
    if not allow_negative and value < 0:
        raise ValueError(f"{label}은 0 이상의 정수여야 합니다.")
    return value


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

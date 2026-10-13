"""Cashflow forecast from Jobis month totals.

Amounts are integer won. Divisions use half-up rounding, the same rule as
Math.round for positive numbers.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP


def half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class MonthActual:
    year: int
    month: int
    sales: int
    purchase: int
    card: int
    bank_in: int
    bank_out: int
    card_paid: int


@dataclass(frozen=True)
class PlannedSale:
    year: int
    month: int
    day: int
    supply: int

    @property
    def vat(self) -> int:
        return half_up(Decimal(self.supply) * Decimal("0.1"))

    @property
    def gross(self) -> int:
        return self.supply + self.vat


def vat_due(year: int, month: int) -> tuple[int, int]:
    """When a sale's VAT leaves the bank: H1 in July, H2 in January."""
    if month <= 6:
        return year, 7
    return year + 1, 1


def _key(year: int, month: int) -> tuple[int, int]:
    return year, month


def _add_month(year: int, month: int, step: int = 1) -> tuple[int, int]:
    index = year * 12 + (month - 1) + step
    return index // 12, index % 12 + 1


def build_forecast(
    actuals: list[MonthActual],
    as_of: date,
    cash_now: int,
    plans: list[PlannedSale],
    horizon_years: int = 3,
) -> dict:
    if not actuals:
        raise ValueError("no actual months")
    by_month = {_key(row.year, row.month): row for row in actuals}
    current = _key(as_of.year, as_of.month)
    if current not in by_month:
        raise ValueError("actuals must include the as-of month")

    days = calendar.monthrange(as_of.year, as_of.month)[1]
    month_complete = as_of.day >= days
    current_row = by_month[current]
    if month_complete or as_of.day <= 0:
        card_run_rate = current_row.card
    else:
        card_run_rate = half_up(Decimal(current_row.card) / Decimal(as_of.day) * Decimal(days))

    previous = _add_month(as_of.year, as_of.month, -1)
    last_full_card = by_month[previous].card if previous in by_month else 0
    if month_complete:
        earlier = _add_month(previous[0], previous[1], -1)
        earlier_card = by_month[earlier].card if earlier in by_month else last_full_card
        base = half_up(Decimal(earlier_card + current_row.card) / Decimal(2))
        anchor_card = current_row.card
    else:
        base = half_up(Decimal(last_full_card + card_run_rate) / Decimal(2))
        anchor_card = card_run_rate

    booked = _booked_plans(plans, by_month, as_of, month_complete)
    vat_by_month: dict[tuple[int, int], int] = {}
    for plan in booked:
        due = vat_due(plan.year, plan.month)
        if due < current or (due == current and month_complete):
            continue
        vat_by_month[due] = vat_by_month.get(due, 0) + plan.vat

    rows: list[dict] = []
    ordered = sorted(by_month)
    for key in ordered:
        if key > current:
            continue
        row = by_month[key]
        if key < current or month_complete:
            rows.append(_actual_row(row))
            continue
        remaining_bill = max(0, last_full_card - row.card_paid)
        plan_supply, plan_gross = _plan_amounts(booked, key, row.sales)
        end_cash = cash_now - remaining_bill + plan_gross
        rows.append(
            {
                "year": row.year,
                "month": row.month,
                "status": "예정" if plan_supply else "진행",
                "sales": row.sales + plan_supply,
                "purchase": row.purchase,
                "card": card_run_rate,
                "bankIn": row.bank_in + plan_gross,
                "bankOut": row.bank_out + remaining_bill + vat_by_month.get(key, 0),
                "endCash": end_cash - vat_by_month.get(key, 0),
            }
        )

    cash = rows[-1]["endCash"]
    bill = anchor_card
    spend = base
    end_key = _key(as_of.year + horizon_years, 12)
    cursor = current if month_complete else _add_month(as_of.year, as_of.month, 1)
    guard = _key(as_of.year + horizon_years + 6, 12)
    while cursor <= guard:
        plan_supply, plan_gross = _plan_amounts(booked, cursor, already_sales=0)
        vat = vat_by_month.get(cursor, 0)
        bank_out = bill + vat
        cash = cash - bank_out + plan_gross
        rows.append(
            {
                "year": cursor[0],
                "month": cursor[1],
                "status": "예정" if plan_supply else "예상",
                "sales": plan_supply,
                "purchase": 0,
                "card": spend,
                "bankIn": plan_gross,
                "bankOut": bank_out,
                "endCash": cash,
            }
        )
        if cursor >= end_key and cash < 0:
            break
        bill = spend
        cursor = _add_month(cursor[0], cursor[1], 1)

    depletion = _depletion(rows)
    return {
        "baseExpense": base,
        "currentMonthCard": anchor_card,
        "monthComplete": month_complete,
        "depletion": depletion,
        "rows": rows,
    }


def _booked_plans(
    plans: list[PlannedSale],
    by_month: dict[tuple[int, int], MonthActual],
    as_of: date,
    month_complete: bool,
) -> list[PlannedSale]:
    kept: list[PlannedSale] = []
    for plan in plans:
        key = _key(plan.year, plan.month)
        actual = by_month.get(key)
        if actual and actual.sales >= int(plan.supply * 0.9):
            continue
        if key < _key(as_of.year, as_of.month):
            continue
        if key == _key(as_of.year, as_of.month) and month_complete:
            continue
        kept.append(plan)
    return kept


def _plan_amounts(plans: list[PlannedSale], key: tuple[int, int], already_sales: int) -> tuple[int, int]:
    supply = 0
    gross = 0
    for plan in plans:
        if _key(plan.year, plan.month) != key:
            continue
        if already_sales >= int(plan.supply * 0.9):
            continue
        supply += plan.supply
        gross += plan.gross
    return supply, gross


def _actual_row(row: MonthActual) -> dict:
    return {
        "year": row.year,
        "month": row.month,
        "status": "실제",
        "sales": row.sales,
        "purchase": row.purchase,
        "card": row.card,
        "bankIn": row.bank_in,
        "bankOut": row.bank_out,
        "endCash": 0,
    }


def apply_actual_balances(rows: list[dict], balances: dict[tuple[int, int], int]) -> None:
    """Fill month-end cash for closed months from the Jobis balance series."""
    for row in rows:
        if row["status"] != "실제":
            continue
        key = (row["year"], row["month"])
        if key in balances:
            row["endCash"] = balances[key]


def _depletion(rows: list[dict]) -> dict | None:
    for index, row in enumerate(rows):
        if row["endCash"] >= 0:
            continue
        opening = rows[index - 1]["endCash"] if index else 0
        length = calendar.monthrange(row["year"], row["month"])[1]
        outflow = row["bankOut"] or 1
        day = half_up(Decimal(opening) / Decimal(outflow) * Decimal(length))
        day = max(1, min(length, day))
        return {"year": row["year"], "month": row["month"], "day": day}
    return None

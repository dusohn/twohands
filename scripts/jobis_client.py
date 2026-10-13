"""Read-only Jobis client. Responses are reduced to monthly totals.

Account numbers, card numbers, and registration numbers are never returned.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from http.cookiejar import CookieJar


BASE = "https://service.jobisbiz.co"
START_YEAR = 2026


def won(value) -> int:
    if value is None or value == "":
        return 0
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class JobisClient:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def login(self) -> None:
        self._open(f"{BASE}/signup/login")
        self._open(
            f"{BASE}/signup/login_act",
            urllib.parse.urlencode(
                {
                    "useremail": self.email,
                    "passwd": self.password,
                    "token": "",
                    "rurl": "",
                    "username": "",
                    "phone": "",
                }
            ).encode(),
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        status, body, _ = self._open(f"{BASE}/financial/dashboard")
        text = body.decode("utf-8", errors="replace")
        if status != 200 or "form_login" in text or 'name="passwd"' in text:
            raise RuntimeError("Jobis login failed")

    def snapshot(self, today: date) -> dict:
        self._post_json("/financial/api_dashboard_init", {})
        hit = self._post_json("/financial/api_dashboard_hit", {})
        as_of = _as_of(hit, today)

        expense_years = {}
        balance_years = {}
        for year in range(START_YEAR, as_of.year + 1):
            end_month = as_of.month if year == as_of.year else 12
            expense_years[year] = self._report(year, end_month, "/financial/load_expense_data")
            balance_years[year] = self._report(year, end_month, "/financial/load_balance_data")

        hometax = self._transactions("/transaction/api_get_transaction_hometax", date(START_YEAR, 1, 1), as_of)
        bank = self._transactions("/transaction/api_get_transaction_bank", date(START_YEAR, 1, 1), as_of)
        mix_year, mix_month = (as_of.year, as_of.month - 1) if as_of.month > 1 else (as_of.year - 1, 12)
        card = self._transactions(
            "/transaction/api_get_transaction_card",
            date(mix_year, mix_month, 1),
            as_of,
        )
        return reduce_snapshot(as_of, expense_years, balance_years, hometax, bank, card)

    def _report(self, year: int, end_month: int, path: str) -> dict:
        return self._post_form(
            path,
            {"start_date": f"{year}01", "end_date": f"{year}{end_month:02d}"},
        )

    def _transactions(self, path: str, start: date, end: date) -> list[dict]:
        query = urllib.parse.urlencode(
            {"from_date": start.strftime("%Y%m%d"), "to_date": end.strftime("%Y%m%d")}
        )
        payload = self._get_json(f"{path}?{query}")
        data = payload.get("data") or []
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected transaction payload from {path}")
        return data

    def _post_json(self, path: str, payload: dict) -> dict:
        status, body, _ = self._open(
            BASE + path,
            json.dumps(payload).encode(),
            {"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )
        if status != 200:
            raise RuntimeError(f"{path} returned HTTP {status}")
        return json.loads(body.decode() or "{}")

    def _post_form(self, path: str, form: dict) -> dict:
        status, body, _ = self._open(
            BASE + path,
            urllib.parse.urlencode(form).encode(),
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        if status != 200:
            raise RuntimeError(f"{path} returned HTTP {status}")
        parsed = json.loads(body.decode() or "{}")
        if parsed.get("result") is False:
            raise RuntimeError(f"{path} returned result=false")
        return parsed

    def _get_json(self, path: str) -> dict:
        status, body, _ = self._open(
            BASE + path,
            headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
        )
        if status != 200:
            raise RuntimeError(f"{path} returned HTTP {status}")
        parsed = json.loads(body.decode() or "{}")
        if parsed.get("result") is False:
            raise RuntimeError(f"{path} returned result=false")
        return parsed

    def _open(self, url: str, data=None, headers=None):
        header_map = {
            "User-Agent": "twohands-cashflow/1.0",
            "Referer": f"{BASE}/financial/dashboard",
        }
        if headers:
            header_map.update(headers)
        request = urllib.request.Request(url, data=data, headers=header_map)
        with self.opener.open(request, timeout=60) as response:
            return response.status, response.read(), response.headers


def _as_of(hit: dict, today: date) -> date:
    raw = str(hit.get("during_end_date") or "")
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        parsed = today
    return parsed if parsed <= today else today


def _month_numbers(payload: dict) -> list[int]:
    months = []
    for label in payload.get("category") or []:
        digits = "".join(ch for ch in str(label) if ch.isdigit())
        months.append(int(digits) if digits else 0)
    return months


def reduce_snapshot(
    as_of: date,
    expense_years: dict[int, dict],
    balance_years: dict[int, dict],
    hometax: list,
    bank: list,
    card: list,
) -> dict:
    card_by_month: dict[tuple[int, int], int] = {}
    purchase_by_month: dict[tuple[int, int], int] = {}
    for year, payload in expense_years.items():
        months = _month_numbers(payload)
        for series in payload.get("expense-voucher") or []:
            target = card_by_month if series.get("name") == "카드매입" else purchase_by_month
            for index, amount in enumerate(series.get("data") or []):
                if index < len(months) and months[index]:
                    key = (year, months[index])
                    target[key] = target.get(key, 0) + int(amount or 0)

    balances: dict[tuple[int, int], int] = defaultdict(int)
    for year, payload in balance_years.items():
        months = _month_numbers(payload)
        for series in payload.get("balance-account") or []:
            for index, amount in enumerate(series.get("data") or []):
                if index < len(months) and months[index]:
                    balances[(year, months[index])] += int(amount or 0)

    sales: dict[tuple[int, int], int] = defaultdict(int)
    for row in hometax:
        if str(row.get("inout_type_cd")) != "1":
            continue
        stamp = str(row.get("ack_date") or "")
        if len(stamp) < 6:
            continue
        sales[(int(stamp[0:4]), int(stamp[4:6]))] += won(row.get("charge_amt"))

    bank_in: dict[tuple[int, int], int] = defaultdict(int)
    bank_out: dict[tuple[int, int], int] = defaultdict(int)
    card_paid: dict[tuple[int, int], int] = defaultdict(int)
    for row in bank:
        stamp = str(row.get("trandate") or "")
        if len(stamp) < 6:
            continue
        key = (int(stamp[0:4]), int(stamp[4:6]))
        incoming = won(row.get("histct_i_krw") or row.get("histct_i"))
        outgoing = won(row.get("histct_o_krw") or row.get("histct_o"))
        bank_in[key] += incoming
        bank_out[key] += outgoing
        if row.get("cate_name") == "신용/체크카드결제":
            card_paid[key] += outgoing

    mix_key = (as_of.year, as_of.month - 1) if as_of.month > 1 else (as_of.year - 1, 12)
    mix: dict[str, int] = defaultdict(int)
    for row in card:
        stamp = str(row.get("ack_date") or "")
        if len(stamp) < 6 or (int(stamp[0:4]), int(stamp[4:6])) != mix_key:
            continue
        if (row.get("tx_sts") or row.get("ack_sts_nm")) == "취소":
            continue
        rate = Decimal(str(row.get("exchange_rate") or "1"))
        amount = won(row.get("ack_amt") if rate != 1 else row.get("tx_tot_amt"))
        mix[row.get("cate_name") or "미분류"] += amount

    if (as_of.year, as_of.month) not in balances:
        raise RuntimeError("Jobis balance series has no current month")
    cash_now = balances[(as_of.year, as_of.month)]

    months = []
    year, month = START_YEAR, 1
    while (year, month) <= (as_of.year, as_of.month):
        key = (year, month)
        months.append(
            {
                "year": year,
                "month": month,
                "sales": sales.get(key, 0),
                "purchase": purchase_by_month.get(key, 0),
                "card": card_by_month.get(key, 0),
                "bankIn": bank_in.get(key, 0),
                "bankOut": bank_out.get(key, 0),
                "cardPaid": card_paid.get(key, 0),
                "endCash": balances.get(key, 0),
            }
        )
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)

    return {
        "asOf": as_of.isoformat(),
        "cashNow": cash_now,
        "months": months,
        "balances": {f"{y}-{m:02d}": amount for (y, m), amount in balances.items()},
        "cardMix": [
            {"name": name, "amount": amount}
            for name, amount in sorted(mix.items(), key=lambda item: item[1], reverse=True)
            if amount
        ],
        "cardMixMonth": f"{mix_key[0]}-{mix_key[1]:02d}",
    }

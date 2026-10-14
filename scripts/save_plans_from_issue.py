#!/usr/bin/env python3
"""Write data/plans.json from a save-plans issue or workflow input."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from refresh_jobis import save_plans


def extract_plans(text: str) -> dict:
    fenced = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    raw = fenced.group(1) if fenced else text.strip()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("plans JSON은 객체여야 합니다.")
    return payload


def load_payload() -> dict:
    raw = os.environ.get("PLANS_JSON", "").strip()
    if raw:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("plans JSON은 객체여야 합니다.")
        return payload
    body = os.environ.get("ISSUE_BODY", "")
    if not body.strip():
        raise ValueError("plans JSON이 없습니다.")
    return extract_plans(body)


def main() -> int:
    result = save_plans(load_payload())
    sales = len(result["plans"]["sales"])
    expenses = len(result["plans"]["expenses"])
    cashflow = "yes" if result["cashflow"] else "no"
    print(f"saved sales={sales} expenses={expenses} cashflow={cashflow}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)

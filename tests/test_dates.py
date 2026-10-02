from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from jobmail.web.dates import format_day

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "date-format-cases.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize(("day", "expected"), CASES["days"])
def test_format_day_shared_cases(day, expected):
    assert format_day(day) == expected
    assert format_day(date.fromisoformat(day)) == expected


def test_format_day_never_breaks_inside_a_date():
    assert " " not in format_day("2026-10-01")


@pytest.mark.parametrize("bad", ["", "demain", "2026-13-01", None, 20261001])
def test_format_day_rejects_unreadable_values(bad):
    assert format_day(bad) == ""

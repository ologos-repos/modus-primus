"""Tests for runtime/cron — minimal cron parser + next_fire_at."""
from __future__ import annotations

import datetime as _dt

import pytest

from means.agents.runtime.cron import next_fire_at, parse_cron


def _epoch(year, month, day, hour=0, minute=0, second=0) -> float:
    return _dt.datetime(year, month, day, hour, minute, second).timestamp()


# ---------- parse_cron ----------


def test_parse_all_stars():
    expr = parse_cron("* * * * *")
    assert expr.minute == list(range(0, 60))
    assert expr.hour == list(range(0, 24))
    assert expr.dom == list(range(1, 32))
    assert expr.month == list(range(1, 13))
    assert expr.dow == list(range(0, 7))


def test_parse_literal_minute():
    expr = parse_cron("7 * * * *")
    assert expr.minute == [7]


def test_parse_step():
    expr = parse_cron("*/5 * * * *")
    assert expr.minute == [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]


def test_parse_step_15_minute():
    expr = parse_cron("*/15 * * * *")
    assert expr.minute == [0, 15, 30, 45]


def test_parse_combined():
    expr = parse_cron("0 7 * * *")
    assert expr.minute == [0]
    assert expr.hour == [7]


def test_parse_wrong_field_count():
    with pytest.raises(ValueError, match="5 fields"):
        parse_cron("* * * *")
    with pytest.raises(ValueError, match="5 fields"):
        parse_cron("* * * * * *")


def test_parse_out_of_range_minute():
    with pytest.raises(ValueError, match="out of range"):
        parse_cron("60 * * * *")


def test_parse_out_of_range_hour():
    with pytest.raises(ValueError, match="out of range"):
        parse_cron("0 24 * * *")


def test_parse_out_of_range_month():
    with pytest.raises(ValueError, match="out of range"):
        parse_cron("0 0 1 13 *")


def test_parse_invalid_step():
    with pytest.raises(ValueError, match="step"):
        parse_cron("*/0 * * * *")


def test_parse_unsupported_syntax():
    """Ranges and lists are deferred; should clearly reject them."""
    with pytest.raises(ValueError, match="unsupported"):
        parse_cron("1-5 * * * *")
    with pytest.raises(ValueError, match="unsupported"):
        parse_cron("1,3,5 * * * *")


def test_parse_records_dom_dow_restriction_flags():
    expr = parse_cron("* * * * *")
    assert expr.dom_restricted is False
    assert expr.dow_restricted is False
    expr2 = parse_cron("* * 15 * *")
    assert expr2.dom_restricted is True
    assert expr2.dow_restricted is False


# ---------- next_fire_at ----------


def test_next_fire_every_minute():
    """`* * * * *` from 10:00:30 → 10:01:00."""
    expr = parse_cron("* * * * *")
    after = _epoch(2026, 5, 7, 10, 0, 30)
    expected = _epoch(2026, 5, 7, 10, 1, 0)
    assert next_fire_at(expr, after) == expected


def test_next_fire_every_5_min_at_boundary():
    """`*/5 * * * *` from 10:03 → next is 10:05."""
    expr = parse_cron("*/5 * * * *")
    after = _epoch(2026, 5, 7, 10, 3, 0)
    expected = _epoch(2026, 5, 7, 10, 5, 0)
    assert next_fire_at(expr, after) == expected


def test_next_fire_daily_at_7_today():
    """`0 7 * * *` from midnight → 7:00 same day."""
    expr = parse_cron("0 7 * * *")
    after = _epoch(2026, 5, 7, 0, 0, 0)
    expected = _epoch(2026, 5, 7, 7, 0, 0)
    assert next_fire_at(expr, after) == expected


def test_next_fire_daily_at_7_tomorrow():
    """`0 7 * * *` from after-7 → 7:00 next day."""
    expr = parse_cron("0 7 * * *")
    after = _epoch(2026, 5, 7, 8, 0, 0)
    expected = _epoch(2026, 5, 8, 7, 0, 0)
    assert next_fire_at(expr, after) == expected


def test_next_fire_strictly_greater_than_after():
    """If we ask for `next_fire_at` with `after = exact_match`, we must
    return the *next* match, not the same one — otherwise the scheduler
    would double-fire within a single minute."""
    expr = parse_cron("0 7 * * *")
    after = _epoch(2026, 5, 7, 7, 0, 0)
    result = next_fire_at(expr, after)
    assert result > after
    assert result == _epoch(2026, 5, 8, 7, 0, 0)


def test_next_fire_dom_only_restriction():
    """`0 0 15 * *` → next is the 15th."""
    expr = parse_cron("0 0 15 * *")
    after = _epoch(2026, 5, 7, 0, 0, 0)
    expected = _epoch(2026, 5, 15, 0, 0, 0)
    assert next_fire_at(expr, after) == expected


def test_next_fire_dow_or_dom_when_both_restricted():
    """GNU cron OR semantics when BOTH dom and dow restricted."""
    # dom=15, dow=Mon (1) — matches Mondays OR the 15th
    expr = parse_cron("0 0 15 * 1")
    # Start from a Tuesday (2026-05-12 was a Tuesday); next match should be
    # next Monday (2026-05-18) UNLESS the 15th comes first (2026-05-15 = Fri).
    after = _epoch(2026, 5, 12, 0, 0, 0)
    expected = _epoch(2026, 5, 15, 0, 0, 0)
    assert next_fire_at(expr, after) == expected


def test_next_fire_seconds_truncated():
    """`after_epoch` with sub-minute precision is fine — we always snap to
    the next minute boundary."""
    expr = parse_cron("* * * * *")
    after = _epoch(2026, 5, 7, 10, 0, 45)  # 10:00:45
    expected = _epoch(2026, 5, 7, 10, 1, 0)
    assert next_fire_at(expr, after) == expected

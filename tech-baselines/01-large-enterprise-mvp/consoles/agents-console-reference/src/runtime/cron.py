"""Minimal 5-field cron parser for the Phase 9 scheduler.

Supported syntax:
  - `*` for any value
  - integer literals (`5`, `30`)
  - step values (`*/5`, `*/15`)

Deferred to a follow-up phase if needed:
  - ranges (`1-5`)
  - lists (`1,3,5`)
  - `@daily` / `@hourly` shortcuts

Field order (standard cron, system-local time):
  minute (0-59)  hour (0-23)  day-of-month (1-31)  month (1-12)  dow (0-6, 0=Sun)

`next_fire_at(after_epoch)` returns the next epoch timestamp that satisfies
the expression, strictly greater than `after_epoch`. Day-of-month and
day-of-week follow GNU/POSIX semantics: when both are restricted (neither
is `*`), a fire happens when EITHER matches; when one or both are `*`
the standard AND semantics apply.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass


@dataclass
class CronExpr:
    minute: list[int]    # sorted set of valid minutes (0-59)
    hour: list[int]      # sorted set of valid hours (0-23)
    dom: list[int]       # sorted set of valid days-of-month (1-31)
    month: list[int]     # sorted set of valid months (1-12)
    dow: list[int]       # sorted set of valid days-of-week (0-6, Sun=0)
    raw: str             # original expression (for debugging / display)
    dom_restricted: bool # True if dom field wasn't `*`
    dow_restricted: bool # True if dow field wasn't `*`


_FIELD_BOUNDS = (
    (0, 59),   # minute
    (0, 23),   # hour
    (1, 31),   # dom
    (1, 12),   # month
    (0, 6),    # dow
)


def parse_cron(expr: str) -> CronExpr:
    """Parse a 5-field cron expression. Raises ValueError on invalid input."""
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(
            f"cron expression must have 5 fields, got {len(parts)}: {expr!r}"
        )
    minute, hour, dom, month, dow = (
        _parse_field(parts[i], _FIELD_BOUNDS[i][0], _FIELD_BOUNDS[i][1])
        for i in range(5)
    )
    return CronExpr(
        minute=minute, hour=hour, dom=dom, month=month, dow=dow,
        raw=expr,
        dom_restricted=parts[2] != "*",
        dow_restricted=parts[4] != "*",
    )


def _parse_field(field: str, lo: int, hi: int) -> list[int]:
    if field == "*":
        return list(range(lo, hi + 1))
    if field.startswith("*/"):
        try:
            step = int(field[2:])
        except ValueError as e:
            raise ValueError(f"invalid step value: {field!r}") from e
        if step <= 0:
            raise ValueError(f"step must be positive: {field!r}")
        return [n for n in range(lo, hi + 1) if (n - lo) % step == 0]
    try:
        n = int(field)
    except ValueError as e:
        raise ValueError(f"unsupported cron syntax: {field!r}") from e
    if not (lo <= n <= hi):
        raise ValueError(f"value {n} out of range [{lo},{hi}] in {field!r}")
    return [n]


def next_fire_at(expr: CronExpr, after_epoch: float) -> float:
    """Return the next epoch timestamp satisfying `expr`, strictly > after.

    Walks minute-by-minute starting from `after + 60s` (truncated to the
    minute boundary). Bounded by ~5 years to avoid infinite loops on
    pathological exprs (e.g. Feb 30 alone — impossible). 5y * 525600 min
    is ~2.6M iterations worst case; in practice the loop exits within a
    handful for any reasonable expression.
    """
    # Start from one minute past `after`, snapped to minute resolution.
    start = _dt.datetime.fromtimestamp(after_epoch).replace(second=0, microsecond=0)
    candidate = start + _dt.timedelta(minutes=1)
    deadline = candidate + _dt.timedelta(days=365 * 5)
    while candidate < deadline:
        if _matches(expr, candidate):
            return candidate.timestamp()
        candidate += _dt.timedelta(minutes=1)
    raise ValueError(
        f"no fire time found within 5 years for expr {expr.raw!r}"
    )


def _matches(expr: CronExpr, dt: _dt.datetime) -> bool:
    if dt.minute not in expr.minute:
        return False
    if dt.hour not in expr.hour:
        return False
    if dt.month not in expr.month:
        return False
    # GNU cron quirk: when BOTH dom and dow are restricted, OR them.
    # When one (or both) is `*`, AND them.
    dow_idx = (dt.weekday() + 1) % 7  # convert Mon=0 → Sun=0 cron form
    if expr.dom_restricted and expr.dow_restricted:
        return dt.day in expr.dom or dow_idx in expr.dow
    return dt.day in expr.dom and dow_idx in expr.dow

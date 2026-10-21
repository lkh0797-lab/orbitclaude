"""Monthly average USD/KRW from daily closes. The fetch function is injectable for tests."""
from __future__ import annotations

from datetime import date

from export_overlay._fdr import FX_SYMBOL, Fetch, fdr_fetch   # 기업추적으로 옮기며(2026-10-21) journal.prices 에서 가져옴

MIN_DAYS = 5               # fewer daily closes than this → no average for the month
SANE = (500.0, 3000.0)     # drop obviously broken ticks


def monthly_average(start: date, end: date, fetch: Fetch = fdr_fetch) -> dict[str, float]:
    """→ {YYYYMM: mean close}. Any fetch failure yields {} (callers fall back to dollars)."""
    try:
        rows = fetch(FX_SYMBOL, start, end)
    except Exception:
        return {}
    buckets: dict[str, list[float]] = {}
    for day, rate in rows:
        if SANE[0] <= rate <= SANE[1]:
            buckets.setdefault(f"{day.year}{day.month:02d}", []).append(rate)
    return {ym: sum(v) / len(v) for ym, v in sorted(buckets.items()) if len(v) >= MIN_DAYS}

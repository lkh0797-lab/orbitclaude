"""FinanceDataReader daily closes (USD/KRW, KOSPI, stocks) — vendored from 주식3 max20 `journal/prices.py`
when the package moved into 기업추적 (2026-10-21), so it no longer needs the trade-journal package.

Kept byte-for-byte in behaviour: Yahoo-sourced series treat `end` as exclusive (widen the request), and
Yahoo FX bars are stamped at London midnight, so a bar whose day starts in British Summer Time carries
the previous date (+1 day fix per bar). Needs 64-bit Python with pandas (`py -3.13`); imported lazily.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

FX_SYMBOL = "USD/KRW"
Fetch = Callable[[str, date, date], list[tuple[date, float]]]


def fdr_fetch(symbol: str, start: date, end: date) -> list[tuple[date, float]]:
    import FinanceDataReader as fdr

    # Widen the request: Yahoo-sourced series treat `end` as exclusive.
    frame = fdr.DataReader(symbol, start - timedelta(days=3), end + timedelta(days=3))
    rows = [(stamp.date(), float(close)) for stamp, close in frame["Close"].dropna().items()]
    return normalize_series(rows, start, end, london_stamped=symbol == FX_SYMBOL)


def normalize_series(rows: list[tuple[date, float]], start: date, end: date,
                     london_stamped: bool = False) -> list[tuple[date, float]]:
    """Align bars to real trading days and trim to the inclusive [start, end] window."""
    if london_stamped:
        rows = [(d + timedelta(days=1), v) if _london_summer_time(d + timedelta(days=1)) else (d, v)
                for d, v in rows]
    return sorted((d, v) for d, v in rows if start <= d <= end)


def _london_summer_time(day: date) -> bool:
    """True when London midnight at the start of `day` falls in British Summer Time."""
    return _last_sunday(day.year, 3) < day <= _last_sunday(day.year, 10)


def _last_sunday(year: int, month: int) -> date:
    last = date(year, month, 31)  # only used for March and October
    return last - timedelta(days=(last.weekday() + 1) % 7)

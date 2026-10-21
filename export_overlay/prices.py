"""Daily closes for the screener: has the price moved since the last print, and what a signal paid.

Fetching goes through `export_overlay._fdr.fdr_fetch` (injectable) and the JSON cache; everything else
is pure. Returns are in percent; "excess" means minus the benchmark index over the same days
(daily log excess returns, summed over the window).
"""
from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Callable, Mapping
from datetime import date

from export_overlay.cache import JsonCache

BENCHMARK = "KS11"           # KOSPI
TTL = 20 * 3600              # a trading day's closes are good for the day
AFTER_FILING = 5             # trading days held past the earnings filing in the event window
VOL_DAYS = 250               # trading days before the filing used for the daily volatility
MIN_VOL_DAYS = 120
LOOKBACK = 63                # trading days for "had the price moved before the signal" (~3 months)
MAX_DAILY = 0.4              # a close-to-close move beyond ±40% is a split or bad data (KRX limits a day to ±30%)
MIN_DAYS = 250

Series = list[tuple[str, float]]      # (ISO date, close), ascending


def fetch_series(symbol: str, start: date, end: date, cache: JsonCache, fetch: Callable) -> Series:
    """Closes from `start` to `end` (ISO dates), cached for the day; [] when the fetch fails."""
    key = f"px_{symbol}_{start.isoformat()}"
    got = cache.get(key, TTL)
    if got is not None:
        return [tuple(row) for row in got]
    try:
        rows = [(d.isoformat(), float(v)) for d, v in fetch(symbol, start, end) if v and v > 0]
    except Exception:
        return []
    if len(rows) < MIN_DAYS:
        return []
    cache.put(key, rows)
    return rows


def suspicious(series: Series) -> bool:
    """A close-to-close move beyond ±40% somewhere: an unadjusted split or broken data. Symmetric in
    percent, so a limit-down day (−30%) passes like a limit-up day."""
    return any(abs(b / a - 1) > MAX_DAILY for (_, a), (_, b) in zip(series, series[1:]))


def signal_date(q: str, months: int = 3) -> date:
    """When the quarter's first `months` months of exports are public: the 15th of the following
    month (the customs item statistics for a month come out around then). Three months = the whole
    quarter, the 15th of the month after it ends."""
    y, n = int(q[:4]), int(q[5])
    m = (n - 1) * 3 + months + 1
    return date(y + (m > 12), m - 12 if m > 12 else m, 15)


def flash_date(q: str) -> date:
    """The 1st of the month after the quarter ends: the ministry's headline export flash."""
    y, n = int(q[:4]), int(q[5])
    m = n * 3 + 1
    return date(y + (m > 12), m - 12 if m > 12 else m, 1)


def daily_excess(stock: Series, bench: Series) -> list[tuple[str, float]]:
    """Daily log excess returns on the dates both series have."""
    b = dict(bench)
    out, prev = [], None
    for d, p in stock:
        if d in b:
            if prev is not None:
                out.append((d, math.log(p / prev[1]) - math.log(b[d] / prev[0])))
            prev = (b[d], p)
    return out


def _index_from(dates: list[str], day: date) -> int | None:
    i = bisect_left(dates, day.isoformat())
    return i if i < len(dates) else None


def window_excess(ex: list[tuple[str, float]], start: date, end: date, after: int = AFTER_FILING) -> float | None:
    """Excess return (percent) from the close of the first day ≥ `start` to `after` trading days past
    the first day ≥ `end`; None when the window is not complete or ends before it starts."""
    dates = [d for d, _ in ex]
    i, j = _index_from(dates, start), _index_from(dates, end)
    if i is None or j is None or j <= i or j + after >= len(ex):
        return None
    return math.expm1(sum(v for _, v in ex[i + 1:j + after + 1])) * 100


def prior_excess(ex: list[tuple[str, float]], day: date, lookback: int = LOOKBACK) -> float | None:
    """Excess return over the `lookback` trading days ending at the first day ≥ `day`."""
    dates = [d for d, _ in ex]
    i = _index_from(dates, day)
    if i is None or i < lookback:
        return None
    return math.expm1(sum(v for _, v in ex[i - lookback + 1:i + 1])) * 100


def since(ex: list[tuple[str, float]], filing: date) -> dict | None:
    """How far the stock has gone against KOSPI since the last report was filed, and how unusual that
    is for this stock: z = Σ excess / (σ_daily · √days), σ from the VOL_DAYS days before the filing."""
    dates = [d for d, _ in ex]
    i = _index_from(dates, filing)
    if i is None or i < MIN_VOL_DAYS:
        return None
    hist = [v for _, v in ex[max(0, i - VOL_DAYS):i]]
    m = sum(hist) / len(hist)
    sd = math.sqrt(sum((v - m) ** 2 for v in hist) / (len(hist) - 1))
    moves = [v for _, v in ex[i + 1:]]
    total = sum(moves)
    return {"from": dates[i], "days": len(moves), "excess": math.expm1(total) * 100,
            "z": total / (sd * math.sqrt(len(moves))) if sd > 0 and moves else None}


def event_study(events: list[dict], ex: list[tuple[str, float]], filings: Mapping[str, date],
                months: int = 3) -> list[dict]:
    """For each walk-forward event with a previous quarter and a filing date for its quarter: the
    stock's excess return from the signal (the quarter's first `months` months public) to AFTER_FILING
    days past the filing — the trade held through the print — the same from the ministry's 1st-of-
    month flash, and the excess return over the LOOKBACK days before the signal."""
    out = []
    for e in events:
        if e.get("prev") is None or e["q"] not in filings:
            continue
        start = signal_date(e["q"], months)
        out.append(dict(q=e["q"], signal=e["signal"], hit=e["hit"], day=start.isoformat(),
                        delta=e["pred"] - e["prev"], actual_change=e["actual"] - e["prev"],
                        excess=window_excess(ex, start, filings[e["q"]]),
                        flash=window_excess(ex, flash_date(e["q"]), filings[e["q"]]) if months == 3 else None,
                        prior=prior_excess(ex, start)))
    return out


def load_all(codes: list[str], start: date, end: date, cache: JsonCache, fetch: Callable,
             log=print) -> tuple[Mapping[str, Series], Series]:
    bench = fetch_series(BENCHMARK, start, end, cache, fetch)
    if not bench:
        log("KOSPI 지수를 받지 못해 주가 열은 비웁니다.")
        return {}, []
    out = {}
    for code in codes:
        s = fetch_series(code, start, end, cache, fetch)
        if s:
            out[code] = s
    log(f"주가: {len(out)}/{len(codes)}곳, KOSPI {bench[0][0]}~{bench[-1][0]}")
    return out, bench

"""Pure calculations: month/quarter labels, YoY, company quarters, basket, lag statistics.

No network, cache or file access. Months are 'YYYYMM', quarters 'YYYYQn'. Percent values
are in percent (12.5 means +12.5%).

Company YoY takes its base from the same report's prior-year column (frmtrm_*), not from the
report filed a year earlier: restatements and spin-offs (주성 2019 기재정정, 피에스케이홀딩스
2019 분할) then compare like with like, and the base is always on the report's own 연결/별도 basis.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from export_overlay.dart import Figure, ReportFigures

MIN_PAIRS = 12          # quarterly YoY overlaps three quarters; fewer pairs say nothing
MIN_COVERAGE = 0.5      # basket YoY only when the compared companies hold at least half the basket's revenue
LAGS = (-1, 0, 1, 2)    # exports lead revenue by k quarters; −1 = revenue leads (reference)
FLAT = 5.0              # |YoY| below this is a coin flip for the direction-agreement rate
RESTATED = 0.01         # base vs originally filed value differing by more than 1% → '재작성'
BANDS = ((-math.inf, 0.0, "0% 미만"), (0.0, 15.0, "0~15%"), (15.0, 30.0, "15~30%"), (30.0, math.inf, "30% 이상"))


# ---------------------------------------------------------------- labels
def ym_shift(ym: str, k: int) -> str:
    i = int(ym[:4]) * 12 + int(ym[4:]) - 1 + k
    return f"{i // 12:04d}{i % 12 + 1:02d}"


def month_range(a: str, b: str) -> list[str]:
    out, ym = [], a
    while ym <= b:
        out.append(ym)
        ym = ym_shift(ym, 1)
    return out


def quarter_of(ym: str) -> str:
    return f"{ym[:4]}Q{(int(ym[4:]) - 1) // 3 + 1}"


def quarter_months(q: str) -> list[str]:
    first = (int(q[5]) - 1) * 3 + 1
    return [f"{q[:4]}{m:02d}" for m in range(first, first + 3)]


def quarter_shift(q: str, k: int) -> str:
    i = int(q[:4]) * 4 + int(q[5]) - 1 + k
    return f"{i // 4}Q{i % 4 + 1}"


def in_windows(q: str, windows: Iterable[tuple[str, str]]) -> bool:
    return any(a <= q <= b for a, b in windows)


def pct_change(cur: float | None, base: float | None) -> float | None:
    """Growth in percent. A missing or non-positive base gives None (sign flips read wrong)."""
    if cur is None or base is None or base <= 0:
        return None
    return (cur / base - 1) * 100


# ---------------------------------------------------------------- exports
def matches(hs: str, prefixes: Iterable[str] | None) -> bool:
    return prefixes is None or any(hs.startswith(p) for p in prefixes)


def select(months_by_sub: Mapping[str, Mapping[str, float]], prefixes: Iterable[str] | None = None) -> dict[str, float]:
    """Monthly total over the sub-HS codes starting with any of `prefixes` (None = all)."""
    chosen = None if prefixes is None else tuple(prefixes)
    return {ym: sum(v for hs, v in by_sub.items() if matches(hs, chosen))
            for ym, by_sub in sorted(months_by_sub.items())}


def to_krw(usd: Mapping[str, float], fx: Mapping[str, float]) -> dict[str, float]:
    return {ym: v * fx[ym] for ym, v in usd.items() if ym in fx}


def yoy_monthly(series: Mapping[str, float]) -> dict[str, float | None]:
    return {ym: pct_change(v, series.get(ym_shift(ym, -12))) for ym, v in series.items()}


def rolling3(series: Mapping[str, float], ym: str) -> float | None:
    window = [series.get(ym_shift(ym, -k)) for k in range(3)]
    return None if any(v is None for v in window) else sum(window)


def yoy_rolling3(series: Mapping[str, float]) -> dict[str, float | None]:
    """Last three months vs the same three months a year earlier."""
    return {ym: pct_change(rolling3(series, ym), rolling3(series, ym_shift(ym, -12))) for ym in series}


def quarter_totals(series: Mapping[str, float]) -> dict[str, float]:
    """Sums of complete quarters only."""
    out = {}
    for q in sorted({quarter_of(ym) for ym in series}):
        months = quarter_months(q)
        if all(m in series for m in months):
            out[q] = sum(series[m] for m in months)
    return out


def yoy_by_quarter(totals: Mapping[str, float]) -> dict[str, float | None]:
    return {q: pct_change(v, totals.get(quarter_shift(q, -4))) for q, v in totals.items()}


def quarter_to_date(series: Mapping[str, float]) -> dict | None:
    """The unfinished quarter at the end of the series: months so far vs the same months a year earlier."""
    if not series:
        return None
    last = max(series)
    q = quarter_of(last)
    if last == quarter_months(q)[-1]:
        return None
    done = [m for m in quarter_months(q) if m <= last]
    base = [series.get(ym_shift(m, -12)) for m in done]
    cur = [series.get(m) for m in done]
    yoy = None if None in base or None in cur else pct_change(sum(cur), sum(base))
    return {"q": q, "months": len(done), "yoy": yoy}


# ---------------------------------------------------------------- company quarters
@dataclass(frozen=True)
class Quarter:
    revenue: float | None
    operating: float | None
    basis: str
    revenue_base: float | None = None     # same quarter a year earlier, from this report's comparative column
    operating_base: float | None = None
    rcept_no: str = ""


def _three_months(figs: dict[int, Figure | None], basis: dict[int, str | None],
                  cur: str, cum: str) -> dict[int, float | None]:
    """Three-month values for Q1-Q4 of one fiscal year from one pair of columns
    (cur/cum = this year, prev/prev_cum = the reports' own prior-year columns).

    Q1-Q3 use each report's 3-month column, else the difference of year-to-date columns;
    Q4 is the annual figure minus the Q3 year to date. A difference is only taken between
    reports on the same basis (연결/별도).
    """
    out: dict[int, float | None] = {}
    for q in (1, 2, 3):
        fig = figs.get(q)
        value = getattr(fig, cur) if fig else None
        if fig is not None and value is None:
            ytd = getattr(fig, cum)
            if q == 1:
                value = ytd
            else:
                prev = figs.get(q - 1)
                prev_ytd = None
                if prev is not None and basis.get(q - 1) == basis.get(q):
                    prev_ytd = getattr(prev, cum)
                    if prev_ytd is None and q - 1 == 1:
                        prev_ytd = getattr(prev, cur)       # Q1's three months are its year to date
                value = ytd - prev_ytd if (ytd is not None and prev_ytd is not None) else None
        out[q] = value
    out[4] = None
    annual = figs.get(4)
    year_total = getattr(annual, cur) if annual else None
    if year_total is not None:
        q3 = figs.get(3)
        nine = getattr(q3, cum) if (q3 is not None and basis.get(3) == basis.get(4)) else None
        if nine is None and all(basis.get(q) == basis.get(4) and out[q] is not None for q in (1, 2, 3)):
            nine = out[1] + out[2] + out[3]
        if nine is not None:
            out[4] = year_total - nine
    return out


def company_quarters(reports: Mapping[tuple[int, int], ReportFigures | None]) -> dict[str, Quarter]:
    """{(year, quarter): report} → {'YYYYQn': Quarter} for quarters with a filed report."""
    out = {}
    for y in sorted({y for y, _ in reports}):
        year = {q: reports.get((y, q)) for q in (1, 2, 3, 4)}
        basis = {q: r.basis if r else None for q, r in year.items()}
        cols = {}
        for field in ("revenue", "operating"):
            figs = {q: getattr(r, field) if r else None for q, r in year.items()}
            cols[field] = _three_months(figs, basis, "cur", "cum")
            cols[field + "_base"] = _three_months(figs, basis, "prev", "prev_cum")
        for field in ("revenue", "revenue_base"):
            # A negative quarter of revenue only comes out of "annual − Q3 year to date" when the two
            # reports cover different scopes (HD현대미포 2017, a reclassified discontinued business);
            # zero is a shell's report (에치에프알's pre-merger SPAC). Neither is a company quarter.
            cols[field] = {q: None if v is not None and v <= 0 else v for q, v in cols[field].items()}
        for q in (1, 2, 3, 4):
            if year[q] is None or (cols["revenue"][q] is None and cols["operating"][q] is None):
                continue
            out[f"{y}Q{q}"] = Quarter(cols["revenue"][q], cols["operating"][q], year[q].basis,
                                      cols["revenue_base"][q], cols["operating_base"][q], year[q].rcept_no)
    return out


def company_yoy(quarters: Mapping[str, Quarter], field: str = "revenue",
                breaks: Iterable[tuple[str, str]] = ()) -> dict[str, float | None]:
    """YoY of one field against the report's own prior-year column; None inside non-comparable windows."""
    breaks = list(breaks)
    return {q: None if in_windows(q, breaks) else pct_change(getattr(c, field), getattr(c, field + "_base"))
            for q, c in quarters.items()}


def pro_forma(companies: Mapping[str, Mapping[str, Quarter]],
              absorbed: Mapping[str, Iterable[tuple[str, str]]]) -> tuple[dict[str, dict[str, Quarter]], set[tuple[str, str]]]:
    """Add an absorbed company's year-earlier revenue (and operating profit) to the acquirer's base from
    the merger quarter on, when the comparatives were not restated → (companies, {(code, quarter)} adjusted).
    Without the absorbed company's year-earlier figure the base is unknown (None)."""
    out = {code: dict(qs) for code, qs in companies.items()}
    adjusted = set()
    for code, merges in absorbed.items():
        for other, first in merges:
            theirs = companies.get(other, {})
            for q, c in list(out.get(code, {}).items()):
                if q < first:
                    continue
                prev = theirs.get(quarter_shift(q, -4))
                rev = None if (c.revenue_base is None or prev is None or prev.revenue is None) else c.revenue_base + prev.revenue
                op = None if (c.operating_base is None or prev is None or prev.operating is None) else c.operating_base + prev.operating
                out[code][q] = Quarter(c.revenue, c.operating, c.basis, rev, op, c.rcept_no)
                adjusted.add((code, q))
    return out, adjusted


def restated(quarters: Mapping[str, Quarter], field: str = "revenue") -> set[str]:
    """Quarters whose base differs by more than 1% from what was originally filed a year earlier."""
    out = set()
    for q, c in quarters.items():
        old = quarters.get(quarter_shift(q, -4))
        base, orig = getattr(c, field + "_base"), getattr(old, field) if old else None
        if base is not None and orig not in (None, 0) and old.basis == c.basis and abs(base - orig) > RESTATED * abs(orig):
            out.add(q)
    return out


# ---------------------------------------------------------------- basket
@dataclass(frozen=True)
class BasketQuarter:
    revenue: float | None        # sum over every company that reported revenue
    operating: float | None      # sum over companies with both revenue and operating profit
    margin: float | None         # operating / revenue over that same set, percent
    reported: int                # companies with revenue this quarter
    revenue_yoy: float | None    # matched sample: Σ revenue / Σ same-report base, comparable companies only
    operating_yoy: float | None
    matched: int
    top: tuple[str, float] | None    # (company code, share of basket revenue %) for the largest company
    median_yoy: float | None         # equal-weight median of company revenue YoY
    coverage: float | None = None    # compared companies' share of the quarter's basket revenue, percent


def basket(companies: Mapping[str, Mapping[str, Quarter]],
           breaks: Mapping[str, Iterable[tuple[str, str]]] | None = None) -> dict[str, BasketQuarter]:
    breaks = {code: list(w) for code, w in (breaks or {}).items()}
    quarters = sorted({q for qs in companies.values() for q in qs})
    out = {}
    for q in quarters:
        rev = op = op_rev = 0.0
        reported = matched = 0
        cur_m = base_m = op_cur = op_base = 0.0
        op_ok = True
        largest = None
        yoys = []
        for code, qs in companies.items():
            c = qs.get(q)
            if c is None or c.revenue is None:
                continue
            reported += 1
            rev += c.revenue
            if largest is None or c.revenue > largest[1]:
                largest = (code, c.revenue)
            if c.operating is not None:
                op += c.operating
                op_rev += c.revenue
            if in_windows(q, breaks.get(code, ())) or c.revenue_base is None or c.revenue_base <= 0:
                continue
            matched += 1
            cur_m += c.revenue
            base_m += c.revenue_base
            yoys.append(pct_change(c.revenue, c.revenue_base))
            if c.operating is None or c.operating_base is None:
                op_ok = False
            else:
                op_cur += c.operating
                op_base += c.operating_base
        if not reported:
            continue
        coverage = cur_m / rev if rev > 0 else 0.0
        # When a break leaves only small companies comparable (a merger in the largest one), their sum is
        # not the basket — say nothing rather than a number about a tenth of it.
        comparable = matched and coverage >= MIN_COVERAGE
        out[q] = BasketQuarter(
            revenue=rev, operating=op if op_rev else None,
            margin=op / op_rev * 100 if op_rev > 0 else None, reported=reported,
            revenue_yoy=pct_change(cur_m, base_m) if comparable else None,
            operating_yoy=pct_change(op_cur, op_base) if (comparable and op_ok) else None,
            matched=matched, coverage=coverage * 100,
            top=(largest[0], largest[1] / rev * 100) if largest and rev > 0 else None,
            median_yoy=statistics.median(yoys) if yoys else None)
    return out


def reporting_status(companies: Mapping[str, Mapping[str, Quarter]]) -> tuple[str | None, int, dict[str, int]]:
    """→ (last quarter every active company has reported, active count, {later quarter: filed count}).

    Active = companies whose latest report is no older than one quarter before the newest
    report anyone has filed, so a company with broken data does not freeze the basket.
    """
    latest = [max((q for q, c in qs.items() if c.revenue is not None), default=None) for qs in companies.values()]
    latest = [v for v in latest if v]
    if not latest:
        return None, 0, {}
    newest = max(latest)
    active = [v for v in latest if v >= quarter_shift(newest, -1)]
    full = min(active)
    filed = {}
    q = quarter_shift(full, 1)
    while q <= newest:
        filed[q] = sum(1 for v in active if v >= q)
        q = quarter_shift(q, 1)
    return full, len(active), filed


# ---------------------------------------------------------------- lag statistics
def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def _autocorr(values: list[float], adjacent: list[bool]) -> float:
    """Lag-1 autocorrelation over neighbouring entries that are consecutive quarters."""
    m = sum(values) / len(values)
    den = sum((v - m) ** 2 for v in values)
    if den == 0:
        return 0.0
    num = sum((values[i] - m) * (values[i + 1] - m) for i in range(len(values) - 1) if adjacent[i])
    return num / den


def _log_change(pct: float | None) -> float | None:
    return math.log1p(pct / 100) if pct is not None and pct > -100 else None


def lag_pairs(x: Mapping[str, float | None], r: Mapping[str, float | None], lag: int) -> list[tuple[str, float, float]]:
    """(quarter, x_q, r_{q+lag}) for quarters where both exist — exports lead revenue by `lag`."""
    out = []
    for q, xv in sorted(x.items()):
        rv = r.get(quarter_shift(q, lag))
        if xv is not None and rv is not None and xv > -100 and rv > -100:
            out.append((q, xv, rv))
    return out


def correlation(pairs: list[tuple[str, float, float]]) -> dict:
    """Pearson r on log changes ln(1+YoY), with a 95% interval on the autocorrelation-adjusted
    effective sample (Bartlett: n·(1−a1·a2)/(1+a1·a2)), plus the direction-agreement rate next
    to what chance alone would give. Pairs where either side is within ±5% are left out of
    the agreement rate."""
    n = len(pairs)
    out = {"n": n, "r": None, "lo": None, "hi": None, "n_eff": None, "hit": None, "chance": None, "flat": 0}
    if n >= MIN_PAIRS:
        lx = [_log_change(a) for _, a, _ in pairs]
        ly = [_log_change(b) for _, _, b in pairs]
        r = pearson(lx, ly)
        if r is not None:
            adjacent = [quarter_shift(pairs[i][0], 1) == pairs[i + 1][0] for i in range(n - 1)]
            a = _autocorr(lx, adjacent) * _autocorr(ly, adjacent)
            n_eff = min(float(n), n * (1 - a) / (1 + a)) if a > -1 else float(n)
            out["n_eff"] = n_eff
            # An r is only reported together with its interval. Two smooth series of a dozen
            # quarters can leave n_eff ≤ 3 — then there is nothing to say, and r stays None.
            if n_eff > 3:
                if abs(r) >= 1 - 1e-12:
                    out.update(r=r, lo=r, hi=r)
                else:
                    z, se = math.atanh(r), 1 / math.sqrt(n_eff - 3)
                    out.update(r=r, lo=math.tanh(z - 1.96 * se), hi=math.tanh(z + 1.96 * se))
    moving = [(a, b) for _, a, b in pairs if abs(a) >= FLAT and abs(b) >= FLAT]
    out["flat"] = n - len(moving)
    if moving:
        px = sum(1 for a, _ in moving if a > 0) / len(moving)
        py = sum(1 for _, b in moving if b > 0) / len(moving)
        out["hit"] = sum(1 for a, b in moving if (a > 0) == (b > 0)) / len(moving) * 100
        out["chance"] = (px * py + (1 - px) * (1 - py)) * 100
    return out


def lag_stats(x: Mapping[str, float | None], r: Mapping[str, float | None], lags=LAGS) -> list[dict]:
    out = []
    for lag in lags:
        pairs = lag_pairs(x, r, lag)
        out.append(dict(correlation(pairs), lag=lag, span=(pairs[0][0], pairs[-1][0]) if pairs else None))
    return out


# ---------------------------------------------------------------- fit, nowcast, backtest
# Two-sided 95% Student-t quantiles by degrees of freedom (interpolated between rows).
T95 = ((1, 12.706), (2, 4.303), (3, 3.182), (4, 2.776), (5, 2.571), (6, 2.447), (8, 2.306), (10, 2.228),
       (12, 2.179), (15, 2.131), (20, 2.086), (25, 2.060), (30, 2.042), (40, 2.021), (60, 2.000), (120, 1.980))


def t95(dof: float) -> float:
    if dof >= T95[-1][0]:
        return 1.960
    for (d0, t0), (d1, t1) in zip(T95, T95[1:]):
        if dof <= d1:
            return t0 + (t1 - t0) * (max(dof, d0) - d0) / (d1 - d0)
    return T95[0][1]


@dataclass(frozen=True)
class Fit:
    """Least squares of ln(1+revenue YoY) on ln(1+export YoY) over paired quarters."""
    n: int
    slope: float
    intercept: float
    r: float
    sigma: float             # residual standard deviation (log units, n−2 degrees of freedom)
    x_mean: float
    sxx: float
    span: tuple[str, str]


def fit(pairs: list[tuple[str, float, float]]) -> Fit | None:
    """None below MIN_PAIRS pairs or when the export side has no spread."""
    n = len(pairs)
    if n < MIN_PAIRS:
        return None
    xs = [_log_change(a) for _, a, _ in pairs]
    ys = [_log_change(b) for _, _, b in pairs]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    intercept = my - slope * mx
    sigma = math.sqrt(sum((y - intercept - slope * x) ** 2 for x, y in zip(xs, ys)) / (n - 2))
    return Fit(n, slope, intercept, pearson(xs, ys) or 0.0, sigma, mx, sxx, (pairs[0][0], pairs[-1][0]))


def predict(f: Fit, x_pct: float | None, extra_sd: float = 0.0, dof: float | None = None) -> dict | None:
    """Revenue YoY implied by an export YoY with its 95% prediction interval, in percent (plus the
    log-unit prediction `log` and its standard error `se`).

    `extra_sd` is an additional uncertainty on the export side (log units) — a quarter-to-date
    figure standing in for the full quarter — propagated through the slope. `dof` replaces n−2 for
    the t quantile (an autocorrelation-adjusted effective sample gives honestly wider intervals)."""
    lx = _log_change(x_pct)
    if lx is None:
        return None
    ly = f.intercept + f.slope * lx
    se = f.sigma * math.sqrt(1 + 1 / f.n + (lx - f.x_mean) ** 2 / f.sxx)
    se = math.sqrt(se ** 2 + (f.slope * extra_sd) ** 2)
    t = t95(max(3.0, dof) if dof is not None else f.n - 2)
    return {"yoy": math.expm1(ly) * 100, "lo": math.expm1(ly - t * se) * 100, "hi": math.expm1(ly + t * se) * 100,
            "log": ly, "se": se}


def wilson(k: int, n: int) -> tuple[float, float] | None:
    """95% Wilson interval for a share k/n, in percent."""
    if n <= 0:
        return None
    z = 1.96
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (centre - half) * 100, (centre + half) * 100


def qtd_error(series: Mapping[str, float], months: int) -> float | None:
    """How far the YoY of a quarter's first `months` months has strayed from the full quarter's YoY:
    the standard deviation of that difference (log units) over past complete quarters, None below 8."""
    diffs = []
    for q, total in quarter_totals(series).items():
        head = quarter_months(q)[:months]
        cur = [series.get(m) for m in head]
        base = [series.get(ym_shift(m, -12)) for m in head]
        full_base = [series.get(ym_shift(m, -12)) for m in quarter_months(q)]
        if None in cur or None in base or None in full_base:
            continue
        a = _log_change(pct_change(sum(cur), sum(base)))
        b = _log_change(pct_change(total, sum(full_base)))
        if a is not None and b is not None:
            diffs.append(a - b)
    return statistics.stdev(diffs) if len(diffs) >= 8 else None


def partial_yoy(series: Mapping[str, float], months: int) -> dict[str, float | None]:
    """YoY of each quarter's first `months` months against the same months a year earlier — what was
    knowable that early. Quarters whose first months are all present (complete or not)."""
    out = {}
    for q in sorted({quarter_of(ym) for ym in series}):
        head = quarter_months(q)[:months]
        cur = [series.get(m) for m in head]
        base = [series.get(ym_shift(m, -12)) for m in head]
        if None not in cur and None not in base:
            out[q] = pct_change(sum(cur), sum(base))
    return out


def backtest(x: Mapping[str, float | None], r: Mapping[str, float | None], lag: int = 0,
             threshold: float = FLAT, x_signal: Mapping[str, float | None] | None = None,
             extra_sd: float = 0.0, known: int = 1) -> dict:
    """Walk-forward check of the nowcast. For each paired quarter q the fit uses only pairs up to
    q − `known`, predicts revenue YoY from x[q], and the predicted change against the revenue YoY of
    q − `known` (the last report public when the signal was read) becomes a signal when it is at
    least `threshold` points either way. `known` = 1 for a complete quarter (q−1 is filed by the 15th
    of the month after q), 2 for a first-month read (the 15th of q's second month, before q−1's
    report is due). Intervals use the training fit's effective sample (dof = n_eff − 2), as the live
    nowcast does.

    With `x_signal` the prediction for q is read off x_signal[q] instead (the quarter's first month
    or two, known earlier), the fit still being on the full-quarter pairs; `extra_sd` widens the
    interval as `predict` does.

    → {"n": quarters predicted, "inside95": % of actuals inside the 95% interval, "mae": mean
       |predicted − actual| in points over every predicted quarter, "mae_prev"/"mae_naive": the same
       over the quarters with a comparison quarter, for the nowcast and for "this quarter's YoY =
       the last reported one" (the forecast the nowcast must beat), "skill": 1 − mae_prev/mae_naive,
       "win": % of those quarters where the nowcast's error was the smaller, "signals": n, "hit": % of
       signals whose direction came true, "up"/"down": {"n", "hit", "median_change" (actual change in
       points)}, "events": [...]}"""
    pairs = lag_pairs(x, r, lag)
    events = []
    for i, (q, xv, rv) in enumerate(pairs):
        cutoff = quarter_shift(q, -known)
        train = [p for p in pairs[:i] if p[0] <= cutoff]
        f = fit(train)
        if x_signal is not None:
            xv = x_signal.get(q)
        if f is None or xv is None:
            continue
        n_eff = correlation(train)["n_eff"]
        p = predict(f, xv, extra_sd, (n_eff - 2) if n_eff else None)
        if p is None:
            continue
        ev = {"q": q, "x": xv, "pred": p["yoy"], "lo": p["lo"], "hi": p["hi"], "actual": rv,
              "inside": p["lo"] <= rv <= p["hi"], "prev": None, "signal": None, "hit": None}
        prev = r.get(quarter_shift(q, lag - known))
        if prev is not None and prev > -100:
            ev["prev"] = prev
            d = p["yoy"] - prev
            if abs(d) >= threshold:
                ev["signal"] = "up" if d > 0 else "down"
                ev["hit"] = (rv - prev > 0) == (d > 0)
        events.append(ev)
    signals = [e for e in events if e["signal"]]
    with_prev = [e for e in events if e["prev"] is not None]
    model = [abs(e["pred"] - e["actual"]) for e in with_prev]
    naive = [abs(e["prev"] - e["actual"]) for e in with_prev]
    mae_naive = sum(naive) / len(naive) if naive else None
    mae_prev = sum(model) / len(model) if model else None
    out = {"n": len(events), "signals": len(signals),
           "inside95": sum(e["inside"] for e in events) / len(events) * 100 if events else None,
           "mae": sum(abs(e["pred"] - e["actual"]) for e in events) / len(events) if events else None,
           "mae_prev": mae_prev, "mae_naive": mae_naive, "n_prev": len(with_prev),
           "skill": 1 - mae_prev / mae_naive if mae_naive else None,
           "win": sum(a < b for a, b in zip(model, naive)) / len(model) * 100 if model else None,
           "hit": sum(e["hit"] for e in signals) / len(signals) * 100 if signals else None, "events": events}
    for side in ("up", "down"):
        chosen = [e for e in signals if e["signal"] == side]
        out[side] = {"n": len(chosen),
                     "hit": sum(e["hit"] for e in chosen) / len(chosen) * 100 if chosen else None,
                     "median_change": statistics.median(e["actual"] - e["prev"] for e in chosen) if chosen else None}
    return out


def band_of(value: float) -> tuple[float, float, str]:
    return next(b for b in BANDS if b[0] <= value < b[1])


def analogs(x: Mapping[str, float | None], r: Mapping[str, float | None], value: float | None) -> dict | None:
    """Past quarters whose export YoY fell in the same band as `value`, with revenue YoY that quarter.
    An empirical reference, not a forecast."""
    if value is None:
        return None
    lo, hi, label = band_of(value)
    rows = [(q, xv, rv) for q, xv, rv in lag_pairs(x, r, 0) if lo <= xv < hi]
    return {"band": label, "quarters": [{"q": q, "x": xv, "r": rv} for q, xv, rv in rows],
            "median": statistics.median([rv for _, _, rv in rows]) if rows else None,
            "positive": sum(1 for _, _, rv in rows if rv > 0)}

"""The inflection radar: what the quarter's customs exports imply for each company's revenue growth
before it is filed, ranked, with the evidence a sceptic asks for. Pure: no network or files.

For every sector the main view's export YoY is fitted (least squares on log changes, same quarter)
to each company's revenue YoY and to the basket. A quarter whose exports are complete but whose
earnings are not yet filed gets a nowcast with a 95% prediction interval; the quarter in progress
gets one from its months so far, widened by how far partial quarters have strayed in the past.
Every fit is checked walking forward (fit on earlier quarters only) against "same YoY as last
quarter", and, with prices, by what holding the stock from the customs release through the
earnings filing paid — per quarter, top versus bottom third of the signal.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Mapping
from datetime import date

from export_overlay import prices as px
from export_overlay import series as s
from export_overlay.build import CompanyInput, _r
from export_overlay.config import Sector
from export_overlay.customs import ItemExports
from export_overlay.dart import due_date

TTM = 4
BAND_POINTS = 25
STRONG = 10.0            # a predicted change of at least this many points (vs the last report) is a signal
MIN_NAMES = 9            # events a quarter needs for a top-vs-bottom-third spread
MIN_OOS = 8              # walk-forward quarters below which a company's record is flagged
MOVED_Z = 2.0            # |z| of the move since the last filing that counts as "already moved"
EARLY_KNOWN = 2          # at the 15th of a quarter's second month the last filed report is two quarters back


# ---------------------------------------------------------------- payload pieces
def _pred(p: dict | None) -> dict | None:
    return None if p is None else {"yoy": _r(p["yoy"]), "lo": _r(p["lo"]), "hi": _r(p["hi"]), "se": _r(p["se"], 3)}


def _fit_payload(f: s.Fit | None, pairs: list) -> tuple[dict | None, float | None]:
    """The fit's numbers plus its line and 95% band sampled across the fitted range (so the page only
    draws) → (payload, dof for the prediction interval = effective sample − 2)."""
    if f is None:
        return None, None
    c = s.correlation(pairs)
    dof = (c["n_eff"] - 2) if c["n_eff"] else f.n - 2
    xs = [a for _, a, _ in pairs]
    lo, hi = math.log1p(min(xs) / 100), math.log1p(max(xs) / 100)
    grid = [math.expm1(lo + (hi - lo) * i / (BAND_POINTS - 1)) * 100 for i in range(BAND_POINTS)]
    band = [dict(x=_r(x), **_pred(s.predict(f, x, dof=dof))) for x in grid]
    return {"n": f.n, "slope": _r(f.slope, 2), "intercept": _r(f.intercept, 3), "r": _r(f.r, 2),
            "lo": _r(c["lo"], 2), "hi": _r(c["hi"], 2), "n_eff": _r(c["n_eff"], 0), "dof": _r(dof, 0),
            "sigma": _r(f.sigma, 3), "span": list(f.span),
            "credible": c["lo"] is not None and c["lo"] > 0, "why": None, "band": band}, dof


def _backtest_payload(bt: dict) -> dict:
    side = lambda d: {"n": d["n"], "hit": _r(d["hit"], 0), "median_change": _r(d["median_change"])}
    wins = round(bt["win"] / 100 * bt["n_prev"]) if bt["win"] is not None else 0
    w = s.wilson(wins, bt["n_prev"]) if bt["n_prev"] else None
    return {"n": bt["n"], "inside95": _r(bt["inside95"], 0), "mae": _r(bt["mae"]), "mae_prev": _r(bt["mae_prev"]),
            "mae_naive": _r(bt["mae_naive"]),
            "n_prev": bt["n_prev"], "ratio": _r(1 - bt["skill"], 2) if bt["skill"] is not None else None,
            "win": _r(bt["win"], 0), "win_lo": _r(w[0], 0) if w else None, "win_hi": _r(w[1], 0) if w else None,
            "signals": bt["signals"], "hit": _r(bt["hit"], 0), "up": side(bt["up"]), "down": side(bt["down"])}


def _margin(qs: Mapping[str, s.Quarter]) -> dict:
    """Operating margin over the last four reported quarters and the four before them."""
    done = sorted(q for q, c in qs.items() if c.revenue and c.operating is not None)
    def over(chunk):
        rev = sum(qs[q].revenue for q in chunk)
        return (sum(qs[q].operating for q in chunk) / rev * 100) if chunk and rev > 0 else None
    return {"ttm": _r(over(done[-TTM:])) if len(done) >= TTM else None,
            "prev": _r(over(done[-2 * TTM:-TTM])) if len(done) >= 2 * TTM else None,
            "last": _r(over(done[-1:])) if done else None}


def _nowcasts(f: s.Fit | None, dof: float | None, pending: list[dict], q_yoy: Mapping[str, float | None],
              q_stat: Mapping[str, float | None], actual: Mapping[str, float | None], qtd: dict | None,
              extra_sd: float | None, last_yoy: float | None) -> list[dict]:
    """One entry per pending quarter: the export figure, the prediction with its interval, the status
    against the last reported YoY ('가속' when the whole interval is above it, '감속' below, else '불명'),
    t = (prediction − last) / SE in log units, and — when the company has filed — the actual."""
    out = []
    for p in pending:
        q = p["q"]
        if p["kind"] == "progress":
            x, months, sd = (qtd or {}).get("yoy"), p["months"], extra_sd
        else:
            x, months, sd = q_stat.get(q), 3, 0.0
        usable = f and x is not None and (p["kind"] != "progress" or sd is not None)
        pred = s.predict(f, x, sd or 0.0, dof) if usable else None
        filed = actual.get(q)
        row = {"q": q, "kind": p["kind"], "due": p.get("due"), "months": months, "x": _r(x),
               "excluded": q_yoy.get(q) is not None and q_stat.get(q) is None,
               "pred": _pred(pred), "actual": _r(filed), "status": None, "t": None, "delta": None, "delta_lo": None,
               "delta_hi": None, "surprise": _r(filed - pred["yoy"]) if (filed is not None and pred) else None,
               "inside": (pred["lo"] <= filed <= pred["hi"]) if (filed is not None and pred) else None}
        if pred and filed is None and last_yoy is not None and last_yoy > -100:
            row.update(delta=_r(pred["yoy"] - last_yoy), delta_lo=_r(pred["lo"] - last_yoy), delta_hi=_r(pred["hi"] - last_yoy),
                       t=_r((pred["log"] - math.log1p(last_yoy / 100)) / pred["se"], 2) if pred["se"] else None,
                       status="가속" if pred["lo"] > last_yoy else "감속" if pred["hi"] < last_yoy else "불명")
        out.append(row)
        if filed is not None:
            last_yoy = filed
    return out


def _focus(nowcasts: list[dict]) -> dict | None:
    """The first pending quarter not yet filed (what the row is ranked on)."""
    return next((n for n in nowcasts if n["actual"] is None), None)


# ---------------------------------------------------------------- evidence
def long_short(events: list[dict], ret: str = "excess", signal: str = "delta") -> dict:
    """Per quarter with at least MIN_NAMES events: mean return of the top third by `signal` minus the
    bottom third. Over quarters: mean with a t-based 95% interval, median, quarters above zero with a
    Wilson interval. Quarters are the unit, so companies moving together in one quarter count once."""
    by_q: dict[str, list[tuple[float, float]]] = {}
    for e in events:
        if e.get(ret) is not None and e.get(signal) is not None:
            by_q.setdefault(e["q"], []).append((e[signal], e[ret]))
    spreads = []
    for q, rows in sorted(by_q.items()):
        if len(rows) < MIN_NAMES:
            continue
        rows.sort(key=lambda row: row[0])          # by the signal only; ties keep their order
        k = len(rows) // 3
        top, bottom = [r for _, r in rows[-k:]], [r for _, r in rows[:k]]
        spreads.append({"q": q, "spread": _r(sum(top) / k - sum(bottom) / k), "names": len(rows)})
    n = len(spreads)
    out = {"n": n, "events": sum(len(v) for v in by_q.values()), "mean": None, "lo": None, "hi": None, "median": None,
           "positive": None, "pos_lo": None, "pos_hi": None, "quarters": spreads}
    if n >= 4:
        vals = [sp["spread"] for sp in spreads]
        mean = sum(vals) / n
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
        half = s.t95(n - 1) * sd / math.sqrt(n)
        pos = sum(v > 0 for v in vals)
        w = s.wilson(pos, n)
        out.update(mean=_r(mean), lo=_r(mean - half), hi=_r(mean + half), median=_r(statistics.median(vals)),
                   positive=_r(pos / n * 100, 0), pos_lo=_r(w[0], 0), pos_hi=_r(w[1], 0))
    return out


def _hit(rows: list[dict]) -> dict:
    k = sum(e["hit"] for e in rows)
    w = s.wilson(k, len(rows)) if rows else None
    return {"n": len(rows), "hit": _r(k / len(rows) * 100, 0) if rows else None,
            "lo": _r(w[0], 0) if w else None, "hi": _r(w[1], 0) if w else None}


def _ratio(bts: list[dict]) -> dict:
    """Pooled nowcast error over pooled "same as last report" error, both over the same quarters."""
    rows = [b for b in bts if b["n_prev"] and b["mae_naive"]]
    naive = sum(b["mae_naive"] * b["n_prev"] for b in rows)
    return {"n": sum(b["n_prev"] for b in rows),
            "value": _r(sum(b["mae_prev"] * b["n_prev"] for b in rows) / naive, 2) if naive else None}


def evidence(company_rows: list[dict], events: list[dict], early: list[dict], signals: list[dict],
             early_signals: list[dict]) -> dict:
    """The pooled record of the walk-forward quarters. Note that 'credible' is itself chosen on that
    record (the error ratio below 1 is part of the gate), so the credible-only figures are not an
    independent test; the unselected ones stand next to them."""
    credible = {c["code"] for c in company_rows if c["fit"] and c["fit"]["credible"]}
    ev = [e for e in events if e["code"] in credible]
    er = [e for e in early if e["code"] in credible]
    out = {"credible": len(credible), "strong": STRONG, "min_names": MIN_NAMES, "moved_z": MOVED_Z,
           "early_known": EARLY_KNOWN,
           "direction": {"all": _hit([e for e in signals if e["signal"]]),
                         "credible": _hit([e for e in signals if e["signal"] and e["code"] in credible]),
                         "early_all": _hit([e for e in early_signals if e["signal"]]),
                         "early_credible": _hit([e for e in early_signals if e["signal"] and e["code"] in credible])},
           "spread": {"signal": long_short(ev), "flash": long_short(ev, "flash"),
                      "oracle": long_short(ev, "excess", "actual_change"), "early": long_short(er)}}
    # calibration and the naive baseline over every walk-forward quarter
    bts = [c["backtest"] for c in company_rows if c["code"] in credible and c["backtest"]["n"]]
    n = sum(b["n"] for b in bts)
    out["inside95"] = {"n": n, "share": _r(sum(b["inside95"] * b["n"] for b in bts) / n, 0) if n else None}
    out["ratio"] = _ratio(bts)
    out["ratio_all"] = _ratio([c["backtest"] for c in company_rows])
    return out


# ---------------------------------------------------------------- the build
def build_screener(sectors: list[tuple[Sector, ItemExports, list[CompanyInput]]], fx: Mapping[str, float],
                   stock_prices: Mapping[str, px.Series], bench: px.Series, today: date, built_at: str,
                   warnings: list[str] | None = None) -> dict:
    sector_rows, company_rows, all_events, all_early, all_signals, all_early_signals = [], [], [], [], [], []
    for sector, exports, companies in sectors:
        view = sector.views[0]
        usd = s.select(exports.months, view.prefixes)
        currency = "KRW" if fx else "USD"
        values = s.to_krw(usd, fx) if fx else usd
        q_yoy = s.yoy_by_quarter(s.quarter_totals(values))
        view_breaks = [(a, b) for a, b, _ in view.breaks]
        q_stat = {q: None if s.in_windows(q, view_breaks) else v for q, v in q_yoy.items()}
        qtd = s.quarter_to_date(values)
        extra_sd = s.qtd_error(values, qtd["months"]) if qtd else None
        # the early read: each quarter's first month alone, masked like q_stat, for the timing check
        first_month = {q: None if s.in_windows(q, view_breaks) else v for q, v in s.partial_yoy(values, 1).items()}
        first_sd = s.qtd_error(values, 1)

        ok = [ci for ci in companies if ci.error is None]
        as_filed = {ci.company.stock_code: s.company_quarters(ci.reports) for ci in ok}
        quarters, _ = s.pro_forma(as_filed, {ci.company.stock_code: ci.company.absorbed for ci in ok if ci.company.absorbed})
        windows = {ci.company.stock_code: [(a, b) for a, b, _ in ci.company.breaks] for ci in ok}
        rev_yoy = {code: s.company_yoy(qs, "revenue", windows[code]) for code, qs in quarters.items()}
        op_yoy = {code: s.company_yoy(qs, "operating", windows[code]) for code, qs in quarters.items()}
        bsk = s.basket(quarters, windows)
        reported, active, filed = s.reporting_status(quarters)
        basket_yoy = {q: b.revenue_yoy for q, b in bsk.items() if reported and q <= reported}

        pending = []
        for q in sorted(s.quarter_totals(values)):
            if reported is not None and q > reported:
                pending.append({"q": q, "kind": "disclosure", "due": due_date(int(q[:4]), int(q[5])).isoformat(),
                                "filed": filed.get(q, 0), "of": active})
        if qtd:
            pending.append({"q": qtd["q"], "kind": "progress", "months": qtd["months"]})

        # ---- basket
        pairs = s.lag_pairs(q_stat, basket_yoy, 0)
        bf = s.fit(pairs)
        fit_row, dof = _fit_payload(bf, pairs)
        last_b = basket_yoy.get(reported) if reported else None
        b_now = _nowcasts(bf, dof, pending, q_yoy, q_stat, {}, qtd, extra_sd, last_b)
        sector_rows.append({
            "key": sector.key, "name": sector.name, "noun": sector.noun, "view": view.label, "currency": currency,
            "caveat": sector.caveat, "companies": len(ok), "reported": reported, "last_yoy": _r(last_b),
            "prev_yoy": _r(basket_yoy.get(s.quarter_shift(reported, -1))) if reported else None,
            "pending": pending, "last_month": max(values) if values else None, "qtd_sd": _r(extra_sd, 3),
            "fit": fit_row, "nowcast": b_now, "focus": _focus(b_now),
            "backtest": _backtest_payload(s.backtest(q_stat, basket_yoy, threshold=STRONG)),
            "history": [{"q": q, "x": _r(a), "r": _r(b)} for q, a, b in pairs],
        })

        # ---- companies
        for ci in ok:
            code = ci.company.stock_code
            ryoy, oyoy, qs = rev_yoy[code], op_yoy[code], quarters[code]
            pairs = s.lag_pairs(q_stat, ryoy, 0)
            f = s.fit(pairs)
            fit_row, dof = _fit_payload(f, pairs)
            last_q = max((q for q, v in ryoy.items() if v is not None), default=None)
            last = ryoy.get(last_q) if last_q else None
            now = _nowcasts(f, dof, pending, q_yoy, q_stat, ryoy, qtd, extra_sd, last)
            bt = s.backtest(q_stat, ryoy, threshold=STRONG)
            if fit_row and bt["skill"] is not None and bt["skill"] <= 0:
                # a correlation the nowcast cannot turn into a better forecast than "same as last quarter"
                fit_row["credible"] = False
                fit_row["why"] = "지난 분기 그대로보다 못 맞힘"
            elif fit_row and not fit_row["credible"]:
                fit_row["why"] = "상관 구간이 0을 품음"
            early = (s.backtest(q_stat, ryoy, threshold=STRONG, x_signal=first_month, extra_sd=first_sd or 0.0, known=EARLY_KNOWN)
                     if first_sd is not None else None)
            all_signals.extend(dict(e, code=code) for e in bt["events"] if e["signal"])
            if early:
                all_early_signals.extend(dict(e, code=code) for e in early["events"] if e["signal"])
            lev = s.fit(s.lag_pairs(ryoy, oyoy, 0))
            # ---- prices
            stock = stock_prices.get(code, [])
            price, events, early_events = None, [], []
            if stock and bench:
                if px.suspicious(stock):
                    price = {"void": "하루 ±40% 넘는 움직임(분할·자료 오류)"}
                else:
                    ex = px.daily_excess(stock, bench)
                    # The report's receipt date, but never past its deadline: a corrected report (정정)
                    # carries the correction's date, and the original was out by the deadline.
                    filings = {q: min(date(int(c.rcept_no[:4]), int(c.rcept_no[4:6]), int(c.rcept_no[6:8])),
                                      due_date(int(q[:4]), int(q[5])))
                               for q, c in qs.items() if len(c.rcept_no) >= 8}
                    last_filing = filings.get(last_q) if last_q else None
                    moved = px.since(ex, last_filing) if last_filing else None
                    price = {"date": stock[-1][0], "close": stock[-1][1], "since": moved,
                             "moved": (abs(moved["z"]) >= MOVED_Z) if (moved and moved["z"] is not None) else None,
                             "prior63": _r(px.prior_excess(ex, date.fromisoformat(stock[-1][0])))}
                    if moved:
                        price["since"] = dict(moved, excess=_r(moved["excess"]), z=_r(moved["z"], 1))
                    events = px.event_study(bt["events"], ex, filings)
                    if early:
                        early_events = px.event_study(early["events"], ex, filings, months=1)
            all_events.extend(dict(e, code=code) for e in events)
            all_early.extend(dict(e, code=code) for e in early_events)
            focus = _focus(now)
            company_rows.append({
                "code": code, "name": ci.company.name, "sector": sector.key, "sector_name": sector.name,
                "note": ci.company.note, "last_q": last_q, "last_yoy": _r(last),
                "prev_yoy": _r(ryoy.get(s.quarter_shift(last_q, -1))) if last_q else None,
                "last_op_yoy": _r(oyoy.get(last_q)) if last_q else None,
                "fit": fit_row, "nowcast": now, "focus": focus,
                "backtest": _backtest_payload(bt),
                "early": {"n": early["n"], "signals": early["signals"], "hit": _r(early["hit"], 0),
                          "ratio": _r(1 - early["skill"], 2) if early["skill"] is not None else None} if early else None,
                "backtest_events": [{"q": e["q"], "x": _r(e["x"]), "pred": _r(e["pred"]), "lo": _r(e["lo"]), "hi": _r(e["hi"]),
                                     "actual": _r(e["actual"]), "inside": e["inside"], "prev": _r(e["prev"]),
                                     "signal": e["signal"], "hit": e["hit"],
                                     "excess": next((_r(x["excess"]) for x in events if x["q"] == e["q"]), None)}
                                    for e in bt["events"]],
                "leverage": {"n": lev.n, "slope": _r(lev.slope, 2), "r": _r(lev.r, 2)} if lev else None,
                "margin": _margin(qs),
                "price": price,
                "history": [{"q": q, "x": _r(a), "r": _r(b)} for q, a, b in pairs],
            })

    ev = evidence(company_rows, all_events, all_early, all_signals, all_early_signals)
    live = [c for c in company_rows if c["fit"] and c["fit"]["credible"] and c["focus"] and c["focus"]["status"]]
    n_live = len(live)
    ev["now"] = {"n": n_live,
                 "up": sum(1 for c in live if c["focus"]["status"] == "가속"),
                 "down": sum(1 for c in live if c["focus"]["status"] == "감속"),
                 "null_mean": _r(0.05 * n_live), "null_sd": _r(math.sqrt(n_live * 0.05 * 0.95))}
    ev.update(after_filing=px.AFTER_FILING, lookback=px.LOOKBACK, vol_days=px.VOL_DAYS, min_vol_days=px.MIN_VOL_DAYS,
              priced=sum(1 for c in company_rows if c["price"] and "void" not in c["price"]),
              bench={"first": bench[0][0], "last": bench[-1][0]} if bench else None)
    return {"built_at": built_at, "today": today.isoformat(), "sectors": sector_rows, "companies": company_rows,
            "evidence": ev, "warnings": list(warnings or [])}

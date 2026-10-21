"""Turn fetched inputs into the JSON payload the page renders. Pure: no network or files.

Every number on the page is computed here (via `series`); the page script only draws.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from export_overlay import series as s
from export_overlay.config import Company, Sector
from export_overlay.customs import ItemExports
from export_overlay.dart import ReportFigures, due_date

EOK = 1e8          # 억원
TOP_DESTINATIONS = 5


@dataclass
class CompanyInput:
    company: Company
    reports: Mapping[tuple[int, int], ReportFigures | None] = field(default_factory=dict)
    error: str | None = None
    missing: list[str] = field(default_factory=list)    # past-deadline reports that failed with nothing cached


def _r(v: float | None, nd: int = 1) -> float | None:
    return None if v is None else round(v, nd)


def _eok(v: float | None) -> float | None:
    return None if v is None else round(v / EOK, 1)


def _destinations(exports: ItemExports, months: list[str], prefixes: tuple[str, ...]) -> list[dict]:
    totals: dict[str, float] = {}
    for ym in months:
        for hs, by_country in exports.countries.get(ym, {}).items():
            if s.matches(hs, prefixes):
                for name, usd in by_country.items():
                    totals[name] = totals.get(name, 0.0) + usd
    grand = sum(totals.values())
    top = sorted(totals.items(), key=lambda kv: -kv[1])[:TOP_DESTINATIONS]
    return [{"name": name, "share": _r(v / grand * 100)} for name, v in top] if grand else []


def _stats(stats: list[dict]) -> list[dict]:
    return [{"lag": d["lag"], "n": d["n"], "r": _r(d["r"], 2), "lo": _r(d["lo"], 2), "hi": _r(d["hi"], 2),
             "n_eff": _r(d["n_eff"], 0), "hit": _r(d["hit"], 0), "chance": _r(d["chance"], 0),
             "flat": d["flat"], "span": list(d["span"]) if d["span"] else None} for d in stats]


def build_payload(sector: Sector, exports: ItemExports, fx: Mapping[str, float],
                  companies: list[CompanyInput], built_at: str, warnings: list[str] | None = None) -> dict:
    months_all = sorted(exports.months)
    shown = [m for m in months_all if months_all and m >= s.ym_shift(months_all[0], 12)]
    last12 = months_all[-12:]

    # ---- companies
    ok = [ci for ci in companies if ci.error is None]
    as_filed = {ci.company.stock_code: s.company_quarters(ci.reports) for ci in ok}
    quarters, proforma = s.pro_forma(as_filed, {ci.company.stock_code: ci.company.absorbed for ci in ok if ci.company.absorbed})
    windows = {ci.company.stock_code: [(a, b) for a, b, _ in ci.company.breaks] for ci in ok}
    rev_yoy = {code: s.company_yoy(qs, "revenue", windows[code]) for code, qs in quarters.items()}
    op_yoy = {code: s.company_yoy(qs, "operating", windows[code]) for code, qs in quarters.items()}
    bsk = s.basket(quarters, windows)
    reported, active, filed = s.reporting_status(quarters)
    # Quarters only some companies have filed are drawn (dashed) but never feed statistics or analogs:
    # a one-company "basket" for the quarter under disclosure must not become its own past analog.
    basket_yoy = {q: b.revenue_yoy for q, b in bsk.items() if reported and q <= reported}
    names = {ci.company.stock_code: ci.company.name for ci in companies}

    # ---- reporting status: every quarter after the last fully reported one is shaded
    main_view = sector.views[0]
    total_usd = s.select(exports.months, main_view.prefixes)
    complete = s.quarter_totals(total_usd)
    qtd_total = s.quarter_to_date(total_usd)
    pending = []
    for q in sorted(complete):
        if reported is not None and q > reported:      # no company data at all → nothing is "공시 전"
            pending.append({"q": q, "kind": "disclosure", "due": due_date(int(q[:4]), int(q[5])).isoformat(),
                            "filed": filed.get(q, 0), "of": active})
    if qtd_total:
        pending.append({"q": qtd_total["q"], "kind": "progress", "months": qtd_total["months"]})
    disclosure = next((p["q"] for p in reversed(pending) if p["kind"] == "disclosure"), None)

    # ---- exports per view × currency
    currencies = (["KRW"] if fx else []) + ["USD"]
    total12 = sum(total_usd.get(m, 0.0) for m in last12)
    codes, payload_exports, destinations = [], {}, {}
    years = sorted({m[:4] for m in months_all})
    year_total = {y: sum(v for m, v in total_usd.items() if m[:4] == y) for y in years}
    for view in sector.views:
        key = view.key
        usd = s.select(exports.months, view.prefixes)
        share = sum(usd.get(m, 0.0) for m in last12) / total12 * 100 if total12 else None
        yearly = {y: _r(sum(v for m, v in usd.items() if m[:4] == y) / year_total[y] * 100)
                  for y in years if year_total[y]}
        inside = all(any(p.startswith(m) for m in main_view.prefixes) for p in view.prefixes)
        view_breaks = [(a, b) for a, b, _ in view.breaks]
        codes.append({"key": key, "label": view.label, "share": _r(share), "yearly": yearly, "mix": view.in_mix,
                      "inside": inside, "breaks": [{"from": a, "to": b, "reason": why} for a, b, why in view.breaks]})
        destinations[key] = _destinations(exports, last12, view.prefixes)
        for cur in currencies:
            values = s.to_krw(usd, fx) if cur == "KRW" else usd
            monthly, roll = s.yoy_monthly(values), s.yoy_rolling3(values)
            q_yoy = s.yoy_by_quarter(s.quarter_totals(values))
            # the view's own break windows (a new HS code, goods that are not the sector's) stay on the chart
            # but out of every statistic
            q_stat = {q: None if s.in_windows(q, view_breaks) else v for q, v in q_yoy.items()}
            lags = {"basket": _stats(s.lag_stats(q_stat, basket_yoy))}
            for code, ryoy in rev_yoy.items():
                lags[code] = _stats(s.lag_stats(q_stat, ryoy))
            analog = s.analogs(q_stat, basket_yoy, q_yoy.get(disclosure)) if disclosure else None
            if analog:
                analog = dict(analog, median=_r(analog["median"]),
                              quarters=[{"q": a["q"], "x": _r(a["x"]), "r": _r(a["r"])} for a in analog["quarters"]])
            qtd = s.quarter_to_date(values)
            payload_exports[f"{key}|{cur}"] = {
                "value": [_r(values.get(m), 0) for m in shown],
                "yoy": [_r(monthly.get(m)) for m in shown],
                "yoy3": [_r(roll.get(m)) for m in shown],
                "quarters": {q: {"value": _r(v, 0), "yoy": _r(q_yoy.get(q))}
                             for q, v in s.quarter_totals(values).items() if shown and q >= s.quarter_of(shown[0])},
                "qtd": dict(qtd, yoy=_r(qtd["yoy"])) if qtd else None,
                "lags": lags,
                "analog": analog,
            }

    company_rows = []
    for ci in companies:
        code = ci.company.stock_code
        qs = quarters.get(code, {})
        restated = s.restated(as_filed.get(code, {})) if qs else set()
        company_rows.append({
            "code": code, "name": ci.company.name, "error": ci.error, "note": ci.company.note,
            "breaks": [{"from": a, "to": b, "reason": why} for a, b, why in ci.company.breaks],
            "first_yoy": min((q for q, v in rev_yoy.get(code, {}).items() if v is not None), default=None),
            "last": max(qs) if qs else None,
            "quarters": {q: {"revenue": _eok(c.revenue), "operating": _eok(c.operating), "basis": c.basis,
                             "revenue_yoy": _r(rev_yoy[code].get(q)), "operating_yoy": _r(op_yoy[code].get(q)),
                             "restated": q in restated, "excluded": s.in_windows(q, windows[code]),
                             "proforma": (code, q) in proforma,
                             "rcept_no": c.rcept_no}
                         for q, c in sorted(qs.items())},
        })

    return {
        "sector": {"key": sector.key, "name": sector.name, "noun": sector.noun, "hs": list(sector.hs),
                   "caveat": sector.caveat, "excluded_note": sector.excluded_note, "mix_note": sector.mix_note},
        "nav": [],                                   # filled by main with every built sector
        "built_at": built_at,
        "months": shown,
        "fx": [_r(fx.get(m), 2) for m in shown],
        "codes": codes,
        "currencies": currencies,
        "exports": payload_exports,
        "destinations": destinations,
        "destinations_span": [last12[0], last12[-1]] if last12 else None,
        "basket": {q: {"revenue": _eok(b.revenue), "operating": _eok(b.operating), "margin": _r(b.margin),
                       "reported": b.reported, "revenue_yoy": _r(b.revenue_yoy), "operating_yoy": _r(b.operating_yoy),
                       "matched": b.matched, "median_yoy": _r(b.median_yoy), "coverage": _r(b.coverage, 0),
                       "top": {"name": names.get(b.top[0], b.top[0]), "share": _r(b.top[1], 0)} if b.top else None}
                   for q, b in bsk.items()},
        "companies": company_rows,
        "reported": reported,
        "pending": pending,
        "warnings": list(warnings or []) + [f"{ci.company.name}: {ci.error}" for ci in companies if ci.error]
                    + [f"{ci.company.name}: 보고서 못 받음 {', '.join(ci.missing)}" for ci in companies if ci.missing],
    }


def summary(payload: dict) -> dict:
    """The few numbers the sector overview page shows for one sector (main view, KRW when available)."""
    cur = payload["currencies"][0]
    main = payload["codes"][0]["key"]
    ex = payload["exports"][f"{main}|{cur}"]
    disclosure = next((p for p in reversed(payload["pending"]) if p["kind"] == "disclosure"), None)
    reported = payload["reported"]
    basket = payload["basket"].get(reported) if reported else None
    lag0 = next((d for d in ex["lags"]["basket"] if d["lag"] == 0), None)
    lag1 = next((d for d in ex["lags"]["basket"] if d["lag"] == 1), None)
    months = payload["months"]
    n = min(len(months), 60)
    quarter_yoy = {q: v["revenue_yoy"] for q, v in payload["basket"].items()}
    return {
        "key": payload["sector"]["key"], "name": payload["sector"]["name"], "noun": payload["sector"]["noun"],
        "hs": payload["sector"]["hs"], "view": payload["codes"][0]["label"], "currency": cur,
        "companies": sum(1 for c in payload["companies"] if not c["error"]),
        "last_month": months[-1] if months else None,
        "yoy3_last": ex["yoy3"][-1] if ex["yoy3"] else None,
        "pending": {"q": disclosure["q"], "due": disclosure["due"], "filed": disclosure["filed"], "of": disclosure["of"],
                    "yoy": (ex["quarters"].get(disclosure["q"]) or {}).get("yoy")} if disclosure else None,
        "reported": reported,
        "revenue_yoy": basket["revenue_yoy"] if basket else None,
        "export_yoy_same_q": (ex["quarters"].get(reported) or {}).get("yoy") if reported else None,
        "margin": basket["margin"] if basket else None,
        "lag0": lag0, "lag1": lag1,
        "analog": ex["analog"],
        # last five years for the overview's small chart
        "months": months[-n:], "yoy3": ex["yoy3"][-n:],
        "basket_yoy": {q: v for q, v in quarter_yoy.items()            # fully reported quarters only
                       if months and reported and s.quarter_of(months[-n]) <= q <= reported},
        "pending_qs": [p["q"] for p in payload["pending"]],
    }

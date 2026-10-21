import json
import math
from datetime import date

import pytest

from export_overlay import prices as px
from export_overlay import screener
from export_overlay.build import CompanyInput
from export_overlay.cache import JsonCache
from export_overlay.config import Company, Sector, View
from export_overlay.customs import ItemExports
from export_overlay.dart import Figure, ReportFigures


def closes(start, n, step=1.0, first=100.0):
    """n trading days (weekdays) from `start`, price rising by `step` a day."""
    out, d, i = [], start, 0
    while len(out) < n:
        if d.weekday() < 5:
            out.append((d.isoformat(), first + step * i))
            i += 1
        d = date.fromordinal(d.toordinal() + 1)
    return out


def test_signal_flash_dates():
    assert px.signal_date("2026Q3") == date(2026, 10, 15)
    assert px.signal_date("2025Q4") == date(2026, 1, 15)
    assert px.signal_date("2026Q3", 1) == date(2026, 8, 15)
    assert px.signal_date("2026Q4", 2) == date(2026, 12, 15)
    assert px.flash_date("2026Q3") == date(2026, 10, 1) and px.flash_date("2026Q4") == date(2027, 1, 1)


def test_daily_excess_windows_and_since():
    stock = closes(date(2024, 1, 1), 600, step=1.0)
    bench = closes(date(2024, 1, 1), 600, step=0.5)
    ex = px.daily_excess(stock, bench)
    assert len(ex) == 599 and ex[0][0] == stock[1][0]
    assert ex[0][1] == pytest.approx(math.log(101 / 100) - math.log(100.5 / 100))
    start, end = date(2025, 3, 3), date(2025, 6, 2)
    dates = [d for d, _ in ex]
    i, j = next(k for k, d in enumerate(dates) if d >= start.isoformat()), next(k for k, d in enumerate(dates) if d >= end.isoformat())
    want = math.expm1(sum(v for _, v in ex[i + 1:j + 6])) * 100
    assert px.window_excess(ex, start, end) == pytest.approx(want)
    assert px.window_excess(ex, end, start) is None                            # ends before it starts
    assert px.window_excess(ex, start, date(2027, 1, 1)) is None               # not complete
    assert px.prior_excess(ex, date(2024, 2, 1)) is None                       # fewer than 63 days before
    assert px.prior_excess(ex, end) == pytest.approx(math.expm1(sum(v for _, v in ex[j - 62:j + 1])) * 100)
    got = px.since(ex, date(2025, 9, 1))
    assert got["from"] >= "2025-09-01" and got["days"] > 0 and got["z"] is not None
    assert px.since(ex, date(2024, 3, 1)) is None                               # not enough history for σ
    assert px.since(ex, date(2030, 1, 1)) is None
    # a stock that only ever matches the index has no excess and no z
    flat = px.daily_excess(stock, stock)
    assert all(v == 0 for _, v in flat) and px.since(flat, date(2025, 9, 1))["z"] is None


def test_suspicious_moves_are_symmetric_and_spare_limit_days():
    assert not px.suspicious(closes(date(2024, 1, 1), 50))
    assert px.suspicious([("2024-01-02", 100.0), ("2024-01-03", 45.0)])            # a 1:2 split
    assert px.suspicious([("2024-01-02", 100.0), ("2024-01-03", 150.0)])
    assert not px.suspicious([("2024-01-02", 100.0), ("2024-01-03", 70.0)])        # 하한가
    assert not px.suspicious([("2024-01-02", 100.0), ("2024-01-03", 130.0)])       # 상한가


def test_fetch_series_caches_and_swallows_failures(tmp_path):
    cache = JsonCache(tmp_path)
    calls = []
    rows = [(date.fromordinal(date(2025, 1, 1).toordinal() + i), 10.0 + i) for i in range(300)]
    got = px.fetch_series("000001", date(2025, 1, 1), date(2026, 1, 1), cache, lambda *a: calls.append(a) or rows)
    assert len(got) == 300 and got[0] == ("2025-01-01", 10.0)
    px.fetch_series("000001", date(2025, 1, 1), date(2026, 1, 1), cache, lambda *a: calls.append(a) or rows)
    assert len(calls) == 1
    def boom(*a):
        raise RuntimeError("no network")
    assert px.fetch_series("000002", date(2025, 1, 1), date(2026, 1, 1), cache, boom) == []
    assert px.fetch_series("000003", date(2025, 1, 1), date(2026, 1, 1), cache, lambda *a: rows[:10]) == []   # too short


def test_event_study_needs_previous_quarter_and_filing():
    stock = closes(date(2019, 1, 1), 2000, step=0.2)
    bench = closes(date(2019, 1, 1), 2000, step=0.1)
    ex = px.daily_excess(stock, bench)
    events = [{"q": "2021Q1", "pred": 20.0, "prev": 5.0, "actual": 18.0, "signal": "up", "hit": True},
              {"q": "2021Q2", "pred": 6.0, "prev": 5.0, "actual": 4.0, "signal": None, "hit": None},
              {"q": "2021Q3", "pred": 6.0, "prev": None, "actual": 4.0, "signal": None, "hit": None},
              {"q": "2021Q4", "pred": 6.0, "prev": 1.0, "actual": 4.0, "signal": None, "hit": None}]
    filings = {"2021Q1": date(2021, 5, 14), "2021Q2": date(2021, 8, 13), "2021Q3": date(2021, 11, 15)}
    got = px.event_study(events, ex, filings)
    assert [e["q"] for e in got] == ["2021Q1", "2021Q2"]                      # no previous quarter / no filing → no event
    assert got[0]["day"] == "2021-04-15" and got[0]["delta"] == 15.0 and got[0]["actual_change"] == 13.0
    assert got[0]["excess"] is not None and got[0]["flash"] is not None and got[0]["prior"] is not None
    early = px.event_study(events, ex, filings, months=1)
    assert early[0]["day"] == "2021-02-15" and early[0]["flash"] is None


def test_long_short_by_quarter():
    assert screener.long_short([])["n"] == 0
    few = [{"q": "2020Q1", "delta": i, "excess": i * 2.0} for i in range(10)]
    assert screener.long_short(few)["n"] == 1 and screener.long_short(few)["mean"] is None
    many = [{"q": f"2020Q{k}", "delta": i, "excess": (i if k != 2 else -i) * 1.0} for k in (1, 2, 3, 4) for i in range(9)]
    ls = screener.long_short(many)
    assert ls["n"] == 4 and ls["events"] == 36
    assert [sp["spread"] for sp in ls["quarters"]] == [6.0, -6.0, 6.0, 6.0]    # top third (6,7,8) − bottom third (0,1,2)
    assert ls["mean"] == 3.0 and ls["positive"] == 75.0 and ls["lo"] < 3.0 < ls["hi"]
    assert screener.long_short(many, "excess", "missing")["n"] == 0
    # tied signals keep their input order instead of being sorted by return (which would fake a spread)
    tied = [{"q": "2020Q1", "delta": 1.0, "excess": float(8 - i)} for i in range(9)]
    assert screener.long_short(tied)["quarters"][0]["spread"] == pytest.approx(-6.0)


# ---------------------------------------------------------------- the screener on a toy sector
SECTOR = Sector(key="toy", name="장난감", noun="회사", hs=("9503",), views=(View("9503", "전체", ("9503",)),),
                companies=(Company("000001", "가"), Company("000002", "나")), caveat="장난감 주의")


def exports(n_months=129, growth_by_year=None):
    """Monthly exports 2016-01 .. (129 months = through 2026-09) with a year-specific growth."""
    growth_by_year = growth_by_year or {}
    months = {}
    base = 100.0
    for i in range(n_months):
        ym = f"{2016 + i // 12}{i % 12 + 1:02d}"
        g = growth_by_year.get(2016 + i // 12, 0.1)
        months[ym] = {"950300": base * (1 + g) ** (i / 12) * (1 + 0.05 * (i % 3))}
    return ItemExports(months, {})


def reports(scale, rev_growth):
    """Quarterly reports 2016-2026Q2 whose revenue YoY tracks `rev_growth(year)`; filed on the deadline."""
    out = {}
    for y in range(2016, 2027):
        for q in (1, 2, 3, 4):
            if (y, q) > (2026, 2):
                out[(y, q)] = None
                continue
            g = rev_growth(y)
            v = scale * (1 + g) ** (y - 2016) * (1 + 0.1 * q)
            prev = scale * (1 + rev_growth(y - 1)) ** (y - 2017) * (1 + 0.1 * q) if y > 2016 else None
            rcept = f"{y + (q == 4)}{(5, 8, 11, 3)[q - 1]:02d}14000001"
            if q == 4:
                cum = sum(scale * (1 + g) ** (y - 2016) * (1 + 0.1 * k) for k in (1, 2, 3, 4))
                pcum = sum(scale * (1 + rev_growth(y - 1)) ** (y - 2017) * (1 + 0.1 * k) for k in (1, 2, 3, 4)) if y > 2016 else None
                out[(y, q)] = ReportFigures("CFS", Figure(cum, cum, pcum, pcum),
                                            Figure(cum / 10, cum / 10, pcum / 10 if pcum else None, pcum / 10 if pcum else None), rcept)
            else:
                cum = sum(scale * (1 + g) ** (y - 2016) * (1 + 0.1 * k) for k in range(1, q + 1))
                pcum = sum(scale * (1 + rev_growth(y - 1)) ** (y - 2017) * (1 + 0.1 * k) for k in range(1, q + 1)) if y > 2016 else None
                out[(y, q)] = ReportFigures("CFS", Figure(v, cum, prev, pcum),
                                            Figure(v / 10, cum / 10, prev / 10 if prev else None, pcum / 10 if pcum else None), rcept)
    return out


def test_screener_payload_shapes_and_gates():
    growth = {y: 0.05 + 0.03 * ((y * 7) % 5) for y in range(2016, 2027)}
    ex = exports(growth_by_year=growth)
    companies = [CompanyInput(Company("000001", "가"), reports(100, lambda y: growth.get(y, 0.1))),
                 CompanyInput(Company("000002", "나"), reports(50, lambda y: 0.02)),       # flat: no relation
                 CompanyInput(Company("000003", "다"), error="DART 고유번호 없음")]
    stock = {"000001": closes(date(2015, 1, 2), 3080, step=0.3), "000002": closes(date(2015, 1, 2), 3080, step=0.1)}
    bench = closes(date(2015, 1, 2), 3080, step=0.2)                               # through 2026-10
    p = screener.build_screener([(SECTOR, ex, companies)], {}, stock, bench, date(2026, 10, 21), "2026-10-21 09:00")
    assert [c["code"] for c in p["companies"]] == ["000001", "000002"]           # errors are left out
    s = p["sectors"][0]
    assert s["key"] == "toy" and s["currency"] == "USD" and s["reported"] == "2026Q2" and s["caveat"] == "장난감 주의"
    assert [n["q"] for n in s["pending"]] == ["2026Q3"] and s["pending"][0]["kind"] == "disclosure"
    a = p["companies"][0]
    assert a["fit"] and a["fit"]["n"] >= 12 and len(a["fit"]["band"]) == screener.BAND_POINTS and a["fit"]["dof"] is not None
    f = a["focus"]
    assert f["q"] == "2026Q3" and f["pred"]["lo"] <= f["pred"]["yoy"] <= f["pred"]["hi"] and f["actual"] is None
    assert f["delta"] == pytest.approx(f["pred"]["yoy"] - a["last_yoy"], abs=0.11)
    assert f["delta_lo"] <= f["delta"] <= f["delta_hi"] and f["status"] in ("가속", "감속", "불명") and f["t"] is not None
    assert (f["status"] == "가속") == (f["pred"]["lo"] > a["last_yoy"])
    assert a["backtest"]["n"] > 0 and a["backtest"]["n"] == len(a["backtest_events"])
    assert a["backtest"]["win_lo"] is not None and a["backtest"]["ratio"] is not None
    assert a["price"]["since"] and a["price"]["since"]["from"] >= "2026-08-14" and a["price"]["moved"] is not None
    assert a["margin"]["ttm"] == pytest.approx(10.0)
    assert a["early"] is not None
    b = p["companies"][1]
    assert b["fit"] is None or (not b["fit"]["credible"] and b["fit"]["why"])    # a flat company shows no credible relation
    e = p["evidence"]
    assert e["credible"] == sum(1 for c in p["companies"] if c["fit"] and c["fit"]["credible"])
    assert set(e) >= {"direction", "spread", "inside95", "ratio", "ratio_all", "now", "priced", "after_filing", "strong", "moved_z"}
    assert set(e["direction"]) == {"all", "credible", "early_all", "early_credible"}
    assert set(e["spread"]) == {"signal", "flash", "oracle", "early"}
    assert all(abs(ev["pred"] - ev["prev"]) >= screener.STRONG for c in p["companies"] for ev in c["backtest_events"] if ev["signal"])
    assert e["ratio_all"]["n"] >= e["ratio"]["n"]
    assert e["now"]["n"] == e["now"]["up"] + e["now"]["down"] + sum(1 for c in p["companies"] if c["fit"] and c["fit"]["credible"] and c["focus"]["status"] == "불명")
    text = json.dumps(p, ensure_ascii=False)
    assert "NaN" not in text and "Infinity" not in text


def test_screener_without_prices_has_no_price_columns():
    ex = exports()
    companies = [CompanyInput(Company("000001", "가"), reports(100, lambda y: 0.1))]
    p = screener.build_screener([(SECTOR, ex, companies)], {}, {}, [], date(2026, 10, 21), "now")
    c = p["companies"][0]
    assert c["price"] is None and p["evidence"]["priced"] == 0
    assert p["evidence"]["spread"]["signal"]["n"] == 0 and p["evidence"]["spread"]["signal"]["mean"] is None


def test_split_like_moves_void_the_price_columns():
    ex = exports()
    companies = [CompanyInput(Company("000001", "가"), reports(100, lambda y: 0.1))]
    stock = closes(date(2015, 1, 2), 3080, step=0.3)
    stock[1000] = (stock[1000][0], stock[999][1] * 3)
    bench = closes(date(2015, 1, 2), 3080, step=0.2)
    p = screener.build_screener([(SECTOR, ex, companies)], {}, {"000001": stock}, bench, date(2026, 10, 21), "now")
    assert "void" in p["companies"][0]["price"] and p["evidence"]["priced"] == 0

import math

import pytest

from export_overlay import series as s


def _pairs(n, slope=0.8, noise=0.0):
    """Quarters with export YoY x and revenue YoY following ln(1+r) = 0.02 + slope·ln(1+x) (+ a fixed wobble)."""
    out = []
    for i in range(n):
        q = s.quarter_shift("2016Q1", i)
        x = 30 * math.sin(i / 2) + 5
        ly = 0.02 + slope * math.log1p(x / 100) + noise * (1 if i % 2 else -1)
        out.append((q, x, math.expm1(ly) * 100))
    return out


def test_t95_matches_the_table_and_interpolates():
    assert s.t95(10) == pytest.approx(2.228)
    assert s.t95(1000) == 1.96
    assert 2.179 < s.t95(11) < 2.228
    assert s.t95(0.5) == pytest.approx(12.706)


def test_fit_recovers_slope_and_predict_brackets_the_truth():
    f = s.fit(_pairs(20, slope=0.8))
    assert f.n == 20 and f.slope == pytest.approx(0.8) and f.intercept == pytest.approx(0.02)
    assert f.sigma == pytest.approx(0.0, abs=1e-9) and f.r == pytest.approx(1.0)
    p = s.predict(f, 25.0)
    assert p["yoy"] == pytest.approx((math.exp(0.02) * 1.25 ** 0.8 - 1) * 100)
    assert p["lo"] == pytest.approx(p["yoy"], abs=1e-6)                     # no residual → no interval width
    noisy = s.fit(_pairs(20, slope=0.8, noise=0.05))
    p = s.predict(noisy, 25.0)
    assert p["lo"] < p["yoy"] < p["hi"]
    wider = s.predict(noisy, 25.0, extra_sd=0.1)
    assert wider["hi"] - wider["lo"] > p["hi"] - p["lo"]                   # quarter-to-date uncertainty widens it
    assert s.predict(noisy, -100.0) is None


def test_fit_needs_twelve_pairs_and_spread():
    assert s.fit(_pairs(11)) is None
    flat = [(q, 10.0, r) for q, _, r in _pairs(15)]
    assert s.fit(flat) is None


def test_qtd_error_measures_how_partial_quarters_stray():
    months = {}
    for i in range(48):                                   # 2016-01 .. 2019-12
        ym = s.ym_shift("201601", i)
        months[ym] = 100.0 + (20 if ym.endswith("03") or ym.endswith("06") or ym.endswith("09") or ym.endswith("12") else 0) + i
    assert s.qtd_error(months, 1) is not None and s.qtd_error(months, 1) >= 0
    assert s.qtd_error(months, 3) == pytest.approx(0.0, abs=1e-12)        # three months IS the quarter
    assert s.qtd_error({"202601": 1.0}, 1) is None


def test_backtest_walks_forward_and_scores_direction():
    pairs = _pairs(24, slope=0.9, noise=0.03)
    x = {q: xv for q, xv, _ in pairs}
    r = {q: rv for q, _, rv in pairs}
    bt = s.backtest(x, r)
    assert bt["n"] == 24 - s.MIN_PAIRS                    # the first 12 quarters only train
    assert all(e["q"] >= "2019Q1" for e in bt["events"])
    assert bt["inside95"] is not None and bt["mae"] is not None
    assert bt["signals"] == bt["up"]["n"] + bt["down"]["n"]
    assert bt["hit"] is not None and 0 <= bt["hit"] <= 100
    assert all(e["prev"] is not None for e in bt["events"])
    assert bt["n_prev"] == bt["n"] and bt["mae_naive"] > bt["mae"]           # exports beat "same as last quarter" here
    assert bt["skill"] == pytest.approx(1 - bt["mae"] / bt["mae_naive"]) and bt["win"] > 50
    # a prediction made for q uses no pair at or after q: predicting from the first 12 only, and its
    # interval uses that training set's effective sample like the live nowcast does
    first = bt["events"][0]
    f = s.fit(pairs[:s.MIN_PAIRS])
    n_eff = s.correlation(pairs[:s.MIN_PAIRS])["n_eff"]
    want = s.predict(f, first["x"], dof=n_eff - 2)
    assert first["pred"] == pytest.approx(want["yoy"]) and first["lo"] == pytest.approx(want["lo"])
    assert bt["mae_prev"] is not None and bt["mae_prev"] <= bt["mae"] * 1.5


def test_partial_yoy_and_early_signal_backtest():
    months = {s.ym_shift("201601", i): 100.0 * (1.1 ** (i // 12)) * (1 + 0.3 * (i % 3 == 0)) for i in range(60)}
    one = s.partial_yoy(months, 1)
    assert one["2017Q1"] == pytest.approx(10.0) and "2016Q1" not in one       # no year-earlier month
    assert s.partial_yoy(months, 3)["2017Q2"] == pytest.approx(10.0)
    pairs = _pairs(24, slope=0.9, noise=0.03)
    x = {q: xv for q, xv, _ in pairs}
    r = {q: rv for q, _, rv in pairs}
    early = {q: xv * 0.9 + 1 for q, xv in x.items()}                          # a noisy first-month read
    bt = s.backtest(x, r, x_signal=early, extra_sd=0.05)
    full = s.backtest(x, r)
    assert bt["n"] == full["n"] and bt["events"][0]["x"] == pytest.approx(early[bt["events"][0]["q"]])
    assert bt["events"][0]["hi"] - bt["events"][0]["lo"] > full["events"][0]["hi"] - full["events"][0]["lo"]
    # read at the 15th of the second month, the last public report is two quarters back: the fit stops
    # at q−2 and the comparison is with q−2's YoY, so the first predictable quarter moves one later
    two = s.backtest(x, r, x_signal=early, extra_sd=0.05, known=2)
    assert two["n"] == full["n"] - 1 and two["events"][0]["q"] == s.quarter_shift(full["events"][0]["q"], 1)
    first = two["events"][0]
    assert first["prev"] == pytest.approx(r[s.quarter_shift(first["q"], -2)])
    f = s.fit([p for p in pairs if p[0] <= s.quarter_shift(first["q"], -2)])
    assert first["pred"] == pytest.approx(s.predict(f, first["x"])["yoy"])


def test_backtest_without_pairs_is_empty():
    bt = s.backtest({"2020Q1": 5.0}, {"2020Q1": 3.0})
    assert bt == {"n": 0, "signals": 0, "inside95": None, "mae": None, "mae_prev": None, "mae_naive": None, "n_prev": 0,
                  "skill": None, "win": None, "hit": None, "events": [],
                  "up": {"n": 0, "hit": None, "median_change": None},
                  "down": {"n": 0, "hit": None, "median_change": None}}

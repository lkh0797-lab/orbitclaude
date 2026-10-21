import math

import pytest

from export_overlay import series as s
from export_overlay.dart import Figure, ReportFigures


def rep(basis, rev, op=None, rcept="r"):
    """rev/op: (cur, cum, prev, prev_cum)."""
    return ReportFigures(basis, Figure(*rev), Figure(*op) if op else None, rcept)


def test_labels():
    assert s.ym_shift("202601", -1) == "202512" and s.ym_shift("202512", 13) == "202701"
    assert s.month_range("202511", "202602") == ["202511", "202512", "202601", "202602"]
    assert s.quarter_of("202609") == "2026Q3" and s.quarter_of("202610") == "2026Q4"
    assert s.quarter_months("2026Q4") == ["202610", "202611", "202612"]
    assert s.quarter_shift("2026Q1", -1) == "2025Q4" and s.quarter_shift("2025Q4", 4) == "2026Q4"
    assert s.in_windows("2019Q3", [("2019Q1", "2020Q4")]) and not s.in_windows("2021Q1", [("2019Q1", "2020Q4")])


def test_pct_change_refuses_non_positive_base():
    assert s.pct_change(150, 100) == pytest.approx(50)
    assert s.pct_change(10, 0) is None and s.pct_change(10, -5) is None and s.pct_change(None, 5) is None


def test_export_yoy_rolling_and_quarters():
    usd = {s.ym_shift("202401", i): 100.0 + i for i in range(24)}   # 202401..202512
    m = s.yoy_monthly(usd)
    assert m["202401"] is None
    assert m["202501"] == pytest.approx((112 / 100 - 1) * 100)
    r3 = s.yoy_rolling3(usd)
    assert r3["202502"] is None
    assert r3["202503"] == pytest.approx(((112 + 113 + 114) / (100 + 101 + 102) - 1) * 100)
    totals = s.quarter_totals(usd)
    assert totals["2025Q1"] == 112 + 113 + 114
    assert s.yoy_by_quarter(totals)["2025Q1"] == pytest.approx(r3["202503"])   # quarter-end 3M YoY = quarter YoY
    assert "2026Q1" not in s.quarter_totals({**usd, "202601": 1.0})


def test_quarter_to_date():
    usd = {s.ym_shift("202401", i): 100.0 + i for i in range(23)}   # ends 202511
    assert s.quarter_to_date(usd) == {"q": "2025Q4", "months": 2,
                                      "yoy": pytest.approx(((121 + 122) / (109 + 110) - 1) * 100)}
    assert s.quarter_to_date({**usd, "202512": 1.0}) is None         # quarter complete


def test_select_and_krw():
    months = {"202601": {"848620": 10.0, "848690": 5.0}, "202602": {"848690": 7.0}}
    assert s.select(months) == {"202601": 15.0, "202602": 7.0}
    assert s.select(months, ["848620"]) == {"202601": 10.0, "202602": 0}
    assert s.select(months, ["8486"]) == {"202601": 15.0, "202602": 7.0}          # prefixes, not exact codes
    assert s.select(months, ["848620", "848690"]) == s.select(months)
    assert s.to_krw({"202601": 2.0, "202602": 3.0}, {"202601": 1400.0}) == {"202601": 2800.0}


def test_company_quarters_values_and_same_report_bases():
    reports = {(2025, 1): rep("CFS", (100, 100, 80, 80), (10, 10, 8, 8)),
               (2025, 2): rep("CFS", (120, 220, 90, 170), (12, 22, 9, 17)),
               (2025, 3): rep("CFS", (130, 350, 100, 270), (13, 35, 10, 27)),
               (2025, 4): rep("CFS", (500, None, 400, None), (50, None, 40, None))}
    q = s.company_quarters(reports)
    assert [q[f"2025Q{i}"].revenue for i in (1, 2, 3, 4)] == [100, 120, 130, 150]
    assert [q[f"2025Q{i}"].revenue_base for i in (1, 2, 3, 4)] == [80, 90, 100, 130]
    assert q["2025Q4"].operating == 15 and q["2025Q4"].operating_base == 13
    assert s.company_yoy(q)["2025Q4"] == pytest.approx((150 / 130 - 1) * 100)


def test_company_quarters_fall_back_to_year_to_date_differences():
    reports = {(2025, 1): rep("CFS", (None, 100, None, 90)), (2025, 2): rep("CFS", (None, 220, None, 190)),
               (2025, 3): rep("CFS", (None, 350, None, 300)), (2025, 4): rep("CFS", (500, None, 420, None))}
    q = s.company_quarters(reports)
    assert [q[f"2025Q{i}"].revenue for i in (1, 2, 3, 4)] == [100, 120, 130, 150]
    assert [q[f"2025Q{i}"].revenue_base for i in (1, 2, 3, 4)] == [90, 100, 110, 120]


def test_q2_ytd_fallback_uses_q1_three_months_but_q3_never_uses_q2_three_months():
    q = s.company_quarters({(2025, 1): rep("CFS", (100, None)), (2025, 2): rep("CFS", (None, 220))})
    assert q["2025Q2"].revenue == 120                         # Q1's 3 months are its year to date
    q = s.company_quarters({(2025, 1): rep("CFS", (100, None)), (2025, 2): rep("CFS", (120, None)),
                            (2025, 3): rep("CFS", (None, 350))})
    assert "2025Q3" not in q                                  # Q2's 120 is three months, not its year to date


def test_company_quarters_never_subtract_across_bases():
    reports = {(2025, 1): rep("OFS", (100, 100)), (2025, 2): rep("CFS", (None, 220)),
               (2025, 3): rep("CFS", (130, None)), (2025, 4): rep("OFS", (500, None))}
    q = s.company_quarters(reports)
    assert "2025Q2" not in q                                 # 220 (연결) − 100 (별도) is not a quarter
    assert q["2025Q3"].revenue == 130
    assert "2025Q4" not in q                                 # annual 별도 vs Q3 연결


def test_q4_uses_sum_of_quarters_when_q3_cumulative_missing():
    reports = {(2025, 1): rep("CFS", (100, 100)), (2025, 2): rep("CFS", (120, 220)),
               (2025, 3): rep("CFS", (130, None)), (2025, 4): rep("CFS", (500, None))}
    assert s.company_quarters(reports)["2025Q4"].revenue == 150


def test_spin_off_restated_base_and_break_window():
    # 피에스케이홀딩스 2019Q1: the report restates 2018Q1 to continuing operations (77.5억, filed 848.6억).
    reports = {(2018, 1): rep("CFS", (848.6, 848.6, 700, 700)), (2019, 1): rep("CFS", (29.4, 29.4, 77.5, 77.5))}
    q = s.company_quarters(reports)
    assert s.company_yoy(q)["2019Q1"] == pytest.approx((29.4 / 77.5 - 1) * 100)
    assert s.restated(q) == {"2019Q1"}
    assert s.company_yoy(q, breaks=[("2019Q1", "2020Q4")])["2019Q1"] is None


def test_basket_matched_sample_breaks_top_and_median():
    companies = {
        "A": {"2025Q1": s.Quarter(120, 12, "CFS", 100, 10)},
        "B": {"2025Q1": s.Quarter(50, -5, "CFS", None, None)},          # newly listed: no comparative
        "C": {"2025Q1": s.Quarter(30, 3, "CFS", 60, 6)},               # inside a break window
    }
    b = s.basket(companies, {"C": [("2025Q1", "2025Q4")]})["2025Q1"]
    assert b.revenue == 200 and b.reported == 3
    assert b.revenue_yoy == pytest.approx(20) and b.matched == 1 and b.coverage == pytest.approx(60)
    assert b.operating == 10 and b.margin == pytest.approx(5)
    assert b.operating_yoy == pytest.approx(20)
    assert b.top == ("A", pytest.approx(60)) and b.median_yoy == pytest.approx(20)


def test_basket_says_nothing_when_compared_companies_are_a_small_part():
    # the largest company merged (break) — three small ones cannot stand for the basket
    companies = {"big": {"2026Q1": s.Quarter(900, 90, "CFS", 400, 40)},
                 "small": {"2026Q1": s.Quarter(100, 10, "CFS", 110, 11)}}
    b = s.basket(companies, {"big": [("2026Q1", "2026Q4")]})["2026Q1"]
    assert b.matched == 1 and b.coverage == pytest.approx(10)
    assert b.revenue_yoy is None and b.operating_yoy is None and b.revenue == 1000


def test_pro_forma_adds_the_absorbed_company_to_the_base():
    acquirer = {"2025Q1": s.Quarter(90, 9, "CFS", 80, 8), "2026Q1": s.Quarter(230, 23, "CFS", 91, 9)}
    target = {"2025Q1": s.Quarter(102, 10, "CFS", 95, 9)}
    out, adjusted = s.pro_forma({"A": acquirer, "T": target}, {"A": [("T", "2026Q1")]})
    q = out["A"]["2026Q1"]
    assert q.revenue_base == 91 + 102 and q.operating_base == 9 + 10
    assert out["A"]["2025Q1"] == acquirer["2025Q1"] and adjusted == {("A", "2026Q1")}
    assert s.company_yoy(out["A"])["2026Q1"] == pytest.approx((230 / 193 - 1) * 100)
    out, _ = s.pro_forma({"A": acquirer, "T": {}}, {"A": [("T", "2026Q1")]})
    assert out["A"]["2026Q1"].revenue_base is None                         # no year-earlier figure → unknown


def test_reporting_status_ignores_stale_companies_and_counts_early_filers():
    q = lambda: s.Quarter(1, 1, "CFS")
    companies = {"A": {"2026Q2": q(), "2026Q3": q()}, "B": {"2026Q2": q()}, "C": {"2026Q2": q()},
                 "D": {"2024Q1": q()}, "E": {}}
    assert s.reporting_status(companies) == ("2026Q2", 3, {"2026Q3": 1})
    assert s.reporting_status({}) == (None, 0, {})


def test_lag_pairs_and_correlation_on_log_changes():
    x = {s.quarter_shift("2016Q1", i): float(v) for i, v in
         enumerate([5, -30, 80, 10, -12, 40, 90, -20, 25, 7, -40, 60, 15, -8])}
    r = {s.quarter_shift(q, 1): v for q, v in x.items()}          # revenue follows exports one quarter later
    stats = {d["lag"]: d for d in s.lag_stats(x, r)}
    assert stats[1]["r"] == pytest.approx(1.0) and stats[1]["n"] == 14
    assert stats[1]["span"] == ("2016Q1", "2019Q2")
    assert stats[0]["n"] == 13 and stats[0]["r"] is not None and stats[0]["r"] < 0.5
    lo, hi = stats[0]["lo"], stats[0]["hi"]
    assert lo < stats[0]["r"] < hi and stats[0]["n_eff"] <= 13
    few = s.lag_stats(dict(list(x.items())[:8]), r)
    assert all(d["r"] is None for d in few)                       # fewer than 12 pairs


def test_agreement_rate_drops_flat_pairs_and_reports_chance():
    pairs = [("q", 10, 20), ("q", 20, 10), ("q", -10, -20), ("q", 30, -15), ("q", 2, 40), ("q", 15, 3)]
    d = s.correlation(pairs)
    assert d["flat"] == 2 and d["hit"] == pytest.approx(75)
    assert d["chance"] == pytest.approx((0.75 * 0.5 + 0.25 * 0.5) * 100)


def test_autocorrelation_shrinks_effective_sample():
    trend = [math.sin(i / 3) * 40 for i in range(30)]
    x = {s.quarter_shift("2016Q1", i): v for i, v in enumerate(trend)}
    r = {q: v * 0.8 + (5 if i % 2 else -5) for i, (q, v) in enumerate(x.items())}
    d = s.lag_stats(x, r, lags=(0,))[0]
    assert d["n"] == 30 and d["n_eff"] < 15


def test_analogs_pick_quarters_in_the_same_band():
    x = {"2017Q1": 80.0, "2017Q2": 20.0, "2018Q3": 95.0, "2019Q1": -10.0, "2026Q3": 44.0}
    r = {"2017Q1": 25.0, "2017Q2": 5.0, "2018Q3": -1.0, "2019Q1": -30.0}
    a = s.analogs(x, r, 44.0)
    assert a["band"] == "30% 이상" and [row["q"] for row in a["quarters"]] == ["2017Q1", "2018Q3"]
    assert a["median"] == 12.0 and a["positive"] == 1
    assert s.analogs(x, r, None) is None


def test_no_r_without_an_interval_when_effective_sample_is_tiny():
    xs = [10, 25, 45, 60, 55, 35, 10, -10, -25, -30, -20, 0, 20]
    rs = [5, 15, 40, 70, 65, 30, 5, -15, -30, -35, -15, 5, 30]
    x = {s.quarter_shift("2020Q1", i): float(v) for i, v in enumerate(xs)}
    r = {s.quarter_shift("2020Q1", i): float(v) for i, v in enumerate(rs)}
    d = s.lag_stats(x, r, lags=(0,))[0]
    assert d["n"] == 13 and d["n_eff"] <= 3
    assert d["r"] is None and d["lo"] is None and d["hi"] is None


def test_negative_derived_revenue_is_treated_as_missing():
    # HD현대미포 2017: the annual report already excludes a reclassified business, the Q3 year to date
    # still includes it, so annual − Q3 YTD comes out negative.
    reports = {(2017, 3): rep("CFS", (6000, 25500, 5000, 20000)), (2017, 4): rep("CFS", (24582, None, 21000, None))}
    q = s.company_quarters(reports)
    assert q["2017Q3"].revenue == 6000
    assert "2017Q4" not in q or q["2017Q4"].revenue is None

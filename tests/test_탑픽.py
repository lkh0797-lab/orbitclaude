# -*- coding: utf-8 -*-
"""탑픽.py 순수 함수 — 시점 규칙(접수일 ≤ s−1) · 신호 A/B/C1/C2/유동성 · 순위 · 민감도 변형 · 거래대금 분할 배수. 캐시 · 서버 없이 가짜 자료로."""
import os, sys, importlib.util as ilu

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("탑픽_시험", os.path.join(BASE, "탑픽.py"))
T = ilu.module_from_spec(_sp); _sp.loader.exec_module(T)


def pt(year, q, rev, op, rev_p=None, op_p=None, known=None, sh=1000.0, eps=None, eps_adj=None, ttm=None, quality=()):
    n = year * 4 + q - 1
    return {"year": year, "q": q, "label": "%dQ%d" % (year, q), "n": n, "fs": "CFS", "매출액": rev, "매출액_전": rev_p, "영업이익": op, "영업이익_전": op_p,
            "지배순이익": (op * 0.8) if op is not None else None, "매출_TTM": (ttm / 0.1) if ttm else None,
            "영업이익_TTM": ttm, "주식수": sh, "EPS": eps, "EPS_adj": eps_adj if eps_adj is not None else eps, "EPS_TTM": 100.0,
            "기준일": known, "품질": list(quality)}


def druck(points):
    return {"v": 4, "points": points}


def filed_of(points, day="15"):
    """원본 접수일 = 분기 말 다음 달 중순(사업보고서는 3월 말)."""
    out = {}
    for p in points:
        y, q = p["year"], p["q"]
        out[p["n"]] = ("%d0%s%s" % (y, {1: "5", 2: "8"}.get(q, "x"), day)) if q in (1, 2) else ("%d11%s" % (y, day) if q == 3 else "%d0331" % (y + 1))
    return out


def grow_series(n_q=20, base=100.0, g=0.05, start=(2020, 1), op_ratio=0.1):
    """n_q 분기 — 매출 · 영업이익이 분기마다 g 씩 복리로 느는 회사(TTM 도 채운다)."""
    pts = []
    y, q = start
    vals = []
    for i in range(n_q):
        rev = base * (1 + g) ** i
        op = rev * op_ratio
        vals.append((rev, op))
        prev = vals[i - 4] if i >= 4 else (None, None)
        ttm = sum(v[1] for v in vals[-4:]) if i >= 3 else None
        pts.append(pt(y, q, rev, op, prev[0], prev[1], ttm=ttm, eps=10.0))
        q += 1
        if q == 5:
            y, q = y + 1, 1
    return pts


def test_series_known_strict_uses_amendment_date_and_loose_uses_filing_date():
    pts = grow_series(6)
    filed = filed_of(pts)
    s = T.series_of(druck(pts), filed)
    assert [x["known"] for x in s][:4] == [filed[pts[0]["n"]], filed[pts[1]["n"]], filed[pts[2]["n"]], filed[pts[3]["n"]]]   # 기준일 없으면 원본 접수일
    assert [x["filed0"] for x in s][:2] == [filed[pts[0]["n"]], filed[pts[1]["n"]]]
    pts[1]["기준일"] = "20210601"                                     # 2020Q2 가 이듬해 6월에 정정됐다
    s2 = T.series_of(druck(pts), filed)
    assert s2[1]["known"] == "20210601" and s2[1]["filed0"] == filed[pts[1]["n"]] and s2[1]["late"]
    assert s2[2]["known_ttm"] is None                                 # 2020Q3 의 창(2019Q4~)은 자료 밖
    assert s2[3]["known_ttm"] == s2[4]["known_ttm"] == "20210601"    # 2020Q4 · 2021Q1 의 4분기 합(2020Q2 포함)은 정정 뒤에야 안다
    assert s2[5]["known_ttm"] == filed[pts[5]["n"]]                    # 2021Q2 의 창(2020Q3~)은 정정 분기 밖
    assert T.series_of(druck(pts), filed, strict=False)[1]["known"] == filed[pts[1]["n"]]
    pts[0]["기준일"] = "20200520"
    s3 = T.series_of(druck(pts), {})
    assert s3[0]["known"] == "20200520" and s3[0]["filed0"] == "20200520" and s3[2]["known"] is None


def test_ttm_unknown_until_amended_quarter_is_known():
    pts = grow_series(20, g=0.08)
    pts[-3]["기준일"] = "20250601"                                    # 2024Q2 가 2025-06 에 정정 — 2024Q3 의 4분기 합은 그때까지 모른다
    s = T.series_of(druck(pts), filed_of(pts))
    m = T.metrics(s, "20241231", lambda d: 100.0, tv=5e9)
    assert m["label"] == "2024Q3" and m["ttm"] is None and "ttm_unknown" in m["flags"] and not T.judge(m)["B"]
    m2 = T.metrics(s, "20250602", lambda d: 100.0, tv=5e9)
    assert m2["label"] == "2024Q4" and m2["ttm"] is not None


def test_known_until_is_strict_on_receipt_date():
    pts = grow_series(8)
    s = T.series_of(druck(pts), filed_of(pts))
    assert [x["label"] for x in T.known_until(s, "20200815")] == ["2020Q1", "2020Q2"]       # 반기보고서 접수일 당일 = 알게 됨
    assert [x["label"] for x in T.known_until(s, "20200814")] == ["2020Q1"]               # 하루 전엔 모른다
    assert T.year_ago("20241231") == "20231231" and T.year_ago("20240229") == "20230228"   # 365일 빼기는 윤년에 하루 어긋난다


def test_sh4_median_smooths_noisy_share_count():
    pts = grow_series(6)
    for p, sh in zip(pts, (1000, 1000, 5000, 1000, 1000, None)):
        p["주식수"] = sh
    s = T.series_of(druck(pts), filed_of(pts))
    assert s[2]["sh4"] == 1000 and s[3]["sh4"] == 1000 and s[5]["sh4"] == 1000        # 한 분기 튐 · 빈 분기 이어 씀


def test_k_at_split_factor_by_quarter():
    pts = grow_series(8)
    for p in pts[:4]:
        p["EPS"], p["EPS_adj"] = 500.0, 10.0          # 2020 — 50:1 분할 전 기준
    s = T.series_of(druck(pts), filed_of(pts))
    assert T.k_at(s, "20200615") == 50.0 and T.k_at(s, "20210201") == 1.0 and T.k_at(s, "20190101") == 50.0 and T.k_at([], "20200101") == 1.0


def _world(pts, px=None, tv=5e9):
    s = T.series_of(druck(pts), filed_of(pts))
    px = px or (lambda d: 100.0)
    return s, px, tv


def test_candidate_all_four_pass_and_judge_flags():
    pts = grow_series(20, g=0.08)                     # 분기 8% 성장 → 전년 대비 +36%, TTM 신고점
    s, px, tv = _world(pts)
    d = "20241231"                                    # 2024Q3(접수 11월) 까지 알게 됨, 2024Q4(이듬해 3월)는 아직
    m = T.metrics(s, d, px, tv=tv)
    assert m["label"] == "2024Q3" and m["known"] == "20241115"
    assert abs(m["op_yoy"] - 36.05) < 0.1 and abs(m["rev_yoy"] - 36.05) < 0.1 and not m["turn"]
    assert m["ttm"] > m["ttm_max"] and m["n_hist"] >= 12
    assert m["mcap_g"] == 0 and m["gap"] > 30                                           # 주가 그대로 · 이익 36% ↑
    assert m["por_pct"][20] == 0 and m["por_n"][20] == 15                               # 이익이 늘기만 했으니 지금 POR 이 가장 싸다 · 과거 TTM 15개(2020Q4~2024Q2)
    assert m["elig"] and m["why_not"] == [] and m["flags"] == []
    j = T.judge(m)
    assert j == {"A1": True, "A2": False, "A": True, "B": True, "C1": True, "C2": True, "L": True, "elig": True, "cand": True,
                 "why": ["실적 개선", "실적 신고점"], "pct": 0.0, "pct_n": 15}


def test_price_run_up_kills_c1_and_c2():
    pts = grow_series(20, g=0.08)
    px = lambda d: 300.0 if d >= "20240101" else 100.0          # 1년 사이 주가 3배
    s, _, tv = _world(pts)
    m = T.metrics(s, "20241231", px, tv=tv)
    assert m["mcap_g"] == 200 and m["gap"] < 30
    j = T.judge(m)
    assert j["A"] and j["B"] and not j["C1"] and not j["C2"] and not j["cand"]


def test_turnaround_counts_as_A_and_ttm_turn_uses_cap():
    pts = grow_series(20, g=0.0)
    for p in pts:
        p["영업이익"], p["영업이익_전"], p["영업이익_TTM"] = -10.0, -10.0, -40.0
    last = pts[-1]
    last["영업이익"], last["영업이익_전"], last["영업이익_TTM"] = 5.0, -10.0, 1.0     # 마지막 분기 흑자 전환, TTM 도 겨우 양수
    s, px, tv = _world(pts)
    m = T.metrics(s, "20250131", px, tv=tv)
    assert m["label"] == "2024Q4" or m["label"] == "2024Q3"
    m = T.metrics(s, "20250401", px, tv=tv)                     # 2024Q4 사업보고서(3/31) 뒤
    assert m["label"] == "2024Q4" and m["turn"] and m["op_yoy"] is None
    assert m["ttm_turn"] and m["ttm_g"] == T.TH["cap"] and "ttm_turn" in m["flags"]
    j = T.judge(m)
    assert j["A"] and j["why"] == ["흑자 전환", "실적 신고점"]
    assert not j["C2"]                                           # 과거 TTM 이 다 음수라 POR 이력이 없다


def test_yoy_falls_back_to_series_when_comparative_missing():
    pts = grow_series(8, g=0.1)
    pts[-1]["영업이익_전"] = None
    pts[-1]["매출액_전"] = None
    s, px, tv = _world(pts)
    m = T.metrics(s, "20220401", px, tv=tv)                    # 2021Q4 사업보고서(3/31) 뒤
    assert m["label"] == "2021Q4" and "yoy_series" in m["flags"] and abs(m["op_yoy"] - 46.41) < 0.1


def test_liquidity_and_history_minimum_gates():
    pts = grow_series(20, g=0.08)
    s, px, _ = _world(pts)
    m = T.metrics(s, "20241231", px, tv=5e8)
    assert not T.judge(m)["L"] and T.judge(m, dict(T.TH, tv=4e8))["L"]
    short = grow_series(10, g=0.08)                              # 과거 TTM 6개 — 12 미만
    s2 = T.series_of(druck(short), filed_of(short))
    m2 = T.metrics(s2, "20221231", px, tv=5e9)
    j2 = T.judge(m2)
    assert m2["n_hist"] < 12 and not j2["B"] and not j2["C2"]


def test_rank_percentile_average_and_turnaround_at_cap():
    rows = [{"m": {"turn": False, "tiny": False, "thin": False, "op_yoy": 25.0, "gap_rank": 40.0}, "j": {"pct": 25.0}},
            {"m": {"turn": True, "tiny": False, "thin": False, "op_yoy": None, "gap_rank": 60.0}, "j": {"pct": 5.0}},
            {"m": {"turn": False, "tiny": False, "thin": False, "op_yoy": 900.0, "gap_rank": 35.0}, "j": {"pct": 15.0}}]
    T.rank(rows)
    assert rows[1]["rank"] == 1 and rows[1]["score"] == 91.7                       # 흑자 전환 = 상한(900% 와 동점 → 75) · 괴리 최대 100 · 자리 최저 100
    assert rows[2]["parts"]["op_yoy"] == rows[1]["parts"]["op_yoy"] == 75.0         # 900% 도 상한 200 과 같은 순위(동점 평균)
    assert rows[0]["rank"] == 3 and rows[0]["parts"]["op_yoy"] == 0.0


def test_pct_rank_ties_and_none():
    assert T.pct_rank([1, 2, 2, None]) == [0.0, 75.0, 75.0, None]
    assert T.pct_rank([5]) == [50.0]


def test_sens_variants_touch_each_threshold_once():
    v = T.sens_variants()
    assert v[0][0] == "기본" and len(v) == 1 + 2 * 8 + 3
    assert [x[1]["por_win"] for x in v if x[0].startswith("POR 창")] == [10, 30]
    assert [x[1]["hist_min"] for x in v if x[0].startswith("과거 이력")] == [6, 18]
    for name, th, opts in v[1:1 + 16]:
        assert sum(1 for k in T.TH if th[k] != T.TH[k]) == 1 and opts == {}
    assert [x[2] for x in v[-3:]] == [{"cap_c1": True}, {"no_tiny": True}, {"no_elig": True}]       # 규칙 변형은 문턱을 건드리지 않는다
    assert all(x[1] == T.TH for x in v[-3:])


def _ohlcv(days, vol_fn):
    return {d: [1, 1, 1, 100.0, vol_fn(d)] for d in days}


def test_split_days_needs_disclosure_and_volume_jump():
    pts = grow_series(12, start=(2019, 1))
    for p in pts[:6]:
        p["EPS"], p["EPS_adj"] = 50.0, 10.0                  # 2019Q1~2020Q2 분할 전 기준(5:1)
    s = T.series_of(druck(pts), filed_of(pts))
    import datetime as dt
    days = [(dt.date(2020, 1, 1) + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range(0, 400) if (dt.date(2020, 1, 1) + dt.timedelta(days=i)).weekday() < 5]
    rows = _ohlcv(days, lambda d: 1000.0 if d < "20200810" else 5000.0)            # 8/10 부터 거래량 5배
    ev = T.split_days(s, rows, ["20200701"])                                        # 7/1 주식분할결정 공시
    assert len(ev) == 1 and ev[0]["day"] == "20200810" and abs(ev[0]["r"] - 5.0) < 1e-9 and not ev[0]["est"] and ev[0]["ev"] == "20200701"
    assert T.split_days(s, rows, []) == []                                           # 공시 없으면 잡음으로 버린다
    assert T.split_days(s, rows, None)[0]["day"] == "20200810"                       # 공시 목록이 아예 없으면 거래량만으로
    flat = _ohlcv(days, lambda d: 1000.0)
    ev2 = T.split_days(s, flat, ["20200701"])                                        # 공시는 있는데 거래량이 안 뛰었다 — 공시일 + 30일 추정
    assert len(ev2) == 1 and ev2[0]["est"] and ev2[0]["day"] == "20200731"
    blip = grow_series(12, start=(2019, 1))
    blip[5]["EPS"], blip[5]["EPS_adj"] = 50.0, 10.0                                   # 한 분기만 튄 배수
    assert T.split_days(T.series_of(druck(blip), filed_of(blip)), rows, None) == []


def test_holding_and_mid_rank_percentile():
    pts = grow_series(6)
    assert not T.is_holding(T.series_of(druck(pts), filed_of(pts)))
    pts[-1]["영업이익"] = pts[-1]["매출액"] * 2                                     # 영업이익 > 매출 — 지분법 이익이 든 순수 지주
    assert T.is_holding(T.series_of(druck(pts), filed_of(pts)))
    assert T._pct([1, 2, 3, 4], 2) == 37.5 and T._pct([1, 2, 3, 4], 0.5) == 0.0 and T._pct([], 1) is None


def test_tiny_base_and_thin_profit_rules_and_opts():
    pts = grow_series(20, g=0.08)
    s, px, tv = _world(pts)
    s[-2]["op_p"] = s[-2]["rev_p"] * 0.001                                             # 2024Q3 전년 영업이익이 매출의 0.1% — 기저 미미
    m = T.metrics(s, "20241231", px, tv=tv)
    assert m["tiny"] and "tiny_base" in m["flags"] and m["op_yoy"] > 1000
    j = T.judge(m)
    assert not j["A1"] and j["B"] and j["cand"]                                        # A1 은 안 보지만 B 로 후보
    assert T.judge(m, opts={"no_tiny": True})["A1"]
    assert T.rank_value_op(m) is None                                                  # 순위 성분에서 빠진다
    s[-2]["op_p"], s[-2]["op"] = -5.0, s[-2]["rev"] * 0.005                            # 흑자 전환인데 매출의 0.5% — 미미
    m2 = T.metrics(s, "20241231", px, tv=tv)
    assert m2["turn"] and m2["thin"] and not T.judge(m2)["A2"] and T.judge(m2, opts={"no_tiny": True})["A2"]


def test_eligibility_reasons_and_no_elig_option():
    pts = grow_series(20, g=0.08)
    s, px, tv = _world(pts)
    m = T.metrics(s, "20251231", px, tv=tv)                                           # 마지막 보고서(2024Q4, 2025-03-31) 뒤 275일 — 묵은 재무
    assert "stale" in m["flags"] and "묵은 재무" in m["why_not"] and not m["elig"]
    assert not T.judge(m)["cand"] and T.judge(m, opts={"no_elig": True})["elig"]
    m3 = T.metrics(s, "20241231", px, tv=tv, fin=True)
    assert "금융" in m3["why_not"] and not m3["elig"]
    m4 = T.metrics(s, "20241231", px, tv=None)
    assert "거래 자료 없음" in m4["why_not"]


def test_flow_groups_counts_candidates_and_already_ran():
    rows = [{"code": "1", "sector": "조선", "industry": "조선", "themes": ["LNG", "방산"], "elig": True, "cand": True, "earn": True, "mcap_g": 10.0},
            {"code": "2", "sector": "조선", "industry": "조선", "themes": ["LNG"], "elig": True, "cand": False, "earn": True, "mcap_g": 80.0},     # 실적↑인데 이미 오름
            {"code": "3", "sector": "조선", "industry": "조선기자재", "themes": [], "elig": True, "cand": False, "earn": False, "mcap_g": 50.0},  # 실적 조건 아님
            {"code": "4", "sector": "반도체", "industry": "반도체", "themes": ["HBM"], "elig": False, "cand": True, "earn": True, "mcap_g": 5.0},     # 비적격은 안 센다
            {"code": "5", "sector": None, "industry": None, "themes": ["방산"], "elig": True, "cand": True, "earn": True, "mcap_g": None}]
    g = T.flow_groups(rows)
    s = {x["name"]: x for x in g["sector"]}
    assert list(s) == ["조선"] and s["조선"]["n_elig"] == 3 and s["조선"]["n_cand"] == 1 and s["조선"]["n_ran"] == 1
    assert s["조선"]["cand_codes"] == ["1"] and s["조선"]["ran_codes"] == ["2"] and s["조선"]["mcap_g_med"] == 50.0
    t = {x["name"]: x for x in g["themes"]}
    assert t["방산"]["n_cand"] == 2 and t["LNG"]["n_cand"] == 1 and t["LNG"]["n_ran"] == 1
    assert [x["name"] for x in g["themes"]] == ["방산", "LNG"]                               # 후보 많은 순
    assert [x["name"] for x in g["industry"]] == ["조선"]                                    # 조선기자재는 후보도 이미 오름도 없어 빠진다
    assert T.flow_groups(rows, min_show=2)["sector"] == []


def test_prices_next_day_and_turnover_split_factor():
    P = T.Prices({"A": {"20240102": 100.0, "20240103": 110.0, "20240105": 120.0}})
    assert P.at("A", "20240104") == (110.0, "20240103") and P.at("A", "20240101") == (None, None)
    assert P.next_day("A", "20240103") == "20240105" and P.next_day("A", "20240105") is None
    assert abs(P.ret("A", "20240102", "20240105") - 20.0) < 1e-9
    assert P.grp_ret("20240102", "20240105") is None                                  # 5곳 미만
    days = ["202401%02d" % d for d in range(2, 32) if d not in (6, 7, 13, 14, 20, 21, 27, 28)]
    ov = {d: [1, 1, 1, 100.0, 1000.0] for d in days}
    TV = T.Turnover({"A": ov}, {"A": [{"r": 10.0, "day": "20240115"}]})               # 1/15 분할 — 그 앞 거래량은 ×10
    v = TV.tv("A", days[-1])
    assert v is not None and 1e5 < v < 1e6                                            # 앞 절반 ×10 — 평균이 10만 ~ 100만 사이
    assert TV.tv("A", "20240110") is None                                              # 20일이 안 된다
    assert T.split_factor([{"r": 10.0, "day": "20240115"}], "20240114") == 10.0 and T.split_factor([{"r": 10.0, "day": "20240115"}], "20240115") == 1.0
    # 시장 달력 — 다른 종목이 거래된 날 봉이 없으면 0 으로 센다(정지), 비영 봉 15개 미만이면 없음
    cal = sorted(set(days) | {"20240208", "20240209"})
    TV2 = T.Turnover({"A": {d: [1, 1, 1, 100.0, 1000.0] for d in days[:12]}, "B": {d: [1, 1, 1, 10.0, 10.0] for d in cal}})
    assert TV2.tv("A", "20240209") is None and TV2.tv("B", "20240209") == 100.0
    assert TV2.last_bar("A", "20240209") == days[11] and TV2.last_date("B") == "20240209"

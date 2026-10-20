# -*- coding: utf-8 -*-
"""우량급락.py 순수 함수 — 변동성 누적합 · 재무 특징 · 관문 · 횡단 순위/자리 · 점수 · 민감도 변형. 캐시 · 서버 없이."""
import os, sys, math, statistics as st, importlib.util as ilu

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _load(name, f):
    sp = ilu.spec_from_file_location(name, os.path.join(BASE, f)); m = ilu.module_from_spec(sp); sp.loader.exec_module(m); return m


Q = _load("우량급락_시험", "우량급락.py")
T = _load("탑픽_우량급락_시험", "탑픽.py")


def test_vol_matches_direct_std():
    import datetime as dt
    days = [(dt.date(2024, 1, 1) + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range(400)]
    px = {d: 100.0 * (1.01 if i % 2 else 0.99) ** (i % 7) for i, d in enumerate(days)}
    V = Q.Vol({"A": px})
    ks = sorted(px)
    rs = [math.log(px[ks[i]] / px[ks[i - 1]]) for i in range(len(ks) - 250, len(ks))]
    want = st.pstdev(rs) * math.sqrt(250) * 100
    assert abs(V.vol("A", ks[-1]) - want) < 1e-6
    assert V.vol("A", ks[100]) is None and V.vol("B", ks[-1]) is None


def _K(n_q=16, op=10.0, rev=100.0, g=0.02, ni=8.0, eq=200.0, eps=10.0, loss_at=()):
    out = []
    for i in range(n_q):
        o = -1.0 if i in loss_at else op * (1 + g) ** i
        r = rev * (1 + g) ** i
        out.append({"n": 8000 + i, "label": "Q%d" % i, "known": "2024%04d" % (100 + i), "filed0": "2024%04d" % (100 + i), "op": o, "rev": r, "ni": ni, "eq": eq,
                    "eps_ttm": eps, "ttm_ok": True})
    for i, s in enumerate(out):
        w = out[max(0, i - 3):i + 1]
        s["ttm"] = sum(x["op"] for x in w) if len(w) == 4 else None
        s["rev_ttm"] = sum(x["rev"] for x in w) if len(w) == 4 else None
    return out


def test_fund_features():
    K = _K(loss_at=(14,))
    f = Q.fund(K, lambda d: 100.0)
    assert f["loss_q12"] == 1 and f["nq12"] == 12
    assert abs(f["roe"] - 8.0 * 4 / 200.0 * 100) < 1e-9                        # 4분기 지배순이익 ÷ 자본총계
    assert f["rev_cagr3"] is not None and abs(f["rev_cagr3"] - ((1.02 ** 12) ** (1 / 3) - 1) * 100) < 1e-6
    assert len(f["per_hist"]) == 15 and f["per_hist"][0] == 10.0                # 접수일 종가 100 ÷ EPS 10
    assert Q.per_pct([10.0] * 15, 5.0) == 0.0 and Q.per_pct([10.0] * 15, 10.0) == 50.0 and Q.per_pct([1.0] * 5, 1.0) is None


def test_gates_and_fin_margin():
    r = {"cap_rank": 120, "loss_q12": 0, "nq12": 12, "roe": 15.0, "opm": 20.0, "rev_cagr3": 6.0, "ttm_cagr3": 1.0, "r3m": -12.0,
         "per_pct": 50.0, "por_pct": 20.0, "vol_pct": 40.0, "ksic": "28"}
    g = Q.gates(r)
    assert all(g.values())
    assert not Q.gates(dict(r, opm=None))["opm"] and Q.gates(dict(r, opm=None, ksic="66121"))["opm"]       # 매출 없는 금융은 마진 통과
    assert not Q.gates(dict(r, r3m=-9.9))["drop"] and not Q.gates(dict(r, per_pct=31, por_pct=31))["cheap"]
    assert not Q.gates(dict(r, nq12=6))["steady"] and not Q.gates(dict(r, vol_pct=51))["calm"]
    assert Q.gates(dict(r, rev_cagr3=None, ttm_cagr3=5.0))["growth"]


def test_cross_section_rank_volpct_and_score():
    rows = [{"code": str(i), "mcap": float(1000 - i), "vol": float(i), "loss_q12": 0, "nq12": 12, "roe": 12.0, "opm": 12.0, "rev_cagr3": 6.0,
             "r3m": -20.0, "per_pct": 10.0, "por_pct": 10.0, "lmcap": math.log10(1000 - i), "ttm_min_max": 0.8, "op_cv12": 0.2, "ttm_cagr3": 6.0}
            for i in range(10)]
    Q.cross_section(rows, dict(Q.TH, cap_rank=5))
    assert [r["cap_rank"] for r in rows] == list(range(1, 11))
    assert rows[0]["vol_pct"] == 5.0 and rows[9]["vol_pct"] == 95.0
    assert rows[0]["n_pass"] == 8 and rows[9]["miss"] == ["cap", "calm"]
    Q.score_rows(rows)
    assert rows[0]["score"] > rows[9]["score"]                                   # 크고 덜 출렁이는 쪽이 위


def test_sens_variants_one_change_each():
    v = Q.sens_variants()
    assert v[0][0] == "기본" and len(v) == 1 + 16
    for name, t in v[1:]:
        assert sum(1 for k in Q.TH if t[k] != Q.TH[k]) == 1
    assert [t["cap_rank"] for n, t in v if n.startswith("시총 순위")] == [150, 450]
    assert [t["vol_q"] for n, t in v if n.startswith("변동성")] == [25.0, 75.0]


def test_series_carries_equity():
    d = {"points": [{"n": 8100, "fs": "CFS", "자본총계": 123.0, "기준일": "20250515", "품질": []}]}
    assert T.series_of(d, {})[0]["eq"] == 123.0

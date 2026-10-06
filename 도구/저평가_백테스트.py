# -*- coding: utf-8 -*-
"""
저평가 — 가치(이익)는 지켰거나 늘었는데 주가가 빠져 값이 싸진 회사를 고르는 규칙이 과거에 맞았나 (2026-10-03)

표본: 도구/분기변화_백테스트.py 가 만든 .cache/quarter/bt_panel.json(보고서가 공시된 날마다, 그때까지 나온 숫자로 · 946곳)에
      이 도구가 같은 시점 값을 더 붙인다.
  - 52주 고점 대비 낙폭(dd) · 최근 3개월 수익률(ret3m) — 공시일까지의 수정주가
  - 서버._pipe_rows 로 다시 읽은 ROE · 영업이익률(4분기 합) · 부채비율 · 영업현금 ÷ 순이익 · EPS 1년(분할 보정)
후보 = 4분기 순이익 흑자 · 순이익 1년 −5% 이내 · 52주 고점 대비 −25%↓  ('가치는 지켰는데 주가가 빠졌다')
잰다 — 공시 다음 거래일 종가부터 12개월 수익률 − 같은 기간 전 종목 중앙값(초과수익 — 분기변화 표본의 ex12m, 2026-10-07 진입일 고침). 회사 단위 부트스트랩 90% 구간, 앞(~2019) · 뒤(2020~).
  (1) 묶음: 전체 · 빠진 회사 · 후보 · 이익도 줄어든 하락
  (2) 후보 안 항목별 위⅓ − 아래⅓ — 어떤 값이 '싸진 회사' 가운데 되돌아온 쪽을 갈랐나
  (3) 빨간불 · 주의 묶음
  (4) --score: 고른 항목으로 만든 점수와 등급을 같은 방식으로 잰다(앞 기간 분포로 뒤 기간도) → .cache/value/score.json(서버가 읽는다)
재무는 재무.py 캐시만 읽는다. 한계 — 지금 상장된 회사만(생존 편향), 재무는 나중 정정값일 수 있다, 항목을 고른 표본과 잰 표본이 같다.

실행: python 도구/저평가_백테스트.py           (표본을 붙이고 보고 — 약 15분)
      python 도구/저평가_백테스트.py --report  (붙인 표본으로 다시 보고 — 몇 초)
      python 도구/저평가_백테스트.py --score   (점수 · 등급 검증 + score.json)
"""
import os
import sys
import json
import bisect
import statistics as st
import importlib.util
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
_argv, sys.argv = sys.argv, ["x"]
_spec = importlib.util.spec_from_file_location("wb", os.path.join(HERE, "억울_백테스트.py"))
W = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(W)
sys.argv = _argv
S = W.S
FIN = S.FIN
OUT = os.path.join(S.CACHE_DIR, "value")
YEARS = list(range(2014, 2027))

_orig_fetch = FIN.fetch_statement


def _cached_only(corp_code, year, reprt_code, fs_div="CFS"):
    path = os.path.join(FIN.FIN_DIR, "%s_%s_%s_%s.json" % (corp_code, year, reprt_code, fs_div))
    if not os.path.exists(path):
        return {"status": "013", "list": []}
    return _orig_fetch(corp_code, year, reprt_code, fs_div)


FIN.fetch_statement = _cached_only


def adj_px(code):
    ks, vs = W.PX.get(code, ((), ()))
    if not ks:
        return None
    pr = dict(zip(ks, vs))
    adj = S.SYN._adjusted(pr, list(ks)) if S.SYN is not None else list(vs)
    return {"d": [int(k) for k in ks], "p": adj, "r": list(vs)}


def px_on(px, t, stale=10):
    i = bisect.bisect_right(px["d"], int(t)) - 1
    if i < 0 or int(W.shift(str(px["d"][i]), stale)) < int(t):
        return None, None
    return px["p"][i], i


def dd52(px, t):
    p, i = px_on(px, t)
    if p is None:
        return None
    lo = bisect.bisect_left(px["d"], int(W.shift(t, -365)))
    hi = max(px["p"][lo:i + 1]) if i >= lo else None
    return (p / hi - 1) * 100 if hi else None


def ret_back(px, t, days):
    a, _ = px_on(px, W.shift(t, -days))
    b, _ = px_on(px, t)
    return (b / a - 1) * 100 if a and b else None


def attach_one(c, rows):
    code = c["code"]
    corp = S.corp_code_of(code)
    px = adj_px(code)
    if not corp or not px:
        return rows
    try:
        mi = FIN.statement_matrix(corp, YEARS, "IS", "q")
        mb = FIN.statement_matrix(corp, YEARS, "BS", "q")
        mc = FIN.statement_matrix(corp, YEARS, "CF", "q")
        pr = S._pipe_rows(c, mi, mb, mc, px=px, blog_pts=[])
    except Exception:
        pr = None
    R = (pr or {}).get("rows") or {}
    for r in rows:
        x = R.get(r["lab"]) or {}
        rev, op, ni, cfo = x.get("rev_ttm"), x.get("op_ttm"), x.get("ni_ttm"), x.get("cfo_ttm")
        eqt, debt = x.get("eq_total"), x.get("debt")
        r.update(dd=dd52(px, r["date"]), ret3m=ret_back(px, r["date"], 91), ret1m=ret_back(px, r["date"], 30),
                 roe=x.get("roe"), roe_chg=x.get("roe_chg"), eps_yoy=x.get("eps_yoy"), op_yoy=x.get("op_yoy"),
                 ni4=ni, opm=op / rev * 100 if (rev and op is not None and rev > 0) else None,
                 debt_eq=debt / eqt * 100 if (debt is not None and eqt and eqt > 0) else None,
                 cfo_ni=cfo / ni if (cfo is not None and ni and ni > 0) else None)
    return rows


def build():
    qp = json.load(open(os.path.join(S.CACHE_DIR, "quarter", "bt_panel.json"), encoding="utf-8"))
    by = {}
    for r in qp:
        by.setdefault(r["code"], []).append(r)
    S.build_index() if not S.INDEX.get("companies") else None
    cos = {c["code"]: c for c in S.INDEX["companies"]}
    out, done = [], 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(attach_one, cos[k], v) for k, v in by.items() if k in cos]
        for f in as_completed(futs):
            out += f.result()
            done += 1
            if done % 50 == 0:
                print("  %d/%d 회사" % (done, len(futs)), flush=True)
    os.makedirs(OUT, exist_ok=True)
    json.dump(out, open(os.path.join(OUT, "bt_panel.json"), "w", encoding="utf-8"), ensure_ascii=False)
    return out


# ---------------------------------------------------------------- 통계
def fmt(v):
    return "—" if v is None else "%+.1f" % v


def group(rows, y="ex12m"):
    v = [r[y] for r in rows if r.get(y) is not None]
    if len(v) < 20:
        return None
    e = [r[y] for r in rows if r.get(y) is not None and r["t"] < W.SPLIT]
    l_ = [r[y] for r in rows if r.get(y) is not None and r["t"] >= W.SPLIT]
    return {"n": len(v), "firms": len({r["code"] for r in rows if r.get(y) is not None}), "median": st.median(v),
            "hit": sum(x > 0 for x in v) / len(v) * 100, "crash": sum(x <= -30 for x in v) / len(v) * 100,
            "early": st.median(e) if len(e) >= 10 else None, "late": st.median(l_) if len(l_) >= 10 else None}


def test(rows, fn, y="ex12m"):
    rs = [dict(r, _f=fn(r)) for r in rows if r.get(y) is not None]
    rs = [r for r in rs if r["_f"] is not None]
    on, off = [r for r in rs if r["_f"]], [r for r in rs if not r["_f"]]
    if len(on) < 10 or len(off) < 10:
        return {"n_on": len(on), "n_off": len(off)}

    def diff(sub):
        a, b = [r[y] for r in sub if r["_f"]], [r[y] for r in sub if not r["_f"]]
        return st.median(a) - st.median(b) if len(a) >= 5 and len(b) >= 5 else None
    lo, hi = W.boot(rs, diff, n=600)
    return {"n_on": len(on), "firms_on": len({r["code"] for r in on}), "n_off": len(off),
            "on": st.median([r[y] for r in on]), "off": st.median([r[y] for r in off]),
            "hit_on": sum(r[y] > 0 for r in on) / len(on) * 100, "diff": diff(rs), "ci": [lo, hi],
            "early": diff([r for r in rs if r["t"] < W.SPLIT]), "late": diff([r for r in rs if r["t"] >= W.SPLIT])}


def comp(r):
    """PER 변화 — 1년 주가 ÷ 1년 이익. −50% = 이익은 그대론데 값이 반이 됐다."""
    a, b = r.get("px_yoy"), r.get("ni_yoy")
    return ((1 + a / 100) / (1 + b / 100) - 1) * 100 if a is not None and b is not None and b > -100 else None


def gapk(r, k):
    a, b = r.get(k), r.get("rev_yoy")
    return a - b if a is not None and b is not None else None


def red(r):
    """빨간불 — 억울한 낙폭과 같은 규칙(앞단 약함 · 업종 가격 하락 · 업종 재고 쌓임)."""
    bg, lg = gapk(r, "blog_yoy"), gapk(r, "liab_yoy")
    return ((bg is not None and bg <= -15) or (lg is not None and lg <= -15) or
            (r.get("mp_yoy") is not None and r["mp_yoy"] <= -10) or
            (r.get("cyc") is not None and r.get("rev_yoy") is not None and r["cyc"] <= -10 and r["rev_yoy"] > 5))


FACT = [   # (키, 이름, 값)
    ("per_pct", "PER 자기 역사 백분위", lambda r: r.get("per_pct")),
    ("per", "PER 수준", lambda r: r.get("per")),
    ("peg", "PEG(PER ÷ 순이익 성장)", lambda r: r.get("peg")),
    ("comp", "PER 변화(주가 1년 ÷ 이익 1년)", comp),
    ("dd", "52주 고점 대비 낙폭", lambda r: r.get("dd")),
    ("px_yoy", "주가 1년", lambda r: r.get("px_yoy")),
    ("ret3m", "최근 3개월 주가", lambda r: r.get("ret3m")),
    ("ret1m", "최근 1개월 주가", lambda r: r.get("ret1m")),
    ("ni_yoy", "순이익 1년", lambda r: min(r["ni_yoy"], 300) if r.get("ni_yoy") is not None else None),
    ("eps_yoy", "EPS 1년", lambda r: min(r["eps_yoy"], 300) if r.get("eps_yoy") is not None else None),
    ("rev_yoy", "매출 1년", lambda r: r.get("rev_yoy")),
    ("opm", "영업이익률", lambda r: r.get("opm")),
    ("opm_pct", "이익률 자기 역사 백분위", lambda r: r.get("opm_pct")),
    ("roe", "ROE", lambda r: r.get("roe")),
    ("roe_chg", "ROE 1년 변화", lambda r: r.get("roe_chg")),
    ("debt_eq", "부채비율", lambda r: r.get("debt_eq")),
    ("cfo_ni", "영업현금 ÷ 순이익", lambda r: max(min(r["cfo_ni"], 5), -5) if r.get("cfo_ni") is not None else None),
    ("mp_yoy", "업종 수출물가 1년", lambda r: r.get("mp_yoy")),
    ("cyc", "업종 재고 순환", lambda r: r.get("cyc")),
    ("bgap", "잔고 − 매출", lambda r: gapk(r, "blog_yoy")),
    ("lgap", "선수금 − 매출", lambda r: gapk(r, "liab_yoy")),
    ("wgap", "재고+계약자산 − 매출", lambda r: gapk(r, "wip_yoy")),
    ("capex_yoy", "설비투자 1년", lambda r: min(r["capex_yoy"], 300) if r.get("capex_yoy") is not None else None),
]
FLAGS = [
    ("빨간불(앞단 약함 · 업종 가격 하락 · 업종 재고 쌓임)", red),
    ("영업현금이 마이너스(이익이 현금으로 안 들어옴)", lambda r: None if r.get("cfo_ni") is None else r["cfo_ni"] < 0),
    ("부채비율 200%↑", lambda r: None if r.get("debt_eq") is None else r["debt_eq"] >= 200),
    ("이익률 자기 역사 상위 10%(꼭대기)", lambda r: None if r.get("opm_pct") is None else r["opm_pct"] >= 90),
    ("PER 자기 역사 상위 30%", lambda r: None if r.get("per_pct") is None else r["per_pct"] >= 70),
    ("PER 자기 역사 하위 30%", lambda r: None if r.get("per_pct") is None else r["per_pct"] <= 30),
    ("PEG < 1", lambda r: None if r.get("peg") is None else r["peg"] < 1),
    ("PER이 1년 새 반 넘게 줄었다", lambda r: None if comp(r) is None else comp(r) <= -50),
    ("최근 3개월 −15%↓(아직 떨어지는 중)", lambda r: None if r.get("ret3m") is None else r["ret3m"] <= -15),
    ("최근 3개월 +10%↑(돌아서는 중)", lambda r: None if r.get("ret3m") is None else r["ret3m"] >= 10),
    ("순이익 +30%↑", lambda r: None if r.get("ni_yoy") is None else r["ni_yoy"] >= 30),
    ("ROE 15%↑", lambda r: None if r.get("roe") is None else r["roe"] >= 15),
]


def cand(r):
    """PER 200배 넘으면 이익이 거의 0 — 값의 기준이 못 된다(서버 VAL_PER_MAX 와 같다)."""
    return (r.get("per") is not None and r["per"] <= 200 and r.get("ni_yoy") is not None and r["ni_yoy"] >= -5
            and r.get("dd") is not None and r["dd"] <= -25)


def report(P):
    base = [r for r in P if r.get("ex12m") is not None and r.get("dd") is not None]
    prof = [r for r in base if r.get("per") is not None]
    C = [r for r in base if cand(r)]
    print("\n== 묶음 — 12개월 초과수익(같은 기간 전 종목 중앙값 대비)")
    for nm, rows in (("전체(공시일, 주가 있음)", base), ("흑자(PER 있음)", prof),
                     ("흑자 · 고점 −25%↓", [r for r in prof if r["dd"] <= -25]),
                     ("  그중 순이익 −5% 이내 = 후보", C),
                     ("  그중 순이익도 −5%↓ 줄어듦", [r for r in prof if r["dd"] <= -25 and r.get("ni_yoy") is not None and r["ni_yoy"] < -5]),
                     ("  후보 · 고점 −40%↓", [r for r in C if r["dd"] <= -40]),
                     ("흑자 · 고점 −10% 이내(안 빠짐)", [r for r in prof if r["dd"] > -10])):
        g = group(rows)
        if g:
            print("  %-30s n %5d 곳 %3d  중앙 %s  이긴 %3.0f%%  −30%%↓ %3.0f%%  앞 %s 뒤 %s"
                  % (nm, g["n"], g["firms"], fmt(g["median"]), g["hit"], g["crash"], fmt(g["early"]), fmt(g["late"])))
    out = {"groups": {}, "factors": {}, "flags": {}}
    print("\n== 후보 안 — 항목별 위⅓ − 아래⅓ (n %d · %d곳)" % (len(C), len({r["code"] for r in C})))
    for k, nm, fx in FACT:
        t = W.tercile_test(C, fx, "ex12m")
        out["factors"][k] = t
        if t:
            print("  %-28s 위⅓ %s 아래⅓ %s 차이 %s [%s, %s] 앞 %s 뒤 %s (n %d)" % (
                nm, fmt(t["top"]), fmt(t["bot"]), fmt(t["spread"]), fmt(t["ci"][0]), fmt(t["ci"][1]), fmt(t["early"]), fmt(t["late"]), t["n"]))
    print("\n== 후보 안 — 표시 묶음(넘은 쪽 − 나머지)")
    for nm, fn in FLAGS:
        t = test(C, fn)
        out["flags"][nm] = t
        if "diff" in t:
            print("  %-36s 넘음 %4d(%3d곳) %s vs %s 차이 %s [%s, %s] 앞 %s 뒤 %s" % (
                nm, t["n_on"], t["firms_on"], fmt(t["on"]), fmt(t["off"]), fmt(t["diff"]), fmt(t["ci"][0]), fmt(t["ci"][1]), fmt(t["early"]), fmt(t["late"])))
    json.dump(out, open(os.path.join(OUT, "bt_report.json"), "w", encoding="utf-8"), ensure_ascii=False, default=str)


# ---------------------------------------------------------------- 점수(--score) — report 를 보고 고른 항목 · 가중치(맞추지 않고 단순하게)
SCORE = [   # (키, 이름, 가중치, 방향 +1 높을수록 좋다 / −1 낮을수록 좋다) — 2026-10-03 보고(후보 2,039건 · 510곳)에서 앞뒤 기간 같은 방향
    ("mp_yoy", "업종 제품 가격(수출물가 1년)", 1.0, 1),      # +11.7 [4.8, 17.1] 앞 +6.3 뒤 +12.7
    ("px_yoy", "주가 1년(더 빠졌을수록)", 1.0, -1),          # −9.6 [−13.8, −5.0] 앞 −4.4 뒤 −10.6
    ("debt_eq", "부채비율(낮을수록)", 1.0, -1),              # −6.0 [−10.7, −1.4] 앞 −14.9 뒤 −3.2
    ("rev_yoy", "매출 1년", 0.5, 1),                        # +3.8 [−0.0, 8.7] 앞 +8.2 뒤 +3.1
    ("ret1m", "최근 1개월 주가(돌아서나)", 0.5, 1),          # +3.7 [0.1, 7.6] 앞 +3.1 뒤 +4.2
    ("per_pct", "PER 자기 역사(너무 싸면 감점)", 0.5, 1),    # +5.4 [0.5, 10.4] 앞 +12.0 뒤 +4.2 — 자기 역사로 싼 쪽이 덜 돌아왔다
]


def score(r, dist, spec):
    tot = wsum = 0.0
    for k, _, w, d in spec:
        sv = dist.get(k) or []
        fx = next(f for kk, _, f in FACT if kk == k)
        x = fx(r)
        if x is None or not sv:
            continue
        p = (bisect.bisect_left(sv, x) + bisect.bisect_right(sv, x)) / 2 / len(sv) * 100
        tot += (p if d > 0 else 100 - p) * w
        wsum += w
    return tot / wsum if wsum >= 2 else None


def score_eval(P):
    base = [r for r in P if r.get("ex12m") is not None and r.get("dd") is not None]
    C = [r for r in base if cand(r)]
    wide = [r for r in base if r.get("per") is not None and r["per"] <= 200 and r["dd"] <= -25]
    fx_of = {k: f for k, _, f in FACT}
    dist = {k: sorted(v for v in (fx_of[k](r) for r in C) if v is not None) for k, *_ in SCORE}
    dist_e = {k: sorted(v for v in (fx_of[k](r) for r in C if r["t"] < W.SPLIT) if v is not None) for k, *_ in SCORE}
    for r in base:
        r["_s"] = score(r, dist, SCORE)
        r["_se"] = score(r, dist_e, SCORE)
    rep = {"weights": [{"key": k, "name": n, "w": w, "dir": d} for k, n, w, d in SCORE], "dist": dist, "eval": {},
           "n_cand": len(C), "firms": len({r["code"] for r in C}), "dates": [min(r["t"] for r in C), max(r["t"] for r in C)]}
    prof = [r for r in base if r.get("per") is not None]
    rep["groups"] = {nm: group(rows) for nm, rows in (
        ("전체", base), ("흑자", prof), ("흑자 · 고점 −25%↓", [r for r in prof if r["dd"] <= -25]), ("후보(이익 지킴)", C),
        ("이익도 줄어든 하락", [r for r in prof if r["dd"] <= -25 and r.get("ni_yoy") is not None and r["ni_yoy"] < -5]),
        ("흑자 · 안 빠짐", [r for r in prof if r["dd"] > -10]))}
    for gname, rows in (("후보", C), ("넓은 표본", wide)):
        print("\n== %s n %d · %d곳" % (gname, len(rows), len({r["code"] for r in rows})))
        for nm, fx in (("점수", lambda r: r["_s"]), ("점수(앞 기간 분포)", lambda r: r["_se"])):
            t = W.tercile_test(rows, fx, "ex12m")
            rep["eval"].setdefault(gname, {})[nm] = t
            if t:
                print("  %-18s 위⅓ %s 아래⅓ %s 차이 %s [%s, %s] 앞 %s 뒤 %s 위⅓ 이긴 %.0f%%" % (
                    nm, fmt(t["top"]), fmt(t["bot"]), fmt(t["spread"]), fmt(t["ci"][0]), fmt(t["ci"][1]), fmt(t["early"]), fmt(t["late"]), t["top_hit"]))
        heavy = lambda r: r.get("debt_eq") is not None and r["debt_eq"] >= 200
        for nm, fn in (("빨간불 없음", lambda r: not red(r)),
                       ("빨간불 없음 · 점수 50↑", lambda r: None if r["_s"] is None else (not red(r) and r["_s"] >= 50)),
                       ("빨간불 · 부채 200%↑ 없음 · 점수 50↑", lambda r: None if r["_s"] is None else (not red(r) and not heavy(r) and r["_s"] >= 50)),
                       ("빨간불 없음 · 점수 60↑", lambda r: None if r["_s"] is None else (not red(r) and r["_s"] >= 60)),
                       ("점수 50↑만", lambda r: None if r["_s"] is None else r["_s"] >= 50)):
            t = test(rows, fn)
            rep["eval"].setdefault(gname, {})[nm] = t
            if "diff" in t:
                print("  %-22s 넘음 %4d(%3d곳) %s vs %s 차이 %s [%s, %s] 앞 %s 뒤 %s 이긴 %.0f%%" % (
                    nm, t["n_on"], t["firms_on"], fmt(t["on"]), fmt(t["off"]), fmt(t["diff"]), fmt(t["ci"][0]), fmt(t["ci"][1]),
                    fmt(t["early"]), fmt(t["late"]), t["hit_on"]))
        if gname == "후보":
            on = [r for r in rows if r["_s"] is not None and not red(r) and not heavy(r) and r["_s"] >= 50]
            g = group(on)
            rep["eval"][gname]["추천 묶음"] = g
            if g:
                print("  추천 묶음(빨간불 · 부채 200%%↑ 없음 · 점수 50↑) 12개월 초과 중앙 %s · 이긴 %.0f%% · −30%%↓ %.0f%% · 앞 %s 뒤 %s · 한 번에 평균 %.1f곳" % (
                    fmt(g["median"]), g["hit"], g["crash"], fmt(g["early"]), fmt(g["late"]),
                    len(on) / max(1, len({r["t"][:6] for r in on}))))
    json.dump(rep, open(os.path.join(OUT, "score.json"), "w", encoding="utf-8"), ensure_ascii=False, default=str)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] in ("--report", "--score"):
        P = json.load(open(os.path.join(OUT, "bt_panel.json"), encoding="utf-8"))
        (report if sys.argv[1] == "--report" else score_eval)(P)
    else:
        report(build())

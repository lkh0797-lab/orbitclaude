# -*- coding: utf-8 -*-
"""
억울한 낙폭 새 점수 · 등급 검증 (2026-10-03) — 도구/억울_재점검.py 의 요인 분석으로 고른 항목을 같은 표본에서 예전 점수와 견준다.

새 점수 = 과거 억울한 낙폭 후보 안에서의 백분위 가중평균(0~100) — 가중치는 맞추지 않고 단순하게 정했다(과적합을 덜려고):
  업종 제품 가격(수출물가 전년 대비) +   1     — 요인 분석에서 가장 확실(후보 +28.9 · 넓은 표본 +20.8, 앞뒤 같은 방향)
  북투빌 +                              1     — 넓은 표본 +8.9 [0.7, 19.3]
  고점 대비 낙폭(깊을수록) +            1     — 관문을 넘은 회사는 깊게 빠질수록 더 되돌아왔다(후보 +10.8)
  영업이익률(높을수록) −                1     — 이익률이 높을 때의 낙폭은 꼭대기에 가까웠다(넓은 표본 −10.8)
  잔고 − 매출 간극 +                    0.5   — 방향은 맞지만 혼자서는 약함
  업종 재고 순환 +                      0.5   — 후보 안에서만 뚜렷
예전 점수(북투빌 · 업종 수익률 · 낙폭 · 잔고÷연매출 · 순차입) · 예전 등급 · 새 등급 후보와 나란히 잰다.
과적합 점검 — 요인 고르기와 같은 표본이라 실제보다 좋아 보인다. 그래서 앞 기간(~2019) 분포 · 앞 기간 성적만으로도 재 본다.

실행: python 도구/억울_새점수.py        결과: 표준출력 + .cache/dip/score_v2.json(서버 _dip_score 가 읽는다)
"""
import os
import sys
import json
import bisect
import statistics as st
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("rc", os.path.join(HERE, "억울_재점검.py"))
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)
W, S = R.W, R.S

NEW = [   # (키, 이름, 가중치, 방향)
    ("mp", "업종 제품 가격(수출물가 전년 대비)", 1.0, 1),
    ("btb", "북투빌", 1.0, 1),
    ("dd", "고점 대비 낙폭", 1.0, -1),
    ("margin", "영업이익률", 1.0, -1),
    ("bgap", "잔고 − 매출 간극", 0.5, 1),
    ("cyc", "업종 재고 순환", 0.5, 1),
]


def vals(r):
    return {"mp": r.get("q_mp_yoy"), "btb": r.get("btb"), "dd": r.get("dd"), "margin": r.get("margin"),
            "bgap": R.gap(r, "blog_yoy"), "cyc": r.get("q_cyc")}


def score(r, dist, spec):
    v = vals(r)
    tot = wsum = 0.0
    for k, _, w, d in spec:
        sv = dist.get(k) or []
        x = v.get(k)
        if x is None or not sv:
            continue
        p = (bisect.bisect_left(sv, x) + bisect.bisect_right(sv, x)) / 2 / len(sv) * 100
        tot += (p if d > 0 else 100 - p) * w
        wsum += w
    return tot / wsum if wsum >= 2 else None        # 두 항목(가중치 2)도 못 채우면 점수 없음


def old_score(r, bt):
    sc = bt.get("score") or {}
    v = {"btb": r.get("btb"), "ind": r.get("i_ret") if r.get("i_ret") is not None else r.get("m_ret"), "dd": r.get("dd"),
         "cover": r.get("cover"), "nd_eq": r.get("nd_eq")}
    tot = wsum = 0.0
    for w in sc.get("weights") or []:
        sv, x = sc["dist"].get(w["key"]) or [], v.get(w["key"])
        if x is None or not sv:
            continue
        p = (bisect.bisect_left(sv, x) + bisect.bisect_right(sv, x)) / 2 / len(sv) * 100
        tot += (p if w["dir"] > 0 else 100 - p) * w["w"]
        wsum += w["w"]
    return tot / wsum if wsum else None


def red(r):
    g = R.gap
    return ((g(r, "blog_yoy") or 1e9) <= -15 or (g(r, "liab_yoy") or 1e9) <= -15 or
            (r.get("q_mp_yoy") is not None and r["q_mp_yoy"] <= -10) or
            (r.get("q_cyc") is not None and r.get("q_rev_yoy") is not None and r["q_cyc"] <= -10 and r["q_rev_yoy"] > 5))


def strong(r):
    g = R.gap
    return (g(r, "blog_yoy") or -1e9) >= 15 or (g(r, "liab_yoy") or -1e9) >= 15


def main():
    R.attach()
    for r in R.DIP:
        r["_cand"] = bool(r.get("money") and r.get("core") and r.get("dd") is not None and r["dd"] <= -20
                          and (r.get("e_chg") is None or r["e_chg"] >= -5))
    cand = [r for r in R.DIP if r["_cand"]]
    wide = [r for r in R.DIP if r.get("dd") is not None and r["dd"] <= -20]
    bt = json.load(open(os.path.join(S.CACHE_DIR, "dip", "bt_report.json"), encoding="utf-8"))
    dist = {k: sorted(v for v in (vals(r)[k] for r in cand) if v is not None) for k, *_ in NEW}
    dist_early = {k: sorted(v for v in (vals(r)[k] for r in cand if r["t"] < W.SPLIT) if v is not None) for k, *_ in NEW}
    for r in R.DIP:
        r["_new"] = score(r, dist, NEW)
        r["_new_oos"] = score(r, dist_early, NEW)
        r["_old"] = old_score(r, bt)
    rep = {"weights": [{"key": k, "name": n, "w": w, "dir": d} for k, n, w, d in NEW], "dist": dist, "eval": {}}
    for gname, rows in (("후보", cand), ("넓은 표본", wide)):
        print("\n== %s n %d · 회사 %d" % (gname, len(rows), len({r["code"] for r in rows})))
        for name, fx in (("새 점수", lambda r: r["_new"]), ("새 점수(앞 기간 분포)", lambda r: r["_new_oos"]), ("예전 점수", lambda r: r["_old"])):
            t = W.tercile_test(rows, fx, "ex12m")
            rep["eval"].setdefault(gname, {})[name] = t
            if t:
                print("  %-22s 위⅓ %s · 아래⅓ %s · 차이 %s [%s, %s] · 앞 %s · 뒤 %s · 위⅓ 이긴 비율 %.0f%% (n %d)"
                      % (name, R.fmt(t["top"]), R.fmt(t["bot"]), R.fmt(t["spread"]), R.fmt(t["ci"][0]), R.fmt(t["ci"][1]),
                         R.fmt(t["early"]), R.fmt(t["late"]), t["top_hit"], t["n"]))
        for name, fn in (("등급 후보 A: 빨간불 없음", lambda r: not red(r)),
                         ("등급 후보 B: 앞단 강함 · 빨간불 없음", lambda r: strong(r) and not red(r)),
                         ("등급 후보 C: 빨간불 없음 · 새 점수 50↑", lambda r: None if r["_new"] is None else (not red(r) and r["_new"] >= 50)),
                         ("예전 등급 '억울'", lambda r: r.get("_tier") == "억울" if r.get("_tier") else
                          (bool(r.get("macro")) and not r.get("worse") and not (r.get("pct") is not None and r["pct"] >= 80)))):
            t = R.test(rows, fn)
            rep["eval"].setdefault(gname, {})[name] = t
            if "diff" in t:
                print("  %-34s 넘음 %4d 회사 %3d · 넘은쪽 %s 나머지 %s · 차이 %s [%s, %s] · 앞 %s 뒤 %s · 이긴 비율 %.0f%%"
                      % (name, t["n_on"], t["firms_on"], R.fmt(t["on"]), R.fmt(t["off"]), R.fmt(t["diff"]), R.fmt(t["ci"][0]),
                         R.fmt(t["ci"][1]), R.fmt(t["early"]), R.fmt(t["late"]), t["hit_on"]))
    rep["n_cand"], rep["firms"] = len(cand), len({r["code"] for r in cand})
    rep["dates"] = [min(r["t"] for r in cand), max(r["t"] for r in cand)]
    json.dump(rep, open(os.path.join(S.CACHE_DIR, "dip", "score_v2.json"), "w", encoding="utf-8"), ensure_ascii=False, default=str)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

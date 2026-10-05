# -*- coding: utf-8 -*-
"""
저평가 점수 재검토 — 앞 기간으로만 고르고 뒤 기간으로만 잰다 (2026-10-06)

계산을 고친 표본(.cache/value/bt_panel.json, 후보 3,792건 · 700곳)에서 지금 점수(SCORE 6항목)의 근거 절반이 약해졌다.
같은 표본으로 항목을 다시 고르면 과적합이라, 경계(2020-01-01) 앞 기간(2016~2019)만 보고 항목 · 방향을 정하고, 분포(백분위)도 앞 기간 후보로만 만든 뒤
뒤 기간(2020~2025) 성적을 지금 점수와 나란히 본다. 지금 점수는 2026-10-03 에 전 기간을 보고 고른 것이라 뒤 기간 성적도 표본 안 값이다 — 비교의 기준선일 뿐.

  고르는 규칙(앞 기간만): 후보 안 위⅓ − 아래⅓ 의 회사 단위 90% 구간이 0을 넘는 항목, 방향 = 부호, 무게 1(맞추지 않는다)
  비교: 지금 점수(SCORE) · 새 점수(앞 기간 선택) · 두 항목(업종 수출물가 · 주가 1년 — 고친 표본 전 기간에서 뚜렷했던 둘, 참고)
  잰다: 뒤 기간 후보 안 위⅓ − 아래⅓ · '점수 50↑ · 빨간불 · 부채 200%↑ 없음' 대 나머지 · 그 묶음의 12개월 초과 중앙 · 이긴 비율 · −30%↓

실행: python 도구/저평가_점수재검토.py     결과: 표준출력 + .cache/value/score_review.json
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_argv, sys.argv = sys.argv, ["x"]
import 저평가_백테스트 as V  # noqa: E402
sys.argv = _argv
W = V.W

OUT = os.path.join(V.OUT, "score_review.json")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    P = json.load(open(os.path.join(V.OUT, "bt_panel.json"), encoding="utf-8"))
    base = [r for r in P if r.get("ex12m") is not None and r.get("dd") is not None]
    C = [r for r in base if V.cand(r)]
    TR = [r for r in C if r["t"] < W.SPLIT]
    TE = [r for r in C if r["t"] >= W.SPLIT]
    print("후보 %d(%d곳) — 앞 %d · 뒤 %d" % (len(C), len({r["code"] for r in C}), len(TR), len(TE)))
    fx_of = {k: f for k, _, f in V.FACT}
    nm_of = {k: n for k, n, _ in V.FACT}

    # 1) 앞 기간만으로 항목 고르기
    pick, table = [], {}
    for k, nm, fx in V.FACT:
        t = W.tercile_test(TR, fx, "ex12m")
        t2 = W.tercile_test(TE, fx, "ex12m")
        table[k] = {"name": nm, "앞": t, "뒤": t2}
        if t and t.get("ci") and t["ci"][0] is not None and (t["ci"][0] > 0 or t["ci"][1] < 0):
            pick.append((k, nm, 1.0, 1 if t["spread"] > 0 else -1))
        f = lambda x: "—" if x is None else "%+.1f" % x
        print("  %-22s 앞 %s [%s, %s]  뒤 %s [%s, %s]%s" % (
            nm, f(t and t["spread"]), f(t and t["ci"][0]), f(t and t["ci"][1]),
            f(t2 and t2["spread"]), f(t2 and t2["ci"][0]), f(t2 and t2["ci"][1]), "  ← 앞 기간에서 고름" if pick and pick[-1][0] == k else ""))
    print("앞 기간이 고른 항목: %s" % ", ".join("%s(%s)" % (n, "+" if d > 0 else "−") for _, n, _, d in pick))

    specs = {
        "지금 점수(6항목, 전 기간을 보고 고름)": V.SCORE,
        "새 점수(앞 기간이 고름)": pick,
        "두 항목(업종 수출물가 · 주가 1년, 참고)": [("mp_yoy", nm_of["mp_yoy"], 1.0, 1), ("px_yoy", nm_of["px_yoy"], 1.0, -1)],
    }
    heavy = lambda r: r.get("debt_eq") is not None and r["debt_eq"] >= 200
    res = {"앞기간_항목": table, "새점수_항목": [{"key": k, "name": n, "w": w, "dir": d} for k, n, w, d in pick], "비교": {}}
    for label, spec in specs.items():
        if not spec:
            print("\n== %s — 항목 없음" % label)
            continue
        dist = {k: sorted(v for v in (fx_of[k](r) for r in TR) if v is not None) for k, *_ in spec}   # 앞 기간 분포
        for r in C:
            r["_x"] = V.score(r, dist, spec)
        tt = W.tercile_test(TE, lambda r: r["_x"], "ex12m")
        grade = lambda r: None if r["_x"] is None else (not V.red(r) and not heavy(r) and r["_x"] >= 50)
        gt = V.test(TE, grade)
        on = [r for r in TE if r["_x"] is not None and not V.red(r) and not heavy(r) and r["_x"] >= 50]
        g = V.group(on)
        res["비교"][label] = {"항목": [k for k, *_ in spec], "뒤_위⅓−아래⅓": tt, "뒤_등급": gt, "뒤_묶음": g}
        f = V.fmt
        print("\n== %s" % label)
        if tt:
            print("  뒤 기간 위⅓ − 아래⅓ %s [%s, %s] · 위⅓ 이긴 %.0f%%" % (f(tt["spread"]), f(tt["ci"][0]), f(tt["ci"][1]), tt["top_hit"]))
        if "diff" in gt:
            print("  뒤 기간 등급(점수 50↑ · 빨간불 · 부채 200%%↑ 없음) 넘음 %d — 차이 %s [%s, %s]" % (gt["n_on"], f(gt["diff"]), f(gt["ci"][0]), f(gt["ci"][1])))
        if g:
            print("  그 묶음 12개월 초과 중앙 %s · 이긴 %.0f%% · −30%%↓ %.0f%%" % (f(g["median"]), g["hit"], g["crash"]))
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, default=str)
    print("\n→ %s" % OUT)


if __name__ == "__main__":
    main()

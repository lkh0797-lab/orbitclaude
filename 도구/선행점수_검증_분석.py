# -*- coding: utf-8 -*-
"""
선행 점수 표본 외 검증 — 도구/선행점수_검증.mjs 결과를 읽는다.

보정(14종목·보고서 513건)에서 정한 분위 경계(INV_LEAD.cuts)를 그대로 두고, 그 14종목과 겹치지 않는 회사들에 적용한다.
  - 분위별 공시 뒤 3·6·12개월 수익률(절대, 그리고 같은 기간 전 종목 중앙값 대비 초과)
  - 5분위 − 1분위 차이의 회사 단위 부트스트랩 90% 구간
  - 점수 세 조각(새 문장 · 주가 흐름 · 재무 모멘텀 할인)의 순위상관
  - 앞(~2019) / 뒤(2020~) 기간

실행: python 도구/선행점수_검증_분석.py .cache/invest_lead_60.json
결과: 표준출력 + .cache/invest/lead_oos.json (화면이 읽는다)
"""
import os
import sys
import json
import random
import statistics as st
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("wb", os.path.join(HERE, "억울_백테스트.py"))
W = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(W)

CUTS = [0.307, 0.858, 1.401, 2.12]          # 웹/index.html INV_LEAD.cuts — 보정 때 정한 경계, 바꾸지 않는다
CAL = {"f3": {1: -1.0, 2: 4.1, 3: 1.4, 4: 3.3, 5: 11.6}}   # 보정 표본의 3개월 중앙값(비교용)
H = {"f3": 91, "f6": 182, "f12": 365}


def q_of(L):
    return sum(1 for c in CUTS if L > c) + 1


def boot_spread(rows, key, n=800, seed=7):
    firms = sorted({r["code"] for r in rows})
    by = {}
    for r in rows:
        by.setdefault(r["code"], []).append(r)
    rnd = random.Random(seed)
    vals = []
    for _ in range(n):
        smp = [x for f in (rnd.choice(firms) for _ in firms) for x in by[f]]
        hi = [x[key] for x in smp if x["q"] == 5 and x.get(key) is not None]
        lo = [x[key] for x in smp if x["q"] == 1 and x.get(key) is not None]
        if len(hi) >= 5 and len(lo) >= 5:
            vals.append(st.median(hi) - st.median(lo))
    vals.sort()
    return (vals[int(len(vals) * .05)], vals[int(len(vals) * .95)]) if vals else (None, None)


def spear(a, b):
    p = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(p) < 20:
        return None
    x, y = zip(*p)
    rx, ry = W.rank(list(x)), W.rank(list(y))
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((i - mx) * (j - my) for i, j in zip(rx, ry))
    den = (sum((i - mx) ** 2 for i in rx) * sum((j - my) ** 2 for j in ry)) ** .5
    return num / den if den else None


def main(path):
    rows = json.load(open(path, encoding="utf-8"))
    for r in rows:
        r["q"] = q_of(r["L"])
        for k, days in H.items():
            u = W.grp_ret("__all__", r["filed"], W.shift(r["filed"], days))
            r["x" + k[1:]] = (r[k] - u) if (r.get(k) is not None and u is not None) else None
    firms = len({r["code"] for r in rows})
    print("표본 %d건 · %d곳 (보정 14종목 제외)" % (len(rows), firms))
    out = {"n": len(rows), "firms": firms, "quint": {}, "spread": {}, "ic": {}, "cuts": CUTS}
    print("\n== 분위별 (경계는 보정 때 그대로)  절대 3개월 중앙 · 초과 3/6/12개월 중앙 · 상승 비율")
    for q in range(1, 6):
        sub = [r for r in rows if r["q"] == q]
        if not sub:
            continue
        g = lambda k: [r[k] for r in sub if r.get(k) is not None]
        rec = {"n": len(sub), "firms": len({r['code'] for r in sub}),
               "f3": st.median(g("f3")) if g("f3") else None, "up3": sum(v > 0 for v in g("f3")) / max(1, len(g("f3"))) * 100,
               "x3": st.median(g("x3")) if g("x3") else None, "x6": st.median(g("x6")) if g("x6") else None,
               "x12": st.median(g("x12")) if g("x12") else None}
        out["quint"][q] = rec
        print("  %d분위 %4d건(%2d곳) 3개월 %+5.1f%% 상승 %2.0f%% | 초과 3개월 %s 6개월 %s 12개월 %s | 보정 때 3개월 %+.1f%%" % (
            q, rec["n"], rec["firms"], rec["f3"] or 0, rec["up3"],
            "%+.1f" % rec["x3"] if rec["x3"] is not None else "—", "%+.1f" % rec["x6"] if rec["x6"] is not None else "—",
            "%+.1f" % rec["x12"] if rec["x12"] is not None else "—", CAL["f3"][q]))
    print("\n== 5분위 − 1분위 (중앙값 차이, 회사 단위 부트스트랩 90% 구간)")
    for k in ("f3", "x3", "x6", "x12"):
        hi = [r[k] for r in rows if r["q"] == 5 and r.get(k) is not None]
        lo = [r[k] for r in rows if r["q"] == 1 and r.get(k) is not None]
        if len(hi) < 5 or len(lo) < 5:
            continue
        d = st.median(hi) - st.median(lo)
        ci = boot_spread(rows, k)
        e = [r for r in rows if r["filed"] < "20200101"]
        l = [r for r in rows if r["filed"] >= "20200101"]
        sp = lambda s: (st.median([r[k] for r in s if r["q"] == 5 and r.get(k) is not None] or [0]) -
                        st.median([r[k] for r in s if r["q"] == 1 and r.get(k) is not None] or [0]))
        out["spread"][k] = {"d": d, "ci": ci, "early": sp(e), "late": sp(l)}
        print("  %-4s %+6.1f%%p  90%% %s ~ %s  | ~2019 %+.1f  2020~ %+.1f" % (
            k, d, "%+.1f" % ci[0] if ci[0] is not None else "—", "%+.1f" % ci[1] if ci[1] is not None else "—", sp(e), sp(l)))
    print("\n== 순위상관 (모든 보고서, 초과 3개월)")
    for k, nm in (("L", "선행 점수"), ("story", "새 문장"), ("tape", "주가 흐름"), ("mom", "재무 모멘텀 할인")):
        v = spear([r[k] for r in rows], [r.get("x3") for r in rows])
        v6 = spear([r[k] for r in rows], [r.get("x6") for r in rows])
        out["ic"][k] = {"x3": v, "x6": v6}
        print("  %-12s 3개월 %s  6개월 %s" % (nm, "%+.3f" % v if v is not None else "—", "%+.3f" % v6 if v6 is not None else "—"))
    os.makedirs(os.path.join(W.S.CACHE_DIR, "invest"), exist_ok=True)
    json.dump(out, open(os.path.join(W.S.CACHE_DIR, "invest", "lead_oos.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(W.S.CACHE_DIR, "invest_lead_60.json"))

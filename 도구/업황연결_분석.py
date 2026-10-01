# -*- coding: utf-8 -*-
"""
업황(업종 수출물가 · 재고 순환)을 회사 하나에 붙이는 게 신호인가 소음인가 (2026-10-01)

분기변화_백테스트.py 가 남긴 표본(.cache/quarter/bt_panel.json — 공시일마다 그 회사의 매출 증가율 · 업종 수출물가 · 재고 순환 · 그 뒤 성적)으로
  1) 회사별 연동도 — 회사 매출(최근 4분기) 전년 대비와 업종 지표의 같은 분기 상관. 회사마다 한 값(그 회사의 전 기간).
  2) 시점 연동도 — 공시일마다 그 전 분기들(8개↑)만으로 잰 상관(미래 정보 없음). 이 값이 0.3↑인 회사(연결)와 아닌 회사(소음)로 나눠
     업황 규칙(수출물가 ±10% · 재고 순환 ±10%p)의 성적(4분기 뒤 매출 증가율 · 영업이익률 변화, 12개월 초과수익)을 비교한다.
연결하는 쪽이 나머지보다 뚜렷이 낫고 소음 쪽이 0 근처면 → 연동도로 골라 붙인다(화면은 연동도를 같이 보여 준다).

실행: python 도구/업황연결_분석.py      결과: 표준출력 + .cache/quarter/macro_fit.json
"""
import os
import sys
import json
import math
import statistics as st
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("bt", os.path.join(HERE, "분기변화_백테스트.py"))
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)
W = B.W
OUT = B.OUT


def corr(xs, ys):
    p = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(p) < 8:
        return None
    x, y = zip(*p)
    mx, my = sum(x) / len(x), sum(y) / len(y)
    vx = sum((a - mx) ** 2 for a in x)
    vy = sum((b - my) ** 2 for b in y)
    if vx <= 0 or vy <= 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(vx * vy)


def clip(v):
    return None if v is None else max(-100.0, min(300.0, v))


def main():
    panel = json.load(open(os.path.join(OUT, "bt_panel.json"), encoding="utf-8"))
    by = {}
    for r in panel:
        by.setdefault(r["code"], []).append(r)
    rep = {"firm": {}, "split": {}}
    # 1) 회사별 연동도(전 기간)
    for key, name in (("mp_yoy", "수출물가"), ("cyc", "재고 순환")):
        rs = []
        for code, rows in by.items():
            rows.sort(key=lambda r: r["lab"])
            v = corr([clip(r.get(key)) for r in rows], [clip(r.get("rev_yoy")) for r in rows])
            if v is not None:
                rs.append(v)
        if rs:
            rs.sort()
            d = {"n": len(rs), "median": st.median(rs), "p25": rs[len(rs) // 4], "p75": rs[3 * len(rs) // 4],
                 "ge04": sum(v >= 0.4 for v in rs) / len(rs) * 100, "ge03": sum(v >= 0.3 for v in rs) / len(rs) * 100,
                 "le0": sum(v <= 0 for v in rs) / len(rs) * 100}
            rep["firm"][name] = d
            print("== 회사별 연동도 · %s — 회사 %d · 중앙 %.2f (25%% %.2f · 75%% %.2f) · 0.4↑ %.0f%% · 0.3↑ %.0f%% · 0 이하 %.0f%%"
                  % (name, d["n"], d["median"], d["p25"], d["p75"], d["ge04"], d["ge03"], d["le0"]))
    # 2) 시점 연동도 — 그 전 분기들만으로
    for r in panel:
        r["_fit_mp"] = r["_fit_cyc"] = None
    for code, rows in by.items():
        rows.sort(key=lambda r: r["lab"])
        for i, r in enumerate(rows):
            prev = rows[:i]
            r["_fit_mp"] = corr([clip(x.get("mp_yoy")) for x in prev], [clip(x.get("rev_yoy")) for x in prev])
            r["_fit_cyc"] = corr([clip(x.get("cyc")) for x in prev], [clip(x.get("rev_yoy")) for x in prev])
    rules = [("수출물가 +10%↑", "mp_yoy", "_fit_mp", lambda v: v >= 10), ("수출물가 −10%↓", "mp_yoy", "_fit_mp", lambda v: v <= -10),
             ("재고 순환 +10%p↑", "cyc", "_fit_cyc", lambda v: v >= 10), ("재고 순환 −10%p↓", "cyc", "_fit_cyc", lambda v: v <= -10)]
    for y, lab in (("drev4", "4분기 뒤 매출 증가율"), ("dopm4", "4분기 뒤 영업이익률"), ("ex12m", "12개월 초과수익")):
        print("\n== %s 변화 — 해당 − 나머지(중앙값 %%p) · [90%% 구간] — 연결(시점 연동도 ≥ 0.3) / 소음(< 0.3) / 연동도 모름" % lab)
        for name, key, fk, fn in rules:
            line = []
            for grp, sel in (("연결", lambda r: r[fk] is not None and r[fk] >= 0.3),
                             ("소음", lambda r: r[fk] is not None and r[fk] < 0.3),
                             ("모름", lambda r: r[fk] is None)):
                sub = [r for r in panel if r.get(key) is not None and sel(r)]
                t = B.rule_test(sub, lambda r: fn(r[key]), y)
                rep["split"].setdefault(name, {}).setdefault(y, {})[grp] = t
                if "diff" in t:
                    line.append("%s %s [%s, %s] n%d" % (grp, B.fmt(t["diff"]), B.fmt(t["ci"][0]), B.fmt(t["ci"][1]), t["n_on"]))
                else:
                    line.append("%s 표본 부족(n%d)" % (grp, t.get("n_on", 0)))
            print("%-14s %s" % (name, " · ".join(line)))
    json.dump(rep, open(os.path.join(OUT, "macro_fit.json"), "w", encoding="utf-8"), ensure_ascii=False, default=str)


if __name__ == "__main__":
    main()

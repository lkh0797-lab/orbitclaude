# -*- coding: utf-8 -*-
"""
억울한 낙폭 재점검 (2026-10-02) — 지난 검증 표본에 '분기 변화' 파이프라인 지표를 시점에 맞춰 붙여, 무엇이 진짜 억울한 낙폭을 가르나 본다.

표본  .cache/dip/bt_panel.json (억울_백테스트.py — 매달 말, 잔고를 믿을 수 있는 회사의 관문 값 · 그 뒤 6/12개월 초과수익)
붙임  .cache/quarter/bt_panel.json (분기변화_백테스트.py — 공시일마다 잔고 · 선수금 · 재고+계약자산 · 매출 증가율, 업황(재고 순환 ·
      수출물가), 분할 보정 PER 자기 역사 백분위 · PEG, 이익률 위치). 그 달 말 이전 마지막 공시(200일 안)를 붙인다 — 미래 정보 없음.
보는 것  관문을 다 넘은 후보(잔고 · 돈 · 20%↓ 하락 · 이익 유지) 안에서, 각 점검을 넘은 쪽과 아닌 쪽의 12개월 초과수익 차이(중앙값),
      회사 단위 부트스트랩 90% 구간, 앞(~2019)/뒤(2020~). 후보가 작아(수백 건 · 수십 곳) 넓은 표본(하락 20%↓ 전부)에서도 같은 방향인지 본다.

실행: python 도구/억울_재점검.py
"""
import os
import sys
import json
import bisect
import statistics as st
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("wb", os.path.join(HERE, "억울_백테스트.py"))
W = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(W)
S = W.S
DIP = json.load(open(os.path.join(S.CACHE_DIR, "dip", "bt_panel.json"), encoding="utf-8"))
QP = json.load(open(os.path.join(S.CACHE_DIR, "quarter", "bt_panel.json"), encoding="utf-8"))


def attach():
    by = {}
    for q in QP:
        by.setdefault(q["code"], []).append(q)
    for v in by.values():
        v.sort(key=lambda q: q["date"])
    keys = ("rev_yoy", "blog_yoy", "liab_yoy", "wip_yoy", "capex_yoy", "ni_yoy", "per_pct", "peg", "opm_pct", "cyc", "mp_yoy")
    n = 0
    for r in DIP:
        qs = by.get(r["code"], [])
        ds = [q["date"] for q in qs]
        i = bisect.bisect_right(ds, r["t"]) - 1
        q = qs[i] if i >= 0 and W.shift(qs[i]["date"], 200) >= r["t"] else None
        for k in keys:
            r["q_" + k] = q.get(k) if q else None
        n += bool(q)
    return n


def gap(r, k):
    a, b = r.get("q_" + k), r.get("q_rev_yoy")
    return a - b if a is not None and b is not None else None


CHECKS = [   # (이름, 넘으면 True · 판정 불가 None)
    ("지금 등급 '억울'(시장·업종 동반 · 혼자 더 안 빠짐 · 안 비쌈)", lambda r: r.get("_tier") == "억울"),
    ("시장·업종이 같이 빠졌다(macro)", lambda r: bool(r.get("macro"))),
    ("앞단 강함: 잔고 또는 선수금이 매출보다 +15%p↑", lambda r: None if gap(r, "blog_yoy") is None and gap(r, "liab_yoy") is None
     else ((gap(r, "blog_yoy") or -1e9) >= 15 or (gap(r, "liab_yoy") or -1e9) >= 15)),
    ("앞단 약함: 잔고가 매출보다 −15%p↓", lambda r: None if gap(r, "blog_yoy") is None else gap(r, "blog_yoy") <= -15),
    ("선수금이 매출보다 −15%p↓", lambda r: None if gap(r, "liab_yoy") is None else gap(r, "liab_yoy") <= -15),
    ("재고+계약자산이 매출보다 +20%p↑", lambda r: None if gap(r, "wip_yoy") is None else gap(r, "wip_yoy") >= 20),
    ("업종 재고 쌓임(재고 순환 −10%p↓) · 회사 매출 +5%↑", lambda r: None if r.get("q_cyc") is None or r.get("q_rev_yoy") is None
     else (r["q_cyc"] <= -10 and r["q_rev_yoy"] > 5)),
    ("업종 재고 순환 −10%p↓(전체)", lambda r: None if r.get("q_cyc") is None else r["q_cyc"] <= -10),
    ("업종 재고 순환 +10%p↑", lambda r: None if r.get("q_cyc") is None else r["q_cyc"] >= 10),
    ("업종 수출물가 −10%↓", lambda r: None if r.get("q_mp_yoy") is None else r["q_mp_yoy"] <= -10),
    ("PER(분할 보정) 자기 역사 상위 30%", lambda r: None if r.get("q_per_pct") is None else r["q_per_pct"] >= 70),
    ("PER(분할 보정) 자기 역사 하위 30%", lambda r: None if r.get("q_per_pct") is None else r["q_per_pct"] <= 30),
    ("PEG < 1", lambda r: None if r.get("q_peg") is None and r.get("q_per_pct") is None else (r.get("q_peg") is not None and r["q_peg"] < 1)),
    ("이익률 자기 역사 상위 10%", lambda r: None if r.get("q_opm_pct") is None else r["q_opm_pct"] >= 90),
    ("순이익(최근 4분기) +20%↑", lambda r: None if r.get("q_ni_yoy") is None else r["q_ni_yoy"] >= 20),
]


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


def fmt(v):
    return "—" if v is None else "%+.1f" % v


def main():
    n = attach()
    print("붙인 표본 %d / %d" % (n, len(DIP)))
    # 관문을 다 넘은 후보 — 화면과 같은 규칙(돈 · 핵심 사업 · 20%↓ · 이익 고점 대비 −5% 이내)
    for r in DIP:
        r["_cand"] = bool(r.get("money") and r.get("core") and r.get("dd") is not None and r["dd"] <= -20
                          and (r.get("e_chg") is None or r["e_chg"] >= -5))
        why = (not r.get("macro")) or r.get("worse") or (r.get("pct") is not None and r["pct"] >= 80)
        r["_tier"] = "관찰" if why else "억울"
    groups = [("관문을 다 넘은 후보", [r for r in DIP if r["_cand"]]),
              ("넓은 표본(잔고 믿을 만 · 20%↓ 하락 전부)", [r for r in DIP if r.get("dd") is not None and r["dd"] <= -20])]
    rep = {}
    for gname, rows in groups:
        print("\n== %s — n %d · 회사 %d · 12개월 초과수익 중앙값 %s" % (gname, len(rows), len({r["code"] for r in rows}),
                                                          fmt(st.median([r["ex12m"] for r in rows if r.get("ex12m") is not None]))))
        print("%-52s %5s %5s %7s %7s %7s %16s %7s %7s" % ("점검", "넘음", "회사", "넘은쪽", "나머지", "차이", "90% 구간", "앞", "뒤"))
        for name, fn in CHECKS:
            t = test(rows, fn)
            rep.setdefault(gname, {})[name] = t
            if "diff" not in t:
                print("%-52s %5d  (표본 부족)" % (name, t["n_on"]))
                continue
            print("%-52s %5d %5d %7s %7s %7s %16s %7s %7s" % (name, t["n_on"], t["firms_on"], fmt(t["on"]), fmt(t["off"]), fmt(t["diff"]),
                                                            "[%s, %s]" % (fmt(t["ci"][0]), fmt(t["ci"][1])), fmt(t["early"]), fmt(t["late"])))
    json.dump(rep, open(os.path.join(S.CACHE_DIR, "dip", "재점검.json"), "w", encoding="utf-8"), ensure_ascii=False, default=str)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

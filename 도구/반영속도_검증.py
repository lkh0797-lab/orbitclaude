# -*- coding: utf-8 -*-
"""
'이 보고서는 이미 주가에 반영됐나?' — 정보 종류별로 공시 뒤 수익률과의 관계를 잰다.

문헌이 말하는 반영 속도를 우리 데이터(수집된 종목의 2015년 이후 정기보고서)로 확인한다.
  실적 수준·증가율      잠정실적으로 공시 전에 이미 값에 든다                → 공시 뒤 관계 ≈ 0 이어야
  문장 변화(Lazy Prices) Cohen·Malloy·Nguyen(2020): 보고서를 많이 고친 회사는 이후 수익률이 낮다 → 음(−)
  이익의 질(발생액)     Sloan(1996): 이익이 현금으로 안 들어오는 회사는 이후 수익률이 낮다 → 영업CF/순이익 과 양(+)
  수익성(질)            Novy-Marx(2013)·Asness 외 QMJ: 높은 수익성은 1년 단위로 초과수익      → ROE 와 양(+)
  값                    PSR·PER 이 낮을수록 1~5년 수익률이 높다(Barbee 외 1996 등)            → PSR 백분위와 음(−)
  주가 흐름             공시 뒤 표류(PEAD, Bernard·Thomas 1989)·모멘텀                         → 직전 주가 흐름과 양(+)

실행: python 도구/반영속도_검증.py [종목,...]   (뷰어 서버 모듈과 캐시를 그대로 쓴다. DART 주식수 조회가 캐시에 없으면 API 를 부른다)
결과: 표준출력 + .cache/반영속도.json (화면이 읽는다)
"""
import os
import sys
import json
import math
import statistics as st
import importlib.util

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.argv = [sys.argv[0]] + sys.argv[1:]
_spec = importlib.util.spec_from_file_location("srv", os.path.join(BASE, "서버.py"))
S = importlib.util.module_from_spec(_spec)
_argv, sys.argv = sys.argv, ["x"]
_spec.loader.exec_module(S)
sys.argv = _argv
S.INDEX.update(json.load(open(S.INDEX_PATH, encoding="utf-8")))

CODES = (sys.argv[1].split(",") if len(sys.argv) > 1 else
         "267260,042700,005930,000660,064400,009150,011070,007660,025860,056190,064350,373220,375500,403870".split(","))
H = {"3개월": 63, "6개월": 126, "12개월": 252}


def rank(v):
    s = sorted(range(len(v)), key=lambda i: v[i])
    r = [0] * len(v)
    for k, i in enumerate(s):
        r[i] = k
    return r


def spear(a, b):
    p = [(x, y) for x, y in zip(a, b) if x is not None and y is not None and math.isfinite(x) and math.isfinite(y)]
    if len(p) < 6:
        return None
    x, y = zip(*p)
    rx, ry = rank(x), rank(y)
    m = (len(p) - 1) / 2
    num = sum((i - m) * (j - m) for i, j in zip(rx, ry))
    den = math.sqrt(sum((i - m) ** 2 for i in rx) * sum((j - m) ** 2 for j in ry))
    return num / den if den else None


def within(rows, fx, h):
    by = {}
    for r in rows:
        by.setdefault(r["code"], []).append(r)
    cs = [spear([fx(r) for r in v], [r[h] for r in v]) for v in by.values()]
    cs = [c for c in cs if c is not None]
    return (st.mean(cs) if cs else None), len(cs), (sum(1 for c in cs if c > 0) if cs else 0)


def main():
    rows = []
    for code in CODES:
        c = S.company_by_code(code)
        if not c:
            continue
        corp = S.corp_code_of(code)
        pr = S.FIN.fetch_prices(code)
        if not pr:
            continue
        ds = sorted(pr)
        adj = S.SYN._adjusted(pr, ds)
        di = {d: i for i, d in enumerate(ds)}

        def at(d8):
            k = None
            for i in range(len(ds)):
                if ds[i] <= d8:
                    k = i
                else:
                    break
            return k
        orb = {r["rcept"]: r for r in (S.orbit(code) or {}).get("rows", [])}
        years = sorted({int(r["stamp"][:4]) for r in c["reports"]})
        funds = {d["year"]: d for d in S.INF.fundamentals(S.FIN, corp, years)}
        reps = [r for r in c["reports"] if not r["tag"] and r["stamp"] >= "2015-01"]
        prev_k = None
        for r in reps:
            d8 = r["rcept"][:8]
            k = at(d8)
            if k is None:
                continue
            row = {"code": code, "name": c["name"], "stamp": r["stamp"], "label": r["label"]}
            for h, n in H.items():
                row[h] = (adj[k + n] / adj[k] - 1) * 100 if k + n < len(adj) else None
            row["tape"] = (adj[k] / adj[prev_k] - 1) * 100 if prev_k is not None and prev_k < k else None
            prev_k = k
            o = orb.get(r["rcept"]) or {}
            row["rewrite"] = o.get("x")
            if r["label"] == "사업보고서":
                f = funds.get(int(r["stamp"][:4]))
                if f:
                    row["roe"] = f.get("roe")
                    row["margin"] = f.get("margin")
                    row["cfo_ni"] = f.get("cfo_ni")
                    row["rev_yoy"] = f.get("rev_yoy")
                    sh = S.FIN.fetch_shares(corp, int(r["stamp"][:4]), "11011").get("shares")
                    row["psr"] = (pr[ds[k]] * sh / f["rev"]) if (sh and f.get("rev") and f["rev"] > 0) else None
            rows.append(row)
        # PSR 은 종목마다 늘 받던 수준이 달라 자기 역사 백분위로 바꾼다(그때까지의 과거만)
        hist = []
        for row in [x for x in rows if x["code"] == code and x.get("psr")]:
            hist.append(row["psr"])
            row["psr_pct"] = sum(1 for v in hist if v <= row["psr"]) / len(hist) * 100 if len(hist) >= 3 else None
        print(code, c["name"], sum(1 for x in rows if x["code"] == code), flush=True)

    tests = [
        ("rewrite", "문장 변화량 (평소 대비 배수)", "Lazy Prices — 많이 고친 보고서 뒤 수익률 낮음", -1, "all"),
        ("tape", "직전 보고서 뒤 주가 흐름", "공시 뒤 표류·모멘텀 — 이어짐", 1, "all"),
        ("rev_yoy", "매출 증가율(연간)", "실적 수준은 공시 전 반영 — 관계 약함", 0, "annual"),
        ("margin", "영업이익률 수준", "수익성 — 1년 단위 초과수익", 1, "annual"),
        ("roe", "ROE", "수익성(질) — 1년 단위 초과수익", 1, "annual"),
        ("cfo_ni", "영업CF ÷ 순이익 (이익의 현금화)", "발생액 이상현상 — 현금화 좋을수록 높음", 1, "annual"),
        ("psr_pct", "PSR 자기 역사 백분위", "값 — 비쌀수록 이후 낮음", -1, "annual"),
    ]
    out = {"n": len(rows), "codes": len(CODES), "tests": []}
    print("\n신호 | 문헌 기대 | 3개월 · 6개월 · 12개월 (종목 안 순위상관 평균, 양(+)인 종목 수/종목 수)")
    for key, nm, lit, sign, scope in tests:
        rs = [r for r in rows if (scope == "all" or r["label"] == "사업보고서")]
        res = {}
        for h in H:
            w, n, pos = within(rs, lambda r: r.get(key), h)
            res[h] = {"rho": None if w is None else round(w, 3), "cos": n, "pos": pos,
                      "n": sum(1 for r in rs if r.get(key) is not None and r.get(h) is not None)}
        out["tests"].append({"key": key, "name": nm, "lit": lit, "sign": sign, "res": res})
        print("%-28s | %s | %s" % (nm, lit, " · ".join(
            "%s %s (%d/%d, n=%d)" % (h, "—" if res[h]["rho"] is None else "%+.2f" % res[h]["rho"], res[h]["pos"], res[h]["cos"], res[h]["n"])
            for h in H)))
    # 종목 사이 비교 — 같은 해 사업보고서끼리 순위를 매겨(수익성 요인은 원래 이렇게 잰다) 해마다 상관을 내고 평균
    print("\n종목 사이 (같은 해 사업보고서끼리, 해마다 순위상관 평균)")
    ann = [r for r in rows if r["label"] == "사업보고서"]
    out["cross"] = []
    for key in ("roe", "margin", "cfo_ni", "rev_yoy", "psr"):
        res = {}
        for h in H:
            by = {}
            for r in ann:
                by.setdefault(r["stamp"][:4], []).append(r)
            cs = [spear([r.get(key) for r in v], [r[h] for r in v]) for v in by.values() if len(v) >= 6]
            cs = [c for c in cs if c is not None]
            res[h] = {"rho": round(st.mean(cs), 3) if cs else None, "years": len(cs), "pos": sum(1 for c in cs if c > 0)}
        out["cross"].append({"key": key, "res": res})
        print("  %-8s %s" % (key, " · ".join("%s %s (%d/%d년)" % (h, "—" if res[h]["rho"] is None else "%+.2f" % res[h]["rho"],
                                                                 res[h]["pos"], res[h]["years"]) for h in H)))
    with open(os.path.join(S.CACHE_DIR, "반영속도.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

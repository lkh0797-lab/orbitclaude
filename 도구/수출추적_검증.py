# -*- coding: utf-8 -*-
"""
수출 추적의 계산법이 의미가 있나 — 여러 계산법을 공시 매출 · 주가로 대결시킨다 (2026-10-02)

통관 수출의 쓸모는 '분기보고서(분기 말 + 45~90일)보다 먼저 이번 분기 매출을 아는 것'이다. 그래서 판단 시점을
분기 마지막 달 통관이 나온 날(분기 말 + 15일)로 두고, 그때 알 수 있는 계산법들을 견준다.
  3개월   그 분기 석 달 합의 전년 대비(지금 화면 '최근 3개월'이 분기 말 직후에 내는 값)
  6개월   그 분기 + 직전 분기 여섯 달 합의 전년 대비
  12개월  최근 12개월 합의 전년 대비
  로그    3개월을 log((올해+ε)/(작년+ε))로 — 작년 값이 0 · 소액일 때 +1500% 같은 폭주를 누른다
맞힐 것
  (1) 그 분기 매출 증가율(공시) — 같은 분기 순위상관(분기마다 회사들끼리)
  (2) 매출 증가율의 변화(이번 분기 − 직전 분기) — 시장이 아직 모르는 '가속 · 둔화' — 통관 변화와 순위상관
  (3) 주가 — 판단 시점 다음 거래일 종가부터 90일 초과수익(2026-10-07 고침)(전 종목 중앙값 대비) — 통관 변화(이번 − 직전 분기)와 순위상관
덩어리 수출(0인 달이 12개월 중 3번↑ 또는 한 달이 12개월 합의 40%↑)을 따로 떼어 본다.
재무는 재무.py 캐시만(네트워크 없음), 주가는 억울_백테스트.py 의 캐시.

실행: python 도구/수출추적_검증.py     결과: 표준출력 + .cache/수출추적/검증.json
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
_spec.loader.exec_module(B)          # 재무 네트워크 차단 · 주가 캐시(W)
W, S, FIN = B.W, B.S, B.FIN
OUT = os.path.join(S.CACHE_DIR, "수출추적")


def mshift(ym, k):
    y, m = int(ym[:4]), int(ym[4:]) - k
    while m <= 0:
        y, m = y - 1, m + 12
    return "%d%02d" % (y, m)


def qmonths(q):
    y, n = int(q[:4]), int(q[5])
    return ["%d%02d" % (y, (n - 1) * 3 + i) for i in (1, 2, 3)]


def qprev(q, k=1):
    y, n = int(q[:4]), int(q[5]) - k
    while n <= 0:
        y, n = y - 1, n + 4
    return "%dQ%d" % (y, n)


def wsum(mon, months):
    vs = [mon.get(m) for m in months]
    return sum(v or 0 for v in vs) if any(v is not None for v in vs) else None


def yoy(a, b):
    return (a / b - 1) * 100 if a is not None and b and b > 0 else None


def measures(mon, q):
    """판단 시점(분기 말 + 15일)에 알 수 있는 계산법들."""
    last = qmonths(q)[-1]
    m3 = qmonths(q)
    m6 = [mshift(last, k) for k in range(6)]
    m12 = [mshift(last, k) for k in range(12)]
    ly = lambda ms: [mshift(m, 12) for m in ms]
    a3, b3 = wsum(mon, m3), wsum(mon, ly(m3))
    out = {"m3": yoy(a3, b3), "m6": yoy(wsum(mon, m6), wsum(mon, ly(m6))), "m12": yoy(wsum(mon, m12), wsum(mon, ly(m12)))}
    t12 = [mon.get(m) or 0 for m in m12]
    tot = sum(t12)
    eps = tot / 12 * 0.25 if tot > 0 else 1.0           # 평소 한 달의 4분의 1 — 0 · 소액 달을 누르는 완충
    out["log"] = math.log((a3 or 0) / 3 + eps) - math.log((b3 or 0) / 3 + eps) if a3 is not None and b3 is not None else None
    out["lumpy"] = (sum(1 for v in t12 if v <= 0) >= 3) or (tot > 0 and max(t12) / tot >= 0.4)
    return out


def rank(v):
    o = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
            j += 1
        for k in range(i, j + 1):
            r[o[k]] = (i + j) / 2
        i = j + 1
    return r


def spear(a, b):
    p = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(p) < 15:
        return None
    x, y = zip(*p)
    rx, ry = rank(list(x)), rank(list(y))
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((i - mx) * (j - my) for i, j in zip(rx, ry))
    den = math.sqrt(sum((i - mx) ** 2 for i in rx) * sum((j - my) ** 2 for j in ry))
    return num / den if den else None


def ic(rows, fx, fy):
    by = {}
    for r in rows:
        by.setdefault(r["q"], []).append(r)
    vals = [v for v in (spear([fx(r) for r in rs], [fy(r) for r in rs]) for rs in by.values()) if v is not None]
    if len(vals) < 4:
        return None
    m = sum(vals) / len(vals)
    sd = st.pstdev(vals) or 1e-9
    return {"ic": m, "t": m / (sd / math.sqrt(len(vals))), "n_q": len(vals), "pos": sum(v > 0 for v in vals) / len(vals)}


def main():
    d = json.load(open(os.path.join(OUT, "result.json"), encoding="utf-8"))
    rows = []
    for k, x in enumerate([i for i in d["items"] if i.get("status") == "ok" and (i.get("series_long") or i.get("series"))], 1):
        c = S.company_by_code(x["code"])
        corp = S.corp_code_of(x["code"]) if c else None
        if not corp:
            continue
        try:
            mi = FIN.statement_matrix(corp, list(range(2019, 2027)), "IS", "q")
        except Exception:
            continue
        rv = S._mseries(mi, S._mrow(mi, ("t:Revenue",), r"^(매출액|수익\(매출액\)|영업수익|매출)$"))
        mon = x.get("series_long") or x["series"]
        filed = {}
        for r in c["reports"]:
            y, m = r["stamp"].split("-")
            if not r["tag"] and m in S.Q_OF_MONTH:
                filed["%sQ%d" % (y, S.Q_OF_MONTH[m])] = min(filed.get("%sQ%d" % (y, S.Q_OF_MONTH[m]), "99999999"), r["rcept"][:8])
        for q in sorted(rv):
            if q < "2021Q2":
                continue
            r_q = yoy(rv.get(q), rv.get(qprev(q, 4)))
            r_p = yoy(rv.get(qprev(q)), rv.get(qprev(q, 5)))
            if r_q is None:
                continue
            me, mp = measures(mon, q), measures(mon, qprev(q))
            y, n = int(q[:4]), int(q[5])
            t = "%d%s" % (y, {1: "0415", 2: "0715", 3: "1015", 4: "1231"}[n]) if n < 4 else "%d0115" % (y + 1)
            if filed.get(q) and filed[q] <= t:          # 공시가 먼저 나왔으면(드묾) 선행이 아니다
                continue
            t1 = W.next_day(x["code"], t)      # 판단 시점 다음 거래일 종가(달력 +1일이면 t 가 금 · 토 · 휴장 전날일 때 t 또는 그 전 종가로 샀다)
            a, b = (W.ret(x["code"], t1, W.shift(t1, 90)), W.grp_ret("__all__", t1, W.shift(t1, 90))) if t1 else (None, None)
            row = {"code": x["code"], "q": q, "grade": x.get("grade"), "r": r_q, "dr": (r_q - r_p) if r_p is not None else None,
                   "ex90": (a - b) if a is not None and b is not None else None, "lumpy": me["lumpy"]}
            for key in ("m3", "m6", "m12", "log"):
                row[key] = me[key]
                row["d" + key] = (me[key] - mp[key]) if me[key] is not None and mp[key] is not None else None
            rows.append(row)
        if k % 50 == 0:
            print("  %d · 표본 %d" % (k, len(rows)), flush=True)
    # 시점 신뢰도 — 그 분기 전 분기들(6개↑)만으로 잰 통관 3개월 ↔ 매출 증가율 순위상관(화면 등급은 전 기간으로 매겨 미래가 섞인다)
    by = {}
    for r in rows:
        by.setdefault(r["code"], []).append(r)
    for rs in by.values():
        rs.sort(key=lambda r: r["q"])
        for i, r in enumerate(rs):
            prev = [(z["m3"], z["r"]) for z in rs[:i] if z["m3"] is not None and z["r"] is not None]
            r["fit"] = None
            if len(prev) >= 6:
                xs, ys = zip(*prev)
                rx, ry = rank(list(xs)), rank(list(ys))
                mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
                den = math.sqrt(sum((u - mx) ** 2 for u in rx) * sum((v - my) ** 2 for v in ry))
                r["fit"] = sum((u - mx) * (v - my) for u, v in zip(rx, ry)) / den if den else None
    json.dump(rows, open(os.path.join(OUT, "검증_표본.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("\n표본 %d (회사 %d) · 분기 %s ~ %s" % (len(rows), len({r["code"] for r in rows}), min(r["q"] for r in rows), max(r["q"] for r in rows)))
    rep = {}
    groups = [("전체", lambda r: True), ("신뢰도 A·B", lambda r: r["grade"] in ("A", "B")),
              ("덩어리 아님", lambda r: not r["lumpy"]), ("덩어리 수출", lambda r: r["lumpy"]),
              ("A·B · 덩어리 아님", lambda r: r["grade"] in ("A", "B") and not r["lumpy"]),
              ("시점 상관 0.3↑ · 덩어리 아님", lambda r: r.get("fit") is not None and r["fit"] >= 0.3 and not r["lumpy"]),
              ("시점 상관 0.3↓ · 덩어리 아님", lambda r: r.get("fit") is not None and r["fit"] < 0.3 and not r["lumpy"])]
    for gname, gf in groups:
        sub = [r for r in rows if gf(r)]
        print("\n== %s (n %d)" % (gname, len(sub)))
        print("%-8s %22s %26s %26s" % ("계산법", "(1) 그 분기 매출 증가율", "(2) 매출 가속 · 둔화", "(3) 90일 초과수익"))
        for key, name in (("m3", "3개월"), ("m6", "6개월"), ("m12", "12개월"), ("log", "로그 3개월")):
            a1 = ic(sub, lambda r: r[key], lambda r: r["r"])
            a2 = ic(sub, lambda r: r["d" + key], lambda r: r["dr"])
            a3 = ic(sub, lambda r: r["d" + key], lambda r: r["ex90"])
            rep.setdefault(gname, {})[key] = {"level": a1, "accel": a2, "price": a3}
            f = lambda z: "—" if not z else "IC %+.3f (t %+.1f)" % (z["ic"], z["t"])
            print("%-8s %22s %26s %26s" % (name, f(a1), f(a2), f(a3)))
    json.dump(rep, open(os.path.join(OUT, "검증.json"), "w", encoding="utf-8"), ensure_ascii=False, default=str)


if __name__ == "__main__":
    main()

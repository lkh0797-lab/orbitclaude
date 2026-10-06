# -*- coding: utf-8 -*-
"""
가속도 칸의 '가속' 기준 — 어느 쪽이 주가와 다음 매출을 더 잘 맞췄나 (2026-10-06)

세 기준을 같은 회사 · 같은 분기 · 같은 공시일에서 견준다.
  A  TTM   가속 = (최근 4분기 합 매출의 전년 대비 증가율) 의 2분기 변화 ÷ 2      — 지금 가속도 칸(drkCalc)
  B  2분기  속도 = 분기 매출 전년 대비 증가율의 최근 2분기 평균, 가속 = 속도 − 그 앞 2분기 평균 — 산업 성장률 업황 시계와 같은 식
  C  1분기  가속 = 이번 분기 전년 대비 − 지난 분기 전년 대비                      — 전 종목 가속도 스크리닝(드러켄밀러.py 매출가속)
변곡(전환) = 가속의 부호가 바뀐 분기. 문턱은 화면과 같다 — A 1.5%p(가속도 칸), B 3%p(업황 시계 띠), C 3%p. 문턱 없이 부호만 본 것도 같이 낸다.

결과
  (1) 주가 — 그 분기 보고서 공시 다음 날부터 6 · 12개월 수익률 − 같은 기간 전 종목 수익률 중앙값(초과수익)
  (2) 매출 — 2 · 4분기 뒤 TTM 매출 증가율이 몇 %p 바뀌었나(신호가 실제 성장 변화를 앞섰나)
  (3) 앞섬 — 같은 회사의 같은 방향 전환을 B 가 A 보다 몇 분기 먼저 잡았나, 그리고 2분기 안에 거꾸로 뒤집힌 헛신호 비율
  (4) 상태 — 가속 + / − 두 묶음의 12개월 초과수익 차이, 연속값 순위상관(IC)
  나눠 보기 — 수주 업종(산업_섹터.ORDER_DRIVEN: 조선 · 방산 · 전력기기 · 건설 · 기계) / 나머지, 앞(~2019) / 뒤(2020~)

재무는 캐시만 읽는다(네트워크 없음). 금융 · 보험 · 지주(KSIC 64~66)는 매출 개념이 달라 뺀다.
한계 — 지금 상장된 회사만(생존 편향: 수익률 수준은 부풀어 있고, 기준끼리 견주는 차이는 덜 휜다), 재무는 그 분기 보고서 값,
       분기 전년 대비가 기저가 거의 0인 분기에선 수천 %로 튄다(그대로 둔다 — 그 소음도 기준의 성질이다).

실행: python 도구/가속기준_백테스트.py           (처음엔 재무 캐시를 8 프로세스로 읽어 .cache/druck/bt_series.json 을 만든다 — 약 15분.
                                                 그 뒤엔 그 파일로 표만 다시 낸다. 재무를 새로 읽으려면 --rebuild)
결과: 표준출력 + .cache/druck/bt_accel.json
"""
import os
import sys
import json
import statistics as st
import importlib.util as ilu
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
OUT = os.path.join(BASE, ".cache", "druck")
SERIES = os.path.join(OUT, "bt_series.json")
YEARS = list(range(2011, 2027))
T0, T1 = "20120101", "20260331"
THR = {"A": 1.5, "B": 3.0, "C": 3.0}
NAME = {"A": "A TTM(지금)", "B": "B 2분기 평균", "C": "C 1분기"}


# ---------------------------------------------------------------- 1단 — 회사별 분기 매출(작업자 프로세스)
DRK = None


def _init():
    global DRK
    sp = ilu.spec_from_file_location("드러켄밀러", os.path.join(BASE, "드러켄밀러.py"))
    DRK = ilu.module_from_spec(sp)
    sp.loader.exec_module(DRK)
    F = DRK.FIN

    def cached(corp, year, reprt, fs_div="CFS"):
        path = os.path.join(F.FIN_DIR, "%s_%s_%s_%s.json" % (corp, year, reprt, fs_div))
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            d = {"status": "013", "list": []}
        return F._or_body(d, corp, year, reprt, fs_div)
    F.fetch_statement = cached


def _series(job):
    code, corp = job
    try:
        pts = DRK.series(corp, code, YEARS)
    except Exception:
        return code, None
    return code, [[p["year"] * 4 + p["q"] - 1, p.get("매출액"), p.get("영업이익")] for p in pts if p.get("매출액")]


def build_series(S, SEC):
    ksic = json.load(open(os.path.join(BASE, ".cache", "거시", "induty.json"), encoding="utf-8"))
    jobs, meta = [], {}
    for c in S.INDEX["companies"]:
        code = c.get("code")
        corp = S.corp_code_of(code) if code else None
        if not corp:
            continue
        k = ksic.get(corp) or ""
        if k.startswith(SEC.FIN_KSIC) and code not in SEC.OVERRIDE:
            continue
        filed = {}
        for r in c["reports"]:
            y, m = r["stamp"].split("-")
            if not r["tag"] and m in S.Q_OF_MONTH:
                n = int(y) * 4 + S.Q_OF_MONTH[m] - 1
                filed[n] = min(filed.get(n, "99999999"), r["rcept"][:8])
        meta[code] = {"name": c["name"], "sec": SEC.sector_of(code, k)[0], "filed": filed}
        jobs.append((code, corp))
    print("재무 캐시 읽는 중 — 회사 %d" % len(jobs), flush=True)
    out = {}
    with Pool(8, initializer=_init) as pool:
        for i, (code, pts) in enumerate(pool.imap_unordered(_series, jobs, chunksize=4), 1):
            if pts:
                out[code] = dict(meta[code], pts=pts)
            if i % 100 == 0:
                print("  %d/%d" % (i, len(jobs)), flush=True)
    os.makedirs(OUT, exist_ok=True)
    json.dump(out, open(SERIES, "w", encoding="utf-8"), ensure_ascii=False)
    return out


# ---------------------------------------------------------------- 2단 — 신호와 그 뒤
def signals(pts):
    rev = {n: v for n, v, _ in pts if v is not None}

    def yoy(n):
        a, b = rev.get(n - 4), rev.get(n)
        return (b / a - 1) * 100 if a and b is not None and a > 0 else None

    def ttm(n):
        v = [rev.get(k) for k in range(n - 3, n + 1)]
        return sum(v) if all(x is not None for x in v) else None

    def g(n):
        a, b = ttm(n - 4), ttm(n)
        return (b / a - 1) * 100 if a and b is not None and a > 0 else None

    def d(f, h, k):
        a, b = f(h), f(k)
        return a - b if a is not None and b is not None else None
    rows = {}
    for n in sorted(rev):
        y, y1 = yoy(n), yoy(n - 1)
        s = (y + y1) / 2 if y is not None and y1 is not None else None
        y2, y3 = yoy(n - 2), yoy(n - 3)
        s2 = (y2 + y3) / 2 if y2 is not None and y3 is not None else None
        a = d(g, n, n - 2)
        rows[n] = {"y": y, "g": g(n), "s": s,
                   "A": a / 2 if a is not None else None,
                   "B": s - s2 if s is not None and s2 is not None else None,
                   "C": y - y1 if y is not None and y1 is not None else None,
                   "dG2": d(g, n + 2, n), "dG4": d(g, n + 4, n)}
    for n, r in rows.items():
        p = rows.get(n - 1) or {}
        for m in "ABC":
            v, v0 = r[m], p.get(m)
            ok = v is not None and v0 is not None
            r[m + "_up"] = ok and v >= THR[m] and v0 < 0
            r[m + "_dn"] = ok and v <= -THR[m] and v0 > 0
            r[m + "_up0"] = ok and v >= 0 > v0
            r[m + "_dn0"] = ok and v < 0 <= v0
    return rows


def panel(W, ser):
    rows = []
    for code, co in ser.items():
        if code not in W.PX:
            continue
        sig = signals(co["pts"])
        filed = {int(k): v for k, v in co["filed"].items()}
        for n, r in sig.items():
            t = filed.get(n)
            if not t or t < T0 or t > T1:
                continue
            t1 = W.shift(t, 1)

            def ex(days):
                a = W.ret(code, t1, W.shift(t1, days))
                b = W.grp_ret("__all__", t1, W.shift(t1, days))
                return a - b if a is not None and b is not None else None
            rows.append(dict(r, code=code, n=n, lab="%dQ%d" % (n // 4, n % 4 + 1), date=t, t=t[:6] + "15",
                             sec=co["sec"], order=co["sec"] in ORDER, ex6=ex(182), ex12=ex(365)))
    return rows


# ---------------------------------------------------------------- 통계
def med(v):
    v = [x for x in v if x is not None]
    return st.median(v) if v else None


def fmt(v, d=1):
    return "—" if v is None else "%+.*f" % (d, v)


def ev_stats(W, rs, y="ex12"):
    v = [r[y] for r in rs if r.get(y) is not None]
    if len(v) < 15:
        return {"n": len(v)}
    lo, hi = W.boot([r for r in rs if r.get(y) is not None], lambda sub: med([x[y] for x in sub]), n=500)
    return {"n": len(v), "firms": len({r["code"] for r in rs}), "med": med(v), "ci": [lo, hi], "hit": sum(x > 0 for x in v) / len(v) * 100,
            "ex6": med([r["ex6"] for r in rs]), "dG2": med([r["dG2"] for r in rs]), "dG4": med([r["dG4"] for r in rs]),
            "early": med([r[y] for r in rs if r["t"] < W.SPLIT]), "late": med([r[y] for r in rs if r["t"] >= W.SPLIT])}


def spread(W, rs, f_up, f_dn, y="ex12"):
    """전환 ▲ 묶음 − ▼ 묶음의 중앙값 차이와 회사 단위 부트스트랩 90% 구간."""
    sub = [r for r in rs if r.get(y) is not None and (f_up(r) or f_dn(r))]

    def diff(x):
        a = [r[y] for r in x if f_up(r)]
        b = [r[y] for r in x if f_dn(r)]
        return st.median(a) - st.median(b) if len(a) >= 8 and len(b) >= 8 else None
    if len(sub) < 30:
        return None, (None, None)
    return diff(sub), W.boot(sub, diff, n=500)


def lead(rows, a, b, dirn):
    """b 의 전환마다, 같은 회사 · 같은 방향의 a 전환이 ±4분기 안에 있으면 (a 분기 − b 분기). + = b 가 먼저."""
    by = {}
    for r in rows:
        by.setdefault(r["code"], []).append(r)
    lags, miss = [], 0
    for rs in by.values():
        na = [r["n"] for r in rs if r[a + "_" + dirn]]
        for r in rs:
            if not r[b + "_" + dirn]:
                continue
            near = [x for x in na if abs(x - r["n"]) <= 4]
            if near:
                lags.append(min(near, key=lambda x: (abs(x - r["n"]), x)) - r["n"])
            else:
                miss += 1
    return lags, miss


def whip(rows, m):
    """전환 뒤 2분기 안에 거꾸로 전환한 비율(헛신호)."""
    by = {}
    for r in rows:
        by.setdefault(r["code"], {})[r["n"]] = r
    hit = tot = 0
    for qs in by.values():
        for n, r in qs.items():
            for dirn, opp in (("up", "dn"), ("dn", "up")):
                if r[m + "_" + dirn]:
                    tot += 1
                    hit += any((qs.get(n + k) or {}).get(m + "_" + opp) for k in (1, 2))
    return hit / tot * 100 if tot else None, tot


def report(W, rows):
    rep = {"n": len(rows), "firms": len({r["code"] for r in rows})}
    base12, base6 = med([r["ex12"] for r in rows]), med([r["ex6"] for r in rows])
    print("\n표본 %d 회사-분기 (회사 %d) · 공시일 %s ~ %s · 아무 분기나 12개월 초과수익 중앙값 %s · 6개월 %s"
          % (len(rows), rep["firms"], min(r["date"] for r in rows), max(r["date"] for r in rows), fmt(base12), fmt(base6)))
    rep["base"] = {"ex12": base12, "ex6": base6}

    def ev_table(title, rs, key):
        print("\n== " + title)
        print("%-16s %-6s %6s %5s %8s %8s %18s %6s %8s %8s %7s %7s" % (
            "기준", "전환", "n", "회사", "6개월", "12개월", "12개월 90% 구간", "이긴%", "앞~19", "뒤20~", "TTM+2Q", "TTM+4Q"))
        out = {}
        for m in "ABC":
            for suf, lab in (("_up", "▲"), ("_dn", "▼"), ("_up0", "▲부호"), ("_dn0", "▼부호")):
                s = ev_stats(W, [r for r in rs if r[m + suf]])
                out[m + suf] = s
                if "med" not in s:
                    print("%-16s %-6s %6d  (표본 부족)" % (NAME[m], lab, s["n"]))
                    continue
                print("%-16s %-6s %6d %5d %8s %8s %18s %5.0f%% %8s %8s %7s %7s" % (
                    NAME[m], lab, s["n"], s["firms"], fmt(s["ex6"]), fmt(s["med"]), "[%s, %s]" % (fmt(s["ci"][0]), fmt(s["ci"][1])),
                    s["hit"], fmt(s["early"]), fmt(s["late"]), fmt(s["dG2"]), fmt(s["dG4"])))
            sp, ci = spread(W, rs, lambda r, m=m: r[m + "_up"], lambda r, m=m: r[m + "_dn"])
            out[m + "_spread"] = {"diff": sp, "ci": list(ci)}
            print("%-16s ▲−▼ 12개월 %s [%s, %s]" % (NAME[m], fmt(sp), fmt(ci[0]), fmt(ci[1])))
        rep[key] = out

    ev_table("전환 뒤 — 전 종목", rows, "ev_all")
    ev_table("전환 뒤 — 수주 업종(조선 · 방산 · 전력기기 · 건설 · 기계)", [r for r in rows if r["order"]], "ev_order")
    ev_table("전환 뒤 — 수주 업종 밖", [r for r in rows if not r["order"]], "ev_other")

    print("\n== 앞섬 — 같은 회사 · 같은 방향 전환, ±4분기 안에서 짝 (+ = 뒤 기준이 먼저 잡음)")
    rep["lead"] = {}
    for a, b in (("A", "B"), ("A", "C"), ("B", "C")):
        for dirn in ("up", "dn"):
            lags, miss = lead(rows, a, b, dirn)
            if not lags:
                continue
            k = "%s→%s %s" % (b, a, dirn)
            ahead = sum(x > 0 for x in lags) / len(lags) * 100
            same = sum(x == 0 for x in lags) / len(lags) * 100
            rep["lead"][k] = {"n": len(lags), "miss": miss, "med": med(lags), "mean": sum(lags) / len(lags), "ahead": ahead, "same": same}
            print("%s 전환 %s (%s 와 짝): 짝 %d · 짝 없음 %d · %s 가 먼저 %.0f%% · 같은 분기 %.0f%% · 늦음 %.0f%% · 평균 %+.2f분기" % (
                b, "▲" if dirn == "up" else "▼", a, len(lags), miss, b, ahead, same, 100 - ahead - same, sum(lags) / len(lags)))

    print("\n== 헛신호 — 전환 뒤 2분기 안에 거꾸로 전환한 비율")
    rep["whip"] = {}
    for m in "ABC":
        w, tot = whip(rows, m)
        rep["whip"][m] = {"pct": w, "n": tot}
        print("%-16s %5.1f%%  (전환 %d번)" % (NAME[m], w or 0, tot))

    print("\n== 상태 — 가속 + 묶음 − 가속 − 묶음, 12개월 초과수익 중앙값 차이 / 연속값 IC")
    rep["state"] = {}
    for m in "ABC":
        sp, ci = spread(W, rows, lambda r, m=m: r[m] is not None and r[m] > 0, lambda r, m=m: r[m] is not None and r[m] < 0)
        ic12 = W.ic_stats([r for r in rows if r.get("ex12") is not None], lambda r, m=m: r[m], "ex12", 12)
        ic6 = W.ic_stats([r for r in rows if r.get("ex6") is not None], lambda r, m=m: r[m], "ex6", 6)
        rep["state"][m] = {"diff": sp, "ci": list(ci), "ic12": ic12, "ic6": ic6}
        print("%-16s 차이 %s [%s, %s] · IC 12개월 %s (t %s) · IC 6개월 %s (t %s)" % (
            NAME[m], fmt(sp), fmt(ci[0]), fmt(ci[1]), fmt(ic12 and ic12["ic"], 3), fmt(ic12 and ic12["t"], 2),
            fmt(ic6 and ic6["ic"], 3), fmt(ic6 and ic6["t"], 2)))

    print("\n== 국면 네 칸 — 12개월 초과수익 중앙값 (성장 부호: A = TTM 증가율, B = 2분기 속도, C = 분기 전년 대비)")
    rep["regime"] = {}
    gk = {"A": "g", "B": "s", "C": "y"}
    for m in "ABC":
        cells = {}
        for lab, fg, fa in (("가속 성장", 1, 1), ("감속 성장", 1, -1), ("바닥 통과", -1, 1), ("역성장 심화", -1, -1)):
            rs = [r for r in rows if r[m] is not None and r[gk[m]] is not None and r.get("ex12") is not None
                  and (r[gk[m]] > 0) == (fg > 0) and (r[m] > 0) == (fa > 0)]
            cells[lab] = {"n": len(rs), "med": med([r["ex12"] for r in rs]), "dG4": med([r["dG4"] for r in rs])}
        rep["regime"][m] = cells
        print("%-16s " % NAME[m] + " · ".join("%s %s (n %d)" % (k, fmt(v["med"]), v["n"]) for k, v in cells.items()))

    print("\n== B 전환을 A 가 받쳐 주나 — B ▲ 가운데 그 분기 A 가속도 + 인 것 / 아직 − 인 것")
    rep["confirm"] = {}
    for lab, f in (("B▲ · A 가속 +", lambda r: r["B_up"] and (r["A"] or 0) > 0), ("B▲ · A 가속 −(A 보다 먼저)", lambda r: r["B_up"] and r["A"] is not None and r["A"] <= 0),
                   ("B▼ · A 가속 −", lambda r: r["B_dn"] and (r["A"] or 0) < 0), ("B▼ · A 가속 +(A 보다 먼저)", lambda r: r["B_dn"] and r["A"] is not None and r["A"] >= 0)):
        s = ev_stats(W, [r for r in rows if f(r)])
        rep["confirm"][lab] = s
        if "med" in s:
            print("%-26s n %5d · 6개월 %s · 12개월 %s [%s, %s] · 이긴 %.0f%% · TTM+4Q %s" % (
                lab, s["n"], fmt(s["ex6"]), fmt(s["med"]), fmt(s["ci"][0]), fmt(s["ci"][1]), s["hit"], fmt(s["dG4"])))
    json.dump(rep, open(os.path.join(OUT, "bt_accel.json"), "w", encoding="utf-8"), ensure_ascii=False, default=str)


ORDER = ()

if __name__ == "__main__":
    sp = ilu.spec_from_file_location("wb", os.path.join(HERE, "억울_백테스트.py"))
    W = ilu.module_from_spec(sp)
    sp.loader.exec_module(W)
    sp = ilu.spec_from_file_location("산업_섹터", os.path.join(BASE, "산업_섹터.py"))
    SEC = ilu.module_from_spec(sp)
    sp.loader.exec_module(SEC)
    ORDER = SEC.ORDER_DRIVEN
    if "--rebuild" in sys.argv or not os.path.exists(SERIES):
        ser = build_series(W.S, SEC)
    else:
        ser = json.load(open(SERIES, encoding="utf-8"))
    print("시계열 %d 회사" % len(ser), flush=True)
    rows = panel(W, ser)
    report(W, rows)

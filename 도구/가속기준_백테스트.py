# -*- coding: utf-8 -*-
"""
가속도 칸의 '가속' 기준 — 어느 쪽이 주가와 다음 매출을 더 잘 맞췄나 (2026-10-06)

세 기준을 같은 회사 · 같은 분기 · 같은 공시일에서 견준다.
  A  TTM   가속 = (최근 4분기 합 매출의 전년 대비 증가율) 의 2분기 변화 ÷ 2      — 지금 가속도 칸(drkCalc)
  B  2분기  속도 = 분기 매출 전년 대비 증가율의 최근 2분기 평균, 가속 = 속도 − 그 앞 2분기 평균 — 산업 성장률 업황 시계와 같은 식
  C  1분기  가속 = 이번 분기 전년 대비 − 지난 분기 전년 대비                      — 전 종목 가속도 스크리닝(드러켄밀러.py 매출가속)
변곡(전환) = 가속의 부호가 바뀐 분기. 문턱은 화면과 같다 — A 1.5%p(가속도 칸), B 3%p(업황 시계 띠), C 3%p. 문턱 없이 부호만 본 것도 같이 낸다.

결과
  (1) 주가 — 그 분기 보고서 공시 다음 거래일 종가부터 6 · 12개월 수익률 − 같은 기간 전 종목 수익률 중앙값(초과수익, 2026-10-07 고침)
  (2) 매출 — 2 · 4분기 뒤 TTM 매출 증가율이 몇 %p 바뀌었나(신호가 실제 성장 변화를 앞섰나)
  (3) 앞섬 — 같은 회사의 같은 방향 전환을 B 가 A 보다 몇 분기 먼저 잡았나, 그리고 2분기 안에 거꾸로 뒤집힌 헛신호 비율
  (4) 상태 — 가속 + / − 두 묶음의 12개월 초과수익 차이, 연속값 순위상관(IC)
  나눠 보기 — 수주 업종(산업_섹터.ORDER_DRIVEN: 조선 · 방산 · 전력기기 · 건설 · 기계) / 나머지, 앞(~2019) / 뒤(2020~)

재무는 캐시만 읽는다(네트워크 없음). 금융 · 보험 · 지주(KSIC 64~66)는 매출 개념이 달라 뺀다.
한계 — 지금 상장된 회사만(생존 편향: 수익률 수준은 부풀어 있고, 기준끼리 견주는 차이는 덜 휜다), 재무는 그 분기 보고서 값,
       분기 전년 대비가 기저가 거의 0인 분기에선 수천 %로 튄다(그대로 둔다 — 그 소음도 기준의 성질이다).

실행: python 도구/가속기준_백테스트.py           (처음엔 재무 캐시를 8 프로세스로 읽어 .cache/druck_bt/bt_series.json 을 만든다 — 약 15분.
                                                 그 뒤엔 그 파일로 표만 다시 낸다. 재무를 새로 읽으려면 --rebuild)
결과: 표준출력 + .cache/druck_bt/bt_accel_abc.json (A/B/C 비교 — 화면이 읽는 bt_accel.json 은 --from-cache 만 쓴다)

--from-cache (2026-10-10, 가속도 개편 6) — 위 A/B/C 비교 대신 가속도 탭이 쓰는 druck 캐시(v = 드러켄밀러.VERSION)의 점을 그대로 표본으로 쓴다.
  B · 7국면 · 변곡(띠를 건너는 규칙)이 화면과 같은 값이다. 들어가는 날 = 그 숫자를 알 수 있던 날(B기준일) 다음 거래일 종가.
  기저율 표본 = 재작성 비교값으로 센 행(품질 asfiled · mix 아님)이고 B기준일 − 원본 공시일 ≤ 45일인 행. 나머지는 'asfiled' 한 줄로만 따로 낸다.
  결과: .cache/druck_bt/bt_accel.json(산업 '섹터 안 종목' · 가속도 탭 기저율) · .cache/druck_bt/events.json(회사별 변곡 · 보고서 구간 시장 대비).
  64비트 파이썬으로 돌린다(py -3.13 — 서버 모듈 + 전 종목 주가를 한 번에 올린다). 뷰어가 매일 밤 미리 계산 뒤 부른다(서버 _druck_prebuild).
"""
import os
import sys
import json
import time
import datetime as dt
import statistics as st
import importlib.util as ilu
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
OUT = os.path.join(BASE, ".cache", "druck_bt")
SERIES = os.path.join(OUT, "bt_series.json")
YEARS = list(range(2011, dt.date.today().year + 1))
T0, T1 = "20120101", dt.date.today().strftime("%Y%m%d")
LAG_MAX = 45          # 일 — B기준일(숫자를 알 수 있던 날)이 원본 공시일보다 이만큼 넘게 늦으면(정정본 값) 기저율 표본에서 뺀다
PHASES = ("확장 가속", "확장 유지", "둔화", "회복", "부진 지속", "수축 심화", "정체")     # 드러켄밀러.phase_label 의 7국면
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
            t1 = W.next_day(code, t)       # 공시 다음 거래일 종가(달력 +1일이면 금요일 공시가 그날 종가로 샀다)

            def ex(days):
                if t1 is None:
                    return None
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
    _dump(rep, "bt_accel_abc.json")      # 화면이 읽는 bt_accel.json(--from-cache, 띠를 건너는 변곡)을 옛 규칙 표로 덮지 않게 따로


# ---------------------------------------------------------------- --from-cache — druck 캐시(v2)로 기저율 · 사건 파일
def _dump(obj, name):
    """OUT/name 에 원자 쓰기(.tmp → replace) — 서버가 mtime 을 보고 읽다가 반쯤 쓴 파일을 만나지 않게. 읽는 쪽이 열고 있으면 몇 번 다시."""
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, default=str)
    for i in range(10):
        try:
            os.replace(tmp, path)
            return path
        except PermissionError:
            time.sleep(0.5)
    raise PermissionError("못 바꿈: " + path)


def _days(a, b):
    """YYYYMMDD a → b 날 수(b − a)."""
    return (dt.datetime.strptime(b[:8], "%Y%m%d") - dt.datetime.strptime(a[:8], "%Y%m%d")).days


def point_rows(points, filed):
    """druck 캐시 점 → 패널 행(회사 몫, 주가 빼고). 가속B 와 날짜(B기준일, 없으면 기준일)가 있는 점만.
    filed = {n: 원본 정기보고서 공시일}(드러켄밀러.filed_meta) — filed0 = 그 분기의 원본 공시일, lag = 날짜 − filed0(일, filed0 없으면 None).
    dG2 · dG4 = 2 · 4분기 뒤 TTM 매출 증가율 − 지금 TTM 매출 증가율(%p). g(n) = 매출_TTM(n) ÷ 매출_TTM(n−4) − 1 — 순번이 아니라 분기 키로 찾는다."""
    by = {p["n"]: p for p in points}

    def g(n):
        a, b = (by.get(n - 4) or {}).get("매출_TTM"), (by.get(n) or {}).get("매출_TTM")
        return (b / a - 1) * 100 if a and b is not None and a > 0 else None

    def d(h, k):
        a, b = g(h), g(k)
        return a - b if a is not None and b is not None else None
    out = []
    for p in points:
        t = p.get("B기준일") or p.get("기준일")
        if not t or p.get("가속B") is None:
            continue
        n, q = p["n"], p.get("품질") or []
        f0 = filed.get(n)
        out.append({"n": n, "date": t, "t": t[:6] + "15", "filed0": f0, "lag": _days(f0, t) if f0 else None,
                    "B": p["가속B"], "s": p.get("속도"), "phase": p.get("국면"), "turn": p.get("변곡"),
                    "asfiled": "asfiled" in q or "mix" in q, "g": g(n), "dG2": d(n + 2, n), "dG4": d(n + 4, n)})
    return out


def in_sample(r):
    """기저율 표본 — 재작성 비교값으로 센 B(asfiled · mix 아님)이고, 원본 공시일을 알고, 그날부터 LAG_MAX 일 안에 알 수 있던 행."""
    return not r["asfiled"] and r["lag"] is not None and r["lag"] <= LAG_MAX


def _ex(W, code, t1, days, today=None):
    """t1(들어간 날)부터 days 일 수익률 − 같은 기간 전 종목 중앙값. 아직 그 날이 안 왔으면 None."""
    if t1 is None or W.shift(t1, days) > (today or T1):
        return None
    t2 = W.shift(t1, days)
    a, b = W.ret(code, t1, t2), W.grp_ret("__all__", t1, t2)
    return a - b if a is not None and b is not None else None


def periods(W, code, filed, today=None):
    """보고서 구간 — 원본 정기보고서 공시일을 분기 순서로 늘어놓고 (d, 다음 d2) 마다 next_day(d) → next_day(d2) 수익률 − 전 종목 중앙값.
    마지막 보고서(d2 없음) · d2 가 오늘 뒤 · d2 가 그 회사 마지막 시세 날 이후(다음 거래일 시세가 아직 없음)면 오늘까지 잰 값과 '진행 중'.
    상장 전 · 거래정지처럼 시세가 비어 못 재는 지난 구간은 ex None · 'done'."""
    today = today or T1
    ks = (W.PX.get(code) or ((), ()))[0]
    last = ks[-1] if ks else None
    ns = sorted(filed)
    out = []
    for i, n in enumerate(ns):
        d = filed[n]
        d2 = filed[ns[i + 1]] if i + 1 < len(ns) else None
        t0 = W.next_day(code, d)
        t1 = W.next_day(code, d2) if d2 and d2 <= today else None
        live = d2 is None or d2 > today or (t1 is None and last is not None and d2 >= last)
        end = today if live else t1
        ex = None
        if t0 is not None and end is not None and end > t0:
            a, b = W.ret(code, t0, end), W.grp_ret("__all__", t0, end)
            ex = a - b if a is not None and b is not None else None
        out.append({"n": n, "d": d, "d2": d2, "ex": ex, "state": "진행 중" if live else "done"})
    return out


def panel_cache(W, S, SEC):
    """druck 캐시(v=VERSION)의 점으로 패널. 금융 · 지주(KSIC 64~66, OVERRIDE 아님)와 영업이익 기준 회사는 기저율 표본에서 빼되 events 에는 넣는다.
    돌려주는 것 (rows, events, 버전이 달라 건너뛴 캐시 수). 보고서 구간(periods)은 캐시가 없는 회사도 색인 · 주가만으로 낸다."""
    sp = ilu.spec_from_file_location("드러켄밀러", os.path.join(BASE, "드러켄밀러.py"))
    DRK = ilu.module_from_spec(sp); sp.loader.exec_module(DRK)
    with open(os.path.join(BASE, ".cache", "거시", "induty.json"), encoding="utf-8") as fh:
        ksic = json.load(fh)
    rows, skipped, ev = [], 0, {}
    for c in S.INDEX["companies"]:
        code = c.get("code")
        if not code:
            continue
        corp = S.corp_code_of(code)
        filed = DRK.filed_meta(c["reports"])["filed"]
        evc = {"turns": [], "periods": periods(W, code, filed)}
        path = os.path.join(BASE, ".cache", "druck", "%s.json" % code)
        d = DRK.read_cache(path) if os.path.exists(path) else None
        if d is None and os.path.exists(path):
            skipped += 1                          # 옛 버전 · 깨진 파일 — 밤 미리 계산이 다시 쌓을 대상
        if d is not None:
            k = str(ksic.get(corp) or "")
            fin = d.get("basis") == "영업이익" or (k.startswith(SEC.FIN_KSIC) and code not in SEC.OVERRIDE)
            sec = SEC.sector_of(code, k)[0]
            for r in point_rows(d.get("points") or [], filed):
                t1 = W.next_day(code, r["date"])       # 그 숫자를 알 수 있던 날 다음 거래일 종가
                r.update(code=code, sec=sec, order=sec in ORDER, ex6=_ex(W, code, t1, 182), ex12=_ex(W, code, t1, 365))
                if r["turn"]:
                    evc["turns"].append({"n": r["n"], "dir": r["turn"], "date": r["date"], "ex6": r["ex6"], "ex12": r["ex12"],
                                         "state": "진행 중" if W.shift(t1 or r["date"], 365) > T1 else "done"})
                if not fin:
                    rows.append(r)
        if evc["turns"] or evc["periods"]:
            ev[code] = evc
    return rows, ev, skipped


def whip_turns(rows, sample):
    """sample 의 변곡마다 같은 회사에서 2분기 안에 반대 변곡이 났나(헛신호). 반대 변곡은 표본 밖 행(asfiled 등)에서 나도 센다 — 화면에 보인 신호가 뒤집혔다는 사실이므로."""
    by = {}
    for r in rows:
        if r["turn"]:
            by.setdefault(r["code"], {})[r["n"]] = r["turn"]
    hit = tot = 0
    for r in sample:
        if not r["turn"]:
            continue
        tot += 1
        opp = "▼" if r["turn"] == "▲" else "▲"
        hit += any((by.get(r["code"]) or {}).get(r["n"] + k) == opp for k in (1, 2))
    return (hit / tot * 100 if tot else None), tot


def _ev_line(lab, s, w=18):
    if "med" not in s:
        return "%-*s %6d  (표본 부족)" % (w, lab, s["n"])
    return "%-*s %6d %5d %8s %8s %18s %5.0f%% %8s %8s %7s %7s" % (
        w, lab, s["n"], s["firms"], fmt(s["ex6"]), fmt(s["med"]), "[%s, %s]" % (fmt(s["ci"][0]), fmt(s["ci"][1])),
        s["hit"], fmt(s["early"]), fmt(s["late"]), fmt(s["dG2"]), fmt(s["dG4"]))


def _ev_head(w=18):
    return "%-*s %6s %5s %8s %8s %18s %6s %8s %8s %7s %7s" % (
        w, "", "n", "회사", "6개월", "12개월", "12개월 90% 구간", "이긴%", "앞~19", "뒤20~", "TTM+2Q", "TTM+4Q")


def report_cache(W, rows):
    """--from-cache 표 · bt_accel.json. 호환 키(산업 '섹터 안 종목'이 읽는다): ev_all.B_up/B_dn · ev_order.B_up/B_dn · regime.B · whip.B · n · firms · base.
    새 키: phase7(7국면 — 전 종목 · 수주 · 나머지) · turn(변곡 규칙 요약) · asfiled(표본 밖 행 — 섞지 않고 한 줄로) · base_any(아무 분기 12개월 중앙값)."""
    S_ = [r for r in rows if in_sample(r)]
    X = [r for r in rows if not in_sample(r)]
    rep = {"src": "druck 캐시", "at": T1, "lag_max": LAG_MAX, "n": len(S_), "firms": len({r["code"] for r in S_})}
    base12, base6 = med([r["ex12"] for r in S_]), med([r["ex6"] for r in S_])
    rep["base"] = {"ex12": base12, "ex6": base6}
    rep["base_any"] = base12
    print("\n표본 %d 회사-분기 (회사 %d) · 날짜 %s ~ %s · 아무 분기나 12개월 초과수익 중앙값 %s · 6개월 %s"
          % (len(S_), rep["firms"], min((r["date"] for r in S_), default="—"), max((r["date"] for r in S_), default="—"), fmt(base12), fmt(base6)))
    why = {"asfiled": sum(r["asfiled"] for r in X), "lag": sum(not r["asfiled"] and r["lag"] is not None for r in X),
           "nofiled": sum(not r["asfiled"] and r["lag"] is None for r in X)}
    print("표본 밖(섞지 않음) %d — 공시 당시 값 · 섞임 %d, 원본 공시일보다 %d일 넘게 늦게 알 수 있던 값 %d, 원본 공시일 모름 %d"
          % (len(X), why["asfiled"], LAG_MAX, why["lag"], why["nofiled"]))

    def turns(rs):
        sp, ci = spread(W, rs, lambda r: r["turn"] == "▲", lambda r: r["turn"] == "▼")
        return {"B_up": ev_stats(W, [r for r in rs if r["turn"] == "▲"]), "B_dn": ev_stats(W, [r for r in rs if r["turn"] == "▼"]),
                "B_spread": {"diff": sp, "ci": list(ci)}}
    order, other = [r for r in S_ if r["order"]], [r for r in S_ if not r["order"]]
    rep["ev_all"], rep["ev_order"], rep["ev_other"] = turns(S_), turns(order), turns(other)
    w, tot = whip_turns(rows, S_)
    rep["whip"] = {"B": {"pct": w, "n": tot}}
    xa = {"n": len(X), "firms": len({r["code"] for r in X}), "why": why,
          "base": {"ex12": med([r["ex12"] for r in X]), "ex6": med([r["ex6"] for r in X])}}
    xa.update(turns(X))
    rep["asfiled"] = xa
    rep["turn"] = {"rule": "|B| ≥ %.0f%%p 이고, 그 앞 가장 가까운 |B| ≥ %.0f%%p 분기(4분기 안)가 반대 부호" % (3.0, 3.0),
                   "up": rep["ev_all"]["B_up"], "dn": rep["ev_all"]["B_dn"], "spread": rep["ev_all"]["B_spread"], "whip": rep["whip"]["B"],
                   "order": rep["ev_order"], "other": rep["ev_other"]}

    print("\n== 변곡 뒤 — 12개월 시장 대비 (띠 ±3%p 를 건너 반대쪽으로 넘어온 분기)")
    print(_ev_head())
    for title, t in (("전 종목", rep["ev_all"]), ("수주 업종", rep["ev_order"]), ("수주 업종 밖", rep["ev_other"]), ("표본 밖(asfiled 등)", xa)):
        print(_ev_line(title + " ▲", t["B_up"]))
        print(_ev_line(title + " ▼", t["B_dn"]))
        sp = t["B_spread"]
        print("%-18s ▲−▼ 12개월 %s [%s, %s]" % (title, fmt(sp["diff"]), fmt(sp["ci"][0]), fmt(sp["ci"][1])))
    print("헛신호 — 변곡 뒤 2분기 안에 반대 변곡 %s%% (변곡 %d번)" % ("—" if w is None else "%.1f" % w, tot))

    cells = {}
    rep["phase7"] = {"labels": list(PHASES)}
    print("\n== 7국면 — 그 분기 국면별 12개월 시장 대비 · 4분기 뒤 TTM 성장 변화")
    print(_ev_head())
    for key, rs in (("all", S_), ("order", order), ("other", other)):
        tab = {lab: ev_stats(W, [r for r in rs if r["phase"] == lab]) for lab in PHASES}
        rep["phase7"][key] = tab
        if key == "all":
            cells = tab
            for lab in PHASES:
                print(_ev_line(lab, tab[lab]))
    rep["regime"] = {"B": cells}
    ic12 = W.ic_stats([r for r in S_ if r.get("ex12") is not None], lambda r: r["B"], "ex12", 12)
    ic6 = W.ic_stats([r for r in S_ if r.get("ex6") is not None], lambda r: r["B"], "ex6", 6)
    rep["state"] = {"B": {"ic12": ic12, "ic6": ic6}}
    print("\nB 연속값 IC — 12개월 %s (t %s) · 6개월 %s (t %s)" % (
        fmt(ic12 and ic12["ic"], 3), fmt(ic12 and ic12["t"], 2), fmt(ic6 and ic6["ic"], 3), fmt(ic6 and ic6["t"], 2)))
    _dump(rep, "bt_accel.json")
    return rep


ORDER = ()

if __name__ == "__main__":
    sp = ilu.spec_from_file_location("wb", os.path.join(HERE, "억울_백테스트.py"))
    W = ilu.module_from_spec(sp)
    sp.loader.exec_module(W)
    sp = ilu.spec_from_file_location("산업_섹터", os.path.join(BASE, "산업_섹터.py"))
    SEC = ilu.module_from_spec(sp)
    sp.loader.exec_module(SEC)
    ORDER = SEC.ORDER_DRIVEN
    if "--from-cache" in sys.argv:
        t0 = time.time()
        print("파이썬 %s (%d비트) · 주가 %d 종목 · 색인 회사 %d" % (sys.version.split()[0], 64 if sys.maxsize > 2 ** 32 else 32, len(W.PX),
                                                       len(W.S.INDEX["companies"])), flush=True)
        rows, ev, skipped = panel_cache(W, W.S, SEC)
        print("druck 캐시 행 %d (회사 %d) · 사건 파일 회사 %d (변곡 %d · 보고서 구간 %d)" % (
            len(rows), len({r["code"] for r in rows}), len(ev), sum(len(v["turns"]) for v in ev.values()),
            sum(len(v["periods"]) for v in ev.values())), flush=True)
        report_cache(W, rows)
        _dump(ev, "events.json")
        print("버전 다른 캐시 건너뜀 %d" % skipped)
        print("끝 %.0f초" % (time.time() - t0))
        sys.exit(0)
    if "--rebuild" in sys.argv or not os.path.exists(SERIES):
        ser = build_series(W.S, SEC)
    else:
        ser = json.load(open(SERIES, encoding="utf-8"))
    print("시계열 %d 회사" % len(ser), flush=True)
    rows = panel(W, ser)
    report(W, rows)

# -*- coding: utf-8 -*-
"""
차트 셋업(저평가V2 셋업 카드)이 과거에 맞았나 (2026-10-07)

매달 말(2012-01 ~ 2026-08)마다 그날까지의 봉만으로 기술.setup() 을 다시 재고, 그날 전 종목 순위로 RS(1~99)를 매긴 뒤
기술.PRESETS 규칙(화면과 같은 함수)을 그대로 돌린다. 실적 모멘텀은 그날까지 공시된 분기 EPS 만 쓴다(공시일 기준).
  결과 — 다음 날부터 1 · 3 · 6 · 12개월 수익률 − 같은 기간 전 종목 수익률 중앙값(초과수익)
  통계 — 셋업마다 중앙값 · 이긴 비율 · 회사 단위 부트스트랩 90% 구간 · 앞(~2019) / 뒤(2020~)
  참고 — 'RS 70↑ 전체'(패턴 없이 강한 종목만)와 견줘 패턴이 더한 몫을 본다. 경고 표시(고점 대량 음봉 등)는 켜짐 − 꺼짐.
  범위 — 전 종목 · 저평가 후보 · 저평가 등급(그달 말 기준 120일 안 마지막 공시일의 등급 — 도구/저평가_백테스트.py 표본 ·
         score.json 과 같은 규칙, 저평가V2_백테스트.tier_of 와 같다). 저평가V2 의 본뜻 '싼데 차트도 좋은 자리'를 여기서 잰다.
목표가 상향은 리포트가 2025-10 부터만 있어 재지 않는다.

시세 = .cache/ohlcv(네이버 수정주가 일봉, 재무.fetch_ohlcv). 재무는 캐시만 읽는다(네트워크 없음).
한계 — 지금 상장된 회사만(생존 편향: 수준은 부풀어 있다. 셋업끼리 · RS 70↑ 전체와의 비교가 덜 휜다),
       같은 종목이 여러 달 연달아 걸리면 표본이 겹친다(구간은 회사 단위로 다시 뽑아 그 겹침을 감안).

실행: python 도구/차트셋업_백테스트.py           (처음엔 분기 EPS 를 8 프로세스로 읽어 .cache/value/v3_eps.json — 약 15분)
      python 도구/차트셋업_백테스트.py --rebuild (EPS 를 새로 읽음)
      python 도구/차트셋업_백테스트.py --report  (저장한 표본으로 표만 — 몇 초)
결과: 표준출력 + .cache/value/v3_report.json(서버 · 화면이 읽는다) + v3_panel.json(종목-달 표본)
"""
import os
import sys
import json
import bisect
import datetime as dt
import statistics as st
import importlib.util as ilu
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
OUT = os.path.join(BASE, ".cache", "value")
OHLCV = os.path.join(BASE, ".cache", "ohlcv")
EPS_PATH = os.path.join(OUT, "v3_eps.json")
H = {"ex1m": 30, "ex3m": 91, "ex6m": 182, "ex12m": 365}


def month_ends(a, b):
    y, m = a
    out = []
    while (y, m) <= b:
        nx = dt.date(y + (m == 12), m % 12 + 1, 1)
        out.append((nx - dt.timedelta(days=1)).strftime("%Y%m%d"))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


DATES = month_ends((2012, 1), (2026, 8))

# ---------------------------------------------------------------- 작업자 — 종목 하나의 달마다 셋업
T = None
DRK = None


def _init_tech():
    global T
    sp = ilu.spec_from_file_location("기술", os.path.join(BASE, "기술.py"))
    T = ilu.module_from_spec(sp)
    sp.loader.exec_module(T)


def _slim(x):
    """패턴 묶음에서 규칙 · 통계에 쓰는 것만(점 · 선은 뺀다)."""
    out = {k: x.get(k) for k in ("rs_raw", "rs1_raw", "tt7", "ma50", "warn")}
    for k, _ in T.PATTERNS:
        p = x.get(k)
        out[k] = {kk: vv for kk, vv in p.items() if kk not in ("pts", "line", "deps")} if p else None
    return out


def _one(code):
    try:
        B = T.bars_from(json.load(open(os.path.join(OHLCV, code + ".json"), encoding="utf-8")), min_n=21)
    except Exception:
        return code, []
    if not B:
        return code, []
    T.prep(B)
    rows = []
    for t in DATES:
        i = bisect.bisect_right(B["d"], int(t)) - 1
        if i < 20 or (dt.datetime.strptime(t, "%Y%m%d") - dt.datetime.strptime(str(B["d"][i]), "%Y%m%d")).days > 10:
            continue
        x = T.setup(B, i)
        if x:
            rows.append((t, _slim(x)))
    return code, rows


def _init_drk():
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


def _eps(job):
    code, corp = job
    try:
        pts = DRK.series(corp, code, list(range(2010, 2027)))
    except Exception:
        return code, None
    return code, [[p["year"] * 4 + p["q"] - 1, p.get("EPS"), p.get("매출액")] for p in pts if p.get("EPS") is not None]


# ---------------------------------------------------------------- 분기 EPS — 공시일 기준
def build_eps(S):
    jobs, filed = [], {}
    for c in S.INDEX["companies"]:
        corp = S.corp_code_of(c["code"])
        if not corp:
            continue
        f = {}
        for r in c["reports"]:
            y, m = r["stamp"].split("-")
            if not r["tag"] and m in S.Q_OF_MONTH:
                n = int(y) * 4 + S.Q_OF_MONTH[m] - 1
                f[n] = min(f.get(n, "99999999"), r["rcept"][:8])
        filed[c["code"]] = f
        jobs.append((c["code"], corp))
    print("분기 EPS 읽는 중 — 회사 %d" % len(jobs), flush=True)
    out = {}
    with Pool(8, initializer=_init_drk) as pool:
        for k, (code, pts) in enumerate(pool.imap_unordered(_eps, jobs, chunksize=4), 1):
            if pts:
                out[code] = {"filed": filed[code], "eps": pts}
            if k % 100 == 0:
                print("  %d/%d" % (k, len(jobs)), flush=True)
    json.dump(out, open(EPS_PATH, "w", encoding="utf-8"), ensure_ascii=False)
    return out


def eps_at(E, t):
    """그날까지 공시된 마지막 분기의 EPS 전년 같은 분기 대비(%) — 기준 EPS 가 0 이하이거나 150일 넘게 묵었으면 None."""
    if not E:
        return None
    eq = {int(n): e for n, e, _ in E["eps"]}
    best = None
    for n, d in E["filed"].items():
        if d <= t and (best is None or int(n) > best[0]):
            best = (int(n), d)
    if not best or (dt.datetime.strptime(t, "%Y%m%d") - dt.datetime.strptime(best[1], "%Y%m%d")).days > 150:
        return None
    a, b = eq.get(best[0] - 4), eq.get(best[0])
    return (b / a - 1) * 100 if a and b is not None and a > 0 else None


# ---------------------------------------------------------------- 통계
def med(v):
    v = [x for x in v if x is not None]
    return st.median(v) if v else None


def stats(W, rs):
    out = {"n": len(rs), "firms": len({r["code"] for r in rs}), "months": len({r["t"] for r in rs})}
    for y in H:
        out[y] = med([r.get(y) for r in rs])
    for y in ("ex6m", "ex12m"):
        sub = [r for r in rs if r.get(y) is not None]
        if len(sub) >= 20:
            out["hit_" + y] = sum(r[y] > 0 for r in sub) / len(sub) * 100
            out["ci_" + y] = list(W.boot(sub, lambda x, y=y: med([r[y] for r in x]), n=400))
            out["early_" + y] = med([r[y] for r in sub if r["t"] < W.SPLIT])
            out["late_" + y] = med([r[y] for r in sub if r["t"] >= W.SPLIT])
    return out


def fmt(v, d=1):
    return "—" if v is None else "%+.*f" % (d, v)


def load_v():
    """저평가_백테스트(V) — 안에서 억울_백테스트(W) · 서버(S)를 한 번만 읽는다."""
    _argv, sys.argv = sys.argv, ["x"]
    sp = ilu.spec_from_file_location("vb", os.path.join(HERE, "저평가_백테스트.py"))
    V = ilu.module_from_spec(sp)
    sp.loader.exec_module(V)
    sys.argv = _argv
    return V


def tier_line(V):
    """종목마다 [(공시일, 등급 또는 None)] — 저평가V2_백테스트.tier_of 와 같은 규칙. 다만 점수 백분위의 바탕(dist)은
    score.json(2013~2025 후보 전체 — 미래 포함)이 아니라 그 공시일 '앞' 후보들만으로 그때그때 쌓는다(항목마다 100개 모이기 전엔 점수 없음 → 관찰).
    점수 항목 · 가중치 자체는 같은 기간을 보고 골랐다 — '저평가 등급' 범위의 한계로 남는다."""
    P = sorted(json.load(open(os.path.join(OUT, "bt_panel.json"), encoding="utf-8")), key=lambda r: r["date"])
    fx = {k: f for k, _, f in V.FACT}
    dist = {k: [] for k, *_ in V.SCORE}
    pend, by = [], {}
    for r in P:
        while pend and pend[0][0] < r["date"]:            # 앞선 공시일 후보부터 바탕에 넣는다(같은 날 것끼리는 서로 안 본다)
            for k, x in pend.pop(0)[1]:
                bisect.insort(dist[k], x)
        t = None
        if V.cand(r):
            sc = V.score(r, {k: v for k, v in dist.items() if len(v) >= 100}, V.SCORE)
            heavy = r.get("debt_eq") is not None and r["debt_eq"] >= 200
            t = "저평가" if (sc is not None and sc >= 50 and not V.red(r) and not heavy) else "관찰"
            pend.append((r["date"], [(k, fx[k](r)) for k in dist if fx[k](r) is not None]))
        by.setdefault(r["code"], []).append((r["date"], t or ""))
    for v in by.values():
        v.sort()
    return by


def tier_at(line, t):
    """그달 말 등급 — 그날까지 공시된 마지막 보고서(120일 안)의 등급. 없으면 None."""
    if not line:
        return None
    k = bisect.bisect_right([d for d, _ in line], t) - 1
    if k < 0 or (dt.datetime.strptime(t, "%Y%m%d") - dt.datetime.strptime(line[k][0], "%Y%m%d")).days > 120:
        return None
    return line[k][1] or None


def build(V):
    W, S = V.W, V.S
    os.makedirs(OUT, exist_ok=True)
    E = build_eps(S) if ("--rebuild" in sys.argv or not os.path.exists(EPS_PATH)) else json.load(open(EPS_PATH, encoding="utf-8"))
    TL = tier_line(V)
    codes = sorted(f[:-5] for f in os.listdir(OHLCV) if f.endswith(".json"))
    print("셋업 재는 중 — 종목 %d · 달 %d" % (len(codes), len(DATES)), flush=True)
    by_t = {}
    with Pool(8, initializer=_init_tech) as pool:
        for k, (code, rows) in enumerate(pool.imap_unordered(_one, codes, chunksize=8), 1):
            for t, x in rows:
                x["code"], x["t"] = code, t
                by_t.setdefault(t, []).append(x)
            if k % 100 == 0:
                print("  %d/%d" % (k, len(codes)), flush=True)
    panel = []
    for t, xs in sorted(by_t.items()):
        rk = T.rank99({x["code"]: x["rs_raw"] for x in xs})
        r1 = T.rank99({x["code"]: x["rs1_raw"] for x in xs})
        for x in xs:
            x["rs"], x["rs1"] = rk.get(x["code"]), r1.get(x["code"])
            x["fund"] = {"eps_yoy": eps_at(E.get(x["code"]), t)}
            x["sets"] = [k for k, _, _, fn, _ in T.PRESETS if k != "tp" and fn(x)]
            x["tier"] = tier_at(TL.get(x["code"]), t)
            # 들어가는 날 = 그달 말 '다음 거래일' 종가(달 말이 금 · 토 · 연말이면 +1일이 휴장이라 신호 봉 종가로 사게 된다)
            ks = W.PX.get(x["code"], ((), ()))[0]
            j = bisect.bisect_right(ks, t)
            t1 = ks[j] if j < len(ks) else None
            for y, days in H.items():
                if t1 is None:
                    x[y] = None
                    continue
                a = W.ret(x["code"], t1, W.shift(t1, days))
                b = W.grp_ret("__all__", t1, W.shift(t1, days))
                x[y] = a - b if a is not None and b is not None else None
            panel.append({k: x.get(k) for k in ("code", "t", "sets", "warn", "rs", "rs1", "tier", *H)})
    json.dump(panel, open(os.path.join(OUT, "v3_panel.json"), "w", encoding="utf-8"), ensure_ascii=False)
    return panel


def report(W, panel):
    print("\n표본 %d 종목-달 · 종목 %d · %s ~ %s" % (len(panel), len({x["code"] for x in panel}), DATES[0], DATES[-1]))
    rep = {"made": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "n": len(panel), "firms": len({x["code"] for x in panel}),
           "dates": [DATES[0], DATES[-1]], "presets": {}, "scopes": {}, "noext": {}, "ref": {}, "warn": {}}

    def line(name, s):
        print("%-16s %7d %5d %7s %7s %7s %7s %18s %5.0f%% %8s %8s" % (
            name, s["n"], s["firms"], fmt(s["ex1m"]), fmt(s["ex3m"]), fmt(s["ex6m"]), fmt(s["ex12m"]),
            "[%s, %s]" % (fmt((s.get("ci_ex6m") or [None])[0]), fmt((s.get("ci_ex6m") or [None, None])[1])),
            s.get("hit_ex6m") or 0, fmt(s.get("early_ex6m")), fmt(s.get("late_ex6m"))))
    head = "%-16s %7s %5s %7s %7s %7s %7s %18s %6s %8s %8s" % ("셋업", "종목-달", "회사", "1개월", "3개월", "6개월", "12개월",
                                                             "6개월 90% 구간", "이긴%", "~2019", "2020~")
    for scope, lab, fn in (("all", "전 종목", lambda x: True), ("cand", "저평가 후보", lambda x: bool(x.get("tier"))),
                           ("tier", "저평가 등급", lambda x: x.get("tier") == "저평가")):
        sub = [x for x in panel if fn(x)]
        print("\n== %s (종목-달 %d)" % (lab, len(sub)))
        print(head)
        out = rep["presets"] if scope == "all" else rep["scopes"].setdefault(scope, {})
        if scope != "all":
            s = stats(W, sub)
            rep["scopes"][scope + "_base"] = s
            line("(%s 전체)" % lab, s)
        for k, nm, _, _, _ in T.PRESETS:
            if k == "tp":
                continue
            rs = [x for x in sub if k in (x.get("sets") or [])]
            if len(rs) < 20:
                out[k] = {"n": len(rs)}
                print("%-16s %7d  (표본 부족)" % (nm, len(rs)))
                continue
            out[k] = stats(W, rs)
            line(nm, out[k])
    print("\n== 전 종목 · '50일선 +25%↑(추격 위험)' 뺀 셋업")
    for k, nm, _, _, _ in T.PRESETS:
        rs = [x for x in panel if k in (x.get("sets") or []) and "ext" not in (x.get("warn") or [])]
        if k != "tp" and len(rs) >= 20:
            rep["noext"][k] = stats(W, rs)
            line(nm, rep["noext"][k])
    print("\n== 참고")
    for nm, fn in (("RS 70↑ 전체", lambda x: (x.get("rs") or 0) >= 70), ("RS 80↑ 전체", lambda x: (x.get("rs") or 0) >= 80),
                   ("셋업 하나라도", lambda x: bool(x.get("sets")))):
        s = stats(W, [x for x in panel if fn(x)])
        rep["ref"][nm] = s
        line(nm, s)
    print("\n== 경고 — 셋업에 걸린 종목-달 안에서 경고 켜짐 − 꺼짐 (6 · 12개월 초과수익 중앙값)")
    on_set = [x for x in panel if x.get("sets")]
    for k, nm in T.WARN.items():
        a = [x for x in on_set if k in (x.get("warn") or [])]
        b = [x for x in on_set if k not in (x.get("warn") or [])]
        d6 = (med([x["ex6m"] for x in a]) or 0) - (med([x["ex6m"] for x in b]) or 0) if a and b else None
        d12 = (med([x["ex12m"] for x in a]) or 0) - (med([x["ex12m"] for x in b]) or 0) if a and b else None
        rep["warn"][k] = {"n": len(a), "d6": d6, "d12": d12}
        print("%-26s n %6d · 6개월 %s · 12개월 %s" % (nm, len(a), fmt(d6), fmt(d12)))
    json.dump(rep, open(os.path.join(OUT, "v3_report.json"), "w", encoding="utf-8"), ensure_ascii=False, default=str)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    V_ = load_v()
    _init_tech()
    if "--report" in sys.argv:
        report(V_.W, json.load(open(os.path.join(OUT, "v3_panel.json"), encoding="utf-8")))
    else:
        report(V_.W, build(V_))

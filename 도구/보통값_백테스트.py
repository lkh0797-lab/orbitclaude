# -*- coding: utf-8 -*-
"""
'보통 값'(최근 4분기 주당이익 × 이 회사 자기 역사 PER 중앙값)이 '가치 대비 싸다'의 기준이 되나 (2026-10-16)

풍경 탭(서버._landscape_build)의 정의
  분기 PER = 분기 말 종가 ÷ 최근 4분기 EPS(0.5~300 배만) · band = 15년 분기 PER 의 25 · 50 · 75% 자리(싼 값 · 보통 값 · 비싼 값)
  가치 온도계 = 지금 PER 이 그 PER 들 가운데 몇 % 자리인가(pct_now) → 싸다 ≤25 · 비싸다 ≥75
표본: 도구/저평가_백테스트.py 가 만든 .cache/value/bt_panel.json(보고서 공시일마다 · 그때까지 나온 숫자로).
  per = 공시일 보정 종가 ÷ 최근 4분기 EPS, per_pct = 그 분기 전 분기 말 PER(최근 40분기, 8개↑)들 사이 자리(도구/분기변화_백테스트.py),
  ex6m · ex12m = 공시 다음 거래일 종가부터 6 · 12개월 수익 − 같은 기간 전 종목 중앙값(초과수익).
이 도구가 패널 위에 시점 기준으로 더 만든다(그 줄의 date 까지 알 수 있던 것 — 같은 회사의 앞 분기 줄들만):
  per_q    = 그 분기 말 PER(= per × 분기 말 종가 ÷ 공시일 종가, .cache/price) — 풍경이 쓰는 분기 PER 과 같은 꼴
  per_med  = 앞 분기들의 per_q(0.5~300) 중앙값(8개↑) → 보통 값 괴리 gap = per ÷ per_med − 1
  pct_land = 앞 분기 전부(확장 창) per_q 사이 지금 per 의 자리(풍경 근사 — 자료가 2014~ 라 15년 창은 못 만든다)
  pct20    = 최근 20분기(5년) 창 · pct_norm = 3년 평균 이익(4분기 합 순이익 t · t−4 · t−8 평균)으로 바꾼 PER 의 자리
  pct_pbr  = PBR(= PER × ROE ÷ 100 — 흑자 줄만) 자기 역사 자리 · cv = 최근 12분기 4분기 합 순이익의 변동계수
사전 등록(결과 보기 전에 정함) — H1: per_pct < 25(싼 구간) 가 per_pct > 75(비싼 구간)보다 ex12m 이 높다.
  판정: 중앙값 차(싼 − 비싼)가 앞(~2019) · 뒤(2020~) 둘 다 양수이고, 회사 단위 부트스트랩 90% 구간이 전체에서 0 위면 '기준이 된다'.
보조(판정에 안 씀): (a) gap 날짜 안 5분위 · 순위상관 IC (b) 되돌림(gap_t → gap_t+4)과 그 길(주가 · 이익) (c) 이익 꾸준 vs 출렁
  (d) 업종 빼기 · 해마다 (e) 대안 정의(풍경 근사 확장 창 · 5년 · 정규화 이익 · PBR) (f) 참고 — 횡단 PER(같은 날짜 다른 회사)과 견줌.
한계 — 지금 상장된 회사만(생존 편향), 재무는 나중 정정값일 수 있다, 주식 수 변화는 정규화 EPS · PBR 근사에 빠져 있다,
       PBR · 정규화는 지금 흑자인 줄만(적자 줄은 시가총액이 없어 못 만든다). 네트워크 없음(캐시만 읽는다).

실행: python -X utf8 도구/보통값_백테스트.py [--out 폴더] [--boot 1000]
결과: 표준출력 + (--out 이 있으면) 폴더/report.json · report.md
"""
import os
import sys
import json
import math
import bisect
import random
import argparse
import datetime as dt
import statistics as st

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, ".cache")
PANEL = os.path.join(CACHE, "value", "bt_panel.json")
PRICE_DIR = os.path.join(CACHE, "price")
SECTOR = os.path.join(CACHE, "업종", "map.json")
SPLIT = "20200101"          # 앞(~2019) / 뒤(2020~)
LO, HI = 0.5, 300.0         # 풍경과 같은 PER 거름
MIN_HIST = 8
Q_END = {1: "0331", 2: "0630", 3: "0930", 4: "1231"}
YS = ("ex12m", "ex6m")
BK = ("cheap", "mid", "exp")
BK_KO = {"cheap": "싼 구간(<25)", "mid": "보통(25~75)", "exp": "비싼 구간(>75)"}


# ---------------------------------------------------------------- 기초
def qn(lab):
    return int(lab[:4]) * 4 + int(lab[5])


_ORD = {}


def ordn(d):
    d = int(d)
    v = _ORD.get(d)
    if v is None:
        v = _ORD[d] = dt.date(d // 10000, d // 100 % 100, d % 100).toordinal()
    return v


def load_prices(codes):
    PX = {}
    for c in codes:
        try:
            s = json.load(open(os.path.join(PRICE_DIR, c + ".json"), encoding="utf-8"))
        except Exception:
            continue
        if s:
            ks = sorted(s)
            PX[c] = ([int(k) for k in ks], [s[k] for k in ks])
    return PX


def px_on(PX, code, d, stale):
    ks, vs = PX.get(code, ((), ()))
    d = int(d)
    i = bisect.bisect_right(ks, d) - 1
    if i < 0 or ordn(d) - ordn(ks[i]) > stale or not vs[i]:
        return None
    return vs[i]


def land_q(vals, q):
    """서버._land_q 와 같은 보간 분위."""
    s = sorted(vals)
    if not s:
        return None
    k = (len(s) - 1) * q
    i = int(k)
    return s[i] + (s[min(i + 1, len(s) - 1)] - s[i]) * (k - i)


def pct_of(hist, v):
    """서버._land_pct 와 같은 자리(지금 값은 분모 밖)."""
    if v is None or len(hist) < MIN_HIST:
        return None
    return sum(1 for x in hist if x <= v) / len(hist) * 100


def bucket(p):
    if p is None:
        return None
    return "cheap" if p < 25 else "exp" if p > 75 else "mid"


def med(v):
    v = [x for x in v if x is not None]
    return st.median(v) if v else None


def mean(v):
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None


def rank(v):
    s = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and v[s[j + 1]] == v[s[i]]:
            j += 1
        for k in range(i, j + 1):
            r[s[k]] = (i + j) / 2
        i = j + 1
    return r


def spear(a, b):
    p = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(p) < 8:
        return None
    x, y = zip(*p)
    rx, ry = rank(list(x)), rank(list(y))
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((i - mx) * (j - my) for i, j in zip(rx, ry))
    den = math.sqrt(sum((i - mx) ** 2 for i in rx) * sum((j - my) ** 2 for j in ry))
    return num / den if den else None


def boot(rows, fn, n=1000, seed=7):
    """회사 단위 부트스트랩 90% 구간 — 같은 회사가 분기마다 나오고 12개월 창이 겹치는 것을 감안."""
    by = {}
    for r in rows:
        by.setdefault(r["code"], []).append(r)
    firms = sorted(by)
    if not firms:
        return None, None
    rnd = random.Random(seed)
    vals = []
    for _ in range(n):
        sub = []
        for _f in range(len(firms)):
            sub.extend(by[firms[rnd.randrange(len(firms))]])
        v = fn(sub)
        if v is not None:
            vals.append(v)
    vals.sort()
    return (vals[int(len(vals) * .05)], vals[int(len(vals) * .95)]) if vals else (None, None)


def date_rank_pct(rows, key, out_key, min_n=6):
    """같은 날짜(t) 안 순위 백분위(0~100, 동률 가운데) — 표본이 min_n 미만인 날짜는 None."""
    by = {}
    for r in rows:
        r[out_key] = None
        if r.get(key) is not None:
            by.setdefault(r["t"], []).append(r)
    for g in by.values():
        if len(g) < min_n:
            continue
        rk = rank([r[key] for r in g])
        for r, k in zip(g, rk):
            r[out_key] = k / (len(g) - 1) * 100 if len(g) > 1 else 50.0


# ---------------------------------------------------------------- 시점 값 만들기
def enrich(P, PX, SEC):
    by = {}
    for r in P:
        by.setdefault(r["code"], []).append(r)
    for code, rs in by.items():
        rs.sort(key=lambda r: qn(r["lab"]))
        for r in rs:
            r["_qn"] = qn(r["lab"])
            r["sector"] = SEC.get(code.upper()) or "없음"
            per = r.get("per")
            r["per"] = per = per if (per is not None and per > 0) else None
            pd_ = px_on(PX, code, r["date"], 10)
            pq = px_on(PX, code, r["lab"][:4] + Q_END[int(r["lab"][5])], 20)
            r["px_d"] = pd_
            r["per_q"] = per * pq / pd_ if (per and pq and pd_) else None
            roe = r.get("roe")
            r["pbr"] = per * roe / 100 if (per and roe is not None and roe > 0) else None
            r["pbr_q"] = r["per_q"] * roe / 100 if (r["per_q"] and roe is not None and roe > 0) else None
        byq = {r["_qn"]: r for r in rs}
        for r in rs:
            n0, d0 = r["_qn"], r["date"]
            prior = [x for x in rs if x["_qn"] < n0 and x["date"] <= d0]
            h_all = [x["per_q"] for x in prior if x["per_q"] is not None and LO <= x["per_q"] <= HI]
            h40 = [x["per_q"] for x in prior if x["_qn"] >= n0 - 40 and x["per_q"] is not None and LO <= x["per_q"] <= HI]
            h20 = [x["per_q"] for x in prior if x["_qn"] >= n0 - 20 and x["per_q"] is not None and LO <= x["per_q"] <= HI]
            per = r["per"]
            r["n_hist"] = len(h_all)
            r["per_med"] = land_q(h_all, .5) if len(h_all) >= MIN_HIST else None
            r["gap"] = per / r["per_med"] - 1 if (per and r["per_med"]) else None
            r["pct_land"] = pct_of(h_all, per)
            r["pct40"] = pct_of(h40, per)
            r["pct20"] = pct_of(h20, per)
            r["per_med20"] = land_q(h20, .5) if len(h20) >= MIN_HIST else None
            # 정규화 — 3년(t · t−4 · t−8) 4분기 합 순이익 평균. 주식 수 변화는 무시(근사)
            ns = [(byq.get(n0 - k) or {}).get("ni4") for k in (0, 4, 8)]
            ok_ = all(v is not None for v in ns) and all((byq.get(n0 - k) or {}).get("date", "99999999") <= d0 for k in (0, 4, 8))
            m3 = sum(ns) / 3 if ok_ else None
            r["per_norm"] = per * ns[0] / m3 if (per and ok_ and m3 and m3 > 0 and ns[0] and ns[0] > 0) else None
            r["pct_norm"] = pct_of(h_all, r["per_norm"])
            r["gap_norm"] = r["per_norm"] / r["per_med"] - 1 if (r["per_norm"] and r["per_med"]) else None
            hp = [x["pbr_q"] for x in prior if x["pbr_q"] is not None and x["pbr_q"] > 0]
            r["pct_pbr"] = pct_of(hp, r["pbr"])
            # 이익 변동 — 최근 12분기(t−11 ~ t) 4분기 합 순이익
            w = [byq[n0 - k] for k in range(12) if (n0 - k) in byq and byq[n0 - k]["date"] <= d0]
            nv = [x["ni4"] for x in w if x.get("ni4") is not None]
            mu = sum(nv) / len(nv) if len(nv) >= MIN_HIST else None
            r["cv"] = (st.pstdev(nv) / abs(mu)) if (mu is not None and mu != 0) else None
            r["all_pos12"] = (len(nv) >= MIN_HIST and all(v > 0 for v in nv)) if nv else False
            # 구간 이름
            r["b_h1"] = bucket(r.get("per_pct"))
            r["b_land"] = bucket(r["pct_land"])
            r["b_20"] = bucket(r["pct20"])
            r["b_norm"] = bucket(r["pct_norm"])
            r["b_pbr"] = bucket(r["pct_pbr"])
    return by


# ---------------------------------------------------------------- 통계 조각
def desc(sub, y):
    v = [r[y] for r in sub if r.get(y) is not None]
    if not v:
        return {"n": 0}
    e = [r[y] for r in sub if r.get(y) is not None and r["t"] < SPLIT]
    l_ = [r[y] for r in sub if r.get(y) is not None and r["t"] >= SPLIT]
    return {"n": len(v), "firms": len({r["code"] for r in sub if r.get(y) is not None}), "med": st.median(v), "mean": sum(v) / len(v),
            "hit": sum(x > 0 for x in v) / len(v) * 100, "le30": sum(x <= -30 for x in v) / len(v) * 100,
            "n_early": len(e), "med_early": med(e), "n_late": len(l_), "med_late": med(l_)}


def make_diff(key, y, a="cheap", b="exp", fn=st.median, min_n=8):
    def diff(sub):
        x = [r[y] for r in sub if r.get(key) == a and r.get(y) is not None]
        z = [r[y] for r in sub if r.get(key) == b and r.get(y) is not None]
        return fn(x) - fn(z) if len(x) >= min_n and len(z) >= min_n else None
    return diff


def date_matched(rows, key, y, a="cheap", b="exp", min_n=5):
    """날짜(t) 안에서 싼 − 비싼 중앙값 차를 구해 날짜끼리 평균(설명용)."""
    by = {}
    for r in rows:
        if r.get(key) in (a, b) and r.get(y) is not None:
            by.setdefault(r["t"], []).append(r)
    ds = []
    for t, g in sorted(by.items()):
        x = [r[y] for r in g if r[key] == a]
        z = [r[y] for r in g if r[key] == b]
        if len(x) >= min_n and len(z) >= min_n:
            ds.append((t, st.median(x) - st.median(z), min(len(x), len(z))))
    if not ds:
        return None
    return {"n_dates": len(ds), "avg": sum(d for _, d, _ in ds) / len(ds), "pos": sum(d > 0 for _, d, _ in ds) / len(ds) * 100,
            "w_avg": sum(d * w for _, d, w in ds) / sum(w for _, _, w in ds),
            "early": mean([d for t, d, _ in ds if t < SPLIT]), "late": mean([d for t, d, _ in ds if t >= SPLIT])}


def bucket_test(rows, key, y, nboot):
    rs = [r for r in rows if r.get(key) is not None and r.get(y) is not None]
    out = {"key": key, "y": y, "n": len(rs), "firms": len({r["code"] for r in rs}), "b": {b: desc([r for r in rs if r[key] == b], y) for b in BK}}
    d = make_diff(key, y)
    out["diff"] = d(rs)
    out["diff_early"] = d([r for r in rs if r["t"] < SPLIT])
    out["diff_late"] = d([r for r in rs if r["t"] >= SPLIT])
    out["diff_mean"] = make_diff(key, y, fn=lambda v: sum(v) / len(v))(rs)
    for nm, a, b in (("cheap_mid", "cheap", "mid"), ("mid_exp", "mid", "exp")):
        f = make_diff(key, y, a=a, b=b)
        out["diff_" + nm] = {"all": f(rs), "early": f([r for r in rs if r["t"] < SPLIT]), "late": f([r for r in rs if r["t"] >= SPLIT])}
    out["ci"] = list(boot(rs, d, n=nboot)) if nboot else [None, None]
    out["date_matched"] = date_matched(rs, key, y)
    lo = out["ci"][0]
    out["verdict"] = ("기준이 된다" if (out["diff_early"] is not None and out["diff_late"] is not None and lo is not None
                                       and out["diff_early"] > 0 and out["diff_late"] > 0 and lo > 0) else "기준이 못 된다")
    return out


def ic_stats(rows, fx, y, h_months, min_n=10):
    by = {}
    for r in rows:
        if fx(r) is not None and r.get(y) is not None:
            by.setdefault(r["t"], []).append(r)
    ics = []
    for t, g in sorted(by.items()):
        if len(g) < min_n:
            continue
        v = spear([fx(r) for r in g], [r[y] for r in g])
        if v is not None:
            ics.append((t, v, len(g)))
    if len(ics) < 6:
        return None
    vals = [v for _, v, _ in ics]
    m = sum(vals) / len(vals)
    sd = st.pstdev(vals) or 1e-9
    span = (ordn(ics[-1][0]) - ordn(ics[0][0])) / 365.25 or 1
    overlap = max(len(vals) / span * h_months / 12, 1)      # 한 수익 창 안에 든 IC 날짜 수
    n_eff = max(len(vals) / overlap, 1)
    return {"ic": m, "t": m / (sd / math.sqrt(n_eff)), "n_dates": len(vals), "n_eff": n_eff, "pos": sum(v > 0 for v in vals) / len(vals) * 100,
            "early": mean([v for t, v, _ in ics if t < SPLIT]), "late": mean([v for t, v, _ in ics if t >= SPLIT])}


def quintiles(rows, fx, y, min_n=10):
    """날짜(t) 안 5분위(1 = 값이 가장 낮다 = 보통 값보다 가장 싸다) → 분위별 중앙값 · 평균 · 이긴 비율."""
    by = {}
    for r in rows:
        if fx(r) is not None and r.get(y) is not None:
            by.setdefault(r["t"], []).append(r)
    acc = {b: [] for b in range(5)}
    for g in by.values():
        if len(g) < min_n:
            continue
        g = sorted(g, key=fx)
        for i, r in enumerate(g):
            acc[min(int(i / len(g) * 5), 4)].append(r)
    out = []
    for b in range(5):
        v = [r[y] for r in acc[b]]
        out.append({"q": b + 1, "n": len(v), "med": med(v), "mean": mean(v), "hit": sum(x > 0 for x in v) / len(v) * 100 if v else None,
                    "le30": sum(x <= -30 for x in v) / len(v) * 100 if v else None,
                    "med_early": med([r[y] for r in acc[b] if r["t"] < SPLIT]), "med_late": med([r[y] for r in acc[b] if r["t"] >= SPLIT]),
                    "gap_med": med([fx(r) for r in acc[b]])})
    meds = [o["med"] for o in out]
    mono = None          # 분위 번호 vs 분위 중앙값 순위상관(5점 — spear 는 8개↑라 직접)
    if None not in meds:
        rx, ry = rank(list(range(5))), rank(meds)
        num = sum((a - 2) * (b - 2) for a, b in zip(rx, ry))
        den = math.sqrt(sum((a - 2) ** 2 for a in rx) * sum((b - 2) ** 2 for b in ry))
        mono = num / den if den else None
    return {"q": out, "mono_rho": mono, "q1_minus_q5": (meds[0] - meds[4]) if None not in (meds[0], meds[4]) else None}


def ols(xy):
    n = len(xy)
    if n < 30:
        return None
    mx = sum(x for x, _ in xy) / n
    my = sum(y for _, y in xy) / n
    vx = sum((x - mx) ** 2 for x, _ in xy)
    return {"slope": sum((x - mx) * (y - my) for x, y in xy) / vx if vx else None, "icpt": None, "n": n, "mx": mx, "my": my} if vx else None


def winsor(vals, lo=.01, hi=.99):
    s = sorted(vals)
    return s[int(len(s) * lo)], s[min(int(len(s) * hi), len(s) - 1)]


# ---------------------------------------------------------------- 보고
def fmt(v, d=1, sign=True):
    if v is None:
        return "—"
    return ("%+.*f" % (d, v)) if sign else ("%.*f" % (d, v))


def run(args):
    t0 = dt.datetime.now()
    lines = []

    def log(msg):
        print(msg, flush=True)
        lines.append(msg)
    P = json.load(open(PANEL, encoding="utf-8"))
    log("패널 %d행 · 회사 %d · 공시일 %s ~ %s" % (len(P), len({r["code"] for r in P}), min(r["date"] for r in P), max(r["date"] for r in P)))
    try:
        SM = json.load(open(SECTOR, encoding="utf-8")).get("stocks", {})
    except Exception:
        SM = {}
    SEC = {k: (v or {}).get("sector") for k, v in SM.items()}
    PX = load_prices({r["code"] for r in P})
    log("주가 파일 %d곳" % len(PX))
    by = enrich(P, PX, SEC)
    rep = {"made": t0.isoformat(timespec="seconds"), "panel": {"rows": len(P), "firms": len(by)}, "prereg": {
        "H1": "per_pct<25(싼) vs per_pct>75(비싼) 의 ex12m 중앙값 차가 앞(~2019) · 뒤(2020~) 둘 다 양수이고 회사 부트스트랩 90% 구간 하한 > 0 이면 '기준이 된다'",
        "boot": args.boot, "seed": 7}}

    # ---- 표본 · 창 비교
    has = lambda k: sum(1 for r in P if r.get(k) is not None)        # noqa: E731
    cov = {k: has(k) for k in ("per", "per_q", "per_pct", "pct40", "pct_land", "pct20", "pct_norm", "pct_pbr", "gap", "cv", "ex12m", "ex6m")}
    rep["coverage"] = cov
    log("값 있는 줄: " + " · ".join("%s %d" % kv for kv in cov.items()))
    both = [r for r in P if r.get("per_pct") is not None and r.get("pct40") is not None]
    agree = sum(1 for r in both if bucket(r["per_pct"]) == r["b_land"]) / len(both) * 100 if both else None
    sanity = {"n": len(both), "rho_panel_vs_rebuilt40": spear([r["per_pct"] for r in both], [r["pct40"] for r in both]) if both else None,
              "bucket_agree_panel_vs_land_pct": agree,
              "h1_rows_hist_over_40q": sum(1 for r in P if r.get("per_pct") is not None and r["n_hist"] > 40),
              "h1_hist_len_median": med([r["n_hist"] for r in P if r.get("per_pct") is not None]),
              "h1_hist_len_q": [land_q([r["n_hist"] for r in P if r.get("per_pct") is not None], q) for q in (.1, .5, .9)]}
    hl = [r["n_hist"] for r in P if r.get("per_pct") is not None]
    sanity["h1_hist_len_dist"] = {"<12": sum(1 for v in hl if v < 12), "12~19": sum(1 for v in hl if 12 <= v < 20),
                                  "20~29": sum(1 for v in hl if 20 <= v < 30), "30~40": sum(1 for v in hl if 30 <= v <= 40), ">40": sum(1 for v in hl if v > 40)}
    rep["window"] = sanity
    log("창 점검: 패널 per_pct vs 다시 만든 40분기 자리 순위상관 %s · 패널 구간과 확장 창(풍경 근사) 구간 일치 %s%% · H1 줄의 앞 분기 수 중앙 %s, 40 넘는 줄 %d"
        % (fmt(sanity["rho_panel_vs_rebuilt40"], 3, False), fmt(agree, 1, False), sanity["h1_hist_len_median"], sanity["h1_rows_hist_over_40q"]))

    # ---- H1
    rep["H1"] = {}
    for y in YS:
        rep["H1"][y] = bucket_test(P, "b_h1", y, args.boot)
        h = rep["H1"][y]
        rs_ = [r for r in P if r.get("b_h1") is not None and r.get(y) is not None]
        for nm, a, b in (("cheap_mid", "cheap", "mid"), ("mid_exp", "mid", "exp")):     # 설명용 — 어느 쪽 끝이 차이를 만드나
            h["diff_" + nm]["ci"] = list(boot(rs_, make_diff("b_h1", y, a=a, b=b), n=max(args.boot // 2, 200))) if args.boot else [None, None]
        log("\n== H1 · %s (n %d · 회사 %d)" % (y, h["n"], h["firms"]))
        for b in BK:
            d = h["b"][b]
            if d["n"]:
                log("  %-14s n %5d 회사 %4d  중앙 %6s  평균 %6s  이긴 %4.1f%%  −30%%↓ %4.1f%%  앞 %6s(n %d)  뒤 %6s(n %d)" % (
                    BK_KO[b], d["n"], d["firms"], fmt(d["med"]), fmt(d["mean"]), d["hit"], d["le30"], fmt(d["med_early"]), d["n_early"],
                    fmt(d["med_late"]), d["n_late"]))
        dm = h["date_matched"] or {}
        log("  싼 − 비싼 중앙값 차 %s [90%% %s, %s]  앞 %s  뒤 %s  · 평균 차 %s · 날짜 안 차 평균 %s(날짜 %s, 양 %s%%)  → %s" % (
            fmt(h["diff"]), fmt(h["ci"][0]), fmt(h["ci"][1]), fmt(h["diff_early"]), fmt(h["diff_late"]), fmt(h["diff_mean"]),
            fmt(dm.get("avg")), dm.get("n_dates"), fmt(dm.get("pos"), 0, False), h["verdict"]))
        for nm, ko in (("cheap_mid", "싼 − 보통"), ("mid_exp", "보통 − 비싼")):
            o = h["diff_" + nm]
            log("  (설명) %s 중앙값 차 %s [90%% %s, %s]  앞 %s  뒤 %s" % (ko, fmt(o["all"]), fmt(o["ci"][0]), fmt(o["ci"][1]), fmt(o["early"]), fmt(o["late"])))
    log("  경과 %s" % (dt.datetime.now() - t0))

    # ---- (a) 보통 값 괴리
    rep["a"] = {}
    for y, hm in (("ex12m", 12), ("ex6m", 6)):
        q = quintiles(P, lambda r: r.get("gap"), y)
        ic = ic_stats(P, lambda r: r.get("gap"), y, hm)
        icp = ic_stats(P, lambda r: r.get("per_pct"), y, hm)
        rep["a"][y] = {"quint": q, "ic_gap": ic, "ic_per_pct": icp}
        log("\n== (a) 보통 값 괴리 gap = per ÷ per_med − 1 · 날짜 안 5분위 · %s (1 = 가장 싸다)" % y)
        for o in q["q"]:
            log("  %d분위 n %5d  괴리 중앙 %6s%%  초과 중앙 %6s  평균 %6s  이긴 %4.1f%%  −30%%↓ %4.1f%%  앞 %6s  뒤 %6s" % (
                o["q"], o["n"], fmt((o["gap_med"] or 0) * 100, 0), fmt(o["med"]), fmt(o["mean"]), o["hit"] or 0, o["le30"] or 0,
                fmt(o["med_early"]), fmt(o["med_late"])))
        log("  단조성(분위 vs 중앙값 순위상관) %s · 1분위 − 5분위 %s" % (fmt(q["mono_rho"], 2), fmt(q["q1_minus_q5"])))
        for nm, s in (("gap", ic), ("per_pct", icp)):
            if s:
                log("  IC(%s) %s  t %s  날짜 %d(유효 %.1f)  양 %.0f%%  앞 %s  뒤 %s" % (nm, fmt(s["ic"], 3), fmt(s["t"], 2), s["n_dates"], s["n_eff"], s["pos"],
                                                                         fmt(s["early"], 3), fmt(s["late"], 3)))
    # 절대 괴리 띠 — '보통 값보다 몇 % 싼가'
    bands = [("≤−30%", lambda g: g <= -.30), ("−30~−10%", lambda g: -.30 < g <= -.10), ("−10~+10%", lambda g: -.10 < g < .10),
             ("+10~+30%", lambda g: .10 <= g < .30), ("≥+30%", lambda g: g >= .30)]
    rep["a_band"] = {}
    for y in YS:
        rows = []
        for r in P:
            if r.get("gap") is None or r.get(y) is None:
                continue
            nm = next(n for n, f in bands if f(r["gap"]))
            rows.append(dict(r, _band=nm))
        tab = {n: desc([r for r in rows if r["_band"] == n], y) for n, _ in bands}
        d = make_diff("_band", y, a="≤−30%", b="≥+30%")
        ci = boot(rows, d, n=max(args.boot // 2, 200)) if args.boot else (None, None)
        rep["a_band"][y] = {"tab": tab, "diff": d(rows), "ci": list(ci), "diff_early": d([r for r in rows if r["t"] < SPLIT]),
                            "diff_late": d([r for r in rows if r["t"] >= SPLIT])}
        log("\n== (a2) 보통 값 대비 괴리 띠 · %s" % y)
        for n, _ in bands:
            o = tab[n]
            if o["n"]:
                log("  %-9s n %5d 회사 %4d  중앙 %6s  이긴 %4.1f%%  −30%%↓ %4.1f%%  앞 %6s  뒤 %6s" % (n, o["n"], o["firms"], fmt(o["med"]), o["hit"], o["le30"],
                                                                                 fmt(o["med_early"]), fmt(o["med_late"])))
        a2 = rep["a_band"][y]
        log("  ≤−30%% − ≥+30%% 중앙값 차 %s [90%% %s, %s]  앞 %s  뒤 %s" % (fmt(a2["diff"]), fmt(a2["ci"][0]), fmt(a2["ci"][1]),
                                                                   fmt(a2["diff_early"]), fmt(a2["diff_late"])))
    log("  경과 %s" % (dt.datetime.now() - t0))

    # ---- (b) 되돌림
    pairs = []
    loss_next = {b: [0, 0, 0] for b in BK}       # [다음 해 줄 있음, 그중 적자 · PER 없음, 줄 없음]
    for code, rs in by.items():
        byq = {r["_qn"]: r for r in rs}
        for r in rs:
            nx = byq.get(r["_qn"] + 4)
            b = r.get("b_h1")
            if b:
                if nx is None:
                    loss_next[b][2] += 1
                else:
                    loss_next[b][0] += 1
                    if nx.get("per") is None:
                        loss_next[b][1] += 1
            if r.get("gap") is None or nx is None or nx.get("gap") is None:
                continue
            x0 = math.log(1 + r["gap"])
            x1 = math.log(1 + nx["gap"])
            x1f = math.log(nx["per"] / r["per_med"])          # 보통 값 PER 을 t 때로 고정
            dper = math.log(nx["per"] / r["per"])
            dp = math.log(nx["px_d"] / r["px_d"]) if (r.get("px_d") and nx.get("px_d")) else None
            pairs.append({"code": code, "t": r["t"], "lab": r["lab"], "x0": x0, "x1": x1, "x1f": x1f, "dper": dper, "dp": dp,
                          "deps": (dp - dper) if dp is not None else None, "b": r.get("b_h1"), "gap": r["gap"]})
    rep["b"] = {"n_pairs": len(pairs), "firms": len({p["code"] for p in pairs})}
    if pairs:
        lo0, hi0 = winsor([p["x0"] for p in pairs])
        lo1, hi1 = winsor([p["x1"] for p in pairs])
        lo2, hi2 = winsor([p["x1f"] for p in pairs])
        cl = lambda v, a, b: min(max(v, a), b)       # noqa: E731

        def slope_of(sub, k="x1"):
            a, b = (lo1, hi1) if k == "x1" else (lo2, hi2)
            o = ols([(cl(p["x0"], lo0, hi0), cl(p[k], a, b)) for p in sub])
            return o["slope"] if o else None
        s1, s2 = slope_of(pairs), slope_of(pairs, "x1f")
        ci1 = boot(pairs, slope_of, n=max(args.boot // 2, 200)) if args.boot else (None, None)
        ci2 = boot(pairs, lambda s: slope_of(s, "x1f"), n=max(args.boot // 2, 200)) if args.boot else (None, None)
        rep["b"].update({"slope": s1, "ci": list(ci1), "slope_fixed_med": s2, "ci_fixed": list(ci2),
                         "slope_early": slope_of([p for p in pairs if p["t"] < SPLIT]), "slope_late": slope_of([p for p in pairs if p["t"] >= SPLIT]),
                         "half_life_y": (math.log(.5) / math.log(s1)) if (s1 and 0 < s1 < 1) else None})
        log("\n== (b) 되돌림 — ln(per/per_med) 이 4분기 뒤 얼마나 남나 (짝 %d · 회사 %d)" % (len(pairs), rep["b"]["firms"]))
        log("  기울기 %s [90%% %s, %s] (1 = 안 줄어듦, 0 = 다 되돌아옴) · 앞 %s 뒤 %s · 반감기 %s년 · 보통 값 PER 을 t 때로 고정하면 %s [%s, %s]" % (
            fmt(s1, 3, False), fmt(ci1[0], 3, False), fmt(ci1[1], 3, False), fmt(rep["b"]["slope_early"], 3, False), fmt(rep["b"]["slope_late"], 3, False),
            fmt(rep["b"]["half_life_y"], 2, False), fmt(s2, 3, False), fmt(ci2[0], 3, False), fmt(ci2[1], 3, False)))
        # 분해 — 괴리가 줄어든 길: 주가(dp) 냐 이익(deps) 이냐. ln PER 변화 = ln 주가 변화 − ln EPS 변화
        dec = {}
        LIM = math.log(10)
        groups = [("cheap", lambda p: p["b"] == "cheap"), ("mid", lambda p: p["b"] == "mid"), ("exp", lambda p: p["b"] == "exp"),
                  ("gap≤−30%", lambda p: p["gap"] <= -.3), ("gap≥+30%", lambda p: p["gap"] >= .3), ("전체", lambda p: True)]
        for nm, f in groups:
            sub = [p for p in pairs if f(p) and p["dp"] is not None and abs(p["dp"]) < LIM and abs(p["dper"]) < LIM and abs(p["deps"]) < LIM]
            if len(sub) < 20:
                continue
            dec[nm] = {"n": len(sub), "firms": len({p["code"] for p in sub}),
                       "mean_dper": mean([p["dper"] for p in sub]) * 100, "mean_dp": mean([p["dp"] for p in sub]) * 100,
                       "mean_deps": mean([p["deps"] for p in sub]) * 100,
                       "med_dper": med([p["dper"] for p in sub]) * 100, "med_dp": med([p["dp"] for p in sub]) * 100, "med_deps": med([p["deps"] for p in sub]) * 100,
                       "closed": sum(1 for p in sub if abs(p["x1"]) < abs(p["x0"])) / len(sub) * 100,
                       "eps_down": sum(1 for p in sub if p["deps"] < 0) / len(sub) * 100}
            o = dec[nm]
            log("  %-9s n %5d  ln변화(×100) 평균: PER %6s = 주가 %6s − EPS %6s  · 중앙: PER %6s 주가 %6s EPS %6s · 괴리 줄어듦 %4.1f%% · EPS 감소 %4.1f%%" % (
                nm, o["n"], fmt(o["mean_dper"]), fmt(o["mean_dp"]), fmt(o["mean_deps"]), fmt(o["med_dper"]), fmt(o["med_dp"]), fmt(o["med_deps"]),
                o["closed"], o["eps_down"]))
        rep["b"]["decomp"] = dec
    # 보통 값을 '목표 주가'로 읽으면 — t 때 보통 값(공시일 종가 ÷ (1 + gap))에 1년 안에 닿았나 · 1년 뒤 그 위인가, 그새 보통 값 선은 얼마나 움직였나
    tgt = {}
    pairs_by = {(p["code"], p["lab"]): p for p in pairs}
    tg_groups = [("cheap(H1)", lambda r: r.get("b_h1") == "cheap"), ("gap≤−30%", lambda r: r["gap"] <= -.3),
                 ("gap −30~−10%", lambda r: -.3 < r["gap"] <= -.1), ("gap −10~+10%", lambda r: -.1 < r["gap"] < .1)]
    for nm, f in tg_groups:
        hit, end_ok, tot, need, mv = 0, 0, 0, [], []
        for r in P:
            if r.get("gap") is None or not r.get("px_d") or not f(r):
                continue
            ks, vs = PX.get(r["code"], ((), ()))
            d0 = int(r["date"])
            d1 = int((dt.date(d0 // 10000, d0 // 100 % 100, d0 % 100) + dt.timedelta(days=365)).strftime("%Y%m%d"))
            i0, i1 = bisect.bisect_right(ks, d0), bisect.bisect_right(ks, d1)
            if i1 <= i0 or ks[-1] < d1:
                continue
            line = r["px_d"] / (1 + r["gap"])
            tot += 1
            hit += max(vs[i0:i1]) >= line
            end_ok += vs[i1 - 1] >= line
            need.append((line / r["px_d"] - 1) * 100)
            p = pairs_by.get((r["code"], r["lab"]))
            if p and p["dp"] is not None:
                mv.append((math.exp(p["dp"]) * (1 + r["gap"]) / math.exp(p["x1"]) - 1) * 100)      # 보통 값 선(EPS × 중앙 PER)의 1년 변화
        if tot:
            tgt[nm] = {"n": tot, "touch_12m": hit / tot * 100, "above_at_12m": end_ok / tot * 100, "need_med": med(need),
                       "line_move_med": med(mv), "line_move_n": len(mv), "line_down_share": (sum(1 for v in mv if v < 0) / len(mv) * 100) if mv else None}
            o = tgt[nm]
            log("  목표 주가로: %-13s n %5d  필요 상승 중앙 %6s%%  1년 안 닿음 %4.1f%%  1년 뒤 그 위 %4.1f%%  · 그새 보통 값 선 변화 중앙 %6s%%(내려감 %s%%, n %d)" % (
                nm, tot, fmt(o["need_med"]), o["touch_12m"], o["above_at_12m"], fmt(o["line_move_med"]), fmt(o["line_down_share"], 1, False), o["line_move_n"]))
    rep["b"]["target"] = tgt
    rep["b"]["next_year"] = {b: {"has_next": v[0], "next_loss_or_noper": v[1], "no_next_row": v[2],
                                 "loss_rate": v[1] / v[0] * 100 if v[0] else None} for b, v in loss_next.items()}
    log("  1년 뒤(4분기 뒤) 줄의 PER 이 없음(적자 등) 비율: " + " · ".join(
        "%s %s%%(%d/%d)" % (BK_KO[b], fmt(rep["b"]["next_year"][b]["loss_rate"], 1, False), loss_next[b][1], loss_next[b][0]) for b in BK))
    log("  경과 %s" % (dt.datetime.now() - t0))

    # ---- (c) 이익 꾸준 vs 출렁
    h1rows = [r for r in P if r.get("b_h1") is not None]
    date_rank_pct(h1rows, "cv", "cv_dp")
    subsets = [("출렁(변동계수 날짜 안 상위⅓)", lambda r: r.get("cv_dp") is not None and r["cv_dp"] >= 200 / 3),
               ("꾸준(하위⅔)", lambda r: r.get("cv_dp") is not None and r["cv_dp"] < 200 / 3),
               ("꾸준(하위⅔) · 12분기 내내 흑자", lambda r: r.get("cv_dp") is not None and r["cv_dp"] < 200 / 3 and r.get("all_pos12")),
               ("변동계수 없음(앞 분기 8개 미만)", lambda r: r.get("cv_dp") is None)]
    rep["c"] = {}
    for nm, f in subsets:
        sub = [r for r in h1rows if f(r)]
        rep["c"][nm] = {y: bucket_test(sub, "b_h1", y, max(args.boot // 2, 200) if args.boot else 0) for y in YS}
    log("\n== (c) 이익 꾸준 vs 출렁 — H1 구간을 그 안에서")
    for nm, _ in subsets:
        for y in YS:
            h = rep["c"][nm][y]
            bb = h["b"]
            log("  %-26s %s  싼 %s(n %d) 보통 %s(n %d) 비싼 %s(n %d)  차 %s [%s, %s] 앞 %s 뒤 %s" % (
                nm, y, fmt(bb["cheap"].get("med")), bb["cheap"]["n"], fmt(bb["mid"].get("med")), bb["mid"]["n"], fmt(bb["exp"].get("med")), bb["exp"]["n"],
                fmt(h["diff"]), fmt(h["ci"][0]), fmt(h["ci"][1]), fmt(h["diff_early"]), fmt(h["diff_late"])))
    log("  경과 %s" % (dt.datetime.now() - t0))

    # ---- (d) 업종 하나씩 빼기 · 해마다
    rep["d"] = {"loso": {}, "sector_alone": {}, "year": {}}
    secs = sorted({r["sector"] for r in h1rows})
    for y in YS:
        d = make_diff("b_h1", y)
        rep["d"]["loso"][y], rep["d"]["sector_alone"][y], rep["d"]["year"][y] = {}, {}, {}
        for s in secs:
            rest = [r for r in h1rows if r["sector"] != s]
            only = [r for r in h1rows if r["sector"] == s]
            rep["d"]["loso"][y][s] = {"n_out": len(only), "diff": d(rest), "early": d([r for r in rest if r["t"] < SPLIT]),
                                      "late": d([r for r in rest if r["t"] >= SPLIT])}
            rep["d"]["sector_alone"][y][s] = {"n": len(only), "n_cheap": sum(1 for r in only if r["b_h1"] == "cheap" and r.get(y) is not None),
                                              "n_exp": sum(1 for r in only if r["b_h1"] == "exp" and r.get(y) is not None), "diff": d(only)}
        for yr in sorted({r["date"][:4] for r in h1rows}):
            sub = [r for r in h1rows if r["date"][:4] == yr]
            c_ = [r[y] for r in sub if r["b_h1"] == "cheap" and r.get(y) is not None]
            e_ = [r[y] for r in sub if r["b_h1"] == "exp" and r.get(y) is not None]
            rep["d"]["year"][y][yr] = {"n_cheap": len(c_), "n_exp": len(e_), "med_cheap": med(c_), "med_exp": med(e_), "diff": d(sub)}
    log("\n== (d) 업종 하나씩 빼고 H1 차(ex12m) — 전체 %s" % fmt(rep["H1"]["ex12m"]["diff"]))
    for s in secs:
        o, a = rep["d"]["loso"]["ex12m"][s], rep["d"]["sector_alone"]["ex12m"][s]
        log("  %-16s 빼면 %6s (앞 %6s 뒤 %6s)  · 그 업종만 %6s (싼 n %d · 비싼 n %d)" % (s, fmt(o["diff"]), fmt(o["early"]), fmt(o["late"]), fmt(a["diff"]),
                                                                          a["n_cheap"], a["n_exp"]))
    log("  해마다(공시 연도) ex12m:")
    for yr, o in rep["d"]["year"]["ex12m"].items():
        log("    %s  싼 %6s(n %4d)  비싼 %6s(n %4d)  차 %6s" % (yr, fmt(o["med_cheap"]), o["n_cheap"], fmt(o["med_exp"]), o["n_exp"], fmt(o["diff"])))
    log("  경과 %s" % (dt.datetime.now() - t0))

    # ---- (e) 대안 정의 — 참고(다중비교)
    alts = [("b_land", "pct_land", "풍경 근사: 앞 분기 전부(확장 창) · 분기 말 PER 0.5~300 · 지금 값 분모 밖"),
            ("b_20", "pct20", "5년(20분기) 창"),
            ("b_norm", "pct_norm", "3년 평균 이익(정규화) PER 의 자기 역사 자리"),
            ("b_pbr", "pct_pbr", "자기 역사 PBR 자리(흑자 줄만)")]
    rep["e"] = {}
    log("\n== (e) 대안 정의(참고 — 다중비교라 판정에 안 씀)")
    for bk, pk, nm in alts:
        rep["e"][bk] = {"name": nm}
        for y, hm in (("ex12m", 12), ("ex6m", 6)):
            h = bucket_test(P, bk, y, max(args.boot // 2, 200) if args.boot else 0)
            h["ic"] = ic_stats(P, lambda r, k=pk: r.get(k), y, hm)
            rep["e"][bk][y] = h
            bb = h["b"]
            log("  %-44s %s  싼 %s(n %d) 보통 %s(n %d) 비싼 %s(n %d)  차 %s [%s, %s] 앞 %s 뒤 %s · IC %s(t %s)" % (
                nm, y, fmt(bb["cheap"].get("med")), bb["cheap"]["n"], fmt(bb["mid"].get("med")), bb["mid"]["n"], fmt(bb["exp"].get("med")), bb["exp"]["n"],
                fmt(h["diff"]), fmt(h["ci"][0]), fmt(h["ci"][1]), fmt(h["diff_early"]), fmt(h["diff_late"]),
                fmt((h["ic"] or {}).get("ic"), 3), fmt((h["ic"] or {}).get("t"), 2)))
    for y, hm in (("ex12m", 12), ("ex6m", 6)):
        rep["e"].setdefault("gap_norm", {})[y] = {"quint": quintiles(P, lambda r: r.get("gap_norm"), y), "ic": ic_stats(P, lambda r: r.get("gap_norm"), y, hm)}
        rep["e"].setdefault("gap20", {})[y] = {"quint": quintiles(P, lambda r: (r["per"] / r["per_med20"] - 1) if (r.get("per") and r.get("per_med20")) else None, y),
                                               "ic": ic_stats(P, lambda r: (r["per"] / r["per_med20"] - 1) if (r.get("per") and r.get("per_med20")) else None, y, hm)}
    for k in ("gap_norm", "gap20"):
        q = rep["e"][k]["ex12m"]["quint"]
        log("  %s 5분위 ex12m 중앙: %s · 단조성 %s · IC %s" % (k, " ".join(fmt(o["med"]) for o in q["q"]), fmt(q["mono_rho"], 2),
                                                         fmt((rep["e"][k]["ex12m"]["ic"] or {}).get("ic"), 3)))
    # ---- (f) 참고 — 그냥 낮은 PER(같은 날짜 다른 회사와 견준 횡단 순위)과 견줌: 자기 역사 자리가 그 위에 정보를 더하나
    withper = [r for r in P if r.get("per") is not None]
    date_rank_pct(withper, "per", "per_xs")
    for r in withper:
        x = r.get("per_xs")
        r["b_xs"] = None if x is None else ("cheap" if x < 100 / 3 else "exp" if x >= 200 / 3 else "mid")
    rep["f"] = {}
    log("\n== (f) 참고 — 횡단 PER(같은 날짜 안 흑자 회사끼리 PER 순위 ⅓) vs 자기 역사 자리")
    for y, hm in (("ex12m", 12), ("ex6m", 6)):
        xs_all = bucket_test(withper, "b_xs", y, max(args.boot // 2, 200) if args.boot else 0)
        xs_h1 = bucket_test([r for r in withper if r.get("b_h1") is not None], "b_xs", y, max(args.boot // 2, 200) if args.boot else 0)
        inside = {}
        for tb in BK:
            sub = [r for r in withper if r.get("b_xs") == tb and r.get("b_h1") is not None]
            inside[tb] = bucket_test(sub, "b_h1", y, max(args.boot // 2, 200) if args.boot else 0)
        rep["f"][y] = {"xs_all": xs_all, "xs_on_h1_rows": xs_h1, "h1_inside_xs": inside, "ic_per": ic_stats(withper, lambda r: r.get("per"), y, hm)}
        log("  %s 횡단 PER 하⅓ − 상⅓(흑자 줄 전체 n %d) %s [%s, %s] 앞 %s 뒤 %s · 같은 차를 H1 줄에서만 %s [%s, %s] · IC(PER) %s(t %s)" % (
            y, xs_all["n"], fmt(xs_all["diff"]), fmt(xs_all["ci"][0]), fmt(xs_all["ci"][1]), fmt(xs_all["diff_early"]), fmt(xs_all["diff_late"]),
            fmt(xs_h1["diff"]), fmt(xs_h1["ci"][0]), fmt(xs_h1["ci"][1]),
            fmt((rep["f"][y]["ic_per"] or {}).get("ic"), 3), fmt((rep["f"][y]["ic_per"] or {}).get("t"), 2)))
        for tb in BK:
            h = inside[tb]
            log("    횡단 %s 안에서 H1 싼 − 비싼 %s [%s, %s] (싼 n %d · 비싼 n %d) 앞 %s 뒤 %s" % (
                {"cheap": "하⅓(싼)", "mid": "중⅓", "exp": "상⅓(비싼)"}[tb], fmt(h["diff"]), fmt(h["ci"][0]), fmt(h["ci"][1]),
                h["b"]["cheap"]["n"], h["b"]["exp"]["n"], fmt(h["diff_early"]), fmt(h["diff_late"])))
    rep["elapsed_s"] = (dt.datetime.now() - t0).total_seconds()
    log("\n끝 · 경과 %s" % (dt.datetime.now() - t0))
    return rep, lines


# ================================================================ --live: 실전 맥락(2026-10-16 2회차)
#   (1) 지금 풍경이 '싼 구간' · '비싼 구간'이라 말하는 회사 — 수 · 업종 · 린치 유형 · 이익 출렁 비율
#   (2) 과거 패널에서 구간에 든 뒤 4분기 순이익이 어떻게 됐나(가치 함정인가)
#   (3) 저평가 · 시너지 · 분기변화 기록과 이번 전 종목 결과를 한 표로(+ 같은 패널 · 같은 25/75 문턱으로 부분 표본 다시 잼)
LAND_DIR = os.path.join(CACHE, "landscape")
SYN_PANEL = os.path.join(CACHE, "시너지", "bt_panel.json")
REC = {"quarter": os.path.join(CACHE, "quarter", "bt_report.json"), "value": os.path.join(CACHE, "value", "bt_report.json"),
       "synergy": os.path.join(CACHE, "시너지", "bt_report.json")}
PATHS = (("up", "늘었다(+10%↑)", lambda d: d >= .10), ("flat", "비슷(−10~+10%)", lambda d: -.10 < d < .10),
         ("down", "줄었다(−10%↓ · 적자 포함)", lambda d: d <= -.10))


def cv_of(vals):
    nv = [v for v in vals if v is not None]
    if len(nv) < MIN_HIST:
        return None
    mu = sum(nv) / len(nv)
    return st.pstdev(nv) / abs(mu) if mu else None


def land_snapshot(SEC, cv_cut_panel):
    files = sorted(f for f in os.listdir(LAND_DIR) if f.endswith(".json"))
    rows, n_err, n_bad, vers, dates = [], 0, 0, {}, {}
    for f in files:
        try:
            d = json.load(open(os.path.join(LAND_DIR, f), encoding="utf-8"))
        except Exception:
            n_bad += 1
            continue
        vers[d.get("v")] = vers.get(d.get("v"), 0) + 1
        if d.get("error") or not d.get("decide"):
            n_err += 1
            continue
        dc = d["decide"]
        dates[dc.get("date")] = dates.get(dc.get("date"), 0) + 1
        qk = lambda q: (q.get("year") or 0) * 4 + (q.get("q") or 0)        # noqa: E731
        qs = sorted((q for q in d.get("quarters") or [] if q.get("year") and q.get("q")), key=qk)
        lastq = next((q for q in reversed(qs) if q.get("ni4") is not None), None)
        win = [q.get("ni4") for q in qs if lastq and qk(lastq) - 11 <= qk(q) <= qk(lastq)]
        rows.append({"code": d.get("code"), "name": d.get("name"), "sector": SEC.get((d.get("code") or "").upper()) or "없음",
                     "pct": dc.get("pct"), "zone": dc.get("zone"), "type": dc.get("type") or "없음", "per": dc.get("per"), "eps": dc.get("eps"),
                     "g": dc.get("g"), "eps_peak": bool(dc.get("eps_peak")), "lynch": (dc.get("lynch") or {}).get("v"),
                     "quad": dc.get("quad"), "band_n": (d.get("band") or {}).get("n"), "date": dc.get("date"), "cv": cv_of(win),
                     "ni4_last": lastq.get("ni4") if lastq else None})
    withp = [r for r in rows if r["pct"] is not None]
    cvs = [r["cv"] for r in withp if r["cv"] is not None]
    cut_now = land_q(cvs, 2 / 3) if cvs else None
    for r in rows:
        r["b"] = None if r["pct"] is None else ("cheap" if r["pct"] < 25 else "exp" if r["pct"] > 75 else "mid")
        r["swing_now"] = None if (r["cv"] is None or cut_now is None) else r["cv"] >= cut_now
        r["swing_panel"] = None if (r["cv"] is None or cv_cut_panel is None) else r["cv"] >= cv_cut_panel

    def prof(sub):
        n = len(sub)
        if not n:
            return {"n": 0}
        cnt = lambda key: sorted(((k, sum(1 for r in sub if r[key] == k)) for k in {r[key] for r in sub}), key=lambda x: -x[1])   # noqa: E731
        share = lambda f: sum(1 for r in sub if f(r)) / n * 100                                                                   # noqa: E731
        sw = [r for r in sub if r["swing_now"] is not None]
        swp = [r for r in sub if r["swing_panel"] is not None]
        return {"n": n, "sector": cnt("sector"), "type": cnt("type"), "lynch": cnt("lynch"), "quad": cnt("quad"),
                "cyc_share": share(lambda r: r["type"] == "경기순환"),
                "swing_now_share": (sum(1 for r in sw if r["swing_now"]) / len(sw) * 100) if sw else None, "swing_n": len(sw),
                "swing_panel_share": (sum(1 for r in swp if r["swing_panel"]) / len(swp) * 100) if swp else None,
                "eps_peak_share": share(lambda r: r["eps_peak"]), "fin_n": sum(1 for r in sub if r["sector"] == "금융"),
                "g_med": med([r["g"] for r in sub]), "g_neg_share": (sum(1 for r in sub if r["g"] is not None and r["g"] < 0) /
                                                                   max(1, sum(1 for r in sub if r["g"] is not None)) * 100),
                "per_med": med([r["per"] for r in sub]), "band_n_med": med([r["band_n"] for r in sub]),
                "band_n_lt20": sum(1 for r in sub if (r["band_n"] or 0) < 20)}
    out = {"files": len(files), "unreadable": n_bad, "error_or_no_decide": n_err, "versions": vers, "decide_dates": dates,
           "with_decide": len(rows), "with_pct": len(withp),
           "no_pct_loss": sum(1 for r in rows if r["pct"] is None and (r["eps"] is None or r["eps"] <= 0)),
           "no_pct_other": sum(1 for r in rows if r["pct"] is None and r["eps"] is not None and r["eps"] > 0),
           "zone_screen": {z: sum(1 for r in rows if r["zone"] == z) for z in ("싸다", "보통", "비싸다")},
           "edge_eq25": sum(1 for r in withp if r["pct"] == 25), "edge_eq75": sum(1 for r in withp if r["pct"] == 75),
           "cv_cut_now": cut_now, "cv_cut_panel": cv_cut_panel,
           "groups": {b: prof([r for r in withp if r["b"] == b]) for b in BK}, "all_pct": prof(withp),
           "list": {b: sorted(([r["code"], r["name"], r["sector"], r["type"], round(r["pct"], 1), round(r["per"], 1) if r["per"] else None,
                                round(r["g"], 0) if r["g"] is not None else None, r["eps_peak"]]
                               for r in withp if r["b"] == b), key=lambda x: x[4]) for b in ("cheap", "exp")}}
    return out


def eps_path(by):
    """각 줄에 dni = 4분기 뒤 ni4 ÷ 지금 ni4 − 1(지금 ni4 > 0) · 같은 날짜 흑자 줄 중앙을 뺀 dni_adj · 4분기 뒤 적자 여부."""
    allr = []
    for code, rs in by.items():
        byq = {r["_qn"]: r for r in rs}
        for r in rs:
            r["dni"] = r["dni_adj"] = r["loss_next"] = None
            r["has_next"] = (r["_qn"] + 4) in byq
            n0 = r.get("ni4")
            nx = byq.get(r["_qn"] + 4)
            if n0 is not None and n0 > 0 and nx is not None and nx.get("ni4") is not None:
                r["dni"] = nx["ni4"] / n0 - 1
                r["loss_next"] = nx["ni4"] <= 0
                allr.append(r)
    byt = {}
    for r in allr:
        byt.setdefault(r["t"], []).append(r["dni"])
    mt = {t: st.median(v) for t, v in byt.items() if len(v) >= 6}
    for r in allr:
        if r["t"] in mt:
            r["dni_adj"] = r["dni"] - mt[r["t"]]
    return allr


def eps_table(rows, key, nboot):
    """구간별 4분기 뒤 순이익 변화 — 중앙 · 줄어든 비율 · −30%↓ · 적자 전환 · 같은 날짜 보정 · 들어갈 때 순이익 1년 변화."""
    out = {"key": key}
    for b in BK:
        sub = [r for r in rows if r.get(key) == b]
        dn = [r for r in sub if r.get("dni") is not None]
        v = [r["dni"] * 100 for r in dn]
        out[b] = {"n": len(sub), "n_dni": len(dn), "firms": len({r["code"] for r in dn}),
                  "no_next_row": sum(1 for r in sub if not r.get("has_next")),
                  "ni4_le0_or_missing_now": sum(1 for r in sub if not (r.get("ni4") is not None and r["ni4"] > 0)),
                  "med": med(v), "down": (sum(1 for x in v if x < 0) / len(v) * 100) if v else None,
                  "le30": (sum(1 for x in v if x <= -30) / len(v) * 100) if v else None,
                  "loss": (sum(1 for r in dn if r["loss_next"]) / len(dn) * 100) if dn else None,
                  "med_adj": med([r["dni_adj"] * 100 for r in dn if r.get("dni_adj") is not None]),
                  "med_early": med([r["dni"] * 100 for r in dn if r["t"] < SPLIT]), "med_late": med([r["dni"] * 100 for r in dn if r["t"] >= SPLIT]),
                  "entry_ni_yoy_med": med([r.get("ni_yoy") for r in sub])}
    for nm, a, b in (("cheap_mid", "cheap", "mid"), ("cheap_exp", "cheap", "exp")):
        for k in ("dni", "dni_adj"):
            def f(sub, a=a, b=b, k=k):
                x = [r[k] for r in sub if r.get(key) == a and r.get(k) is not None]
                z = [r[k] for r in sub if r.get(key) == b and r.get(k) is not None]
                return (st.median(x) - st.median(z)) * 100 if len(x) >= 8 and len(z) >= 8 else None
            rs = [r for r in rows if r.get(key) in (a, b) and r.get(k) is not None]
            out["%s_%s" % (nm, k)] = {"diff": f(rs), "ci": list(boot(rs, f, n=nboot)) if nboot else [None, None],
                                      "early": f([r for r in rs if r["t"] < SPLIT]), "late": f([r for r in rs if r["t"] >= SPLIT])}
    return out


def trap_split(rows, key):
    """사후 지식(설명용) — 구간 안에서 4분기 뒤 순이익 길별 ex12m 중앙. 같은 길 안의 싼 − 비싼도."""
    out = {}
    for b in BK:
        sub = [r for r in rows if r.get(key) == b and r.get("dni") is not None and r.get("ex12m") is not None]
        out[b] = {"n": len(sub)}
        for pk, _, f in PATHS:
            g = [r for r in sub if f(r["dni"])]
            out[b][pk] = {"n": len(g), "share": len(g) / len(sub) * 100 if sub else None, "ex12m_med": med([r["ex12m"] for r in g]),
                          "hit": (sum(1 for r in g if r["ex12m"] > 0) / len(g) * 100) if g else None}
    out["within_path_cheap_minus_exp"] = {pk: (out["cheap"][pk]["ex12m_med"] - out["exp"][pk]["ex12m_med"])
                                          if (out["cheap"][pk]["ex12m_med"] is not None and out["exp"][pk]["ex12m_med"] is not None) else None
                                          for pk, _, _ in PATHS}
    return out


def pooled_tercile(rows, fx, y="ex12m"):
    """도구/억울_백테스트.tercile_test(by_date=False)와 같은 컷 — 저평가 기록 재현용."""
    rs = [r for r in rows if r.get(y) is not None and fx(r) is not None]
    if len(rs) < 30:
        return None
    v = sorted(fx(r) for r in rs)
    a, b = v[len(v) // 3], v[2 * len(v) // 3]

    def sp(sub):
        lo = [r[y] for r in sub if fx(r) < a]
        hi = [r[y] for r in sub if fx(r) >= b]
        return st.median(hi) - st.median(lo) if len(lo) > 5 and len(hi) > 5 else None
    return {"n": len(rs), "firms": len({r["code"] for r in rs}), "top_minus_bot": sp(rs), "early": sp([r for r in rs if r["t"] < SPLIT]),
            "late": sp([r for r in rs if r["t"] >= SPLIT])}


def run_live(args):
    t0 = dt.datetime.now()
    lines = []

    def log(msg):
        print(msg, flush=True)
        lines.append(msg)
    nb = args.boot
    P = json.load(open(PANEL, encoding="utf-8"))
    try:
        SM = json.load(open(SECTOR, encoding="utf-8")).get("stocks", {})
    except Exception:
        SM = {}
    SEC = {k: (v or {}).get("sector") for k, v in SM.items()}
    PX = load_prices({r["code"] for r in P})
    by = enrich(P, PX, SEC)
    rep = {"made": t0.isoformat(timespec="seconds"), "boot": nb}
    h1rows = [r for r in P if r.get("b_h1") is not None]
    cv_cut_panel = land_q([r["cv"] for r in h1rows if r.get("cv") is not None], 2 / 3)

    # ---- (1) 지금 풍경
    L = land_snapshot(SEC, cv_cut_panel)
    rep["live"] = L
    log("== (1) 지금 풍경 — .cache/landscape %d 파일 · 판 있음 %d · 자리(pct) 있음 %d · 적자 등으로 자리 없음 %d · 흑자인데 자리 없음 %d · 오류/짧음 %d"
        % (L["files"], L["with_decide"], L["with_pct"], L["no_pct_loss"], L["no_pct_other"], L["error_or_no_decide"]))
    log("  판 버전 %s · 판의 날 %s" % (L["versions"], sorted(L["decide_dates"].items())))
    log("  화면 zone(≤25 · ≥75): %s · pct 가 정확히 25 인 곳 %d · 75 인 곳 %d" % (L["zone_screen"], L["edge_eq25"], L["edge_eq75"]))
    log("  이익 출렁 문턱: 지금 자리 있는 회사 안 변동계수 상위⅓ %s · 패널 H1 줄 66.7%% 자리 %s" % (fmt(L["cv_cut_now"], 2, False), fmt(L["cv_cut_panel"], 2, False)))
    for b in BK + ("all",):
        g = L["groups"][b] if b != "all" else L["all_pct"]
        if not g["n"]:
            continue
        log("\n  [%s] %d곳 · 경기순환 유형 %.1f%% · 이익 출렁(지금 기준 상위⅓) %s%%(n %d) · 패널 문턱 기준 %s%% · EPS 15년 최고 근처 %.1f%% · 금융 %d곳"
            % (BK_KO.get(b, "자리 있는 전체"), g["n"], g["cyc_share"], fmt(g["swing_now_share"], 1, False), g["swing_n"],
               fmt(g["swing_panel_share"], 1, False), g["eps_peak_share"], g["fin_n"]))
        log("    EPS 1년 변화 중앙 %s%% (줄어든 곳 %.0f%%) · PER 중앙 %s · 띠 PER 개수 중앙 %s (20개 미만 %d곳)"
            % (fmt(g["g_med"], 0), g["g_neg_share"], fmt(g["per_med"], 1, False), g["band_n_med"], g["band_n_lt20"]))
        log("    유형: " + " · ".join("%s %d" % kv for kv in g["type"]))
        log("    업종: " + " · ".join("%s %d" % kv for kv in g["sector"]))
        log("    린치 판정: " + " · ".join("%s %d" % kv for kv in g["lynch"]) + "  / 사분면: " + " · ".join("%s %d" % kv for kv in g["quad"]))

    # ---- (2) 4분기 뒤 순이익
    eps_path(by)
    rep["eps"] = {}
    log("\n== (2) 구간에 든 뒤 4분기 순이익 변화 dni = ni4(t+4) ÷ ni4(t) − 1 (ni4(t) > 0 · 주식 수 변화 무시)")
    for key, nm in (("b_h1", "H1 per_pct(40분기 창)"), ("b_land", "풍경 근사(확장 창)")):
        tb = eps_table(P, key, nb)
        rep["eps"][key] = tb
        log("  -- %s" % nm)
        for b in BK:
            o = tb[b]
            log("    %-14s 줄 %5d · dni 있음 %5d(%d곳) · 다음 해 줄 없음 %d  | 중앙 %6s%%  줄어듦 %4.1f%%  −30%%↓ %4.1f%%  적자 전환 %4.1f%%  | 같은 날짜 보정 중앙 %6s%%p | 앞 %6s 뒤 %6s | 들어갈 때 순이익 1년 중앙 %6s%%"
                % (BK_KO[b], o["n"], o["n_dni"], o["firms"], o["no_next_row"], fmt(o["med"]), o["down"] or 0, o["le30"] or 0, o["loss"] or 0,
                   fmt(o["med_adj"]), fmt(o["med_early"]), fmt(o["med_late"]), fmt(o["entry_ni_yoy_med"])))
        for nm2 in ("cheap_mid", "cheap_exp"):
            for k in ("dni", "dni_adj"):
                o = tb["%s_%s" % (nm2, k)]
                log("    %s %-8s 중앙 차 %6s%%p [90%% %s, %s]  앞 %s  뒤 %s" % ({"cheap_mid": "싼 − 보통", "cheap_exp": "싼 − 비싼"}[nm2], k,
                                                                     fmt(o["diff"]), fmt(o["ci"][0]), fmt(o["ci"][1]), fmt(o["early"]), fmt(o["late"])))
    ts = trap_split(P, "b_h1")
    rep["trap"] = ts
    log("  -- (사후 지식 · 설명용) H1 구간 안에서 4분기 뒤 순이익 길별 12개월 초과수익 중앙")
    for b in BK:
        log("    %-14s n %5d  " % (BK_KO[b], ts[b]["n"]) + "  ".join(
            "%s %4.1f%% → %6s (이긴 %4.1f%%)" % (lab, ts[b][pk]["share"] or 0, fmt(ts[b][pk]["ex12m_med"]), ts[b][pk]["hit"] or 0) for pk, lab, _ in PATHS))
    log("    같은 길 안 싼 − 비싼: " + " · ".join("%s %s" % (lab, fmt(ts["within_path_cheap_minus_exp"][pk])) for pk, lab, _ in PATHS))
    # 결과를 본 뒤 더한 설명(사전 등록 밖) — 들어갈 때 알 수 있던 갈래: 순이익 급증(1년 +30%↑) · 순이익 정점 근처(자기 최고의 95%↑, 앞 분기 8개↑)
    for code, rs in by.items():
        for r in rs:
            prior = [x.get("ni4") for x in rs if x["_qn"] < r["_qn"] and x["date"] <= r["date"] and x.get("ni4") is not None]
            n0 = r.get("ni4")
            r["ni_peak"] = (n0 >= .95 * max(prior + [n0])) if (n0 is not None and n0 > 0 and len(prior) >= MIN_HIST) else None
            r["ni_spike"] = (r["ni_yoy"] >= 30) if r.get("ni_yoy") is not None else None
    rep["entry_split"] = {}
    log("  -- (결과 본 뒤 더함 · 설명용) 들어갈 때 알 수 있던 갈래별 — 12개월 초과수익 중앙 / 4분기 뒤 순이익 중앙")
    for fk, fnm in (("ni_spike", "순이익 1년 +30%↑"), ("ni_peak", "순이익 자기 최고의 95%↑")):
        rep["entry_split"][fk] = {}
        for b in BK:
            sub = [r for r in P if r.get("b_h1") == b]
            o = {}
            for val, vn in ((True, "예"), (False, "아니오")):
                g = [r for r in sub if r.get(fk) is val]
                o[vn] = {"n": len(g), "share": len(g) / max(1, sum(1 for r in sub if r.get(fk) is not None)) * 100,
                         "ex12m_med": med([r.get("ex12m") for r in g]), "dni_med": med([r["dni"] * 100 for r in g if r.get("dni") is not None]),
                         "dni_down": (sum(1 for r in g if r.get("dni") is not None and r["dni"] < 0) /
                                      max(1, sum(1 for r in g if r.get("dni") is not None)) * 100)}
            rep["entry_split"][fk][b] = o
            log("    %-22s %-14s 예 %4.1f%%(n %4d): 초과 %6s · 순이익 %6s%%(줄어듦 %4.1f%%)  | 아니오(n %4d): 초과 %6s · 순이익 %6s%%(줄어듦 %4.1f%%)" % (
                fnm, BK_KO[b], o["예"]["share"], o["예"]["n"], fmt(o["예"]["ex12m_med"]), fmt(o["예"]["dni_med"]), o["예"]["dni_down"],
                o["아니오"]["n"], fmt(o["아니오"]["ex12m_med"]), fmt(o["아니오"]["dni_med"]), o["아니오"]["dni_down"]))
        # 싼 구간 안 예 − 아니오 차 · 회사 부트스트랩
        sub = [r for r in P if r.get("b_h1") == "cheap" and r.get(fk) is not None and r.get("ex12m") is not None]
        for r in sub:
            r["_fk"] = "y" if r[fk] else "n"
        f = make_diff("_fk", "ex12m", a="y", b="n")
        ci = boot(sub, f, n=max(nb // 2, 200)) if nb else (None, None)
        rep["entry_split"][fk]["cheap_yes_minus_no"] = {"diff": f(sub), "ci": list(ci), "early": f([r for r in sub if r["t"] < SPLIT]),
                                                         "late": f([r for r in sub if r["t"] >= SPLIT])}
        o = rep["entry_split"][fk]["cheap_yes_minus_no"]
        log("    싼 구간 안 %s 예 − 아니오 ex12m 중앙 차 %s [90%% %s, %s] 앞 %s 뒤 %s" % (fnm, fmt(o["diff"]), fmt(o["ci"][0]), fmt(o["ci"][1]),
                                                                          fmt(o["early"]), fmt(o["late"])))
    cg = [r for r in L["list"]["cheap"]]
    gv = [x[6] for x in cg if x[6] is not None]
    rep["live_cheap_spike"] = {"g_ge30": sum(1 for v in gv if v >= 30), "g_n": len(gv), "eps_peak": sum(1 for x in cg if x[7]), "n": len(cg)}
    log("    지금 풍경 싼 곳: EPS 1년 +30%%↑ %d/%d곳 · EPS 15년 최고 근처 %d/%d곳" % (rep["live_cheap_spike"]["g_ge30"], len(gv),
                                                                     rep["live_cheap_spike"]["eps_peak"], len(cg)))

    # ---- (3) 기록 + 같은 패널 · 같은 문턱으로 부분 표본
    rec = {}
    try:
        q = json.load(open(REC["quarter"], encoding="utf-8"))
        rec["quarter"] = {"lo30": q["rules"]["PER 자기 역사 하위 30%"]["ex12m"], "hi30": q["rules"]["PER 자기 역사 상위 30%"]["ex12m"],
                          "lo30_drev4": q["rules"]["PER 자기 역사 하위 30%"].get("drev4"), "hi30_drev4": q["rules"]["PER 자기 역사 상위 30%"].get("drev4"),
                          "ic": (q.get("cont") or {}).get("PER 자기 역사 백분위")}
    except Exception as e:
        rec["quarter"] = {"error": str(e)}
    try:
        v = json.load(open(REC["value"], encoding="utf-8"))
        rec["value"] = {"tercile": v["factors"].get("per_pct"), "lo30": v["flags"].get("PER 자기 역사 하위 30%"),
                        "hi30": v["flags"].get("PER 자기 역사 상위 30%"), "mtime": dt.datetime.fromtimestamp(os.path.getmtime(REC["value"])).isoformat(timespec="minutes")}
    except Exception as e:
        rec["value"] = {"error": str(e)}
    try:
        s = json.load(open(REC["synergy"], encoding="utf-8"))
        rec["synergy"] = {"tercile": s["terciles"].get("per_pct"), "ic": s["factors"].get("per_pct"), "at": s.get("at"), "n": s.get("n"), "firms": s.get("firms")}
    except Exception as e:
        rec["synergy"] = {"error": str(e)}
    rep["records"] = rec

    def cand(r):
        return (r.get("per") is not None and r["per"] <= 200 and r.get("ni_yoy") is not None and r["ni_yoy"] >= -5
                and r.get("dd") is not None and r["dd"] <= -25)
    subs = [("전 종목(H1)", lambda r: True),
            ("저평가 후보(흑자 · 순이익 −5% 이내 · 고점 −25%↓)", cand),
            ("흑자 · 고점 −25%↓ 전체", lambda r: r.get("per") is not None and r.get("dd") is not None and r["dd"] <= -25),
            ("흑자 · 고점 −25% 안쪽(안 빠짐)", lambda r: r.get("per") is not None and r.get("dd") is not None and r["dd"] > -25),
            ("잔고 1년 > 0(blog_yoy)", lambda r: r.get("blog_yoy") is not None and r["blog_yoy"] > 0),
            ("잔고 1년 ≤ 0", lambda r: r.get("blog_yoy") is not None and r["blog_yoy"] <= 0)]
    rep["subs"] = {}
    log("\n== (3) 같은 패널 · 같은 H1 문턱(per_pct <25 / >75)으로 부분 표본 — 부호는 '싼 − 비싼'(+ = 싼 쪽이 이김)")
    for nm, f in subs:
        sub = [r for r in h1rows if f(r)]
        h = bucket_test(sub, "b_h1", "ex12m", nb)
        et = eps_table(sub, "b_h1", 0)
        pt = pooled_tercile(sub, lambda r: r.get("per_pct"))
        rep["subs"][nm] = {"h1": h, "eps": et, "pooled_tercile_top_minus_bot": pt}
        bb = h["b"]
        log("  %-40s 싼 %s(n %d) 보통 %s(n %d) 비싼 %s(n %d) · 싼−비싼 %s [%s, %s] 앞 %s 뒤 %s · 싼−보통 %s | 4분기 뒤 순이익 중앙 싼 %s%% 보통 %s%% 비싼 %s%% (싼 적자 전환 %s%%) | 합친 ⅓ 위−아래 %s"
            % (nm, fmt(bb["cheap"].get("med")), bb["cheap"]["n"], fmt(bb["mid"].get("med")), bb["mid"]["n"], fmt(bb["exp"].get("med")), bb["exp"]["n"],
               fmt(h["diff"]), fmt(h["ci"][0]), fmt(h["ci"][1]), fmt(h["diff_early"]), fmt(h["diff_late"]), fmt(h["diff_cheap_mid"]["all"]),
               fmt(et["cheap"]["med"]), fmt(et["mid"]["med"]), fmt(et["exp"]["med"]), fmt(et["cheap"]["loss"], 1, False),
               fmt((pt or {}).get("top_minus_bot"))))
    # 시너지 패널(월말 줄 · 수주잔고 공시 회사) — 정정 뺀 · 둔화 뺀
    try:
        SP = json.load(open(SYN_PANEL, encoding="utf-8"))
    except Exception:
        SP = []
    sp = [r for r in SP if r.get("ex12m") is not None and not r.get("amended_after")]
    for r in sp:
        r["b_h1"] = bucket(r.get("per_pct"))
    spk = {(r["code"], r["t"]): r for r in sp}
    for r in sp:
        nx = spk.get((r["code"], str(int(r["t"][:4]) + 1) + r["t"][4:]))
        n0 = r.get("ni4")
        r["dni"] = (nx["ni4"] / n0 - 1) if (n0 and n0 > 0 and nx and nx.get("ni4") is not None) else None
        r["loss_next"] = (nx["ni4"] <= 0) if r["dni"] is not None else None
        r["dni_adj"] = None
        r["has_next"] = nx is not None
    rep["synergy_recalc"] = {}
    for nm, f in (("시너지 패널 전체(정정 뺀)", lambda r: True), ("시너지 패널 둔화 뺀", lambda r: r.get("stage") != "둔화"),
                  ("시너지 패널 둔화만", lambda r: r.get("stage") == "둔화")):
        sub = [r for r in sp if f(r) and r.get("b_h1") is not None]
        h = bucket_test(sub, "b_h1", "ex12m", nb)
        et = eps_table(sub, "b_h1", 0)
        rep["synergy_recalc"][nm] = {"h1": h, "eps": et}
        bb = h["b"]
        log("  %-40s 싼 %s(n %d) 보통 %s(n %d) 비싼 %s(n %d) · 싼−비싼 %s [%s, %s] 앞 %s 뒤 %s · 싼−보통 %s | 1년 뒤 순이익 중앙 싼 %s%% 보통 %s%% 비싼 %s%% (싼 적자 전환 %s%%)"
            % (nm, fmt(bb["cheap"].get("med")), bb["cheap"]["n"], fmt(bb["mid"].get("med")), bb["mid"]["n"], fmt(bb["exp"].get("med")), bb["exp"]["n"],
               fmt(h["diff"]), fmt(h["ci"][0]), fmt(h["ci"][1]), fmt(h["diff_early"]), fmt(h["diff_late"]), fmt(h["diff_cheap_mid"]["all"]),
               fmt(et["cheap"]["med"]), fmt(et["mid"]["med"]), fmt(et["exp"]["med"]), fmt(et["cheap"]["loss"], 1, False)))
    log("\n  기록(그대로 옮김):")
    qr = rec.get("quarter", {})
    if "lo30" in qr:
        log("    분기변화(전 종목 · 공시일 · 30%% 문턱, 해당 − 나머지): 하위 30%% %s [%s, %s] 앞 %s 뒤 %s (n %d) · 상위 30%% %s [%s, %s] 앞 %s 뒤 %s (n %d)"
            % (fmt(qr["lo30"]["diff"]), fmt(qr["lo30"]["ci"][0]), fmt(qr["lo30"]["ci"][1]), fmt(qr["lo30"]["early"]), fmt(qr["lo30"]["late"]), qr["lo30"]["n_on"],
               fmt(qr["hi30"]["diff"]), fmt(qr["hi30"]["ci"][0]), fmt(qr["hi30"]["ci"][1]), fmt(qr["hi30"]["early"]), fmt(qr["hi30"]["late"]), qr["hi30"]["n_on"]))
    vr = rec.get("value", {})
    if vr.get("tercile"):
        t_ = vr["tercile"]
        log("    저평가 후보 안(%s 판 · 합친 ⅓, 위 − 아래 = 비싼 − 싼): %s [%s, %s] 앞 %s 뒤 %s (n %d · %d곳)" % (
            vr["mtime"], fmt(t_["spread"]), fmt(t_["ci"][0]), fmt(t_["ci"][1]), fmt(t_["early"]), fmt(t_["late"]), t_["n"], t_["firms"]))
    sr = rec.get("synergy", {})
    if sr.get("tercile"):
        t_ = sr["tercile"]
        ns = t_.get("no_slow") or {}
        log("    시너지(%s 판 · 날짜 안 ⅓, 위 − 아래 = 비싼 − 싼): 전체 %s [%s, %s] 앞 %s 뒤 %s (n %d · %d곳) · 둔화 뺀 %s [%s, %s] 앞 %s 뒤 %s (n %d)" % (
            sr.get("at"), fmt(t_["spread"]), fmt(t_["ci"][0]), fmt(t_["ci"][1]), fmt(t_["early"]), fmt(t_["late"]), t_["n"], t_["firms"],
            fmt(ns.get("spread")), fmt((ns.get("ci") or [None])[0]), fmt((ns.get("ci") or [None, None])[1]), fmt(ns.get("early")), fmt(ns.get("late")), ns.get("n") or 0))
    rep["elapsed_s"] = (dt.datetime.now() - t0).total_seconds()
    log("\n끝 · 경과 %s" % (dt.datetime.now() - t0))
    return rep, lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="report.json 을 쓸 폴더(없으면 표준출력만)")
    ap.add_argument("--boot", type=int, default=1000, help="부트스트랩 횟수(H1 · 나머지는 절반)")
    ap.add_argument("--live", action="store_true", help="실전 맥락(지금 풍경 · 4분기 뒤 순이익 · 저평가/시너지 기록 대조) → live.json")
    args = ap.parse_args()
    if args.live:
        rep, lines = run_live(args)
        if args.out:
            os.makedirs(args.out, exist_ok=True)
            json.dump(rep, open(os.path.join(args.out, "live.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
            print("저장: " + os.path.join(args.out, "live.json"), flush=True)
        return
    rep, lines = run(args)
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        json.dump(rep, open(os.path.join(args.out, "report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
        with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8") as f:
            f.write("# 보통 값 백테스트 — 실행 표(도구/보통값_백테스트.py 출력 그대로)\n\n```text\n" + "\n".join(lines) + "\n```\n")
        print("저장: " + os.path.join(args.out, "report.json") + " · report.md", flush=True)


if __name__ == "__main__":
    main()

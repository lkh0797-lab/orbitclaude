# -*- coding: utf-8 -*-
"""
'억울한 낙폭' 점수 기준을 데이터로 정한다.

매달 말(2013.06~2025.09) 그 시점에 이미 공시된 정기보고서만으로 관문을 다시 세운다(미래 정보 차단).
  잔고   수주잔고 검산 신뢰 · 꾸준히 증가 또는 1년 +15% · 북투빌 ≥ 1 · 잔고 ≥ 연매출 15%
  돈     4분기 영업이익·순이익 흑자 · 3년 누적 영업CF 흑자 · 순차입/자본 ≤ 100% · 매출 −5% 이내 · 이익률 −5%p 이내
  하락   52주 고점 대비 −20%↓
  이익   고점 무렵 대비 4분기 순이익 −5% 이내
그 뒤 6·12개월 수익률을 같은 기간 전 종목 수익률 중앙값과 비교한다(초과수익).
항목마다 날짜별 순위상관(IC)을 구해 평균하고, 앞뒤 기간(2013~2019 / 2020~2025)에서 부호가 같은지 본다.

한계
  - 주주가치 관문(공시 판정)은 과거 3년 치 DART 목록을 날짜마다 다시 받아야 해서 뺐다.
  - 종목은 지금 상장된 회사만 있다(상장폐지된 회사 없음 → 생존 편향). 항목끼리 비교는 덜 휘지만 수익률 수준은 부풀어 있다.
  - PER 자기 역사는 '수정주가 ÷ 4분기 순이익'으로 근사했다(증자로 주식 수가 늘면 싸게 보인다).
  - 매달 표본이라 12개월 수익률 구간이 겹친다. t 값은 겹침(12배)을 감안해 줄였다.

실행: python 도구/억울_백테스트.py        (뷰어 서버 모듈과 캐시를 그대로 쓴다. 네트워크 없이 캐시만 읽는다)
결과: 표준출력 + .cache/dip/bt_panel.json(표본) + .cache/dip/bt_report.json(요약, 화면이 읽는다)
"""
import os
import sys
import json
import math
import bisect
import datetime as dt
import statistics as st
import functools
import importlib.util

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
_spec = importlib.util.spec_from_file_location("srv", os.path.join(BASE, "서버.py"))
S = importlib.util.module_from_spec(_spec)
_argv, sys.argv = sys.argv, ["x"]
_spec.loader.exec_module(S)
sys.argv = _argv
S.INDEX.update(json.load(open(S.INDEX_PATH, encoding="utf-8")))

OUT = os.path.join(S.CACHE_DIR, "dip")
H = {"6m": 182, "12m": 365}
SPLIT = "20200101"        # 앞 기간 / 뒤 기간 경계


def ds(d):
    return d.strftime("%Y%m%d")


@functools.lru_cache(maxsize=None)
def shift(d, days):
    return ds(dt.datetime.strptime(d, "%Y%m%d") + dt.timedelta(days=days))


def month_ends(a, b):
    y, m = a
    out = []
    while (y, m) <= b:
        nx = dt.date(y + (m == 12), m % 12 + 1, 1)
        out.append(ds(nx - dt.timedelta(days=1)))
        y, m = nx.year, nx.month
    return out


DATES = month_ends((2013, 6), (2025, 9))

# ---------------------------------------------------------------- 주가
PX = {}
for f in os.listdir(os.path.join(S.CACHE_DIR, "price")):
    try:
        s = json.load(open(os.path.join(S.CACHE_DIR, "price", f), encoding="utf-8"))
    except Exception:
        continue
    if s:
        ks = sorted(s)
        PX[f[:-5]] = (ks, [s[k] for k in ks])


def px_at(code, d, stale=10):
    ks, vs = PX.get(code, ((), ()))
    i = bisect.bisect_right(ks, d) - 1
    if i < 0 or shift(ks[i], stale) < d:
        return None, None
    return vs[i], ks[i]


def ret(code, d0, d1):
    a, _ = px_at(code, d0)
    b, _ = px_at(code, d1)
    return (b / a - 1) * 100 if (a and b) else None


SMAP = (S.sector_map() or {}).get("stocks", {})
IND = {c: (SMAP.get(c.upper(), {}) or {}).get("industry") or "" for c in PX}
GROUPS = {"__all__": list(PX)}
for c, g in IND.items():
    if g:
        GROUPS.setdefault(g, []).append(c)
_GR = {}


def grp_ret(g, d0, d1, skip=None):
    key = (g, d0, d1, skip)
    if key in _GR:
        return _GR[key]
    rs = [r for c in GROUPS.get(g, []) if c != skip for r in [ret(c, d0, d1)] if r is not None]
    v = st.median(rs) if len(rs) >= 5 else None
    _GR[key] = v
    return v


# ---------------------------------------------------------------- 회사별 시점 자료
Q_MON = {"03": 1, "06": 2, "09": 3, "12": 4}


def prep(c):
    code = c["code"]
    corp = S.corp_code_of(code)
    if not corp or code not in PX:
        return None
    fd = {}
    for r in c["reports"]:
        y, m = r["stamp"].split("-")
        q = Q_MON.get(m)
        if q and not r["tag"] and (int(y), q) not in fd:
            fd[(int(y), q)] = r["rcept"][:8]
    try:
        B = S.BACK.company_series(c, S.read_section, max_reports=80)
    except Exception:
        B = []
    B = [dict(b, date=b["rcept"][:8]) for b in B if b.get("value")]
    B.sort(key=lambda b: b["date"])
    if len(B) < 5:
        return None
    try:
        Q = S.DRK.series(corp, code, list(range(2011, 2027)))
    except Exception:
        return None
    for i, p in enumerate(Q):
        w = Q[max(0, i - 3):i + 1]
        ok = len(w) == 4 and all(x["year"] * 4 + x["q"] == w[0]["year"] * 4 + w[0]["q"] + k for k, x in enumerate(w))
        p["ni4"] = sum(x["당기순이익"] for x in w) if ok and all(x.get("당기순이익") is not None for x in w) else None
        p["op4"] = sum(x["영업이익"] for x in w) if ok and all(x.get("영업이익") is not None for x in w) else None
        p["rev4"] = sum(x["매출액"] for x in w) if ok and all(x.get("매출액") for x in w) else None
        base = dt.date(p["year"], p["q"] * 3, 1)
        p["fdate"] = fd.get((p["year"], p["q"])) or shift(ds(base), 45 + (45 if p["q"] == 4 else 0) + 30)
    try:
        F = S.INF.fundamentals(S.FIN, corp, list(range(2010, 2026)))
    except Exception:
        F = []
    for a in F:
        a["fdate"] = fd.get((a["year"], 4)) or "%d0331" % (a["year"] + 1)
    return {"code": code, "name": c["name"], "B": B, "Q": Q, "F": F, "ind": IND.get(code, "")}


def q_at(Q, t, back=0):
    k = [p for p in Q if p["fdate"] <= t]
    return k[-1 - back] if len(k) > back else None


def evaluate(P, t):
    """시점 t 의 관문 판정과 항목 값. 잔고 관문을 못 넘으면 None."""
    Bt = [b for b in P["B"] if b["date"] <= t]
    if len(Bt) < 5 or shift(Bt[-1]["date"], 200) < t:
        return None
    tr = S.BACK.trend(Bt)
    if not tr or tr.get("yoy") is None:
        return None
    Q = P["Q"]
    qn = q_at(Q, t)
    if not qn or shift(qn["fdate"], 200) < t or not qn.get("rev4"):
        return None
    k = [p for p in Q if p["fdate"] <= t]
    q4 = k[-5] if len(k) >= 5 else None
    rev = qn["rev4"]
    last, yoy = tr["last"], tr["yoy"]
    b1 = last / (1 + yoy / 100) if yoy > -100 else None
    btb = (1 + (last - b1) / rev) if b1 else None
    cover = last / rev
    win = Bt[-8:]
    sure = sum(1 for b in win if b.get("verified") or b.get("method") == "문장")
    reliable = tr["n"] >= 4 and not tr.get("jumps") and sure >= (len(win) + 1) // 2 and cover >= 0.15
    g1 = reliable and (tr["steady"] or yoy >= 15) and btb is not None and btb >= 1
    if not g1:
        return None
    # 돈
    rev_yoy = (rev / q4["rev4"] - 1) * 100 if (q4 and q4.get("rev4")) else None
    m_now = qn["op4"] / rev * 100 if qn.get("op4") is not None else None
    m_old = q4["op4"] / q4["rev4"] * 100 if (q4 and q4.get("op4") is not None and q4.get("rev4")) else None
    md = (m_now - m_old) if (m_now is not None and m_old is not None and abs(m_now) < 100) else None
    Fk = [a for a in P["F"] if a["fdate"] <= t]
    cfo3 = sum(a["cfo"] for a in Fk[-3:] if a.get("cfo") is not None) if Fk else None
    lf = Fk[-1] if Fk else {}
    nd_eq = (((lf.get("debt") or 0) - (lf.get("cash") or 0)) / lf["eq"] * 100) if (lf.get("eq") and lf["eq"] > 0) else None
    core = bool(qn.get("op4") and qn["op4"] > 0 and qn.get("ni4") and qn["ni4"] > 0
                and (nd_eq is None or nd_eq <= 100) and (rev_yoy is None or rev_yoy >= -5) and (md is None or md >= -5))
    cfo_ok = cfo3 is not None and cfo3 > 0
    money = core and cfo_ok
    # 하락
    ks, vs = PX[P["code"]]
    i1 = bisect.bisect_right(ks, t) - 1
    if i1 < 0 or shift(ks[i1], 10) < t:
        return None
    i0 = bisect.bisect_left(ks, shift(t, -365))
    if i1 - i0 < 120:
        return None
    j = max(range(i0, i1 + 1), key=lambda x: vs[x])
    hi_d, dd = ks[j], (vs[i1] / vs[j] - 1) * 100
    # 이익 버팀 · 값 매김
    e_chg = rerate = None
    qh = q_at(Q, hi_d)
    if qh:
        e0, e1 = qh.get("ni4"), qn.get("ni4")
        if e0 and e1 and e0 > 0 and e1 > 0:
            e_chg = (e1 / e0 - 1) * 100
        else:
            o0, o1 = qh.get("op4"), qn.get("op4")
            if o0 and o1 and o0 > 0 and o1 > 0:
                e_chg = (o1 / o0 - 1) * 100
    if e_chg is not None:
        rerate = ((1 + dd / 100) / (1 + e_chg / 100) - 1) * 100
    # 시장·업종 (고점일 → t)
    m_ret = grp_ret("__all__", hi_d, t) if dd <= -10 else None
    i_ret = grp_ret(P["ind"], hi_d, t, skip=P["code"]) if (dd <= -10 and P["ind"]) else None
    base = [x for x in (m_ret, i_ret) if x is not None]
    macro = (m_ret is not None and m_ret <= -8) or (i_ret is not None and i_ret <= -10)
    excess = (dd - min(base + [0])) if base else None       # 음수일수록 회사만 더 빠졌다
    worse = excess is not None and excess < -25
    # PER 자기 역사(근사) — 수정주가 ÷ 4분기 순이익, 지난 10년 분기 공시일 값과 비교
    pct = None
    if qn.get("ni4") and qn["ni4"] > 0:
        r_now = vs[i1] / qn["ni4"]
        hist = []
        for p in Q:
            if p["fdate"] >= t or p["fdate"] < shift(t, -3650) or not p.get("ni4") or p["ni4"] <= 0:
                continue
            px, _ = px_at(P["code"], p["fdate"])
            if px:
                hist.append(px / p["ni4"])
        if len(hist) >= 8:
            pct = sum(1 for h in hist if h <= r_now) / len(hist) * 100
    # 앞으로의 수익률(초과)
    fw = {}
    for h, days in H.items():
        t1 = shift(t, days)
        r = ret(P["code"], t, t1)
        u = grp_ret("__all__", t, t1)
        fw["ret" + h] = r
        fw["ex" + h] = (r - u) if (r is not None and u is not None) else None
    return {"code": P["code"], "name": P["name"], "t": t, "ind": P["ind"],
            "yoy": yoy, "steady": tr["steady"], "btb": btb, "cover": cover,
            "money": money, "core": core, "cfo_ok": cfo_ok, "rev_yoy": rev_yoy, "margin": m_now, "md": md, "cfo3": cfo3, "nd_eq": nd_eq,
            "dd": dd, "hi_d": hi_d, "e_chg": e_chg, "rerate": rerate,
            "m_ret": m_ret, "i_ret": i_ret, "macro": macro, "excess": excess, "worse": worse, "pct": pct, **fw}


def old_score(r):
    """지금 화면 점수(주의 항목은 값 매김·시장 동반·업종보다 더 빠짐 세 가지만 근사)."""
    soft = sum([(r["rerate"] or 0) > -15, not r["macro"], bool(r["worse"])])
    s = min(r["yoy"] or 0, 100) * 0.35 + min(r["btb"] or 0, 3) * 8
    s += min(-(r["dd"] or 0), 60) * 0.5 + max(min(-(r["rerate"] or 0), 70), 0) * 0.6
    s += max(min(r["e_chg"] or 0, 60), -5) * 0.3
    if r["pct"] is not None:
        s += (50 - r["pct"]) * 0.25
    s += 6 if r["macro"] else 0
    return s - 5 * soft


# ---------------------------------------------------------------- 통계
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
    rx, ry = rank([float(v) for v in x]), rank(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((i - mx) * (j - my) for i, j in zip(rx, ry))
    den = math.sqrt(sum((i - mx) ** 2 for i in rx) * sum((j - my) ** 2 for j in ry))
    return num / den if den else None


def ic_stats(rows, fx, y, overlap):
    by = {}
    for r in rows:
        by.setdefault(r["t"], []).append(r)
    ics = []
    for t, rs in sorted(by.items()):
        v = spear([fx(r) for r in rs], [r[y] for r in rs])
        if v is not None:
            ics.append((t, v))
    if len(ics) < 6:
        return None
    vals = [v for _, v in ics]
    m = sum(vals) / len(vals)
    sd = st.pstdev(vals) or 1e-9
    n_eff = max(len(vals) / overlap, 1)
    early = [v for t, v in ics if t < SPLIT]
    late = [v for t, v in ics if t >= SPLIT]
    return {"ic": m, "t": m / (sd / math.sqrt(n_eff)), "n_dates": len(vals), "pos": sum(v > 0 for v in vals) / len(vals),
            "early": sum(early) / len(early) if early else None, "late": sum(late) / len(late) if late else None}


def summ(rows, y):
    v = [r[y] for r in rows if r[y] is not None]
    if not v:
        return None
    return {"n": len(v), "firms": len({r["code"] for r in rows if r[y] is not None}), "mean": sum(v) / len(v),
            "median": st.median(v), "hit": sum(x > 0 for x in v) / len(v) * 100}


def quint(rows, fx, y):
    """날짜마다 다섯 묶음으로 나눈 뒤 묶음별 평균 초과수익을 모은다(표본이 적은 날은 셋)."""
    by = {}
    for r in rows:
        if fx(r) is not None and r[y] is not None:
            by.setdefault(r["t"], []).append(r)
    acc = {}
    for rs in by.values():
        if len(rs) < 5:
            continue
        rs = sorted(rs, key=fx)
        for i, r in enumerate(rs):
            b = min(int(i / len(rs) * 5), 4)
            acc.setdefault(b, []).append(r[y])
    return [round(sum(acc[b]) / len(acc[b]), 1) if acc.get(b) else None for b in range(5)]


FACTORS = [   # (키, 이름, 값 함수) — 값이 클수록 좋다고 보는 방향이 아니라 날것 그대로. IC 부호로 방향을 읽는다
    ("yoy", "잔고 1년 증가율", lambda r: min(r["yoy"], 300)),
    ("btb", "북투빌", lambda r: min(r["btb"], 5) if r["btb"] is not None else None),
    ("cover", "잔고/연매출(년치)", lambda r: min(r["cover"], 10)),
    ("dd", "고점 대비 낙폭(음수)", lambda r: r["dd"]),
    ("e_chg", "그 사이 이익 변화", lambda r: min(r["e_chg"], 200) if r["e_chg"] is not None else None),
    ("rerate", "값 매김 변화(음수)", lambda r: r["rerate"]),
    ("pct", "PER 자기 역사 백분위", lambda r: r["pct"]),
    ("excess", "시장·업종 대비 추가 낙폭", lambda r: r["excess"]),
    ("m_ret", "같은 기간 시장", lambda r: r["m_ret"]),
    ("i_ret", "같은 기간 업종", lambda r: r["i_ret"]),
    ("rev_yoy", "매출 1년(4분기 합)", lambda r: max(min(r["rev_yoy"], 200), -50) if r["rev_yoy"] is not None else None),
    ("margin", "영업이익률", lambda r: max(min(r["margin"], 60), -20) if r["margin"] is not None else None),
    ("md", "이익률 변화(%p)", lambda r: max(min(r["md"], 30), -30) if r["md"] is not None else None),
    ("nd_eq", "순차입/자본", lambda r: max(min(r["nd_eq"], 200), -200) if r["nd_eq"] is not None else None),
    ("old", "지금 화면 점수", old_score),
]


def one(c):
    """회사 하나의 모든 시점. 캐시 파일 읽기(구글 드라이브)가 대부분이라 여러 갈래로 나란히 돈다."""
    try:
        P = prep(c)
    except Exception as e:
        print("  건너뜀", c.get("code"), e, flush=True)
        return []
    out = []
    if P:
        for t in DATES:
            try:
                r = evaluate(P, t)
            except Exception:
                r = None
            if r:
                out.append(r)
    return out


def main():
    from concurrent.futures import ThreadPoolExecutor, as_completed
    comps = [c for c in S.INDEX.get("companies", []) if c.get("code")]
    panel = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(one, c) for c in comps]
        for n, f in enumerate(as_completed(futs), 1):
            panel.extend(f.result())
            if n % 50 == 0:
                print("  %d/%d 회사 · 표본 %d" % (n, len(comps), len(panel)), flush=True)
    panel.sort(key=lambda r: (r["t"], r["code"]))
    os.makedirs(OUT, exist_ok=True)
    json.dump(panel, open(os.path.join(OUT, "bt_panel.json"), "w", encoding="utf-8"), ensure_ascii=False)
    report(panel)


# 새 점수 — 이 백테스트에서 (1) 앞뒤 기간 부호가 같고 (2) 회사 단위 부트스트랩 90% 구간이 대체로 0을 비켜 간 항목만.
# (키, 이름, 가중치, 방향) 방향 +1 = 클수록 좋다, −1 = 작을수록 좋다. 점수 = 과거 후보 분포에서의 백분위 가중평균(0~100).
SCORE_W = [
    ("btb", "북투빌", 1.0, +1),
    ("ind", "같은 기간 업종(없으면 시장) 수익률", 1.0, +1),
    ("dd", "고점 대비 낙폭", 1.0, -1),
    ("cover", "잔고 ÷ 연매출", 0.5, +1),
    ("nd_eq", "순차입금 ÷ 자본", 0.5, -1),
]


def fval(r, k):
    if k == "ind":
        return r["i_ret"] if r.get("i_ret") is not None else r.get("m_ret")
    return r.get(k)


def pctile(sv, v):
    if v is None or not sv:
        return None
    return (bisect.bisect_left(sv, v) + bisect.bisect_right(sv, v)) / 2 / len(sv) * 100


def new_score(r, dist):
    tot = w = 0.0
    for k, _, wt, d in SCORE_W:
        p = pctile(dist.get(k), fval(r, k))
        if p is not None:
            tot += (p if d > 0 else 100 - p) * wt
            w += wt
    return tot / w if w else None


def boot(rows, fn, n=800, seed=7):
    """회사 단위 부트스트랩 90% 구간 — 같은 회사가 여러 달 나오는 겹침을 감안."""
    import random
    firms = sorted({r["code"] for r in rows})
    by = {}
    for r in rows:
        by.setdefault(r["code"], []).append(r)
    rnd = random.Random(seed)
    vals = sorted(v for v in (fn([x for f in (rnd.choice(firms) for _ in firms) for x in by[f]]) for _ in range(n)) if v is not None)
    return (vals[int(len(vals) * .05)], vals[int(len(vals) * .95)]) if vals else (None, None)


def tercile_test(rows, fx, y="ex12m"):
    rs = [dict(r, _s=fx(r)) for r in rows if r.get(y) is not None]
    rs = [r for r in rs if r["_s"] is not None]
    if len(rs) < 30:
        return None
    v = sorted(r["_s"] for r in rs)
    a, b = v[len(v) // 3], v[2 * len(v) // 3]

    def spread(sub):
        lo = [r[y] for r in sub if r["_s"] < a]
        hi = [r[y] for r in sub if r["_s"] >= b]
        return st.median(hi) - st.median(lo) if len(lo) > 5 and len(hi) > 5 else None
    top = [r[y] for r in rs if r["_s"] >= b]
    bot = [r[y] for r in rs if r["_s"] < a]
    lo, hi = boot(rs, spread)
    return {"top": st.median(top), "bot": st.median(bot), "top_hit": sum(x > 0 for x in top) / len(top) * 100,
            "spread": spread(rs), "ci": [lo, hi], "n": len(rs), "firms": len({r["code"] for r in rs}),
            "early": spread([r for r in rs if r["t"] < SPLIT]), "late": spread([r for r in rs if r["t"] >= SPLIT])}


def report(panel):
    g1 = panel
    g2 = [r for r in g1 if r["money"]]
    dip = [r for r in g2 if r["dd"] <= -20 and r["e_chg"] is not None and r["e_chg"] >= -5]
    calm = [r for r in g2 if r["dd"] > -10]
    tier_a = [r for r in dip if r["macro"] and not r["worse"] and (r["pct"] is None or r["pct"] < 80)]
    tier_b = [r for r in dip if r not in tier_a]
    fell_earn = [r for r in g2 if r["dd"] <= -20 and r["e_chg"] is not None and r["e_chg"] < -5]
    core = [r for r in g1 if r["core"]]
    dip_core = [r for r in core if r["dd"] <= -20 and r["e_chg"] is not None and r["e_chg"] >= -5]
    dip_nocfo = [r for r in dip_core if not r["cfo_ok"]]
    out = {"dates": [DATES[0], DATES[-1]], "groups": {}, "factors": {}, "factors_g2": {}}
    print("\n== 묶음별 앞으로 수익률(같은 기간 전 종목 중앙값 대비 초과, %)")
    for name, rows in (("잔고 관문 통과", g1), ("+ 돈 관문", g2), ("  그중 주가 안 빠짐(고점 −10% 이내)", calm),
                       ("  그중 −20%↓인데 이익도 −5%↓ 줄어듦", fell_earn),
                       ("억울한 낙폭 후보(잔고·돈·하락·이익)", dip), ("  억울 등급", tier_a), ("  관찰 등급", tier_b),
                       ("후보 — 영업CF 조건 뺀 경우", dip_core), ("  그중 영업CF 3년 적자라 막혔던 곳", dip_nocfo)):
        s6, s12 = summ(rows, "ex6m"), summ(rows, "ex12m")
        out["groups"][name.strip()] = {"6m": s6, "12m": s12}
        if s12:
            print("  %-34s 표본 %5d (%3d곳)  6개월 평균 %+6.1f 중앙 %+6.1f | 12개월 평균 %+6.1f 중앙 %+6.1f 이긴 비율 %4.0f%%" % (
                name, s12["n"], s12["firms"], s6["mean"], s6["median"], s12["mean"], s12["median"], s12["hit"]))
    for label, rows, key in (("억울한 낙폭 후보 안에서", dip, "factors"), ("돈 관문 통과 전체에서", g2, "factors_g2")):
        print("\n== 항목별 예측력 — %s (날짜별 순위상관 평균, 12개월 초과수익)" % label)
        print("  %-22s %7s %6s %6s %8s %8s   다섯 묶음 평균 초과수익(낮은 값 → 높은 값)" % ("항목", "IC", "t", "양수%", "앞기간", "뒷기간"))
        for k, nm, fx in FACTORS:
            s = ic_stats(rows, fx, "ex12m", overlap=12)
            if not s:
                continue
            s6 = ic_stats(rows, fx, "ex6m", overlap=6)
            s["q"] = quint(rows, fx, "ex12m")
            s["ic6"] = s6["ic"] if s6 else None
            out[key][k] = dict(s, name=nm)
            print("  %-22s %+7.3f %+6.2f %5.0f%% %+8.3f %+8.3f   %s" % (
                nm, s["ic"], s["t"], s["pos"] * 100, s["early"] or 0, s["late"] or 0, s["q"]))
    # 새 점수 — 분포 기준점은 과거 '억울한 낙폭 후보' 표본
    dist = {k: sorted(v for v in (fval(r, k) for r in dip) if v is not None) for k, _, _, _ in SCORE_W}
    out["score"] = {"weights": [{"key": k, "name": nm, "w": wt, "dir": d} for k, nm, wt, d in SCORE_W], "dist": dist,
                    "new": tercile_test(dip, lambda r: new_score(r, dist)), "old": tercile_test(dip, old_score),
                    "new_g2": tercile_test(g2, lambda r: new_score(r, dist)), "old_g2": tercile_test(g2, old_score)}
    early = [r for r in dip if r["t"] < SPLIT]
    d_early = {k: sorted(v for v in (fval(r, k) for r in early) if v is not None) for k, _, _, _ in SCORE_W}
    out["score"]["oos"] = tercile_test([r for r in dip if r["t"] >= SPLIT], lambda r: new_score(r, d_early))
    out["tiers"] = {"억울": summ(tier_a, "ex12m"), "관찰": summ(tier_b, "ex12m")}
    out["n_dip"] = len(dip)
    print("\n== 점수 검증 — 후보 안에서 점수 상위⅓ vs 하위⅓ (12개월 초과수익 중앙값)")
    for k, nm in (("old", "지금 점수"), ("new", "새 점수"), ("oos", "새 점수(앞 기간 분포 → 뒤 기간)"), ("old_g2", "지금 점수 · 돈 관문 전체"), ("new_g2", "새 점수 · 돈 관문 전체")):
        x = out["score"].get(k)
        if x:
            print("  %-28s 상위 %+6.1f (이긴 %3.0f%%) 하위 %+6.1f  차이 %+6.1f  90%%CI %s ~ %s  ~2019 %s  2020~ %s" % (
                nm, x["top"], x["top_hit"], x["bot"], x["spread"] or 0,
                "%+.1f" % x["ci"][0] if x["ci"][0] is not None else "—", "%+.1f" % x["ci"][1] if x["ci"][1] is not None else "—",
                "%+.0f" % x["early"] if x["early"] is not None else "—", "%+.0f" % x["late"] if x["late"] is not None else "—"))
    out["at"] = ds(dt.date.today())
    json.dump(out, open(os.path.join(OUT, "bt_report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--report":
        report(json.load(open(os.path.join(OUT, "bt_panel.json"), encoding="utf-8")))
    else:
        main()

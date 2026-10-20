# -*- coding: utf-8 -*-
"""
우량 급락 — 과거 검증 · 민감도 · 최신 후보 (2026-10-20). 잣대 · 문턱은 우량급락.py(TH, 사전 등록 — docs/superpowers/specs/2026-10-20-qualdip-design.md).

사전 등록 주 지표(돌리기 전에 정함): 월말 패널 · 12개월 초과수익 · 달마다 (후보 중앙 − 같은 달 저PER 하위 30% 중앙)의 중앙 ·
  분기 블록과 연 블록 부트스트랩 90% 구간 가운데 넓은 쪽. 구간이 0 위면 '저PER 보다 나았다', 0 아래면 '못했다', 걸치면 '차이를 확신할 수 없다'.
시점: 월말 m 까지 알게 된 분기(탑픽.series_of 엄격 — 정정 포함 접수일)와 m 종가 → 판정, 들어가는 날 = m 다음 거래일 종가.
  초과수익 = 3 · 6 · 12개월 수익률 − 같은 기간 전 종목 중앙(탑픽_백테스트.attach_returns).
기준선(같은 달 · 같은 적격 집합): 저PER 하위 30% · 우량만(①~⑤ · ⑧) · 급락만(⑥) · 우량+급락(⑦ 없이) · 일곱 이상 · 적격 전 종목.
나눠 보기: 시장 급락 달(그달 전 종목 1개월 중앙 ≤ −5%) · 앞(~2019) / 뒤(2020~) · 2026 시총 300 안 / 밖. 민감도: 문턱마다 ×0.5 · ×1.5.
최신 후보: 마지막 시세일까지 → 후보(여덟) · 아깝게(일곱, 빠진 관문) · 원본 12종목의 지금 · 돈의 흐름(섹터 · 업종 · 테마).
재료 — 캐시만(네트워크 없음): .cache/druck · .cache/색인.json · .cache/price · 종목.txt · .cache/거시/induty.json · .cache/업종/map.json.
한계 — 잣대는 12종목 · 하루 단면에서 역산(시간으로는 표본 밖, 종목 수는 작다) · 지금 상장된 회사만(생존 편향) · 주식 수 역산 · 월말 12개월 창 겹침.

실행: py -3.13 -X utf8 도구/우량급락_백테스트.py            (전부 — 5분 안팎)
      py -3.13 -X utf8 도구/우량급락_백테스트.py --latest   (최신 후보만 — 1분 안팎)
      --asof YYYYMMDD · --boot N(기본 600) · --out 폴더 · --codes 쉼표(시험용)
결과: .cache/qualdip/bt.json · bt.md · latest.json · panel_cand.json
"""
import os, sys, json, time, math, random, argparse, datetime as dt, statistics as st, importlib.util as ilu

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
CACHE = os.path.join(BASE, ".cache")
OUT = os.path.join(CACHE, "qualdip")
START = "20140101"
SPLIT = "20200101"
CRASH_M = -5.0          # 시장 급락 달 — 그달 전 종목 1개월 수익 중앙 ≤ 이 값(%)
PRIMARY = "월말 패널 · 12개월 · 달마다 (후보 중앙 − 같은 달 저PER 하위 30% 중앙)의 중앙 · 분기 / 연 블록 부트스트랩 90% 구간 가운데 넓은 쪽"
ORIGIN = {"016360": "삼성증권", "071050": "한국금융지주", "009450": "경동나비엔", "326030": "SK바이오팜", "271560": "오리온", "000270": "기아",
          "214150": "클래시스", "021240": "코웨이", "259960": "크래프톤", "453340": "현대그린푸드", "111770": "영원무역", "035900": "JYP Ent."}


def _load(name, file):
    sp = ilu.spec_from_file_location(name, os.path.join(BASE, file))
    m = ilu.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


T = _load("탑픽", "탑픽.py")
Q = _load("우량급락", "우량급락.py")
TB = _load("탑픽_백테스트", os.path.join("도구", "탑픽_백테스트.py"))


def log(*a):
    print(*a, flush=True)


def qkey(d):
    return int(d[:4]) * 4 + (int(d[4:6]) - 1) // 3


# ---------------------------------------------------------------- 한 회사 · 한 날 특징 행
def row_of(code, ser, d, P, V, ksic):
    """d 까지 알게 된 분기 · d 종가로 특징 행. 최근 보고서가 150일 넘게 묵었거나 신호 분기가 어긋나면 elig False(관문은 그래도 센다 — 화면 설명용)."""
    K = T.known_until(ser, d)
    if not K:
        return None

    def pxf(x):
        return P.at(code, x)[0]
    m = T.metrics(ser, d, pxf, tv=None)
    if m is None:
        return None
    f = Q.fund(K, pxf)
    last = K[-1]
    stale = T.days_between(last["known"], d) > T.STALE_FIN
    r = {"code": code, "date": d, "lab": f["lab"], "known": f["known"], "mcap": m["mcap"], "mcap_g": m["mcap_g"],
         "lmcap": math.log10(m["mcap"]) if m["mcap"] else None, "per": m["per"], "por": m["por"], "por_pct": (m["por_pct"] or {}).get(20),
         "per_pct": Q.per_pct(f["per_hist"], m["per"]), "r3m": P.ret(code, T.shift(d, -91), d), "r1m": P.ret(code, T.shift(d, -30), d),
         "dd52": None, "vol": V.vol(code, d), "ksic": ksic.get(code) or "",
         "elig": bool(m["mcap"]) and not stale and last["valid"]}
    for k in ("loss_q12", "nq12", "op_cv12", "ttm_min_max", "ttm_cagr3", "rev_cagr3", "opm", "roe"):
        r[k] = f[k]
    return r


def day_rows(codes, ser, d, P, V, ksic, th=Q.TH):
    rows = [x for x in (row_of(c, ser[c], d, P, V, ksic) for c in codes if c in ser) if x]
    U = [r for r in rows if r["elig"]]
    Q.cross_section(U, th)
    Q.score_rows(U)
    return rows, U


# ---------------------------------------------------------------- 패널
def monthly_panel(codes, ser, P, V, ksic, T1, dates):
    out, crash = [], {}
    t0 = time.time()
    for i, m in enumerate(dates):
        _, U = day_rows(codes, ser, m, P, V, ksic)
        r1 = [r["r1m"] for r in U if r.get("r1m") is not None]
        crash[m] = st.median(r1) if r1 else None
        for r in U:
            r["s"] = P.next_day(r["code"], m)
            r["n"] = qkey(m)
            TB.attach_returns(P, r, codes, T1)
            r["crash"] = crash[m] is not None and crash[m] <= CRASH_M
            out.append(r)
        if (i + 1) % 24 == 0:
            log("  월말 %d/%d  행 %d  %.0f초" % (i + 1, len(dates), len(out), time.time() - t0))
    return out, crash


# ---------------------------------------------------------------- 통계
def month_pairs(cand, base, key="ex12m", min_n=3, nboot=800):
    """달마다 후보 중앙 − 기준선 중앙 → {n_months, wins, diff_med, ci_q(분기 블록), ci_y(연 블록), ci(넓은 쪽), months}."""
    bc, bb = {}, {}
    for r in cand:
        if r.get(key) is not None:
            bc.setdefault(r["date"], []).append(r[key])
    for r in base:
        if r.get(key) is not None:
            bb.setdefault(r["date"], []).append(r[key])
    rows = [[d, st.median(bc[d]) - st.median(bb[d]), len(bc[d]), len(bb[d])] for d in sorted(set(bc) & set(bb))
            if len(bc[d]) >= min_n and len(bb[d]) >= min_n]
    if not rows:
        return {"n_months": 0, "wins": 0, "diff_med": None, "ci": [None, None], "ci_q": [None, None], "ci_y": [None, None], "months": []}

    def boot(blockf, seed):
        by = {}
        for d, v, _, _ in rows:
            by.setdefault(blockf(d), []).append(v)
        blocks = list(by)
        rnd = random.Random(seed)
        vals = sorted(st.median([v for b in (rnd.choice(blocks) for _ in blocks) for v in by[b]]) for _ in range(nboot))
        return [vals[int(len(vals) * .05)], vals[int(len(vals) * .95)]]
    ci_q, ci_y = boot(qkey, 21), boot(lambda d: d[:4], 23)
    diffs = [x[1] for x in rows]
    return {"n_months": len(rows), "wins": sum(1 for v in diffs if v > 0), "diff_med": st.median(diffs), "diff_mean": sum(diffs) / len(diffs),
            "ci_q": ci_q, "ci_y": ci_y, "ci": [min(ci_q[0], ci_y[0]), max(ci_q[1], ci_y[1])],
            "months": [[d, round(v, 2), a, b] for d, v, a, b in rows]}


def verdict(pp):
    if not pp or pp.get("diff_med") is None:
        return "검증 전"
    lo, hi = pp["ci"]
    if lo is not None and lo > 0:
        return "저PER 보다 나았다"
    if hi is not None and hi < 0:
        return "저PER 보다 못했다"
    return "저PER 과 차이를 확신할 수 없다"


def groups(MR, th=Q.TH):
    by = {}
    for r in MR:
        by.setdefault(r["date"], []).append(r)
    low30 = []
    for d, rs in by.items():
        pe = sorted([r for r in rs if r.get("per") is not None and r["per"] > 0], key=lambda r: r["per"])
        if pe:
            low30.extend(pe[:max(1, int(len(pe) * 0.3))])
    G = {"후보(여덟 다)": [r for r in MR if r["n_pass"] == 8],
         "일곱 이상": [r for r in MR if r["n_pass"] >= 7],
         "우량만(①~⑤ · ⑧)": [r for r in MR if all(r["gates"][k] for k in Q.QUALITY)],
         "우량 + 급락(⑦ 없이)": [r for r in MR if all(r["gates"][k] for k in Q.QUALITY) and r["gates"]["drop"]],
         "급락만(⑥)": [r for r in MR if r["gates"]["drop"]],
         "저PER 하위 30%": low30,
         "적격 전 종목": MR}
    return G


def sensitivity(MR, nboot):
    out = []
    for name, t in Q.sens_variants():
        cand = [r for r in MR if all(Q.gates(r, t).values())]
        s = TB.stats(cand, 0, ci=False)
        nd = {}
        for r in cand:
            nd[r["date"]] = nd.get(r["date"], 0) + 1
        dates = sorted({r["date"] for r in MR})
        s.update(name=name, th=t, per_month=(sum(nd.get(d, 0) for d in dates) / len(dates)) if dates else None,
                 months_with=sum(1 for d in dates if nd.get(d)))
        out.append(s)
    return out


def split_stats(rows, key_fn):
    by = {}
    for r in rows:
        k = key_fn(r)
        if k is not None:
            by.setdefault(k, []).append(r)
    return {str(k): TB.stats(v, 0, ci=False) for k, v in sorted(by.items(), key=lambda x: str(x[0]))}


def ic_mean(rows, key="ex12m"):
    by = {}
    for r in rows:
        if r.get("score") is not None and r.get(key) is not None:
            by.setdefault(r["date"], []).append((r["score"], r[key]))
    ics = [v for xs in by.values() for v in [TB.spear([a for a, _ in xs], [b for _, b in xs])] if v is not None]
    return {"ic": (sum(ics) / len(ics)) if ics else None, "dates": len(ics), "pos": (sum(1 for v in ics if v > 0) / len(ics) * 100) if ics else None}


# ---------------------------------------------------------------- 최신 후보
SLIM = ("code", "date", "lab", "known", "mcap", "mcap_g", "per", "per_pct", "por", "por_pct", "r3m", "r1m", "vol", "vol_pct", "loss_q12", "nq12", "op_cv12",
        "ttm_min_max", "ttm_cagr3", "rev_cagr3", "opm", "roe", "cap_rank", "gates", "n_pass", "miss", "score", "parts", "ksic", "elig")


def latest(codes, ser, P, V, ksic, idx, univ, sectors, asof=None):
    last_px = max((P.last_date(c) for c in codes if P.last_date(c)), default=None)
    d = asof or last_px
    rows, U = day_rows(codes, ser, d, P, V, ksic)
    for r in rows:
        r["name"] = (idx.get(r["code"]) or {}).get("name") or (univ.get(r["code"]) or {}).get("name") or r["code"]
        sc = sectors.get(r["code"]) or {}
        r.update(sector=sc.get("sector"), industry=sc.get("industry"), themes=sc.get("themes") or [],
                 market=(univ.get(r["code"]) or {}).get("market"), rank26=(univ.get(r["code"]) or {}).get("rank"),
                 px_date=P.at(r["code"], d)[1], hi52=None)
        ks = P.ks.get(r["code"]) or []
        import bisect as _b
        i = _b.bisect_right(ks, d) - 1
        if i >= 0:
            w = P.vs[r["code"]][max(0, i - 251):i + 1]
            r["dd52"] = (w[-1] / max(w) - 1) * 100 if w else None
    slim = lambda r: {k: r.get(k) for k in SLIM + ("name", "sector", "industry", "themes", "market", "rank26", "px_date", "dd52")}     # noqa: E731
    cand = sorted([r for r in U if r["n_pass"] == 8], key=lambda r: -(r["score"] or 0))
    near = sorted([r for r in U if r["n_pass"] == 7], key=lambda r: -(r["score"] or 0))
    counts = {"rows": len(rows), "elig": len(U), "cand": len(cand), "near": len(near)}
    for k, _, _ in Q.GATES:
        counts[k] = sum(1 for r in U if r["gates"][k])
    flow = [{"code": r["code"], "sector": r.get("sector"), "industry": r.get("industry"), "themes": r.get("themes") or [], "elig": True,
             "cand": r["n_pass"] == 8, "earn": all(r["gates"][k] for k in Q.QUALITY), "mcap_g": r.get("mcap_g")} for r in U]
    by = {r["code"]: r for r in rows}
    origin = []
    for c, nm in ORIGIN.items():
        r = by.get(c)
        origin.append(slim(r) if r else {"code": c, "name": nm, "missing": True})
    return {"v": Q.VERSION, "asof": d, "last_px": last_px, "th": dict(Q.TH), "gates": Q.GATES, "counts": counts,
            "rows": [slim(r) for r in cand], "near": [slim(r) for r in near[:80]], "origin": origin,
            "groups": T.flow_groups(flow, {"c1": 30.0}), "at": dt.datetime.now().isoformat(timespec="seconds")}


# ---------------------------------------------------------------- 보고
def fmt(v, d=1):
    return "—" if v is None else ("%+." + str(d) + "f") % v


def pc(v):
    return "—" if v is None else "%d%%" % round(v)


def ci_s(ci):
    return ("%s ~ %s" % (fmt(ci[0]), fmt(ci[1]))) if (ci and ci[0] is not None) else "—"


def md_report(R):
    L = ["# 우량 급락 과거 검증 (%s)\n" % R["at"][:10], "사전 등록 주 지표: %s\n" % PRIMARY]
    pp = R["primary"]
    L.append("**판정: %s** — 달 %d개 가운데 후보가 이긴 달 %d, 달별 차이 중앙 %s (90%% 구간 %s · 분기 블록 %s · 연 블록 %s)\n" % (
        R["verdict"], pp["n_months"], pp["wins"], fmt(pp["diff_med"]), ci_s(pp["ci"]), ci_s(pp["ci_q"]), ci_s(pp["ci_y"])))
    L.append("월말 %s ~ %s · 회사 %d · 시세 마지막 %s · 잣대 우량급락.py v%d · 문턱 고정(TH)\n" % (R["dates"][0], R["dates"][-1], R["n_firms"], R["T1"], Q.VERSION))
    L.append("## 묶음별 (12개월 초과수익 = 같은 기간 전 종목 중앙 대비)\n")
    L.append("| 묶음 | 행 | 회사 | 후보 있던 달 | 3개월 | 6개월 | 12개월 중앙 | 90% 구간(회사) | 90% 구간(분기) | 이긴 비율 | −30%↓ | ~2019 | 2020~ |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---:|")
    for k, s in R["groups"].items():
        L.append("| %s | %d | %d | %d | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            k, s["n12"], s["firms"], s["dates"], fmt(s["med3m"]), fmt(s["med6m"]), fmt(s["med12m"]), ci_s(s.get("ci12")), ci_s(s.get("ci12_season")),
            pc(s["hit"]), pc(s["crash"]), fmt(s["early"]), fmt(s["late"])))
    L.append("\n후보 − 기준선(12개월 중앙 차이):\n")
    L.append("| 기준선 | 차이 | 90% 구간(회사) | 90% 구간(분기) | ~2019 | 2020~ |")
    L.append("|---|---:|---|---|---:|---:|")
    for k, s in R["vs"].items():
        L.append("| %s | %s | %s | %s | %s | %s |" % (k, fmt(s["diff"]), ci_s(s["ci"]), ci_s(s["ci_season"]), fmt(s["early"]), fmt(s["late"])))
    L.append("\n나눠 보기(후보, 12개월 중앙(이긴 비율, 행)):\n")
    for name, sp in R["splits"].items():
        L.append("- %s: " % name + " · ".join("%s %s(%s, %d)" % (k, fmt(v["med12m"]), pc(v["hit"]), v["n12"]) for k, v in sp.items()))
    ic = R["ic"]
    L.append("- 순위 점수(일곱 이상 안): 날짜별 순위상관 평균 %s (양수 %s · 날짜 %d)" % (fmt(ic["ic"], 3), pc(ic["pos"]), ic["dates"]))
    L.append("\n## 민감도 — 문턱 하나씩 ×0.5 · ×1.5 (문턱은 바꾸지 않는다)\n")
    L.append("| 변형 | 행 | 회사 | 달 평균 후보 | 후보 있던 달 | 6개월 | 12개월 중앙 | 이긴 비율 | ~2019 | 2020~ |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for s in R["sens"]:
        L.append("| %s | %d | %d | %s | %d | %s | %s | %s | %s | %s |" % (s["name"], s["n12"], s["firms"], fmt(s["per_month"], 2).lstrip("+"), s["months_with"],
                                                                      fmt(s["med6m"]), fmt(s["med12m"]), pc(s["hit"]), fmt(s["early"]), fmt(s["late"])))
    flips = sum(1 for s in R["sens"] if s.get("med12m") is not None and R["sens"][0].get("med12m") is not None and (s["med12m"] > 0) != (R["sens"][0]["med12m"] > 0))
    L.append("\n12개월 중앙 부호가 기본과 뒤집힌 변형: %d / %d\n" % (flips, len(R["sens"])))
    L.append("## 한계\n")
    L += ["- " + x for x in R["limits"]]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--asof", default=None)
    ap.add_argument("--boot", type=int, default=600)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--codes", default=None)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    univ, _snap = TB.load_universe()
    idx = TB.load_index()
    codes = [c for c in univ if c in idx]
    if a.codes:
        want = set(a.codes.split(","))
        codes = [c for c in codes if c in want]
    corp_of = TB.load_corp_map()
    ksic = TB.load_ksic({c: corp_of.get(c) for c in codes if corp_of.get(c)})
    ser, skipped, _basis, _fy = TB.load_series(codes, idx, {})
    data = {}
    for c in codes:
        s = TB._json(os.path.join(CACHE, "price", c + ".json"))
        if s:
            data[c] = s
    P, V = T.Prices(data), Q.Vol(data)
    sectors, _ = TB.load_sectors()
    T1 = max((P.last_date(c) for c in codes if P.last_date(c)), default=None)
    codes = [c for c in codes if c in ser and c in P.ks]
    log("회사 %d · 시리즈 %d (옛 캐시 %d) · 마지막 시세일 %s · %.0f초" % (len(codes), len(ser), skipped, T1, time.time() - t0))
    LT = latest(codes, ser, P, V, ksic, idx, univ, sectors, asof=a.asof)
    with open(os.path.join(a.out, "latest.json"), "w", encoding="utf-8") as fh:
        json.dump(LT, fh, ensure_ascii=False)
    log("최신 후보 %d · 아깝게(일곱) %d · 적격 %d (s−1 = %s) · %.0f초" % (LT["counts"]["cand"], LT["counts"]["near"], LT["counts"]["elig"], LT["asof"], time.time() - t0))
    for r in LT["rows"][:20]:
        log("  %-12s %3s위 점수 %s ROE %s 마진 %s 3개월 %s PER자리 %s POR자리 %s" % (r["name"], r["cap_rank"], r["score"], fmt(r["roe"]), fmt(r["opm"]), fmt(r["r3m"]), fmt(r["per_pct"], 0), fmt(r["por_pct"], 0)))
    log("원본 12종목 지금 — " + " · ".join("%s %s/8%s" % (o["name"], o.get("n_pass"), "(" + ",".join(o.get("miss") or []) + ")" if o.get("miss") else "") for o in LT["origin"]))
    if a.latest:
        return
    dates = [d for d in TB.month_ends(START, T1) if d < T1]
    log("월말 패널 %d 달 …" % len(dates))
    MR, crash = monthly_panel(codes, ser, P, V, ksic, T1, dates)
    log("월말 행 %d · %.0f초" % (len(MR), time.time() - t0))
    G = groups(MR)
    GS = {k: TB.stats(v, a.boot, ci=(k not in ("적격 전 종목", "급락만(⑥)"))) for k, v in G.items()}
    cand = G["후보(여덟 다)"]
    vs = {k: TB.diff_stats(cand, G[k], a.boot) for k in ("저PER 하위 30%", "우량만(①~⑤ · ⑧)", "우량 + 급락(⑦ 없이)", "급락만(⑥)", "적격 전 종목")}
    primary = month_pairs(cand, G["저PER 하위 30%"])
    vs_q = month_pairs(cand, G["우량만(①~⑤ · ⑧)"])
    splits = {"시장 급락 달(전 종목 1개월 중앙 ≤ −5%)": split_stats(cand, lambda r: "급락 달" if r["crash"] else "보통 달"),
              "기간": split_stats(cand, lambda r: "~2019" if r["date"] < SPLIT else "2020~"),
              "2026 시총 순위": split_stats(cand, lambda r: "300 안" if (univ.get(r["code"]) or {}).get("rank", 9999) <= 300 else "300 밖"),
              "우량만 — 시장 급락 달": split_stats(G["우량만(①~⑤ · ⑧)"], lambda r: "급락 달" if r["crash"] else "보통 달")}
    log("민감도 …")
    SE = sensitivity(MR, a.boot)
    R = {"v": Q.VERSION, "at": dt.datetime.now().isoformat(timespec="seconds"), "T1": T1, "dates": [dates[0], dates[-1]], "n_firms": len({r["code"] for r in MR}),
         "primary_def": PRIMARY, "th": dict(Q.TH), "th_name": Q.TH_NAME, "gates": Q.GATES, "groups": GS, "vs": vs, "primary": primary, "verdict": verdict(primary),
         "vs_quality": vs_q, "splits": splits, "ic": ic_mean(G["일곱 이상"]), "sens": SE,
         "crash_months": sorted(d for d, v in crash.items() if v is not None and v <= CRASH_M),
         "limits": ["잣대는 한 투자자의 12종목 · 하루(2026-10-16) 단면에서 역산했다 — 과거 기간으로는 표본 밖이지만, 고른 근거가 12개뿐이다.",
                    "지금 상장된 회사만(생존 편향) — 수익률 수준은 부풀어 있다. 그때 작았는데 지금 큰 회사가 남아 있다(2026 시총 순위 나눠 보기).",
                    "'큰 회사'는 그날 우리 유니버스(지금 시총 상위 약 990곳) 안 순위 — 그때 시장 전체 순위와 다르다.",
                    "분기 값은 마지막 원장(정정값) · 값을 아는 날은 정정 포함 접수일(엄격). 주식 수는 순이익 ÷ EPS 역산, ROE 분모는 자본총계(비지배 포함).",
                    "월말 표본은 12개월 창이 겹친다 — 회사 · 분기 · 연 블록 구간을 같이 본다.",
                    "그 투자자는 시장 급락 주간(2026-10-07 ~ 10-15)에 샀다 — '시장 급락 달' 나눠 보기가 그 타이밍을 본다."],
         "secs": None}
    R["secs"] = round(time.time() - t0)
    with open(os.path.join(a.out, "bt.json"), "w", encoding="utf-8") as fh:
        json.dump(R, fh, ensure_ascii=False)
    with open(os.path.join(a.out, "bt.md"), "w", encoding="utf-8") as fh:
        fh.write(md_report(R))
    keep = ("code", "date", "lab", "n_pass", "miss", "score", "ex3m", "ex6m", "ex12m", "ret12m", "crash", "per", "r3m", "roe", "opm")
    with open(os.path.join(a.out, "panel_cand.json"), "w", encoding="utf-8") as fh:
        json.dump([{k: r.get(k) for k in keep} for r in G["일곱 이상"]], fh, ensure_ascii=False)
    log(md_report(R))
    log("끝 %.0f초 → %s" % (time.time() - t0, a.out))


if __name__ == "__main__":
    main()

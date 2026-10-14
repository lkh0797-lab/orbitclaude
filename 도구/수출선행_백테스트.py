# -*- coding: utf-8 -*-
"""
수출 선행 발굴 — 과거엔 맞았나 (2026-10-14). 설계 docs/superpowers/specs/2026-10-14-export-lead-value-design.md 3절.

시점: 2021-02 ~ 마지막 통관 달, 매달 16일(관세청이 지난달 치를 내는 15일께 다음 날). 진입 = 그 날 다음 거래일 종가.
시점 자르기: 통관 ≤ m, 공시는 접수일 ≤ d, 등급은 그때까지 쌓인 쌍으로(수출선행.pit_grade), PER 백분위 · 부채는
.cache/value/bt_panel.json 의 접수일(date) ≤ d 마지막 줄(200일 넘게 오래됐으면 모름). 주가 · 전 종목 중앙값은 억울_백테스트 와 같은 틀.
잰다: 3 · 6 · 12개월 초과수익(같은 기간 전 종목 중앙값 대비), 묶음별 중앙값 · 회사 단위 부트스트랩 90% · 앞(~2023)/뒤(2024~).
한계(bt.json caveats 에도 적는다): 통로는 지금 보고서 기준 · 지금 상장사만 · 공시위험/증권사 상태는 과거를 모름 · 겹침.

캐시만 읽는다 — 재무.fetch_statement 는 캐시 파일이 없으면 013 으로(저평가_백테스트 와 같은 봉인), 드러켄밀러 는 offline + 네트워크 예산 0.

실행: python 도구/수출선행_백테스트.py           (주가 988곳 읽기 포함 10~20분)
      python 도구/수출선행_백테스트.py --report  (bt_rows.json 으로 다시 집계)
"""
import os, sys, json, bisect, time, datetime as dt, statistics as st, importlib.util
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
_argv, sys.argv = sys.argv, ["x"]
_spec = importlib.util.spec_from_file_location("wb", os.path.join(HERE, "억울_백테스트.py"))
W = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(W)
sys.argv = _argv
S = W.S
_x = importlib.util.spec_from_file_location("수출선행", os.path.join(BASE, "수출선행.py"))
X = importlib.util.module_from_spec(_x); _x.loader.exec_module(X)
_e = importlib.util.spec_from_file_location("수출추적", os.path.join(BASE, "수출추적.py"))
E = importlib.util.module_from_spec(_e); _e.loader.exec_module(E)


# ---------------------------------------------------------------- 캐시만(새 DART 호출 없음)
def _seal(fin):
    orig = fin.fetch_statement

    def cached_only(corp_code, year, reprt_code, fs_div="CFS", force=False):
        path = os.path.join(fin.FIN_DIR, "%s_%s_%s_%s.json" % (corp_code, year, reprt_code, fs_div))
        if force or not os.path.exists(path):
            return {"status": "013", "list": []}
        return orig(corp_code, year, reprt_code, fs_div)
    fin.fetch_statement = cached_only


for _m in {id(m): m for m in (S.FIN, getattr(S.DRK, "FIN", None)) if m is not None}.values():
    _seal(_m)
if S.DRK is not None:
    S.DRK.NET["budget"] = 0          # offline 에서 네트워크가 필요한 분기는 받지 않고 건너뛴다(transient)

OUT = os.path.join(S.CACHE_DIR, "수출선행")
Q_MON = {"03": 1, "06": 2, "09": 3, "12": 4}
HORIZON = {"ex3": 91, "ex6": 182, "ex12": 365}
SPLIT = "20240101"          # 앞(2021~2023) · 뒤(2024~)
FIRST_M = "202101"          # 첫 통관 달 → 첫 시점 2021-02-16
STALE = 200                 # 마지막 공시 · 패널 줄이 시점보다 이보다 오래됐으면 모름(억울_백테스트 와 같은 신선도)


def filing_dates(c):
    """{"2026Q1": "20260515", …} — 보고서 접수일(정정 제외). 분기 하나에 여러 건이면 첫 것."""
    fd = {}
    for r in c.get("reports") or []:
        y, m = r["stamp"].split("-")
        q = Q_MON.get(m)
        if q and not r.get("tag"):
            fd.setdefault("%sQ%d" % (y, q), r["rcept"][:8])
    return fd


def rev_yoy_by_q(corp, code):
    """분기 매출 YoY — DRK.series(분기 매출액, 캐시만)로. 비중(coverage)도 여기 매출로."""
    try:
        pts = S.DRK.series(corp, code, list(range(2019, dt.date.today().year + 1)), offline=True)
    except Exception:
        return {}, {}
    rev = {"%dQ%d" % (p["year"], p["q"]): p.get("매출액") for p in pts if p.get("매출액")}
    yoy = {}
    for q, v in rev.items():
        p = "%dQ%s" % (int(q[:4]) - 1, q[5])
        if rev.get(p):
            yoy[q] = (v / rev[p] - 1) * 100
    return yoy, rev


def coverage_at(mon_cut, rev, d_fd, d):
    """통관/매출 비중(%) — 접수일 ≤ d 인 마지막 4개 완성 분기 중앙값(수출추적.validate 와 같은 식)."""
    vals = []
    for q in sorted(q for q in rev if d_fd.get(q) and d_fd[q] <= d)[-4:]:
        ms = X._q_months(q)
        if all(m in mon_cut for m in ms) and rev.get(q):
            fx = E.USDKRW.get(int(q[:4]), 1400)
            vals.append(sum(mon_cut[m] for m in ms) * 1000 * fx / rev[q] * 100)
    return st.median(vals) if vals else None


def dd52(code, d):
    ks, vs = W.PX.get(code, ((), ()))
    p, k = W.px_at(code, d)
    if p is None:
        return None
    lo = bisect.bisect_left(ks, W.shift(d, -365))
    i = bisect.bisect_right(ks, d) - 1
    hi = max(vs[lo:i + 1]) if i >= lo else None
    return (p / hi - 1) * 100 if hi else None


def panel_at(rows, d):
    """접수일(date) ≤ d 인 마지막 패널 줄 — t 는 달 가운데(15일) 꼬리표라 쓰지 않는다(2014Q4 접수 03-31 이 t 03-15 로 새는 것 막음)."""
    k = [r for r in rows if r.get("date") and r["date"] <= d]
    if not k or W.shift(k[-1]["date"], STALE) < d:
        return None
    return k[-1]


def month_list(first, last):
    y, m = int(first[:4]), int(first[4:])
    out = []
    while "%04d%02d" % (y, m) <= last:
        out.append("%04d%02d" % (y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def d_of(m):
    """통관 달 m 의 공개 시점 — 다음 달 16일."""
    y, mm = int(m[:4]), int(m[4:]) + 1
    if mm > 12:
        y, mm = y + 1, 1
    return "%04d%02d16" % (y, mm)


def _y12(cut, m):
    w = [X._ym_shift(m, k) for k in range(12)]
    ly = [X._ym_shift(k, 12) for k in w]
    cur, prev = sum(cut.get(k, 0) for k in w), sum(cut.get(k, 0) for k in ly)
    return (cur / prev - 1) * 100 if prev > 0 and all(k in cut for k in ly) else None


def company_rows(x, prows, today):
    code = x["code"]
    c = S.company_by_code(code)
    corp = S.corp_code_of(code)
    if not c or not corp or code not in W.PX:
        return []
    mon = x.get("series_long") or x["series"]
    fd = filing_dates(c)
    yoy, rev = rev_yoy_by_q(corp, code)
    fin = bool(S.VAL_FIN.search(W.IND.get(code, "") or ""))
    rows = []
    for m in month_list(FIRST_M, max(mon)):
        d = d_of(m)
        if d > today:
            break
        cut = X.cut_series(mon, m)
        lrq = X.last_reported_q(fd, d)
        if not lrq or W.shift(fd[lrq], STALE) < d:          # 마지막 공시가 너무 오래됐으면 그 회사 상태를 모른다
            continue
        pairs = X.pit_pairs(mon, yoy, fd, m, d)
        grade = X.pit_grade(pairs, coverage_at(cut, rev, fd, d))
        al = E.aligned(cut, lrq, [{"q": p["q"], "x": p["x"], "r": p["r"]} for p in pairs])
        if not al:
            continue
        e = W.next_day(code, d)
        if not e:
            continue
        pr = panel_at(prows, d)
        ret3m, univ3m = W.ret(code, W.shift(d, -91), d), W.grp_ret("__all__", W.shift(d, -91), d)
        inp = {"grade": grade, "lumpy": al["lumpy"], "reported": al["reported"], "cur": al["cur"], "months": al["months"],
               "ret3m": ret3m, "univ3m": univ3m, "dd52": dd52(code, d),
               "per_pct": pr.get("per_pct") if pr else None,
               "red": (["부채비율 %.0f%%" % pr["debt_eq"]] if (pr and pr.get("debt_eq") is not None and pr["debt_eq"] >= X.DEBT_RED and not fin) else []),
               "risk": [], "fin": fin}
        j = X.judge(inp)
        if j["tier"] is None and not (grade in ("A", "B") and not al["lumpy"]):
            continue                                   # 등급 C · 덩어리는 비교군에도 안 넣는다
        row = {"code": code, "name": x["name"], "m": m, "d": d, "e": e, "grade": grade, "tier": j["tier"],
               "cur": al["cur"], "cur_q": al["cur_q"], "reported": al["reported"], "ret3m": ret3m, "univ3m": univ3m,
               "dd52": inp["dd52"], "per_pct": inp["per_pct"], "red": bool(inp["red"]), "why": j["why"]}
        y12 = _y12(cut, m)
        px_yoy = W.ret(code, W.shift(d, -365), d)
        row["y12"], row["gap"] = y12, X.gap(y12, px_yoy)
        for k, days in HORIZON.items():
            r_, b_ = W.ret(code, e, W.shift(e, days)), W.grp_ret("__all__", e, W.shift(e, days))
            row[k] = (r_ - b_) if (r_ is not None and b_ is not None) else None
        rows.append(row)
    return rows


def build_rows():
    with open(os.path.join(S.CACHE_DIR, "수출추적", "result.json"), "r", encoding="utf-8") as fh:
        items = [x for x in json.load(fh)["items"] if x.get("status") == "ok" and (x.get("series_long") or x.get("series"))]
    with open(os.path.join(S.CACHE_DIR, "value", "bt_panel.json"), "r", encoding="utf-8") as fh:
        panel = {}
        for r in json.load(fh):
            panel.setdefault(r["code"], []).append(r)
    for v in panel.values():
        v.sort(key=lambda r: (r.get("date") or "", r["t"]))
    today = W.ds(dt.date.today())
    last_m = max(max(x.get("series_long") or x["series"]) for x in items)
    # 전 종목 중앙값은 날짜별로 한 번만 — 갈래가 같은 키를 두 번 세지 않게 미리 데운다
    for m in month_list(FIRST_M, last_m):
        d = d_of(m)
        if d > today:
            break
        W.grp_ret("__all__", W.shift(d, -91), d)
        e = W.next_day("005930", d)
        if e:
            for days in HORIZON.values():
                W.grp_ret("__all__", e, W.shift(e, days))
    print("회사 %d곳 · 시점 %s~ · 오늘 %s" % (len(items), d_of(FIRST_M), today), flush=True)
    rows, t0 = [], time.time()
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(company_rows, x, panel.get(x["code"], []), today): x for x in items}
        for n, f in enumerate(as_completed(futs), 1):
            x = futs[f]
            try:
                rows.extend(f.result())
            except Exception as err:
                print("  건너뜀 %s %s: %s" % (x["code"], x["name"], err), flush=True)
            if n % 20 == 0:
                print("  %d/%d %s · 줄 %d · %.0f초" % (n, len(items), x["name"], len(rows), time.time() - t0), flush=True)
    rows.sort(key=lambda r: (r["d"], r["code"]))
    return rows


def _stat(rows, k="ex12"):
    v = [r[k] for r in rows if r.get(k) is not None]
    if len(v) < 5:
        return {"med": None, "ci": [None, None], "n": len(v)}
    lo, hi = W.boot([r for r in rows if r.get(k) is not None], lambda rs: st.median([r[k] for r in rs]))
    return {"med": st.median(v), "ci": [lo, hi], "n": len(v)}


def summarize(rows):
    def grp(sub):
        g = {"n": len(sub), "firms": len({r["code"] for r in sub}), "days": len({r["d"] for r in sub})}
        for k in HORIZON:
            g[k] = _stat(sub, k)
        ea, la = _stat([r for r in sub if r["d"] < SPLIT], "ex12"), _stat([r for r in sub if r["d"] >= SPLIT], "ex12")
        g["ex12"].update(early=ea["med"], late=la["med"], early_ci=ea["ci"], late_ci=la["ci"], n_early=ea["n"], n_late=la["n"])
        return g
    found = [r for r in rows if r["tier"] == "발굴"]
    watch = [r for r in rows if r["tier"] == "관찰"]
    clue = found + watch
    groups = {"발굴": grp(found), "관찰": grp(watch), "단서만": grp(clue), "비교(통로 있는 회사 전체)": grp(rows)}
    gs = [r for r in clue if r.get("gap") is not None and r.get("ex12") is not None]
    gap_split = None
    if len(gs) >= 30:
        v = sorted(r["gap"] for r in gs)
        a, b = v[len(v) // 3], v[2 * len(v) // 3]
        top, bot = [r for r in gs if r["gap"] >= b], [r for r in gs if r["gap"] < a]
        lo, hi = W.boot(gs, lambda rs: (st.median([r["ex12"] for r in rs if r["gap"] >= b]) - st.median([r["ex12"] for r in rs if r["gap"] < a]))
                        if (sum(r["gap"] >= b for r in rs) > 5 and sum(r["gap"] < a for r in rs) > 5) else None)
        gap_split = {"top": st.median([r["ex12"] for r in top]), "bot": st.median([r["ex12"] for r in bot]),
                     "spread": st.median([r["ex12"] for r in top]) - st.median([r["ex12"] for r in bot]), "ci": [lo, hi],
                     "n_top": len(top), "n_bot": len(bot)}
    by = {}
    for r in sorted(found, key=lambda r: (r["code"], r["d"])):
        by.setdefault(r["code"], []).append(r["d"])
    cons = sum(1 for ds_ in by.values() for a_, b_ in zip(ds_, ds_[1:]) if W.shift(a_, 40) >= b_)
    overlap = cons / max(1, len(found) - len(by))
    # 결정 규칙(설계 3절): 발굴 묶음 12개월 초과 중앙값이 앞 · 뒤 모두 플러스, 전체 구간 또는 한쪽 반의 구간이 0 을 벗어나면 '발굴'
    f = groups["발굴"]["ex12"]
    clear = any(ci and ci[0] is not None and ci[0] > 0 for ci in (f["ci"], f["early_ci"], f["late_ci"]))
    verdict = "발굴" if (f["med"] is not None and f["early"] is not None and f["late"] is not None
                       and f["early"] > 0 and f["late"] > 0 and clear) else "관찰"
    return {"v": 1, "at": dt.datetime.now().isoformat(timespec="seconds"),
            "dates": [min(r["d"] for r in rows), max(r["d"] for r in rows)] if rows else None, "n": len(rows),
            "groups": groups, "gap_split": gap_split, "overlap": round(overlap, 3), "verdict": verdict,
            "rules": {"clue": X.CLUE_MIN, "dd": X.PRICE_DD, "per_pct": X.VALUE_PCT_MAX, "debt": X.DEBT_RED, "split": SPLIT, "stale_days": STALE},
            "caveats": ["통로(시군구 × 품목)는 지금 보고서 기준 — 과거 시점 공장이 달랐을 수 있다",
                        "지금 상장된 회사만(생존 편향)", "공시위험 · 증권사 상태는 과거 시점을 몰라 빨간불에 넣지 않았다",
                        "같은 회사가 연속 달에 또 걸리면 모두 셌다(겹침 비율 overlap)", "초과수익 = 같은 기간 전 종목 중앙값 대비 · 수수료 없음",
                        "PER 백분위 · 부채는 저평가 백테스트 표본(bt_panel, 접수일 ≤ 시점, 200일 안)에서 — 표본이 끝난 뒤 시점은 값 모름",
                        "분기 매출은 지금 캐시의 값(나중 정정 반영) · 환율은 연평균 근사"]}


def _f(v):
    return "모름" if v is None else "%+.1f%%p" % v


def main():
    os.makedirs(OUT, exist_ok=True)
    rows_p = os.path.join(OUT, "bt_rows.json")
    if "--report" in sys.argv and os.path.exists(rows_p):
        with open(rows_p, "r", encoding="utf-8") as fh:
            rows = json.load(fh)
    else:
        rows = build_rows()
        with open(rows_p, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False)
    rep = summarize(rows)
    with open(os.path.join(OUT, "bt.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1)
    print("시점 %s · 줄 %d" % (rep["dates"], rep["n"]))
    for k, g in rep["groups"].items():
        e = g["ex12"]
        print("%-22s n %5d · 회사 %3d · 날 %3d · 3개월 %s · 6개월 %s · 12개월 초과 중앙 %s [%s, %s] · 앞 %s(n %d) · 뒤 %s(n %d)" % (
            k, g["n"], g["firms"], g["days"], _f(g["ex3"]["med"]), _f(g["ex6"]["med"]),
            _f(e["med"]), _f(e["ci"][0]), _f(e["ci"][1]), _f(e["early"]), e["n_early"], _f(e["late"]), e["n_late"]))
    print("벌어짐 위⅓−아래⅓:", rep["gap_split"], "· 겹침", rep["overlap"], "· 판정:", rep["verdict"])


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
'시너지 발굴' 점수와 단계(잠복·점화·반영·둔화·관찰)가 실제로 맞았나.

매달 말(2013.06~2025.09) 그때 이미 공시된 보고서만으로 시너지 발굴 행을 다시 만든다.
  선행   잔고 1년 증가율 · 북투빌
  전환   매출 가속(분기 YoY 변화) · 영업이익률 변화(직전 분기 대비 %p)
  가격   잔고 증가 − 주가 1년(반영 갭) · PER(낮을수록)
  확인   보고서 뒤 수주 공시 — 과거 공시 목록이 캐시에 없어 뺐다(가중치를 나머지로 다시 나눈다)
점수는 시너지.py score() 를 그대로 부르고(그 날 신뢰할 수 있는 회사끼리 백분위 → 가중평균), 단계는 stage() 를 그대로 부른다.
2026-09-29 이전 식(선행 = 잔고 증가 .6·북투빌 .4, 전환 = 매출 가속 .6·이익률 변화 .4, 가격 = 반영 갭 .6·PER .4)은 score_old 로 함께 잰다.
그 뒤 6·12개월 수익률을 같은 기간 전 종목 중앙값과 비교한다.

한계 — 억울_백테스트.py 와 같다(지금 상장된 회사만, 표본 대부분이 2020년 뒤).
  PER = 종목.txt 시가총액 스냅샷 × (그 날 수정주가 ÷ 스냅샷 날 수정주가) ÷ 4분기 순이익. 그 사이 증자·자사주 소각은 반영 못 한다.

실행: python 도구/시너지_백테스트.py   (억울_백테스트.py 의 시점 재구성을 그대로 쓴다)
결과: 표준출력 + .cache/시너지/bt_panel.json · bt_report.json
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
SYN = S.SYN
OUT = os.path.join(S.CACHE_DIR, "시너지")
UNIV, SNAP = S._universe_info()
PARTS = {"선행": 0.35, "전환": 0.25, "가격": 0.25}      # 확인(0.15)은 뺐다


def cap_at(code, t):
    u = UNIV.get(code)
    if not u or not SNAP:
        return None
    a, _ = W.px_at(code, SNAP, stale=30)
    b, _ = W.px_at(code, t)
    return u["cap"] * b / a if (a and b) else None


def row_at(P, t):
    """시점 t 의 시너지 행(점수 전 단계). 잔고를 믿을 수 없으면 None."""
    Bt = [b for b in P["B"] if b["date"] <= t]
    if len(Bt) < 4 or W.shift(Bt[-1]["date"], 200) < t:
        return None
    tr = S.BACK.trend(Bt)
    if not tr:
        return None
    Q = P["Q"]
    k = [p for p in Q if p["fdate"] <= t]
    if not k or W.shift(k[-1]["fdate"], 200) < t:
        return None
    cur = k[-1]
    rev = cur.get("rev4")
    last, yoy = tr["last"], tr.get("yoy")
    b1 = last / (1 + yoy / 100) if (yoy is not None and yoy > -100) else None
    btb = (1 + (last - b1) / rev) if (b1 and rev) else None
    cover = last / rev if rev else None
    # 잔고를 여러 기간·형태로 — 1년이 최선인지 가린다(2026-09-30)
    ly, lm = map(int, Bt[-1]["stamp"].split("-"))
    kv = {}
    for b in Bt:
        y_, m_ = map(int, b["stamp"].split("-"))
        kv[y_ * 12 + m_] = b["value"]
    base_k = ly * 12 + lm

    def ago(months):
        for d in (0, -1, 1):
            v = kv.get(base_k - months + d)
            if v:
                return v
        return None

    def revq(n):
        w = k[-n:]
        ok_ = len(w) == n and all(x.get("매출액") for x in w) and \
            all(b_["year"] * 4 + b_["q"] - a_["year"] * 4 - a_["q"] == 1 for a_, b_ in zip(w, w[1:]))
        return sum(x["매출액"] for x in w) if ok_ else None

    def chg(a, b, yrs=None):
        if not (a and b and b > 0):
            return None
        return ((a / b) ** (1 / yrs) - 1) * 100 if yrs else (a / b - 1) * 100
    a3, a6, a12, a15, a24, a36 = (ago(m) for m in (3, 6, 12, 15, 24, 36))
    by1_prev = chg(a3, a15)
    by1_old = chg(a12, a24)
    by1 = chg(last, a12)
    rv1, rv2, rv8 = revq(1), revq(2), revq(8)
    q_old = k[-5] if len(k) >= 5 else None
    cover_old = (a12 / q_old["rev4"]) if (a12 and q_old and q_old.get("rev4")) else None
    prev12 = [v for kk, v in kv.items() if base_k - 36 <= kk < base_k]
    bt_extra = {
        "bq1": chg(last, a3), "bq2": chg(last, a6), "by1": by1, "by2": chg(last, a24, 2), "by3": chg(last, a36, 3),
        "bacc": (by1 - by1_prev) if (by1 is not None and by1_prev is not None) else None,
        "bacc4": (by1 - by1_old) if (by1 is not None and by1_old is not None) else None,
        "btb1": (1 + (last - a3) / rv1) if (a3 and rv1) else None,
        "btb2": (1 + (last - a6) / rv2) if (a6 and rv2) else None,
        "btb8": (1 + (last - a24) / rv8) if (a24 and rv8) else None,
        "up8": tr.get("up_ratio"),
        "cover_chg": (last / rev - cover_old) if (rev and cover_old is not None) else None,
        "newhigh": (last / max(prev12) - 1) * 100 if prev12 else None,
    }
    win = Bt[-12:]
    sure = sum(1 for b in win if b.get("verified") or b.get("method") == "문장")
    reliable = (tr["n"] >= 4 and not tr.get("jumps") and sure >= (len(win) + 1) // 2
                and (cover is None or cover >= 0.15))
    if not reliable:
        return None
    ks, vs = W.PX[P["code"]]
    i1 = bisect.bisect_right(ks, t) - 1
    if i1 < 0 or W.shift(ks[i1], 10) < t:
        return None
    p1y = W.ret(P["code"], W.shift(t, -365), t)
    i0 = bisect.bisect_left(ks, W.shift(t, -365))
    dd52 = (vs[i1] / max(vs[i0:i1 + 1]) - 1) * 100 if i1 >= i0 else None
    cap = cap_at(P["code"], t)
    per = cap / cur["ni4"] if (cap and cur.get("ni4") and cur["ni4"] > 0) else None
    mgn = None if cur.get("이익률_비정상") else cur.get("이익률변화")
    yoy_c = min(yoy, 300.0) if yoy is not None else None
    # 4분기 합 — 한 분기 반짝 흑자·기저효과에 흔들리지 않는 이익 (가온칩스 2026Q2: 분기 +1.5%, 4분기 합 영업손실 −91억)
    q4 = k[-5] if len(k) >= 5 else None
    op4, ni4 = cur.get("op4"), cur.get("ni4")
    m4 = (op4 / rev * 100) if (op4 is not None and rev) else None
    m4_old = (q4["op4"] / q4["rev4"] * 100) if (q4 and q4.get("op4") is not None and q4.get("rev4")) else None
    m4d = (m4 - m4_old) if (m4 is not None and m4_old is not None and abs(m4) <= 100 and abs(m4_old) <= 100) else None
    rev4_yoy = (rev / q4["rev4"] - 1) * 100 if (q4 and q4.get("rev4") and rev) else None
    r = {"code": P["code"], "name": P["name"], "t": t, "ind": P["ind"],
         "backlog_yoy": yoy, "btb": btb, "cover": cover, "steady": tr.get("steady"),
         "rev_yoy": cur.get("매출YoY"), "rev_accel": cur.get("매출가속"), "margin_delta": mgn,
         "margin": cur.get("영업이익률") if not cur.get("이익률_비정상") else None,
         "price_1y": p1y, "dd52": dd52, "per": per,
         "op4": op4, "ni4": ni4, "m4": m4 if (m4 is None or abs(m4) <= 100) else None, "m4d": m4d, "rev4_yoy": rev4_yoy,
         "margin4": m4,          # 시너지.score() 가 읽는 이름
         **bt_extra,
         "loss4": (op4 is not None and op4 <= 0) or (ni4 is not None and ni4 <= 0),
         "gap": (yoy_c - p1y) if (yoy_c is not None and p1y is not None) else None}
    r["stage"], _ = SYN.stage(r)
    for h, days in W.H.items():
        t1 = W.shift(t, days)
        a, u = W.ret(P["code"], t, t1), W.grp_ret("__all__", t, t1)
        r["ex" + h] = (a - u) if (a is not None and u is not None) else None
    return r


def score_date(rows):
    """지금 화면 식(SYN.score)과 예전 식을 함께 매긴다. 확인(수주 공시)은 과거 자료가 없어 모두 0 — 같은 날 순서는 바뀌지 않는다."""
    for r in rows:
        r.update(reliable=True, new_pct=None, flags=[])
    SYN.score(rows)
    for r in rows:
        r["p_선행"], r["p_전환"], r["p_가격"] = (r["parts"].get(k) for k in ("선행", "전환", "가격"))
        del r["parts"]
    R = {k: SYN._pct_rank([r[f] for r in rows]) for k, f in
         (("yoy", "backlog_yoy"), ("btb", "btb"), ("acc", "rev_accel"), ("mgn", "margin_delta"), ("gap", "gap"))}
    R["per"] = SYN._pct_rank([-r["per"] if r["per"] else None for r in rows])

    def blend(parts):
        tot = w = 0.0
        for v, wt in parts:
            if v is not None:
                tot += v * wt
                w += wt
        return tot / w if w else None
    for r in rows:
        old = {"선행": blend([(R["yoy"](r["backlog_yoy"]), .6), (R["btb"](r["btb"]), .4)]),
               "전환": blend([(R["acc"](r["rev_accel"]), .6), (R["mgn"](r["margin_delta"]), .4)]),
               "가격": blend([(R["gap"](r["gap"]), .6), (R["per"](-r["per"]) if r["per"] else None, .4)])}
        r["score_old"] = blend([(old[k], w) for k, w in PARTS.items()])


FACTORS = [
    ("score_old", "예전 점수(확인 뺌)", lambda r: r["score_old"]),
    ("score", "지금 점수(확인 뺌)", lambda r: r["score"]),
    ("p_선행", "  선행 부분", lambda r: r["p_선행"]),
    ("p_전환", "  전환 부분", lambda r: r["p_전환"]),
    ("p_가격", "  가격 부분", lambda r: r["p_가격"]),
    ("backlog_yoy", "잔고 1년 증가율", lambda r: min(r["backlog_yoy"], 300) if r["backlog_yoy"] is not None else None),
    ("btb", "북투빌", lambda r: min(r["btb"], 5) if r["btb"] is not None else None),
    ("cover", "잔고/연매출", lambda r: min(r["cover"], 10) if r["cover"] is not None else None),
    ("rev_yoy", "매출 YoY(분기)", lambda r: max(min(r["rev_yoy"], 200), -80) if r["rev_yoy"] is not None else None),
    ("rev_accel", "매출 가속", lambda r: max(min(r["rev_accel"], 100), -100) if r["rev_accel"] is not None else None),
    ("margin_delta", "이익률 변화(분기 %p)", lambda r: max(min(r["margin_delta"], 30), -30) if r["margin_delta"] is not None else None),
    ("margin", "영업이익률", lambda r: max(min(r["margin"], 60), -30) if r["margin"] is not None else None),
    ("gap", "반영 갭(잔고−주가)", lambda r: max(min(r["gap"], 300), -300) if r["gap"] is not None else None),
    ("price_1y", "주가 1년", lambda r: min(r["price_1y"], 300) if r["price_1y"] is not None else None),
    ("dd52", "52주 고점 대비", lambda r: r["dd52"]),
    ("per", "PER(근사)", lambda r: min(r["per"], 100) if r["per"] else None),
    ("m4", "4분기 합 영업이익률", lambda r: max(min(r["m4"], 60), -30) if r.get("m4") is not None else None),
    ("m4d", "4분기 합 이익률 1년 변화", lambda r: max(min(r["m4d"], 30), -30) if r.get("m4d") is not None else None),
    ("rev4_yoy", "4분기 합 매출 1년", lambda r: max(min(r["rev4_yoy"], 200), -80) if r.get("rev4_yoy") is not None else None),
]


def _w(k, lo, hi):
    return lambda r: max(min(r[k], hi), lo) if r.get(k) is not None else None


# 잔고 기간·형태 비교 — 1년 증가율과 1년 북투빌이 최선인가
BACKLOG_FACTORS = [
    ("bq1", "잔고 3개월 변화", _w("bq1", -60, 150)),
    ("bq2", "잔고 6개월 변화", _w("bq2", -70, 200)),
    ("by1", "잔고 1년 변화(지금)", _w("by1", -80, 300)),
    ("by2", "잔고 2년 연율", _w("by2", -60, 200)),
    ("by3", "잔고 3년 연율", _w("by3", -50, 150)),
    ("bacc", "잔고 증가율 가속(석 달 전 대비)", _w("bacc", -200, 200)),
    ("bacc4", "잔고 증가율 가속(1년 전 대비)", _w("bacc4", -300, 300)),
    ("btb1", "북투빌 1분기", _w("btb1", -3, 8)),
    ("btb2", "북투빌 2분기", _w("btb2", -3, 6)),
    ("btb", "북투빌 1년(지금)", _w("btb", -2, 5)),
    ("btb8", "북투빌 2년", _w("btb8", -1, 4)),
    ("up8", "꾸준함(8개 중 증가 비율)", _w("up8", 0, 1)),
    ("cover_chg", "잔고/연매출 배수 1년 변화", _w("cover_chg", -3, 5)),
    ("newhigh", "3년 최고치 대비", _w("newhigh", -80, 200)),
]


def one(c):
    try:
        P = W.prep(c)
    except Exception:
        return []
    out = []
    if P:
        for t in W.DATES:
            try:
                r = row_at(P, t)
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
            if n % 100 == 0:
                print("  %d/%d 회사 · 표본 %d" % (n, len(comps), len(panel)), flush=True)
    by = {}
    for r in panel:
        by.setdefault(r["t"], []).append(r)
    for rows in by.values():
        score_date(rows)
    panel.sort(key=lambda r: (r["t"], r["code"]))
    os.makedirs(OUT, exist_ok=True)
    json.dump(panel, open(os.path.join(OUT, "bt_panel.json"), "w", encoding="utf-8"), ensure_ascii=False)
    report(panel)


def report(panel):
    out = {"dates": [W.DATES[0], W.DATES[-1]], "stages": {}, "factors": {}, "terciles": {}}
    Y = "ex12m"
    rows = [r for r in panel if r.get(Y) is not None]
    allv = [r[Y] for r in rows]
    print("\n== 단계별 12개월 초과수익 (같은 기간 전 종목 중앙값 대비, %%)  전체 표본 %d건 · %d곳 · 중앙 %+.1f" % (
        len(rows), len({r['code'] for r in rows}), st.median(allv)))
    for sg in ("잠복", "점화", "반영", "둔화", "관찰"):
        sub = [r for r in rows if r["stage"] == sg]
        if not sub:
            continue
        s = W.summ(sub, Y)
        lo, hi = W.boot(sub, lambda x: st.median([r[Y] for r in x]) if x else None)
        e = [r[Y] for r in sub if r["t"] < W.SPLIT]
        l = [r[Y] for r in sub if r["t"] >= W.SPLIT]
        out["stages"][sg] = dict(s, ci=[lo, hi], early=st.median(e) if e else None, late=st.median(l) if l else None,
                                 n_early=len(e), n_late=len(l))
        print("  %-4s 표본 %5d (%3d곳) 중앙 %+6.1f 90%%CI %+6.1f~%+6.1f 평균 %+6.1f 이긴 %3.0f%% | ~2019 %s(n%d) 2020~ %s(n%d)" % (
            sg, s["n"], s["firms"], s["median"], lo, hi, s["mean"], s["hit"],
            "%+.1f" % st.median(e) if e else "—", len(e), "%+.1f" % st.median(l) if l else "—", len(l)))
    print("\n== 항목별 — 날짜별 순위상관(IC) 평균과 세 묶음(상위⅓−하위⅓) 차이, 12개월 초과수익")
    print("  %-20s %7s %6s %5s %7s %7s | %7s %7s %7s  %-15s %s" % ("항목", "IC", "t", "양수", "~2019", "2020~", "하위⅓", "상위⅓", "차이", "90%구간", "~2019/2020~"))
    for k, nm, fx in FACTORS:
        ic = W.ic_stats(rows, fx, Y, overlap=12)
        tt = W.tercile_test(rows, fx, Y)
        if not ic or not tt:
            continue
        out["factors"][k] = dict(ic, name=nm)
        out["terciles"][k] = dict(tt, name=nm)
        print("  %-20s %+7.3f %+6.2f %4.0f%% %+7.3f %+7.3f | %+7.1f %+7.1f %+7.1f  %+6.1f~%+6.1f  %s/%s" % (
            nm, ic["ic"], ic["t"], ic["pos"] * 100, ic["early"] or 0, ic["late"] or 0, tt["bot"], tt["top"], tt["spread"],
            tt["ci"][0], tt["ci"][1], "%+.0f" % tt["early"] if tt["early"] is not None else "—",
            "%+.0f" % tt["late"] if tt["late"] is not None else "—"))
    print("\n== 잔고 기간·형태별 — 전체 / 둔화 뺀 나머지 (상위⅓−하위⅓, 12개월 초과수익)")
    nd0 = [r for r in rows if r["stage"] != "둔화"]
    out["backlog"] = {}
    for k, nm, fx in BACKLOG_FACTORS:
        ic = W.ic_stats(rows, fx, Y, overlap=12)
        tt = W.tercile_test(rows, fx, Y)
        tn = W.tercile_test(nd0, fx, Y)
        if not ic or not tt:
            continue
        out["backlog"][k] = {"name": nm, "ic": ic, "all": tt, "no_slow": tn}
        print("  %-26s IC %+.3f t %+.2f (%+.3f/%+.3f) | 차 %+6.1f %+6.1f~%+6.1f %s/%s | 둔화 뺀 차 %s" % (
            nm, ic["ic"], ic["t"], ic["early"] or 0, ic["late"] or 0, tt["spread"], tt["ci"][0], tt["ci"][1],
            "%+.0f" % tt["early"] if tt["early"] is not None else "—", "%+.0f" % tt["late"] if tt["late"] is not None else "—",
            "%+.1f (%+.1f~%+.1f)" % (tn["spread"], tn["ci"][0], tn["ci"][1]) if tn and tn["spread"] is not None else "—"))
    # 추천필터 — 화면과 같은 정의(시너지.SYN_REC)로 과거 성과를 잰다. 악재 공시 거름은 과거 자료가 없어 빠진다
    print("\n== 추천필터별 12개월 초과수익 (전체 중앙 %+.1f)" % st.median(allv))
    out["rec"] = {}
    for rc in SYN.SYN_REC:
        sub = [r for r in rows if SYN.rec_pass(r, rc["f"])]
        if len(sub) < 20:
            continue
        s = W.summ(sub, Y)
        lo, hi = W.boot(sub, lambda x: st.median([r[Y] for r in x]) if x else None)
        e = [r[Y] for r in sub if r["t"] < W.SPLIT]
        l = [r[Y] for r in sub if r["t"] >= W.SPLIT]
        worst = sum(1 for r in sub if r[Y] < -30) / len(sub) * 100
        per_date = len(sub) / max(len({r["t"] for r in rows}), 1)
        out["rec"][rc["id"]] = dict(s, ci=[lo, hi], early=st.median(e) if e else None, late=st.median(l) if l else None,
                                    worst=worst, per_date=per_date)
        print("  %-12s 표본 %5d (%3d곳, 한 달 평균 %.1f곳) 중앙 %+6.1f 90%%CI %+6.1f~%+6.1f 이긴 %3.0f%% −30%%↓ %2.0f%% | ~2019 %s 2020~ %s" % (
            rc["name"], s["n"], s["firms"], per_date, s["median"], lo, hi, s["hit"], worst,
            "%+.1f" % st.median(e) if e else "—", "%+.1f" % st.median(l) if l else "—"))
    # 4분기 합 적자 — 점수에 흑자·적자를 보는 항목이 없었다(가온칩스 1위). 적자 회사가 실제로 뒤처졌나
    print("\n== 4분기 합 적자(영업이익 또는 순이익 ≤ 0) vs 흑자")
    out["loss4"] = {}
    for lab, sub_all in (("전체", rows), ("둔화 뺀 나머지", [r for r in rows if r["stage"] != "둔화"])):
        for nm, f in (("적자", lambda r: r.get("loss4")), ("흑자", lambda r: r.get("loss4") is False)):
            sub = [r for r in sub_all if f(r)]
            if not sub:
                continue
            s = W.summ(sub, Y)
            lo, hi = W.boot(sub, lambda x: st.median([r[Y] for r in x]) if x else None)
            e = [r[Y] for r in sub if r["t"] < W.SPLIT]
            l = [r[Y] for r in sub if r["t"] >= W.SPLIT]
            out["loss4"]["%s·%s" % (lab, nm)] = dict(s, ci=[lo, hi], early=st.median(e) if e else None, late=st.median(l) if l else None)
            print("  %-10s %s 표본 %5d (%3d곳) 중앙 %+6.1f 90%%CI %+6.1f~%+6.1f 이긴 %3.0f%% | ~2019 %s 2020~ %s" % (
                lab, nm, s["n"], s["firms"], s["median"], lo, hi, s["hit"],
                "%+.1f" % st.median(e) if e else "—", "%+.1f" % st.median(l) if l else "—"))
    nd = [r for r in rows if r["stage"] != "둔화"]
    out["no_slow"] = {k: W.tercile_test(nd, (lambda r, k=k: r[k]), Y) for k in ("score", "score_old")}
    print("\n== 둔화를 뺀 나머지 안에서 점수 상위⅓−하위⅓")
    for k in ("score_old", "score"):
        x = out["no_slow"][k]
        if x:
            print("  %-10s 하 %+5.1f 상 %+5.1f 차 %+5.1f 90%% %+5.1f~%+5.1f" % (k, x["bot"], x["top"], x["spread"], x["ci"][0], x["ci"][1]))
    out["n"], out["firms"], out["median"] = len(rows), len({r["code"] for r in rows}), st.median(allv)
    out["at"] = W.ds(W.dt.date.today())
    json.dump(out, open(os.path.join(OUT, "bt_report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--report":
        # 표본은 그대로 두고 점수만 지금 식으로 다시 매긴다(점수 식을 고친 뒤 몇 초면 된다)
        panel = json.load(open(os.path.join(OUT, "bt_panel.json"), encoding="utf-8"))
        by = {}
        for r in panel:
            by.setdefault(r["t"], []).append(r)
        for rows in by.values():
            score_date(rows)
        report(panel)
    else:
        main()

# -*- coding: utf-8 -*-
"""
'시너지 발굴' 점수와 단계(잠복·점화·반영·둔화·관찰)가 실제로 맞았나.

매달 말(2013.06~2025.09) 그때 이미 공시된 보고서만으로 시너지 발굴 행을 다시 만든다.
2026-10-20 v3(docs/superpowers/specs/2026-10-20-synergy-score-v3-design.md) — 점수 = (수주 + 값 + 여지) ÷ 3 − 위험 표지 10.
  수주   북투빌 · 잔고/연매출 배수 1년 변화(v2 '선행')
  값     PER 자기 역사 % 가 낮을수록(분기 패널 per_pct, 접수일 ≤ t)
  여지   4분기 합 영업이익률(흑자만 백분위, 적자는 해당 없음 → 50 대입 — v2 '전환')
  위험   12개월 안 희석 · 부실 공시(.cache/공시목록 I · B · A001 을 시점마다 다시 셈 — 시너지.risk_flags)
v2(선행 .35 · 전환 .25 · 가격 = 반영 갭 .25)는 score_v2 로 같은 행에 함께 매기고, 미리 적은 주 지표(둔화 뺀 상⅓ − 하⅓, 회사 · 해 재표본)와
v3 − v2 짝 차를 보고의 'v3' 칸에 적는다. 점수는 시너지.py score() 를 그대로 부르고, 단계는 stage() 를 그대로 부른다.
2026-10-14 v2 — 행에 per_pct(분기 패널 .cache/quarter/bt_panel.json 의 같은 code · 같은 분기 lab 줄, 접수일 ≤ t 인 것만 —
미래 분기 금지) · lead(잔고 1년 증가율 − 4분기 합 매출 1년 변화, %p)를 더해 추천필터 '싼 수주'(SYN_REC cheap)를 같은 정의로 잰다.
보고에 overall(전체 중앙 · 90%) · no_slow(둔화 뺀 중앙 · 90% + 점수 상⅓−하⅓) · 요인 per_pct · lead(둔화 뺀 IC 도) 가 더 들어간다.
문턱 · 식은 결과를 보고 바꾸지 않는다(설계 문서 1절).
2026-09-29 이전 식(선행 = 잔고 증가 .6·북투빌 .4, 전환 = 매출 가속 .6·이익률 변화 .4, 가격 = 반영 갭 .6·PER .4)은 score_old 로 함께 잰다.
그 뒤 6·12개월 수익률을 같은 기간 전 종목 중앙값과 비교한다. 들어가는 날 = 그달 말 다음 거래일 종가(2026-10-07).

한계 — 억울_백테스트.py 와 같다(지금 상장된 회사만, 표본 대부분이 2020년 뒤).
  PER = 종목.txt 시가총액 스냅샷 × (그 날 수정주가 ÷ 스냅샷 날 수정주가) ÷ 4분기 순이익. 그 사이 증자·자사주 소각은 반영 못 한다.
  재무는 나중 정정값일 수 있다 — 원장 캐시(DRK.series, meta 없음)는 정정판을 들고 fdate 는 원본 접수일이다(억울 prep 공통). cur 분기 '기준일'
  (정정 반영 접수일)이 t 뒤인 행은 패널에 amended_after 로 표시하고 점수 · 보고에서 뺀다(2026-10-15 리뷰). 기준일 없는 옛 원장은 '모름'(fin_base None)
  으로 세어 둔다. 4분기 합의 앞 세 분기 · 1년 전 분기의 정정은 안 본다.
  상⅓−하⅓(tercile_test)는 2026-10-15 부터 날짜 안 분위(by_date — 억울_백테스트 기본값은 pooled 그대로).

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
PARTS = {"선행": 0.35, "전환": 0.25, "가격": 0.25}      # 예전 식(score_old)용. 확인은 뺐다 — SYN.WEIGHTS 도 v2 부터 확인 0
QTR_PANEL = os.path.join(S.CACHE_DIR, "quarter", "bt_panel.json")


def _load_qpanel(path=QTR_PANEL):
    """분기 패널(도구/분기변화_백테스트.py) → {(code, 'YYYYQn'): [(접수일, per_pct), …]}.
    per_pct = 공시일 종가 PER 의 자기 역사 백분위(앞 40분기 · 8개↑, 낮을수록 싸다). 접수일은 'date'(실제 rcept 날짜 —
    't' 는 그 달 15일로 뭉친 값). per_pct 없는 줄은 담지 않는다(담아도 None 이라 결과가 같다). 파일이 없으면 빈 dict → 전부 None."""
    qp = {}
    try:
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)
    except Exception as e:
        print("  분기 패널을 못 읽어 per_pct 는 전부 None:", path, e, flush=True)
        return qp
    for r in rows:
        if r.get("per_pct") is None or not r.get("code") or not r.get("lab"):
            continue
        qp.setdefault((r["code"], r["lab"]), []).append((r.get("date") or r.get("t"), r["per_pct"]))
    return qp


QP = _load_qpanel()

# 위험 표지(2026-10-20 v3) — 공시 목록(.cache/공시목록 I · B · A001)을 회사별로 한 번 읽고, 시점 t 까지 12개월(t−12개월, t] 의 범주별 서로 다른
# 날 수를 센다. 정정 · 첨부 재제출은 세지 않고, '자회사사항'만인 공시는 뺀다(도구/작전주_사망_검증.prepare 와 같은 규칙).
# 서버는 같은 셈을 도구/공시위험.py 가 s12 로 적어 주고, 둘 다 시너지.risk_flags 로 표지를 만든다.
sys.path.insert(0, HERE)
import 공시분류 as K            # noqa: E402
import 작전주_사망_검증 as DTH   # noqa: E402
_RISK = {"d": None}
_RISK_FROM = None          # risk_from() — 아래 정의 뒤 채운다
_RISK_LOCK = __import__("threading").Lock()
assert all(c in {x["id"] for x in K.CATEGORIES} for c in SYN.RISK_DIL + SYN.RISK_BAD), "위험 범주 이름이 공시분류와 다르다"


def _risk_info():
    """{종목코드: {"ev": [(날짜, frozenset(범주)) …], "evd": [날짜 …]}} — 처음 부를 때 한 번 읽는다(스레드 안전)."""
    with _RISK_LOCK:
        if _RISK["d"] is not None:
            return _RISK["d"]
        import glob
        want = {c.get("code") for c in S.INDEX.get("companies", []) if c.get("code")}
        seen, ev = set(), {}
        for kd in K.KINDS:
            for fp in sorted(glob.glob(os.path.join(K.DIR, "%s_*.jsonl" % kd))):
                with open(fp, encoding="utf-8") as fh:
                    for ln in fh:
                        x = json.loads(ln)
                        sc = (x.get("stock_code") or "").strip()
                        if sc not in want or x.get("rcept_no") in seen:
                            continue
                        seen.add(x.get("rcept_no"))
                        if K.norm(x["report_nm"])[1]:          # 정정 · 첨부 재제출
                            continue
                        cs = K.classify(x["report_nm"], x.get("flr_nm"))
                        if not cs or cs == ("자회사사항",):
                            continue
                        ev.setdefault(sc, []).append((x["rcept_dt"], frozenset(cs)))
        d = {}
        for sc, v in ev.items():
            v.sort(key=lambda e: e[0])
            d[sc] = {"ev": v, "evd": [e[0] for e in v]}
        _RISK["d"] = d
        print("  위험 공시 — %d곳 · %d건(원본, 분류됨)" % (len(d), sum(len(v["ev"]) for v in d.values())), flush=True)
        return d


def risk_s12(code, t):
    """시점 t 까지 12개월의 범주별 서로 다른 날 수({범주: n}) — 접수일 ≤ t 만(미래 공시 안 봄)."""
    f = _risk_info().get(code)
    return DTH.count_signals(f, DTH.shift(t, -12), t) if f else {}


def risk_from():
    """12개월 창 (t−12개월, t] 이 공시 목록 캐시 안에 다 드는 첫 날. 캐시가 2013Q1 부터라 20131231 — 그 전 달들은 창이 잘려
    표지를 덜 센다(2026-10-20 리뷰: 2013-06 표지 비율 12% vs 2014 31%). 그 날들의 행은 위험 '모름'(감점 없음)이고 v3 표에서 뺀다."""
    import glob
    import re as _re
    qs = [m.groups() for fp in glob.glob(os.path.join(K.DIR, "*_*Q*.jsonl"))
          for m in [_re.search(r"_(\d{4})Q([1-4])\.jsonl$", fp)] if m]
    if not qs:
        return "99999999"
    y, q = min((int(a), int(b)) for a, b in qs)
    start = W.dt.date(y, 3 * (q - 1) + 1, 1) - W.dt.timedelta(days=1)       # 첫 분기 시작 전날
    return DTH.shift(start.strftime("%Y%m%d"), 12)


def qpanel_per_pct(code, year, q, t, qp=None):
    """시점 t 의 PER 자기 역사 백분위 — 분기 패널의 같은 code · 같은 분기(year, q) 줄, 접수일 ≤ t 일 때만(시너지.per_pct_at).
    아직 접수 안 된 줄 · 미래 분기는 안 본다. 없으면 None(적자 · 이력 8분기 미만 · 패널 밖) — '싼 수주'는 통과 못 한다(감점 아님)."""
    return SYN.per_pct_at((QP if qp is None else qp).get((code, "%dQ%d" % (year, q))), t)


def derive(r):
    """행의 파생 셋(2026-10-14 v2) — 반영 갭(양쪽 300 자름) · lead(잔고 − 4분기 매출 %p) · per_pct(분기 패널 join).
    row_at 끝과 --report 에서 같이 부른다 — 세 값은 행의 다른 칸(backlog_yoy · price_1y · rev4_yoy · lab · t)에서 다시 나온다."""
    r["gap"] = SYN.gap_of(r.get("backlog_yoy"), r.get("price_1y"))
    r["lead"] = SYN.lead_of(r.get("backlog_yoy"), r.get("rev4_yoy"))
    lab = r.get("lab")
    r["per_pct"] = SYN.per_pct_at(QP.get((r["code"], lab)), r["t"]) if lab else None
    # 2026-10-20 v3 — 12개월 희석 · 부실(시점 t 까지). 창이 캐시 밖으로 잘리는 날(risk_from 전)은 '모름' — 감점 없음, v3 표에서 뺀다
    r["risk_known"] = r["t"] >= _RISK_FROM
    r["flags"] = SYN.risk_flags(risk_s12(r["code"], r["t"])) if r["risk_known"] else []
    return r


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
    # 재무는 나중 정정값일 수 있다 — cur 분기 '기준일'(정정 반영 접수일, 드러켄밀러.series)이 t 뒤면 rev4 · op4 · ni4(→ rev4_yoy · lead · m4 ·
    # per · PER≥40 단계)는 t 에 알 수 없던 값. 행은 패널에 남기되 amended_after 로 표시해 main · report 가 뺀다(2026-10-15 리뷰).
    # 기준일 없는 옛 원장은 fin_base None('모름'). 4분기 합의 앞 세 분기 · 1년 전 분기(q4)의 정정은 안 본다(한계)
    fin_base = (cur.get("기준일") or "")[:8] or None
    amended_after = bool(fin_base and fin_base > t)
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
    reliable = (tr["n"] >= 4 and not tr.get("jumps") and not tr.get("last_switch")   # 서버 why_not 과 같은 조건(2026-10-03)
                and sure >= (len(win) + 1) // 2 and (cover is None or cover >= 0.15))
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
         "lab": "%dQ%d" % (cur["year"], cur["q"]),       # 마지막 분기 — 분기 패널 per_pct join 키
         "fin_base": fin_base, "amended_after": amended_after,
         "loss4": (op4 is not None and op4 <= 0) or (ni4 is not None and ni4 <= 0)}
    derive(r)                                           # gap(양쪽 자름) · lead · per_pct(접수일 ≤ t)
    r["stage"], _ = SYN.stage(r)
    t0 = W.next_day(P["code"], t)          # 들어가는 날 = 그달 말 다음 거래일 종가(억울_백테스트.next_day)
    for h, days in W.H.items():
        t1 = W.shift(t0, days) if t0 else None
        a, u = (W.ret(P["code"], t0, t1), W.grp_ret("__all__", t0, t1)) if t0 else (None, None)
        r["ex" + h] = (a - u) if (a is not None and u is not None) else None
    return r


def score_v2(rows):
    """2026-10-14 v2 점수(2026-10-20 까지 화면 식) — 선행 .35 · 전환 .25 · 가격(반영 갭) .25, 확인 0(백테스트엔 공시 금액이 없다), 결측 50,
    선행 없으면 None. 감점은 없다(v2 백테스트는 악재 자료가 없었다). v3 와 같은 행에서 견주려고 얼려 둔다."""
    ok = rows
    R = {"btb": SYN._pct_rank([r.get("btb") for r in ok]), "cov": SYN._pct_rank([r.get("cover_chg") for r in ok]),
         "low": SYN._pct_rank([-SYN._margin(r) for r in ok if SYN._profit4(r)]), "gap": SYN._pct_rank([r.get("gap") for r in ok])}
    W2 = {"선행": .35, "전환": .25, "가격": .25}
    for r in rows:
        a, b = R["btb"](r.get("btb")), R["cov"](r.get("cover_chg"))
        lead = ((a or 0) * .5 + (b or 0) * .5) / ((.5 if a is not None else 0) + (.5 if b is not None else 0)) if (a is not None or b is not None) else None
        p = {"선행": lead, "전환": R["low"](-SYN._margin(r)) if SYN._profit4(r) else None, "가격": R["gap"](r.get("gap"))}
        r["p_선행"], r["p_전환"], r["p_가격"] = (round(p[k]) if p[k] is not None else None for k in ("선행", "전환", "가격"))
        r["score_v2"] = None if lead is None else round(sum((50.0 if p[k] is None else p[k]) * w for k, w in W2.items()) / sum(W2.values()), 1)


def score_date(rows):
    """지금 화면 식(SYN.score — v3)과 v2 · 예전 식을 함께 매긴다. 위험 표지(flags)는 derive 가 시점마다 센 값 — 없으면 []."""
    for r in rows:
        r.update(reliable=True, new_pct=None, flags=r.get("flags") or [])
    SYN.score(rows)
    for r in rows:
        r["p_수주"], r["p_값"], r["p_여지"] = (r["parts"].get(k) for k in ("수주", "값", "여지"))
        del r["parts"]
    score_v2(rows)
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


_RISK_FROM = risk_from()


def boot_year(rows, fn, n=800, seed=11):
    """해(年) 단위 재표본 90% 구간 — 같은 해의 시장 충격을 한 덩어리로(회사 재표본만 하면 구간이 좁게 나온다, 2026-10-20 감사)."""
    import random
    by = {}
    for r in rows:
        by.setdefault(r["t"][:4], []).append(r)
    yrs = sorted(by)
    rnd = random.Random(seed)
    vals = sorted(v for v in (fn([x for y in (rnd.choice(yrs) for _ in yrs) for x in by[y]]) for _ in range(n)) if v is not None)
    return (vals[int(len(vals) * .05)], vals[int(len(vals) * .95)]) if vals else (None, None)


def _tspread(key, Y):
    """날짜 안 분위(key) 상⅓ 중앙 − 하⅓ 중앙. 양쪽 6행↑일 때만."""
    def f(sub):
        lo = [r[Y] for r in sub if r[key] < 100.0 / 3]
        hi = [r[Y] for r in sub if r[key] >= 200.0 / 3]
        return st.median(hi) - st.median(lo) if len(lo) > 5 and len(hi) > 5 else None
    return f


def m1_test(rows, key, Y="ex12m", label=True):
    """스펙 2절 주 지표 — rows(보통 둔화 뺀) 안 key 의 날짜 안 분위 상⅓ − 하⅓. 회사 · 해 재표본 90% · ~2019 / 2020~ ·
    믿음 표지(회사 하한 > 0 · 해 하한 > 0 · 앞 > 0 · 뒤 > 0 이면 '근거 있음'). 한 기간만 든 부분 표본(잠복 2020~)은 label=False —
    앞 기간이 늘 비어 표지가 늘 '약함'으로 나오던 것(2026-10-20 리뷰)을 없앤다."""
    rs = [dict(r, _p=r.get(key)) for r in rows if r.get(Y) is not None and r.get(key) is not None]
    rs = SYN.date_pct(rs, "_p", "t")
    if len(rs) < 30:
        return None
    sp = _tspread("_p", Y)
    c, yr = W.boot(rs, sp), boot_year(rs, sp)
    e, l = sp([r for r in rs if r["t"] < W.SPLIT]), sp([r for r in rs if r["t"] >= W.SPLIT])
    ok = all(x is not None and x > 0 for x in (c[0], yr[0], e, l))
    return {"spread": sp(rs), "ci": list(c), "ci_year": list(yr), "early": e, "late": l, "n": len(rs),
            "firms": len({r["code"] for r in rs}), "label": ("근거 있음" if ok else "근거 약함") if label else None}


def paired_test(rows, ka, kb, Y="ex12m"):
    """같은 행에서 ka 의 상⅓−하⅓ − kb 의 상⅓−하⅓(둘 다 날짜 안 분위). 회사 재표본 90% · ~2019 / 2020~."""
    rs = [dict(r, _a=r.get(ka), _b=r.get(kb)) for r in rows if r.get(Y) is not None and r.get(ka) is not None and r.get(kb) is not None]
    rs = SYN.date_pct(SYN.date_pct(rs, "_a", "t"), "_b", "t")
    if len(rs) < 30:
        return None
    sa, sb = _tspread("_a", Y), _tspread("_b", Y)

    def d(sub):
        x, y = sa(sub), sb(sub)
        return (x - y) if (x is not None and y is not None) else None
    c = W.boot(rs, d)
    return {"diff": d(rs), "ci": list(c), "a": sa(rs), "b": sb(rs), "early": d([r for r in rs if r["t"] < W.SPLIT]),
            "late": d([r for r in rs if r["t"] >= W.SPLIT]), "n": len(rs),
            "verdict": "나았다" if (c[0] is not None and c[0] > 0) else ("못했다" if (c[1] is not None and c[1] < 0) else "차이를 확신할 수 없다")}


def v3_report(rows, nd, Y="ex12m"):
    """2026-10-20 v3 — 스펙 2절에 미리 적은 표. 화면 '과거 검증' 상자와 종목 해석이 label 을 읽는다.
    위험 창이 캐시 밖으로 잘리는 날(risk_known False — 2013-06 ~ 2013-11)은 뺀다(스펙 뒤 고침, README 에 적음)."""
    n0, nd0 = len(rows), len(nd)
    rows = [r for r in rows if r.get("risk_known", True)]
    nd = [r for r in nd if r.get("risk_known", True)]
    out = {"spec": "docs/superpowers/specs/2026-10-20-synergy-score-v3-design.md", "risk_from": _RISK_FROM,
           "dropped_rows": n0 - len(rows), "dropped_no_slow": nd0 - len(nd)}
    out["m1"] = m1_test(nd, "score", Y)                       # 주 지표 — 둔화 뺀 안 v3
    out["m1_v2"] = m1_test(nd, "score_v2", Y)                 # 같은 잣대로 v2
    out["m1_all"] = m1_test(rows, "score", Y)                 # 전체 행(둔화 포함)
    out["paired"] = paired_test(nd, "score", "score_v2", Y)   # v3 − v2, 둔화 뺀 같은 행
    lat = [r for r in nd if r["stage"] == "잠복" and r["t"] >= W.SPLIT]
    out["latent_late"] = m1_test(lat, "score", Y, label=False)   # 잠복만 2020~ (앞 기간은 날짜당 행이 적다) — 믿음 표지 없음
    out["ic"] = W.ic_stats(nd, lambda r: r.get("score"), Y, overlap=12)
    out["ic_v2"] = W.ic_stats(nd, lambda r: r.get("score_v2"), Y, overlap=12)
    # 위험 표지 — 둔화 뺀 안에서 있음 vs 없음
    out["risk"] = {}
    for nm, f in (("없음", lambda r: not r.get("flags")), ("희석", lambda r: any(x.startswith("희석") for x in r.get("flags") or [])),
                  ("부실", lambda r: any(x.startswith("부실") for x in r.get("flags") or []))):
        sub = [r for r in nd if f(r)]
        s = W.summ(sub, Y) if sub else None
        if not s:
            continue
        lo, hi = W.boot(sub, lambda x: st.median([r[Y] for r in x]) if x else None)
        e = [r[Y] for r in sub if r["t"] < W.SPLIT]
        l = [r[Y] for r in sub if r["t"] >= W.SPLIT]
        out["risk"][nm] = dict(s, ci=[lo, hi], early=st.median(e) if e else None, late=st.median(l) if l else None,
                               worst=sum(1 for r in sub if r[Y] < -30) / len(sub) * 100)
    out["coverage"] = {"per_pct": sum(1 for r in nd if r.get("per_pct") is not None), "loss4": sum(1 for r in nd if r.get("loss4")),
                       "flags": sum(1 for r in nd if r.get("flags")), "n": len(nd)}

    def fm(x):
        return "—" if x is None else "%+.1f" % x
    print("\n== v3 (스펙 2026-10-20) — 둔화 뺀 안 상⅓ − 하⅓")
    for k in ("m1", "m1_v2", "m1_all", "latent_late"):
        x = out[k]
        if x:
            print("  %-12s 차 %s 회사 %s~%s 해 %s~%s | ~2019 %s 2020~ %s | n %d (%d곳) → %s" % (
                k, fm(x["spread"]), fm(x["ci"][0]), fm(x["ci"][1]), fm(x["ci_year"][0]), fm(x["ci_year"][1]),
                fm(x["early"]), fm(x["late"]), x["n"], x["firms"], x["label"] or "—"))
    pt = out["paired"]
    if pt:
        print("  v3 − v2 짝 차 %s [%s, %s] (v3 %s · v2 %s) ~2019 %s 2020~ %s → %s" % (
            fm(pt["diff"]), fm(pt["ci"][0]), fm(pt["ci"][1]), fm(pt["a"]), fm(pt["b"]), fm(pt["early"]), fm(pt["late"]), pt["verdict"]))
    for nm, x in out["risk"].items():
        print("  위험 %-4s 표본 %5d (%3d곳) 중앙 %s [%s, %s] −30%%↓ %2.0f%% | ~2019 %s 2020~ %s" % (
            nm, x["n"], x["firms"], fm(x["median"]), fm(x["ci"][0]), fm(x["ci"][1]), x["worst"], fm(x["early"]), fm(x["late"])))
    return out


FACTORS = [
    ("score_old", "예전 점수(확인 뺌)", lambda r: r["score_old"]),
    ("score", "지금 점수 v3(수주 · 값 · 여지 − 위험)", lambda r: r["score"]),
    ("p_수주", "  수주 부분", lambda r: r.get("p_수주")),
    ("p_값", "  값 부분", lambda r: r.get("p_값")),
    ("p_여지", "  여지 부분", lambda r: r.get("p_여지")),
    ("score_v2", "v2 점수(선행 · 전환 · 가격)", lambda r: r.get("score_v2")),
    ("p_선행", "  v2 선행 부분", lambda r: r.get("p_선행")),
    ("p_전환", "  v2 전환 부분", lambda r: r.get("p_전환")),
    ("p_가격", "  v2 가격 부분", lambda r: r.get("p_가격")),
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
    # 2026-10-14 v2 — 가치 대비 가격(자기 역사 PER 위치)과 잔고 − 매출 선행. 둔화 뺀 표본의 IC · 상⅓−하⅓ 도 같이 적는다
    ("per_pct", "PER 자기 역사 %(낮을수록 싸다)", lambda r: r.get("per_pct")),
    ("lead", "잔고 − 4분기 매출(%p)", lambda r: max(min(r["lead"], 300), -300) if r.get("lead") is not None else None),
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
        if r.get("amended_after"):          # cur 재무가 t 뒤 정정값인 행 — 그 날 백분위에도 안 든다(패널 파일엔 남긴다)
            continue
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
    # cur 재무가 t 뒤 정정값인 행(amended_after)은 뺀다 — 옛 패널(키 없음)은 전부 든다
    rows = [r for r in panel if r.get(Y) is not None and not r.get("amended_after")]
    allv = [r[Y] for r in rows]
    nd = [r for r in rows if r["stage"] != "둔화"]          # 둔화 뺀 나머지 — per_pct · lead 의 근거 표본

    def band(sub):
        """묶음 요약 — 중앙 · 회사 단위 부트스트랩 90% · 앞/뒤 기간 중앙."""
        s = W.summ(sub, Y)
        if not s:
            return None
        lo, hi = W.boot(sub, lambda x: st.median([r[Y] for r in x]) if x else None)
        e = [r[Y] for r in sub if r["t"] < W.SPLIT]
        l = [r[Y] for r in sub if r["t"] >= W.SPLIT]
        return dict(s, ci=[lo, hi], early=st.median(e) if e else None, late=st.median(l) if l else None, n_early=len(e), n_late=len(l))

    def band_line(lab, x):
        print("  %-4s 표본 %5d (%3d곳) 중앙 %+6.1f 90%%CI %+6.1f~%+6.1f 평균 %+6.1f 이긴 %3.0f%% | ~2019 %s(n%d) 2020~ %s(n%d)" % (
            lab, x["n"], x["firms"], x["median"], x["ci"][0], x["ci"][1], x["mean"], x["hit"],
            "%+.1f" % x["early"] if x["early"] is not None else "—", x["n_early"],
            "%+.1f" % x["late"] if x["late"] is not None else "—", x["n_late"]))
    print("\n== 단계별 12개월 초과수익 (같은 기간 전 종목 중앙값 대비, %%)  전체 표본 %d건 · %d곳 · 중앙 %+.1f" % (
        len(rows), len({r['code'] for r in rows}), st.median(allv)))
    # 전체 · 둔화 뺀 나머지 — 요약줄의 기준점(단계 중앙만 적으면 표본 기저 +2 가 안 보인다, 2026-10-14 감사 ①)
    out["overall"] = band(rows)
    ns = band(nd)
    band_line("전체", out["overall"])
    if ns:
        band_line("둔화뺀", ns)
    for sg in ("잠복", "점화", "반영", "둔화", "관찰"):
        sub = [r for r in rows if r["stage"] == sg]
        if not sub:
            continue
        out["stages"][sg] = band(sub)
        band_line(sg, out["stages"][sg])
    out["coverage"] = {"n": len(rows), "no_slow": len(nd),
                       "per_pct": sum(1 for r in rows if r.get("per_pct") is not None),
                       "per_pct_no_slow": sum(1 for r in nd if r.get("per_pct") is not None),
                       "lead": sum(1 for r in rows if r.get("lead") is not None),
                       # 재무 정정(2026-10-15 리뷰): cur 기준일 > t 라 뺀 행 · 기준일 없는(옛 원장, 모름) 행
                       "amended_after": sum(1 for r in panel if r.get("amended_after")),
                       "fin_base_unknown": sum(1 for r in rows if not r.get("fin_base"))}
    cv = out["coverage"]
    print("  per_pct 있는 행 %d/%d (둔화 뺀 %d/%d) · lead 있는 행 %d/%d — PER 없는 행(적자 · 이력 8분기 미만)은 '싼 수주' 해당 없음" % (
        cv["per_pct"], cv["n"], cv["per_pct_no_slow"], cv["no_slow"], cv["lead"], cv["n"]))
    print("  cur 분기 재무가 t 뒤 정정값이라 뺀 행 %d · 기준일 없음(옛 원장, 모름) %d/%d" % (cv["amended_after"], cv["fin_base_unknown"], cv["n"]))
    print("\n== 항목별 — 날짜별 순위상관(IC) 평균과 세 묶음(상위⅓−하위⅓, 날짜 안 분위) 차이, 12개월 초과수익")
    print("  %-20s %7s %6s %5s %7s %7s | %7s %7s %7s  %-15s %s" % ("항목", "IC", "t", "양수", "~2019", "2020~", "하위⅓", "상위⅓", "차이", "90%구간", "~2019/2020~"))
    for k, nm, fx in FACTORS:
        ic = W.ic_stats(rows, fx, Y, overlap=12)
        tt = W.tercile_test(rows, fx, Y, by_date=True)      # 상⅓−하⅓ 컷은 날짜 안에서(2026-10-15 — pooled 컷은 기간 효과가 섞였다)
        if not ic or not tt:
            continue
        # 둔화 뺀 나머지 안에서도 — per_pct · lead 는 이 표본에서 앞/뒤 부호가 같은지가 근거다(2026-10-14 v2)
        out["factors"][k] = dict(ic, name=nm, no_slow=W.ic_stats(nd, fx, Y, overlap=12))
        out["terciles"][k] = dict(tt, name=nm, no_slow=W.tercile_test(nd, fx, Y, by_date=True))
        print("  %-20s %+7.3f %+6.2f %4.0f%% %+7.3f %+7.3f | %+7.1f %+7.1f %+7.1f  %+6.1f~%+6.1f  %s/%s" % (
            nm, ic["ic"], ic["t"], ic["pos"] * 100, ic["early"] or 0, ic["late"] or 0, tt["bot"], tt["top"], tt["spread"],
            tt["ci"][0], tt["ci"][1], "%+.0f" % tt["early"] if tt["early"] is not None else "—",
            "%+.0f" % tt["late"] if tt["late"] is not None else "—"))
    print("\n== 둔화를 뺀 나머지 안에서 — 항목별 IC · 상위⅓−하위⅓ (per_pct · lead 의 근거 표본, %d건)" % len(nd))
    print("  %-20s %7s %6s %5s %7s %7s | %7s %7s %7s  %-15s %s" % ("항목", "IC", "t", "양수", "~2019", "2020~", "하위⅓", "상위⅓", "차이", "90%구간", "~2019/2020~"))
    for k, nm, fx in FACTORS:
        ic = (out["factors"].get(k) or {}).get("no_slow")
        tt = (out["terciles"].get(k) or {}).get("no_slow")
        if not ic or not tt:
            continue
        print("  %-20s %+7.3f %+6.2f %4.0f%% %+7.3f %+7.3f | %+7.1f %+7.1f %+7.1f  %+6.1f~%+6.1f  %s/%s" % (
            nm, ic["ic"], ic["t"], ic["pos"] * 100, ic["early"] or 0, ic["late"] or 0, tt["bot"], tt["top"], tt["spread"],
            tt["ci"][0], tt["ci"][1], "%+.0f" % tt["early"] if tt["early"] is not None else "—",
            "%+.0f" % tt["late"] if tt["late"] is not None else "—"))
    print("\n== 잔고 기간·형태별 — 전체 / 둔화 뺀 나머지 (상위⅓−하위⅓, 12개월 초과수익)")
    nd0 = nd
    out["backlog"] = {}
    for k, nm, fx in BACKLOG_FACTORS:
        ic = W.ic_stats(rows, fx, Y, overlap=12)
        tt = W.tercile_test(rows, fx, Y, by_date=True)
        tn = W.tercile_test(nd0, fx, Y, by_date=True)
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
    # no_slow — 둔화 뺀 나머지의 중앙 · 90% 구간(화면 요약줄 "둔화 −y vs 나머지 +z") 위에 점수 상⅓−하⅓(score · score_old,
    # 예전 키 그대로 — 화면 NS.score 가 읽는다)을 얹는다
    out["no_slow"] = dict(ns or {}, **{k: W.tercile_test(nd, (lambda r, k=k: r.get(k)), Y, by_date=True) for k in ("score", "score_v2", "score_old")})
    print("\n== 둔화를 뺀 나머지 안에서 점수 상위⅓−하위⅓ (날짜 안 분위)")
    for k in ("score_old", "score_v2", "score"):
        x = out["no_slow"][k]
        if x:
            print("  %-10s 하 %+5.1f 상 %+5.1f 차 %+5.1f 90%% %+5.1f~%+5.1f" % (k, x["bot"], x["top"], x["spread"], x["ci"][0], x["ci"][1]))
    out["v3"] = v3_report(rows, nd, Y)
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
            derive(r)            # gap(양쪽 자름) · lead · per_pct 를 행에서 다시 채운다 — lab 이 없는 옛 패널은 per_pct None
            if r.get("amended_after"):       # 정정값 행은 main 과 같이 점수 · 보고 밖(패널에 기준일이 없으면 다시 재지 못한다 — 패널 재생성)
                continue
            by.setdefault(r["t"], []).append(r)
        for rows in by.values():
            score_date(rows)
        report(panel)
    else:
        main()

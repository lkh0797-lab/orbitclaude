# -*- coding: utf-8 -*-
"""
수출 선행 발굴 — 통관은 올랐는데 주가 · 값은 아직 (2026-10-14).
설계: docs/superpowers/specs/2026-10-14-export-lead-value-design.md

순수 함수만 둔다(서버 · 재무 · 관세청 import 없음). 서버(exlead_view)와 도구/수출선행_백테스트.py 가 같은 판정을 쓴다.
"""
import datetime as dt
import math

CLUE_MIN = 20.0        # 아직 공시 안 된 분기 통관 YoY — 이 위면 '수출 단서'
PRICE_DD = -25.0       # 52주 고점 대비 — 이 아래면 '주가는 아직'
VALUE_PCT_MAX = 50.0   # PER 자기 역사 백분위 — 이 아래면 '값은 싸다'
VALUE_MIN_N = 8        # PER 자기 역사 표본(분기) 하한 — 이보다 적으면 백분위를 믿지 않는다(값 모름). 저평가 백테스트 bt_panel per_pct 와 같은 문턱
DEBT_RED = 200.0       # 차입금/자본 — 저평가 탭과 같은 빨간불(금융업 제외)
MIN_COVER, MAX_COVER = 5.0, 150.0      # 수출추적._grade 와 같은 문턱(통관/매출 비중)
DUE_DAYS = {1: 45, 2: 45, 3: 45, 4: 90}


# ---------------------------------------------------------------- 분기 · 기한
def quarter_end(q):
    y, n = int(q[:4]), int(q[5])
    m = n * 3
    nx = dt.date(y + (m == 12), m % 12 + 1, 1)
    return nx - dt.timedelta(days=1)


def due_date(q):
    """분기 보고서 제출 기한 — 1 · 2 · 3분기 분기 말 + 45일, 4분기(사업보고서) + 90일. 토 · 일이면 다음 월요일(공휴일은 모른다)."""
    d = quarter_end(q) + dt.timedelta(days=DUE_DAYS[int(q[5])])
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def due_label(q, today):
    d = due_date(q)
    n = (d - today).days
    return {"due": d.isoformat(), "days": n,
            "text": ("D-%d · %s까지(≈)" % (n, d.strftime("%m-%d"))) if n >= 0 else ("D+%d · %s 지남" % (-n, d.strftime("%m-%d")))}


# ---------------------------------------------------------------- 적중 · 벌어짐 · 상관 · 등급
def hit_rate(pairs):
    ok = [(p.get("x"), p.get("r")) for p in pairs or [] if p.get("x") is not None and p.get("r") is not None]
    return sum(1 for x, r in ok if (x >= 0) == (r >= 0)), len(ok)


def gap(y12, px_yoy):
    return (y12 - px_yoy) if (y12 is not None and px_yoy is not None) else None


def pearson(a, b):
    xy = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(xy) < 3:
        return None
    mx = sum(x for x, _ in xy) / len(xy)
    my = sum(y for _, y in xy) / len(xy)
    sx = math.sqrt(sum((x - mx) ** 2 for x, _ in xy))
    sy = math.sqrt(sum((y - my) ** 2 for _, y in xy))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in xy) / (sx * sy)


def pit_grade(pairs, coverage):
    """시점 등급 — 수출추적._grade 와 같은 문턱. 쌍은 그 시점까지 공시된 분기만 넣는다."""
    ok = [p for p in pairs or [] if p.get("x") is not None and p.get("r") is not None]
    n = len(ok)
    if n < 6 or coverage is None or not (MIN_COVER <= coverage <= MAX_COVER):
        return "C"
    r = pearson([p["x"] for p in ok], [p["r"] for p in ok])
    if r is None:
        return "C"
    return "A" if (r >= 0.6 and n >= 8) else "B" if r >= 0.3 else "C"


# ---------------------------------------------------------------- 시점 자르기(백테스트)
def cut_series(mon, m):
    return {k: v for k, v in (mon or {}).items() if k <= m and v is not None}


def _q_of(ym):
    return "%sQ%d" % (ym[:4], (int(ym[4:]) - 1) // 3 + 1)


def _q_months(q):
    y, n = int(q[:4]), int(q[5])
    return ["%d%02d" % (y, (n - 1) * 3 + i) for i in (1, 2, 3)]


def rev_quarters(mon_cut, rev_yoy_by_q):
    """완성 분기(3개월 다 있는)의 통관 YoY x 와 매출 YoY r — 등급 · 적중 · 선형 맞춤에 쓰는 쌍."""
    out = []
    for q in sorted({_q_of(k) for k in mon_cut}):
        ms = _q_months(q)
        if not all(m in mon_cut for m in ms):
            continue
        ly = ["%d%s" % (int(m[:4]) - 1, m[4:]) for m in ms]
        cur, prev = sum(mon_cut[m] for m in ms), sum(mon_cut.get(m, 0) for m in ly)
        x = (cur / prev - 1) * 100 if prev > 0 and all(m in mon_cut for m in ly) else None
        r = rev_yoy_by_q.get(q)
        if x is None and r is None:
            continue
        out.append({"q": q, "x": x, "r": r})
    return out


def last_reported_q(fd, d):
    """접수일 fd[q] <= d 인 마지막 분기(없으면 None)."""
    qs = [q for q, t in (fd or {}).items() if t and t <= d]
    return max(qs) if qs else None


def pit_pairs(mon, rev_yoy_by_q, fd, m, d):
    """시점 d(= 통관 달 m 의 다음 달 16일)에서 알 수 있던 쌍 — 통관 ≤ m, 매출은 접수일 ≤ d 인 분기만."""
    cut = cut_series(mon, m)
    rev_d = {q: v for q, v in (rev_yoy_by_q or {}).items() if (fd or {}).get(q) and fd[q] <= d}
    return [p for p in rev_quarters(cut, rev_d) if p["x"] is not None and p["r"] is not None]


# ---------------------------------------------------------------- 판정
def _pct(v):
    return ("%+.0f%%" % v) if v is not None else "모름"


def judge(inp):
    """세 조건 + 빨간불 → {"tier": "발굴"|"관찰"|None, "why": [...], "checks": {...}}.
    inp: grade, lumpy, reported, cur, months, ret3m, univ3m, dd52, per_pct, per_n(PER 표본 수 — 없으면 안 본다), red[list], risk[list], fin."""
    clue = (inp.get("grade") in ("A", "B") and not inp.get("lumpy") and inp.get("reported") is False
            and inp.get("cur") is not None and inp["cur"] >= CLUE_MIN)
    checks = {"clue": bool(clue), "price": None, "value": None, "red": False}
    if not clue:
        return {"tier": None, "why": [], "checks": checks}
    why = []
    ret3m, univ, dd = inp.get("ret3m"), inp.get("univ3m"), inp.get("dd52")
    if ret3m is None:                                     # 이력 91일 미만(신규 상장) — 짧은 창의 고점은 52주 고점이 아니라 dd 로도 못 판다(설계 1절: 모름)
        why.append("주가 모름 — 이력 91일 미만")
    elif dd is not None and dd <= PRICE_DD:
        checks["price"] = True
    elif univ is not None:
        checks["price"] = ret3m <= univ
        if not checks["price"]:
            why.append("주가 3개월 %s — 전 종목 중앙 %s 보다 이미 올랐다(고점 대비 %s)" % (_pct(ret3m), _pct(univ), _pct(dd)))
    else:
        why.append("주가 모름 — 전 종목 3개월 중앙값 모름")
    pp, pn = inp.get("per_pct"), inp.get("per_n")
    if pp is None:
        why.append("값 모름 — PER 없음(적자 · 표본 부족 · 풍경 없음)")
    elif pn is not None and pn < VALUE_MIN_N:             # 표본이 적은 백분위는 단정하지 않는다 — 과거 검증(bt_panel, 8분기↑)과 같은 조건
        why.append("값 모름 — PER 표본 %d분기(%d 미만)" % (pn, VALUE_MIN_N))
    else:
        checks["value"] = pp <= VALUE_PCT_MAX
        if not checks["value"]:
            why.append("PER 자기 역사 상위 %d%% — 싸지 않다" % round(100 - pp))
    red = list(inp.get("red") or [])
    risk = list(inp.get("risk") or [])
    if red or risk:
        checks["red"] = True
        why.extend("빨간불: " + r for r in red)
        why.extend(risk)
    tier = "발굴" if (checks["price"] is True and checks["value"] is True and not checks["red"]) else "관찰"
    return {"tier": tier, "why": why, "checks": checks}


def last_final_day(last_dates):
    """전 종목 마지막(확정) 봉 날짜들의 중앙값(YYYYMMDD) — 과거 검증의 지평 끝은 이 날을 넘으면 '모름'.
    최대값이 아니라 중앙값: 주가 캐시가 반쯤 새로 받아진 상태(일부만 오늘 봉)에서 벤치마크가 묵은 봉과 섞이지 않게. 없으면 None."""
    ks = sorted(k for k in (last_dates or []) if k)
    return ks[len(ks) // 2] if ks else None


# ---------------------------------------------------------------- 그림 재료
def _ym_shift(ym, k):
    y, m = int(ym[:4]), int(ym[4:]) - k
    while m <= 0:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return "%04d%02d" % (y, m)


def index_series(mon, px_m, n=24):
    """마지막 n 개월 — x: 12개월 합 지수(첫 완성 달 = 100, 그 전은 100), p: 월말 주가 지수(첫 유효 달 = 100, 빠진 달 None)."""
    ks = sorted(k for k in (mon or {}) if mon[k] is not None)
    if not ks:
        return []
    last = ks[-1]
    yms = [_ym_shift(last, n - 1 - i) for i in range(n)]
    roll = {}
    for ym in yms:
        w = [_ym_shift(ym, k) for k in range(12)]
        roll[ym] = sum(mon[k] for k in w) if all(k in mon and mon[k] is not None for k in w) else None
    x0 = next((roll[ym] for ym in yms if roll[ym]), None)
    p0 = next((px_m[ym] for ym in yms if px_m.get(ym)), None)
    out = []
    for ym in yms:
        x = (roll[ym] / x0 * 100) if (roll[ym] and x0) else (100.0 if x0 else None)
        p = (px_m[ym] / p0 * 100) if (px_m.get(ym) and p0) else None
        out.append({"ym": ym, "x": x, "p": p})
    return out

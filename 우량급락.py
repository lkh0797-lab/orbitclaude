# -*- coding: utf-8 -*-
"""
우량 급락 — 꾸준히 버는 큰 회사가 급락했을 때 (2026-10-20, 설계 docs/superpowers/specs/2026-10-20-qualdip-design.md)

출처: 한 개인 투자자가 2026-10-16 인증한 12종목("수익은 꾸준한데 주가가 일시적으로 급락, 성장성도 뒷받침")을 전 종목과 견줘 역산한 잣대.
관문 여덟(TH — 사전 등록, 결과를 보고 바꾸지 않는다):
  ① 큰 회사      그날 시가총액 순위 ≤ 300
  ② 이익 꾸준    알게 된 최근 12분기 가운데 분기 영업적자 ≤ 1
  ③ 돈 잘 범     ROE(최근 4분기 지배순이익 ÷ 최근 자본총계) ≥ 10%
  ④ 마진         4분기 합 영업이익률 ≥ 10% — 매출 줄이 없는 금융(KSIC 64~66)은 통과
  ⑤ 성장         4분기 합 매출 또는 영업이익의 3년 연평균 ≥ +5%
  ⑥ 최근 빠짐    3개월(91일) 주가 수익률 ≤ −10%
  ⑦ 자기 역사로 쌈  PER 자기 역사 자리(최근 40분기) 또는 POR 자리(최근 20분기) ≤ 30%
  ⑧ 덜 출렁임    250거래일 변동성(연율)이 그날 전 종목 가운데 자리 50% 이하(중앙 이하)
후보 = 여덟 다 · 아깝게 = 일곱. 순위 = 열한 특징의 그날 횡단 백분위 평균(FEATS).
시점: 탑픽과 같다 — 그날까지 알게 된 분기(정정 포함 접수일)와 그날 종가(도구가 s−1 을 넘긴다).
이 파일은 순수 함수만 — 서버 · 도구 · 시험이 같이 쓴다. 분기 줄 · 주가 · 시가총액 · POR 은 탑픽.py 를 그대로 쓴다.
"""
import bisect
import math
import statistics as st

VERSION = 1

TH = {"cap_rank": 300, "loss_max": 1, "roe": 10.0, "opm": 10.0, "growth": 5.0, "r3m": -10.0, "cheap": 30.0, "vol_q": 50.0}
TH_NAME = {"cap_rank": "시총 순위", "loss_max": "적자 분기 수", "roe": "ROE", "opm": "영업이익률", "growth": "3년 성장",
           "r3m": "3개월 수익률", "cheap": "자기 역사 자리", "vol_q": "변동성 분위"}
GATES = [  # (키, 짧은 이름, 설명)
    ("cap", "큰 회사", "그날 시가총액 300위 안"),
    ("steady", "이익 꾸준", "최근 12분기 영업적자 1개 이하"),
    ("roe", "ROE", "최근 4분기 지배순이익 ÷ 자본총계 ≥ 10%"),
    ("opm", "마진", "4분기 합 영업이익률 ≥ 10%(매출 없는 금융은 통과)"),
    ("growth", "성장", "매출 또는 영업이익 3년 연 +5%↑"),
    ("drop", "최근 빠짐", "3개월 주가 −10%↓"),
    ("cheap", "자기 역사로 쌈", "PER(40분기) 또는 POR(20분기) 자기 역사 하위 30%"),
    ("calm", "덜 출렁임", "1년 변동성이 전 종목 중앙 이하"),
]
QUALITY = ("cap", "steady", "roe", "opm", "growth", "calm")     # 기준선 '우량만' — 급락 · 싸다 없이
FEATS = {"lmcap": 1, "roe": 1, "opm": 1, "vol": -1, "r3m": -1, "rev_cagr3": 1, "ttm_min_max": 1, "op_cv12": -1, "per_pct": -1, "por_pct": -1, "loss_q12": -1}
FIN_KSIC = ("64", "65", "66")


# ---------------------------------------------------------------- 변동성 — 누적합으로 날짜마다 빠르게
class Vol:
    """보정 종가 {code: {YYYYMMDD: 종가}} → vol(code, d) = d 까지 마지막 250거래일 일간 로그수익 표준편차 × √250 × 100(%). 봉이 모자라면 None."""

    def __init__(self, data, days=250):
        self.days = days
        self.ks, self.c1, self.c2 = {}, {}, {}
        for code, s in (data or {}).items():
            if not s:
                continue
            ks = sorted(s)
            c1, c2, a, b = [0.0], [0.0], 0.0, 0.0
            for i in range(1, len(ks)):
                x, y = s[ks[i - 1]], s[ks[i]]
                r = math.log(y / x) if (x and y and x > 0 and y > 0) else 0.0
                a += r
                b += r * r
                c1.append(a)
                c2.append(b)
            self.ks[code], self.c1[code], self.c2[code] = ks, c1, c2

    def vol(self, code, d):
        ks = self.ks.get(code)
        if not ks:
            return None
        i = bisect.bisect_right(ks, str(d)) - 1
        n = self.days
        if i < n:
            return None
        c1, c2 = self.c1[code], self.c2[code]
        s1, s2 = c1[i] - c1[i - n], c2[i] - c2[i - n]
        var = s2 / n - (s1 / n) ** 2
        return math.sqrt(max(var, 0.0)) * math.sqrt(250) * 100


# ---------------------------------------------------------------- 한 회사 · 한 날 — 재무 특징
def fund(K, pxf):
    """K = 그날까지 알게 된 분기 줄(탑픽.series_of → known_until). pxf(d) = 보정 종가.
    돌려주는 것: 적자 분기 수 · 분기 영업이익 변동계수 · 4분기 합 최저/최고 · 3년 연평균(영업이익 · 매출) · 영업이익률 · ROE · PER 자기 역사 자리."""
    if not K:
        return None
    last = K[-1]
    by = {s["n"]: s for s in K}
    q12 = [s for s in K if s["n"] > last["n"] - 12]
    ops = [s["op"] for s in q12 if s["op"] is not None]
    ttms = [s["ttm"] for s in K if s["ttm"] is not None and s["n"] > last["n"] - 12]
    m_ = st.mean(ops) if len(ops) >= 8 else None
    op_cv = (st.pstdev(ops) / abs(m_)) if (m_ and len(ops) >= 8) else None
    if len(ttms) >= 8:
        ttm_mm = (min(ttms) / max(ttms)) if (max(ttms) > 0 and min(ttms) > 0) else 0.0
    else:
        ttm_mm = None

    def at(nn, key):
        s = by.get(nn)
        return s.get(key) if s else None
    t0, t12 = at(last["n"], "ttm"), at(last["n"] - 12, "ttm")
    r0, r12 = at(last["n"], "rev_ttm"), at(last["n"] - 12, "rev_ttm")
    cagr = lambda a, b: (((a / b) ** (1 / 3) - 1) * 100) if (a and b and a > 0 and b > 0) else None     # noqa: E731
    ni4 = [s["ni"] for s in K[-4:]] if len(K) >= 4 and K[-4]["n"] == last["n"] - 3 else []
    ni_ttm = sum(ni4) if (len(ni4) == 4 and all(x is not None for x in ni4)) else None
    eq = next((s.get("eq") for s in reversed(K) if s.get("eq")), None)
    hist = []
    for s in K[-41:-1]:
        e = s.get("eps_ttm")
        if e and e > 0 and s.get("ttm_ok"):
            p = pxf(s.get("filed0") or s["known"])
            if p:
                hist.append(p / e)
    e_now = last.get("eps_ttm") if last.get("ttm_ok") else None
    return {"lab": last["label"], "known": last["known"], "loss_q12": sum(1 for x in ops if x <= 0), "nq12": len(ops), "op_cv12": op_cv,
            "ttm_min_max": ttm_mm, "ttm_cagr3": cagr(t0, t12), "rev_cagr3": cagr(r0, r12),
            "opm": (t0 / r0 * 100) if (t0 is not None and r0) else None,
            "roe": (ni_ttm / eq * 100) if (ni_ttm is not None and eq and eq > 0) else None,
            "per_hist": hist, "eps_ttm": e_now}


def per_pct(hist, per):
    """PER 자기 역사 자리 — (지금보다 작은 과거 값 + 같은 값 × ½) ÷ 과거 값 수 × 100. 과거 8개 미만이면 None."""
    if per is None or len(hist) < 8:
        return None
    return (sum(1 for v in hist if v < per) + 0.5 * sum(1 for v in hist if v == per)) / len(hist) * 100


def gates(r, th=TH):
    """특징 행 r(그날 횡단 값 cap_rank · vol_pct 가 붙은 것) → {관문: True/False}. 값이 없으면 False(금융 마진만 예외)."""
    g = {}
    g["cap"] = r.get("cap_rank") is not None and r["cap_rank"] <= th["cap_rank"]
    g["steady"] = (r.get("nq12") or 0) >= 8 and r.get("loss_q12") is not None and r["loss_q12"] <= th["loss_max"]
    g["roe"] = r.get("roe") is not None and r["roe"] >= th["roe"]
    if r.get("opm") is not None:
        g["opm"] = r["opm"] >= th["opm"]
    else:
        g["opm"] = str(r.get("ksic") or "").startswith(FIN_KSIC)
    g["growth"] = any(r.get(k) is not None and r[k] >= th["growth"] for k in ("rev_cagr3", "ttm_cagr3"))
    g["drop"] = r.get("r3m") is not None and r["r3m"] <= th["r3m"]
    g["cheap"] = any(r.get(k) is not None and r[k] <= th["cheap"] for k in ("per_pct", "por_pct"))
    g["calm"] = r.get("vol_pct") is not None and r["vol_pct"] <= th["vol_q"]
    return g


def pct_maps(rows, feats=FEATS):
    """그날 횡단 백분위 {특징: {code: 0~100}} — 큰 값이 100 쪽."""
    out = {}
    for f in feats:
        vals = sorted(r[f] for r in rows if r.get(f) is not None)
        n = len(vals)
        m = {}
        for r in rows:
            v = r.get(f)
            if v is None or not n:
                continue
            lo, hi = bisect.bisect_left(vals, v), bisect.bisect_right(vals, v)
            m[r["code"]] = (lo + 0.5 * (hi - lo)) / n * 100
        out[f] = m
    return out


def score_rows(rows, feats=FEATS):
    """같은 날 행들 → r['score'](열한 특징 방향 맞춘 백분위 평균, 60% 이상 있을 때) · r['parts']."""
    pm = pct_maps(rows, feats)
    for r in rows:
        xs, parts = [], {}
        for f, sgn in feats.items():
            v = pm[f].get(r["code"])
            if v is None:
                continue
            v = v if sgn > 0 else 100 - v
            parts[f] = round(v, 1)
            xs.append(v)
        r["score"] = round(sum(xs) / len(xs), 1) if len(xs) >= len(feats) * 0.6 else None
        r["parts"] = parts
    return rows


def cross_section(rows, th=TH):
    """같은 날 행들에 시총 순위 · 변동성 자리(0~100, 낮을수록 덜 출렁임) · 관문 · 통과 수를 붙인다. rows = 특징 행(mcap · vol 등)."""
    neg = sorted(-r["mcap"] for r in rows if r.get("mcap"))
    vols = sorted(r["vol"] for r in rows if r.get("vol") is not None)
    nv = len(vols)
    for r in rows:
        r["cap_rank"] = (bisect.bisect_left(neg, -r["mcap"]) + 1) if r.get("mcap") else None
        if r.get("vol") is not None and nv:
            lo, hi = bisect.bisect_left(vols, r["vol"]), bisect.bisect_right(vols, r["vol"])
            r["vol_pct"] = (lo + 0.5 * (hi - lo)) / nv * 100
        else:
            r["vol_pct"] = None
        apply_gates(r, th)
    return rows


def apply_gates(r, th=TH):
    r["gates"] = gates(r, th)
    r["n_pass"] = sum(r["gates"].values())
    r["miss"] = [k for k, _, _ in GATES if not r["gates"][k]]
    return r


def sens_variants(th=TH):
    """문턱마다 ×0.5 · ×1.5 하나씩 — 기본값 먼저. vol_q(중앙)는 25 · 75 분위로."""
    out = [("기본", dict(th))]
    for k in ("cap_rank", "loss_max", "roe", "opm", "growth", "r3m", "cheap", "vol_q"):
        for f in (0.5, 1.5):
            t = dict(th)
            v = th[k] * f
            if k in ("cap_rank", "loss_max"):
                v = int(round(v))
            t[k] = v
            out.append(("%s ×%.1f" % (TH_NAME[k], f), t))
    return out

# -*- coding: utf-8 -*-
"""
탑픽 — 실적은 좋아졌거나 사상 최대인데, 시가총액은 아직 그만큼 오르지 않은 회사 (2026-10-20)

시점 규칙(사용자, 고정): 어떤 날 s 의 신호든 s−1 까지 접수된 보고서와 s−1 종가 시가총액만 쓴다. 분기 말이 아니라 접수일이다.
  값을 '아는 날' = druck 기준일(원본 또는 정정 접수일 가운데 늦은 날 — 시리즈 값이 마지막 원장이라 정정 뒤에야 그 값을 안다, 엄격). 4분기 합은 창 네 분기를 다 아는 날.
  '알린 날' = 원본 정기보고서 접수일(사건 패널의 사건일 · 역사 POR 의 주가일 · 먼저 알려진 날 비교). 원본 날에 정정값을 안 것으로 보는 느슨한 판은 민감도 줄로만.
문턱(사용자, 고정 — TH): 성과를 보고 바꾸지 않는다. 대신 문턱마다 ×0.5 · ×1.5 민감도 표만 낸다(도구/탑픽_백테스트.py).

신호(기본값)
  A 실적 개선  A1: 최근 분기 영업이익 전년 대비 ≥ +20% 그리고 매출 전년 대비 ≥ +5%. A2: 영업이익 적자 → 흑자.
               전년 대비는 그 보고서에 적힌 비교값(_전 — 공시 당시 숫자)으로, 없으면 시리즈의 4분기 앞 값(flag 'yoy_series').
               기저가 매출의 1% 미만인 양수면 전년 대비는 뜻이 없어 A1 을 보지 않는다(flag 'tiny_base' — 드러켄밀러 '무의미' 규칙과 같다).
               흑자 전환인데 영업이익이 매출의 1% 미만이면 A2 로 치지 않는다(flag 'thin_profit'). 순위에 쓰는 전년 대비는 +200% 에서 자른다.
  B 실적 신고점  최근 4분기 합 영업이익이 자료 안 과거 모든 4분기 합의 최고치보다 크다(과거 값 12개↑ — 연결/별도 섞인 창 · 빈 창은 뺀다).
  C1 괴리      4분기 합 영업이익 증가율(4분기 전 합 대비) − 시가총액 증가율(1년 전 같은 날 대비) ≥ +30%p.
               4분기 전 합이 0 이하였고 지금 양수면 증가율을 +200(상한)으로 본다(flag 'ttm_turn'). 통과 판정은 날것 증가율, 순위는 상한값.
  C2 자기 배수  지금 POR(시가총액 ÷ 4분기 합 영업이익)이 자기 과거 최근 20분기 POR(각 분기 접수일 시가총액 ÷ 그 4분기 합, 양수만, 12개↑)
               가운데 하위 30% 안 — 자리 = (지금보다 작은 과거 값 수 + 같은 값 × ½) ÷ 과거 값 수.
  유동성       20거래일(시장 달력) 평균 거래대금 ≥ 10억 원 — 봉이 없는 날은 0(거래정지 종목은 저절로 떨어진다).
후보 = 적격 그리고 (A 또는 B) 그리고 C1 그리고 C2 그리고 유동성.
적격 = 신호 분기가 온전하고(연결/별도 · 범위 어긋남 없음) · 최근 보고서가 150일 안이고 · 금융(KSIC 64~66, 매출 없는 회사) · 순수 지주(영업이익 > 매출인 분기)가 아니고 ·
       지금 · 1년 전 시가총액(주식 수)을 알고 · 과거 4분기 합 12개↑ · 거래대금을 잴 수 있다. 기준선(저PER 등)도 같은 적격 집합 안에서 센다.
순위 = 영업이익 전년 대비(상한 · 기저 미미는 빼고) · C1 괴리(상한 증가율) · C2 자리(낮을수록) 의 후보 안 백분위 평균.

재료(캐시만 · 네트워크 없음)
  분기 숫자  .cache/druck/{code}.json(드러켄밀러.series v4) — 매출액 · 영업이익 · _전 · 영업이익_TTM · 주식수(지금 기준) · EPS · EPS_adj · 품질 · 기준일.
  알게 된 날  그 분기 원본 정기보고서 접수일(색인 — 드러켄밀러.filed_meta['filed']) — 없으면 druck 기준일. 값은 마지막으로 받은 원장(정정값일 수 있다 —
             기준일이 원본보다 45일 넘게 늦으면 flag 'late_amend').
  먼저 알려진 날  (있으면) 영업(잠정)실적 · 매출액또는손익구조변동 공시 접수일 — 분기 말 뒤 · 보고서 접수일 전의 가장 이른 날. 신호엔 안 쓰고 표시 · 나눠 보기만.
  시가총액   보정 종가(.cache/price, 그대로 — 시너지._adjusted 재보정 안 함) × 그때 알던 주식 수(자기 분기 역산 주식수 가운데 가까운 4개의 중앙값).
  거래대금   보정 종가 × 거래량(.cache/ohlcv, 원주 수) × 분할 배수(거래량이 뛴 날짜로 — split_days) — 보정 전 주가 × 원주 거래량과 같다.
이 파일은 순수 함수만 — 서버 · 도구 · 시험이 같이 쓴다.
"""
import bisect
import math
import statistics as st
from array import array

VERSION = 2

TH = {
    "op_yoy": 20.0,     # A1 — 최근 분기 영업이익 전년 대비 ≥ (%)
    "rev_yoy": 5.0,     # A1 — 최근 분기 매출 전년 대비 ≥ (%)
    "cap": 200.0,       # 전년 대비 상한(순위 · 흑자 전환 값)
    "hist_min": 12,     # B 과거 4분기 합 개수 · C2 과거 POR 개수 최소
    "c1": 30.0,         # C1 괴리 ≥ (%p)
    "c2": 30.0,         # C2 자기 과거 POR 가운데 자리 ≤ (%)
    "por_win": 20,      # C2 과거 POR 창(분기)
    "tv": 1e9,          # 20거래일 평균 거래대금 ≥ (원)
}
TH_NAME = {"op_yoy": "영업이익 전년 대비", "rev_yoy": "매출 전년 대비", "cap": "전년 대비 상한", "hist_min": "과거 이력 최소 개수",
           "c1": "C1 괴리", "c2": "C2 자리", "por_win": "POR 창(분기)", "tv": "거래대금"}
POR_WINS = (10, 20, 30)     # 민감도 — C2 창 ×0.5 · ×1.5 를 한 번에 재 둔다
STALE = 10                   # 일 — 종가 · 봉이 이만큼 오래됐으면 없는 것으로(거래정지 · 상장 전)
STALE_FIN = 150              # 일 — 최근 보고서가 이보다 오래됐으면 묵은 재무(3분기 11-14 → 사업보고서 3-31 의 137일을 덮는다)
TINY = 0.01                  # 기저(영업이익_전) 가 매출의 이 비율 미만이면 전년 대비 무의미 · 흑자 전환인데 영업이익이 매출의 이 비율 미만이면 미미
SH_MIN_NI = 0.005            # 역산 주식 수를 믿는 최소 |지배순이익| ÷ 매출
SH_WOBBLE = 1.25             # 가까운 4개 주식수 max ÷ min 이 이보다 크면 '주식 수 흔들림'
LAG_AMEND = 45               # 일 — 기준일(정정 포함) − 원본 접수일 > 이면 '늦은 정정'
TV_DAYS = 20
TV_MIN_BARS = 15             # 20거래일 창에 거래량 > 0 봉이 이보다 적으면 거래대금 없음(정지)
OPM_TOP = 90                 # 이익률 고점 꼬리표 — 4분기 합 영업이익률이 자기 과거 20개 가운데 이 백분위 이상


# ---------------------------------------------------------------- 날짜
def shift(d, days):
    import datetime as dt
    return (dt.datetime.strptime(str(d)[:8], "%Y%m%d") + dt.timedelta(days=days)).strftime("%Y%m%d")


def days_between(a, b):
    import datetime as dt
    return (dt.datetime.strptime(str(b)[:8], "%Y%m%d") - dt.datetime.strptime(str(a)[:8], "%Y%m%d")).days


def year_ago(d):
    """1년 전 같은 날(달력) — 365일 빼기는 윤년에 하루 어긋난다(2024-12-31 − 365 = 2024-01-01). 2월 29일은 28일로."""
    s = str(d)[:8]
    y, md = int(s[:4]) - 1, s[4:]
    if md == "0229":
        md = "0228"
    return "%04d%s" % (y, md)


def qend(n):
    """분기 키 n(연도×4 + 분기−1) → 분기 말 YYYYMMDD."""
    return "%d%s" % (n // 4, {0: "0331", 1: "0630", 2: "0930", 3: "1231"}[n % 4])


# ---------------------------------------------------------------- 주가 세계 — {code: {YYYYMMDD: 종가}} 위의 작은 함수들
class Prices:
    """보정 종가(.cache/price 그대로) → at(code, d) · next_day · ret · 전 종목 중앙값(캐시). 도구와 서버가 같이 쓴다."""

    def __init__(self, data):
        self.ks, self.vs = {}, {}
        for code, s in (data or {}).items():
            if s:
                ks = sorted(s)
                self.ks[code], self.vs[code] = ks, [s[k] for k in ks]
        self._gr = {}

    def codes(self):
        return list(self.ks)

    def last_date(self, code):
        ks = self.ks.get(code)
        return ks[-1] if ks else None

    def at(self, code, d, stale=STALE):
        """d 에 또는 그 전 마지막 종가(stale 일 안) — (종가, 날짜) · 없으면 (None, None)."""
        ks = self.ks.get(code)
        if not ks:
            return None, None
        i = bisect.bisect_right(ks, str(d)) - 1
        if i < 0 or days_between(ks[i], d) > stale:
            return None, None
        return self.vs[code][i], ks[i]

    def next_day(self, code, d):
        """d 뒤 첫 거래일 — d 에 살아 있는 종가가 없으면 None(상장 전 · 거래정지)."""
        ks = self.ks.get(code)
        if not ks:
            return None
        j = bisect.bisect_right(ks, str(d))
        if j == 0 or j >= len(ks) or days_between(ks[j - 1], d) > STALE:
            return None
        return ks[j]

    def ret(self, code, d0, d1):
        a, _ = self.at(code, d0)
        b, _ = self.at(code, d1)
        return (b / a - 1) * 100 if (a and b) else None

    def grp_ret(self, d0, d1, codes=None):
        """같은 기간 전 종목 수익률 중앙값(5곳↑) — 초과수익의 기준."""
        key = (d0, d1)
        if key in self._gr:
            return self._gr[key]
        rs = [r for c in (codes or self.ks) for r in [self.ret(c, d0, d1)] if r is not None]
        v = st.median(rs) if len(rs) >= 5 else None
        self._gr[key] = v
        return v


# ---------------------------------------------------------------- 분할 날짜 — 거래량이 뛴 날
def split_days(series, rows, events=None):
    """자기 분기 분할 배수 k(EPS ÷ EPS_adj)가 연속 자기 분기 사이에서 1.2배 넘게(0.83배 아래로) 바뀌면 분할 · 병합 사건 후보.
    events(공시 날짜들 — 주식분할 · 무상증자 · 주식병합 · 감자 결정, 공시목록)가 주어지면 [앞 분기 말 − 120일, 뒤 분기 말 + 60일] 안에 공시가 있어야 사건이고
    날짜 탐색은 그 공시일부터; 없으면(None) 거래량만으로. 날짜는 ohlcv 거래량으로: R(d) = (d 부터 10개 비영 봉 거래량 중앙) ÷ (d 앞 10개 비영 봉 중앙) 이
    배수 r 에 로그로 가장 가까운 날. R 이 r^0.4 를 못 넘으면(병합은 거꾸로) 공시가 있을 때만 공시일 + 30일로 두고 est=True, 공시가 없으면 잡음으로 버린다.
    한 분기만 튀고 돌아오는 배수는 사건이 아니다(다음 자기 분기에도 새 수준이 이어져야).
    돌려주는 것 [{a, b, r, day, R, est}] (날짜 오름차순). 거래대금 배수 factor(d) = Π r (d < day)."""
    own = [p for p in series if p.get("k")]
    out = []
    if not own or not rows:
        return out
    ds = sorted(rows)
    vols = [(rows[d][4] if len(rows[d]) > 4 else 0) or 0 for d in ds]
    ev = sorted(events) if events is not None else None          # [] = 공시 목록은 있는데 이 회사엔 사건 공시가 없다(배수 변화는 잡음) · None = 목록 자체가 없다
    for i, (a, b) in enumerate(zip(own, own[1:])):
        r = a["k"] / b["k"]
        if 0.83 <= r <= 1.2:
            continue
        # 한 분기만 튀고 돌아오는 배수(엘에스일렉트릭 2014Q1 ¼배 → 다음 분기 ×4)는 역산 주식수 잡음 — 앞 수준이 앞 자기 분기에서, 새 수준이 다음 자기 분기에서 이어져야 사건
        prv = own[i - 1] if i >= 1 else None
        nxt = own[i + 2] if i + 2 < len(own) else None
        if prv is not None and not (0.83 <= prv["k"] / a["k"] <= 1.2):
            continue
        if nxt is not None and not (0.83 <= b["k"] / nxt["k"] <= 1.2):
            continue
        lo, hi = shift(qend(a["n"]), -90), shift(qend(b["n"]), 45)
        evd = None
        if ev is not None:
            j = bisect.bisect_left(ev, shift(qend(a["n"]), -120))
            if j >= len(ev) or ev[j] > shift(qend(b["n"]), 60):
                continue                                   # 공시 없는 배수 변화 — 역산 주식수 잡음
            evd = ev[j]
            lo, hi = evd, shift(evd, 150)
        i0, i1 = bisect.bisect_left(ds, lo), bisect.bisect_right(ds, hi)
        best, bestR = None, None
        thr = r ** 0.4
        for i in range(max(i0, 1), i1):
            before = [v for v in vols[max(0, i - 40):i] if v > 0][-10:]
            after = [v for v in vols[i:i + 40] if v > 0][:10]
            if len(before) < 5 or len(after) < 5 or vols[i] <= 0:
                continue
            R = st.median(after) / st.median(before)
            day_r = vols[i] / st.median(before)                    # 그날 자체 거래량도 뛰어야(병합은 꺼져야) — 뛰기 며칠 앞 날이 같은 R 로 잡히지 않게
            if R <= 0 or not ((r > 1 and day_r >= thr) or (r < 1 and day_r <= thr)):
                continue
            if best is None or abs(math.log(R) - math.log(r)) < abs(math.log(bestR) - math.log(r)):
                best, bestR = i, R
        ok = best is not None and ((r > 1 and bestR >= r ** 0.4) or (r < 1 and bestR <= r ** 0.4))      # 거래량 비가 배수의 0.4제곱은 넘어야 '그날'
        if ok:
            out.append({"a": a["label"], "b": b["label"], "r": r, "day": ds[best], "R": bestR, "est": False, "ev": evd})
        elif evd:
            out.append({"a": a["label"], "b": b["label"], "r": r, "day": shift(evd, 30), "R": bestR, "est": True, "ev": evd})
    out.sort(key=lambda x: x["day"])
    return out


def split_factor(splits, d):
    f = 1.0
    for x in splits or []:
        if str(d) < x["day"]:
            f *= x["r"]
    return f


# ---------------------------------------------------------------- 거래대금 — 시장 달력 20거래일 평균
class Turnover:
    """ohlcv {code: {YYYYMMDD: [시,고,저,종,거래량]}} + 분할 사건 {code: splits} → tv(code, d)(원).
    시장 달력 = 모든 종목 봉 날짜의 합집합. 봉이 없는 날은 거래대금 0 — 정지 종목은 창 평균이 떨어진다.
    마지막 봉이 d 보다 STALE 일 넘게 오래됐거나 창에 거래량 > 0 봉이 TV_MIN_BARS 미만이면 None."""

    def __init__(self, data, splits=None, calendar=None):
        cal = sorted(calendar) if calendar else sorted({d for rows in (data or {}).values() for d in (rows or ())})
        self.cal = cal
        idx = {d: i for i, d in enumerate(cal)}
        self.pre, self.nz, self.present = {}, {}, {}
        n = len(cal)
        for code, rows in (data or {}).items():
            if not rows:
                continue
            sp = (splits or {}).get(code) or []
            val, nz, pres = array("d", [0.0]) * (n + 1), array("i", [0]) * (n + 1), []
            s, c = 0.0, 0
            per = {}
            for d, r in rows.items():
                i = idx.get(d)
                if i is None:
                    continue
                cl, v = (r[3] if len(r) > 3 else None), (r[4] if len(r) > 4 else None)
                per[i] = ((cl * v * split_factor(sp, d)) if (cl and v) else 0.0, 1 if (v and v > 0) else 0)
            for i in range(n):
                x = per.get(i)
                if x:
                    s += x[0]
                    c += x[1]
                    pres.append(i)
                val[i + 1], nz[i + 1] = s, c
            self.pre[code], self.nz[code], self.present[code] = val, nz, pres

    def last_bar(self, code, d):
        """d 이하 마지막 봉 날짜."""
        pres = self.present.get(code)
        if not pres:
            return None
        i = bisect.bisect_right(self.cal, str(d)) - 1
        j = bisect.bisect_right(pres, i) - 1
        return self.cal[pres[j]] if j >= 0 else None

    def tv(self, code, d, days=TV_DAYS, stale=STALE):
        """창은 그 종목의 마지막 봉(≤ d)에서 끝난다 — 봉 자료가 며칠 늦게 받아졌을 때(ohlcv 가 price 보다 늦다) 없는 날을 0 으로 세지 않게.
        마지막 봉이 d 보다 stale 일 넘게 오래됐으면 None(정지 · 상장폐지 · 묵은 자료)."""
        pre = self.pre.get(code)
        if pre is None:
            return None
        pres = self.present.get(code) or []
        i = bisect.bisect_right(self.cal, str(d)) - 1
        j = bisect.bisect_right(pres, i) - 1
        if j < 0:
            return None
        i = pres[j]
        if i < days - 1 or days_between(self.cal[i], d) > stale:
            return None
        if self.nz[code][i + 1] - self.nz[code][i + 1 - days] < TV_MIN_BARS:
            return None
        return (pre[i + 1] - pre[i + 1 - days]) / days

    def last_date(self, code):
        pres = self.present.get(code)
        return self.cal[pres[-1]] if pres else None


# ---------------------------------------------------------------- 분기 시리즈
def series_of(druck, filed=None, first=None, strict=True):
    """druck 캐시 → 분기 줄(원장 있는 분기만, n 오름차순).
    filed0 = 알린 날(원본 정기보고서 접수일 filed[n], 없으면 기준일) · known = 값을 아는 날 — strict 면 druck 기준일(정정 접수일 포함 — 시리즈 값은 마지막 원장이라
    정정 뒤에야 그 값을 안다), 아니면 filed0(원본 날에 정정값을 안 것으로 — 느슨, 민감도용) · known_ttm = 4분기 합을 아는 날(창 네 분기 known 의 최대, 창이 비면 None) ·
    first = 먼저 알려진 날(잠정실적 등, 없으면 filed0) · valid = 품질에 gap · basis · cut 없음 · k = 분할 배수(자기 분기만) ·
    sh4 = 믿을 만한 역산 주식수(자기 분기 · 제외 아님 · unit/cut 없음 · |순이익| ≥ 매출 0.5%) 가까운 4개 중앙값 · late = 기준일이 원본보다 45일 넘게 늦음."""
    pts = [p for p in (druck or {}).get("points") or [] if p.get("fs") and p.get("n") is not None]
    pts.sort(key=lambda p: p["n"])
    out, win = [], []
    for p in pts:
        n = p["n"]
        base = str(p.get("기준일")) if p.get("기준일") else None
        f0 = (filed or {}).get(n) or (filed or {}).get(str(n)) or base
        filed0 = str(f0) if f0 else None
        known = (base or filed0) if strict else (filed0 or base)
        q = list(p.get("품질") or [])
        e, ea, ni, rev, sh = p.get("EPS"), p.get("EPS_adj"), p.get("지배순이익"), p.get("매출액"), p.get("주식수")
        sh_ok = bool(sh) and not p.get("주식수_제외") and not ({"unit", "cut"} & set(q)) and \
            (ni is not None) and (not rev or rev <= 0 or abs(ni) >= SH_MIN_NI * rev)
        k = (e / ea) if (sh_ok and e and ea and e * ea > 0) else None
        fk = (first or {}).get(n) or (first or {}).get(str(n))
        fk = str(fk) if fk else None
        if fk and filed0 and not (qend(n) < fk < filed0):
            fk = None
        s = {"n": n, "label": p.get("label") or "%dQ%d" % (n // 4, n % 4 + 1), "known": known, "filed0": filed0, "base": base, "first": fk or filed0,
             "late": bool(filed0 and base and days_between(filed0, base) > LAG_AMEND),
             "valid": not ({"gap", "basis", "cut"} & set(q)), "q": q,
             "rev": rev, "rev_p": p.get("매출액_전"), "op": p.get("영업이익"), "op_p": p.get("영업이익_전"), "ni": ni,
             "ttm": p.get("영업이익_TTM"), "rev_ttm": p.get("매출_TTM"), "eps_ttm": p.get("EPS_TTM"), "sh": sh, "sh_ok": sh_ok, "k": k,
             "opm_bad": bool(p.get("이익률_비정상")), "px_known": p.get("주가")}
        s["ttm_ok"] = s["ttm"] is not None and not ({"gap", "basis"} & set(q))
        s["opm"] = (s["ttm"] / s["rev_ttm"] * 100) if (s["ttm"] is not None and s["rev_ttm"]) else None
        if sh_ok:
            win.append(sh)
            win = win[-4:]
        s["sh4"] = st.median(win) if win else None
        s["sh_wobble"] = bool(win) and (max(win) / min(win) > SH_WOBBLE)
        out.append(s)
    for a, b in zip(out, out[1:]):
        b["sh_up"] = bool(a["sh4"] and b["sh4"] and b["sh4"] / a["sh4"] >= 1.10)
    if out:
        out[0]["sh_up"] = False
    by = {s["n"]: s for s in out}
    for s in out:
        w = [by.get(m) for m in range(s["n"] - 3, s["n"] + 1)]
        ks = [x["known"] for x in w if x] if all(w) else []
        s["known_ttm"] = max(ks) if (ks and all(ks)) else None
    return out


def is_holding(series):
    """순수 지주 — 마지막 4개 자료 분기 가운데 영업이익 > 0 이고 영업이익 > 매출액 인 분기가 하나라도(지분법 이익이 영업이익에 든다)."""
    for s in series[-4:]:
        if s["op"] is not None and s["op"] > 0 and s["rev"] is not None and s["op"] > s["rev"]:
            return True
    return False


def k_at(series, d):
    """d 가 속한 분기의 분할 배수(그 분기 EPS 기준) — 거래량 날짜 탐색(split_days)이 없을 때의 거친 대안."""
    if not series:
        return 1.0
    y, m = int(str(d)[:4]), int(str(d)[4:6])
    n = y * 4 + (m - 1) // 3
    best = None
    for s in series:
        if s["k"] is None:
            continue
        if s["n"] <= n:
            best = s["k"]
        elif best is None:
            best = s["k"]
            break
    return best or 1.0


def known_until(series, d):
    """알게 된 날 ≤ d 인 분기들(n 오름차순)."""
    return [s for s in series if s["known"] and s["known"] <= str(d)]


def shares_at(series, d):
    """d 까지 알게 된 마지막 분기의 sh4(가까운 4개 믿을 만한 역산 주식수의 중앙값) — (주식수, 그 분기)."""
    for s in reversed(known_until(series, d)):
        if s["sh4"]:
            return s["sh4"], s
    return None, None


def _yoy(v, p):
    """전년 대비 % — 기저 > 0 일 때만. (값, 흑자 전환 여부)."""
    if v is None or p is None:
        return None, False
    if p > 0:
        return (v - p) / p * 100, False
    if p < 0 and v > 0:
        return None, True
    return None, False


def _pct(hist, now):
    """자리 — (지금보다 작은 과거 값 수 + 같은 값 × ½) ÷ 과거 값 수 × 100."""
    if now is None or not hist:
        return None
    return (sum(1 for v in hist if v < now) + 0.5 * sum(1 for v in hist if v == now)) / len(hist) * 100


# ---------------------------------------------------------------- 한 회사 · 한 날의 숫자들(문턱 적용 전)
def metrics(series, d, px_fn, tv=None, th=TH, fin=False, hold=None):
    """s−1 = d 기준. px_fn(d) → 보정 종가(없으면 None). tv = 20거래일 평균 거래대금(원) 또는 None. fin = 금융(매출 개념 없음) · hold = 순수 지주(None 이면 자료로 판정).
    돌려주는 것: 문턱을 적용하기 전 숫자 + 적격(elig) · 그 까닭(why_not) · 꼬리표(flags). 알게 된 분기가 없으면 None."""
    K = known_until(series, d)
    if not K:
        return None
    d = str(d)
    last = K[-1]
    by = {s["n"]: s for s in K}
    flags, why_not = [], []
    if hold is None:
        hold = is_holding(K)
    if days_between(last["known"], d) > STALE_FIN:
        flags.append("stale")
        why_not.append("묵은 재무")
    if not last["valid"]:
        flags.append("q_invalid")
        why_not.append("분기 자료 어긋남")
    if fin:
        flags.append("fin")
        why_not.append("금융")
    if hold:
        flags.append("holding")
        why_not.append("지주")
    if last["late"]:
        flags.append("late_amend")
    for t in ("amended", "asfiled", "mix"):
        if t in last["q"]:
            flags.append("q_" + t)
    # A — 최근 분기 전년 대비(공시 당시 비교값, 없으면 시리즈 4분기 앞)
    prev4 = by.get(last["n"] - 4)
    op_p, rev_p, src = last["op_p"], last["rev_p"], "_전"
    if op_p is None and prev4:
        op_p, src = prev4["op"], "n−4"
        flags.append("yoy_series")
    if rev_p is None and prev4:
        rev_p = prev4["rev"]
        if "yoy_series" not in flags:
            flags.append("yoy_series")
    op_yoy, turn = _yoy(last["op"], op_p)
    rev_yoy, _ = _yoy(last["rev"], rev_p)
    tiny = op_p is not None and rev_p and rev_p > 0 and 0 < op_p < TINY * rev_p
    if tiny:
        flags.append("tiny_base")
    thin = turn and last["rev"] and last["rev"] > 0 and last["op"] < TINY * last["rev"]
    if thin:
        flags.append("thin_profit")
    no_rev = last["rev"] is None and rev_p is None
    if no_rev:
        flags.append("no_rev")
    # B — 4분기 합 신고점(온전한 창 · 창 네 분기를 다 아는 날 ≤ d 만)
    tok = lambda s: s["ttm_ok"] and s.get("known_ttm") and s["known_ttm"] <= d       # noqa: E731
    ttm = last["ttm"] if tok(last) else None
    if last["ttm"] is not None and not tok(last):
        flags.append("ttm_unknown")
    prior = [s["ttm"] for s in K if s["n"] < last["n"] and tok(s)]
    ttm_max = max(prior) if prior else None
    # C1 — 4분기 합 증가율 − 시가총액 증가율
    cap = th["cap"]
    ttm_prev = prev4["ttm"] if (prev4 and tok(prev4)) else None
    ttm_g, ttm_turn = None, False
    if ttm is not None and ttm_prev is not None:
        if ttm_prev > 0:
            ttm_g = (ttm / ttm_prev - 1) * 100
            if prev4["rev_ttm"] and ttm_prev < TINY * prev4["rev_ttm"]:
                flags.append("tiny_ttm_base")
        elif ttm > 0:
            ttm_g, ttm_turn = cap, True
            flags.append("ttm_turn")
    sh, shp = shares_at(series, d)
    px_now = px_fn(d)
    mcap = px_now * sh if (px_now and sh) else None
    d1y = year_ago(d)
    sh1, _ = shares_at(series, d1y)
    px1 = px_fn(d1y)
    mcap1 = px1 * sh1 if (px1 and sh1) else None
    mcap_g = (mcap / mcap1 - 1) * 100 if (mcap and mcap1) else None
    px_g = (px_now / px1 - 1) * 100 if (px_now and px1) else None
    gap = ttm_g - mcap_g if (ttm_g is not None and mcap_g is not None) else None
    gap_rank = min(ttm_g, cap) - mcap_g if gap is not None else None
    if shp and shp.get("sh_wobble"):
        flags.append("sh_wobble")
    if sh and sh1 and sh / sh1 >= 1.10:
        flags.append("sh_up")
    # C2 — 지금 POR 의 자기 과거 자리(창 10 · 20 · 30 을 한 번에)
    por = mcap / ttm if (mcap and ttm and ttm > 0) else None
    hist = []
    for s in K:
        if s["n"] >= last["n"] or not tok(s) or s["ttm"] <= 0 or not s["sh4"] or "cut" in s["q"]:
            continue
        p_ = px_fn(s["filed0"] or s["known"])                   # 그 분기가 알려진 날(원본 접수일)의 종가 — 그때 시장이 매긴 값
        if p_:
            hist.append((s["n"], p_ * s["sh4"] / s["ttm"]))
    hist.sort()
    pcts, nh = {}, {}
    for w in POR_WINS:
        hv = [v for _, v in hist[-w:]]
        nh[w] = len(hv)
        pcts[w] = _pct(hv, por)
    # 이익률 고점 꼬리표 — 4분기 합 영업이익률이 자기 과거 20개 가운데 상위 10% 이고, 매출 합 증가율이 이익 합 증가율의 절반에 못 미친다
    opm_hist = [s["opm"] for s in K if s["n"] < last["n"] and s["opm"] is not None][-20:]
    rev_ttm_g = None
    if last["rev_ttm"] and prev4 and prev4["rev_ttm"] and prev4["rev_ttm"] > 0:
        rev_ttm_g = (last["rev_ttm"] / prev4["rev_ttm"] - 1) * 100
    opm_peak = (last["opm"] is not None and len(opm_hist) >= 12 and _pct(opm_hist, last["opm"]) >= OPM_TOP
                and ttm_g is not None and rev_ttm_g is not None and rev_ttm_g < ttm_g / 2)
    if opm_peak:
        flags.append("opm_peak")
    if last["opm_bad"]:
        flags.append("opm_bad")
    # 저PER 기준선용 · 먼저 알려진 날
    eps_ttm = last["eps_ttm"] if tok(last) else None
    per = (px_now / eps_ttm) if (px_now and eps_ttm and eps_ttm > 0) else None
    first = last["first"] if (last["first"] and last["filed0"] and last["first"] < last["filed0"]) else None
    px_first = px_fn(first) if first else None
    px_since_first = (px_now / px_first - 1) * 100 if (px_now and px_first) else None
    if first:
        flags.append("prelim")
    # 적격
    if mcap is None:
        why_not.append("주식 수 없음")
    elif mcap1 is None:
        why_not.append("1년 전 시가총액 없음")
    if len(prior) < th["hist_min"]:
        why_not.append("이력 %d분기 미만" % th["hist_min"])
    if tv is None:
        why_not.append("거래 자료 없음")
    elig = not why_not
    return {"n": last["n"], "label": last["label"], "known": last["known"], "filed0": last["filed0"], "first": first, "px_since_first": px_since_first, "d": d,
            "op": last["op"], "op_p": op_p, "rev": last["rev"], "rev_p": rev_p, "yoy_src": src, "op_yoy": op_yoy, "rev_yoy": rev_yoy,
            "turn": bool(turn), "tiny": bool(tiny), "thin": bool(thin), "no_rev": bool(no_rev),
            "ttm": ttm, "ttm_max": ttm_max, "n_hist": len(prior), "ttm_prev": ttm_prev, "ttm_g": ttm_g, "ttm_turn": ttm_turn,
            "rev_ttm": last["rev_ttm"], "rev_ttm_g": rev_ttm_g, "opm": last["opm"],
            "px": px_now, "px_1y": px1, "sh": sh, "sh_1y": sh1, "sh_label": shp["label"] if shp else None, "mcap": mcap, "mcap_1y": mcap1,
            "mcap_g": mcap_g, "px_g": px_g, "gap": gap, "gap_rank": gap_rank, "por": por, "por_pct": pcts, "por_n": nh,
            "por_hist": [(n_, round(v, 3)) for n_, v in hist[-max(POR_WINS):]],
            "tv": tv, "eps_ttm": eps_ttm, "per": per, "fin": bool(fin), "hold": bool(hold), "elig": elig, "why_not": why_not, "flags": flags}


def judge(m, th=TH, opts=None):
    """숫자 → 판정 {A1, A2, A, B, C1, C2, L, elig, cand, why, pct, pct_n}. 문턱은 th. 숫자가 없으면 그 조건은 False.
    opts: cap_c1 = C1 통과 판정에도 상한 증가율을 쓴다 · no_tiny = 기저 미미 · 미미한 흑자 규칙을 끈다 · no_elig = 적격을 보지 않는다 (민감도용)."""
    if not m:
        return None
    o = opts or {}
    tiny, thin = (False, False) if o.get("no_tiny") else (m["tiny"], m["thin"])
    rev_ok = (m["rev_yoy"] is not None and m["rev_yoy"] >= th["rev_yoy"]) or (m["no_rev"] and m["fin"])
    A1 = (not tiny) and m["op_yoy"] is not None and m["op_yoy"] >= th["op_yoy"] and rev_ok
    A2 = bool(m["turn"]) and not thin
    A = A1 or A2
    B = m["ttm"] is not None and m["ttm_max"] is not None and m["n_hist"] >= th["hist_min"] and m["ttm"] > m["ttm_max"]
    g = m["gap_rank"] if o.get("cap_c1") else m["gap"]
    C1 = g is not None and g >= th["c1"]
    w = int(th["por_win"])
    pct = (m["por_pct"] or {}).get(w)
    nh = (m["por_n"] or {}).get(w) or 0
    C2 = pct is not None and nh >= th["hist_min"] and pct <= th["c2"]
    L = m["tv"] is not None and m["tv"] >= th["tv"]
    elig = True if o.get("no_elig") else m["elig"]
    cand = elig and (A or B) and C1 and C2 and L
    why = []
    if A:
        why.append("흑자 전환" if (A2 and not A1) else "실적 개선")
    if B:
        why.append("실적 신고점")
    return {"A1": A1, "A2": A2, "A": A, "B": B, "C1": C1, "C2": C2, "L": L, "elig": elig, "cand": cand, "why": why, "pct": pct, "pct_n": nh}


def pct_rank(vals):
    """값들 → 백분위(0~100, 큰 값이 100 쪽). None 은 None. 동점은 평균 순위."""
    idx = [i for i, v in enumerate(vals) if v is not None]
    out = [None] * len(vals)
    if not idx:
        return out
    order = sorted(idx, key=lambda i: vals[i])
    n = len(order)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        r = (i + j) / 2.0
        for k in range(i, j + 1):
            out[order[k]] = (r / (n - 1) * 100) if n > 1 else 50.0
        i = j + 1
    return out


def rank_value_op(m, th=TH):
    """순위용 영업이익 전년 대비 — 흑자 전환(A2)은 상한값, 기저 미미는 없음, 나머지는 상한으로 자른 값."""
    if m["turn"] and not m["thin"]:
        return th["cap"]
    if m["tiny"] or m["op_yoy"] is None:
        return None
    return min(m["op_yoy"], th["cap"])


def rank(rows, th=TH):
    """같은 날 후보들 → score(0~100) · 순위. rows[i] = {"m": metrics, "j": judge}. 영업이익 전년 대비(상한) · C1 은 gap_rank · C2 는 100 − 자리.
    셋 가운데 있는 것의 평균(없는 항목은 뺀다 — 기저 미미 · 4분기 합 흑자 전환은 그 성분이 없다)."""
    a = [rank_value_op(r["m"], th) for r in rows]
    # C1 성분 — 4분기 합 기저가 0 이하(흑자 전환)거나 매출 합의 1% 미만이면 증가율이 뜻이 없어 성분에서 뺀다(통과 판정은 사용자 스펙대로)
    b = [None if (r["m"].get("ttm_turn") or "tiny_ttm_base" in (r["m"].get("flags") or [])) else r["m"]["gap_rank"] for r in rows]
    c = [(100 - r["j"]["pct"]) if r["j"].get("pct") is not None else None for r in rows]
    ra, rb, rc = pct_rank(a), pct_rank(b), pct_rank(c)
    for i, r in enumerate(rows):
        parts = [x for x in (ra[i], rb[i], rc[i]) if x is not None]
        r["score"] = round(sum(parts) / len(parts), 1) if parts else None
        r["parts"] = {"op_yoy": ra[i], "gap": rb[i], "por": rc[i]}
    order = sorted(range(len(rows)), key=lambda i: (-(rows[i]["score"] if rows[i]["score"] is not None else -1), i))
    for k, i in enumerate(order, 1):
        rows[i]["rank"] = k
    return rows


GENERIC_THEME = ("밸류업", "지주사", "대표주", "S7(", "코리아 밸류업", "MSCI", "KOSPI", "KRX ", "우선주", "고배당")   # 돈의 흐름을 말하지 않는 꼬리표 — 테마 칩에서 뺀다


def flow_groups(rows, th=TH, kinds=("sector", "industry", "themes"), min_show=1, skip=GENERIC_THEME):
    """돈의 흐름 — 적격 회사를 섹터 · 업종 · 테마로 묶어 후보(실적↑인데 아직 싸다) · 이미 오름(실적↑인데 1년 시총이 C1 문턱 넘게 올랐다) · 시총 1년 변화 중앙을 센다.
    rows = [{code, sector, industry, themes[], elig, cand, earn(A 또는 B), mcap_g}]. 돌려주는 것 {kind: [{name, n_elig, n_cand, n_ran, mcap_g_med, cand_codes, ran_codes}]} —
    후보 많은 순 · 같으면 이미 오름 많은 순. min_show: 후보도 이미 오름도 이보다 적은 묶음은 뺀다(테마 264개가 다 나오지 않게)."""
    out = {}
    for kind in kinds:
        agg = {}
        for r in rows:
            if not r.get("elig"):
                continue
            names = r.get(kind) if kind == "themes" else [r.get(kind)]
            for nm in names or []:
                if not nm or (kind == "themes" and any(x in nm for x in (skip or ()))):
                    continue
                g = agg.setdefault(nm, {"name": nm, "n_elig": 0, "n_cand": 0, "n_ran": 0, "mg": [], "cand_codes": [], "ran_codes": []})
                g["n_elig"] += 1
                if r.get("mcap_g") is not None:
                    g["mg"].append(r["mcap_g"])
                if r.get("cand"):
                    g["n_cand"] += 1
                    g["cand_codes"].append(r["code"])
                elif r.get("earn") and r.get("mcap_g") is not None and r["mcap_g"] >= th["c1"]:
                    g["n_ran"] += 1
                    g["ran_codes"].append(r["code"])
        lst = []
        for g in agg.values():
            if g["n_cand"] < min_show and g["n_ran"] < min_show:
                continue
            g["mcap_g_med"] = st.median(g.pop("mg")) if g["mg"] else None
            lst.append(g)
        lst.sort(key=lambda g: (-g["n_cand"], -g["n_ran"], -g["n_elig"], g["name"]))
        out[kind] = lst
    return out


def sens_variants(th=TH):
    """문턱마다 ×0.5 · ×1.5 하나씩 바꾼 변형 [(이름, th, opts)] — 기본값 먼저. 끝에 규칙 변형(문턱 아님) 셋."""
    out = [("기본", dict(th), {})]
    for k in ("op_yoy", "rev_yoy", "cap", "hist_min", "c1", "c2", "por_win", "tv"):
        for f in (0.5, 1.5):
            t = dict(th)
            v = th[k] * f
            if k in ("hist_min", "por_win"):
                v = int(round(v))
            t[k] = v
            out.append(("%s ×%.1f" % (TH_NAME[k], f), t, {}))
    out.append(("C1 통과에도 상한 증가율", dict(th), {"cap_c1": True}))
    out.append(("기저 1% 규칙 없이", dict(th), {"no_tiny": True}))
    out.append(("적격 조건 없이", dict(th), {"no_elig": True}))
    return out

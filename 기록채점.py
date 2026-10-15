# -*- coding: utf-8 -*-
"""
기록 채점 — 매일 남긴 판단 기록을 그 뒤 실제 주가로 잰다(백테스트가 아닌 진짜 표본 밖 성적).

기록 두 가지:
  저평가 실전 기록  .cache/value/forward/YYYYMMDD.json — 아침 06:30, 장 열기 전에 price_d 까지의 종가로 고른 목록
  Tech 스캔 일지    Tech/output/journal.csv — asof 장 마감 뒤에 쓴 목록(읽기만 한다)
                    rule 칸이 빈 행(2026-10-14 Tech 패턴 초기화 전 옛 탐지기 기록 — 제거된 식)은 채점에서 뺀다
                    (2026-10-16 사용자 요청 — 원본 일지 파일에는 남아 있다).

규칙(저장소 백테스트와 같게):
  진입   기록 기준일 다음 거래일 종가. 거래일 = 그 종목 자기 주가 날짜.
         실전 기록 파일이 기준일보다 늦게 쓰였으면(섞인 날) 진입은 파일 쓴 날 이후로 — 미리 본 값을 막는다.
  수익률 진입 뒤 h 거래일 종가 / 진입 − 1. 아직 h 거래일이 안 지났으면 None(채점 전).
  지금   마지막 종가 / 진입 − 1, 진입 뒤 1거래일 이상 지난 것만.
  초과   같은 기간(진입일 종가 → 같은 끝날 종가) 벤치마크 종목들 수익률 중앙값을 뺀 값.
  손절   Tech 기록 중 손절가가 있는 것 — 진입 뒤 60거래일 안에서 종가가 손절가 이하로 먼저 닫혔나,
         진입 × 1.20 이상으로 먼저 닫혔나(종가 기준). 지금 식 기록은 손절가 없는 기록이 하나라도 섞인 묶음의 비율을
         내지 않는다(exit_note) — 섞어 내면 손절가 있는 몇 건의 비율이 묶음 전체 비율로 보인다. 손절가가 없는 까닭은
         그 묶음에 실제로 든 패턴으로 적는다(NO_STOP_RULE: 식 · 기법에 손절 규칙 없음 / STOP_AFTER_ENTRY: 돌파 · 신호 전
         기록이라 손절이 아직 없음). 빗각 추세선 돌파 기록의 손절은 기록 날 다음 봉 선 값으로 고정해 잰다 — 기법 규칙
         (그날 선 아래 종가, 선은 날마다 내려감)보다 이르게 걸리고, '형성 중'(거래량 미달 관찰) · 안착 확인 대기 기록도
         섞여 매매로 잰 값이 아니다(TL_STOP_CAVEAT).
         옛 기록은 예전처럼 손절가 있는 것만 세고 뺀 건수를 적는다.

주가는 밖에서 넣어 준다(Prices(load)) — 이 모듈은 주가 파일을 직접 읽지 않는다.
"""
import bisect
import csv
import datetime as dt
import json
import math
import os
import re
from collections import Counter

HORIZONS = (5, 20, 60, 120, 250)
STOP_BARS = 60        # 손절 · 목표를 보는 기간(거래일)
STALL_DAYS = 30       # 종목 주가가 전체 마지막 날보다 이만큼(달력) 앞에서 끊겼으면 거래 정지 · 상장폐지로 본다
TARGET = 0.20         # 목표 = 진입 × 1.20
BENCH_MIN = 20        # 벤치마크를 세우는 최소 종목 수
BENCH_BACK = 10       # 그날 종가가 없으면 달력으로 며칠 앞까지 쓴다

V_TIER, O_TIER = "저평가", "관찰"

VALUE_REF = {"label": "백테스트 기대(README)",
             "text": "저평가 묶음 12개월(250일) 초과 중앙 +3.3%, 이긴 비율 54%, −30% 이하 12%"}
# 2026-10-14 Tech 패턴 초기화: 옛 탐지기(VCP · 옛 컵 · CAN SLIM · 300억 눌림목 · 주도주 …)를 지우고 사용자 식 컵 앤 핸들
# (cwh_reference_v1.0.0)과 보컬(관찰)만 남겼다. 일지의 rule 칸이 빈 행 = 옛 탐지기 기록 — 채점 · 화면에서 뺀다(2026-10-16, 원본 일지는 그대로).
RESET_DAY = "2026-10-14"
# 결과 형식 판 — 서버가 캐시(.cache/score/_result.json)의 schema 가 이것과 다르면 옛 코드가 쓴 결과로 보고 보이지 않고 다시 잰다
# (2 = 패턴 초기화: tech / tech_legacy 분리 · 지금 식 손절 비율 규칙, 3 = 옛 탐지기 기록 묶음(tech_legacy) 뺌 2026-10-16,
# 4 = 칸마다 due(첫 숫자가 나오는 날) 2026-10-16). 형식을 바꾸면 올린다.
SCHEMA = 4
TECH_REF = {"label": "지금 식 백테스트",
            "text": "컵 앤 핸들(사용자 식): 백테스트 아직 없음 · 보컬(관찰용): 기업추적 보컬 백테스트(2013~2026 눌림목) "
                    "346거래 거래당 −2.4% · 승률 31% · 20일 초과 중앙 −4.8%p(손실) · 《차트의 기술》 기법 6개"
                    "(빗각 · 피보 · 빗각+피보 · 60일선 · 월봉 적삼병 · 10% 주도주): 검증 전 — 영상 사례 수익률 · 불코우스키 "
                    "미국 통계는 우리 성적이 아니다"}
BASIS = ("진입 = 기록 기준일 다음 거래일 종가(실전 기록은 파일 쓴 날보다 앞서지 않게) · "
         "수익률 = 진입 뒤 5/20/60/120/250 거래일 종가(분할 보정) · "
         "초과 = 같은 기간 벤치마크 종목 수익률 중앙값 대비 · "
         "손절/목표(+20%) = 60거래일 안 종가 기준 먼저 닿은 쪽 · 비용 전")

NOTES = [
    "표본이 작다 — 기록이 쌓이기 전 숫자는 운에 크게 흔들린다.",
    "거래 비용 · 세금 · 슬리피지를 빼기 전 수익률이다.",
    "겹치는 관측 — 같은 종목이 여러 날 목록에 있으면 날마다 한 번씩 센다(독립 표본이 아니다).",
    "진입 규칙이 Tech 추적(다음 날 시가)과 다르다 — 여기서는 다음 거래일 종가.",
    "벤치마크 = 주가 캐시가 있는 종목(지금 유니버스) 중앙값 — 상장폐지로 사라진 종목은 빠진다.",
    "주가가 30일 넘게 끊긴 종목(거래 정지 · 상장폐지)은 끊긴 날 종가로 끝난 것으로 센다 — 묶음마다 '끊김' 수를 적는다.",
]

PATTERN_KO = {"cup_with_handle": "컵 앤 핸들 (사용자 식)", "vocal": "보컬 (관찰용)", "": "패턴 없음",
              # 2026-10-14 《차트의 기술》 영상 기법 (Tech 일지 rule 칸: tlbrk_v1 · fibpb_v1 · tlfib_v1 · ma60s_v1 · red3m_v1 · dlead_v1)
              "trendline_break": "빗각 추세선 돌파", "fib_pullback": "피보나치 눌림 반등",
              "trendline_fib": "빗각 돌파 + 피보 눌림", "ma60_supply": "60일선 수급 돌파 (신호 · 손절 없음)",
              "red_three_monthly": "월봉 적삼병 (신호 · 손절 없음)", "day_leader": "10% 주도주 (단타 관찰)"}
# 식 · 기법에 손절 규칙이 없는 패턴 — 기록에 손절가가 없는 게 정상 (Tech scoring.NO_STOP_REASON · backtest.STOP_RULE None)
NO_STOP_RULE = ("cup_with_handle", "ma60_supply", "red_three_monthly", "day_leader")
# 손절 규칙은 있지만 손절가가 없는 단계가 있는 패턴 (빗각: 돌파 임박 · 실패 표시 / 피보: 고점 확정 뒤 대기)
STOP_AFTER_ENTRY = ("trendline_break", "fib_pullback", "trendline_fib")
# 빗각 추세선 돌파 기록 채점의 한계 — 손절 칸에 따라 붙는다
TL_STOP_CAVEAT = ("빗각 추세선 돌파 기록의 손절 = 기록 날 다음 봉 선 값 고정 — 기법 규칙(그날 선 아래 종가, 선은 날마다 내려감)보다 "
                  "이르게 걸림 · '형성 중'(거래량 미달 관찰) · 안착 확인 대기(매수 전) 기록도 섞여 매매로 잰 값 아님")
STAGE_KO = {"breakout": "돌파", "near_pivot": "피벗 근처", "forming": "만드는 중",
            "extended": "이격 과다", "failed": "실패", "": "단계 없음"}
STAGE_ORDER = ("breakout", "near_pivot", "forming", "extended", "failed", "")

J_TEXT = ("name", "market", "pattern", "stage", "rule")
J_NUM = ("pivot", "stop", "composite", "rs", "close", "value")


# ---------------------------------------------------------------- 작은 도구
def _num(x):
    """숫자로. 빈 값 · 글자 · NaN · 무한대는 None."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, str):
        x = x.strip()
        if not x:
            return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _d8(x):
    """날짜 → 'YYYYMMDD'. date · 'YYYY-MM-DD' · 'YYYYMMDD' 를 받는다."""
    if x is None:
        return None
    if isinstance(x, (dt.date, dt.datetime)):
        return x.strftime("%Y%m%d")
    s = str(x).strip().replace("-", "")
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        dt.datetime.strptime(s, "%Y%m%d")
    except ValueError:
        return None
    return s


_ORD = {}


def _ordinal(d):
    o = _ORD.get(d)
    if o is None:
        o = _ORD[d] = dt.date(int(d[:4]), int(d[4:6]), int(d[6:8])).toordinal()
    return o


def _shift(d, days):
    return (dt.date(int(d[:4]), int(d[4:6]), int(d[6:8])) + dt.timedelta(days=days)).strftime("%Y%m%d")


def _add_weekdays(d, k):
    """d 다음 k 번째 평일(YYYYMMDD) — 아직 안 온 거래일을 어림한다. 공휴일 달력은 모른다(주말만 건너뜀 — 공휴일이 끼면 하루씩 늦다)."""
    x = dt.date(int(d[:4]), int(d[4:6]), int(d[6:8]))
    while k > 0:
        x += dt.timedelta(days=1)
        if x.weekday() < 5:
            k -= 1
    return x.strftime("%Y%m%d")


def _code(x):
    """종목코드 — 엑셀이 앞자리 0 을 먹었으면 되살린다."""
    if x is None:
        return ""
    s = str(x).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s.zfill(6) if s.isdigit() else s


def _median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return None
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2.0


def _pct(x):
    return None if x is None else round(x * 100.0, 2)


# ---------------------------------------------------------------- 주가
def _adjusted(prices, ds):
    """액면분할·병합 보정(시너지._adjusted 그대로). 하루 ±30% 를 넘는 움직임은 주식 수가 바뀐 것 —
    그 앞의 가격을 비율만큼 고쳐 이어 붙인다. 상장 직후 5거래일은 건드리지 않는다."""
    adj = [prices[d] for d in ds]
    for i in range(len(ds) - 1, 5, -1):
        a, b = adj[i - 1], adj[i]
        if a and b and not (0.69 <= b / a <= 1.31):
            k = b / a
            for j in range(i):
                adj[j] *= k
    return adj


class Prices:
    """종목 → (날짜 목록, 분할 보정 종가 목록). load(code) -> {"YYYYMMDD": 종가} 또는 None.
    종목마다 한 번만 읽어 둔다. since 를 주면 보정한 뒤 그 날짜 앞은 버린다(32비트 메모리 아끼기)."""

    def __init__(self, load, since=None):
        self._load = load
        self.since = _d8(since)
        self._s = {}
        self._f = {}              # 종목 → 날짜별 보정 비율(보정 종가 / 원래 종가) — 손절가를 같은 기준으로
        self._dates = {}          # 같은 날짜 문자열을 종목마다 따로 들고 있지 않게
        self.last = None          # 읽은 주가 중 가장 늦은 날
        self.bench_memo = {}
        self.bench_univ = None

    def series(self, code):
        s = self._s.get(code)
        if s is not None:
            return s
        try:
            raw = self._load(code)
        except Exception:
            raw = None
        ds, cs = [], []
        if raw:
            clean = {}
            for k, v in raw.items():
                v = _num(v)
                d = _d8(k)
                if v is not None and v > 0 and d:
                    clean[d] = v
            ds = sorted(clean)
            cs = _adjusted(clean, ds)
            fs = [a / clean[d] for a, d in zip(cs, ds)]
            if self.since and ds:
                k = bisect.bisect_left(ds, self.since)
                ds, cs, fs = ds[k:], cs[k:], fs[k:]
            pool = self._dates
            ds = [pool.setdefault(d, d) for d in ds]
            if ds and (self.last is None or ds[-1] > self.last):
                self.last = ds[-1]
            self._f[code] = fs
        s = self._s[code] = (ds, cs)
        return s

    def factor(self, code, d):
        """d(같은 날 포함) 이전 마지막 거래일의 보정 비율 — 그 뒤 분할이 모두 반영된 값. 모르면 1."""
        ds, _ = self.series(code)
        fs = self._f.get(code) or []
        k = bisect.bisect_right(ds, d) - 1
        return fs[k] if 0 <= k < len(fs) else 1.0


def _at_or_before(ds, cs, d, od):
    """d 이전(같은 날 포함) 마지막 종가 — 달력으로 BENCH_BACK 일보다 오래됐으면 None."""
    i = bisect.bisect_right(ds, d) - 1
    if i < 0 or od - _ordinal(ds[i]) > BENCH_BACK:
        return None
    return cs[i]


def bench(prices, universe_codes, d0, d1):
    """벤치마크 = d0 종가 → d1 종가 유니버스 종목 수익률 중앙값(소수, 0.03 = +3%).
    두 날 모두 주가가 있는 종목이 BENCH_MIN 개 못 되면 None. (d0, d1) 마다 한 번만 센다 —
    같은 universe_codes 객체를 넘기는 동안 기억한다."""
    if prices.bench_univ is not universe_codes:
        prices.bench_univ = universe_codes
        prices.bench_memo = {}
    key = (d0, d1)
    memo = prices.bench_memo
    if key in memo:
        return memo[key]
    o0, o1 = _ordinal(d0), _ordinal(d1)
    rs = []
    for c in universe_codes:
        ds, cs = prices.series(c)
        if not ds:
            continue
        a = _at_or_before(ds, cs, d0, o0)
        if a is None:
            continue
        b = _at_or_before(ds, cs, d1, o1)
        if b is None:
            continue
        rs.append(b / a - 1.0)
    v = _median(rs) if len(rs) >= BENCH_MIN else None
    memo[key] = v
    return v


# ---------------------------------------------------------------- 한 기록 채점
def _evaluate(prices, univ, code, rdate, cutoff=None, not_before=None, stop=None, glast=None):
    """기록 하나 → {"entry_d", "h": {h: (ret, ex)}, "now": (ret, ex, days) | None, "exit", "exit_done", "stalled"}.
    주가가 아예 없으면 None. glast = 전체 마지막 거래일 — 이 종목 주가가 그보다 STALL_DAYS 넘게 앞에서 끊겼으면
    (거래 정지 · 상장폐지) 아직 안 온 기간을 마지막 종가로 끝난 것으로 채운다 — 망한 종목이 '아직 채점 전'으로
    숨지 않게."""
    ds, cs = prices.series(code)
    if not ds:
        return None
    n = len(ds) if cutoff is None else bisect.bisect_right(ds, cutoff)
    i = bisect.bisect_right(ds, rdate)
    if not_before:
        i = max(i, bisect.bisect_left(ds, not_before))
    out = {"entry_d": None, "h": {}, "now": None, "exit": None, "exit_done": False, "stalled": False, "due": {}}
    if i >= n:                           # 아직 진입 전 — 진입일(기록 다음 평일, 파일 쓴 날 이후)부터 어림한 '첫 숫자가 나오는 날'
        base = rdate if n == 0 else max(rdate, ds[n - 1])
        entry = _add_weekdays(base, 1)
        if not_before and entry < not_before:
            entry = not_before if dt.date(int(not_before[:4]), int(not_before[4:6]), int(not_before[6:8])).weekday() < 5 \
                else _add_weekdays(not_before, 1)
        out["due"] = {"now": _add_weekdays(entry, 1), **{str(h): _add_weekdays(entry, h) for h in HORIZONS}}
        return out
    e, d0 = cs[i], ds[i]
    out["entry_d"] = d0
    stalled = bool(glast) and n > 0 and _ordinal(glast) - _ordinal(ds[n - 1]) > STALL_DAYS
    out["stalled"] = stalled
    for h in HORIZONS:
        j = i + h
        if j < n:
            r = cs[j] / e - 1.0
            b = bench(prices, univ, d0, ds[j])
            out["h"][h] = (r, None if b is None else r - b)
        elif stalled and n - 1 > i:
            r = cs[n - 1] / e - 1.0                    # 끊긴 날 종가로 끝난 것으로
            b = bench(prices, univ, d0, ds[n - 1])
            out["h"][h] = (r, None if b is None else r - b)
    days = n - 1 - i
    if days >= 1:
        r = cs[n - 1] / e - 1.0
        b = bench(prices, univ, d0, ds[n - 1])
        out["now"] = (r, None if b is None else r - b, days)
    else:
        out["due"]["now"] = _add_weekdays(ds[n - 1], 1 - days)
    for h in HORIZONS:                   # 아직 안 지난 기간 — 이 종목 마지막 주가 날에서 모자란 거래일만큼 평일로 어림
        if h not in out["h"]:
            out["due"][str(h)] = _add_weekdays(ds[n - 1], h - days)
    if stop is not None and stop > 0:
        lvl = stop * prices.factor(code, rdate)   # 기록 날 기준 손절가를 보정 종가와 같은 기준으로
        tgt = e * (1.0 + TARGET)
        res = "open"
        for j in range(i + 1, min(n, i + 1 + STOP_BARS)):
            c = cs[j]
            if c <= lvl:
                res = "stop"
                break
            if c >= tgt:
                res = "target"
                break
        out["exit"] = res
        out["exit_done"] = res != "open" or days >= STOP_BARS
    return out


# ---------------------------------------------------------------- 묶음 통계
def _stats(items, n_all, with_days=False):
    """items: 다 지난 관측 [(ret, ex[, days])]. 숫자는 % 로 소수 둘째 자리(3.25 = +3.25%)."""
    n = len(items)
    st = {"n": n, "n_all": n_all, "mean": None, "median": None, "ex_median": None,
          "win": None, "worst": None, "n_ex": 0}
    if with_days:
        st["days_median"] = None
    if not n:
        return st
    rets = [t[0] for t in items]
    exs = [t[1] for t in items if t[1] is not None]
    st["mean"] = _pct(sum(rets) / n)
    st["median"] = _pct(_median(rets))
    st["worst"] = _pct(min(rets))
    st["n_ex"] = len(exs)
    if exs:
        st["ex_median"] = _pct(_median(exs))
        st["win"] = round(100.0 * sum(1 for x in exs if x > 0) / len(exs), 2)
    if with_days:
        st["days_median"] = round(float(_median([t[2] for t in items])), 1)
    return st


def _dedupe(obs):
    """같은 날 같은 종목은 한 번만."""
    seen, out = set(), []
    for o in obs:
        k = (o["date"], o["code"])
        if k not in seen:
            seen.add(k)
            out.append(o)
    return out


def _has_stop(row):
    s = (row or {}).get("stop")
    return isinstance(s, (int, float)) and s > 0


def _short_name(p):
    """패턴 이름 (괄호 설명 뺌) — 손절 메모에 늘어놓는 용."""
    return PATTERN_KO.get(p, p or "패턴 없음").split(" (")[0]


def _names(ps):
    return " · ".join(_short_name(p) for p in ps)


def _nostop_note(obs, n_all):
    """손절가 없는 기록이 섞인 지금 식 묶음의 메모 — 까닭을 묶음에 실제로 든 패턴으로 (하드코딩한 식 이름 아님)."""
    rows = [o.get("row") or {} for o in obs]
    nos = Counter((r.get("pattern") or "") for r in rows if not _has_stop(r))
    # 가리킬 줄: 이 묶음에서 손절가 있는 기록만 가진 패턴 (손절가 없는 기록도 섞인 패턴 줄은 그 자신도 비율이 없다)
    ns = Counter((r.get("pattern") or "") for r in rows if _has_stop(r))
    has = sorted((p for p in ns if p not in nos), key=lambda p: (-ns[p], p))
    order = sorted(nos, key=lambda p: (-nos[p], p))
    rule = [p for p in order if p in NO_STOP_RULE]
    pre = [p for p in order if p in STOP_AFTER_ENTRY]
    other = [p for p in order if p not in NO_STOP_RULE and p not in STOP_AFTER_ENTRY]
    why = []
    if rule:
        why.append(_names(rule) + ": 식 · 기법에 손절 규칙 없음")
    if pre:
        why.append(_names(pre) + ": 손절가 없는 단계(돌파 · 신호 전 · 실패 표시) 기록")
    if other:
        why.append(_names(other) + ": 손절가 없는 기록")
    nostop = sum(nos.values())
    if nostop == n_all:
        head = "손절 규칙 없음" if not pre and not other else ("손절가 없는 단계" if not rule and not other else "손절가 없음")
        return head + " — " + " / ".join(why)
    return ("손절가 없는 기록 %d건(%s)이 섞여 이 묶음 비율은 내지 않음" % (nostop, " / ".join(why))
            + (" — 손절가 있는 패턴 줄 참고 (%s)" % _names(has) if has else ""))


def _group(key, label, obs, with_exit=False, strict_exit=False):
    """strict_exit: 손절가 없는 기록이 하나라도 섞인 묶음은 손절 먼저 · +20% 먼저를 내지 않는다(지금 식 기록 —
    손절 규칙 없는 식 · 기법(컵 앤 핸들 사용자 식 · 60일선 · 월봉 적삼병 · 10% 주도주)이나 돌파 · 신호 전 기록이 섞이면
    손절가 있는 몇 건의 비율이 묶음 전체 비율로 보인다). 메모의 까닭은 _nostop_note 가 묶음의 패턴으로 적는다."""
    obs = _dedupe(obs)
    n_all = len(obs)
    evs = [o["ev"] for o in obs if o["ev"]]
    g = {"key": key, "label": label, "n_obs": n_all, "n_codes": len({o["code"] for o in obs}),
         "n_stalled": len({o["code"] for o in obs if o["ev"] and o["ev"].get("stalled")}),
         "now": _stats([e["now"] for e in evs if e["now"]], n_all, with_days=True),
         "h": {str(h): _stats([e["h"][h] for e in evs if h in e["h"]], n_all) for h in HORIZONS}}
    # 아직 안 지난 기록 중 가장 빠른 '첫 숫자가 나오는 날'(평일 어림) — 화면이 '익는 중' 대신 'MM-DD부터' 로 보인다
    for k, st in [("now", g["now"])] + [(str(h), g["h"][str(h)]) for h in HORIZONS]:
        ds_ = [e["due"][k] for e in evs if k in (e.get("due") or {})]
        st["due"] = min(ds_) if ds_ else None
    if with_exit:
        done = [e["exit"] for e in evs if e["exit"] and e["exit_done"]]
        m = len(done)
        nostop = sum(1 for o in obs if not _has_stop(o.get("row")))
        g["n_exit"] = m
        g["n_nostop"] = nostop
        g["stop_first"] = round(100.0 * done.count("stop") / m, 2) if m else None
        g["target_first"] = round(100.0 * done.count("target") / m, 2) if m else None
        if nostop and strict_exit:
            g["stop_first"] = g["target_first"] = None
            g["exit_note"] = _nostop_note(obs, n_all)
        elif nostop:
            g["exit_note"] = "손절가 있는 기록만 셈 — 손절가 없는 %d건은 뺐다" % nostop
        if strict_exit and any((o.get("row") or {}).get("pattern") == "trendline_break" and _has_stop(o.get("row"))
                               for o in obs):
            g["exit_note"] = (g["exit_note"] + " · " if g.get("exit_note") else "") + TL_STOP_CAVEAT
    return g


# ---------------------------------------------------------------- 읽기
_FWD_RE = re.compile(r"^(\d{8})\.json$")


def _data_date(rows):
    """스냅숏 기준일 = 행들의 price_d 중 가장 늦은 날 — 섞인 파일(일부 종목 주가 캐시가 하루 묵음)도
    그 파일을 쓸 때 이미 알던 가장 늦은 종가 날로 묶는다(진입은 그 다음 거래일 · 파일 쓴 날 이후)."""
    ds = [d for d in (_d8(r.get("price_d")) for r in rows if isinstance(r, dict)) if d]
    return max(ds) if ds else None


def load_forward(dir_path):
    """실전 기록 폴더 → [{"file", "file_date", "data_date", "at", "rows"}] 기준일 순.
    같은 기준일(휴일 · 주말에 다시 쓴 파일)은 가장 이른 파일 하나만 — 가장 먼저 진입할 수 있던 기록."""
    best = {}
    try:
        names = sorted(os.listdir(dir_path))
    except OSError:
        return []
    for fn in names:
        m = _FWD_RE.match(fn)
        if not m:
            continue
        try:
            with open(os.path.join(dir_path, fn), "r", encoding="utf-8") as fh:
                j = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(j, dict):
            continue
        rows = [r for r in (j.get("rows") or []) if isinstance(r, dict)]
        fdate = m.group(1)
        if not _d8(fdate):
            continue
        dd = _data_date(rows) or _shift(fdate, -1)
        cur = best.get(dd)
        if cur is None or fn < cur["file"]:
            best[dd] = {"file": fn, "file_date": fdate, "data_date": dd, "at": j.get("at"), "rows": rows}
    return [best[k] for k in sorted(best)]


def load_journal(path):
    """Tech 스캔 일지(UTF-8 BOM) → 행 목록. asof 는 'YYYYMMDD', 숫자 칸은 float(빈 칸 None).
    더 붙은 칸(추적용)은 버린다. 파일은 읽기만 한다."""
    out = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            asof = _d8(r.get("asof"))
            code = _code(r.get("code"))
            if not asof or not code:
                continue
            row = {"asof": asof, "code": code}
            for k in J_TEXT:
                row[k] = (r.get(k) or "").strip()
            for k in J_NUM:
                row[k] = _num(r.get(k))
            row["leader"] = (r.get("leader") or "").strip().lower() in ("true", "1", "y", "yes")
            out.append(row)
    return out


# ---------------------------------------------------------------- 두 기록 묶기
def _file_date(s):
    """실전 기록 파일 쓴 날(06:30, 장 전) — 진입은 이 날 종가보다 앞설 수 없다. 모르면 None."""
    fd = _d8(s.get("file_date"))
    if fd:
        return fd
    m = _FWD_RE.match(os.path.basename(s.get("file") or ""))
    return m.group(1) if m else None


def _value_part(snaps, prices, univ, cutoff, glast=None):
    snaps = sorted(((_d8(s.get("data_date")), s) for s in snaps if _d8(s.get("data_date"))), key=lambda t: t[0])
    obs_all, cohorts, dates, prev_v = [], [], [], None
    for d, s in snaps:
        nb = _file_date(s)
        dates.append(d)
        seen, obs = set(), []
        for r in s.get("rows") or []:
            code = _code(r.get("code"))
            if not code or code in seen:
                continue
            seen.add(code)
            obs.append({"code": code, "date": d, "row": r, "tier": r.get("tier"),
                        "score": _num(r.get("score")), "risk": bool(r.get("risk")),
                        "ev": _evaluate(prices, univ, code, d, cutoff, nb, glast=glast)})
        scored = sorted((o for o in obs if o["score"] is not None), key=lambda o: (-o["score"], o["code"]))
        k = len(scored) // 3
        for o in obs:
            o["top"] = o["bot"] = False
        for o in scored[:k]:
            o["top"] = True
        for o in scored[len(scored) - k:] if k else []:
            o["bot"] = True
        cur_v = {o["code"] for o in obs if o["tier"] == V_TIER}
        for o in obs:
            o["new_v"] = o["tier"] == V_TIER and (prev_v is None or o["code"] not in prev_v)
        prev_v = cur_v
        ov = [o for o in obs if o["tier"] == V_TIER]
        oo = [o for o in obs if o["tier"] == O_TIER]
        cohorts.append({"date": d, "file": s.get("file"), "n_v": len(ov), "n_o": len(oo),
                        "now_v": _stats([o["ev"]["now"] for o in ov if o["ev"] and o["ev"]["now"]], len(ov), True),
                        "now_o": _stats([o["ev"]["now"] for o in oo if o["ev"] and o["ev"]["now"]], len(oo), True)})
        obs_all.extend(obs)
    spec = (("tier_v", "저평가 등급", lambda o: o["tier"] == V_TIER),
            ("tier_o", "관찰 등급", lambda o: o["tier"] == O_TIER),
            ("score_top", "저평가 점수 위 ⅓", lambda o: o["top"]),
            ("score_bot", "점수 아래 ⅓", lambda o: o["bot"]),
            ("risk", "공시 위험 걸림", lambda o: o["risk"]),
            ("new_v", "저평가 새로 들어온 날만", lambda o: o["new_v"]))
    uniq = _dedupe(obs_all)
    return {"dates": dates, "n_codes": len({o["code"] for o in uniq}),
            "n_obs": len(uniq), "n_noprice": sum(1 for o in uniq if o["ev"] is None),
            "groups": [_group(k, lab, [o for o in obs_all if f(o)]) for k, lab, f in spec],
            "cohorts": cohorts, "ref": dict(VALUE_REF)}


def is_legacy(r):
    """rule 칸이 빈 일지 행 = 2026-10-14 패턴 초기화 전 옛 탐지기 기록."""
    return not (r.get("rule") or "").strip()


def _tech_part(rows, prices, univ, cutoff, glast=None):
    """Tech 일지 묶음(지금 식 기록만 — 옛 탐지기 기록은 score() 가 미리 뺀다). 권장 · 피하기 묶음은 만들지 않는다
    (지금 식으로 잰 백테스트가 아직 없다)."""
    by_date = {}
    for r in rows:
        d = _d8(r.get("asof"))
        code = _code(r.get("code"))
        if d and code:
            by_date.setdefault(d, []).append((code, r))
    dates = sorted(by_date)
    obs_all, prev = [], None
    for d in dates:
        cur = {c for c, _ in by_date[d]}
        for code, r in by_date[d]:
            ev = _evaluate(prices, univ, code, d, cutoff, stop=_num(r.get("stop")), glast=glast)
            obs_all.append({"code": code, "date": d, "row": r, "ev": ev,
                            "new": prev is None or code not in prev})
        prev = cur

    def grp(key, label, obs):          # 손절가 없는 기록이 섞인 묶음의 손절 비율은 내지 않는다
        return _group(key, label, obs, True, strict_exit=True)

    groups = [grp("all", "전체", obs_all),
              grp("new", "새로 들어온 날만", [o for o in obs_all if o["new"]])]
    pc = Counter((o["row"].get("pattern") or "") for o in obs_all)
    for p, _ in sorted(pc.items(), key=lambda kv: (-kv[1], kv[0])):
        name = PATTERN_KO.get(p, p)
        groups.append(grp("pattern:" + (p or "-"), "패턴 · " + name,
                          [o for o in obs_all if (o["row"].get("pattern") or "") == p]))
    sc = Counter((o["row"].get("stage") or "") for o in obs_all)
    for s in sorted(sc, key=lambda x: (STAGE_ORDER.index(x) if x in STAGE_ORDER else 99, x)):
        groups.append(grp("stage:" + (s or "-"), "단계 · " + STAGE_KO.get(s, s),
                          [o for o in obs_all if (o["row"].get("stage") or "") == s]))
    uniq = _dedupe(obs_all)
    return {"dates": dates, "n_codes": len({o["code"] for o in uniq}),
            "n_obs": len(uniq), "n_noprice": sum(1 for o in uniq if o["ev"] is None),
            "groups": groups, "ref": dict(TECH_REF)}


def score(forward_snaps, journal_rows, prices, universe_codes, today=None):
    """두 기록을 채점해 JSON 으로 그대로 내보낼 수 있는 dict 를 돌려준다.
    today('YYYYMMDD' 등)를 주면 그 뒤 주가는 없는 것으로 본다."""
    cutoff = _d8(today)
    univ = universe_codes if isinstance(universe_codes, (list, tuple)) else list(universe_codes or ())
    for c in univ:                       # 전체 마지막 거래일(끊긴 종목 판단)을 먼저 안다 — 벤치마크도 어차피 읽는다
        prices.series(c)
    glast = prices.last
    if cutoff and glast and glast > cutoff:
        glast = cutoff
    value = _value_part(forward_snaps or [], prices, univ, cutoff, glast)
    jr = journal_rows or []
    tech = _tech_part([r for r in jr if not is_legacy(r)], prices, univ, cutoff, glast)      # 옛 탐지기 기록(제거된 식)은 뺀다
    last = prices.last
    if cutoff and last and last > cutoff:
        last = cutoff
    return {"schema": SCHEMA, "at": dt.datetime.now().isoformat(timespec="seconds"), "cutoff": cutoff,
            "basis": BASIS, "price_last": last, "horizons": list(HORIZONS),
            "value": value, "tech": tech, "notes": list(NOTES)}


def run(fwd_dir, journal_path, price_load, universe_codes, today=None):
    """읽기부터 채점까지 한 번에. 주가는 기록 첫날 조금 앞부터만 들고 있는다."""
    snaps = load_forward(fwd_dir) if fwd_dir and os.path.isdir(fwd_dir) else []
    rows = load_journal(journal_path) if journal_path and os.path.isfile(journal_path) else []
    ds = [s["data_date"] for s in snaps] + [r["asof"] for r in rows]
    since = _shift(min(ds), -(BENCH_BACK + 5)) if ds else None
    prices = Prices(price_load, since=since)
    return score(snaps, rows, prices, list(universe_codes or ()), today)

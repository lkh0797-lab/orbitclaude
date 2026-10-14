# 수출 선행 발굴 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 통관 수출이 아직 공시 안 된 분기에 +20%↑ 늘었는데 주가는 안 따라왔고 값은 자기 역사 기준으로 싼 회사를, 과거 검증 결과와 함께 수출 추적 탭의 새 칸 · 저평가 탭 배지로 보인다.

**Architecture:** 판정은 새 순수 모듈 `수출선행.py`(서버 · 재무 import 없음)에 두고 pytest 로 다 검사한다. `도구/수출선행_백테스트.py` 가 시점 기준(통관 ≤ m · 접수일 ≤ d)으로 2021~ 매달 같은 판정을 돌려 `.cache/수출선행/bt.json` 을 쓴다. 서버는 `exlead_view()` 한 함수에서 수출 추적 결과 · 주가 캐시 · 풍경 캐시 · bt.json 을 묶어 `/api/exlead` 로 내고, `value_view()` 줄에 `exl` 을 붙인다. 화면은 `viewExport` 에 칸 하나, `valTable` 에 배지 하나.

**Tech Stack:** Python 3.11 32-bit 표준 라이브러리(서버 · 모듈 · 도구), pytest, 바닐라 JS/SVG(웹/index.html).

**Spec:** `docs/superpowers/specs/2026-10-14-export-lead-value-design.md`

## Global Constraints

- 새 DART · 관세청 · 네이버 · KIS 호출 없음 — 모두 캐시 읽기. 새 자동 루프 없음.
- `수출선행.py` 는 `서버.py` · `재무.py` · `관세청.py` 를 import 하지 않는다(순수 함수).
- 테스트는 반드시 `python -X utf8 -m pytest -q tests` (bare `pytest` 금지 — 51k 폴더를 걷는다).
- 커밋은 자기 파일만 `git add <file>` (절대 `-A` 금지 — 다른 세션이 같은 저장소를 쓴다). 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- 문구 규칙: 모르는 값은 `모름`, 영상 · 책 일화 수익률 금지, 검증 전이면 '(검증 전)' 표시. 비밀값(.env 키 · KIS 설정)은 열지도 찍지도 않는다.
- 숫자 기준(스펙 1절): 단서 `cur ≥ 20`, 주가 `ret3m ≤ 전 종목 중앙값 또는 dd52 ≤ −25`, 값 `per_pct ≤ 50`, 부채 `de ≥ 200`(금융업 제외), 등급 A·B, lumpy 제외.
- 뷰어(8765)는 레시피로만 재시작(Stop-ScheduledTask GiupChujeok_Viewer → viewer.py 프로세스 종료 → Start-ScheduledTask). 시험 서버는 `python -X utf8 서버.py --port 8766 --no-auto`.

## Review Focus

1. 통관 2개월만 나온 분기(`aligned.reported == False`, months 2개) — 단서로 친다; 1개월이면 `reported == True` 로 떨어져 목록에서 빠져야 한다 → Task 1 judge 테스트.
2. 주가 이력이 91일 미만(신규 상장) — 주가 조건 '모름' → 관찰, 발굴 아님 → Task 1 judge 테스트 `ret3m=None`.
3. 풍경 캐시가 없거나 `decide.pct` 가 None(적자) — 값 '모름' → 관찰 → Task 1 + Task 3 서버 테스트.
4. 백테스트에서 미래 달이 섞이면 안 된다 — `cut_series` 에 m 뒤 달을 넣어도 결과 불변(앞부분 불변) → Task 2 테스트.
5. bt.json 이 없을 때 화면 제목 '(검증 전)', verdict 가 '관찰'일 때 등급 이름 '관찰 후보' → Task 3 서버 테스트 + Task 4 화면.

---

### Task 1: `수출선행.py` 순수 함수 + 테스트

**Files:**
- Create: `수출선행.py`
- Test: `tests/test_수출선행.py`

**Interfaces:**
- Produces (Task 2 · 3 이 쓴다):
  - `quarter_end(q: str) -> datetime.date` — `"2026Q3"` → 2026-09-30
  - `due_date(q: str) -> datetime.date` — 1·2·3분기 = 분기 말 + 45일, 4분기 = 분기 말 + 90일, 토·일이면 다음 월요일
  - `due_label(q: str, today: datetime.date) -> dict` — `{"due": "2026-11-16", "days": 33, "text": "D-33 · 11-16까지(≈)"}` (지났으면 `"D+5 · 11-16 지남"`)
  - `hit_rate(pairs: list[dict]) -> tuple[int, int]` — `(맞춘 수, 비교 가능한 수)`; 맞춤 = `(x >= 0) == (r >= 0)`; x 또는 r 이 None 이면 뺀다
  - `gap(y12, px_yoy) -> float | None`
  - `pearson(a: list, b: list) -> float | None` — None 쌍 제외, 3개 미만이면 None
  - `pit_grade(pairs: list[dict], coverage: float | None) -> str` — `"A" | "B" | "C"`: n(x·r 둘 다 있는 수) < 6 → C; coverage None 또는 5~150 밖 → C; r ≥ 0.6 and n ≥ 8 → A; r ≥ 0.3 → B; else C
  - `cut_series(mon: dict, m: str) -> dict` — `{ym: v}` 중 `ym <= m` 만
  - `rev_quarters(mon_cut: dict, rev_yoy_by_q: dict) -> list[dict]` — 완성 분기(3개월 다 있는)만 `{"q", "x"(통관 분기 YoY), "r"(매출 YoY)}`, 전년 같은 분기 합이 0 이면 x None
  - `judge(inp: dict) -> dict` — 아래 코드 그대로
  - `index_series(mon: dict, px_m: dict, n: int = 24) -> list[dict]` — 마지막 n 개월 `{ym, x, p}`; x = 12개월 합 지수, p = 월말 주가 지수, 첫 유효 달 = 100
  - 상수 `CLUE_MIN = 20.0`, `PRICE_DD = -25.0`, `VALUE_PCT_MAX = 50.0`, `DEBT_RED = 200.0`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_수출선행.py
# -*- coding: utf-8 -*-
"""수출 선행 발굴 — 순수 함수(2026-10-14). 스펙 docs/superpowers/specs/2026-10-14-export-lead-value-design.md 1 · 2절."""
import os, sys, datetime as dt, importlib.util as ilu
import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("수출선행_시험", os.path.join(BASE, "수출선행.py"))
X = ilu.module_from_spec(_sp); _sp.loader.exec_module(X)
D = dt.date


def test_quarter_end_and_due_date():
    assert X.quarter_end("2026Q3") == D(2026, 9, 30)
    assert X.quarter_end("2026Q4") == D(2026, 12, 31)
    assert X.quarter_end("2024Q1") == D(2024, 3, 31)
    assert X.due_date("2026Q3") == D(2026, 11, 16)          # 9/30 + 45 = 11/14(토) → 11/16(월)
    assert X.due_date("2026Q2") == D(2026, 8, 14)           # 6/30 + 45 = 8/14(금)
    assert X.due_date("2025Q4") == D(2026, 3, 31)           # 12/31 + 90 = 3/31(화)
    assert X.due_date("2024Q4") == D(2025, 3, 31)           # 윤년 거침


def test_due_label_before_and_after():
    assert X.due_label("2026Q3", D(2026, 10, 14)) == {"due": "2026-11-16", "days": 33, "text": "D-33 · 11-16까지(≈)"}
    assert X.due_label("2026Q2", D(2026, 8, 19))["text"] == "D+5 · 08-14 지남"


def test_hit_rate_counts_only_comparable_pairs():
    pairs = [{"x": 10, "r": 5}, {"x": -3, "r": -1}, {"x": 8, "r": -2}, {"x": None, "r": 4}, {"x": 2, "r": None}, {"x": 0, "r": 0}]
    assert X.hit_rate(pairs) == (3, 4)
    assert X.hit_rate([]) == (0, 0)


def test_gap_and_pearson():
    assert X.gap(40.0, -20.0) == 60.0
    assert X.gap(None, -20.0) is None and X.gap(40.0, None) is None
    assert X.pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert X.pearson([1, 2, None, 3], [2, 4, 9, 6]) == pytest.approx(1.0)       # None 쌍 제외
    assert X.pearson([1, 2], [2, 4]) is None
    assert X.pearson([1, 1, 1], [2, 4, 6]) is None                                # 분산 0


def _pairs(n, r=1.0):
    return [{"x": float(i), "r": float(i) * r} for i in range(n)]


def test_pit_grade_thresholds():
    assert X.pit_grade(_pairs(5), 30.0) == "C"                     # 쌍 부족
    assert X.pit_grade(_pairs(8), None) == "C"                     # 비중 모름
    assert X.pit_grade(_pairs(8), 4.9) == "C" and X.pit_grade(_pairs(8), 150.1) == "C"
    assert X.pit_grade(_pairs(8), 5.0) == "A" and X.pit_grade(_pairs(8), 150.0) == "A"
    assert X.pit_grade(_pairs(7), 30.0) == "B"                     # 상관 1 이지만 8쌍 미만 → B
    mixed = [{"x": 0, "r": 0}, {"x": 1, "r": 3}, {"x": 2, "r": 1}, {"x": 3, "r": 4}, {"x": 4, "r": 2}, {"x": 5, "r": 6}, {"x": 6, "r": 3}, {"x": 7, "r": 7}]
    g = X.pit_grade(mixed, 30.0)
    assert g in ("A", "B")                                          # 상관 0.3 ↑
    anti = [{"x": i, "r": -i} for i in range(8)]
    assert X.pit_grade(anti, 30.0) == "C"


def test_cut_series_and_rev_quarters():
    mon = {"202501": 10, "202502": 10, "202503": 10, "202504": 12, "202505": 12, "202506": 12, "202507": 9,
           "202601": 15, "202602": 15, "202603": 15, "202604": 18, "202605": 18}
    cut = X.cut_series(mon, "202604")
    assert max(cut) == "202604" and "202605" not in cut
    rq = X.rev_quarters(cut, {"2026Q1": 20.0, "2025Q1": None})
    assert rq == [{"q": "2026Q1", "x": 50.0, "r": 20.0}]           # 2026Q1 만 완성 + 작년 분기 합 있음(2025Q1 30 → 45)
    # 미래 달을 더해도 잘라 낸 결과는 같다(앞부분 불변)
    mon2 = dict(mon, **{"202606": 99, "202607": 99})
    assert X.cut_series(mon2, "202604") == cut


def _inp(**kw):
    base = {"grade": "A", "lumpy": False, "reported": False, "cur": 35.0, "months": ["202607", "202608"],
            "ret3m": -4.0, "univ3m": 2.0, "dd52": -10.0, "per_pct": 30.0, "red": [], "risk": [], "fin": False}
    base.update(kw)
    return base


def test_judge_found():
    j = X.judge(_inp())
    assert j["tier"] == "발굴" and j["why"] == [] and j["checks"] == {"clue": True, "price": True, "value": True, "red": False}


def test_judge_no_clue_cases():
    assert X.judge(_inp(reported=True))["tier"] is None            # 이미 공시된 분기 값뿐 — 공시보다 먼저가 아님
    assert X.judge(_inp(cur=19.9))["tier"] is None
    assert X.judge(_inp(cur=None))["tier"] is None
    assert X.judge(_inp(grade="C"))["tier"] is None
    assert X.judge(_inp(lumpy=True))["tier"] is None


def test_judge_watch_reasons():
    j = X.judge(_inp(ret3m=18.0, univ3m=2.0, dd52=-5.0))
    assert j["tier"] == "관찰" and j["checks"]["price"] is False and "주가 3개월 +18%" in j["why"][0]
    j = X.judge(_inp(ret3m=18.0, univ3m=2.0, dd52=-30.0))          # 3개월은 올랐어도 고점 대비 −30% 면 통과
    assert j["tier"] == "발굴"
    j = X.judge(_inp(ret3m=None, dd52=None))
    assert j["tier"] == "관찰" and j["checks"]["price"] is None and any("주가 모름" in w for w in j["why"])
    j = X.judge(_inp(per_pct=72.0))
    assert j["tier"] == "관찰" and j["checks"]["value"] is False and any("상위 28%" in w for w in j["why"])
    j = X.judge(_inp(per_pct=None))
    assert j["tier"] == "관찰" and j["checks"]["value"] is None and any("값 모름" in w for w in j["why"])
    j = X.judge(_inp(red=["부채비율 240% — 200% 넘는 빚"]))
    assert j["tier"] == "관찰" and j["checks"]["red"] is True and j["why"] == ["빨간불: 부채비율 240% — 200% 넘는 빚"]
    j = X.judge(_inp(risk=["공시 위험: 빨강", "증권사 상태: 관리종목"]))
    assert j["tier"] == "관찰" and j["why"] == ["공시 위험: 빨강", "증권사 상태: 관리종목"]


def test_index_series_rebased_and_missing_months():
    mon = {"2024%02d" % m: 10 for m in range(1, 13)}
    mon.update({"2025%02d" % m: 20 for m in range(1, 13)})
    px = {"2024%02d" % m: 100 for m in range(1, 13)}
    px.update({"2025%02d" % m: 80 for m in range(1, 13)})
    px.pop("202506")
    s = X.index_series(mon, px, n=24)
    assert len(s) == 24 and s[0]["ym"] == "202401" and s[-1]["ym"] == "202512"
    assert s[0]["p"] == 100.0 and s[-1]["p"] == 80.0
    assert s[5]["ym"] == "202406" and s[5]["x"] == 100.0           # 12개월 합이 처음 완성되는 달까지 100
    assert s[-1]["x"] == 200.0                                      # 2025 합 240 vs 2024 합 120
    assert s[17]["ym"] == "202506" and s[17]["p"] is None           # 빠진 달은 None(선이 끊긴다)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -X utf8 -m pytest -q tests/test_수출선행.py`
Expected: FAIL — `FileNotFoundError` (수출선행.py 없음)

- [ ] **Step 3: Write `수출선행.py`**

```python
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


# ---------------------------------------------------------------- 판정
def _pct(v):
    return ("%+.0f%%" % v) if v is not None else "모름"


def judge(inp):
    """세 조건 + 빨간불 → {"tier": "발굴"|"관찰"|None, "why": [...], "checks": {...}}.
    inp: grade, lumpy, reported, cur, months, ret3m, univ3m, dd52, per_pct, red[list], risk[list], fin."""
    clue = (inp.get("grade") in ("A", "B") and not inp.get("lumpy") and inp.get("reported") is False
            and inp.get("cur") is not None and inp["cur"] >= CLUE_MIN)
    checks = {"clue": bool(clue), "price": None, "value": None, "red": False}
    if not clue:
        return {"tier": None, "why": [], "checks": checks}
    why = []
    ret3m, univ, dd = inp.get("ret3m"), inp.get("univ3m"), inp.get("dd52")
    if dd is not None and dd <= PRICE_DD:
        checks["price"] = True
    elif ret3m is not None and univ is not None:
        checks["price"] = ret3m <= univ
        if not checks["price"]:
            why.append("주가 3개월 %s — 전 종목 중앙 %s 보다 이미 올랐다(고점 대비 %s)" % (_pct(ret3m), _pct(univ), _pct(dd)))
    else:
        why.append("주가 모름 — 이력 91일 미만")
    pp = inp.get("per_pct")
    if pp is None:
        why.append("값 모름 — PER 없음(적자 · 표본 부족 · 풍경 없음)")
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -X utf8 -m pytest -q tests/test_수출선행.py`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add 수출선행.py tests/test_수출선행.py
git commit -m "수출 선행 발굴: 순수 판정 모듈(기한 · 적중 · 등급 · 판정 · 지수) + 테스트

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `도구/수출선행_백테스트.py` — 시점 기준 과거 검증 → `.cache/수출선행/bt.json`

**Files:**
- Create: `도구/수출선행_백테스트.py`
- Test: `tests/test_수출선행.py` (시점 자르기 검사 추가 — 아래)
- Output: `.cache/수출선행/bt.json`, `.cache/수출선행/bt_rows.json`

**Interfaces:**
- Consumes: `수출선행.cut_series / rev_quarters / pit_grade / judge / gap`; `도구/억울_백테스트.py` 의 `PX, px_at, ret, next_day, grp_ret, shift, ds, boot` (저평가_백테스트.py 와 같은 방식으로 로드); `수출추적.aligned` 와 `USDKRW`; `.cache/수출추적/result.json`; `.cache/value/bt_panel.json`(code, lab, t, per_pct, debt_eq, rev_yoy); `S.company_by_code(code)["reports"]`(stamp · rcept · tag); `S.DRK.series(corp, code, years)`(분기 매출액 — 비중 계산).
- Produces: `bt.json` 형식(스펙 3절): `{"v": 1, "at", "dates": [first, last], "n", "groups": {name: {"n", "firms", "days", "ex3", "ex6", "ex12": {"med", "ci", "early", "late", "n"}}}, "gap_split": {"top", "bot", "spread", "ci"}, "overlap": 0.xx, "verdict": "발굴"|"관찰", "caveats": [...]}`

- [ ] **Step 1: Add the point-in-time test to `tests/test_수출선행.py`**

```python
def test_pit_inputs_prefix_invariant():
    # 도구/수출선행_백테스트.pit_inputs 와 같은 재료로 — 미래 달 · 미래 접수일을 더해도 시점 d 의 판정 재료는 같다
    mon = {"2025%02d" % m: 100 for m in range(1, 13)}
    mon.update({"202601": 150, "202602": 150, "202603": 150, "202604": 160, "202605": 160})
    rev = {"2025Q1": 10.0, "2025Q2": 12.0, "2025Q3": 8.0, "2025Q4": 9.0, "2026Q1": 40.0}
    fd = {"2025Q1": "20250515", "2025Q2": "20250814", "2025Q3": "20251114", "2025Q4": "20260331", "2026Q1": "20260515"}
    a = X.pit_pairs(mon, rev, fd, m="202605", d="20260616")
    b = X.pit_pairs(dict(mon, **{"202606": 999, "202607": 999}), dict(rev, **{"2026Q2": 99.0}), dict(fd, **{"2026Q2": "20260814"}), m="202605", d="20260616")
    assert a == b
    assert [p["q"] for p in a] == ["2026Q1"]                        # 2025 분기는 2024 통관이 없어 x None → r 만 (r 도 없으면 빠짐) … 2026Q1 만 x · r 둘 다
    assert X.last_reported_q(fd, "20260616") == "2026Q1" and X.last_reported_q(fd, "20260514") == "2025Q4"
```

그리고 `수출선행.py` 에 두 함수를 더한다(Task 1 파일에):

```python
def last_reported_q(fd, d):
    """접수일 fd[q] <= d 인 마지막 분기(없으면 None)."""
    qs = [q for q, t in (fd or {}).items() if t and t <= d]
    return max(qs) if qs else None


def pit_pairs(mon, rev_yoy_by_q, fd, m, d):
    """시점 d(= 통관 달 m 의 다음 달 16일)에서 알 수 있던 쌍 — 통관 ≤ m, 매출은 접수일 ≤ d 인 분기만."""
    cut = cut_series(mon, m)
    rev_d = {q: v for q, v in (rev_yoy_by_q or {}).items() if (fd or {}).get(q) and fd[q] <= d}
    return [p for p in rev_quarters(cut, rev_d) if p["x"] is not None and p["r"] is not None]
```

- [ ] **Step 2: Run to verify the new test fails, add the functions, run to pass**

Run: `python -X utf8 -m pytest -q tests/test_수출선행.py` → FAIL `AttributeError: pit_pairs` → add → 11 passed

- [ ] **Step 3: Write the tool**

```python
# 도구/수출선행_백테스트.py
# -*- coding: utf-8 -*-
"""
수출 선행 발굴 — 과거엔 맞았나 (2026-10-14). 설계 docs/superpowers/specs/2026-10-14-export-lead-value-design.md 3절.

시점: 2021-02 ~ 마지막 통관 달, 매달 16일(관세청이 지난달 치를 내는 15일께 다음 날). 진입 = 그 날 다음 거래일 종가.
시점 자르기: 통관 ≤ m, 공시는 접수일 ≤ d, 등급은 그때까지 쌓인 쌍으로(수출선행.pit_grade), PER 백분위 · 부채는
.cache/value/bt_panel.json 의 접수일 ≤ d 마지막 줄. 주가 · 전 종목 중앙값은 억울_백테스트 와 같은 틀.
잰다: 3 · 6 · 12개월 초과수익(같은 기간 전 종목 중앙값 대비), 묶음별 중앙값 · 회사 단위 부트스트랩 90% · 앞(~2023)/뒤(2024~).
한계(bt.json caveats 에도 적는다): 통로는 지금 보고서 기준 · 지금 상장사만 · 공시위험/증권사 상태는 과거를 모름 · 겹침.

실행: python 도구/수출선행_백테스트.py           (주가 988곳 읽기 포함 10분 안팎)
      python 도구/수출선행_백테스트.py --report  (bt_rows.json 으로 다시 집계)
"""
import os, sys, json, bisect, datetime as dt, statistics as st, importlib.util

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

OUT = os.path.join(S.CACHE_DIR, "수출선행")
Q_MON = {"03": 1, "06": 2, "09": 3, "12": 4}
HORIZON = {"ex3": 91, "ex6": 182, "ex12": 365}
SPLIT = "20240101"          # 앞(2021~2023) · 뒤(2024~)


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
    """분기 매출 YoY — DRK.series(분기 매출액)로. 비중(coverage)도 여기 매출로."""
    try:
        pts = S.DRK.series(corp, code, list(range(2019, dt.date.today().year + 1)))
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
    k = [r for r in rows if r["t"] <= d]
    return k[-1] if k else None


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


def build_rows():
    with open(os.path.join(S.CACHE_DIR, "수출추적", "result.json"), "r", encoding="utf-8") as fh:
        items = [x for x in json.load(fh)["items"] if x.get("status") == "ok" and (x.get("series_long") or x.get("series"))]
    with open(os.path.join(S.CACHE_DIR, "value", "bt_panel.json"), "r", encoding="utf-8") as fh:
        panel = {}
        for r in json.load(fh):
            panel.setdefault(r["code"], []).append(r)
    for v in panel.values():
        v.sort(key=lambda r: r["t"])
    rows = []
    for i, x in enumerate(items):
        code = x["code"]
        c = S.company_by_code(code)
        corp = S.corp_code_of(code)
        if not c or not corp or code not in W.PX:
            continue
        mon = x.get("series_long") or x["series"]
        fd = filing_dates(c)
        yoy, rev = rev_yoy_by_q(corp, code)
        fin = bool(S.VAL_FIN.search(W.IND.get(code, "") or ""))
        for m in month_list("202101", max(mon)):
            d = d_of(m)
            if d > W.ds(dt.date.today()):
                break
            cut = X.cut_series(mon, m)
            lrq = X.last_reported_q(fd, d)
            if not lrq:
                continue
            pairs = X.pit_pairs(mon, yoy, fd, m, d)
            grade = X.pit_grade(pairs, coverage_at(cut, rev, fd, d))
            al = E.aligned(cut, lrq, [{"q": p["q"], "x": p["x"], "r": p["r"]} for p in pairs])
            if not al:
                continue
            e = W.next_day(code, d)
            if not e:
                continue
            pr = panel_at(panel.get(code, []), d)
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
                   "cur": al["cur"], "reported": al["reported"], "ret3m": ret3m, "univ3m": univ3m, "dd52": inp["dd52"],
                   "per_pct": inp["per_pct"]}
            y12 = _y12(cut, m)
            px_yoy = W.ret(code, W.shift(d, -365), d)
            row["y12"], row["gap"] = y12, X.gap(y12, px_yoy)
            for k, days in HORIZON.items():
                r_, b_ = W.ret(code, e, W.shift(e, days)), W.grp_ret("__all__", e, W.shift(e, days))
                row[k] = (r_ - b_) if (r_ is not None and b_ is not None) else None
            rows.append(row)
        if i % 20 == 0:
            print("  %d/%d %s" % (i, len(items), x["name"]), flush=True)
    return rows


def _y12(cut, m):
    w = [X._ym_shift(m, k) for k in range(12)]
    ly = [X._ym_shift(k, 12) for k in w]
    cur, prev = sum(cut.get(k, 0) for k in w), sum(cut.get(k, 0) for k in ly)
    return (cur / prev - 1) * 100 if prev > 0 and all(k in cut for k in ly) else None


def _stat(rows, k="ex12"):
    v = [r[k] for r in rows if r.get(k) is not None]
    if len(v) < 5:
        return {"med": None, "ci": [None, None], "n": len(v)}
    lo, hi = W.boot([r for r in rows if r.get(k) is not None], lambda rs: st.median([r[k] for r in rs]))
    return {"med": st.median(v), "ci": [lo, hi], "n": len(v)}


def summarize(rows):
    def grp(name, sub):
        g = {"n": len(sub), "firms": len({r["code"] for r in sub}), "days": len({r["d"] for r in sub})}
        for k in HORIZON:
            g[k] = _stat(sub, k)
        g["ex12"]["early"] = _stat([r for r in sub if r["d"] < SPLIT], "ex12")["med"]
        g["ex12"]["late"] = _stat([r for r in sub if r["d"] >= SPLIT], "ex12")["med"]
        return g
    found = [r for r in rows if r["tier"] == "발굴"]
    watch = [r for r in rows if r["tier"] == "관찰"]
    clue = found + watch
    groups = {"발굴": grp("발굴", found), "관찰": grp("관찰", watch), "단서만": grp("단서만", clue),
              "비교(통로 있는 회사 전체)": grp("비교", rows)}
    gs = [r for r in clue if r.get("gap") is not None and r.get("ex12") is not None]
    gap_split = None
    if len(gs) >= 30:
        v = sorted(r["gap"] for r in gs)
        a, b = v[len(v) // 3], v[2 * len(v) // 3]
        top, bot = [r for r in gs if r["gap"] >= b], [r for r in gs if r["gap"] < a]
        lo, hi = W.boot(gs, lambda rs: (st.median([r["ex12"] for r in rs if r["gap"] >= b]) - st.median([r["ex12"] for r in rs if r["gap"] < a]))
                        if (sum(r["gap"] >= b for r in rs) > 5 and sum(r["gap"] < a for r in rs) > 5) else None)
        gap_split = {"top": st.median([r["ex12"] for r in top]), "bot": st.median([r["ex12"] for r in bot]),
                     "spread": st.median([r["ex12"] for r in top]) - st.median([r["ex12"] for r in bot]), "ci": [lo, hi]}
    by = {}
    for r in sorted(found, key=lambda r: (r["code"], r["d"])):
        by.setdefault(r["code"], []).append(r["d"])
    cons = sum(1 for ds_ in by.values() for a_, b_ in zip(ds_, ds_[1:]) if W.shift(a_, 40) >= b_)
    overlap = cons / max(1, len(found) - len(by))
    f = groups["발굴"]["ex12"]
    verdict = "발굴" if (f["med"] is not None and f["early"] is not None and f["late"] is not None
                       and f["early"] > 0 and f["late"] > 0
                       and (f["ci"][0] is not None and f["ci"][0] > 0)) else "관찰"
    return {"v": 1, "at": dt.datetime.now().isoformat(timespec="seconds"),
            "dates": [min(r["d"] for r in rows), max(r["d"] for r in rows)] if rows else None, "n": len(rows),
            "groups": groups, "gap_split": gap_split, "overlap": round(overlap, 3), "verdict": verdict,
            "caveats": ["통로(시군구 × 품목)는 지금 보고서 기준 — 과거 시점 공장이 달랐을 수 있다",
                        "지금 상장된 회사만(생존 편향)", "공시위험 · 증권사 상태는 과거 시점을 몰라 빨간불에 넣지 않았다",
                        "같은 회사가 연속 달에 또 걸리면 모두 셌다(겹침 비율 overlap)", "초과수익 = 같은 기간 전 종목 중앙값 대비 · 수수료 없음"]}


def main():
    os.makedirs(OUT, exist_ok=True)
    rows_p = os.path.join(OUT, "bt_rows.json")
    if "--report" in sys.argv and os.path.exists(rows_p):
        rows = json.load(open(rows_p, encoding="utf-8"))
    else:
        rows = build_rows()
        with open(rows_p, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False)
    rep = summarize(rows)
    with open(os.path.join(OUT, "bt.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1)
    for k, g in rep["groups"].items():
        e = g["ex12"]
        print("%-22s n %5d · 회사 %3d · 날 %3d · 12개월 초과 중앙 %s [%s, %s] · 앞 %s · 뒤 %s" % (
            k, g["n"], g["firms"], g["days"], _f(e["med"]), _f(e["ci"][0]), _f(e["ci"][1]), _f(e["early"]), _f(e["late"])))
    print("벌어짐 위⅓−아래⅓:", rep["gap_split"], "· 겹침", rep["overlap"], "· 판정:", rep["verdict"])


def _f(v):
    return "모름" if v is None else "%+.1f%%p" % v


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tool**

Run: `python -X utf8 도구/수출선행_백테스트.py` (10분 안팎). 로그와 `bt.json` 의 `verdict`, 묶음 표를 진행 기록에 적는다. 실패하면 `--report` 로 집계만 다시.
Expected: `.cache/수출선행/bt.json` 생성, 네 묶음 숫자 출력. **숫자를 보고 문턱(20 · −25 · 50)을 바꾸지 않는다.**

- [ ] **Step 5: Commit**

```bash
git add 도구/수출선행_백테스트.py 수출선행.py tests/test_수출선행.py
git commit -m "수출 선행 발굴: 시점 기준 과거 검증 도구 → .cache/수출선행/bt.json

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
(`.cache/` 는 git 밖 — bt.json 은 커밋하지 않는다.)

---

### Task 3: 서버 `exlead_view()` · `/api/exlead` · 저평가 줄 `exl`

**Files:**
- Modify: `서버.py` — `export_view` 구역 바로 뒤에 `# ---- 수출 선행 발굴 (2026-10-14)` 구역 추가; `value_view()` 끝에 `exl` 붙이기; 라우트 `if path == "/api/export":` 앞에 `/api/exlead`
- Test: `tests/test_수출선행_서버.py`

**Interfaces:**
- Consumes: `수출선행.judge / due_label / hit_rate / gap / index_series`; `export_view()`(items 에 `aligned` · `grade` · `signals.y12` · `validation.pairs` · `national`); `_px_file(code)`; `_land_read(code)`(`decide.pct · decide.per · decide.zone`, `rows[-1].de`); `VAL["rows"]`(red); `_disc_risk()` · `_kis_snapshot()` · `_kis_tags()` · `DRISK_RED`; `_score_universe()`; `_last_close()`.
- Produces: `exlead_view() -> dict` = `{"at", "basis", "verdict", "title", "rows": [...], "bt", "rules", "caveats"}`; row = `{"code","name","industry","tier","why","checks","cur","months","months_label","cur_q","prev","acc","est","err","due","hit","unit_yoy","ret3m","univ3m","dd52","px_yoy","y12","gap","per","per_pct","zone","idx":[...]}`; `value_view()` 줄에 `exl: {"tier","cur","months_label","due","why"}`.

- [ ] **Step 1: Write the failing server tests**

```python
# tests/test_수출선행_서버.py
# -*- coding: utf-8 -*-
"""수출 선행 발굴 서버 — 가짜 캐시로 exlead_view · value_view 배지(2026-10-14)."""
import os, sys, json, copy, datetime as dt, importlib.util as ilu
import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("서버_수출선행_시험", os.path.join(BASE, "서버.py"))
SRV = ilu.module_from_spec(_sp); _sp.loader.exec_module(SRV)


def _mon(last="202608", v=100.0, bump=1.5):
    out = {}
    y, m = 2023, 1
    while "%04d%02d" % (y, m) <= last:
        k = "%04d%02d" % (y, m)
        out[k] = v * (bump if k >= "202607" else 1.0)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _item(code="000001", name="가짜", grade="A", cur=50.0, reported=False, lumpy=False):
    return {"code": code, "name": name, "status": "ok", "grade": grade, "series_long": _mon(),
            "signals": {"last": "202608", "y12": 30.0, "state": "가속"},
            "aligned": {"cur_q": "2026Q3", "prev_q": "2026Q2", "months": ["202607", "202608"], "reported": reported, "cur": cur,
                        "prev": 10.0, "acc": 40.0, "lumpy": lumpy, "est": 25.0, "err": 8.0, "state": "가속", "last": "202608"},
            "validation": {"pairs": [{"q": "2026Q1", "x": 20, "r": 15}, {"q": "2026Q2", "x": -5, "r": 2}], "last_rev_q": "2026Q2"},
            "national": [{"hs": "854232", "unit_yoy": 12.0, "name": "메모리"}]}


def _px(days=400, start=10000.0, end=9000.0):
    d0 = dt.date(2026, 10, 13) - dt.timedelta(days=days)
    out = {}
    for i in range(days + 1):
        d = d0 + dt.timedelta(days=i)
        if d.weekday() < 5:
            out[d.strftime("%Y%m%d")] = start + (end - start) * i / days
    return out


@pytest.fixture
def world(monkeypatch, tmp_path):
    items = [_item(), _item("000002", "비쌈", cur=60.0)]
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "export_view", lambda: {"items": copy.deepcopy(items), "month": "202608"})
    px = {"000001": _px(), "000002": _px(end=13000.0)}
    for k in ("000003", "000004", "000005"):
        px[k] = _px(end=10500.0)                       # 전 종목 3개월 중앙값 ≈ +1% (5곳 — _exl_univ3m 최소)
    monkeypatch.setattr(SRV, "_px_file", lambda code: dict(px.get(code) or {}))
    monkeypatch.setattr(SRV, "_score_universe", lambda: sorted(px))
    monkeypatch.setattr(SRV, "FIN", None)              # value_view 가 _run_value 스레드를 띄우지 않게
    land = {"000001": {"decide": {"pct": 30.0, "per": 8.5, "zone": "쌈"}, "rows": [{"de": 40.0}]},
            "000002": {"decide": {"pct": 80.0, "per": 30.0, "zone": "비쌈"}, "rows": [{"de": 40.0}]}}
    monkeypatch.setattr(SRV, "_land_read", lambda code: copy.deepcopy(land.get(code)))
    monkeypatch.setattr(SRV, "_disc_risk", lambda: {"codes": {}})
    monkeypatch.setattr(SRV, "_kis_snapshot", lambda: None)
    monkeypatch.setattr(SRV, "sector_map", lambda: {"stocks": {}})
    monkeypatch.setattr(SRV, "VAL", {"rows": [], "at": 0, "running": False})
    SRV._EXL.update(key=None, d=None)
    return tmp_path


def test_exlead_rows_and_tiers(world):
    d = SRV.exlead_view()
    assert d["verdict"] is None and "(검증 전)" in d["title"]
    by = {r["code"]: r for r in d["rows"]}
    a, b = by["000001"], by["000002"]
    assert a["tier"] == "발굴" and a["why"] == [] and a["due"]["due"] == "2026-11-16" and a["hit"] == [1, 2]
    assert a["months_label"] == "7~8월" and a["cur_q"] == "2026Q3" and a["unit_yoy"] == 12.0
    assert a["per_pct"] == 30.0 and a["zone"] == "쌈" and len(a["idx"]) == 24
    assert b["tier"] == "관찰" and any("상위 20%" in w for w in b["why"]) and any("이미 올랐다" in w for w in b["why"])
    assert d["rows"][0]["code"] == "000001"                         # 발굴 먼저


def test_exlead_missing_landscape_is_unknown_value(world, monkeypatch):
    monkeypatch.setattr(SRV, "_land_read", lambda code: None)
    SRV._EXL.update(key=None, d=None)
    r = {x["code"]: x for x in SRV.exlead_view()["rows"]}["000001"]
    assert r["tier"] == "관찰" and r["per_pct"] is None and any("값 모름" in w for w in r["why"])


def test_exlead_reads_bt_and_sets_title(world):
    os.makedirs(os.path.join(str(world), "수출선행"), exist_ok=True)
    bt = {"v": 1, "verdict": "관찰", "groups": {"발굴": {"n": 40, "firms": 9, "days": 30, "ex12": {"med": -1.2, "ci": [-5.0, 2.0], "early": -2.0, "late": 1.0, "n": 40}}}}
    with open(os.path.join(str(world), "수출선행", "bt.json"), "w", encoding="utf-8") as fh:
        json.dump(bt, fh)
    SRV._EXL.update(key=None, d=None)
    d = SRV.exlead_view()
    assert d["verdict"] == "관찰" and "과거 우위 근거 없음" in d["title"] and d["bt"]["groups"]["발굴"]["n"] == 40
    assert all(r["tier_label"] == "관찰 후보" for r in d["rows"] if r["tier"] == "발굴")


def test_value_rows_get_export_badge(world, monkeypatch):
    monkeypatch.setattr(SRV, "VAL", {"rows": [{"code": "000001", "name": "가짜", "tier": "저평가", "score": 60, "red": []}], "at": 1, "running": False})
    monkeypatch.setattr(SRV, "_val_score_spec", lambda: None)
    SRV._EXL.update(key=None, d=None)
    rows = SRV.value_view()["rows"]
    assert rows[0]["exl"]["tier"] == "발굴" and rows[0]["exl"]["cur"] == 50.0 and rows[0]["exl"]["months_label"] == "7~8월"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -X utf8 -m pytest -q tests/test_수출선행_서버.py`
Expected: FAIL — `AttributeError: module has no attribute '_EXL'`

- [ ] **Step 3: Add the server section** (export_view 구역 뒤)

```python
# ---------------------------------------------------------------- 수출 선행 발굴 (2026-10-14)
# 통관은 올랐는데 주가 · 값은 아직 — 설계 docs/superpowers/specs/2026-10-14-export-lead-value-design.md.
# 판정은 수출선행.py(순수), 재료는 수출 추적 결과 · 주가 캐시 · 풍경 캐시 · 저평가 줄 · 공시위험 · 증권사 상태 · bt.json. 새 호출 · 루프 없음.
try:
    _xl = _ilu.spec_from_file_location("수출선행", os.path.join(BASE, "수출선행.py"))
    EXL = _ilu.module_from_spec(_xl)
    _xl.loader.exec_module(EXL)
except Exception as _e:
    EXL = None
    print("수출선행 모듈 로드 실패:", _e)
EXL_DIR = os.path.join(CACHE_DIR, "수출선행")
_EXL = {"key": None, "d": None, "univ": {}, "bt_mt": None, "bt": None}
EXL_LOCK = threading.Lock()


def _exl_bt():
    p = os.path.join(EXL_DIR, "bt.json")
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None
    if _EXL["bt_mt"] != mt:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                _EXL.update(bt=json.load(fh), bt_mt=mt)
        except Exception:
            return _EXL["bt"]
    return _EXL["bt"]


def _exl_px(code):
    """{"last": (날짜, 종가), "ret3m", "px_yoy", "dd52", "px_m": {YYYYMM: 월말 종가}} — 주가 캐시만."""
    import bisect
    px = _px_file(code) or {}
    ks = sorted(px)
    if not ks:
        return None
    last = ks[-1]
    p = px[last]

    def back(days):
        t = (dt.datetime.strptime(last, "%Y%m%d") - dt.timedelta(days=days)).strftime("%Y%m%d")
        i = bisect.bisect_right(ks, t) - 1
        if i < 0 or ks[i] < (dt.datetime.strptime(t, "%Y%m%d") - dt.timedelta(days=10)).strftime("%Y%m%d"):
            return None
        return (p / px[ks[i]] - 1) * 100 if px[ks[i]] else None
    t365 = (dt.datetime.strptime(last, "%Y%m%d") - dt.timedelta(days=365)).strftime("%Y%m%d")
    hi = max((px[k] for k in ks if k >= t365), default=None)
    pm = {}
    for k in ks:
        pm[k[:6]] = px[k]
    return {"last": (last, p), "ret3m": back(91), "px_yoy": back(365), "dd52": (p / hi - 1) * 100 if hi else None, "px_m": pm}


def _exl_univ3m(day):
    """같은 날짜 기준 전 종목 3개월 수익률 중앙값 — 하루 한 번."""
    if _EXL["univ"].get("day") == day:
        return _EXL["univ"]["v"]
    rs = []
    for c in _score_universe():
        x = _exl_px(c)
        if x and x.get("ret3m") is not None:
            rs.append(x["ret3m"])
    rs.sort()
    v = rs[len(rs) // 2] if len(rs) >= 5 else None       # 실제 유니버스는 988곳 — 5곳 미만이면 모름
    _EXL["univ"] = {"day": day, "v": v}
    return v


def _exl_months_label(months):
    if not months:
        return ""
    a, b = int(months[0][4:]), int(months[-1][4:])
    return ("%d월" % a) if a == b else ("%d~%d월" % (a, b))


def _exl_risk(code, dr, ks):
    out = []
    rk = (dr.get("codes") or {}).get(code) if dr else None
    if rk and rk.get("level") in DRISK_RED:
        out.append("공시 위험: " + rk["level"])
    bad, _ = _kis_tags((ks or {}).get(code))
    if bad:
        out.append("증권사 상태: " + " · ".join(bad))
    return out


def exlead_view():
    if EXL is None:
        return {"error": "수출선행 모듈이 없다"}
    ex = export_view()
    if ex.get("error"):
        return {"error": ex["error"]}
    _, lc, _ = _last_close()
    day = lc.strftime("%Y%m%d")
    bt = _exl_bt()
    key = (_EXP.get("mt"), day, _EXL["bt_mt"], (VAL.get("at") or 0))
    with EXL_LOCK:
        if _EXL["key"] == key and _EXL["d"] is not None:
            return _EXL["d"]
    univ = _exl_univ3m(day)
    dr, ks = _disc_risk() or {}, ((_kis_snapshot() or {}).get("status")) or {}
    vrows = {r["code"]: r for r in (VAL.get("rows") or [])}
    smap = (sector_map() or {}).get("stocks", {})
    today = dt.date.today()
    rows = []
    for x in ex.get("items") or []:
        al = x.get("aligned")
        if x.get("status") != "ok" or not al or x.get("grade") not in ("A", "B"):
            continue
        code = x["code"]
        pxi = _exl_px(code) or {}
        land = _land_read(code) or {}
        dec = land.get("decide") or {}
        vr = vrows.get(code)
        fin = bool(VAL_FIN.search((smap.get(code.upper(), {}) or {}).get("industry") or ""))
        red = list(vr.get("red") or []) if vr else []
        de = ((land.get("rows") or [{}])[-1] or {}).get("de")
        if not vr and de is not None and de >= EXL.DEBT_RED and not fin:
            red.append("부채비율 %.0f%% — 200%% 넘는 빚" % de)
        inp = {"grade": x.get("grade"), "lumpy": al.get("lumpy"), "reported": al.get("reported"), "cur": al.get("cur"),
               "months": al.get("months") or [], "ret3m": pxi.get("ret3m"), "univ3m": univ, "dd52": pxi.get("dd52"),
               "per_pct": dec.get("pct"), "red": red, "risk": _exl_risk(code, dr, ks), "fin": fin}
        j = EXL.judge(inp)
        if j["tier"] is None:
            continue
        hit = EXL.hit_rate((x.get("validation") or {}).get("pairs") or [])
        y12 = (x.get("signals") or {}).get("y12")
        nat = (x.get("national") or [{}])[0] or {}
        rows.append({"code": code, "name": x["name"], "industry": (smap.get(code.upper(), {}) or {}).get("industry") or "",
                     "tier": j["tier"], "why": j["why"], "checks": j["checks"], "grade": x.get("grade"),
                     "cur": al.get("cur"), "months": al.get("months"), "months_label": _exl_months_label(al.get("months")),
                     "cur_q": al.get("cur_q"), "prev": al.get("prev"), "acc": al.get("acc"), "est": al.get("est"), "err": al.get("err"),
                     "due": EXL.due_label(al["cur_q"], today) if al.get("cur_q") else None, "hit": list(hit),
                     "unit_yoy": nat.get("unit_yoy"), "ret3m": pxi.get("ret3m"), "univ3m": univ, "dd52": pxi.get("dd52"),
                     "px_yoy": pxi.get("px_yoy"), "y12": y12, "gap": EXL.gap(y12, pxi.get("px_yoy")),
                     "per": dec.get("per"), "per_pct": dec.get("pct"), "zone": dec.get("zone"),
                     "price": (pxi.get("last") or (None, None))[1], "price_d": (pxi.get("last") or (None, None))[0],
                     "idx": EXL.index_series(x.get("series_long") or x.get("series") or {}, pxi.get("px_m") or {}, 24)})
    rows.sort(key=lambda r: (r["tier"] != "발굴", -(r["gap"] if r["gap"] is not None else -1e9)))
    verdict = (bt or {}).get("verdict")
    n_found = sum(1 for r in rows if r["tier"] == "발굴")
    if verdict == "발굴":
        title, label = "수출은 먼저 올랐다 — 주가 · 값은 아직 %d곳" % n_found, "발굴"
    elif verdict == "관찰":
        title, label = "수출은 먼저 올랐다 — 관찰 (과거 우위 근거 없음) %d곳" % n_found, "관찰 후보"
    else:
        title, label = "수출은 먼저 올랐다 — 주가 · 값은 아직 %d곳 (검증 전)" % n_found, "발굴(검증 전)"
    for r in rows:
        r["tier_label"] = label if r["tier"] == "발굴" else "관찰"
    d = {"at": time.time(), "basis": ex.get("month"), "verdict": verdict, "title": title, "rows": rows, "bt": bt,
         "rules": {"clue": EXL.CLUE_MIN, "dd": EXL.PRICE_DD, "per_pct": EXL.VALUE_PCT_MAX, "debt": EXL.DEBT_RED},
         "caveats": ["통로는 지금 보고서 기준(옛 공장 변경 모름)", "지금 상장사만(생존 편향)", "매출 ≠ 이익 — 단가는 보조",
                     "대형주는 잠정실적 공시가 보고서 기한보다 먼저일 수 있다", "주가 = 네이버 일봉(KRX+넥스트레이드 통합 시세)"]}
    with EXL_LOCK:
        _EXL.update(key=key, d=d)
    return d
```

`value_view()` 끝(`out["rules"] = …` 뒤)에:

```python
    try:                                    # 수출 선행 발굴 배지(한 군데서 계산 — exlead_view)
        xl = {r["code"]: r for r in (exlead_view().get("rows") or [])}
        for r in out["rows"]:
            e = xl.get(r.get("code"))
            if e:
                r["exl"] = {"tier": e["tier"], "tier_label": e.get("tier_label"), "cur": e["cur"], "months_label": e["months_label"],
                            "cur_q": e["cur_q"], "due": e["due"], "hit": e["hit"], "why": e["why"]}
    except Exception:
        pass
```

라우트(`if path == "/api/export":` 앞):

```python
            if path == "/api/exlead":
                return self._send(200, exlead_view())
```

- [ ] **Step 4: Run the tests**

Run: `python -X utf8 -m pytest -q tests/test_수출선행_서버.py tests/test_수출선행.py` → 15 passed. 그다음 전체 `python -X utf8 -m pytest -q tests` → 모두 통과(기존 570 + 15).

- [ ] **Step 5: Smoke on 8766**

`python -X utf8 서버.py --port 8766 --no-auto` 띄우고 `curl -s http://127.0.0.1:8766/api/exlead | python -X utf8 -c "import json,sys; d=json.load(sys.stdin); print(d['title']); [print(r['name'], r['tier'], r['cur'], r['why'][:1]) for r in d['rows'][:12]]"`. 끝나면 8766 프로세스만 종료.

- [ ] **Step 6: Commit**

```bash
git add 서버.py tests/test_수출선행_서버.py
git commit -m "수출 선행 발굴: /api/exlead (수출 · 주가 · 풍경 · 빨간불 묶기) + 저평가 줄 exl 배지 재료

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: 화면 — 수출 추적 탭 새 칸 · 저평가 배지

**Files:**
- Modify: `웹/index.html` — `viewExport` 의 `const duo=el('div','expDuo');` 앞에 칸 삽입; `valTable` 이름 칸(`valRiskPill` 뒤)에 배지; CSS `.expPick.lead` 등
- Modify: `README.md` — 수출 추적 · 저평가 설명에 한 줄씩

**Interfaces:**
- Consumes: `GET /api/exlead` (Task 3 응답), `valTable` 의 `r.exl`.
- 기존 helper: `el`, `svgEl`, `expP`(퍼센트 문구), `expOpen(code)`, `pick(code)`, `expTrend(series, cls)`, `won`.

- [ ] **Step 1: CSS** (`.expPick .st{…}` 줄 근처)

```css
.expPick.lead{border-left:3px solid var(--p-gold,#d6b46a)}
.expPick.lead .h .verdict{font-size:11px;padding:0 6px;border-radius:999px;border:1px solid var(--line)}
.expLeadRow{font-size:11.5px;color:var(--dim);margin-top:3px;display:flex;gap:8px;flex-wrap:wrap;font-variant-numeric:tabular-nums}
.expLeadRow b{color:var(--ink)}
.expLeadWhy{font-size:11px;color:var(--del);margin-top:2px}
.expLeadTier{font-size:10.5px;border-radius:999px;padding:0 6px;border:1px solid var(--line);margin-left:4px}
.expLeadTier.found{color:var(--add);border-color:var(--add)}
.expGap{width:100%;height:58px;display:block;margin-top:3px}
.expGap .x{fill:none;stroke:var(--add);stroke-width:1.6}.expGap .p{fill:none;stroke:var(--ink);stroke-width:1.3;opacity:.7}
.expGap .ax{font-size:9px;fill:var(--faint)}
.expLeadPill{font-size:10.5px;color:var(--add);border:1px solid var(--add);border-radius:999px;padding:0 6px;margin-left:4px;cursor:help}
.expLeadPill.watch{color:var(--dim);border-color:var(--line)}
```

- [ ] **Step 2: 칸 함수** (`viewExport` 앞에 추가)

```javascript
// 수출 선행 발굴(2026-10-14) — 통관은 올랐는데 주가 · 값은 아직. /api/exlead(서버 exlead_view) — 판정은 수출선행.py, 검증은 bt.json
function expGapChart(idx){
  const W=300,H=58,L=4,R=4,T=8,B=12, ok=idx.filter(q=>q.x!=null||q.p!=null);
  const svg=svgEl('svg',{viewBox:'0 0 '+W+' '+H,class:'expGap'});
  if(ok.length<2) return svg;
  const vals=idx.flatMap(q=>[q.x,q.p]).filter(v=>v!=null), lo=Math.min(100,...vals), hi=Math.max(100,...vals);
  const x=i=>L+i*(W-L-R)/(idx.length-1), y=v=>T+(hi-v)/(hi-lo||1)*(H-T-B);
  svg.appendChild(svgEl('line',{x1:L,x2:W-R,y1:y(100),y2:y(100),stroke:'var(--line2)','stroke-dasharray':'3 3'}));
  [['x','x'],['p','p']].forEach(([k,cls])=>{ let d=''; idx.forEach((q,i)=>{ if(q[k]==null){ d+=' '; return; } d+=(/\d$/.test(d)?'L':'M')+x(i).toFixed(1)+','+y(q[k]).toFixed(1); });
    svg.appendChild(svgEl('path',{d:d.replace(/ +/g,''),class:cls})); });
  const t=svgEl('text',{x:L,y:H-2,class:'ax'}); t.textContent='24개월 전 = 100 · 초록 = 수출 12개월 합 · 흰선 = 주가'; svg.appendChild(t);
  return svg;
}
async function expLeadBox(){
  let d; try{ d=await (await fetch('/api/exlead')).json(); }catch(e){ d={error:'불러오지 못했다'}; }
  const b=el('div','expPick lead');
  const h=el('div','h'); b.appendChild(h);
  if(d.error){ h.appendChild(el('b',null,'수출은 먼저 올랐다')); b.appendChild(el('div','empty',d.error)); return b; }
  S.expF.lead=S.expF.lead||'발굴';
  h.appendChild(el('b',null,d.title));
  h.appendChild(el('span',null,'통관(아직 미공시 분기 +'+d.rules.clue+'%↑)은 올랐는데 주가는 아직(3개월 ≤ 전 종목 중앙 또는 고점 대비 '+d.rules.dd+'%↓)이고 값은 싸다(PER 자기 역사 하위 '+d.rules.per_pct+'%) — 분기보고서 전에'));
  const tg=el('button','ghost',S.expF.lead==='발굴'?'관찰까지 보기':'발굴만'); tg.onclick=()=>{ S.expF.lead=S.expF.lead==='발굴'?'전체':'발굴'; b.replaceWith(expLeadBoxSync(d)); }; h.appendChild(tg);
  return expLeadBoxSync(d,b);
}
function expLeadBoxSync(d,b){
  b=b||el('div','expPick lead');
  if(!b.querySelector('.h')){ const h=el('div','h'); h.appendChild(el('b',null,d.title)); const tg=el('button','ghost',S.expF.lead==='발굴'?'관찰까지 보기':'발굴만'); tg.onclick=()=>{ S.expF.lead=S.expF.lead==='발굴'?'전체':'발굴'; b.replaceWith(expLeadBoxSync(d)); }; h.appendChild(tg); b.appendChild(h); }
  const g=d.bt&&d.bt.groups&&d.bt.groups['발굴'], e=g&&g.ex12;
  if(e&&e.med!=null) b.appendChild(el('div','expNote','과거엔 이랬다 — 같은 조건 '+g.n+'건('+g.firms+'곳 · '+g.days+'날): 12개월 초과수익 중앙 '+expP(e.med)+'p ['+expP(e.ci[0])+', '+expP(e.ci[1])+'] · 앞 '+expP(e.early)+' · 뒤 '+expP(e.late)+' — 전 종목 중앙값 대비, 수수료 없음'));
  else b.appendChild(el('div','expNote','과거 검증 없음(검증 전) — python 도구/수출선행_백테스트.py'));
  const rows=(d.rows||[]).filter(r=>S.expF.lead==='전체'||r.tier==='발굴');
  if(!rows.length) b.appendChild(el('div','empty',S.expF.lead==='발굴'?'지금은 세 조건을 다 넘은 회사가 없다 — 관찰까지 보기':'해당 없음'));
  const grid=el('div','expCards'); b.appendChild(grid);
  rows.forEach(r=>{ const c=el('div','expCard');
    const t=el('div','t'); const a=el('a',null,r.name); a.href='#'; a.onclick=ev=>{ev.preventDefault(); expOpen(r.code);}; t.appendChild(a);
    t.appendChild(el('span','expLeadTier'+(r.tier==='발굴'?' found':''),r.tier_label));
    if(r.unit_yoy!=null) t.appendChild(el('span','good','단가 '+expP(r.unit_yoy)));
    c.appendChild(t);
    c.appendChild(expGapChart(r.idx||[]));
    const l1=el('div','expLeadRow'); l1.innerHTML='<b>'+r.months_label+' 통관 '+expP(r.cur)+'</b> ('+r.cur_q+' 미공시'+(r.est!=null?' · 매출 추정 '+expP(r.est)+'±'+Math.round(r.err||0):'')+')'+(r.due?' · <b>'+r.due.text+'</b>':'')+' · 적중 '+r.hit[0]+'/'+r.hit[1]; c.appendChild(l1);
    const l2=el('div','expLeadRow'); l2.textContent='주가 3개월 '+expP(r.ret3m)+' (전 종목 '+expP(r.univ3m)+') · 고점 대비 '+expP(r.dd52)+' · 1년 '+expP(r.px_yoy)+' · PER '+(r.per!=null?r.per.toFixed(1)+'배':'—')+(r.per_pct!=null?' 자기 역사 하위 '+Math.round(r.per_pct)+'%':' 모름')+' · 벌어짐 '+(r.gap!=null?expP(r.gap)+'p':'—'); c.appendChild(l2);
    if(r.why&&r.why.length) c.appendChild(el('div','expLeadWhy',r.why.join(' · ')));
    grid.appendChild(c); });
  b.appendChild(el('div','finnote',(d.caveats||[]).join(' · ')+'. 적중 = 같은 자료로 등급을 매긴 분기 쌍(표본 안). 기한 = 분기 말 +45일(사업보고서 +90일), 주말만 밈.'));
  return b;
}
```

`viewExport` 안 `const duo=el('div','expDuo');` 바로 앞에: `body.appendChild(await expLeadBox());`

- [ ] **Step 3: 저평가 배지** (`valTable` 의 `const rp = valRiskPill(r.risk); if (rp) td.appendChild(rp);` 뒤)

```javascript
    if (r.exl) { const x = r.exl, pl = el('span', 'expLeadPill' + (x.tier === '발굴' ? '' : ' watch'), '수출 단서 ' + expP(x.cur) + ' (' + x.months_label + '까지)');
      pl.title = x.cur_q + ' 아직 미공시' + (x.due ? ' · 기한 ' + x.due.due.slice(5) : '') + ' · 통관 적중 ' + x.hit[0] + '/' + x.hit[1] + ' · ' + (x.tier_label || x.tier) + (x.why && x.why.length ? '\n' + x.why.join('\n') : '');
      pl.onclick = ev => { ev.preventDefault(); ev.stopPropagation(); S.tab = 'exp'; jump('exp'); }; td.appendChild(pl); }
```

- [ ] **Step 4: README** — 수출 추적 절에 "수출 선행 발굴 칸(통관 +20%↑ · 주가 아직 · PER 자기 역사 하위 50%, 과거 검증 bt.json 이 제목을 정함)" 한 줄, 저평가 절에 "수출 단서 배지" 한 줄.

- [ ] **Step 5: 확인** — 8766 에 띄우고 브라우저로 수출 추적 탭 · 저평가 탭을 열어 콘솔 오류 0, 칸 · 배지가 보이는지 본다(스크린샷). 끝나면 8766 종료.

- [ ] **Step 6: Commit**

```bash
git add 웹/index.html README.md
git commit -m "수출 선행 발굴 칸(수출 추적 탭) · 저평가 줄 수출 단서 배지

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: 뷰어 재시작 · 결과 확인

- [ ] 레시피로 8765 재시작(Stop-ScheduledTask GiupChujeok_Viewer → viewer.py 프로세스 종료 → Start-ScheduledTask).
- [ ] `curl /api/exlead` 로 제목 · 발굴/관찰 수 · 상위 줄을 적고, `/api/value` 줄에 `exl` 이 붙는지 확인.
- [ ] 진행 기록(scratchpad)에 bt.json 묶음 표 · 오늘 목록 · 남은 문제를 적는다.

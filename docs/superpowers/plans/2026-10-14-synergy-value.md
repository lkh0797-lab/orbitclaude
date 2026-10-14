# 시너지 발굴 1차 개선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 시너지 발굴에 '자기 역사 PER 위치'(싼 수주 추천필터 · 열 · 필터 칸)를 넣고, 점수 식의 작은 결함(전환 적자 동률 · 결측 재정규화 · 확인 가중 · 갭 자르기 · reliable 조건 · 쌍둥이)을 고친 뒤 백테스트를 다시 돌려 그 숫자로 화면 · README 의 과장 문구 20곳을 사실로 바꾼다. 매일 목록을 forward 로 남긴다.

**Architecture:** 판정 규칙은 `시너지.py`(score · SYN_REC · rec_pass) 한 곳 — 서버와 백테스트가 같은 함수를 부른다. 서버 `_syn_row` 는 풍경 캐시에서 오늘 PER · 자기 역사 백분위를 붙이고, 백테스트는 분기 패널에서 과거 백분위를 붙인다. 화면은 bt_report 값을 그대로 읽는다(하드코딩 금지).

**Tech Stack:** Python 3.11 32-bit 표준 라이브러리, pytest, 바닐라 JS.

**Spec:** `docs/superpowers/specs/2026-10-14-synergy-value-design.md` (문턱 · 문구 표는 거기 1절 · 부록)

## Global Constraints

- 테스트 `python -X utf8 -m pytest -q tests` (bare pytest 금지). 커밋은 자기 파일만 `git add <file>`(-A 금지). 커밋 끝 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- 새 DART · KIS · 네이버 호출 없음. `.cache/` 는 git 밖. 비밀값 안 봄.
- 문턱(스펙 1절)은 결과를 보고 바꾸지 않는다. 숫자는 다시 돌린 `bt_report.json` 에서만 — 감사 scratch 숫자(+10.7 등)를 화면 · README 에 쓰지 않는다.
- 8765 뷰어는 레시피로만 재시작, 시험은 8766(`--no-auto`)만.
- 다른 워크플로(수출 선행 발굴)가 같은 저장소의 `서버.py` · `웹/index.html` · `README.md` 를 고쳤을 수 있다 — 작업 시작 때 `git log -3` · `git status` 를 보고 HEAD 위에서 작업, 커밋 전 `git diff --stat` 로 자기 변경만 들어가는지 확인.

## Review Focus

1. 전환 적자 None → 50 대입: 적자 회사 점수가 흑자 중앙과 같은 자리에 오는가(최상위 동률 아님) → Task 1 테스트.
2. 선행 None 이면 점수 None, 가격만 있는 행이 점수를 갖지 않는가 → Task 1 테스트.
3. 백테스트 per_pct join 이 접수일 ≤ t 만 쓰는가(미래 분기 금지) → Task 2 테스트(합성).
4. 쌍둥이 둘 다 reliable 이던 것이 cover 큰 쪽 하나만 남는가, 업종 백분위에서 빠지는가 → Task 3 테스트.
5. bt_report 가 없거나 옛 형식(overall 없음)이어도 화면이 죽지 않는가 → Task 4(JS null 처리) + Task 3 synergy_view.

---

### Task 1: `시너지.py` — 점수 식 결함 · '싼 수주' · 문구

**Files:** Modify `시너지.py`; Create `tests/test_시너지.py`

**Interfaces (Produces):**
- `WEIGHTS = {"선행": .35, "전환": .25, "확인": 0.0, "가격": .25}`
- `score(rows)`: 행에 `score`, `parts`(선행 · 전환 · 확인 · 가격, None 가능). 규칙: 선행 None → score None; 전환 = 흑자(m4 > 0)만 백분위(`-m4`), 적자 None; 전환 · 가격 · 확인 None → 50 대입(재정규화 안 함); 확인은 계산해 parts 에 두되 가중 0.
- `SYN_REC[0] = {"id": "cheap", "name": "싼 수주", "desc": …, "f": {"stages": _NOT_SLOW, "btbMin": 1.1, "leadMin": 15, "perPctMax": 50}}`
- `rec_pass(r, f)`: 새 키 `leadMin`(r["lead"] ≥) · `perPctMax`(r["per_pct"] 가 None 이면 통과 못 함, 아니면 ≤).
- 행 필드 가정: `lead`, `per_pct` (서버 · 백테스트가 채운다).

- [ ] **Step 1: tests/test_시너지.py**

```python
# -*- coding: utf-8 -*-
"""시너지 점수 식(2026-10-14 v2) — 전환 적자 None · 결측 50 · 확인 가중 0 · 싼 수주 필터."""
import os, sys, importlib.util as ilu
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_sp = ilu.spec_from_file_location("시너지_시험", os.path.join(BASE, "시너지.py"))
SYN = ilu.module_from_spec(_sp); _sp.loader.exec_module(SYN)


def _row(code, btb=1.2, cov=0.2, m4=5.0, gap=20.0, new_pct=None, lead=20.0, per_pct=30.0, flags=None):
    return {"code": code, "reliable": True, "btb": btb, "cover_chg": cov, "margin4": m4, "gap": gap,
            "new_pct": new_pct, "flags": flags or [], "lead": lead, "per_pct": per_pct, "loss4": m4 is not None and m4 <= 0, "stage": "잠복"}


def test_weights_confirm_is_zero():
    assert SYN.WEIGHTS == {"선행": .35, "전환": .25, "확인": 0.0, "가격": .25}


def test_loss_company_gets_neutral_transition_not_top():
    rows = [_row("A", m4=12.0), _row("B", m4=4.0), _row("C", m4=1.0), _row("L", m4=-10.0)]
    SYN.score(rows)
    by = {r["code"]: r for r in rows}
    assert by["L"]["parts"]["전환"] is None                      # 적자 = 해당 없음
    assert by["C"]["parts"]["전환"] > by["A"]["parts"]["전환"]  # 흑자끼리는 낮을수록 높다
    # 적자는 50 대입 — 흑자 셋의 가운데와 같은 자리, 최상위 아님
    assert by["L"]["score"] < by["C"]["score"] and by["L"]["score"] > by["A"]["score"]


def test_missing_parts_substitute_50_not_renormalize():
    a, b = _row("A", gap=None), _row("B", gap=None, m4=None)
    rows = [a, b, _row("C"), _row("D", gap=-30.0, m4=20.0)]
    SYN.score(rows)
    for r in rows:
        assert r["score"] is not None
    # 가격이 None 인 행은 가격 50 — 선행이 같은 행끼리 비교하면 가격 100 인 C 보다 낮고 가격 0 인 D 보다 높다
    sc = {r["code"]: r["score"] for r in rows}
    assert sc["C"] > sc["A"] > sc["D"]


def test_no_leading_part_means_no_score():
    r = _row("X", btb=None, cov=None)
    SYN.score([r, _row("Y")])
    assert r["score"] is None and r["parts"].get("선행") is None


def test_confirm_part_is_shown_but_has_no_weight():
    a, b = _row("A", new_pct=50.0), _row("B", new_pct=None)
    SYN.score([a, b])
    assert a["parts"]["확인"] is not None and a["score"] == b["score"]


def test_cheap_filter_and_rec_pass_keys():
    rc = next(x for x in SYN.SYN_REC if x["id"] == "cheap")
    assert SYN.SYN_REC[0]["id"] == "cheap" and rc["f"] == {"stages": SYN._NOT_SLOW, "btbMin": 1.1, "leadMin": 15, "perPctMax": 50}
    assert SYN.rec_pass(_row("A"), rc["f"])
    assert not SYN.rec_pass(_row("A", per_pct=None), rc["f"])      # PER 없음 = 통과 못 함
    assert not SYN.rec_pass(_row("A", per_pct=51.0), rc["f"])
    assert not SYN.rec_pass(_row("A", lead=14.9), rc["f"])
    assert not SYN.rec_pass(dict(_row("A"), stage="둔화"), rc["f"])
```

- [ ] **Step 2:** `python -X utf8 -m pytest -q tests/test_시너지.py` → FAIL
- [ ] **Step 3:** 구현 — `score()`:

```python
    R = {
        "btb": _pct_rank([r["btb"] for r in ok]),
        "cov": _pct_rank([r.get("cover_chg") for r in ok]),
        # 흑자만 백분위 — 낮을수록 높은 점수(늘어날 여지). 적자는 '해당 없음'(None → 50 대입): 예전 식은 적자를 최상위 동률로 올렸다(2026-10-14 감사)
        "low": _pct_rank([-m for r in ok for m in [_margin(r)] if m is not None and m > 0]),
        "new": _pct_rank([r.get("new_pct") for r in ok]),
        "gap": _pct_rank([r["gap"] for r in ok]),
    }
    …
        m = _margin(r)
        parts = {
            "선행": blend([(R["btb"](r["btb"]), 0.5), (R["cov"](r.get("cover_chg")), 0.5)]),
            "전환": R["low"](-m) if (m is not None and m > 0) else None,
            "확인": R["new"](r.get("new_pct")) if r.get("new_pct") else None,     # 표시만 — 가중 0(검증 전)
            "가격": R["gap"](r["gap"]),
        }
        if parts["선행"] is None:
            r["parts"], r["score"] = {k: (round(v) if v is not None else None) for k, v in parts.items()}, None
            continue
        s = sum((50.0 if parts[k] is None else parts[k]) * WEIGHTS[k] for k in WEIGHTS) / sum(WEIGHTS.values())
```
  `rec_pass` 에 `ge(r.get("lead"), f.get("leadMin"))` · `(num(f.get("perPctMax")) is None or (r.get("per_pct") is not None and r["per_pct"] <= num(f["perPctMax"])))` 추가. `SYN_REC` 맨 앞에 cheap. 머리말 · 둔화 desc · 전환 주석 문구를 스펙 부록 #2 · #3 · #10 · #11 · #13 · #14 대로(숫자 자리는 "다시 돌린 검증 값은 README 참고").
- [ ] **Step 4:** 테스트 통과 + 전체 suite. **Step 5:** `git add 시너지.py tests/test_시너지.py` 커밋 "시너지 점수 v2: 전환 적자 해당 없음 · 결측 50 · 확인 가중 0 · 싼 수주 추천필터".

---

### Task 2: `도구/시너지_백테스트.py` — per_pct · lead · 양쪽 자름 · overall/no_slow, 다시 실행

**Files:** Modify `도구/시너지_백테스트.py`; Test `tests/test_시너지.py`(합성 join 검사 추가); Output `.cache/시너지/bt_panel.json` · `bt_report.json`

**Interfaces:**
- 모듈 함수 `qpanel_per_pct(code, year, q, t)` → 분기 패널 `(code, "%dQ%d")` 줄의 `per_pct`(접수일 `t_row ≤ t` 일 때만, 아니면 None). 패널은 모듈 로드 때 `.cache/quarter/bt_panel.json` 을 `{(code, lab): [(t, per_pct), …]}` 로 읽는다.
- `row_at` 행에 `per_pct`, `lead = backlog_yoy − rev4_yoy`(둘 다 있을 때), `gap = min(yoy,300) − min(p1y,300)`.
- `report()` 출력에 `overall`(전체 중앙 · ci) · `no_slow`(둔화 뺀 중앙 · ci) · 요인표에 `("per_pct", "PER 자기 역사 %(낮을수록 싸다)", …)` · `("lead", "잔고 − 4분기 매출(%p)", …)`.

- [ ] **Step 1: 테스트(합성 — 도구 모듈을 import 하지 않고 순수 join 규칙을 시너지.py 에 두어 검사)**: `시너지.py` 에 `def per_pct_at(entries, t)`(entries = [(t_filed, per_pct)], `t_filed <= t` 인 마지막) 추가, 테스트:

```python
def test_per_pct_at_uses_only_filed_rows():
    e = [("20240515", 20.0), ("20240814", 60.0), ("20241114", 90.0)]
    assert SYN.per_pct_at(e, "20240601") == 20.0
    assert SYN.per_pct_at(e, "20240814") == 60.0
    assert SYN.per_pct_at(e, "20240101") is None
    assert SYN.per_pct_at(e + [("20250101", 5.0)], "20240901") == 60.0       # 미래 줄은 안 본다
```

- [ ] **Step 2:** 도구 수정(위 인터페이스). `report()` 에 `out["overall"] = dict(W.summ(rows, Y), ci=[lo, hi])`, `out["no_slow"] = …`(둔화 뺀). 둔화 뺀 요인표(`nd0`)에도 per_pct · lead 를 포함.
- [ ] **Step 3: 실행** `python -X utf8 도구/시너지_백테스트.py > <scratch>/synergy_bt.log 2>&1` (background, 10~20분). 끝나면 묶음 · 추천필터(cheap 포함) · 단계 · overall/no_slow 숫자를 진행 기록에 적는다. **숫자를 보고 문턱 · 식을 바꾸지 않는다.**
- [ ] **Step 4:** `git add 도구/시너지_백테스트.py 시너지.py tests/test_시너지.py` 커밋.

---

### Task 3: 서버 — `_syn_row` · 쌍둥이 · 업종 백분위 · forward · synergy_view

**Files:** Modify `서버.py`; Create `tests/test_시너지_서버.py`

**Interfaces (Produces):**
- `_syn_row` 행에 `per`(오늘, 풍경 `decide.per`; 없으면 None), `per_filed`(예전 `PER_TTM`), `per_pct`(풍경 `decide.pct`), `per_med`(풍경 `band.mid`), `lead`, `gap`(양쪽 자름), `fresh_days`(마지막 잔고 보고서 접수일 · 마지막 분기 접수일 중 오래된 쪽부터 오늘까지 일수).
- reliable: 기존 다섯 + `fresh_days > 200` → why_not "마지막 잔고 · 재무가 N일 전 — 묵었다", 검산 창 = 최근 12개(`b["points"][-12:]` 의 verified/explicit 로 `sure`).
- 순수 함수(서버 모듈 상위): `_syn_twin_keep(rows)` — `same_as` 쌍 중 cover 큰 쪽만 reliable, 다른 쪽 `reliable=False, why_not="같은 잔고(이름) — 지주 · 자회사 중복"`; `_syn_capbl_pct(rows)` — reliable · industry != 분류없음 · cap · backlog 있는 행, 같은 업종 3곳↑일 때 `capbl_pct`(낮을수록 잔고 대비 시총 작음) 채움, 아니면 None.
- `_run_synergy`: `_syn_twin_keep` → `SYN.score` 앞에, `_syn_capbl_pct` 는 score 뒤, 끝에 forward 기록(`.cache/시너지/forward/YYYYMMDD.json`, 스펙 4절 필드, `cheap = SYN.rec_pass(r, SYN_REC[0]["f"])`).
- `synergy_view`: `out["bt"]` 에 `overall` · `no_slow` 추가.

- [ ] **Step 1: tests/test_시너지_서버.py** — `test_미리계산.py` 방식으로 서버 모듈 로드.

```python
def test_twin_keep_prefers_larger_cover():
    a = {"code": "A", "name": "원익홀딩스", "reliable": True, "cover": 0.4, "same_as": ["원익IPS"], "why_not": None}
    b = {"code": "B", "name": "원익IPS", "reliable": True, "cover": 1.2, "same_as": ["원익홀딩스"], "why_not": None}
    c = {"code": "C", "name": "혼자", "reliable": True, "cover": 0.9, "same_as": [], "why_not": None}
    SRV._syn_twin_keep([a, b, c])
    assert b["reliable"] and c["reliable"] and not a["reliable"] and "원익IPS" in a["why_not"]


def test_capbl_pct_needs_three_in_industry():
    rows = [{"code": str(i), "reliable": True, "industry": "조선", "cap": c, "backlog": 100.0} for i, c in enumerate((50.0, 100.0, 200.0))]
    rows.append({"code": "x", "reliable": True, "industry": "건설", "cap": 10.0, "backlog": 100.0})
    rows.append({"code": "u", "reliable": False, "industry": "조선", "cap": 1.0, "backlog": 100.0})
    SRV._syn_capbl_pct(rows)
    assert rows[0]["capbl_pct"] < rows[1]["capbl_pct"] < rows[2]["capbl_pct"]
    assert rows[3]["capbl_pct"] is None and rows[4]["capbl_pct"] is None


def test_reliable_why_fresh_and_window():
    assert SRV._syn_reliable_why(n=5, jumps=0, last_switch=None, sure=6, n_win=12, cover=0.5, fresh_days=100) is None
    assert "묵었다" in SRV._syn_reliable_why(n=5, jumps=0, last_switch=None, sure=6, n_win=12, cover=0.5, fresh_days=201)
    assert "절반" in SRV._syn_reliable_why(n=5, jumps=0, last_switch=None, sure=5, n_win=12, cover=0.5, fresh_days=10)
```

- [ ] **Step 2:** 구현(why_not 분기를 `_syn_reliable_why(n, jumps, last_switch, sure, n_win, cover, fresh_days)` 로 뺀다 — 기존 문구 그대로 + 묵음). 풍경 읽기: `land = _land_read(code) or {}`; `dec = land.get("decide") or {}`; `per = dec.get("per")`, `per_pct = dec.get("pct")`, `per_med = (land.get("band") or {}).get("mid")`. `lead`: `sr.get("매출_TTM")`·`sr.get("매출_TTM_1년전")`. forward 기록은 try/except 로 감싼다.
- [ ] **Step 3:** 테스트 + 전체 suite. 8766 smoke: `/api/synergy` 응답(계산이 3시간 캐시라 `?force=1` 로 한 번 — 몇 분) → reliable 수 · 쌍둥이 why_not 수 · per_pct 있는 행 수 · cheap 통과 수 · 상위 10 을 진행 기록에. forward 파일 생성 확인.
- [ ] **Step 4:** `git add 서버.py tests/test_시너지_서버.py` 커밋.

---

### Task 4: 화면 · README

**Files:** Modify `웹/index.html`, `README.md`

- [ ] SYN_DEF 에 `leadMin:'', perPctMax:''`; synPass 에 `if(!ge(r.lead,f.leadMin)) return false; if(num(f.perPctMax)!==null && !(r.per_pct!==null&&r.per_pct!==undefined&&r.per_pct<=num(f.perPctMax))) return false;`; 직접 설정 필터의 '가격·밸류' 묶음에 두 입력 칸(기존 gapMin 칸 옆, 같은 만드는 함수).
- [ ] SYN_PART_HELP · SYN_PRESETS 꼬리표(6장 desc 끝 " — 과거 검증 무신호") · 잠복/점화/과열 카드 "단계는 수익을 못 갈랐다".
- [ ] 표 `SYN_COLS['가격·밸류']`: 'PER' = `r.per`(오늘, 툴팁 "오늘 주가 ÷ 최근 4분기 주당이익(풍경)"), 'PER 자기 역사 %' = `r.per_pct`(툴팁 "자기 역사 분기 PER 중 지금보다 낮은 비율 — 낮을수록 싸다 · 적자 · 이력 부족은 —"), '시총/잔고 업종 %' = `r.capbl_pct`(툴팁 "같은 업종 안 백분위 — 낮을수록 잔고에 비해 시총이 작다 · 사이클 지표, 등급 근거 아님"). 예전 접수일 PER 열은 `r.per_filed` 로 이름 'PER(접수일)' 유지하거나 지움(지우면 README 도).
- [ ] 주목 종목: `ideas` = cheap 통과(`synPass(r, SYN_REC cheap f)` 또는 서버가 준 `r.cheap`) 점수 순 먼저, 모자라면 나머지 점수 순 8곳까지; 머리말 "TOP IDEAS · 싼 수주 먼저"; 각주 "단계는 과거 수익을 못 갈랐다".
- [ ] synEvidence: 요약줄 `전체 ${f(bt.overall.median)} · 둔화 ${f(SG.둔화.median)} vs 나머지 ${f(bt.no_slow.median)} — 잠복 · 점화 · 반영 · 관찰은 서로 구분되지 않는다(90% 구간 겹침)`(overall/no_slow 없으면 예전 줄 + "(옛 형식)"); 본문에 스펙 부록 #19 두 문장; 추천필터 표는 bt.rec 순회라 cheap 자동 — 턴어라운드 등 구간이 0 걸치면 '0 걸침' 표기.
- [ ] 문구 부록 #1 · #2 · #3 · #4 · #5 · #12 · #15 · #16 · #17 · #19 (index.html).
- [ ] README 604~744: 부록 #6 · #7 · #8 · #9 · #10 · #13 · #18 · #20 — **Task 2 가 낸 bt_report 값**으로. 09-30 · 10-07 값은 '이력' 소절로. 새 소절 "2026-10-14 v2: 전환 적자 해당 없음 · 결측 50 · 확인 가중 0 · 싼 수주 · PER 자기 역사 열 · forward 기록". 저평가 탭과 부호 반대 이유 한 줄(README 저평가 절에도).
- [ ] 8766 브라우저 확인(호재기업 → 시너지 발굴): 콘솔 오류 0, 추천필터 '싼 수주' 카드 · 과거 성적 줄, 표 열 셋, 직접 설정 칸, 주목 종목 머리말, 요약줄. 스크린샷.
- [ ] `git add 웹/index.html README.md` 커밋.

---

### Task 5: 뷰어 재시작 · 확인 · 기록

- [ ] 레시피 재시작. `/api/synergy?force=1` 한 번(몇 분) → reliable · cheap 수 · 상위 10 · forward 파일 · bt overall/no_slow/cheap 값을 진행 기록에.

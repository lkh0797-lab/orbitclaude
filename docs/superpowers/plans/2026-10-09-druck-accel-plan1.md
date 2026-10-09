# 가속도 탭 개편 — 계획 1: 기업추적 안(KIS 없이) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 가속도 탭과 형제 화면이 같은 가속 정의(B · 7국면 · 띠 ±3%p)를 한 곳(`드러켄밀러.py`)에서 읽고, 데이터 품질(분기 키 · 연결/별도 · 재작성 비교 · 정정 기준일 · 비12월 결산 · 분할 보정 EPS)을 고치고, 문구 · 성적표를 서술형 + 기저율로 바꾼다.

**Architecture:** `드러켄밀러.py` 에 계산을 모은다 — `period_data()`(비교기간 · rcept · 기준 추출), `series()`(분기 키 조밀 격자 · 품질), `share_basis()`(분기 주식 수 · 분할), `accel()`(B · 국면 · 변곡 · 엇갈림). 서버 `druck()` 은 버전 키 · 잠금 · 백그라운드 · 밤 미리 계산을 맡고, 소비처는 `_druck_read()` 로 같은 필드를 읽는다. 기저율 · 사건 수익률은 밤 64비트 별도 프로세스(`도구/가속기준_백테스트.py`)가 캐시에서 만든다.

**Tech Stack:** Python 3.11 32-bit(뷰어 · pytest 9.1) · Python 3.13 64-bit(`py -3.13`, 밤 백테스트) · 단일 파일 `웹/index.html`(바닐라 JS · SVG).

**Spec:** `docs/superpowers/specs/2026-10-09-druck-accel-kis-design.md` (커밋 7ed70a0). 계획 2(Tech KIS 레이어 · seen/want.json · `kis` 칸)는 이 계획이 들어간 뒤 따로 쓴다.

## Global Constraints
- 띠 `PHASE_BAND = 3.0`(%p), 정체 `PHASE_FLAT = 2.0`(%), 국면 이름 = `산업.PHASE_NAME` 그대로(확장 가속 · 확장 유지 · 둔화 · 회복 · 부진 지속 · 수축 심화) + '정체'.
- 변곡: |B(n)| ≥ 3 이고 n 앞의 가장 가까운 |B| ≥ 3 분기 m 이 반대 부호이며 n − m ≤ 4.
- 엇갈림: |B(n)| ≥ 3, C = Y(n) − Y(n−1) 가 반대 부호, |C| ≥ 5.
- 분기 키 n = 연도×4 + 분기 − 1. 앞 분기 · 1년 전은 키(n−1 · n−4)로만 찾는다(순번 금지).
- 국면 · 변곡 · 성적표 · 기저율 계산에 KIS 값을 넣지 않는다(이 계획엔 KIS 없음).
- 가속도 탭 문구에 실존 인물 이름 · 처방('비중을 싣는다', '들어가는 자리', '기다릴 구간')을 쓰지 않는다. 변곡점의 구루 렌즈 이름은 그대로.
- 기존 점 필드(매출_TTM · 매출YoY · 매출가속(C) · 영업이익_TTM · 주가 · 주가일 · 당기순이익 · 재고일수 · 매출채권일수)는 이름 · 뜻 유지. `EPS_TTM` · `PER_TTM` 은 분할 보정 값으로 바뀐다(원래 분기 EPS 는 `EPS` 에 남음).
- 시너지 `rev_accel` 은 C 그대로(범위 밖).
- 커밋은 자기 파일만 `git add <file>`. 커밋 전 `git diff` 로 남의 덩어리 확인. 커밋 끝줄: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- 뷰어 재시작은 16:00 · 00:10 · 02:00 · 06:30 을 피한다. 재시작 = `Stop-ScheduledTask GiupChujeok_Viewer` → `Start-ScheduledTask GiupChujeok_Viewer`(PowerShell).
- 경로에 공백 · 한글 — 셸에서는 늘 따옴표.

## Review Focus
1. **사업보고서가 아직 없는 올해 분기**(2026Q1 · Q2) — 최신 국면 · 헤드라인이 비지 않아야 한다(연결/별도는 그 분기 보고서 자체로 정함). → Task 2 테스트 `test_latest_year_without_annual`.
2. **상장 2년 안 회사**(HPSP 같은 짧은 이력) — B 가 아직 없으면 국면 없음으로 조용히 넘어가고 화면은 '분기 자료가 모자라 국면을 못 정했다'를 보인다(오류 아님). → Task 3 테스트 `test_short_history_no_phase`, Task 8 브라우저 확인.
3. **이익선 · 재작성이 섞이는 2015년 경계**(본문 파싱 → API) — 같은 B 창에 재작성 · 공시 당시가 섞이면 `mix` 로 공시 당시 값끼리 계산. → Task 3 테스트 `test_mix_window_falls_back_to_asfiled`.
4. **분기 하나만 빠진 회사**(비츠로테크 · LG씨엔에스) — 빈 분기를 건너뛰어 5분기 전과 비교하지 않는다. → Task 2 테스트 `test_gap_quarter_dense_grid`.
5. **캐시 버전이 옛것인 소비처 읽기**(_inv_regimes 등이 v1 파일을 읽는 순간) — 옛 파일은 없는 것으로 보고 빈 결과(오류 아님) + 다시 계산 대상. → Task 5 테스트 `test_druck_read_rejects_old_version`.

---

## File Structure
| 파일 | 맡는 일 |
|---|---|
| `재무.py` (수정) | `fetch_statement` 가 일시 오류(020 · 800 · 네트워크)를 본문으로 대신하지 않고 `transient` 표시 |
| `드러켄밀러.py` (수정) | 상수 `VERSION` · `PHASE_*` · `SHEV_*`, `phase_label()`, `period_data()` 확장, `series()` v2, `share_basis()`, `per_share()`, `accel()` |
| `산업.py` (수정) | `PHASE_*` · `_phase` 판정을 `드러켄밀러.phase_label` 로 |
| `서버.py` (수정) | `druck()` v2(버전 키 · 잠금 · 백그라운드 · offline · 지금 PER), `_druck_read()`, 밤 미리 계산 루프, 소비처 전환, `_pipe_rows` 가 `share_basis` 사용 |
| `변곡점.py` (수정) | 가속 전환 사건 · 드러켄밀러 카드 배지 · 판정을 `가속B` · `변곡` 으로 |
| `도구/가속기준_백테스트.py` (수정) | `--from-cache` — druck 캐시(v2)로 패널 · `bt_accel.json`(호환 키 + 7국면) · `events.json` |
| `도구/구루렌즈_검증.py` · `도구/구루적중률_백테스트.py` (수정) | 드러켄밀러 가속 규칙을 같은 시점 `가속B` 로 |
| `도구/가속도_점검.py` (새) | 회귀 사례 · 정의 대조 · 소비처 응답 점검 스크립트 |
| `tests/test_druck.py` (새) | `드러켄밀러.py` 순수 함수 테스트(pytest, 네트워크 없음) |
| `웹/index.html` (수정) | 가속도 탭 전부 · 변화 브리핑 국면 칩/띠/국면별 칸 · 전 종목 스크리닝 표/산점도 · 산업 섹터 안 종목 문구 |

---

### Task 1: `재무.fetch_statement` 일시 오류 표시 + `period_data()` 확장

**Files:**
- Modify: `재무.py:183-207` (`fetch_statement`), `재무.py:230-255` (`_or_body`)
- Modify: `드러켄밀러.py:36-46` (IS_PICK), `드러켄밀러.py:58-116` (`_grab`, `period_data`)
- Test: `tests/test_druck.py` (새)

**Interfaces:**
- Produces: `FIN.fetch_statement(...)` 가 일시 오류면 `{"status": <code>, "list": [], "transient": True}` 를 돌려준다(본문 대체 없음). 네트워크 예외도 같은 모양으로.
- Produces: `DRK.period_data(corp, year, q, offline=False) -> dict | None`. 키:
  `매출액 · 영업이익 · 당기순이익 · 지배순이익 · EPS`(그 보고서 thstrm), 같은 이름 + `_누적`(thstrm_add), `_전`(frmtrm_q, Q1 은 frmtrm_add 로 대체),
  `_전누적`(frmtrm_add), `_전연`(frmtrm, 사업보고서만), BS 4개, `CAPEX`(누적 그대로 — 분기 차분은 series 에서),
  메타 `_fs`('CFS'|'OFS'), `_src`('api'|'body'), `_rcept`(쓴 행 rcept_no 의 앞 8자리 최댓값 또는 None), `_transient`(bool).
- Produces: `DRK.NET` = `{"budget": None | int, "used": 0}` — offline 빌드의 네트워크 예산(캐시 파일이 없을 때만 차감).

- [ ] **Step 1: 실패하는 테스트**

`tests/test_druck.py`:
```python
# -*- coding: utf-8 -*-
import os, sys, importlib.util as ilu
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("드러켄밀러", os.path.join(BASE, "드러켄밀러.py"))
DRK = ilu.module_from_spec(_sp); _sp.loader.exec_module(DRK)


def row(sj, acc_id, name, **amt):
    r = {"sj_div": sj, "account_id": acc_id, "account_nm": name, "rcept_no": amt.pop("rcept", "20240514000123")}
    r.update({k: str(v) for k, v in amt.items()})
    return r


def stmt(rows, status="000"):
    return {"status": status, "list": rows}


def fake_fetch(table):
    """table: {(year, reprt, fs): stmt} — 없으면 013."""
    def f(corp, year, reprt, fs_div="CFS"):
        return table.get((int(year), str(reprt), fs_div), {"status": "013", "list": []})
    return f


def test_period_data_reads_comparatives(monkeypatch):
    rows = [row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=1200, thstrm_add_amount=2300,
                frmtrm_q_amount=1000, frmtrm_add_amount=1900, rcept="20240814000555"),
            row("IS", "ifrs-full_ProfitLossAttributableToOwnersOfParent", "지배기업 소유주지분", thstrm_amount=90, thstrm_add_amount=170,
                frmtrm_q_amount=80, frmtrm_add_amount=150)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11012", "CFS"): stmt(rows)}))
    d = DRK.period_data("C", 2024, 2)
    assert d["매출액"] == 1200 and d["매출액_누적"] == 2300
    assert d["매출액_전"] == 1000 and d["매출액_전누적"] == 1900
    assert d["지배순이익"] == 90 and d["_fs"] == "CFS" and d["_src"] == "api"
    assert d["_rcept"] == "20240814" and d["_transient"] is False


def test_period_data_q1_comparative_falls_back_to_add(monkeypatch):
    rows = [row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=500, thstrm_add_amount=500, frmtrm_add_amount=450)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11013", "CFS"): stmt(rows)}))
    assert DRK.period_data("C", 2024, 1)["매출액_전"] == 450


def test_period_data_annual_reads_frmtrm(monkeypatch):
    rows = [row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=5000, frmtrm_amount=4200)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11011", "CFS"): stmt(rows)}))
    d = DRK.period_data("C", 2024, 4)
    assert d["매출액"] == 5000 and d["매출액_전연"] == 4200


def test_period_data_ofs_fallback_marks_fs(monkeypatch):
    rows = [row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=10)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11013", "OFS"): stmt(rows)}))
    assert DRK.period_data("C", 2024, 1)["_fs"] == "OFS"


def test_period_data_transient(monkeypatch):
    monkeypatch.setattr(DRK.FIN, "fetch_statement",
                        lambda *a, **k: {"status": "020", "list": [], "transient": True})
    d = DRK.period_data("C", 2024, 1)
    assert d == {"_transient": True}
```

- [ ] **Step 2: 실패 확인**

Run: `cd "G:/내 드라이브/Claude/주식/기업추적" && python -m pytest tests/test_druck.py -q`
Expected: FAIL (`KeyError: '매출액_전'` 등)

- [ ] **Step 3: `재무.py` — 일시 오류 표시**

`fetch_statement` 의 네트워크 부분을 바꾼다(`재무.py:195-207`):
```python
    try:
        r = requests.get(DART + "/fnlttSinglAcntAll.json", timeout=90, params={
            "crtfc_key": API_KEY, "corp_code": corp_code, "bsns_year": str(year),
            "reprt_code": reprt_code, "fs_div": fs_div})
        r.raise_for_status()
        js = r.json()
    except Exception:
        # 네트워크 · HTTP 오류 — 본문으로 대신하지 않는다. 받는 쪽(드러켄밀러)이 이 빌드를 캐시하지 않게 표시만 단다
        return {"status": "net", "list": [], "transient": True}
    data = {"status": js.get("status"), "list": js.get("list") or []}
    # 정상(000)과 '데이터 없음'(013)만 캐시한다. 한도 초과(020)·점검중(800) 같은
    # 일시 오류를 캐시하면 그 해는 영영 빈 채로 남는다.
    if data["status"] in ("000", "013"):
        with open(cache, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
    else:
        # 일시 오류는 본문으로 대신하지 않는다(대신하면 받는 쪽이 오류를 못 본다 — 2026-10-09)
        time.sleep(0.25)
        return dict(data, transient=True)
    time.sleep(0.25)
    return _or_body(data, corp_code, year, reprt_code, fs_div)
```

- [ ] **Step 4: `드러켄밀러.py` — IS_PICK · `_grab` · `period_data`**

IS_PICK 에 지배순이익을 더한다(`드러켄밀러.py:38-46` 안):
```python
    "지배순이익": (["ifrs-full_ProfitLossAttributableToOwnersOfParent"], r"^(지배기업\s*)?(소유주|지배주주|지배기업).*(지분|순이익|귀속)"),
```
`period_data` 를 바꾼다:
```python
NET = {"budget": None, "used": 0}   # offline 빌드의 네트워크 예산 — 캐시 파일이 없을 때만 센다


def _fetch(corp_code, year, reprt, fs_div, offline):
    if offline:
        path = os.path.join(FIN.FIN_DIR, "%s_%s_%s_%s.json" % (corp_code, year, reprt, fs_div))
        if not os.path.exists(path):
            if NET["budget"] is not None and NET["used"] >= NET["budget"]:
                return {"status": "budget", "list": [], "transient": True}
            NET["used"] += 1
    return FIN.fetch_statement(corp_code, year, reprt, fs_div)


def period_data(corp_code, year, q, offline=False):
    """한 분기의 원장 — 그 보고서의 값(thstrm) · 누적(thstrm_add) · 비교기간(frmtrm_q · frmtrm_add · frmtrm) · 기준(CFS/OFS) · 출처 · rcept.
    4분기 단독은 series() 에서 연간 − 3분기 누적으로 뗀다."""
    reprt = REPRT_BY_Q[q]
    st = _fetch(corp_code, year, reprt, "CFS", offline)
    if st.get("transient"):
        return {"_transient": True}
    rows, fs = st.get("list") or [], "CFS"
    if not rows:
        st = _fetch(corp_code, year, reprt, "OFS", offline)
        if st.get("transient"):
            return {"_transient": True}
        rows, fs = st.get("list") or [], "OFS"
    if not rows:
        return None
    d = {}
    d.update(_grab(rows, ("IS", "CIS"), IS_PICK, "thstrm_amount"))
    d.update(_grab(rows, ("BS",), BS_PICK, "thstrm_amount"))
    for fld, suf in (("thstrm_add_amount", "_누적"), ("frmtrm_q_amount", "_전"), ("frmtrm_add_amount", "_전누적"), ("frmtrm_amount", "_전연")):
        for k, v in _grab(rows, ("IS", "CIS"), IS_PICK, fld).items():
            d[k + suf] = v
    if q == 1:
        for k in IS_PICK:
            if d.get(k + "_전") is None and d.get(k + "_전누적") is not None:
                d[k + "_전"] = d[k + "_전누적"]
    if q != 4:                              # 분기 · 반기 보고서의 frmtrm_amount 는 대개 없고, 있으면 누적값이다 — 쓰지 않는다
        for k in IS_PICK:
            d.pop(k + "_전연", None)
    cx = _capex(rows)
    if cx is not None:
        d["CAPEX"] = cx
    if not any(not k.startswith("_") for k in d):
        return None
    rc = [str(r.get("rcept_no") or "")[:8] for r in rows if r.get("rcept_no")]
    d.update(_fs=fs, _src="body" if st.get("status") == "body" else "api", _rcept=max(rc) if rc else None, _transient=False)
    return d
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `python -m pytest tests/test_druck.py -q`
Expected: 5 passed

- [ ] **Step 6: 커밋**
```bash
git add 재무.py 드러켄밀러.py tests/test_druck.py
git commit -m "가속도 개편 1: 재무 일시 오류 표시 · 분기 원장에 비교기간 · 기준 · rcept · 지배순이익"
```

---

### Task 2: `series()` v2 — 분기 키 조밀 격자 · Q4 기준/범위 · 재작성 비교 · 기준일 · 이상값 · 결산월

**Files:**
- Modify: `드러켄밀러.py:119-219` (`series`)
- Test: `tests/test_druck.py`

**Interfaces:**
- Consumes: `period_data()` (Task 1).
- Produces: `DRK.VERSION = 2`.
- Produces: `DRK.series(corp, code, years, prices=None, meta=None, offline=False) -> list[dict]` — n 오름차순 조밀 격자(첫 자료 분기 ~ 끝 자료 분기, 빈 분기 포함).
  `meta = {"filed": {n: "YYYYMMDD"}, "fy_bad": set(years), "fin": bool}`(없으면 빈 값).
  점 키: `year · q · label · n · 매출액 · 영업이익 · 당기순이익 · 지배순이익 · EPS · 재고자산 · 매출채권 · 유형자산 · 자본총계 · CAPEX(분기) ·
  매출YoY · 영업이익YoY · 영업이익률 · 이익률_비정상 · 매출가속 · 영업이익가속 · 이익률변화 · 매출_TTM · 영업이익_TTM · 재고일수 · 매출채권일수 · CAPEX강도 ·
  YoY_r · 영업이익YoY_r · 기준일 · fs · 품질(list)`. 리스트 객체에 속성처럼 못 붙이므로 회사 단위 결과는 `DRK.LAST = {"transient": int, "fy_bad": [...]}` 에 둔다.

- [ ] **Step 1: 실패하는 테스트** (`tests/test_druck.py` 끝에 덧붙임)
```python
def mk_q(rev, cum=None, prev=None, prev_cum=None, prev_ann=None, rc="20240514", fs="CFS", src="api", op=None, ni=None):
    d = {"매출액": rev, "_fs": fs, "_src": src, "_rcept": rc, "_transient": False}
    if cum is not None: d["매출액_누적"] = cum
    if prev is not None: d["매출액_전"] = prev
    if prev_cum is not None: d["매출액_전누적"] = prev_cum
    if prev_ann is not None: d["매출액_전연"] = prev_ann
    if op is not None: d["영업이익"] = op
    if ni is not None: d["지배순이익"] = ni
    return d


def run_series(monkeypatch, table, years, meta=None):
    monkeypatch.setattr(DRK, "period_data", lambda corp, y, q, offline=False: table.get((y, q)))
    return DRK.series("C", "000000", years, meta=meta or {})


def test_gap_quarter_dense_grid(monkeypatch):
    t = {(2023, 1): mk_q(100), (2023, 2): mk_q(110), (2023, 4): None, (2023, 3): mk_q(120), (2024, 1): mk_q(130, prev=100)}
    pts = run_series(monkeypatch, t, [2023, 2024])
    assert [p["label"] for p in pts] == ["2023Q1", "2023Q2", "2023Q3", "2023Q4", "2024Q1"]
    assert pts[3].get("매출액") is None and "gap" in pts[3]["품질"]
    assert pts[4]["매출_TTM"] is None             # 창 안에 빈 분기 — TTM 안 냄


def test_q4_basis_mismatch(monkeypatch):
    t = {(2020, 3): mk_q(70, cum=7233, fs="CFS"), (2020, 4): mk_q(1566, prev_ann=1660, fs="OFS")}
    pts = run_series(monkeypatch, t, [2020])
    q4 = [p for p in pts if p["q"] == 4][0]
    assert q4["매출액"] is None and "basis" in q4["품질"]


def test_q4_scope_restated(monkeypatch):
    # DL 2020: 사업보고서 frmtrm/전년 사업보고서 thstrm = 0.171, Q3 frmtrm_add/전년 Q3 thstrm_add = 0.978 → 범위가 다름
    t = {(2019, 3): mk_q(2400, cum=6956), (2019, 4): mk_q(9700),
         (2020, 3): mk_q(2300, cum=7233, prev_cum=6803), (2020, 4): mk_q(1566, prev_ann=1660)}
    pts = run_series(monkeypatch, t, [2019, 2020])
    q4 = [p for p in pts if p["label"] == "2020Q4"][0]
    assert q4["매출액"] is None and "basis" in q4["품질"]


def test_restated_yoy_and_amended(monkeypatch):
    t = {(2023, 2): mk_q(100), (2024, 2): mk_q(130, prev=104, rc="20241020")}
    pts = run_series(monkeypatch, t, [2023, 2024], meta={"filed": {2024 * 4 + 1: "20240814"}})
    p = [x for x in pts if x["label"] == "2024Q2"][0]
    assert round(p["YoY_r"], 4) == round((130 / 104 - 1) * 100, 4)
    assert round(p["매출YoY"], 4) == 30.0          # 공시 당시 값끼리(이름 · 뜻 유지)
    assert p["기준일"] == "20241020" and "amended" in p["품질"]


def test_negative_and_dup_past_only(monkeypatch):
    t = {(2024, 1): mk_q(100), (2024, 2): mk_q(100), (2024, 3): mk_q(-5)}
    pts = run_series(monkeypatch, t, [2024])
    q2 = [p for p in pts if p["label"] == "2024Q2"][0]; q3 = [p for p in pts if p["label"] == "2024Q3"][0]
    assert q2["매출액"] is None and "dup" in q2["품질"]
    assert q3["매출액"] is None and "neg" in q3["품질"]


def test_fy_bad_year_excluded(monkeypatch):
    t = {(2015, 1): mk_q(100), (2015, 2): mk_q(110)}
    pts = run_series(monkeypatch, t, [2015], meta={"fy_bad": {2015}})
    assert all(p.get("매출액") is None and "fy" in p["품질"] for p in pts)


def test_latest_year_without_annual(monkeypatch):
    t = {(2025, 1): mk_q(100), (2025, 2): mk_q(100), (2025, 3): mk_q(100, cum=300), (2025, 4): mk_q(420),
         (2026, 1): mk_q(120, prev=100), (2026, 2): mk_q(130, prev=101)}
    pts = run_series(monkeypatch, t, [2025, 2026])
    last = pts[-1]
    assert last["label"] == "2026Q2" and last["매출액"] == 130 and last["YoY_r"] is not None
```

- [ ] **Step 2: 실패 확인** — Run: `python -m pytest tests/test_druck.py -q` → 새 테스트 FAIL.

- [ ] **Step 3: 구현** — `series()` 를 아래로 바꾼다(`드러켄밀러.py`, 함수 전체 교체 · `VERSION` · `LAST` 상수는 파일 위쪽 `CACHE_DIR` 아래에):
```python
VERSION = 2          # 2: 분기 키 · 재작성 비교 · 기준일 · 품질 · 분할 보정 EPS · B(2026-10-09). 계산을 바꾸면 올린다 — 캐시가 전부 다시 계산된다
LAST = {"transient": 0, "fy_bad": []}
KEYS_IS = ("매출액", "영업이익", "당기순이익", "지배순이익", "EPS")


def _n(y, q):
    return y * 4 + q - 1


def series(corp_code, stock_code, years, prices=None, meta=None, offline=False):
    """분기 시계열 v2 — n 오름차순 조밀 격자. meta = {filed: {n: 원본 공시일}, fy_bad: {연도}, fin: bool}."""
    meta = meta or {}
    filed, fy_bad = meta.get("filed") or {}, set(meta.get("fy_bad") or ())
    LAST.update(transient=0, fy_bad=sorted(fy_bad))
    raw = {}
    for y in years:
        for q in (1, 2, 3, 4):
            try:
                d = period_data(corp_code, y, q, offline=offline)
            except Exception:
                d = {"_transient": True}
            if d and d.get("_transient"):
                LAST["transient"] += 1
                continue
            if d:
                raw[_n(y, q)] = d
    if not raw:
        return []
    n0, n1 = min(raw), max(raw)
    pts = []
    for n in range(n0, n1 + 1):
        y, q = n // 4, n % 4 + 1
        p = {"year": y, "q": q, "label": "%dQ%d" % (y, q), "n": n, "품질": []}
        d = raw.get(n)
        if y in fy_bad:
            p["품질"].append("fy")
            d = None
        if d is None:
            if "fy" not in p["품질"]:
                p["품질"].append("gap")
            pts.append(p)
            continue
        p["fs"] = d.get("_fs")
        if q != 4:
            for k in KEYS_IS:
                p[k] = d.get(k)
                p[k + "_전"] = d.get(k + "_전")
        else:
            q3 = raw.get(n - 1) or {}
            same_fs = q3.get("_fs") == d.get("_fs")
            # 범위 검사 — 사업보고서 비교연도 ÷ 전년 사업보고서, Q3 비교 누적 ÷ 전년 Q3 누적 이 2% 넘게 다르면 연말 재작성
            pa, p3 = raw.get(n - 4) or {}, raw.get(n - 5) or {}
            scope_ok = True
            ra = (d.get("매출액_전연") / pa["매출액"]) if d.get("매출액_전연") and pa.get("매출액") else None
            r3 = (q3.get("매출액_전누적") / p3["매출액_누적"]) if q3.get("매출액_전누적") and p3.get("매출액_누적") else None
            if ra is not None and r3 is not None and abs(ra / r3 - 1) > 0.02:
                scope_ok = False
            for k in KEYS_IS:
                ann, cum9 = d.get(k), q3.get(k + "_누적")
                ok = same_fs and scope_ok and ann is not None and cum9 is not None
                p[k] = (ann - cum9) if ok else None
                pa_, pc_ = d.get(k + "_전연"), q3.get(k + "_전누적")
                p[k + "_전"] = (pa_ - pc_) if (ok and pa_ is not None and pc_ is not None) else None
            if d.get("매출액") is not None and p.get("매출액") is None:
                p["품질"].append("basis")
        for k in ("재고자산", "매출채권", "유형자산", "자본총계"):
            p[k] = d.get(k)
        cx, cx_prev = d.get("CAPEX"), (raw.get(n - 1) or {}).get("CAPEX") if q != 1 else 0
        p["CAPEX"] = (cx - cx_prev) if (cx is not None and cx_prev is not None) else None
        f0 = filed.get(n)
        rc = d.get("_rcept")
        p["기준일"] = max(x for x in (f0, rc) if x) if (f0 or rc) else None
        if f0 and rc and rc > f0:
            p["품질"].append("amended")
        pts.append(p)
    by = {p["n"]: p for p in pts}
    # 이상값 — 그 분기와 앞 분기들만 본다
    for p in pts:
        v = p.get("매출액")
        if v is None:
            continue
        prev = by.get(p["n"] - 1) or {}
        hist = [by[m]["매출액"] for m in range(p["n"] - 4, p["n"]) if m in by and by[m].get("매출액")]
        med = sorted(hist)[len(hist) // 2] if hist else None
        if v <= 0 or (med is not None and med > 0 and v < 0):
            p["매출액"] = None; p["품질"].append("neg")
        elif prev.get("매출액") is not None and prev["매출액"] == v:
            p["매출액"] = None; p["품질"].append("dup")
    # 전년 대비 — 공시 당시(매출YoY) · 재작성(YoY_r)
    for p in pts:
        b = by.get(p["n"] - 4) or {}
        for k, tag in (("매출액", "매출"), ("영업이익", "영업이익")):
            a, v = b.get(k), p.get(k)
            p[tag + "YoY"] = None
            if a is not None and v is not None and a > 0:
                if tag == "영업이익" and b.get("매출액") and a < b["매출액"] * 0.01:
                    p[tag + "YoY_무의미"] = True
                else:
                    p[tag + "YoY"] = (v - a) / abs(a) * 100
            pr = p.get(k + "_전")
            key_r = "YoY_r" if tag == "매출" else "영업이익YoY_r"
            p[key_r] = (v - pr) / abs(pr) * 100 if (v is not None and pr is not None and pr > 0) else None
        if p.get("매출액") and p.get("영업이익") is not None:
            p["영업이익률"] = p["영업이익"] / p["매출액"] * 100
            if abs(p["영업이익률"]) > 100:
                p["이익률_비정상"] = True
    for p in pts:
        prev = by.get(p["n"] - 1) or {}
        for tag in ("매출", "영업이익"):
            a, b_ = p.get(tag + "YoY"), prev.get(tag + "YoY")
            p[tag + "가속"] = (a - b_) if (a is not None and b_ is not None) else None
        p["이익률변화"] = (p["영업이익률"] - prev["영업이익률"]) if (p.get("영업이익률") is not None and prev.get("영업이익률") is not None) else None
    # TTM · 회전일수 · CAPEX 강도 — 연속 네 분기(키)일 때만
    for p in pts:
        win = [by.get(m) or {} for m in range(p["n"] - 3, p["n"] + 1)]
        p["매출_TTM"] = sum(w["매출액"] for w in win) if all(w.get("매출액") for w in win) else None
        p["영업이익_TTM"] = sum(w["영업이익"] for w in win) if all(w.get("영업이익") is not None for w in win) else None
        if p["매출_TTM"] and len({w.get("fs") for w in win}) > 1:
            p["품질"].append("basis")
        daily = p["매출_TTM"] / 365.0 if p["매출_TTM"] else None
        p["재고일수"] = (p["재고자산"] / daily) if (daily and p.get("재고자산")) else None
        p["매출채권일수"] = (p["매출채권"] / daily) if (daily and p.get("매출채권")) else None
        cw = [w.get("CAPEX") for w in win]
        p["CAPEX강도"] = (sum(cw) / p["매출_TTM"] * 100) if (p["매출_TTM"] and all(c is not None for c in cw)) else None
    for p in pts:
        p["품질"] = sorted(set(p["품질"]))
    return pts
```
`LAST["fy_bad"]` 는 meta 를 그대로 옮긴다. `attach_prices` 는 그대로 둔다(빈 분기는 dates 에 없어 건너뜀).

- [ ] **Step 4: 통과 확인** — Run: `python -m pytest tests/test_druck.py -q` → 12 passed

- [ ] **Step 5: 커밋**
```bash
git add 드러켄밀러.py tests/test_druck.py
git commit -m "가속도 개편 2: series v2 — 분기 키 격자 · Q4 기준/범위 · 재작성 전년 비교 · 기준일 · 이상값 · 결산월"
```

---

### Task 3: `accel()` — B · 7국면 · 변곡 · 엇갈림 · mix, 국면 판정 공용화

**Files:**
- Modify: `드러켄밀러.py` (끝에 `PHASE_*`, `phase_label`, `accel`)
- Modify: `산업.py:540-575` (`PHASE_*` · `_phase` 가 공용 함수 사용)
- Test: `tests/test_druck.py`

**Interfaces:**
- Consumes: `series()` 점(Task 2).
- Produces: `DRK.PHASE_BAND = 3.0`, `DRK.PHASE_FLAT = 2.0`, `DRK.PHASE_NAME`(dict), `DRK.phase_label(speed, accel) -> str`.
- Produces: `DRK.accel(pts, basis="매출") -> pts`(제자리 수정, 같은 리스트 반환). 점에 `Y · Y_asfiled · 속도 · 가속B · C · 국면 · 변곡('▲'|'▼'|None) · 엇갈림(bool) · B기준일`, 품질에 `asfiled` · `mix`.
  `basis='영업이익'` 이면 Y 는 영업이익 YoY(전년 값 양수 · 최근 4분기 평균 |영업이익| 의 20% 이상일 때만).

- [ ] **Step 1: 실패하는 테스트**
```python
def grid(yoys, start=(2024, 1)):
    """yoys: 분기마다 (재작성 YoY_r, 공시 당시 매출YoY) — 하나만 주면 둘 다 같은 값."""
    y0, q0 = start; out = []
    for i, v in enumerate(yoys):
        n = y0 * 4 + q0 - 1 + i
        r, a = (v if isinstance(v, tuple) else (v, v))
        out.append({"n": n, "year": n // 4, "q": n % 4 + 1, "label": "%dQ%d" % (n // 4, n % 4 + 1), "YoY_r": r, "매출YoY": a, "품질": [], "기준일": "20240101"})
    return out


def test_b_definition():
    pts = DRK.accel(grid([10, 20, 30, 50]))
    # s(n) = (Y(n)+Y(n-1))/2 ; B(n) = s(n) - s(n-2)
    assert pts[3]["속도"] == 40 and pts[3]["가속B"] == 40 - 15


def test_phase_labels_and_flat():
    assert DRK.phase_label(10, 4) == "확장 가속" and DRK.phase_label(10, 0) == "확장 유지" and DRK.phase_label(10, -4) == "둔화"
    assert DRK.phase_label(-10, 4) == "회복" and DRK.phase_label(-10, 0) == "부진 지속" and DRK.phase_label(-10, -4) == "수축 심화"
    assert DRK.phase_label(1, 1) == "정체"


def test_turn_through_flat_band():
    # 삼성 모양: B ... −6.2 → +10.9(▲) → +41.7(같은 쪽 — 변곡 아님)
    pts = grid([0] * 8)
    Bs = [None, None, None, -9.2, -6.2, 10.9, 41.7, 1.0]
    for p, b in zip(pts, Bs):
        p["가속B"] = b
    DRK._turns(pts)
    assert [p["변곡"] for p in pts][4:7] == [None, "▲", None]


def test_turn_needs_within_4():
    pts = grid([0] * 8)
    for p, b in zip(pts, [-5, 1, 1, 1, 1, 6, None, None]):
        p["가속B"] = b
    DRK._turns(pts)
    assert pts[5]["변곡"] is None        # 반대쪽 띠 밖 값이 5분기 앞 — 변곡 아님


def test_divergence_only_outside_band():
    pts = DRK.accel(grid([0, 10, 20, 40, 15]))
    last = pts[-1]
    # B(last) = s(4) - s(2) = 27.5 - 15 = 12.5 > 3, C = 15 - 40 = -25 → 엇갈림
    assert last["가속B"] == 12.5 and last["C"] == -25 and last["엇갈림"] is True
    same = DRK.accel(grid([10, 10, 10, 10, 2]))
    assert same[-1]["가속B"] == -4 and same[-1]["C"] == -8 and same[-1]["엇갈림"] is False   # B · C 같은 부호
    inband = DRK.accel(grid([10, 10, 10, 12, 4]))
    assert abs(inband[-1]["가속B"]) < 3 and inband[-1]["엇갈림"] is False                  # 띠 안이면 방향이 없어 엇갈림도 없음


def test_mix_window_falls_back_to_asfiled():
    pts = DRK.accel(grid([(None, 5), (None, 6), (10, 7), (12, 8)]))
    last = pts[-1]
    assert "mix" in last["품질"] and last["가속B"] == ((8 + 7) / 2) - ((6 + 5) / 2)


def test_short_history_no_phase():
    pts = DRK.accel(grid([10, 12]))
    assert all(p["국면"] is None for p in pts)


def test_op_basis_small_base_skipped():
    pts = grid([0] * 6)
    ops = [2, 100, 100, 100, 50, 120]      # pts[4] 의 1년 전 기저 2 는 직전 4분기 평균 |영업이익| 75.5 의 20% 미만 — YoY 안 씀
    for p, o in zip(pts, ops):
        p["영업이익"] = o
    for p in pts:
        b = next((x for x in pts if x["n"] == p["n"] - 4), None)
        p["영업이익YoY_r"] = (p["영업이익"] / b["영업이익"] - 1) * 100 if b else None
        p["영업이익YoY"] = p["영업이익YoY_r"]
    DRK.accel(pts, basis="영업이익")
    assert pts[4]["Y"] is None
    assert round(pts[5]["Y"], 6) == 20.0
```
(`test_divergence_only_outside_band` 의 둘째 경우: Y=[10,10,10,10,2] → s(4)=6, s(2)=10, B=−4(띠 밖), C=−8(같은 부호) → 엇갈림 False.)

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_druck.py -q` → FAIL(`AttributeError: accel`).

- [ ] **Step 3: 구현** (`드러켄밀러.py` 끝에 덧붙임)
```python
# ---------------------------------------------------------------- 가속(B) · 국면 — 산업 업황 시계와 같은 식 · 같은 이름(2026-10-09)
PHASE_BAND = 3.0      # %p — 가속이 이 안이면 '유지'
PHASE_FLAT = 2.0      # % — 속도가 이 안이고 가속도 '유지'면 '정체'
PHASE_NAME = {(True, 1): "확장 가속", (True, 0): "확장 유지", (True, -1): "둔화",
              (False, 1): "회복", (False, 0): "부진 지속", (False, -1): "수축 심화"}


def phase_label(speed, acc):
    band = 1 if acc >= PHASE_BAND else -1 if acc <= -PHASE_BAND else 0
    if band == 0 and abs(speed) < PHASE_FLAT:
        return "정체"
    return PHASE_NAME[(speed > 0, band)]


def _turns(pts):
    """|B(n)| ≥ 띠 이고, n 앞 가장 가까운 |B| ≥ 띠 분기 m 이 반대 부호 · n − m ≤ 4 이면 ▲/▼."""
    last = None                      # (n, sign) — 가장 최근 띠 밖 분기
    for p in pts:
        b = p.get("가속B")
        p["변곡"] = None
        if b is None or abs(b) < PHASE_BAND:
            continue
        s = 1 if b > 0 else -1
        if last and last[1] != s and p["n"] - last[0] <= 4:
            p["변곡"] = "▲" if s > 0 else "▼"
        last = (p["n"], s)
    return pts


def accel(pts, basis="매출"):
    by = {p["n"]: p for p in pts}
    for p in pts:
        p.setdefault("품질", [])
        if basis == "영업이익":
            hist = [abs(by[m]["영업이익"]) for m in range(p["n"] - 4, p["n"]) if m in by and by[m].get("영업이익") is not None]
            base = (by.get(p["n"] - 4) or {}).get("영업이익")
            ok = base is not None and base > 0 and hist and base >= 0.2 * (sum(hist) / len(hist))
            r, a = (p.get("영업이익YoY_r"), p.get("영업이익YoY")) if ok else (None, None)
        else:
            r, a = p.get("YoY_r"), p.get("매출YoY")
        p["Y_asfiled"] = a
        if r is not None:
            p["Y"] = r
        else:
            p["Y"] = a
            if a is not None:
                p["품질"].append("asfiled")
    for p in pts:
        n = p["n"]
        w = [by.get(m) for m in range(n - 3, n + 1)]
        p["속도"] = p["가속B"] = p["C"] = p["국면"] = p["B기준일"] = None
        p["엇갈림"] = False
        if all(x is not None for x in w) and all(x.get("Y") is not None for x in w):
            ys = [x["Y"] for x in w]
            kinds = {"asfiled" in x["품질"] for x in w}
            if len(kinds) > 1:
                alt = [x.get("Y_asfiled") for x in w]
                if all(v is not None for v in alt):
                    ys = alt
                    p["품질"].append("mix")
                else:
                    ys = None
            if ys:
                s, s2 = (ys[3] + ys[2]) / 2, (ys[1] + ys[0]) / 2
                p["속도"], p["가속B"] = s, s - s2
                p["국면"] = phase_label(s, s - s2)
                dates = [x.get("기준일") for x in w if x.get("기준일")]
                p["B기준일"] = max(dates) if dates else None
        prev = by.get(n - 1)
        if prev and p.get("Y") is not None and prev.get("Y") is not None:
            p["C"] = p["Y"] - prev["Y"]
        b, c = p.get("가속B"), p.get("C")
        p["엇갈림"] = bool(b is not None and c is not None and abs(b) >= PHASE_BAND and abs(c) >= 5 and (b > 0) != (c > 0))
    _turns(pts)
    for p in pts:
        p["품질"] = sorted(set(p["품질"]))
    return pts
```
`산업.py:540-575` — 상수 세 줄을 `from 드러켄밀러 import PHASE_BAND, PHASE_FLAT, PHASE_NAME, phase_label  # noqa: E402` 로 바꾸고 `_phase` 의 판정 두 줄을 공용 함수로:
```python
    band = 1 if ac >= PHASE_BAND else -1 if ac <= -PHASE_BAND else 0
    n = len(ys)
    label = phase_label(sp, ac)
```
(산업.py 위쪽 `sys.path` 에 BASE 가 없으면 `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` 를 import 앞에 둔다.)

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_druck.py -q` → 전부 PASS. 산업 확인: `python -c "import 산업; print(산업._phase([{'q':'a','rev_yoy':5},{'q':'b','rev_yoy':5},{'q':'c','rev_yoy':10},{'q':'d','rev_yoy':12}])['label'])"` → `확장 가속`

- [ ] **Step 5: 커밋**
```bash
git add 드러켄밀러.py 산업.py tests/test_druck.py
git commit -m "가속도 개편 3: accel — B · 7국면(업황 시계 공용 판정) · 띠를 건너는 변곡 · 엇갈림 · 재작성/공시 당시 섞임"
```

---

### Task 4: 분기 주식 수 · 분할 보정 EPS — `share_basis()` 공용화

**Files:**
- Modify: `드러켄밀러.py` (끝에 `SHEV_ADJ` · `SHEV_MIX` · `share_basis` · `per_share`)
- Modify: `서버.py:3764-3765`(`SHEV_*` 를 `DRK.SHEV_*` 로), `서버.py` `_pipe_rows` 의 분할 블록(`sh = {...}` 부터 `sh_now = ...` 까지)
- Test: `tests/test_druck.py`, `도구/가속도_점검.py`(새 — `_pipe_rows` 전후 비교)

**Interfaces:**
- Produces: `DRK.share_basis(sh: dict[label, float], sev: list[tuple[str, str]], cnt=None) -> dict` → `{"now": {label: 지금 기준 주식 수}, "splits": [...], "cut": n|None}`. label 형식은 `YYYY?Q`(5번째 글자 = 분기 숫자, `2026Q2` · `2026.2Q` 둘 다).
  규칙은 `_pipe_rows` 와 같다(한 분기 튐 제거 · 1.8/0.56 · 공시 확인 시 1.25/0.8 · 증자 섞임 cut · `cnt(label)` 은 회사의 개요 낱말 수 콜백, 없으면 정수 비율만).
- Produces: `DRK.per_share(pts, sev, cnt=None) -> pts` — 점에 `주식수 · EPS_adj · EPS_TTM · EPS_TTM_raw`, 단위 오류 품질 `unit`. `attach_prices` 가 `PER_TTM` 을 `EPS_TTM`(보정) 으로 계산하므로 순서는 `series → per_share → accel → attach_prices`.

- [ ] **Step 1: 실패하는 테스트**
```python
def test_share_basis_mid_year_split():
    # LS일렉트릭: 2026Q1 까지 약 2,940만 주, 2026Q2 부터 1.47억 주(5:1)
    sh = {"2025Q3": 29.4e6, "2025Q4": 29.4e6, "2026Q1": 29.4e6, "2026Q2": 147e6}
    out = DRK.share_basis(sh, [("20260410", "주식분할결정")])
    assert abs(out["now"]["2026Q1"] - 147e6) < 1 and abs(out["now"]["2026Q2"] - 147e6) < 1
    assert out["splits"][0]["kind"].startswith("분할")


def test_share_basis_one_quarter_spike_dropped():
    sh = {"2024Q1": 10e6, "2024Q2": 210e6, "2024Q3": 10e6}
    out = DRK.share_basis(sh, [])
    assert "2024Q2" not in out["now"] and not out["splits"]


def test_per_share_eps_ttm_same_basis():
    pts = grid([0] * 4, start=(2025, 3))
    ni = [131e8, 164e8, 1190e8, 1158e8]
    eps = [447, 560, 4052, 797]                  # 앞 세 분기는 분할 전 기준(약 2,930만 주), 2026Q2 만 새 기준(약 1.45억 주)
    for p, a, b in zip(pts, ni, eps):
        p["지배순이익"], p["EPS"], p["매출액"] = a, b, 1e12
    DRK.per_share(pts, [("20260410", "주식분할결정")])
    last = pts[-1]
    want = sum(p["지배순이익"] for p in pts) / 145.3e6      # 네 분기 모두 지금 주식 수로
    assert abs(last["EPS_TTM"] / want - 1) < 0.05
    assert last["EPS_TTM_raw"] == sum(eps)                  # 원래 합(기준 섞임)은 따로 남는다


def test_per_share_unit_error():
    pts = grid([0] * 5)
    for p in pts:
        p["지배순이익"], p["EPS"], p["매출액"] = 100e8, 1000, 1e12
    pts[2]["EPS"] = 1000 * 1e6
    DRK.per_share(pts, [])
    assert "unit" in pts[2]["품질"] and abs(pts[2]["EPS_adj"] - 1000) < 1
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_druck.py -q` → FAIL.

- [ ] **Step 3: 구현** — `_pipe_rows`(서버.py) 의 `sh` 튐 제거 · `events_between` · `split_like` · `fac` 루프 · `sh_now` 를 그대로 옮긴 `share_basis` 를 `드러켄밀러.py` 에 둔다:
```python
import datetime as _dt
SHEV_ADJ = re.compile(r"무상증자결정|유무상증자결정|주식분할결정|주식병합결정|감자결정")     # 주가 자료(수정주가)도 같이 보정되는 사건
SHEV_MIX = re.compile(r"회사합병결정|유상증자결정|주식교환|분할합병")                      # 주가 보정 없이 주식 수만 바뀌는 사건


def _qn(k):
    return int(k[:4]) * 4 + int(k[5])


def _qend(lab):
    return int("%s%s" % (lab[:4], {1: "0331", 2: "0630", 3: "0930", 4: "1231"}[int(lab[5])]))


def share_basis(sh, sev, cnt=None):
    """분기별 역산 주식 수 → 지금 기준 주식 수. 서버 _pipe_rows 와 가속도가 같이 쓴다(규칙 설명은 _pipe_rows 주석 그대로)."""
    sh = dict(sh)
    ks = sorted(sh, key=_qn)
    for i in range(1, len(ks) - 1):
        a_, b_, c_ = sh.get(ks[i - 1]), sh.get(ks[i]), sh.get(ks[i + 1])
        if a_ and b_ and c_ and not (0.56 < b_ / a_ < 1.8) and 0.8 <= c_ / a_ <= 1.25:
            sh.pop(ks[i], None)
    ks = [k for k in ks if k in sh]

    def events_between(after, at):
        lo = int((_dt.datetime.strptime(str(_qend(after)), "%Y%m%d") - _dt.timedelta(days=90)).strftime("%Y%m%d"))
        hi = _qend(at)
        ev = [nm for d_, nm in (sev or []) if d_ and lo <= int(d_) <= hi]
        return [x for x in ev if SHEV_ADJ.search(x)], [x for x in ev if SHEV_MIX.search(x)]

    def split_like(after, at, r_):
        adj_, _mix = events_between(after, at)
        if adj_:
            return True
        if cnt is not None:
            a_n, b_n = cnt(after), cnt(at)
            if a_n is not None and b_n is not None and b_n > a_n:
                return True
        k = r_ if r_ >= 1 else 1 / r_
        return k >= 4.5 and abs(k - round(k)) <= 0.15
    fac = {k: 1.0 for k in ks}
    splits, cut = [], None
    for a, b in zip(ks, ks[1:]):
        r_ = sh[b] / sh[a]
        adj_, mix_ = events_between(a, b) if (r_ >= 1.25 or r_ <= 0.8) else ([], [])
        if (r_ >= 1.8 or r_ <= 0.56) or adj_:
            kk = r_ if r_ >= 1 else 1 / r_
            if adj_:
                kind = "분할·병합"
                if mix_ and abs(kk - round(kk)) > 0.15:
                    kind = "분할·병합(증자 섞임 — 앞 기록 제외)"
                    cut = _qn(a) if cut is None else max(cut, _qn(a))
            else:
                kind = "분할·병합" if split_like(a, b, r_) else "증자 등(주가 보정 없음)"
            splits.append({"after": a, "at": b, "ratio": round(r_, 2), "kind": kind})
            if kind.startswith("분할·병합"):
                for k in ks:
                    if _qn(k) <= _qn(a):
                        fac[k] *= r_
    return {"now": {k: sh[k] * fac[k] for k in ks}, "splits": splits, "cut": cut}


def per_share(pts, sev, cnt=None):
    """분기 주식 수(지배순이익 ÷ EPS) → 지금 기준 EPS_adj · EPS_TTM(보정). 원래 합은 EPS_TTM_raw."""
    by = {p["n"]: p for p in pts}
    imp = {}
    for p in pts:
        ni, e = p.get("지배순이익") if p.get("지배순이익") is not None else p.get("당기순이익"), p.get("EPS")
        if ni and e and p.get("매출액") and abs(ni) >= abs(p["매출액"]) * 0.005 and ni / e > 0:
            imp[p["label"]] = ni / e
    if imp:
        med = sorted(imp.values())[len(imp) // 2]
        for lab, s in list(imp.items()):
            if s < med / 300 or s > med * 300:
                p = next(x for x in pts if x["label"] == lab)
                for div in (1e3, 1e6):
                    if med / 1.8 <= s * div <= med * 1.8:
                        p["EPS"] = p["EPS"] / div
                        imp[lab] = s * div
                        break
                else:
                    imp.pop(lab)
                p["품질"] = sorted(set(p.get("품질", []) + ["unit"]))
    now = share_basis(imp, sev, cnt)["now"] if imp else {}
    for p in pts:
        ni = p.get("지배순이익") if p.get("지배순이익") is not None else p.get("당기순이익")
        s = now.get(p["label"])
        if s is None and now:
            qk = p["year"] * 4 + p["q"]                       # _qn 과 같은 척도(연도×4 + 분기)
            near = min(now, key=lambda k: abs(_qn(k) - qk))
            s = now[near] if abs(_qn(near) - qk) <= 4 else None
        p["주식수"] = s
        p["EPS_adj"] = (ni / s) if (ni is not None and s) else None
    for p in pts:
        w = [by.get(m) or {} for m in range(p["n"] - 3, p["n"] + 1)]
        p["EPS_TTM_raw"] = sum(x["EPS"] for x in w) if all(x.get("EPS") is not None for x in w) else None
        p["EPS_TTM"] = sum(x["EPS_adj"] for x in w) if all(x.get("EPS_adj") is not None for x in w) else None
    return pts
```
`_qn` 은 label 의 5번째 글자를 분기로 읽는다 — `2026Q2` 는 `k[5]='2'`, `2026.2Q` 도 `k[5]='2'`(같은 규칙).

`서버.py` — `SHEV_ADJ = DRK.SHEV_ADJ` · `SHEV_MIX = DRK.SHEV_MIX` 로 바꾸고, `_pipe_rows` 의 블록을 다음으로 바꾼다:
```python
    sh = {lab: ni[lab] / eps[lab] for lab in labs if ni.get(lab) and eps.get(lab) and ni[lab] / eps[lab] > 0}
    sev = _share_events(c["code"])
    rx_ = re.compile(r"액면\s*분할|주식\s*분할|액면\s*병합|주식\s*병합|무상\s*증자")

    def cnt(lab):
        st_ = "%s-%02d" % (lab[:4], int(lab[5]) * 3)
        rep = next((r for r in c["reports"] if r["stamp"] == st_ and not r["tag"]), None)
        if not rep:
            return None
        return sum(len(rx_.findall(read_section(c, rep, sec["file"]))) for sec in rep["sections"] if "개요" in sec["title"])
    sb = DRK.share_basis(sh, sev, cnt)
    sh_now, splits, cut = sb["now"], sb["splits"], sb["cut"]
    qn = lambda k: int(k[:4]) * 4 + int(k[5])
```
(그 뒤 `for lab in labs:` 부터는 그대로.)

- [ ] **Step 4: `_pipe_rows` 전후 비교 스크립트** — `도구/가속도_점검.py`:
```python
# -*- coding: utf-8 -*-
"""가속도 개편 점검 — (pipe) _pipe_rows 분할 보정이 리팩터 앞뒤로 같은가 · (cases) 회귀 사례 · (api) 소비처 응답.
실행: python 도구/가속도_점검.py pipe --save before.json  /  python 도구/가속도_점검.py pipe --compare before.json"""
import os, sys, json, importlib.util as ilu
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
CODES = ["005930", "010120", "035720", "035420", "003550", "036800", "000210", "042370", "403870", "105560"]


def load_server():
    sp = ilu.spec_from_file_location("서버", os.path.join(BASE, "서버.py"))
    S = ilu.module_from_spec(sp); sp.loader.exec_module(S)
    S.load_index() if hasattr(S, "load_index") else None
    return S


def pipe(S):
    out = {}
    for code in CODES:
        c = S.company_by_code(code); corp = S.corp_code_of(code)
        if not c or not corp:
            continue
        mi = S.matrix_cached(c, corp, "IS", "q", S.IS_YEARS); mb = S.matrix_cached(c, corp, "BS", "q", S.QTR_YEARS)
        mc = S.matrix_cached(c, corp, "CF", "q", S.QTR_YEARS)
        pr = S._pipe_rows(c, mi, mb, mc, blog_pts=[])
        out[code] = {"splits": pr.get("splits"), "eps": {l: round((pr["rows"][l].get("eps_ttm") or 0), 4) for l in pr["labs"]}} if pr else None
    return out


if __name__ == "__main__":
    S = load_server()
    if sys.argv[1] == "pipe":
        res = pipe(S)
        if "--save" in sys.argv:
            json.dump(res, open(sys.argv[sys.argv.index("--save") + 1], "w", encoding="utf-8"), ensure_ascii=False)
        else:
            old = json.load(open(sys.argv[sys.argv.index("--compare") + 1], encoding="utf-8"))
            bad = [k for k in res if res[k] != old.get(k)]
            print("다름:", bad or "없음")
```
(`load_index` 이름은 서버.py 의 색인 적재 함수 이름에 맞춘다 — `grep -n "def load_index\|INDEX = " 서버.py` 로 확인해 그 함수를 부른다.)

- [ ] **Step 5: 확인** — 리팩터 **전에** `python 도구/가속도_점검.py pipe --save "C:/Users/lkh07/AppData/Local/Temp/claude/pipe_before.json"` 을 먼저 실행해 둔다(Step 3 앞에서). Step 3 뒤:
Run: `python -m pytest tests/test_druck.py -q` → PASS · `python 도구/가속도_점검.py pipe --compare "C:/Users/lkh07/AppData/Local/Temp/claude/pipe_before.json"` → `다름: 없음`

- [ ] **Step 6: 커밋**
```bash
git add 드러켄밀러.py 서버.py tests/test_druck.py 도구/가속도_점검.py
git commit -m "가속도 개편 4: 분기 주식 수 · 분할 보정 EPS — share_basis 를 드러켄밀러로 옮겨 _pipe_rows 와 같이 쓴다"
```

---

### Task 5: 서버 `druck()` v2 · `_druck_read()` · 백그라운드 · 지금 PER

**Files:**
- Modify: `서버.py:1461-1516` (`druck`), `서버.py:1830` (`DRUCK_BUILDING`), 라우트 `/api/druck`(`서버.py:9978` 부근)
- Test: `tests/test_druck_server.py`(새 — `_druck_read` 만 따로 떼어 시험)

**Interfaces:**
- Consumes: `DRK.series(meta=...)`, `DRK.per_share`, `DRK.accel`, `DRK.attach_prices`, `DRK.VERSION`, `DRK.LAST`.
- Produces: `druck(code, force=False, offline=False, wait=True) -> dict | None`. 캐시 `{v, sig, code, name, basis, fy, points, text, transient}`. `wait=False` 이고 캐시가 없으면 `{"building": True, "done": i, "total": n}`.
- Produces: `_druck_read(code) -> dict | None` — 파일의 `v == DRK.VERSION` 일 때만 반환(아니면 None).
- Produces: `/api/druck` 응답에 `now: {px, date, per, k}` (지금 PER, 캐시 안 함).

- [ ] **Step 1: 실패하는 테스트** — `tests/test_druck_server.py`:
```python
# -*- coding: utf-8 -*-
import os, sys, json, importlib.util as ilu
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("드러켄밀러", os.path.join(BASE, "드러켄밀러.py"))
DRK = ilu.module_from_spec(_sp); _sp.loader.exec_module(DRK)


def druck_read(path):
    """서버.py _druck_read 와 같은 규칙(서버를 띄우지 않고 시험하려고 같은 본문을 둔다)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        return None
    return d if d.get("v") == DRK.VERSION else None


def test_druck_read_rejects_old_version(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"sig": "abc", "points": []}), encoding="utf-8")
    assert druck_read(str(p)) is None
    p.write_text(json.dumps({"v": DRK.VERSION, "sig": "v2:abc", "points": [{"n": 1}]}), encoding="utf-8")
    assert druck_read(str(p))["points"] == [{"n": 1}]
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_druck_server.py -q` → (DRK.VERSION 이 Task 2 에 있으므로) 통과할 수도 있다. 이 테스트는 규칙 고정용 — 서버 함수가 같은 규칙인지는 Step 4 에서 라이브로 본다.

- [ ] **Step 3: 구현** — `druck()` 교체:
```python
DRUCK_BUILDING = {}           # code → {"done", "total"} — 백그라운드 계산 진행
DRUCK_LOCKS = {}
DRUCK_LOCKS_G = threading.Lock()


def _druck_path(code):
    return os.path.join(CACHE_DIR, "druck", code + ".json")


def _druck_read(code):
    """가속도 캐시(지금 VERSION 만). 옛 버전 · 깨진 파일은 None — 다시 계산 대상."""
    try:
        with open(_druck_path(code), "r", encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        return None
    return d if DRK is not None and d.get("v") == DRK.VERSION else None


def _druck_sig(c):
    rc = max((r["rcept"] for r in c["reports"]), default="")     # 정정 포함 — 옛 분기 정정도 다시 계산
    return "v%d:%s" % (DRK.VERSION, rc)


def _druck_meta(c):
    filed, fy_bad = {}, set()
    ok = {("분기보고서", "03"), ("반기보고서", "06"), ("분기보고서", "09"), ("사업보고서", "12")}
    for r in c["reports"]:
        y, mth = r["stamp"].split("-")
        if (r["label"], mth) not in ok:
            fy_bad.add(int(y))
            continue
        q = Q_OF_MONTH.get(mth)
        n = int(y) * 4 + q - 1
        if not r["tag"]:
            filed[n] = min(filed.get(n, "99999999"), rcept_dt_of(r))
    return {"filed": filed, "fy_bad": fy_bad}


def _druck_basis(code):
    """KSIC 64~66 이면서 매출액이 없는 회사만 영업이익 기준."""
    try:
        ksic = _ind_ksic(corp_code_of(code)) if "_ind_ksic" in globals() else ""
    except Exception:
        ksic = ""
    return "영업이익" if str(ksic).startswith(("64", "65", "66")) else "매출"


def druck(code, force=False, offline=False, wait=True):
    c = company_by_code(code)
    if not c:
        return None
    if DRK is None:
        return {"error": "가속도 모듈을 불러오지 못했습니다."}
    corp = corp_code_of(code)
    if not corp:
        return {"error": "DART 고유번호를 찾지 못했습니다."}
    sig = _druck_sig(c)
    old = _druck_read(code)
    if not force and old and old.get("sig") == sig:
        return old
    if not wait:
        with DRUCK_LOCKS_G:
            if code not in DRUCK_BUILDING:
                DRUCK_BUILDING[code] = {"done": 0, "total": 0}
                threading.Thread(target=druck, args=(code, force, offline, True), daemon=True).start()
        return {"building": True, **DRUCK_BUILDING.get(code, {})}
    with DRUCK_LOCKS_G:
        lk = DRUCK_LOCKS.setdefault(code, threading.Lock())
    with lk:
        old = _druck_read(code)
        if not force and old and old.get("sig") == sig:
            DRUCK_BUILDING.pop(code, None)
            return old
        meta = _druck_meta(c)
        years = sorted({int(r["stamp"][:4]) for r in c["reports"]})
        pts = DRK.series(corp, code, years, meta=meta, offline=offline)
        transient = DRK.LAST.get("transient", 0)
        DRK.per_share(pts, _share_events(code))
        basis = _druck_basis(code) if not any(p.get("매출액") for p in pts) else "매출"
        DRK.accel(pts, basis=basis)
        DRK.attach_prices(pts, code, {(p["year"], p["q"]): meta["filed"].get(p["n"]) for p in pts if meta["filed"].get(p["n"])})
        text_rows = []
        for r in c["reports"]:
            if r["tag"]:
                continue
            sec = next((s for s in r["sections"] if s["norm"] == "사업의 내용"), None)
            if not sec:
                continue
            found = DRK.scan_text_metrics(read_section(c, r, sec["file"]))
            if found:
                text_rows.append({"stamp": r["stamp"], "label": r["label"], "rcept": r["rcept"], "found": found})
        out = {"v": DRK.VERSION, "sig": sig, "code": code, "name": c["name"], "basis": basis,
               "fy": sorted(meta["fy_bad"]), "points": pts, "text": text_rows, "transient": transient}
        DRUCK_BUILDING.pop(code, None)
        if transient:
            return old or out              # 일시 오류가 낀 빌드는 캐시하지 않는다(예전 캐시 유지)
        path = _druck_path(code)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False)
        os.replace(tmp, path)
        return out
```
(`_ind_ksic` 가 없으면 `.cache/거시/induty.json` 을 읽는 작은 함수로: `json.load(open(os.path.join(CACHE_DIR, "거시", "induty.json"), encoding="utf-8")).get(corp, "")` — 한 번 읽어 전역에 둔다. `attach_prices` 는 `PER_TTM = 주가 / EPS_TTM` 이라 보정 EPS 로 계산된다.)

지금 PER — `/api/druck` 라우트(`res = druck(...)`) 를:
```python
            if path == "/api/druck":
                code_ = q.get("code", "")
                res = druck(code_, q.get("force") == "1", wait=False)
                if res and res.get("points"):
                    res = dict(res, now=_druck_now(code_, res))
                    _seen_note(code_) if "_seen_note" in globals() else None
```
그리고:
```python
def _druck_now(code, d):
    """지금 PER = 네이버 오늘 종가 ÷ (최신 EPS_TTM ÷ k). k = 캐시의 마지막 주가 ÷ 지금 받은 수정주가의 같은 날 종가(분할이 생기면 ≠ 1)."""
    pts = [p for p in d["points"] if p.get("EPS_TTM")]
    if not pts or FIN is None:
        return None
    last = pts[-1]
    pr = FIN.fetch_prices(code) or {}
    if not pr:
        return None
    ds = sorted(pr)
    px, date = pr[ds[-1]], ds[-1]
    k = 1.0
    if last.get("주가") and last.get("주가일") and pr.get(last["주가일"]):
        k = last["주가"] / pr[last["주가일"]]
    eps = last["EPS_TTM"] / k
    per = px / eps if eps and eps > 0 else None
    hist = [p.get("PER_TTM") for p in d["points"][-41:] if (p.get("PER_TTM") or 0) > 0]
    pct = (sum(1 for v in hist if per and v <= per) / len(hist) * 100) if per and len(hist) >= 8 else None
    return {"px": px, "date": date, "per": per, "k": round(k, 3), "pct": pct, "stale": not (0.55 < k < 1.8)}
```
`_inv_ttm` · `_inv_regimes` · `_dip_points` 의 파일 직접 읽기는 Task 7 에서 `_druck_read` 로 바꾼다.

- [ ] **Step 4: 라이브 확인** — 뷰어 재시작(Global Constraints 시간 피함) 뒤:
```bash
curl -s "http://127.0.0.1:8765/api/druck?code=005930" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('building'), d.get('v'), len(d.get('points') or []))"
```
처음엔 `True None 0`(백그라운드), 몇십 초 뒤 다시 → `None 2 6x`. 그 뒤:
```bash
curl -s "http://127.0.0.1:8765/api/druck?code=005930" | python -c "import sys,json; d=json.load(sys.stdin); p=[x for x in d['points'] if x['label'] in ('2015Q1','2018Q1','2025Q4','2026Q2')]; print([(x['label'], x.get('PER_TTM'), x.get('국면'), x.get('변곡')) for x in p], d.get('now'))"
```
Expected: 2015Q1 · 2018Q1 PER 이 5~30 사이, 2025Q4 변곡 `▲`, `now.per` 숫자.

- [ ] **Step 5: 커밋**
```bash
git add 서버.py tests/test_druck_server.py
git commit -m "가속도 개편 5: druck v2 — 버전 키(정정 포함) · 잠금 · 원자 쓰기 · 백그라운드 · 일시 오류 미캐시 · 지금 PER"
```

---

### Task 6: 밤 미리 계산 + 기저율/사건 파일(64비트 백테스트)

**Files:**
- Modify: `서버.py` (새 `_druck_auto_loop`, `main()` 의 스레드 시작 목록 `서버.py:10163-10168` 옆)
- Modify: `도구/가속기준_백테스트.py` (`--from-cache` 경로 · 출력 위치 `.cache/druck_bt/`)
- Modify: `서버.py:9090` (`industry_sub` 경로)
- Test: `도구/가속도_점검.py def` 하위 명령(정의 대조)

**Interfaces:**
- Consumes: `druck(code, offline=True)`, `_druck_read`.
- Produces: `.cache/druck_bt/bt_accel.json` — 호환 키 `ev_all.B_up/B_dn`(새 변곡 규칙) · `ev_order.B_up/B_dn` · `regime.B`(7국면 칸 `{n, med, dG4, ci, hit}`) · `whip.B` · `n` · `firms` · `base` + 새 키 `phase7` · `turn` · `asfiled` · `base_any`.
- Produces: `.cache/druck_bt/events.json` — `{code: {"turns": [{n, dir, date, ex6, ex12, state}], "periods": [{d, d2, ex, state}]}}`(state = 'done'|'진행 중').
- Produces: 서버 `DRUCK_PRE = {"at", "done", "total", "net"}` · `/api/druck/pre`(상태).

- [ ] **Step 1: 정의 대조(실패 테스트 역할)** — `도구/가속도_점검.py` 에 하위 명령 `def` 를 더한다:
```python
def defcheck():
    """품질 · 재작성 · 결산월을 끈 accel 의 B 가 옛 signals() 의 B 와 bt_series 전 회사 · 전 분기에서 같은가."""
    sp = ilu.spec_from_file_location("bt", os.path.join(BASE, "도구", "가속기준_백테스트.py"))
    BT = ilu.module_from_spec(sp); sp.loader.exec_module(BT)
    sp = ilu.spec_from_file_location("드러켄밀러", os.path.join(BASE, "드러켄밀러.py"))
    DRK = ilu.module_from_spec(sp); sp.loader.exec_module(DRK)
    ser = json.load(open(os.path.join(BASE, ".cache", "druck_bt", "bt_series.json"), encoding="utf-8"))
    bad = 0; tot = 0
    for code, co in ser.items():
        rev = {n: v for n, v, _ in co["pts"] if v is not None}
        old = BT.signals(co["pts"])
        pts = [{"n": n, "year": n // 4, "q": n % 4 + 1, "label": "%dQ%d" % (n // 4, n % 4 + 1), "품질": [], "YoY_r": None,
                "매출YoY": ((rev[n] / rev[n - 4] - 1) * 100 if rev.get(n - 4) and rev[n - 4] > 0 and n in rev else None)}
               for n in range(min(rev), max(rev) + 1)]
        DRK.accel(pts)
        for p in pts:
            b0 = (old.get(p["n"]) or {}).get("B")
            if b0 is None and p["가속B"] is None:
                continue
            tot += 1
            if b0 is None or p["가속B"] is None or abs(b0 - p["가속B"]) > 1e-9:
                bad += 1
    print("B 대조 %d칸 중 다름 %d" % (tot, bad))
```
(`bt_series.json` 은 먼저 `.cache/druck/` → `.cache/druck_bt/` 로 옮긴다: `mkdir -p .cache/druck_bt && mv .cache/druck/bt_series.json .cache/druck/bt_accel.json .cache/druck_bt/`.)
Run: `python 도구/가속도_점검.py def` → Expected: `다름 0`

- [ ] **Step 2: 백테스트 `--from-cache`** — `도구/가속기준_백테스트.py`:
  - `OUT = os.path.join(BASE, ".cache", "druck_bt")`, `SERIES` 도 그 안.
  - `T1 = dt.date.today().strftime("%Y%m%d")`(고정값 삭제), `YEARS = list(range(2011, dt.date.today().year + 1))`.
  - 새 함수:
```python
def panel_cache(W, S, SEC):
    """druck 캐시(v=VERSION)의 점으로 패널. 금융 · 지주(KSIC 64~66)는 기저율 표본에서 빼되 events 에는 넣는다."""
    sp = ilu.spec_from_file_location("드러켄밀러", os.path.join(BASE, "드러켄밀러.py"))
    DRK = ilu.module_from_spec(sp); sp.loader.exec_module(DRK)
    ksic = json.load(open(os.path.join(BASE, ".cache", "거시", "induty.json"), encoding="utf-8"))
    rows, skipped, ev = [], 0, {}
    for c in S.INDEX["companies"]:
        code = c.get("code"); corp = S.corp_code_of(code) if code else None
        path = os.path.join(BASE, ".cache", "druck", "%s.json" % code)
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        if d.get("v") != DRK.VERSION:
            skipped += 1
            continue
        fin = str(ksic.get(corp) or "").startswith(SEC.FIN_KSIC)
        sec = SEC.sector_of(code, ksic.get(corp) or "")[0]
        evc = {"turns": [], "periods": []}
        for p in d["points"]:
            t = p.get("B기준일") or p.get("기준일")
            if not t or p.get("가속B") is None:
                continue
            t1 = W.next_day(code, t)

            def ex(days):
                if t1 is None or W.shift(t1, days) > T1:
                    return None
                a = W.ret(code, t1, W.shift(t1, days)); b = W.grp_ret("__all__", t1, W.shift(t1, days))
                return a - b if a is not None and b is not None else None
            r = {"code": code, "n": p["n"], "date": t, "t": t[:6] + "15", "sec": sec, "order": sec in ORDER,
                 "B": p["가속B"], "s": p["속도"], "phase": p["국면"], "turn": p["변곡"], "ex6": ex(182), "ex12": ex(365),
                 "late": "amended" in p["품질"] and t > (p.get("기준일") or t), "asfiled": "asfiled" in p["품질"] or "mix" in p["품질"],
                 "dG4": None}
            if p["변곡"]:
                evc["turns"].append({"n": p["n"], "dir": p["변곡"], "date": t, "ex6": r["ex6"], "ex12": r["ex12"],
                                     "state": "done" if r["ex12"] is not None else "진행 중"})
            if not fin:
                rows.append(r)
        ev[code] = evc
    return rows, ev, skipped
```
  - `report_cache(W, rows)` — 표본 = `not r["asfiled"]` 이고 (기준일 − 원본 공시일) ≤ 45일인 행. `rep["ev_all"]["B_up"] = ev_stats(W, [r for r in S if r["turn"] == "▲"])`, `B_dn` 같은 식, `ev_order` 는 `order` 행만, `regime["B"] = {label: ev_stats(W, [r for r in S if r["phase"] == label])}`(7국면), `whip["B"]` = 변곡 뒤 2분기 안 반대 변곡 비율, `base`, `base_any`(아무 분기 중앙값), `asfiled`(asfiled 행만 같은 표 한 줄), `n`, `firms`. `json.dump` 를 `.cache/druck_bt/bt_accel.json` 으로, events 는 `.cache/druck_bt/events.json`.
  - 보고서 구간 사건(`periods`): 색인의 정기보고서 원본 공시일 순서로 (d, 다음 d) 마다 `W.ret(code, next_day(d), next_day(d2)) − W.grp_ret("__all__", …)` 를 `periods` 에 넣는다(d2 가 오늘 뒤면 '진행 중').
  - `__main__`: `--from-cache` 면 `rows, ev, skipped = panel_cache(W, W.S, SEC); report_cache(W, rows); json.dump(ev, …)` 하고 `print("버전 다른 캐시 건너뜀 %d" % skipped)`.

- [ ] **Step 3: 서버 밤 루프** — `서버.py`:
```python
DRUCK_PRE = {"at": None, "done": 0, "total": 0, "net": 0, "running": False}
DRUCK_NET_BUDGET = 2000
BT_PY = os.environ.get("ORBIT_BT_PY") or "py"         # 64비트 파이썬 실행기 — 'py -3.13'


def _druck_prebuild():
    if DRUCK_PRE["running"] or DRK is None:
        return
    DRUCK_PRE.update(running=True, done=0, total=len(INDEX["companies"]), net=0)
    DRK.NET.update(budget=DRUCK_NET_BUDGET, used=0)
    try:
        for c in INDEX["companies"]:
            try:
                druck(c["code"], offline=True)
            except Exception:
                pass
            DRUCK_PRE["done"] += 1
            DRUCK_PRE["net"] = DRK.NET["used"]
        args = [BT_PY, "-3.13", os.path.join(BASE, "도구", "가속기준_백테스트.py"), "--from-cache"]
        subprocess.run(args, cwd=BASE, timeout=3 * 3600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        DRK.NET.update(budget=None, used=0)
        DRUCK_PRE.update(running=False, at=dt.datetime.now().isoformat(timespec="seconds"))


def _druck_auto_loop():
    """매일 02:00(00:10 수집 뒤 · 06:30 저평가 전) 전 종목 가속도를 캐시만으로 미리 계산하고 기저율을 다시 낸다."""
    while True:
        now = dt.datetime.now()
        nxt = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += dt.timedelta(days=1)
        time.sleep((nxt - now).total_seconds())
        _druck_prebuild()
```
`main()` 의 스레드 목록에 `threading.Thread(target=_druck_auto_loop, daemon=True).start()` 를 더한다. 라우트 `"/api/druck/pre"` → `DRUCK_PRE` 를 돌려준다.
`industry_sub`(서버.py:9090) 경로를 `os.path.join(CACHE_DIR, "druck_bt", "bt_accel.json")` 로.

- [ ] **Step 4: 한 번 손으로 돌리기(뷰어 재시작 · 시간 피함 뒤)** — 파이썬 콘솔 대신 라우트를 하나 더 둔다: `"/api/druck/pre?run=1"` 이면 `threading.Thread(target=_druck_prebuild, daemon=True).start()`.
```bash
curl -s "http://127.0.0.1:8765/api/druck/pre?run=1"; sleep 5; curl -s "http://127.0.0.1:8765/api/druck/pre"
```
Expected: `running: true` 와 `done` 이 늘어난다. 끝난 뒤 `.cache/druck_bt/bt_accel.json` · `events.json` 이 생기고 `ls .cache/druck/*.json | wc -l` ≈ 988.
기저율 출력 확인: `py -3.13 도구/가속기준_백테스트.py --from-cache | tail -30` 에 ▲/▼ · 7국면 표.

- [ ] **Step 5: 커밋**
```bash
git add 서버.py 도구/가속기준_백테스트.py 도구/가속도_점검.py
git commit -m "가속도 개편 6: 밤 02:00 전 종목 미리 계산(캐시만 · DART 상한 2,000) · 64비트 기저율/사건 파일 · 정의 대조"
```

---

### Task 7: 소비처 전환(서버 · 변곡점 · 검증 도구)

**Files:**
- Modify: `서버.py` `_inv_ttm`(3114), `_inv_regimes`(4873), `screen_row`(1840) · `score_rows`(1920), `earnings`(1710), `_dip_points`(7686), theme(7268 부근), `inflect`(1311 — 캐시 키), `lens_value`(4729) · `LENS_RULES`(4697) · 주석(4692)
- Modify: `변곡점.py:416-424, 526-557, 694-705`
- Modify: `도구/구루렌즈_검증.py:111-137`, `도구/구루적중률_백테스트.py:115-124`

**Interfaces:**
- Consumes: `_druck_read(code)` 점 필드 `n · 가속B · 속도 · 국면 · 변곡 · 엇갈림 · 매출_TTM · PER_TTM · 주가`.
- Produces: `_inv_ttm(code, stamp) -> {label, g, a, s, reg, turn, price, per, per_pct}`(a = 가속B, s = 속도, reg = 7국면), `_inv_regimes(code) -> [{label, g, s, a, reg}]`.
- Produces: `screen_row` 에 `가속B · 속도 · 국면 · 변곡` 키, `전환` = (변곡 == '▲'), `전환종류` = '성장'|'역성장완화'(속도 부호). `매출가속`(C) 키는 그대로(시너지용).

- [ ] **Step 1: 실패 확인용 라이브 질의(바꾸기 전 기록)**
```bash
curl -s "http://127.0.0.1:8765/api/invest?code=092460" | python -c "import sys,json; d=json.load(sys.stdin); print((d.get('ttm') or {}).get('reg'))"
```
Expected(지금): `가속 성장` 같은 4국면 이름 → 바뀐 뒤 7국면 이름이어야 한다.

- [ ] **Step 2: 구현 — 서버**
  - `_inv_ttm`:
```python
def _inv_ttm(code, stamp):
    """가속도 캐시(지금 버전)로 이 분기의 속도 · 가속(B) · 국면. 없으면 None — 여기서 새로 쌓지 않는다."""
    d = _druck_read(code)
    if not d:
        return None
    pts = d.get("points") or []
    y, m = stamp.split("-")
    lab = "%sQ%d" % (y, Q_OF_MONTH.get(m, 0))
    idx = next((i for i, p in enumerate(pts) if p.get("label") == lab), None)
    if idx is None:
        return None
    p = pts[idx]
    b = next((x for x in pts if x.get("n") == p["n"] - 4), None)
    g = (p["매출_TTM"] / b["매출_TTM"] - 1) * 100 if p.get("매출_TTM") and b and b.get("매출_TTM") else None
    per = p.get("PER_TTM")
    hist = [x.get("PER_TTM") for x in pts[:idx + 1] if (x.get("PER_TTM") or 0) > 0]
    per_pct = (sum(1 for v in hist if v <= per) / len(hist) * 100) if per and per > 0 and len(hist) >= 8 else None
    return {"label": lab, "g": g, "s": p.get("속도"), "a": p.get("가속B"), "reg": p.get("국면"), "turn": p.get("변곡"),
            "price": p.get("주가"), "per": per, "per_pct": per_pct}
```
  - `_inv_regimes`:
```python
def _inv_regimes(code):
    """가속도 캐시(지금 버전)로 분기별 국면(7). 캐시가 없으면 빈 목록."""
    d = _druck_read(code)
    out = []
    for p in (d or {}).get("points") or []:
        out.append({"label": p.get("label"), "s": p.get("속도"), "a": p.get("가속B"), "reg": p.get("국면")})
    return out
```
  - `screen_row`: `pts = DRK.series(...)` 줄부터 `cur, prev = pts[-1], pts[-2]` 까지를 바꾼다:
```python
    d_ = _druck_read(c["code"])
    if d_:
        pts = [p for p in d_["points"] if p.get("매출액")]
    else:
        meta = _druck_meta(c)
        pts = DRK.series(corp, c["code"], years, meta=meta, offline=True)
        DRK.accel(pts)
        pts = [p for p in pts if p.get("매출액")]
    if len(pts) < 2:
        return None
    if not d_:
        dates = {(p["year"], p["q"]): _druck_meta(c)["filed"].get(p["n"]) for p in pts if _druck_meta(c)["filed"].get(p["n"])}
        DRK.attach_prices(pts, c["code"], dates)
    by = {p["n"]: p for p in pts}
    cur = pts[-1]
    prev = by.get(cur["n"] - 1) or {}
```
    `w4` 를 `[by.get(m) for m in range(cur["n"] - 3, cur["n"] + 1)]`(모두 있어야), `turned = cur.get("변곡") == "▲"`, `kind = ("성장" if (cur.get("속도") or 0) >= 0 else "역성장완화") if turned else None`,
    반환 dict 에 `"가속B": cur.get("가속B"), "속도": cur.get("속도"), "국면": cur.get("국면"), "변곡": cur.get("변곡")`, `"매출_TTM_1년전": (by.get(cur["n"] - 4) or {}).get("매출_TTM")` 를 넣는다(나머지 키 유지).
  - `score_rows`: `ranks["매출가속"]` 를 `_pct_rank([r.get("가속B") for r in rows])` 로, 가중 루프에서 `key == "매출가속"` 일 때 값 `r.get("가속B")`. 응답 dict 에 `"score_note": "가중 50/30/20 — 검증 안 됨"`.
  - `earnings`(1710) · `_dip_points` 대체 경로(7700): `[p for p in DRK.series(...) if p.get("매출액")]` 를 `DRK.series(..., meta=_druck_meta(c), offline=True)` 그대로(빈 분기 점 유지) 쓰고, 이어지는 순번 접근(`pts[-5]` 등)을 `n` 키 조회로 바꾼다(각 함수 안 `by = {p["n"]: p for p in pts}`).
  - theme(7268 부근 `P[k-3:k+1]`): `주가일` 로 거른 뒤 순번 창 → `n` 키 창(`[by.get(m) for m in range(p["n"]-3, p["n"]+1)]`).
  - `inflect`: 캐시 sig 에 `DRK.VERSION` 을 붙인다(`sig = "%s:%d" % (sig, DRK.VERSION)` — inflect 의 sig 계산 줄 바로 뒤).
  - `_dip_points` · `_inv_ttm` · `_inv_regimes` 의 파일 직접 읽기를 `_druck_read` 로(위에서 바꿈).
  - 렌즈: `LENS_RULES["스탠리 드러켄밀러"][0] = "드러켄밀러 · 가속(B) +3%p↑"`, `lens_value` 의:
```python
    dk = _druck_read(code)
    lastp = next((p for p in reversed((dk or {}).get("points") or []) if p.get("가속B") is not None), None)
    acc = lastp.get("가속B") if lastp else None
```
    (기존 `acc = (last["rev_yoy"] - prev["rev_yoy"]) …` 줄 대체), 조건 `if acc is not None and acc >= DRK.PHASE_BAND:` 문구 `"매출 가속(B) %+.1f%%p(속도 %+.0f%%, %s)" % (acc, lastp["속도"], lastp["국면"])`, ev 이름 `"드러켄밀러 · 가속(B) +3%p↑"`. 4692 주석의 '매출 가속 +5%p↑(+2.3%p …)' 줄은 '매출 가속(B) +3%p↑ — 성적은 lens_bt.json' 으로.
- [ ] **Step 3: 구현 — 변곡점.py**
  - 416-424 사건: `qs = [q for q in quarters if q.get("가속B") is not None][-8:]`, `for b in qs: if b.get("변곡") == "▲" and (b.get("속도") or 0) > 0:` 사건 제목 `"분기 매출 가속 전환 (%s)" % b["label"]`, detail `"속도 %s, 가속(B) %+.1f%%p — 띠(±3%%p) 반대쪽에서 넘어옴" % (_pct(b.get("속도")), b["가속B"])`.
  - 526-557 카드: `acc = [q.get("가속B") for q in qs if q.get("가속B") is not None]`, 배지 `good` 의 첫 항을 `(1 if last.get("가속B") is not None and last["가속B"] >= 3 else 0)`, 시리즈 `{"k": "매출 가속(B)", "v": None if last.get("가속B") is None else "%+.1f%%p" % last["가속B"], "note": "속도(분기 YoY 2분기 평균)의 변화", "series": [{"y": q.get("label"), "v": q.get("가속B")} for q in qs]}`,
    `how` 문장의 '큰 표본에서 가속 +5%p↑는 약하게 맞았지만 …' 을 `lens_ev` 숫자로 만든 문장 또는 삭제(`ev = 서버가 넘긴 lens_ev` 가 없으면 문장 삭제).
  - `_druck_verdict`: 
```python
def _druck_verdict(last, invd):
    if not last:
        return "분기 실적 자료가 부족하다."
    s = "최근 분기(%s) 속도 %s, 가속(B) %s — %s." % (last.get("label", ""), _pct(last.get("속도"), 1),
                                              "—" if last.get("가속B") is None else "%+.1f%%p" % last["가속B"], last.get("국면") or "국면 판단 전")
    if last.get("엇갈림"):
        s += " 이번 분기 단독은 반대로 움직였다."
    if len(invd) >= 2:
        s += " 재고일수 %.0f일 → %.0f일." % (invd[0], invd[-1])
    return s
```
- [ ] **Step 4: 구현 — 검증 도구**
  - `도구/구루렌즈_검증.py`: 행을 만들 때 그 공시의 분기 키 n 으로 `.cache/druck/{code}.json`(v 확인) 점의 `가속B` 를 `r["accB"]` 로 붙이고, 규칙을 `("드러켄밀러 · 가속(B) +3%p↑", lambda r: None if r.get("accB") is None else r["accB"] >= 3)` 로 바꾼다(옛 `acc` 규칙 줄 삭제).
  - `도구/구루적중률_백테스트.py:115-124`: 드러켄밀러 배지의 `acc = y0 - y1 > 0` 를 같은 시점 druck 점 `가속B >= 3` 으로.
  - 다시 돌린다: `python 도구/구루렌즈_검증.py` · `python 도구/구루적중률_백테스트.py`(각 도구 머리 주석의 실행법 그대로). 통과 기준(90% 구간 하단 > 0 · 앞뒤 같은 방향)을 못 넘으면 결과를 기록해 두고 Task 9 보고에 올린다(배지를 '검증 안 됨'으로 — `_ev_word` 가 그렇게 적는지 화면에서 확인).
- [ ] **Step 5: 확인** — 뷰어 재시작 뒤: Step 1 질의가 7국면 이름을 돌려준다 · `/api/screen` 행에 `가속B` · `/api/inflect?code=092460` 드러켄밀러 카드 판정이 서술형 · `/api/industry/sub?tab=stocks&sector=반도체` 의 `bt.B_up.n` 이 숫자.
- [ ] **Step 6: 커밋**
```bash
git add 서버.py 변곡점.py 도구/구루렌즈_검증.py 도구/구루적중률_백테스트.py
git commit -m "가속도 개편 7: 소비처를 같은 B 로 — 변화 브리핑 · 전 종목 스크리닝 · 변곡점 카드/렌즈 · 구루 적중률 · 순번 → 분기 키"
```

---

### Task 8: 화면 — 가속도 탭 · 변화 브리핑 · 스크리닝 · 산업 문구

**Files:**
- Modify: `웹/index.html` 가속도 블록(8379-8937: `DRK_REG` · `DRK_READ` · `drkCalc` · `viewDruck` · `drkPlate` · `drkCompass` · `drkTipBody` · `drkChecks` · `drkStack` · `drkTurns` · `drkLedger`), 변화 브리핑 TTM 국면 칩(9869 부근) · `invArc` 국면 띠/범례/'TTM 국면별' 칸, 전 종목 스크리닝(8171 · 8191 · 8241 · 8283 · 8305 · 8347), 산업 섹터 안 종목 문구(5033-5036)

**Interfaces:**
- Consumes: `/api/druck` `{building, done, total}` 또는 `{points, basis, fy, now, transient}` · `/api/druck/bt`(새 — `.cache/druck_bt/bt_accel.json` 의 `regime.B` · `ev_all` · `base_any` · `firms` · `n`) · `/api/druck/events?code=`(새 — events.json 의 그 회사 항목).
- Produces: `DRK_REG` = 7국면 `[{k, en, c}]`(색은 `GR_PHASE` 의 같은 이름 색), `DRK_RC`.

- [ ] **Step 1: 서버 라우트 둘** — `"/api/druck/bt"` → `_ind_file("bt_accel", os.path.join(CACHE_DIR, "druck_bt", "bt_accel.json")) or {}` 에서 `{"regime": .., "ev_all": .., "base_any": .., "firms": .., "n": ..}` 만. `"/api/druck/events"` → events.json 에서 그 code(파일은 `_ind_file` 처럼 mtime 캐시).
- [ ] **Step 2: `DRK_REG` · 문구** — 7국면, 서술형 `d`:
```js
const DRK_REG=[
  {k:'확장 가속', en:'EXPANDING · FASTER', d:'매출이 늘고, 늘어나는 속도도 빨라졌다(가속 +3%p 이상)'},
  {k:'확장 유지', en:'EXPANDING · STEADY', d:'매출이 늘고, 속도는 비슷하다(가속 ±3%p 안)'},
  {k:'둔화',     en:'SLOWING',            d:'매출은 늘지만 속도가 줄었다(가속 −3%p 이하)'},
  {k:'회복',     en:'RECOVERING',         d:'매출은 줄었지만 줄어드는 폭이 작아졌다(가속 +3%p 이상)'},
  {k:'부진 지속', en:'STILL WEAK',         d:'매출이 줄고, 줄어드는 속도는 비슷하다'},
  {k:'수축 심화', en:'CONTRACTING',        d:'매출이 줄고, 줄어드는 속도가 빨라졌다'},
  {k:'정체',     en:'FLAT',               d:'속도가 ±2% 안이고 가속도 ±3%p 안 — 늘지도 줄지도 않는다'},
].map(r=>Object.assign(r,{c:(GR_PHASE_COLOR[r.k]||'#8b95a3')}));
const DRK_RC=Object.fromEntries(DRK_REG.map(r=>[r.k,r]));
```
  (`GR_PHASE_COLOR` — 산업 탭 `GR_PHASE`(4509 부근)가 쓰는 클래스의 실제 색을 이름 → 색 객체로 하나 둔다: 그 CSS 클래스(`pos2` 등)의 색값을 그대로 옮긴다.) `DRK_READ` · `DRK_FLAT_READ` · `drkRead` · `drkFlat` 은 지운다.
- [ ] **Step 3: `drkCalc` → 읽기만**
```js
function drkCalc(pts){
  const R=pts.map(p=>Object.assign({},p));
  const by=Object.fromEntries(R.map(r=>[r.n,r]));
  const ratio=(a,b)=>(dNum(a)&&dNum(b)&&b>0&&a>0)?(a/b-1)*100:null;
  R.forEach(r=>{ const b=by[r.n-4];
    r.g = b&&dNum(r['매출_TTM'])&&dNum(b['매출_TTM'])&&b['매출_TTM']>0 ? (r['매출_TTM']/b['매출_TTM']-1)*100 : null;   // 추세(약 1분기 늦음)
    r.m = dNum(r['영업이익_TTM'])&&dNum(r['매출_TTM'])&&r['매출_TTM']>0 ? r['영업이익_TTM']/r['매출_TTM']*100 : null;
    r.og = b ? ratio(r['영업이익_TTM'], b['영업이익_TTM']) : null;
    r.mD4 = b&&dNum(r.m)&&dNum(b.m) ? r.m-b.m : null;
    r.invD4 = b ? ratio(r['재고일수'], b['재고일수']) : null;
    r.arD4 = b ? ratio(r['매출채권일수'], b['매출채권일수']) : null;
    r.px4 = b ? ratio(r['주가'], b['주가']) : null;
    r.eps4 = b ? ratio(r['EPS_TTM'], b['EPS_TTM']) : null;
    r.s=r['속도']; r.a=r['가속B']; r.reg=r['국면']; r.turn=r['변곡']==='▲'?'up':r['변곡']==='▼'?'down':null; });
  R.forEach(r=>{ const p=by[r.n-1]; r.streak = !dNum(r.a)||Math.abs(r.a)<3 ? 0 : (p&&dNum(p.a)&&Math.abs(p.a)>=3&&(p.a>0)===(r.a>0) ? p.streak+1 : 1); });
  return R;
}
```
- [ ] **Step 4: `viewDruck` — 진행률 · 품질 · 기저율 · 사건**
```js
async function viewDruck(p){
  const c=S.co, code=c.code;
  p.innerHTML='';
  const plate=el('section','synplate orbplate drkplate'); p.appendChild(plate);
  const wait=el('div','orbWait','분기 단독 실적 쌓는 중…'); plate.appendChild(wait);
  const ledger=el('div','orbledger drkledger'); p.appendChild(ledger);
  let d;
  for(;;){
    try{ d=await (await fetch('/api/druck?code='+code)).json(); }
    catch(e){ plate.innerHTML=''; plate.appendChild(el('div','orbWait','불러오지 못했습니다.')); return; }
    if(S.tab!=='druck' || !S.co || S.co.code!==code) return;
    if(!d.building) break;
    wait.textContent='분기 단독 실적 쌓는 중… 처음 한 번만 걸린다'+(d.total?' ('+d.done+' / '+d.total+')':'')+' — 다른 탭에 다녀와도 계속 계산한다.';
    await new Promise(r=>setTimeout(r,2500));
  }
  plate.innerHTML='';
  if(d.error){ plate.appendChild(el('div','orbWait',d.error)); return; }
  const pts=d.points||[];
  if(pts.filter(x=>x['매출액']||(d.basis==='영업이익'&&dNum(x['영업이익']))).length<6){
    plate.appendChild(el('div','orbWait', d.basis==='영업이익'?'영업이익 분기 자료가 모자랍니다 (6분기 이상 필요).':'분기 자료가 모자랍니다 (6분기 이상 필요).')); return; }
  const [bt,ev]=await Promise.all([fetch('/api/druck/bt').then(r=>r.json()).catch(()=>({})), fetch('/api/druck/events?code='+code).then(r=>r.json()).catch(()=>({}))]);
  const R=drkCalc(pts);
  drkPlate(plate, R, c, d, bt, ev);
  drkLedger(ledger, R, d.text||[]);
}
```
- [ ] **Step 5: `drkPlate(plate, R, c, d, bt, ev)`** — 머리 · 헤드라인 · 기저율 · 품질 배너 · KPI:
  - 헤드라인(`now` = 국면이 있는 마지막 점):
```js
  const H={'확장 가속':'매출 성장 속도가 올라간다','확장 유지':'매출이 비슷한 속도로 늘고 있다','둔화':'매출은 늘지만 속도가 줄었다',
           '회복':'매출 감소 폭이 줄고 있다','부진 지속':'매출이 비슷한 속도로 줄고 있다','수축 심화':'매출 감소가 빨라졌다','정체':'매출이 제자리다'};
  h3 = reg ? c.name+', '+H[now.reg] : '분기 자료가 모자라 국면을 못 정했다';
  // 설명: 'YYYYQn 기준 속도(최근 2분기 분기 매출 전년 대비 평균) +x%, 그 앞 2분기 +y% — 가속 ±z%p. N분기째 띠 밖.'
  // 엇갈림이면 ' 이번 분기 단독은 반대로 움직였다(±c%p).' 를 붙인다. 처방 문구 없음.
```
  - 기저율 줄 — `bt.regime[now.reg]`(또는 막 난 변곡이면 `bt.ev_all.B_up/B_dn`):
```js
  const brl=(o,lab)=>o&&o.n? lab+' · 과거 '+(bt.firms||0)+'곳 '+o.n.toLocaleString('ko-KR')+'번 — 12개월 시장 대비 중앙 '+dPct(o.med,1)+
     (o.ci?' ['+dPct(o.ci[0],1)+', '+dPct(o.ci[1],1)+']':'')+' · 이긴 비율 '+Math.round(o.hit||0)+'%'+(dNum(o.dG4)?' · 4분기 뒤 TTM 성장 '+dPp(o.dG4,1):'')+
     (dNum(bt.base_any)?' · 아무 분기 '+dPct(bt.base_any,1):'') : null;
  const NEG=new Set(['회복','부진 지속','수축 심화']);
  // d.basis==='영업이익' → '기저율 표본(KSIC 64~66 제외)에 없는 회사 — 견줄 기저율 없음'
  // NEG.has(now.reg) → ' · 상장폐지된 회사가 빠져 위로 치우친 값' 덧붙임. 끝에 ' · 주가보다 실적 변화를 더 잘 맞힌다 · 지금 상장사만(생존 편향)'.
```
  - 품질 배너 — 마지막 12분기 점의 `품질` 합집합 · `d.fy` · `d.basis`:
```js
  const QN={gap:'빠진 분기',basis:'기준(연결/별도 · 범위)이 다른 4분기',asfiled:'재작성 비교값 없음 — 공시 당시 값',mix:'재작성/공시 당시 섞임',
            amended:'정정본 값(알 수 있던 날이 늦음)',neg:'음수 매출 제외',dup:'같은 값 반복 제외',fy:'결산월 다름 — 그 해 계산 제외',unit:'주당순이익 단위 오류 고침'};
  const qs=new Set(); R.slice(-12).forEach(r=>(r['품질']||[]).forEach(x=>qs.add(x)));
  // 배너: [...qs].map(k=>QN[k]) + (d.basis==='영업이익'?['금융사 — 영업이익으로 계산']:[]) + (d.fy&&d.fy.length?['결산월 다름: '+d.fy.join(', ')]:[])
```
  - KPI 다섯: `속도`(dPct(now.s,1), '최근 2분기 분기 매출 전년 대비 평균') · `가속(B)`(dPp(now.a,1), now.streak+'분기째 띠 밖' 또는 '띠 안') · `TTM 이익률` · `재고일수` · `PER` → `공시일 '+(now.PER_TTM?.toFixed(1))+'배 · 지금 '+(d.now&&d.now.per?d.now.per.toFixed(1)+'배':'—')` 와 백분위 `d.now.pct`(8분기 이상일 때). `d.now.stale` 이면 '분할 뒤 다시 계산 대기'.
  - footer 문구: '출처: DART 분기·반기·사업보고서(분기 단독, 전년 대비는 같은 보고서의 비교기간 값). 속도 = 분기 매출 전년 대비의 최근 2분기 평균, 가속 = 속도 − 앞 2분기 평균, 띠 ±3%p — 산업 탭 업황 시계와 같은 식. 사건 수익률은 그 숫자를 알 수 있던 날 다음 거래일부터 전 종목 중앙값 대비.'
- [ ] **Step 6: 나침반 · 말풍선 · 점검 메모**
  - `drkCompass`: x = `r.s`(속도), y = `r.a`(B), 칸 = 6국면 사분면 대신 **띠 음영**(y −3~+3 에 옅은 회색 띠) + 사분면 이름 넷(확장 가속 · 둔화 · 회복 · 수축 심화) + 띠 안 라벨(확장 유지 / 부진 지속), 원점 ±2% 정체 상자. 축 이름: '속도 → (분기 매출 전년 대비, 최근 2분기 평균)', '가속 → (속도 − 앞 2분기, %p)'. '전형적 순환 ↻' 호는 두되 라벨을 '읽는 법 · 흔한 순서'로.
  - `drkTipBody`: 행 `['속도',dPct(r.s,1)],['가속(B)',dPp(r.a,1)],['분기 매출 YoY',dPct(r.YoY_r??r['매출YoY'],1)],['TTM 추세',dPct(r.g,1)], …`, 품질이 있으면 끝에 `el('p',null,'품질: '+…)`. 변곡이면 `events` 의 ex6/ex12(시장 대비) 를 적는다.
  - `drkChecks` → 제목 '점검 메모' / 'NOTES · '+now.label, 아이콘 `↑`(좋아짐) `↓`(나빠짐) `–`(판단 보류), 클래스 `up/dn/na`, 'N / M 통과' · `drkVerdict` 삭제. 항목 문장은 사실만(예: '이익 +562% vs 매출 +57% — 이익이 매출보다 빨리 늘었다').
- [ ] **Step 7: 분기 궤적 · 성적표 · 원장**
  - `drkStack`: 국면 띠 = 7색, 범례 `DRK_REG`, 캡션 '속도 부호 × 가속(띠 ±3%p)'. A 판: 막대 = 분기 YoY(`YoY_r` 우선), 선 = 속도(`r.s`, 금색), 점선 = TTM 추세(`r.g`), 변곡 삼각형은 `r.turn`.
    `R[i-4]` 같은 순번 접근 없음(이미 drkCalc 가 키로 계산). 빈 분기(`매출액` 없음) 칸은 빈 칸으로 둔다(필터 안 함).
  - `drkTurns(R, ev, bt)`: 제목 '변곡 기록' / 'TURNS · 시장 대비 · 그 숫자를 알 수 있던 날 다음 거래일부터'. 위 두 카드 = 기저율(`bt.ev_all.B_up`, `B_dn` — n · 중앙 · 구간 · 이긴 비율). 아래 목록 = 이 회사 변곡(분기 · ▲▼ · 속도 · 가속) + `ev.turns` 의 같은 n 의 6 · 12개월(없으면 '진행 중'), 쪽별 3번 미만이면 '표본 적음'. **종목 판정 문장 없음.** 빈 상태: '가속이 띠(±3%p)를 건너 반대쪽으로 넘어간 분기가 없다.'
  - `drkLedger`: 열 `분기 · 국면 · 매출 · 분기 YoY · 속도 · 가속(B) · TTM 추세 · TTM 이익률 · 이익률 Δ1년 · 재고일 · 채권일 · 주가 · 공시일 PER · 품질`. 설명 문구 갱신.
- [ ] **Step 8: 변화 브리핑 · 스크리닝 · 산업 문구**
  - 'TTM 국면' 칩(9869 부근): `chip('국면', d.ttm.reg+' · 속도 '+iPct(d.ttm.s,0)+' · 가속 '+(d.ttm.a>=0?'+':'')+d.ttm.a.toFixed(1)+'%p')`.
  - `invArc`: `regBy[r.label]=r` 그대로(라벨 키), `DRK_REG`/`DRK_RC` 가 7국면이 되면 띠 · 범례 · 'TTM 국면별' 칸이 따라온다. 칸 제목 '국면별 · 시장 대비 (중앙값 · 횟수)' 로, 값은 `/api/druck/events` 의 `periods` 에서 같은 공시일(`d`)의 `ex` 를 쓴다(없으면 기존 원수익률 대신 '—').
  - 스크리닝(8171 · 8191 · 8241 · 8283 · 8305 · 8347): 표시 · 거르기 · 산점도 x 의 `매출가속` → `가속B`, 열 이름 '가속(B)', 배지 '★성장 전환' 은 `변곡==='▲'`. 점수 열 머리에 '(가중 미검증)'.
  - 산업 섹터 안 종목(5033-5036): '가속 전환 ↑(가속이 −에서 +로)' → '가속 전환 ↑(띠 밖 반대쪽에서 넘어옴)', '네 상태의 12개월 초과수익 중앙' → '국면별 12개월 초과수익 중앙'.
- [ ] **Step 9: 브라우저 확인** — 뷰어(재시작 필요 시 시간 피함) · 브라우저로 005930 · 092460 · 403870 · 105560 · 042370 · 000210 의 가속도 탭, 005930 변화 브리핑, 전 종목 스크리닝, 092460 변곡점, 산업 반도체 섹터 안 종목을 연다. 콘솔 오류 0, 처방 문구 없음(`grep -n "비중을 싣\|들어가는 자리\|기다릴 구간" 웹/index.html` → 없음).
- [ ] **Step 10: 커밋**
```bash
git add 웹/index.html 서버.py
git commit -m "가속도 개편 8: 화면 — 7국면 · 서술형 문구 · 기저율 · 품질 배너 · 지금 PER · 점검 메모 · 시장 대비 변곡 기록 · 진행률"
```

---

### Task 9: 회귀 사례 · 독립 검토 · 문서

**Files:**
- Modify: `도구/가속도_점검.py` (하위 명령 `cases`)
- Modify: `README.md`(가속도 절), `docs/superpowers/specs/2026-10-09-druck-accel-kis-design.md`(끝에 '만든 뒤 바뀐 것')

- [ ] **Step 1: 회귀 사례 스크립트** — `cases` 하위 명령(라이브 API 로):
```python
CASES = [
    ("005930", lambda d: all(5 <= (p.get("PER_TTM") or 10) <= 30 for p in d["points"] if "2012Q1" <= p["label"] <= "2018Q4" and p.get("PER_TTM")), "삼성 2012~2018 공시일 PER 5~30"),
    ("005930", lambda d: next(p for p in d["points"] if p["label"] == "2025Q4")["변곡"] == "▲", "삼성 2025Q4 ▲"),
    ("005930", lambda d: next(p for p in d["points"] if p["label"] == "2026Q1")["변곡"] is None, "삼성 2026Q1 같은 쪽 — 변곡 아님"),
    ("010120", lambda d: abs(next(p for p in d["points"] if p["label"] == "2026Q2")["EPS_TTM"] / next(p for p in d["points"] if p["label"] == "2026Q1")["EPS_TTM"] - 1) < 0.6, "LS일렉트릭 분할 앞뒤 EPS_TTM 한 기준"),
    ("000210", lambda d: next(p for p in d["points"] if p["label"] == "2020Q4").get("매출액") is None, "DL 2020Q4 Q4 없음"),
    ("042370", lambda d: bool(d.get("fy")), "비츠로테크 결산월 다름"),
    ("105560", lambda d: d.get("basis") == "영업이익", "KB 영업이익 기준"),
    ("003550", lambda d: all((p.get("EPS") or 0) < 1e6 for p in d["points"]), "LG EPS 단위"),
]
def cases():
    import urllib.request
    fails = 0
    for code, f, name in CASES:
        d = json.load(urllib.request.urlopen("http://127.0.0.1:8765/api/druck?code=" + code, timeout=300))
        while d.get("building"):
            import time; time.sleep(3)
            d = json.load(urllib.request.urlopen("http://127.0.0.1:8765/api/druck?code=" + code, timeout=300))
        ok = False
        try:
            ok = bool(f(d))
        except Exception as e:
            name += " (%s)" % e
        fails += not ok
        print(("OK  " if ok else "FAIL") + "  " + name)
    print("실패 %d" % fails)
```
Run: `python 도구/가속도_점검.py cases` → Expected: `실패 0`. 실패가 있으면 원인을 고치고(테스트 먼저) 다시.
- [ ] **Step 2: 독립 검토** — 다관점(정확성 · 통계/시점 · 화면 문구 · 소비처 회귀) 검토와 반박 검증을 돌려 확인된 것만 고친다(각 수정은 테스트 먼저).
- [ ] **Step 3: 문서** — README 가속도 절을 B · 7국면 · 품질 · 기저율 파일 · 밤 계산으로 바꾸고, 설계 문서 끝에 '만든 뒤 바뀐 것'(검토 반영 · 렌즈 재검증 결과 · 기저율 숫자)을 적는다.
- [ ] **Step 4: 커밋**
```bash
git add 도구/가속도_점검.py README.md docs/superpowers/specs/2026-10-09-druck-accel-kis-design.md
git commit -m "가속도 개편 9: 회귀 사례 점검 · 검토 반영 · 문서"
```

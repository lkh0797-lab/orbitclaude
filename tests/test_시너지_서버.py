# -*- coding: utf-8 -*-
"""시너지 발굴 서버 조각(2026-10-14 v2) — 쌍둥이 정리 · 시총/잔고 업종 백분위 · reliable 이유(신선도 · 검산 창 12) ·
_syn_row 의 풍경 PER · lead · 갭 자름 · forward 기록 · synergy_view bt overall/no_slow.
설계 docs/superpowers/specs/2026-10-14-synergy-value-design.md 1절 · 4절, 계획 Task 3."""
import os, sys, json, copy, time, datetime as dt, importlib.util as ilu
import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("서버_시너지_시험", os.path.join(BASE, "서버.py"))
SRV = ilu.module_from_spec(_sp); _sp.loader.exec_module(SRV)


# ---------------------------------------------------------------- 쌍둥이
def test_twin_keep_prefers_larger_cover():
    a = {"code": "A", "name": "원익홀딩스", "reliable": True, "cover": 0.4, "same_as": ["원익IPS"], "why_not": None}
    b = {"code": "B", "name": "원익IPS", "reliable": True, "cover": 1.2, "same_as": ["원익홀딩스"], "why_not": None}
    c = {"code": "C", "name": "혼자", "reliable": True, "cover": 0.9, "same_as": [], "why_not": None}
    SRV._syn_twin_keep([a, b, c])
    assert b["reliable"] and c["reliable"] and not a["reliable"] and "원익IPS" in a["why_not"]
    assert "지주" in a["why_not"] and b["why_not"] is None


def test_twin_keep_ignores_partner_already_unreliable_and_handles_none_cover():
    a = {"code": "A", "name": "지주", "reliable": True, "cover": None, "same_as": ["자회사"], "why_not": None}
    b = {"code": "B", "name": "자회사", "reliable": False, "cover": 2.0, "same_as": ["지주"], "why_not": "잔고 보고서가 3개뿐"}
    SRV._syn_twin_keep([a, b])
    assert a["reliable"] and a["why_not"] is None          # 상대가 이미 빠져 있으면 중복이 아니다
    assert not b["reliable"] and b["why_not"] == "잔고 보고서가 3개뿐"
    # 셋이 같은 잔고 — cover 큰 하나만 남는다, cover None 은 가장 작다
    x = {"code": "X", "name": "엑스", "reliable": True, "cover": None, "same_as": ["와이", "제트"], "why_not": None}
    y = {"code": "Y", "name": "와이", "reliable": True, "cover": 0.5, "same_as": ["엑스", "제트"], "why_not": None}
    z = {"code": "Z", "name": "제트", "reliable": True, "cover": 0.8, "same_as": ["엑스", "와이"], "why_not": None}
    SRV._syn_twin_keep([x, y, z])
    assert z["reliable"] and not x["reliable"] and not y["reliable"]
    assert "제트" in x["why_not"] and "제트" in y["why_not"]


# ---------------------------------------------------------------- 시총/잔고 업종 백분위
def test_capbl_pct_needs_three_in_industry():
    rows = [{"code": str(i), "reliable": True, "industry": "조선", "cap": c, "backlog": 100.0} for i, c in enumerate((50.0, 100.0, 200.0))]
    rows.append({"code": "x", "reliable": True, "industry": "건설", "cap": 10.0, "backlog": 100.0})
    rows.append({"code": "u", "reliable": False, "industry": "조선", "cap": 1.0, "backlog": 100.0})
    rows.append({"code": "n", "reliable": True, "industry": "분류없음", "cap": 1.0, "backlog": 100.0})
    rows.append({"code": "m", "reliable": True, "industry": "조선", "cap": None, "backlog": 100.0})
    SRV._syn_capbl_pct(rows)
    assert rows[0]["capbl_pct"] < rows[1]["capbl_pct"] < rows[2]["capbl_pct"]
    assert rows[3]["capbl_pct"] is None and rows[4]["capbl_pct"] is None
    assert rows[5]["capbl_pct"] is None and rows[6]["capbl_pct"] is None
    assert 0 <= rows[0]["capbl_pct"] <= 100


# ---------------------------------------------------------------- reliable 이유
def test_reliable_why_fresh_and_window():
    assert SRV._syn_reliable_why(n=5, jumps=0, last_switch=None, sure=6, n_win=12, cover=0.5, fresh_days=100) is None
    assert "묵었다" in SRV._syn_reliable_why(n=5, jumps=0, last_switch=None, sure=6, n_win=12, cover=0.5, fresh_days=201)
    assert "절반" in SRV._syn_reliable_why(n=5, jumps=0, last_switch=None, sure=5, n_win=12, cover=0.5, fresh_days=10)
    # 경계: 200일은 통과, 201일부터 묵음. 날짜를 모르면(None) 빼지 않는다
    assert SRV._syn_reliable_why(n=5, jumps=0, last_switch=None, sure=6, n_win=12, cover=0.5, fresh_days=200) is None
    assert SRV._syn_reliable_why(n=5, jumps=0, last_switch=None, sure=6, n_win=12, cover=0.5, fresh_days=None) is None


def test_reliable_why_keeps_existing_messages_in_order():
    assert "3개뿐" in SRV._syn_reliable_why(n=3, jumps=0, last_switch=None, sure=0, n_win=3, cover=None, fresh_days=None)
    assert "5배" in SRV._syn_reliable_why(n=5, jumps=1, last_switch=None, sure=6, n_win=12, cover=0.5, fresh_days=None)
    w = SRV._syn_reliable_why(n=5, jumps=0, last_switch=("표·행합산", 1.8), sure=6, n_win=12, cover=0.5, fresh_days=None)
    assert "표·행합산" in w and "1.8배" in w
    assert "연매출의 10%" in SRV._syn_reliable_why(n=5, jumps=0, last_switch=None, sure=6, n_win=12, cover=0.10, fresh_days=None)
    # 검산 창 12: 6/12 는 절반이라 통과, 6/13 은 못 넘는다
    assert SRV._syn_reliable_why(n=5, jumps=0, last_switch=None, sure=6, n_win=12, cover=None, fresh_days=None) is None
    assert "절반" in SRV._syn_reliable_why(n=5, jumps=0, last_switch=None, sure=6, n_win=13, cover=None, fresh_days=None)


def test_fresh_days_takes_the_older_of_two_dates():
    today = dt.date(2026, 10, 15)
    assert SRV._syn_fresh_days("20260814", "20260901", today=today) == (today - dt.date(2026, 8, 14)).days
    assert SRV._syn_fresh_days("20260814", None, today=today) == (today - dt.date(2026, 8, 14)).days
    assert SRV._syn_fresh_days(None, "", today=today) is None
    assert SRV._syn_fresh_days("2026081", "bad", today=today) is None


# ---------------------------------------------------------------- _syn_row — 풍경 PER · lead · 갭 자름 · 창 12
def _pt(i, verified=True, method="표·합계", rcept="20260814000001"):
    return {"stamp": "2026-06", "label": "반기보고서", "rcept": rcept, "value": 1000.0 * (i + 1), "method": method,
            "source": "표 … [검산 일치]" if verified else "표 … [검산 불가]", "verified": verified}


def _b(n_pts=13, n_sure=7, last_rcept="20260814000001"):
    pts = [_pt(i, verified=(i >= n_pts - n_sure)) for i in range(n_pts)]
    pts[-1]["rcept"] = last_rcept
    return {"code": "000001", "name": "가짜", "sector": "산업재", "industry": "조선",
            "points": pts[-12:], "trend": {"last": 2.0e11, "yoy": 400.0, "n": 8, "jumps": 0, "last_switch": None},
            "verified": 0, "explicit": 0, "n_pts": 8}


class _Fin:
    API_KEY = "x"

    @staticmethod
    def fetch_prices(code):
        return {}


@pytest.fixture
def env(monkeypatch, tmp_path):
    c = {"code": "000001", "name": "가짜", "dir": "가짜_000001", "reports": []}
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "company_by_code", lambda code: c if code == "000001" else None)
    monkeypatch.setattr(SRV, "FIN", _Fin)
    monkeypatch.setattr(SRV, "_universe_info", lambda: ({"000001": {"rank": 10, "market": "KOSPI", "cap": 1.0e12}}, "20261001"))
    monkeypatch.setattr(SRV, "sector_map", lambda: {"stocks": {}})
    monkeypatch.setattr(SRV.SYN, "price_stats", lambda prices, snap: {"now": 100.0, "p1y": 450.0, "p3m": 5.0, "p1m": 1.0, "dd52": -3.0, "since_snap": 1.0})
    sr = {"매출_TTM": 1.0e11, "매출_TTM_1년전": 0.8e11, "영업이익_TTM": 5.0e9, "순이익_TTM": 4.0e9, "PER_TTM": 12.0,
          "quarter": "2026Q2", "접수일": "20260814", "매출YoY": 10.0, "매출가속": 1.0, "영업이익률": 5.0, "마진변화": 0.5}
    monkeypatch.setattr(SRV, "screen_row", lambda c_: dict(sr))
    land = {"decide": {"per": 20.0, "pct": 35.0, "date": "20261014"}, "band": {"lo": 10.0, "mid": 25.0, "hi": 40.0, "n": 30}}
    monkeypatch.setattr(SRV, "_land_read", lambda code: copy.deepcopy(land))
    return {"c": c, "sr": sr, "land": land}


def test_syn_row_fills_per_from_landscape_lead_and_clipped_gap(env):
    r = SRV._syn_row(_b(), {}, {}, {})
    assert r["per"] == 20.0 and r["per_pct"] == 35.0 and r["per_med"] == 25.0      # 오늘 주가 PER(풍경)
    assert r["per_date"] == "20261014"                                              # 그 PER 의 주가 날짜 = 풍경 계산일(2026-10-15 리뷰)
    assert r["per_filed"] == 12.0                                                   # 접수일 PER 은 따로
    assert r["lead"] == pytest.approx(400.0 - 25.0)                                 # 잔고 1년 − 4분기 합 매출 1년(+25%)
    assert r["gap"] == pytest.approx(300.0 - 300.0)                                 # 양쪽 300 으로 자름(주가 +450% 도)
    assert r["fresh_days"] == (dt.date.today() - dt.date(2026, 8, 14)).days
    assert r["reliable"] is True and r["why_not"] is None
    assert r["n_pts"] == 12 and r["verified"] + r["explicit"] == 7                  # 검산 창 12 — 7/12 통과


def test_syn_row_window_12_and_stale_report(env, monkeypatch):
    r = SRV._syn_row(_b(n_sure=5), {}, {}, {})          # 5/12 — 절반이 안 된다(예전 창 8 이면 5/8 로 통과했다)
    assert not r["reliable"] and "절반" in r["why_not"] and "5/12" in r["why_not"]
    r = SRV._syn_row(_b(last_rcept="20250301000001"), {}, {}, {})     # 잔고 보고서가 200일 넘게 묵었다
    assert not r["reliable"] and "묵었다" in r["why_not"]


def test_syn_row_without_landscape_has_no_per(env, monkeypatch):
    monkeypatch.setattr(SRV, "_land_read", lambda code: None)
    r = SRV._syn_row(_b(), {}, {}, {})
    assert r["per"] is None and r["per_pct"] is None and r["per_med"] is None and r["per_date"] is None
    assert r["per_filed"] == 12.0 and r["reliable"]
    monkeypatch.setattr(SRV, "_land_read", lambda code: {"v": 1, "error": "짧은 이력", "nsig": "x"})     # 부정 캐시
    r = SRV._syn_row(_b(), {}, {}, {})
    assert r["per"] is None and r["per_pct"] is None


# ---------------------------------------------------------------- forward 기록
def test_forward_writes_daily_file_with_spec_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    rows = [{"code": "A", "name": "에이", "reliable": True, "stage": "잠복", "score": 61.5, "btb": 1.3, "backlog_yoy": 40.0,
             "lead": 20.0, "per": 9.0, "per_pct": 30.0, "per_date": "20261013", "cheap": True, "loss4": False, "flags": ["희석 (2026-10-01)"]},
            {"code": "B", "name": "비", "reliable": False, "stage": "둔화", "score": None, "btb": None, "backlog_yoy": -5.0,
             "lead": None, "per": None, "per_pct": None, "per_date": None, "cheap": False, "loss4": True, "flags": []}]
    p = SRV._syn_forward(rows, day="20261015")
    assert p == os.path.join(str(tmp_path), "시너지", "forward", "20261015.json") and os.path.exists(p)
    with open(p, encoding="utf-8") as fh:
        d = json.load(fh)
    assert d["spec"] == SRV.SYN_SPEC and "loss4" in d["spec"] and d["at"] > 0 and d["n"] == 2
    a, b = d["rows"]
    assert set(a) == {"code", "name", "reliable", "stage", "score", "btb", "backlog_yoy", "lead", "per", "per_pct", "per_date", "cheap", "loss4", "n_flags"}
    assert a["cheap"] is True and a["n_flags"] == 1 and a["per_pct"] == 30.0
    assert a["per_date"] == "20261013" and b["per_date"] is None                 # per · per_pct 의 주가 날짜(풍경 계산일) — 채점 기준(2026-10-15)
    assert b["cheap"] is False and b["loss4"] is True and b["score"] is None
    # 같은 날 다시 쓰면 덮어쓴다
    SRV._syn_forward(rows[:1], day="20261015")
    with open(p, encoding="utf-8") as fh:
        assert json.load(fh)["n"] == 1


def test_forward_row_cheap_uses_cheap_filter():
    rc = SRV.SYN.SYN_REC[0]
    assert rc["id"] == "cheap"
    r = {"code": "A", "name": "에이", "reliable": True, "stage": "잠복", "btb": 1.2, "lead": 20.0, "per_pct": 30.0, "margin4": 5.0,
         "backlog_yoy": 40.0, "cover_chg": 0.2, "gap": 20.0, "loss4": False, "flags": []}
    assert SRV._syn_cheap(r) is True
    assert SRV._syn_cheap(dict(r, per_pct=None)) is False
    assert SRV._syn_cheap(dict(r, stage="둔화")) is False


# ---------------------------------------------------------------- synergy_view — bt overall · no_slow
def _view_with_bt(monkeypatch, bt):
    monkeypatch.setattr(SRV, "_syn_bt", lambda: bt)
    monkeypatch.setitem(SRV.SYNERGY, "running", True)       # 시험에서 재계산 스레드를 띄우지 않게
    monkeypatch.setitem(SRV.SYNERGY, "rows", [])
    return SRV.synergy_view()


def test_synergy_view_passes_overall_and_no_slow(monkeypatch):
    bt = {"dates": 150, "stages": {"둔화": {"median": -1.4}}, "n": 9153, "firms": 171, "median": 2.3, "at": "20261015",
          "rec": {"cheap": {"n": 419}}, "overall": {"median": 2.3, "ci": [0.5, 4.2]}, "no_slow": {"median": 5.2, "ci": [2.6, 8.0]},
          "coverage": {"per_pct": 0.49}, "terciles": {"btb": {"spread": 12.2}}, "loss4": {"전체·적자": {"n": 2630, "median": 3.8}}}
    out = _view_with_bt(monkeypatch, bt)
    assert out["bt"]["overall"] == {"median": 2.3, "ci": [0.5, 4.2]}
    assert out["bt"]["no_slow"]["median"] == 5.2 and out["bt"]["coverage"] == {"per_pct": 0.49}
    assert out["bt"]["factors"] == {"btb": {"spread": 12.2}}
    assert out["bt"]["loss4"] == {"전체·적자": {"n": 2630, "median": 3.8}}          # 적자/흑자 표 재료(2026-10-15 리뷰 A-F4)
    assert out["rec"][0]["id"] == "cheap"


def test_synergy_view_old_report_without_overall_does_not_crash(monkeypatch):
    bt = {"dates": 150, "stages": {}, "n": 8911, "firms": 156, "median": 2.5, "at": "20261007", "rec": {}}
    out = _view_with_bt(monkeypatch, bt)
    assert out["bt"]["overall"] is None and out["bt"]["no_slow"] is None and out["bt"]["factors"] == {}
    assert out["bt"]["loss4"] is None                                              # 옛 보고엔 없다 — 화면은 빈 객체로 받아 표를 안 그린다
    out = _view_with_bt(monkeypatch, None)
    assert "bt" not in out


# ---------------------------------------------------------------- 2026-10-20 v3 — 위험 표지 · 점수 부분 정의 · v3 검증 표
def test_risk_flags_read_s12_from_disclosure_risk(monkeypatch):
    d = {"codes": {"A": {"name": "에이", "s12": {"CB발행": {"n": 1, "last": "20260901"}, "횡령배임": {"n": 2, "last": "20260310"}}},
                   "B": {"name": "비", "level": None}}}
    monkeypatch.setattr(SRV, "_disc_risk", lambda: d)
    assert SRV._syn_risk_flags("A") == ["희석 — CB 발행 (12개월, 마지막 2026-09-01)", "부실 — 횡령·배임 (12개월, 마지막 2026-03-10)"]
    assert SRV._syn_risk_flags("B") == [] and SRV._syn_risk_flags("Z") == []      # s12 없음 · 목록 밖 = 표지 없음
    monkeypatch.setattr(SRV, "_disc_risk", lambda: None)                          # 공시위험.json 이 없을 때
    assert SRV._syn_risk_flags("A") == []


def test_disclosure_risk_tool_counts_the_same_categories():
    """도구/공시위험.py 의 s12 범주 = 시너지.RISK_DIL + RISK_BAD — 서버 표지와 백테스트 표지가 같은 범주를 센다."""
    src = open(os.path.join(BASE, "도구", "공시위험.py"), encoding="utf-8").read()
    i = src.index("S12_CATS = (")
    cats = eval(src[i + len("S12_CATS = "):src.index(")", i) + 1])
    assert tuple(cats) == SRV.SYN.RISK_DIL + SRV.SYN.RISK_BAD


def test_synergy_view_passes_parts_def_and_v3(monkeypatch):
    bt = {"dates": 150, "stages": {}, "n": 8662, "firms": 169, "median": 2.5, "at": "20261020", "rec": {},
          "v3": {"m1": {"spread": 10.7, "label": "근거 있음"}, "paired": {"diff": 4.1, "verdict": "차이를 확신할 수 없다"}}}
    out = _view_with_bt(monkeypatch, bt)
    assert [p["key"] for p in out["parts_def"]] == ["수주", "값", "여지"] and out["risk_pen"] == 10
    assert out["bt"]["v3"]["m1"]["label"] == "근거 있음"
    out = _view_with_bt(monkeypatch, {"dates": 150, "stages": {}, "n": 1, "firms": 1, "median": 0, "at": "x", "rec": {}})
    assert out["bt"]["v3"] is None                                                 # 옛 보고 — 화면은 v3 표를 안 그린다


def test_spec_names_v3():
    assert SRV.SYN_SPEC.startswith("2026-10-20 v3") and "loss4" in SRV.SYN_SPEC

# -*- coding: utf-8 -*-
"""수출 선행 발굴 서버 — 가짜 캐시로 exlead_view · value_view 배지(2026-10-14).
설계 docs/superpowers/specs/2026-10-14-export-lead-value-design.md 4절, 계획 Task 3."""
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
    monkeypatch.setattr(SRV, "VAL_DIR", str(tmp_path))  # 저장된 실제 저평가 결과(_result.json)를 읽지 않게
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


def test_exlead_uses_saved_value_red_even_before_value_tab(world):
    # 저평가 결과를 아직 메모리에 안 읽었어도(VAL 비어 있음) 저장분 _result.json 의 빨간불을 쓴다 — /api/exlead 를 먼저 열어도 같은 등급
    saved = {"v": SRV.VAL_V, "at": 5, "n_fell": 0, "n_univ": 0,
             "rows": [{"code": "000001", "name": "가짜", "tier": "관찰", "score": 40, "red": ["부채비율 240% — 200% 넘는 빚"]}]}
    with open(os.path.join(str(world), "_result.json"), "w", encoding="utf-8") as fh:
        json.dump(saved, fh)
    SRV._EXL.update(key=None, d=None)
    r = {x["code"]: x for x in SRV.exlead_view()["rows"]}["000001"]
    assert r["tier"] == "관찰" and r["checks"]["red"] is True and r["why"] == ["빨간불: 부채비율 240% — 200% 넘는 빚"]
    assert SRV.VAL["at"] == 5                                      # 저장분이 메모리에 올라왔다(계산 스레드는 없다)


def test_value_rows_get_export_badge(world, monkeypatch):
    monkeypatch.setattr(SRV, "VAL", {"rows": [{"code": "000001", "name": "가짜", "tier": "저평가", "score": 60, "red": []}], "at": 1, "running": False})
    monkeypatch.setattr(SRV, "_val_score_spec", lambda: None)
    SRV._EXL.update(key=None, d=None)
    rows = SRV.value_view()["rows"]
    assert rows[0]["exl"]["tier"] == "발굴" and rows[0]["exl"]["cur"] == 50.0 and rows[0]["exl"]["months_label"] == "7~8월"

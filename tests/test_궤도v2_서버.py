# -*- coding: utf-8 -*-
"""서버 궤도 v2 배선 — orbit2_view(캐시 없는 회사도 빈 칸으로 답한다) · 라우트 · 밤 훅 · 조회 전용에서 내 기록 비움 · 주가 요약 · 업종 PER 중앙. 서버를 띄우지 않고 모듈만 읽는다."""
import os
import sys
import json
import importlib.util as ilu

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("서버_궤도v2_시험", os.path.join(BASE, "서버.py"))
SRV = ilu.module_from_spec(_sp)
_sp.loader.exec_module(SRV)


def _src():
    with open(os.path.join(BASE, "서버.py"), "r", encoding="utf-8") as fh:
        return fh.read()


def _company(tmp_path, monkeypatch, reports=None):
    """캐시 폴더를 빈 임시 폴더로 — 모든 재료가 '없음'인 회사."""
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "ORB2_DIR", str(tmp_path / "궤도v2"))
    monkeypatch.setattr(SRV, "ORD_DIR", str(tmp_path / "수주공시"))
    monkeypatch.setattr(SRV, "_INDF", {})
    monkeypatch.setattr(SRV, "_DRISK", {"mt": None, "d": None})
    c = {"code": "000001", "name": "시험회사", "count": 2, "reports": reports or [
        {"stamp": "2026-03", "label": "분기보고서", "tag": "", "rcept": "20260515000001"},
        {"stamp": "2026-06", "label": "반기보고서", "tag": "", "rcept": "20260814000001"}]}
    monkeypatch.setattr(SRV, "INDEX", {"companies": [c], "built": 0})
    # 바깥을 부를 수 있는 것들은 막는다
    monkeypatch.setattr(SRV, "_druck_read", lambda code: None)
    monkeypatch.setattr(SRV, "_land_read", lambda code: None)
    monkeypatch.setattr(SRV, "_px_file", lambda code: {})
    monkeypatch.setattr(SRV, "_orbit_sum_rows", lambda c: None)
    monkeypatch.setattr(SRV, "_ord_series", lambda c, budget=0, net=True: [])
    monkeypatch.setattr(SRV, "_watch_backlog", lambda c, rev, asb=None: {})
    def _no_net(*a, **k):          # 요청 경로에서 DART · 네이버를 부르는 것들은 불리면 안 된다(리뷰 2026-10-21)
        raise AssertionError("요청 경로에서 네트워크 함수가 불렸다")
    monkeypatch.setattr(SRV, "invest_view", _no_net)
    monkeypatch.setattr(SRV, "_inv_expect", _no_net)
    monkeypatch.setattr(SRV, "_beads_path", lambda name: str(tmp_path / "신호판" / name))
    monkeypatch.setattr(SRV, "_story_path", lambda code: str(tmp_path / "story" / (code + ".json")))
    return c


def test_view_without_any_cache_answers_with_empty_slots(monkeypatch, tmp_path):
    _company(tmp_path, monkeypatch)
    v = SRV.orbit2_view("000001")
    assert v["code"] == "000001" and v["px"] is None and v["val"] is None and v["beads"] is None
    assert [x["key"] for x in v["drivers"]] in ([], ["risk"])           # 캐시가 없어도 '공시 위험 — 해당 없음' 한 줄은 설 수 있다(최신 보고서)
    assert v["verdict"]["partial"] == "both" and v["verdict"]["cell"] is None and v["verdict"]["base"] is None
    assert v["verdict"]["biz_line"] == "가속도 자료 없음" and v["verdict"]["px_line"] == "주가 자료 없음"
    assert v["quarters"] == [] and v["series"] == [] and v["strip"] == [] and v["ledger"] == [] and v["cells"] is None
    assert v["next"]["stamp"] == "2026-09" and v["next"]["label"] == "분기보고서" and v["report"]["rcept"] == "20260814000001"
    assert SRV.orbit2_view("없는코드") is None


def test_view_reads_cells_and_beads_row_and_industry_median(monkeypatch, tmp_path):
    _company(tmp_path, monkeypatch)
    (tmp_path / "궤도v2").mkdir()
    (tmp_path / "궤도v2" / "cells.json").write_text(json.dumps({"at": 1.0, "cells": {"up·cheap": {"n": 50, "firms": 20, "med": 2.0, "ci": [0.5, 3.5], "hit": 55, "early": 1.0, "late": 2.5}}, "primary": None}), encoding="utf-8")
    (tmp_path / "신호판").mkdir()
    rows = [{"code": "000001", "industry": "전기장비", "per": 60.0, "beads": {"val": {"pct": 20.0, "per": 60.0, "date": "20261010"}}, "gates": [{"name": "위험", "why": "CB"}], "k": 0, "k_ref": 0, "n_known": 1, "why": []},
            {"code": "000002", "industry": "전기장비", "per": 10.0}, {"code": "000003", "industry": "전기장비", "per": 20.0}, {"code": "000004", "industry": "전기장비", "per": 400.0}]
    (tmp_path / "신호판" / "_result.json").write_text(json.dumps({"asof": "20261010", "rows": rows}), encoding="utf-8")
    pts = [{"n": 8100 + i, "label": "2024Q%d" % (i % 4 + 1), "year": 2024, "q": i % 4 + 1, "fs": "CFS", "기준일": "2024%02d14" % (i + 1), "매출액": 100.0, "매출_TTM": 400.0 + i, "영업이익_TTM": 40.0,
            "영업이익": 10.0, "영업이익_전": 9.0, "가속B": 5.0, "국면": "확장 가속", "주가": 1000.0, "PER_TTM": 20.0 - i, "품질": []} for i in range(10)]   # PER 이 내려와 마지막이 가장 싸다
    monkeypatch.setattr(SRV, "_druck_read", lambda code: {"points": pts, "basis": "매출"})
    monkeypatch.setattr(SRV, "_beads_gap", lambda code, px: {"dm": 1.0, "dp": -10.0, "label": "2024Q2", "d": "20241014"})
    v = SRV.orbit2_view("000001")
    assert v["ind_per"] == {"name": "전기장비", "n": 3, "med": 20.0}            # PER 400 은 뺀다
    assert v["val"]["src"].startswith("가속도") and abs(v["val"]["pct"] - 10) < 1e-9 and v["val"]["label"] == "2024Q2"     # 공시일 PER 11 = 열 중 가장 싸다(칸 기준)
    assert v["val_now"] is None and v["verdict"]["cell"] == "up·cheap" and "50회(20곳)" in v["verdict"]["base"]
    assert v["gap"]["color"] == "blue" and v["verdict"]["gap_line"].startswith("엇갈림 파랑") and v["verdict"]["gate_line"] == "빨간불: 위험 — CB"
    assert len(v["series"]) == 10 and len(v["quarters"]) == 8 and v["cells"]["cells"]["up·cheap"]["n"] == 50


def test_px_summary_and_monthly_and_readonly_mine(monkeypatch, tmp_path):
    px = {"20250102": 100.0, "20250131": 110.0, "20250228": 120.0, "20251231": 150.0, "20260115": 200.0, "20260116": 180.0}
    P = SRV._orb2_px(px)
    assert P["d"] == "20260116" and P["px"] == 180.0 and P["hi"] == 200.0 and abs(P["dd"] + 10) < 1e-9 and P["r12"] is None       # 1년 전 봉이 열흘 밖
    assert [m["d"] for m in SRV._orb2_monthly(px)] == ["20250131", "20250228", "20251231", "20260116"]       # 같은 달은 마지막 봉만
    assert SRV._orb2_px({}) is None and SRV._orb2_monthly(None) == []
    monkeypatch.setattr(SRV, "READONLY", True)
    assert SRV._orb2_mine("000001") == {}
    assert SRV.orb2_kick() is False


def test_route_and_nightly_hook_are_wired():
    src = _src()
    assert 'if path == "/api/orbit2":' in src and "orbit2_view(q.get(\"code\", \"\"))" in src
    assert "_orb2_nightly()" in src.split("def _druck_auto_loop")[1].split("\ndef ")[0]
    assert "orbit2:viewOrbit2" in open(os.path.join(BASE, "웹", "index.html"), encoding="utf-8").read()

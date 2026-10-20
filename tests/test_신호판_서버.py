# -*- coding: utf-8 -*-
"""서버 신호판 배선 — 파일 서빙(beads_view) · 시너지 재료 되돌림(forward) · 엇갈림 재료 · 스캔 일지 거르기 · 라우트 · 조회 전용. 서버를 띄우지 않고 모듈만 읽는다."""
import os
import sys
import json
import time
import importlib.util as ilu

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("서버_신호판_시험", os.path.join(BASE, "서버.py"))
SRV = ilu.module_from_spec(_sp)
_sp.loader.exec_module(SRV)


def _dir(monkeypatch, tmp_path):
    monkeypatch.setattr(SRV, "BEADS_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "_INDF", {})
    monkeypatch.setattr(SRV, "BEADS", {"running": False, "at": 0, "secs": None, "error": None})


def test_view_without_files_kicks_once_and_has_definitions(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    kicks = []
    monkeypatch.setattr(SRV, "beads_kick", lambda: kicks.append(1) or True)
    v = SRV.beads_view()
    assert v["result"] is None and v["bt"] is None and kicks == [1]
    assert [b["key"] for b in v["beads_def"]] == ["exp", "su", "earn", "text", "gap", "val", "dip", "chain", "chart", "rep"]
    assert v["base_keys"] == ["su", "gap", "val", "dip", "chain"] and v["th"]["val_pct"] == 30 and len(v["gates_def"]) == 3


def test_view_reads_result_and_does_not_kick_when_fresh(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    kicks = []
    monkeypatch.setattr(SRV, "beads_kick", lambda: kicks.append(1) or True)
    (tmp_path / "_result.json").write_text(json.dumps({"at": time.time(), "rows": [{"code": "000001", "k": 2}], "n": 1}), encoding="utf-8")
    (tmp_path / "bt.json").write_text(json.dumps({"primary": {"label": "근거 약함"}}), encoding="utf-8")
    v = SRV.beads_view()
    assert v["result"]["rows"][0]["k"] == 2 and v["bt"]["primary"]["label"] == "근거 약함" and kicks == []
    SRV.beads_view(True)
    assert kicks == [1]                                   # force 는 다시 계산한다
    (tmp_path / "_result.json").write_text(json.dumps({"at": time.time() - 7 * 3600, "rows": []}), encoding="utf-8")
    os.utime(tmp_path / "_result.json", (time.time() + 5, time.time() + 5))
    SRV.beads_view()
    assert kicks == [1, 1]                                # 6시간 넘게 묵으면 다시


def test_readonly_never_kicks(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    monkeypatch.setattr(SRV, "READONLY", True)
    assert SRV.beads_kick() is False
    kicks = []
    monkeypatch.setattr(SRV, "beads_kick", lambda: kicks.append(1) or True)
    assert SRV.beads_view()["readonly"] is True and kicks == []


def test_syn_rows_fall_back_to_forward_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(SRV, "SYNERGY", {"running": False, "rows": [], "at": 0})
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    fw = tmp_path / "시너지" / "forward"
    fw.mkdir(parents=True)
    (fw / "20261019.json").write_text(json.dumps({"at": 1.0, "rows": [{"code": "000001", "reliable": True, "stage": "점화", "p_su": 71.2, "cover_chg": 0.4, "btb": 1.8, "score": 60}]}), encoding="utf-8")
    (fw / "20261018.json").write_text(json.dumps({"at": 0.5, "rows": [{"code": "000001", "reliable": True, "stage": "둔화"}]}), encoding="utf-8")
    rows, src, at = SRV._beads_syn_rows()
    assert src == "forward 20261019" and rows["000001"]["p_su"] == 71.2 and rows["000001"]["stage"] == "점화" and at == 1.0
    monkeypatch.setattr(SRV, "SYNERGY", {"running": False, "rows": [{"code": "000002", "reliable": True, "stage": "잠복", "parts": {"수주": 80.0}, "btb": 2.0}], "at": 9.0})
    rows, src, at = SRV._beads_syn_rows()
    assert src == "메모리" and rows["000002"]["p_su"] == 80.0 and at == 9.0


def test_syn_forward_rows_carry_p_su(monkeypatch, tmp_path):
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    p = SRV._syn_forward([{"code": "000001", "name": "가", "reliable": True, "stage": "점화", "parts": {"수주": 66.7, "값": 50, "여지": 40}, "cover_chg": 0.3, "flags": []}], day="20261020")
    j = json.load(open(p, encoding="utf-8"))
    assert j["rows"][0]["p_su"] == 66.7 and j["rows"][0]["cover_chg"] == 0.3 and j["rows"][0]["n_flags"] == 0


def test_gap_material_from_druck_points(monkeypatch):
    pts = [{"n": 8100 + i, "label": "%dQ%d" % ((8100 + i) // 4, (8100 + i) % 4 + 1), "영업이익_TTM": 100 + i * 5, "매출_TTM": 1000, "기준일": "20260814"} for i in range(6)]
    monkeypatch.setattr(SRV, "_druck_read", lambda code: {"points": pts})
    lab = pts[-1]["label"]
    y, q = int(lab[:4]), int(lab[5:])
    qe = "%04d%02d%02d" % (y, 3 * q, (31, 30, 30, 31)[q - 1])
    yago = (SRV.dt.datetime.strptime(qe, "%Y%m%d") - SRV.dt.timedelta(days=365)).strftime("%Y%m%d")
    px = {yago: 100.0, qe: 80.0}
    g = SRV._beads_gap("000001", px)
    assert g["label"] == lab and abs(g["dm"] - 2.0) < 1e-9 and abs(g["dp"] + 20.0) < 1e-9 and g["d"] == "20260814"
    assert SRV.KM.gap_of(g["dm"], g["dp"]) == "blue"
    assert SRV._beads_gap("000001", {})["dp"] is None                   # 주가 없으면 dp 없음 → 자료 없는 신호


def test_chart_journal_latest_day_only_and_stage_filter(monkeypatch, tmp_path):
    p = tmp_path / "journal.csv"
    today = SRV.dt.date.today().strftime("%Y%m%d")
    p.write_text("﻿asof,code,name,market,pattern,stage,pivot,stop,composite,rs,close,value,leader,rule\n"
                 "20260101,000001,가,KOSPI,cup_with_handle,base,,,,,,,,rule1\n"
                 "%s,000001,가,KOSPI,ma60_supply,,,,,,,,,ma60s_v1\n%s,000002,나,KOSDAQ,trendline_break,failed,,,,,,,,tlbrk_v1\n%s,000003,다,KOSDAQ,old,,,,,,,,,\n" % (today, today, today), encoding="utf-8")
    monkeypatch.setattr(SRV, "_score_journal_path", lambda: str(p))
    by, last, fresh = SRV._beads_chart()
    assert last == today and fresh and list(by) == ["000001"] and by["000001"][0]["pattern"] == "ma60_supply"


def test_route_and_nightly_hook_present():
    src = open(os.path.join(BASE, "서버.py"), encoding="utf-8").read()
    assert 'if path == "/api/beads":' in src and "beads_kick()" in src.split("def _val_auto_loop")[1].split("def ")[0]

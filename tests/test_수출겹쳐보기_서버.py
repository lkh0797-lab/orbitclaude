# -*- coding: utf-8 -*-
"""서버 수출 겹쳐보기 배선 — 만든 HTML 이름 규칙(하위 폴더 · 다른 확장자 막기) · 목록(섹터 순서) · 밤 갱신 판정 · 조회 전용 · 라우트. 서버를 띄우지 않는다."""
import os
import sys
import json
import time
import importlib.util as ilu

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("서버_수출겹쳐보기_시험", os.path.join(BASE, "서버.py"))
SRV = ilu.module_from_spec(_sp)
_sp.loader.exec_module(SRV)


def _dir(monkeypatch, tmp_path):
    monkeypatch.setattr(SRV, "OVL_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "OVL", {"running": None, "at": None, "rc": None, "py": None, "secs": None, "error": None})


def test_file_name_rule_blocks_traversal_and_other_types(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    (tmp_path / "semiconductor.html").write_text("<p>x</p>", encoding="utf-8")
    (tmp_path / "수출겹쳐보기.html").write_text("<p>x</p>", encoding="utf-8")
    (tmp_path / "run.log").write_text("log", encoding="utf-8")
    (tmp_path / "_summary").mkdir()
    (tmp_path / "_summary" / "a.html").write_text("x", encoding="utf-8")
    assert SRV._ovl_file("semiconductor.html") and SRV._ovl_file("수출겹쳐보기.html")
    for bad in ("run.log", "../서버.py", "_summary/a.html", "..\\x.html", "a b.html", "", None, "없음.html"):
        assert SRV._ovl_file(bad) is None, bad


def test_view_lists_index_radar_and_sectors_in_preset_order(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    assert SRV.overlay_view()["index"] is None and SRV.overlay_view()["sectors"] == []
    sd = tmp_path / "_summary"
    sd.mkdir()
    for key, name in (("steel", "철강"), ("semiconductor", "반도체"), ("orphan", "고아")):
        (sd / (key + ".json")).write_text(json.dumps({"key": key, "name": name}), encoding="utf-8")
    for fn in ("steel.html", "semiconductor.html", "수출겹쳐보기.html", "변곡점레이더.html"):
        (tmp_path / fn).write_text("x", encoding="utf-8")
    v = SRV.overlay_view()
    assert v["index"] == "수출겹쳐보기.html" and v["radar"] == "변곡점레이더.html" and v["index_at"]
    keys = [x["key"] for x in v["sectors"]]
    assert keys == ["semiconductor", "steel"] and v["sectors"][0]["name"] == "반도체"    # 요약만 있고 화면 없는 섹터는 뺀다 · 프리셋 순


def test_nightly_runs_only_when_index_is_old_or_missing(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    runs = []
    monkeypatch.setattr(SRV, "_ovl_run", lambda args=(): runs.append(1) or True)
    assert SRV._ovl_nightly() is True and runs == [1]
    (tmp_path / "수출겹쳐보기.html").write_text("x", encoding="utf-8")
    assert SRV._ovl_nightly() is False and runs == [1]
    old = time.time() - SRV.OVL_MAX_AGE - 60
    os.utime(tmp_path / "수출겹쳐보기.html", (old, old))
    assert SRV._ovl_nightly() is True and runs == [1, 1]


def test_readonly_never_kicks_and_route_is_wired(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    monkeypatch.setattr(SRV, "READONLY", True)
    assert SRV.ovl_kick() is False
    assert SRV._ro_block("/api/overlay", {"run": "1"}) and SRV._ro_block("/overlay/x.html", {}) is None
    with open(os.path.join(BASE, "서버.py"), "r", encoding="utf-8") as fh:
        src = fh.read()
    assert 'if path == "/api/overlay":' in src and 'path.startswith("/overlay/")' in src
    assert "_ovl_nightly()" in src.split("def _druck_auto_loop")[1].split("\ndef ")[0]
    with open(os.path.join(BASE, "웹", "index.html"), "r", encoding="utf-8") as fh:
        assert "ovl:viewOverlay" in fh.read()


def test_package_output_dir_is_what_the_server_serves():
    from export_overlay import config
    assert os.path.normcase(str(config.OUTPUT_DIR)) == os.path.normcase(os.path.join(BASE, ".cache", "수출겹쳐보기"))
    assert os.path.normcase(str(config.CACHE_DIR)) == os.path.normcase(os.path.join(BASE, ".cache", "export_overlay"))

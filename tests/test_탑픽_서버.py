# -*- coding: utf-8 -*-
"""서버 탑픽 배선 — 파일 서빙(toppick_view) · 밤 갱신 판정(_toppick_nightly) · 실행 잠금(toppick_kick). 서버를 띄우지 않고 모듈만 읽어, 자식 프로세스는 가짜로."""
import os, sys, json, time, importlib.util as ilu
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("서버_탑픽_시험", os.path.join(BASE, "서버.py"))
SRV = ilu.module_from_spec(_sp); _sp.loader.exec_module(SRV)


def _dir(monkeypatch, tmp_path):
    monkeypatch.setattr(SRV, "TOPPICK_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "_INDF", {})
    monkeypatch.setattr(SRV, "TOPPICK", {"running": None, "mode": None, "at": None, "rc": None, "py": None, "secs": None, "error": None})


def test_view_without_files_is_empty_but_has_thresholds(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    v = SRV.toppick_view()
    assert v["latest"] is None and v["bt"] is None and v["files"] == {"latest": None, "bt": None}
    assert v["th"]["c1"] == 30.0 and v["th_name"]["c1"] == "C1 괴리" and v["run"]["running"] is None


def test_view_reads_files_and_caches_by_mtime(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    (tmp_path / "latest.json").write_text(json.dumps({"rows": [{"code": "000001"}], "asof": "20260101"}), encoding="utf-8")
    (tmp_path / "bt.json").write_text(json.dumps({"dates": ["20140131", "20260930"]}), encoding="utf-8")
    v = SRV.toppick_view()
    assert v["latest"]["asof"] == "20260101" and v["bt"]["dates"][0] == "20140131" and v["files"]["latest"]
    (tmp_path / "latest.json").write_text(json.dumps({"rows": [], "asof": "20260102"}), encoding="utf-8")
    os.utime(tmp_path / "latest.json", (time.time() + 5, time.time() + 5))
    assert SRV.toppick_view()["latest"]["asof"] == "20260102"            # mtime 이 바뀌면 다시 읽는다


def test_nightly_runs_full_when_bt_missing_or_old(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(SRV, "_toppick_run", lambda mode="latest": calls.append(mode) or True)
    SRV._toppick_nightly()
    (tmp_path / "bt.json").write_text("{}", encoding="utf-8")
    SRV._toppick_nightly()
    old = time.time() - SRV.TOPPICK_BT_MAX_AGE - 10
    os.utime(tmp_path / "bt.json", (old, old))
    SRV._toppick_nightly()
    assert calls == ["full", "latest", "full"]


def test_kick_refuses_while_running(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    started = []
    monkeypatch.setattr(SRV.threading, "Thread", lambda target, args=(), daemon=None: type("T", (), {"start": lambda self: started.append(args)})())
    assert SRV.toppick_kick("latest") is True and started == [("latest",)]
    SRV.TOPPICK["running"] = "latest"
    assert SRV.toppick_kick("full") is False and len(started) == 1


def test_run_falls_back_to_server_python_on_quick_failure(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    monkeypatch.setattr(SRV, "BT_PY", "py -3.13")
    seen = []

    class P:
        def __init__(self, rc):
            self.returncode = rc

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return P(103 if cmd[0] == "py" else 0)                              # 런처 103 = 3.13 없음 → 서버 파이썬으로
    monkeypatch.setattr(SRV.subprocess, "run", fake_run)
    assert SRV._toppick_run("latest") is True
    assert len(seen) == 2 and seen[1][0] == sys.executable and seen[1][-1] == "--latest" and "-X" in seen[1]
    assert SRV.TOPPICK["rc"] == 0 and SRV.TOPPICK["running"] is None and SRV.TOPPICK["mode"] == "latest"
    assert os.path.exists(tmp_path / "run.log")
    assert SRV._toppick_run("full") is True and seen[-1][-1].endswith("탑픽_백테스트.py")     # full 은 --latest 없이

# -*- coding: utf-8 -*-
"""서버 우량 급락 배선 — 파일 서빙 · 밤 갱신 판정 · 실행 잠금 · 자식 프로세스 대체. 서버를 띄우지 않고 모듈만 읽는다."""
import os, sys, json, time, importlib.util as ilu
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("서버_우량급락_시험", os.path.join(BASE, "서버.py"))
SRV = ilu.module_from_spec(_sp); _sp.loader.exec_module(SRV)


def _dir(mp, tmp_path):
    mp.setattr(SRV, "QUALDIP_DIR", str(tmp_path))
    mp.setattr(SRV, "_INDF", {})
    mp.setattr(SRV, "QUALDIP", {"running": None, "mode": None, "at": None, "rc": None, "py": None, "secs": None, "error": None})


def test_view_empty_then_reads_files(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    v = SRV.qualdip_view()
    assert v["latest"] is None and v["bt"] is None and v["causes"] is None and v["files"] == {"latest": None, "bt": None}
    (tmp_path / "latest.json").write_text(json.dumps({"asof": "20261019", "rows": []}), encoding="utf-8")
    (tmp_path / "origin_causes.json").write_text(json.dumps({"by": {}}), encoding="utf-8")
    v = SRV.qualdip_view()
    assert v["latest"]["asof"] == "20261019" and v["causes"] == {"by": {}} and v["files"]["latest"]


def test_nightly_full_when_bt_missing_or_old(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(SRV, "_qualdip_run", lambda mode="latest": calls.append(mode) or True)
    SRV._qualdip_nightly()
    (tmp_path / "bt.json").write_text("{}", encoding="utf-8")
    SRV._qualdip_nightly()
    old = time.time() - SRV.QUALDIP_BT_MAX_AGE - 10
    os.utime(tmp_path / "bt.json", (old, old))
    SRV._qualdip_nightly()
    assert calls == ["full", "latest", "full"]


def test_run_falls_back_and_passes_latest_flag(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    monkeypatch.setattr(SRV, "BT_PY", "py -3.13")
    seen = []

    class P:
        def __init__(self, rc):
            self.returncode = rc
    monkeypatch.setattr(SRV.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or P(103 if cmd[0] == "py" else 0))
    assert SRV._qualdip_run("latest") is True
    assert len(seen) == 2 and seen[1][0] == sys.executable and seen[1][-1] == "--latest" and seen[1][-2].endswith("우량급락_백테스트.py")
    assert SRV.QUALDIP["rc"] == 0 and SRV.QUALDIP["running"] is None and SRV.QUALDIP["mode"] == "latest"
    assert SRV._qualdip_run("full") is True and seen[-1][-1].endswith("우량급락_백테스트.py")
    SRV.QUALDIP["running"] = "full"
    assert SRV.qualdip_kick("latest") is False and SRV._qualdip_run("latest") is False

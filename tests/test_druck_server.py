# -*- coding: utf-8 -*-
"""서버 druck() 배선 — 서버를 띄우지 않고 모듈만 읽어 시험한다(회사 색인 · DART · 네이버는 가짜로)."""
import os, sys, time, copy, importlib.util as ilu
import pytest
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("서버_시험", os.path.join(BASE, "서버.py"))
SRV = ilu.module_from_spec(_sp); _sp.loader.exec_module(SRV)
DRK = SRV.DRK


# ---------------------------------------------------------------- 미캐시 결과 기억(DRUCK_SOFT)
def test_fresh_error_memo_only_for_bg_lookups(monkeypatch):
    monkeypatch.setattr(SRV, "_druck_read", lambda code: None)
    monkeypatch.setattr(SRV, "DRUCK_SOFT", {"000001": (time.time(), "v2:x", {"error": "e"}, "error")})
    assert SRV._druck_fresh("000001", "v2:x") is None                    # 동기 호출은 오류 기억에 막히지 않는다
    assert SRV._druck_fresh("000001", "v2:x", bg=True) == {"error": "e"}


def test_fresh_transient_memo_for_everyone_until_ttl(monkeypatch):
    monkeypatch.setattr(SRV, "_druck_read", lambda code: None)
    res = {"points": [{"n": 1}], "transient": 2}
    monkeypatch.setattr(SRV, "DRUCK_SOFT", {"000001": (time.time(), "v2:x", res, "transient")})
    assert SRV._druck_fresh("000001", "v2:x") is res and SRV._druck_fresh("000001", "v2:x", bg=True) is res
    assert SRV._druck_fresh("000001", "v2:y") is None                    # 새 보고서(sig 바뀜)
    SRV.DRUCK_SOFT["000001"] = (time.time() - SRV.DRUCK_SOFT_TTL - 1, "v2:x", res, "transient")
    assert SRV._druck_fresh("000001", "v2:x") is None                    # TTL 지남


def test_kick_stale_once_per_code(monkeypatch):
    calls = []
    monkeypatch.setattr(SRV, "druck", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(SRV, "DRUCK_STALE_KICKED", set())
    assert SRV._druck_kick_stale("005930") is True
    assert SRV._druck_kick_stale("005930") is False
    assert SRV._druck_kick_stale("000660") is True
    assert calls == [(("005930", True), {"wait": False}), (("000660", True), {"wait": False})]


def test_no_secret_masks_keys_and_flattens():
    msg = SRV._no_secret("ConnectionError: url /api/x.json?crtfc_key=ABCDEF123&corp_code=1\n  more")
    assert "ABCDEF123" not in msg and "crtfc_key=***" in msg and "\n" not in msg


# ---------------------------------------------------------------- druck() 빌드 — 가짜 회사 · 가짜 series
REPS = [{"stamp": s, "label": lb, "tag": "", "rcept": rc, "sections": []}
        for s, lb, rc in (("2025-03", "분기보고서", "20250515000001"), ("2025-06", "반기보고서", "20250814000002"))]
PTS = [{"year": 2025, "q": 1, "label": "2025Q1", "n": 2025 * 4, "품질": [], "fs": "CFS", "매출액": 100.0},
       {"year": 2025, "q": 2, "label": "2025Q2", "n": 2025 * 4 + 1, "품질": [], "fs": "CFS", "매출액": 110.0}]


@pytest.fixture
def fake_co(monkeypatch, tmp_path):
    c = {"code": "000001", "name": "가짜", "reports": copy.deepcopy(REPS)}
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "company_by_code", lambda code: c if code == "000001" else None)
    monkeypatch.setattr(SRV, "corp_code_of", lambda code: "00000001")
    monkeypatch.setattr(SRV, "_share_events", lambda code: [("20260901", "주식분할결정")])
    monkeypatch.setattr(SRV, "DRUCK_SOFT", {})
    monkeypatch.setattr(SRV, "DRUCK_LOCKS", {})
    monkeypatch.setattr(SRV, "DRUCK_BUILDING", {})
    seen = []

    def series(corp, code, years, meta=None, offline=False, progress=None):
        DRK.LAST.update(transient=0, fy_bad=[], error=None)
        for i in range(1, 9):
            progress(i, 8)
        seen.append(dict(meta))
        return copy.deepcopy(PTS)
    monkeypatch.setattr(DRK, "series", series)
    return c, seen, tmp_path


def ok_prices(pts, code, dates):
    for p in pts:
        d = dates.get((p["year"], p["q"]))
        if d:
            p["주가"], p["주가일"] = 10000.0, d
    return pts


def test_druck_writes_cache_with_split_after_and_progress(fake_co, monkeypatch):
    c, seen, tmp = fake_co
    monkeypatch.setattr(DRK, "attach_prices", ok_prices)
    SRV.DRUCK_BUILDING["000001"] = {"done": 0, "total": 0}               # bg 요청이 걸어 둔 칸
    out = SRV.druck("000001")
    assert out["transient"] == 0 and out["v"] == DRK.VERSION and out["basis"] == "매출"
    assert out["split_after"] == [{"date": "20260901", "title": "주식분할결정"}]
    assert SRV.DRUCK_BUILDING["000001"] == {"done": 8, "total": 8}
    assert seen[0]["filed"] == {2025 * 4: "20250515", 2025 * 4 + 1: "20250814"}
    assert SRV._druck_read("000001")["sig"] == out["sig"]


def test_druck_price_failure_is_transient_and_not_cached(fake_co, monkeypatch):
    c, seen, tmp = fake_co
    monkeypatch.setattr(DRK, "attach_prices", lambda pts, code, dates: pts)     # fetch_prices 가 {} — 주가 하나도 없음
    out = SRV.druck("000001")
    assert out["transient"] == 1 and len(out["points"]) == 2
    assert not os.path.exists(os.path.join(str(tmp), "druck", "000001.json"))
    assert SRV.DRUCK_SOFT["000001"][3] == "transient"


def test_druck_transient_rebuild_returns_old_marked(fake_co, monkeypatch):
    c, seen, tmp = fake_co
    monkeypatch.setattr(DRK, "attach_prices", ok_prices)
    first = SRV.druck("000001")
    monkeypatch.setattr(DRK, "attach_prices", lambda pts, code, dates: pts)
    again = SRV.druck("000001", force=True)
    assert again["transient"] == 1 and again["points"] == first["points"]          # 예전 캐시 + '새로 못 받음' 표시
    assert SRV._druck_read("000001")["transient"] == 0                             # 디스크는 그대로


def test_druck_write_failure_returns_uncached(fake_co, monkeypatch, capsys):
    c, seen, tmp = fake_co
    monkeypatch.setattr(DRK, "attach_prices", ok_prices)
    monkeypatch.setattr(DRK, "write_cache", lambda path, obj: False)
    out = SRV.druck("000001")
    assert out["transient"] == 0 and len(out["points"]) == 2
    assert "000001" in capsys.readouterr().out and SRV._druck_read("000001") is None


# ---------------------------------------------------------------- 밤 미리 계산(_druck_prebuild)
import datetime as _dt


def test_bt_cmd_splits_launcher_and_quoted_windows_path():
    assert SRV._bt_cmd("py -3.13") == ["py", "-3.13"]
    exe = r"C:\Program Files\Python313\python.exe"
    assert SRV._bt_cmd('"%s" -X utf8' % exe) == [exe, "-X", "utf8"]
    assert SRV._bt_cmd("") == [sys.executable]


def _co(code, *rcepts):
    return {"code": code, "name": code, "reports": [{"rcept": r, "stamp": "2025-03", "label": "분기보고서", "tag": ""} for r in rcepts]}


def test_druck_order_cached_first_then_recent_filers_then_no_reports():
    comps = [_co("A", "20240101000001"), _co("B", "20250301000001", "20250515000002"), _co("C"), _co("D", "20250601000001"),
             _co("E", "20230101000001")]
    order = SRV._druck_order(comps, lambda code: code in ("A", "E"))
    assert [c["code"] for c in order] == ["A", "E", "D", "B", "C"]


def test_druck_deadline_is_next_six_oclock():
    d = _dt.datetime
    assert SRV._druck_deadline(d(2026, 10, 10, 2, 0)) == d(2026, 10, 10, 6, 0)
    assert SRV._druck_deadline(d(2026, 10, 10, 0, 50)) == d(2026, 10, 10, 6, 0)
    assert SRV._druck_deadline(d(2026, 10, 10, 6, 0)) == d(2026, 10, 11, 6, 0)
    assert SRV._druck_deadline(d(2026, 10, 10, 14, 0)) == d(2026, 10, 11, 6, 0)


@pytest.fixture
def prebuild(monkeypatch, tmp_path):
    """가짜 색인 다섯 회사 · 가짜 druck — 시계는 호출마다 1시간씩 간다(02:00 → 03:00 → …)."""
    comps = [_co(c, "2025060%d000001" % i) for i, c in enumerate(("A", "B", "C", "D", "E"), 1)]
    monkeypatch.setattr(SRV, "INDEX", {"companies": comps})
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "DRUCK_PRE", {"at": None, "done": 0, "total": 0, "net": 0, "running": False})
    monkeypatch.setattr(SRV, "_druck_read", lambda code: {"sig": SRV._druck_sig(SRV.company_by_code(code))} if code == "E" else None)
    calls, budgets = [], []

    def fake_druck(code, force=False, offline=False, wait=True):
        calls.append((code, offline))
        budgets.append(DRK.NET["budget"])
        DRK.NET["used"] += 3
        return {"B": {"transient": 1}, "C": {"error": "x"}}.get(code, {"points": []})
    monkeypatch.setattr(SRV, "druck", fake_druck)
    monkeypatch.setattr(DRK, "NET", {"budget": None, "used": 0})
    t = [_dt.datetime(2026, 10, 10, 2, 0)]

    def clock():
        t[0] += _dt.timedelta(hours=1)
        return t[0]
    return comps, calls, budgets, clock


def test_prebuild_counts_and_restores_budget(prebuild):
    comps, calls, budgets, _ = prebuild
    clock = lambda: _dt.datetime(2026, 10, 10, 2, 30)          # noqa: E731 — 시간이 안 간다
    assert SRV._druck_prebuild(now=clock, run_bt=False) is True
    P = SRV.DRUCK_PRE
    assert [c for c, _ in calls] == ["E", "D", "C", "B", "A"][1:] and all(off for _, off in calls)     # E 는 이미 지금 sig — 건너뜀
    assert set(budgets) == {SRV.DRUCK_NET_BUDGET}
    assert (P["done"], P["total"], P["fresh"], P["built"], P["transient"], P["failed"], P["net"]) == (5, 5, 1, 2, 1, 1, 12)
    assert P["running"] is False and P["stopped"] is None and P["at"] and DRK.NET == {"budget": None, "used": 0}


def test_prebuild_stops_at_six(prebuild):
    comps, calls, budgets, clock = prebuild
    assert SRV._druck_prebuild(now=clock, run_bt=False) is True
    # start 03:00 → 마감 06:00. 회사마다 시계를 한 번 본다: 04:00 · 05:00 → 두 회사, 06:00 에 멈춤
    assert SRV.DRUCK_PRE["stopped"] == "06:00" and SRV.DRUCK_PRE["done"] == 2 and len(calls) == 1      # 첫 회사 E 는 fresh
    assert SRV.DRUCK_PRE["running"] is False


def test_prebuild_not_reentrant(prebuild):
    SRV.DRUCK_PRE["running"] = True
    assert SRV._druck_prebuild(run_bt=False) is False

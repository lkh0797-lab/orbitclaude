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

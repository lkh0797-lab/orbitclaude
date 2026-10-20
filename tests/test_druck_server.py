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


# ---------------------------------------------------------------- 최종 검토 고침(2026-10-10)
def test_druck_newest_filed_quarter_missing_is_transient(fake_co, monkeypatch):
    """오늘 공시된 분기의 원장이 시리즈에 없다(공시 당일 DART 013) — 새 서명으로 굳히지 않는다(다음 조회 · 다음 밤에 다시 받는다)."""
    c, seen, tmp = fake_co
    c["reports"].append({"stamp": "2025-09", "label": "분기보고서", "tag": "", "rcept": time.strftime("%Y%m%d") + "000003", "sections": []})
    monkeypatch.setattr(DRK, "attach_prices", ok_prices)
    out = SRV.druck("000001")
    assert out["transient"] == 1 and len(out["points"]) == 2
    assert not os.path.exists(os.path.join(str(tmp), "druck", "000001.json"))


def test_druck_basis_from_recent_quarters_for_financials(fake_co, monkeypatch):
    """금융(KSIC 64~66)이고 최근 8개 자료 분기에 매출액이 없으면 영업이익 기준 — 옛 분기에 매출이 있어도(IFRS17 뒤 보험사)."""
    c, seen, tmp = fake_co
    monkeypatch.setattr(DRK, "attach_prices", ok_prices)
    old = [{"year": 2016 + i // 4, "q": i % 4 + 1, "label": "x", "n": 2016 * 4 + i, "품질": [], "fs": "CFS", "매출액": 100.0} for i in range(8)]
    new = [dict(p, 매출액=None, 영업이익=10.0) for p in copy.deepcopy(PTS)]
    new = [dict(p, n=2016 * 4 + 8 + i, year=2018, q=i + 1, label="2018Q%d" % (i + 1)) for i, p in enumerate(new * 4)][:8]
    monkeypatch.setattr(DRK, "series", lambda corp, code, years, meta=None, offline=False, progress=None: copy.deepcopy(old + new))
    monkeypatch.setattr(SRV, "_ksic_of", lambda corp: "65110")
    assert SRV.druck("000001", force=True)["basis"] == "영업이익"
    monkeypatch.setattr(SRV, "_ksic_of", lambda corp: "26110")
    assert SRV.druck("000001", force=True)["basis"] == "매출"                         # 금융이 아니면 매출


def test_druck_split_after_blanks_per_history(fake_co, monkeypatch):
    """마지막 자료 분기 뒤 분할 공시(20260901) — 분할 뒤 첫 보고서까지 모든 분기 PER_TTM 을 비워 캐시한다."""
    c, seen, tmp = fake_co

    def priced(pts, code, dates):
        ok_prices(pts, code, dates)
        for p in pts:
            p["EPS_TTM"], p["PER_TTM"] = 1000.0, 10.0
        return pts
    monkeypatch.setattr(DRK, "attach_prices", priced)
    out = SRV.druck("000001")
    assert out["split_after"] and all("PER_TTM" not in p for p in out["points"])
    assert all("PER_TTM" not in p for p in SRV._druck_read("000001")["points"])
    monkeypatch.setattr(SRV, "_share_events", lambda code: [])
    assert all(p["PER_TTM"] == 10.0 for p in SRV.druck("000001", force=True)["points"])


def test_druck_now_gives_reason_without_eps_and_skips_price_fetch(monkeypatch):
    class _F:
        @staticmethod
        def fetch_prices(code):
            raise AssertionError("EPS_TTM 이 없으면 주가를 받지 않는다")
    monkeypatch.setattr(SRV, "FIN", _F)
    monkeypatch.setattr(SRV, "corp_code_of", lambda code: "00000001")
    monkeypatch.setattr(SRV, "_ksic_of", lambda corp: "64190")
    pts = [qp(y, q, fs="CFS", 지배순이익=1e12) for y, q in ((2025, 3), (2025, 4), (2026, 1), (2026, 2))]
    now = SRV._druck_now("105560", {"points": pts})
    assert now["per"] is None and now["reason"].startswith("금융사 주식 수 산출 불가") and now["last"] == "2026Q2"


def test_bg_thread_start_failure_leaves_no_stuck_entry(fake_co, monkeypatch):
    """스레드를 못 띄우면(32비트 'can't start new thread') 진행 칸 · 다시 쌓기 표시를 거두고 예외를 올린다 — 화면이 영영 '쌓는 중'이 되지 않게."""
    class _Boom:
        def __init__(self, *a, **kw):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")
    monkeypatch.setattr(SRV.threading, "Thread", _Boom)
    monkeypatch.setattr(SRV, "DRUCK_STALE_KICKED", set())
    with pytest.raises(RuntimeError):
        SRV.druck("000001", wait=False)
    assert "000001" not in SRV.DRUCK_BUILDING
    with pytest.raises(RuntimeError):
        SRV._druck_kick_stale("000001")
    assert "000001" not in SRV.DRUCK_STALE_KICKED and "000001" not in SRV.DRUCK_BUILDING


def test_industry_stocks_sends_order_up_down_and_spread(monkeypatch, tmp_path):
    """산업 '섹터 안 종목' — 수주 업종 ▲ 만이 아니라 ▼ 와 ▲−▼ 도 보낸다(같은 업종 상승이 둘 다 덮는지 보이게)."""
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "_INDF", {})
    monkeypatch.setattr(SRV, "IND", dict(SRV.IND, data={"sectors": []}))
    order = {"B_up": {"n": 177, "med": 13.1}, "B_dn": {"n": 180, "med": 14.0}, "B_spread": {"diff": -0.9, "ci": [-8.2, 9.2]}, "x": 1}
    _write_json(os.path.join(str(tmp_path), "druck_bt", "bt_accel.json"), dict(BT_FILE, ev_order=order))
    assert SRV.industry_sub("stocks", "")["bt"]["order"] == {k: order[k] for k in ("B_up", "B_dn", "B_spread")}


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


def test_prebuild_drops_uncached_memo(prebuild, monkeypatch):
    comps, calls, budgets, _ = prebuild
    soft = {"Z": (0, "v2:z", {}, "transient")}                      # 다른 회사(화면 폴링) 기억은 그대로
    monkeypatch.setattr(SRV, "DRUCK_SOFT", soft)

    def fake(code, force=False, offline=False, wait=True):
        res = {"B": {"transient": 1}, "C": {"error": "x"}}.get(code, {"points": []})
        if code in ("B", "D"):
            SRV.DRUCK_SOFT[code] = (0, "sig", res, "transient")
        return res
    monkeypatch.setattr(SRV, "druck", fake)
    SRV._druck_prebuild(now=lambda: _dt.datetime(2026, 10, 10, 2, 30), run_bt=False)
    assert "B" not in soft and "Z" in soft and "D" in soft             # D 는 깨끗한 빌드(가짜가 남긴 기억은 druck 몫)


def test_prebuild_after_budget_skips_only_companies_needing_network(prebuild, monkeypatch):
    """예산이 끝난 뒤엔 원장을 새로 받아야 하는 회사만 건너뛰고(다음 밤), 받을 것이 없는 회사는 계속 쌓는다(2026-10-10 최종 검토 S2)."""
    comps, calls, budgets, _ = prebuild
    asked = []

    def fake(code, force=False, offline=False, wait=True):
        calls.append((code, offline))
        DRK.NET["used"] += SRV.DRUCK_NET_BUDGET // 2
        return {"points": []}
    monkeypatch.setattr(SRV, "druck", fake)
    monkeypatch.setattr(SRV, "_druck_needs_net", lambda c: asked.append(c["code"]) or c["code"] == "B")
    SRV._druck_prebuild(now=lambda: _dt.datetime(2026, 10, 10, 2, 30), run_bt=False)
    P = SRV.DRUCK_PRE
    assert [c for c, _ in calls] == ["D", "C", "A"]                   # E 는 fresh, D · C 에서 예산 끝 → B(받을 것 있음)만 건너뜀
    assert asked == ["B", "A"]                                         # 예산이 남아 있는 동안은 묻지 않는다
    assert (P["fresh"], P["built"], P["skipped_budget"], P["done"]) == (1, 3, 1, 5)


def test_druck_needs_net_reads_ledger_files_with_meta(monkeypatch):
    c = {"code": "000001", "reports": [{"stamp": "2024-03", "label": "분기보고서", "tag": "", "rcept": "20240515000001"},
                                       {"stamp": "2025-06", "label": "반기보고서", "tag": "[기재정정]", "rcept": "20251020000002"}]}
    got = []
    monkeypatch.setattr(SRV, "corp_code_of", lambda code: "00000001" if code == "000001" else None)
    monkeypatch.setattr(DRK, "needs_net", lambda corp, years, meta: got.append((corp, years, meta)) or True)
    assert SRV._druck_needs_net(c) is True
    assert got[0][0] == "00000001" and got[0][1] == [2024, 2025]
    assert got[0][2]["filed"] == {2024 * 4: "20240515"} and got[0][2]["amend"] == {(2025, 2): "20251020"}
    assert SRV._druck_needs_net({"code": "999999", "reports": []}) is False         # 고유번호 없음 — 쌓으면 오류로 끝난다


class _P:
    def __init__(self, rc):
        self.returncode = rc


def test_run_bt_falls_back_when_64bit_launcher_fails_fast(monkeypatch, tmp_path):
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "BT_PY", "py -3.13")
    ran = []
    monkeypatch.setattr(SRV.subprocess, "run", lambda cmd, **kw: ran.append(cmd[0]) or _P(103 if cmd[0] == "py" else 0))
    res = SRV._druck_run_bt()
    assert ran == ["py", sys.executable] and res["py"] == sys.executable and res["rc"] == 0
    log = (tmp_path / "druck_bt" / "bt_run.log").read_text(encoding="utf-8")
    assert "실행: py -3.13" in log and "코드 103" in log and "실행: " + sys.executable in log


def test_run_bt_no_fallback_on_slow_failure_or_success(monkeypatch, tmp_path):
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "BT_PY", "py -3.13")
    monkeypatch.setattr(SRV, "BT_QUICK_FAIL", 0)                      # 어떤 실패도 '곧바로'가 아니다 — 스크립트 자체 실패는 다시 안 돈다
    ran = []
    monkeypatch.setattr(SRV.subprocess, "run", lambda cmd, **kw: ran.append(cmd[0]) or _P(1))
    assert SRV._druck_run_bt()["py"] == "py -3.13" and ran == ["py"]
    ran.clear()
    monkeypatch.setattr(SRV, "BT_QUICK_FAIL", 20)
    monkeypatch.setattr(SRV.subprocess, "run", lambda cmd, **kw: ran.append(cmd[0]) or _P(0))
    assert SRV._druck_run_bt()["rc"] == 0 and ran == ["py"]


# ---------------------------------------------------------------- 소비처 — 같은 B · 분기 키(Task 7)
def qp(y, q, **kw):
    """가속도 캐시 점 하나(분기 키 n 포함)."""
    return dict({"year": y, "q": q, "label": "%dQ%d" % (y, q), "n": y * 4 + q - 1, "품질": []}, **kw)


def test_inv_ttm_reads_druck_cache_by_quarter_key(monkeypatch):
    # 2024Q2 가 목록에서 빠진(조밀하지 않은) 캐시 — 순번 i − 4 는 2024Q1 을 집지만 키 n − 4 는 2024Q2 가 없어 g 를 내지 않는다
    pts = [qp(2024, 1, 매출_TTM=100.0), qp(2024, 3, 매출_TTM=110.0), qp(2024, 4, 매출_TTM=120.0),
           qp(2025, 1, 매출_TTM=125.0), qp(2025, 2, 매출_TTM=140.0, 속도=12.0, 가속B=4.5, 국면="확장 가속", 변곡="▲", PER_TTM=9.0, 주가=1000.0),
           qp(2025, 3, 매출_TTM=150.0)]
    monkeypatch.setattr(SRV, "_druck_read", lambda code: {"points": pts})
    t = SRV._inv_ttm("000001", "2025-06")
    assert (t["label"], t["s"], t["a"], t["reg"], t["turn"], t["price"], t["per"]) == ("2025Q2", 12.0, 4.5, "확장 가속", "▲", 1000.0, 9.0)
    assert t["g"] is None and t["per_pct"] is None                                   # PER 기록 8개 미만
    assert SRV._inv_ttm("000001", "2025-09")["g"] == pytest.approx((150 / 110 - 1) * 100)   # 2024Q3 은 키로 있다
    assert SRV._inv_ttm("000001", "2023-12") is None
    monkeypatch.setattr(SRV, "_druck_read", lambda code: None)                       # 옛 버전 · 없음 — 쌓지 않는다
    assert SRV._inv_ttm("000001", "2025-06") is None and SRV._inv_regimes("000001") == []


def test_inv_ttm_per_pct_skips_cut_quarters(monkeypatch):
    pts = [qp(2023 + i // 4, i % 4 + 1, PER_TTM=float(v)) for i, v in enumerate([1, 2, 3, 4, 5, 6, 7, 8, 9])]
    pts[0]["품질"] = ["cut"]                                                            # 분할 보정 못 한 분기 — 견주지 않는다
    monkeypatch.setattr(SRV, "_druck_read", lambda code: {"points": pts})
    t = SRV._inv_ttm("000001", "2025-03")                                             # 9번째 점(2025Q1, PER 9)
    assert t["per_pct"] == 100.0                                                      # 나머지 8개 가운데 가장 높다


def test_inv_regimes_are_seven_phase_names_with_key_growth(monkeypatch):
    pts = [qp(2024, 1, 매출_TTM=100.0), qp(2024, 2), qp(2024, 3), qp(2024, 4),
           qp(2025, 1, 매출_TTM=130.0, 속도=10.0, 가속B=-4.0, 국면="둔화"), qp(2025, 2, 품질=["fy"])]
    monkeypatch.setattr(SRV, "_druck_read", lambda code: {"points": pts})
    r = SRV._inv_regimes("000001")
    assert len(r) == 6 and r[4] == {"label": "2025Q1", "g": pytest.approx(30.0), "s": 10.0, "a": -4.0, "reg": "둔화"}
    assert r[5]["reg"] is None and r[5]["g"] is None


@pytest.fixture
def screen_co(monkeypatch):
    c = {"code": "000001", "name": "가짜", "reports": []}
    monkeypatch.setattr(SRV, "corp_code_of", lambda code: "00000001")
    return c


def test_screen_row_from_cache_uses_quarter_keys_and_b(monkeypatch, screen_co):
    pts = [qp(2024, 2, 매출액=90.0, 매출_TTM=380.0, 당기순이익=5.0),
           qp(2024, 3, 매출액=95.0, 당기순이익=6.0, 재고일수=50.0, 매출가속=-2.0),
           qp(2024, 4, 품질=["gap"]),                                                     # 4분기 빈칸 — 순이익 4분기 합은 못 낸다
           qp(2025, 1, 매출액=100.0, 당기순이익=7.0, 재고일수=48.0, 매출가속=1.0),
           qp(2025, 2, 매출액=110.0, 당기순이익=8.0, 재고일수=45.0, 매출가속=3.0, 매출YoY=20.0, 매출_TTM=420.0,
              가속B=5.0, 속도=-1.0, 국면="회복", 변곡="▲", PER_TTM=12.0),
           qp(2025, 3, 품질=["fy"]), qp(2025, 4, 품질=["fy"])]                         # 끝에 붙은 빈 fy 점 — '지금'이 아니다
    monkeypatch.setattr(SRV, "_druck_read", lambda code: {"points": pts})
    r = SRV.screen_row(screen_co)
    assert r["quarter"] == "2025Q2" and r["가속B"] == 5.0 and r["속도"] == -1.0 and r["국면"] == "회복" and r["변곡"] == "▲"
    assert r["전환"] is True and r["전환종류"] == "역성장완화"                          # 속도 < 0 이면 '덜 나빠짐'
    assert r["매출가속"] == 3.0 and r["전분기가속"] == 1.0                              # C 키는 그대로(시너지)
    assert r["재고일수변화"] == -3.0 and r["매출_TTM_1년전"] == 380.0 and r["순이익_TTM"] is None
    assert r["PER_TTM"] == 12.0


def test_screen_row_turn_needs_band_crossing_not_c_sign(monkeypatch, screen_co):
    pts = [qp(2025, 1, 매출액=100.0, 매출가속=-1.0), qp(2025, 2, 매출액=110.0, 매출가속=2.0, 가속B=2.0, 속도=5.0, 변곡=None)]
    monkeypatch.setattr(SRV, "_druck_read", lambda code: {"points": pts})
    r = SRV.screen_row(screen_co)
    assert r["전환"] is False and r["전환종류"] is None                                # 옛 판정(C 가 − → +)이면 전환이었다


def test_screen_row_without_cache_builds_series_per_share_accel_prices(monkeypatch, screen_co):
    screen_co["reports"] = [{"stamp": "2025-06", "label": "반기보고서", "tag": "", "rcept": "20250814000001"}]
    calls = []
    raw = [qp(2024, q, 매출액=100.0 + q, 매출YoY=10.0) for q in (1, 2, 3, 4)] + [qp(2025, q, 매출액=120.0 + q, 매출YoY=25.0) for q in (1, 2)]
    for p in raw:
        p["YoY_r"] = p["매출YoY"]
    monkeypatch.setattr(SRV, "_druck_read", lambda code: None)
    monkeypatch.setattr(SRV, "_share_events", lambda code: [("20250101", "주식분할결정")])
    monkeypatch.setattr(DRK, "series", lambda corp, code, years, meta=None, offline=False: calls.append(("series", offline, dict(meta["filed"]))) or raw)
    monkeypatch.setattr(DRK, "per_share", lambda pts, sev: calls.append(("per_share", sev)) or pts)

    def prices(pts, code, dates):
        calls.append(("prices", dates))
        return pts
    monkeypatch.setattr(DRK, "attach_prices", prices)
    r = SRV.screen_row(screen_co)
    assert [x[0] for x in calls] == ["series", "per_share", "prices"]
    assert calls[0][1] is True and calls[0][2] == {2025 * 4 + 1: "20250814"}             # offline · 원본 공시일 meta
    assert calls[1][1] == [("20250101", "주식분할결정")] and calls[2][1] == {(2025, 2): "20250814"}
    assert r["가속B"] == pytest.approx(15.0) and r["국면"] == "확장 가속"                  # 진짜 accel: 속도 25 − 앞 2분기 10


def test_score_rows_ranks_b_not_c():
    rows = [{"가속B": 10.0, "매출가속": -9.0}, {"가속B": 0.0, "매출가속": 0.0}, {"가속B": -10.0, "매출가속": 9.0}]
    SRV.score_rows(rows)
    assert rows[0]["score"] > rows[1]["score"] > rows[2]["score"]


def test_screen_response_says_weights_unvalidated(monkeypatch):
    monkeypatch.setattr(SRV, "SCREEN", {"rows": [{"x": 1}], "done": 1, "total": 1, "running": False, "years": 4, "built": 1})
    assert SRV.screen()["score_note"] == "가중 50/30/20 — 검증 안 됨"


def test_earnings_yoy_matches_same_quarter_by_key(monkeypatch, screen_co):
    class _F:
        fetch_consensus = staticmethod(lambda code, period: {"cols": [], "rows": {}})
        consensus_history = staticmethod(lambda code, period: {})
    monkeypatch.setattr(SRV, "FIN", _F)
    seen = {}

    def series(corp, code, years, meta=None, offline=False):
        seen.update(offline=offline, meta=meta)
        return [qp(2024, 1, 매출액=100.0), qp(2024, 2, 품질=["gap"]), qp(2024, 3, 매출액=120.0), qp(2024, 4, 매출액=130.0),
                qp(2025, 1, 매출액=110.0), qp(2025, 2, 매출액=150.0)]
    monkeypatch.setattr(DRK, "series", series)
    out = SRV.earnings(screen_co, "q", 10)
    yy = {r["key"]: (r["yoy"] or {}).get("매출액") for r in out["rows"]}
    assert "202406" not in yy                                                          # 값 없는 분기는 칸을 만들지 않는다
    assert yy["202503"] == pytest.approx(10.0) and yy["202506"] is None               # 순번 4칸 전이면 2024Q1(+50%)을 집었다
    assert seen["offline"] is True and set(seen["meta"]) == {"filed", "fy_bad", "amend"}


def test_dip_points_cache_first_then_short_series_keeps_gap_points(monkeypatch, screen_co):
    monkeypatch.setattr(SRV, "_druck_read", lambda code: {"points": [qp(2025, 1, 매출액=1.0), {"품질": []}]})
    assert [p["label"] for p in SRV._dip_points(screen_co)] == ["2025Q1"]
    screen_co["reports"] = [{"stamp": "2025-03", "label": "분기보고서", "tag": "", "rcept": "20250515000001"}]
    monkeypatch.setattr(SRV, "_druck_read", lambda code: None)
    monkeypatch.setattr(DRK, "series", lambda corp, code, years, meta=None, offline=False: [qp(2025, 1, 매출액=1.0), qp(2025, 2, 품질=["gap"])])
    got = {}
    monkeypatch.setattr(DRK, "attach_prices", lambda pts, code, dates: got.update(dates) or pts)
    assert [p["label"] for p in SRV._dip_points(screen_co)] == ["2025Q1", "2025Q2"] and got == {(2025, 1): "20250515"}


def test_checked_call_is_coloured_only_for_the_pass_wording():
    ok = {"word": SRV.EV_PASS, "diff": 2.0}
    assert SRV._checked_call("up", "가속", ok) == {"tone": "up", "text": "가속", "ev": ok}
    for ev in ({"word": "뚜렷하나 기간마다 달랐다"}, {"word": "통계적으로 뚜렷하지 않음"}, None):
        c = SRV._checked_call("up", "가속", ev)
        assert c["tone"] == "nu" and c["text"] == "가속 (검증 안 됨)" and c["ev"] is ev
    assert SRV._ev_word(1.0, [0.2, 2.0], 0.5, 0.7) == SRV.EV_PASS


def test_lens_value_b_call_neutral_when_lens_fails(monkeypatch):
    c = {"code": "000001", "name": "가짜", "reports": []}
    monkeypatch.setattr(SRV, "company_by_code", lambda code: c)
    monkeypatch.setattr(SRV, "corp_code_of", lambda code: "00000001")
    monkeypatch.setattr(SRV, "matrix_cached", lambda *a, **kw: {})
    monkeypatch.setattr(SRV, "_guru_hit_for", lambda code: None)
    R = {"2026Q2": {"shares": 10.0, "rev_ttm": 1000.0, "eps_ttm": 10.0}}
    monkeypatch.setattr(SRV, "_pipe_rows", lambda *a, **kw: {"labs": ["2026Q2"], "rows": R, "px": {"p": [50.0], "d": [20261008]}})
    monkeypatch.setattr(SRV, "_druck_read", lambda code: {"points": [qp(2026, 2, 가속B=4.8, 속도=34.0, 국면="확장 가속")]})
    bt = {"rules": {SRV.DRUCK_LENS: {"n_on": 4093, "diff": 1.2, "ci": [-0.2, 2.9], "early": 1.4, "late": 1.4}}}
    monkeypatch.setattr(SRV, "_lens_bt", lambda: bt)
    call = next(x for x in SRV.lens_value("000001")["calls"] if "가속(B)" in x["text"])
    assert call["tone"] == "nu" and call["text"].endswith(" (검증 안 됨)")
    bt["rules"][SRV.DRUCK_LENS]["ci"] = [0.3, 2.9]                                    # 통과 — 초록
    call = next(x for x in SRV.lens_value("000001")["calls"] if "가속(B)" in x["text"])
    assert call["tone"] == "up" and "검증 안 됨" not in call["text"]


def test_lens_rule_name_is_b():
    assert SRV.LENS_RULES["스탠리 드러켄밀러"][0] == SRV.DRUCK_LENS == "드러켄밀러 · 가속(B) +3%p↑"


def test_inflect_cache_key_carries_druck_version(monkeypatch, tmp_path):
    c = {"code": "000001", "name": "가짜", "reports": [{"rcept": "20250814000001"}]}
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "company_by_code", lambda code: c)
    monkeypatch.setattr(SRV, "corp_code_of", lambda code: "00000001")
    monkeypatch.setattr(SRV, "FIN", object())
    sig = "20250814000001_v%d_%s:%d" % (SRV.INF.VERSION, SRV.dt.date.today().strftime("%Y%m%d"), DRK.VERSION)
    os.makedirs(os.path.join(str(tmp_path), "inflect"))
    with open(os.path.join(str(tmp_path), "inflect", "000001.json"), "w", encoding="utf-8") as fh:
        SRV.json.dump({"sig": sig, "hit": True}, fh)
    assert SRV.inflect("000001") == {"sig": sig, "hit": True}                       # DRK.VERSION 이 바뀌면 이 캐시는 안 맞는다


# ---------------------------------------------------------------- 변곡점 — 가속 전환 사건 · 드러켄밀러 카드(같은 B)
INF = SRV.INF


def test_inflect_event_is_b_turn_up_with_positive_speed():
    qs = [qp(2024, 1, 가속B=-5.0, 속도=8.0, rcept="r1"), qp(2024, 2, 가속B=4.0, 속도=9.0, 변곡="▲", rcept="r2"),
          qp(2024, 3, 가속B=-6.0, 속도=-2.0, 변곡="▼", rcept="r3"), qp(2024, 4, 가속B=5.0, 속도=-1.0, 변곡="▲", rcept="r4")]
    ev = [e for e in INF.events([], qs, [], [], [], {}) if e["title"].startswith("분기 매출 가속 전환")]
    assert len(ev) == 1 and ev[0]["title"] == "분기 매출 가속 전환 (2024Q2)"           # 속도 < 0 인 ▲ 은 사건이 아니다
    assert ev[0]["rcept"] == "r2" and ev[0]["prev_rcept"] == "r1" and "가속(B) +4.0%p" in ev[0]["detail"]


def test_last_quarters_is_a_key_window():
    qs = [qp(2023, q, 매출YoY=1.0) for q in (1, 2, 3, 4)] + [qp(2024, q) for q in (1, 2)] + \
         [qp(2024, q, 매출YoY=2.0) for q in (3, 4)] + [qp(2025, 1, 품질=["fy"])]
    w = INF._last_quarters(qs, "매출YoY")
    assert [q["label"] for q in w] == ["2023Q1", "2023Q2", "2023Q3", "2023Q4", "2024Q1", "2024Q2", "2024Q3", "2024Q4"]
    assert INF._last_quarters([qp(2024, 1)], "매출YoY") == []


def _druck_card(quarters, price_info=None):
    return next(L for L in INF.lenses([], quarters, price_info or {}) if L["guru"] == "스탠리 드러켄밀러")


def test_druck_card_badge_series_and_descriptive_verdict():
    qs = [qp(2025, 1, 매출YoY=10.0, 가속B=2.5, 재고일수=60.0), qp(2025, 2, 매출YoY=20.0, 가속B=3.0, 속도=15.0, 국면="확장 가속",
                                                           엇갈림=True, 이익률변화=1.0, 재고일수=50.0)]
    card = _druck_card(qs)
    m = next(x for x in card["metrics"] if x["k"] == "매출 가속(B)")
    assert m["v"] == "+3.0%p" and [s["v"] for s in m["series"]] == [2.5, 3.0]
    assert card["grade"] == "강함"                                                     # B 3↑ · 이익률↑ · 재고일수↓ 셋 다
    assert card["verdict"] == "최근 분기(2025Q2) 속도 +15.0%, 가속(B) +3.0%p — 확장 가속. 이번 분기 단독은 반대로 움직였다. 재고일수 60일 → 50일."
    qs[1]["가속B"] = 2.9
    assert _druck_card(qs)["grade"] == "보통"                                           # 띠 안(+3%p 미만)은 가속이 아니다


def test_druck_card_how_reads_lens_bt_or_drops_sentence():
    qs = [qp(2025, 2, 매출YoY=20.0, 가속B=3.0, 속도=15.0, 국면="확장 가속")]
    how = _druck_card(qs)["clock"]["how"]
    assert "+5%p" not in how and "큰 표본" not in how                                   # 성적 파일이 없으면 문장을 뺀다
    ev = {"n": 1234, "diff": 1.8, "ci": [-0.4, 3.9], "word": "통계적으로 뚜렷하지 않음"}
    how = _druck_card(qs, {"druck_ev": ev})["clock"]["how"]
    assert "공시 1,234건" in how and "+1.8%p" in how and "(90% 구간 -0.4 ~ +3.9)" in how and "통계적으로 뚜렷하지 않음" in how


# ---------------------------------------------------------------- 가속도 탭 — 기저율(/api/druck/bt) · 사건(/api/druck/events)
def _write_json(path, obj):
    import json
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)


BT_FILE = {"at": "20261010", "n": 8269, "firms": 309, "base": {"ex12": 0.6}, "base_any": 0.6,
           "ev_all": {"B_up": {"n": 821, "firms": 291, "med": 2.0}, "B_dn": {"n": 829, "firms": 285, "med": 0.9}},
           "regime": {"B": {"확장 가속": {"n": 2450, "firms": 302, "med": 2.0, "dG4": 1.6}}},
           "phase7": {"labels": ["확장 가속"]}, "whip": {"B": {"pct": 23.0}}, "asfiled": {"n": 3003}}


def test_druck_bt_view_keeps_only_screen_keys_and_firm_counts_from_file(monkeypatch, tmp_path):
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "_INDF", {})
    assert SRV.druck_bt_view() == {"regime": None, "ev_all": None, "base_any": None, "firms": None, "n": None, "at": None}
    _write_json(os.path.join(str(tmp_path), "druck_bt", "bt_accel.json"), BT_FILE)
    v = SRV.druck_bt_view()
    assert set(v) == {"regime", "ev_all", "base_any", "firms", "n", "at"}
    assert v["regime"] == BT_FILE["regime"]["B"] and v["ev_all"] == BT_FILE["ev_all"]          # 7국면 칸은 regime.B 를 펴서
    assert (v["firms"], v["n"], v["base_any"], v["at"]) == (309, 8269, 0.6, "20261010")


def test_druck_bt_view_rereads_when_file_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "_INDF", {})
    p = os.path.join(str(tmp_path), "druck_bt", "bt_accel.json")
    _write_json(p, BT_FILE)
    assert SRV.druck_bt_view()["firms"] == 309
    _write_json(p, dict(BT_FILE, firms=877))
    os.utime(p, (time.time() + 5, time.time() + 5))                                            # mtime 이 바뀌면 다시 읽는다
    assert SRV.druck_bt_view()["firms"] == 877


def test_druck_events_returns_that_company_or_empty_lists(monkeypatch, tmp_path):
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "_INDF", {})
    assert SRV.druck_events("005930") == {"turns": [], "periods": []}                         # 파일 없음
    ev = {"005930": {"turns": [{"n": 8103, "dir": "▲", "date": "20260310", "ex6": 56.0, "ex12": None, "state": "진행 중"}],
                     "periods": [{"n": 8105, "d": "20260814", "d2": None, "ex": -2.2, "state": "진행 중"}]},
          "000660": {"turns": [], "periods": [{"n": 8104, "d": "20260515", "d2": "20260814", "ex": 3.0, "state": "done"}]}}
    _write_json(os.path.join(str(tmp_path), "druck_bt", "events.json"), ev)
    assert SRV.druck_events("005930") == ev["005930"]
    assert SRV.druck_events("000660") == {"turns": [], "periods": ev["000660"]["periods"]}
    assert SRV.druck_events("999999") == {"turns": [], "periods": []}
    assert SRV.druck_events("") == {"turns": [], "periods": []}


# ---------------------------------------------------------------- 증권사 분기 손익 대조 · 주간 주가(가속도 '한눈에' 판)
def _kp(n, rev=None, op=None, rev_p=None, op_p=None, year=None):
    p = {"n": n, "year": year or n // 4}
    if rev is not None: p["매출액"] = rev
    if op is not None: p["영업이익"] = op
    if rev_p is not None: p["매출액_전"] = rev_p
    if op_p is not None: p["영업이익_전"] = op_p
    return p


def test_kfin_check_prefers_restated_comparative_and_flags_over_2pct_and_1eok():
    n = 2024 * 4 + 2                                   # 2024Q3
    pts = [_kp(n, rev=100e9, op=10e9), _kp(n + 4, rev_p=103e9, op_p=10e9)]
    rows = [{"ym": "202409", "rev": 103e9, "op": 11e9}]
    chk, ncmp = SRV.kfin_check(pts, rows)
    assert ncmp == 2
    assert "rev" not in chk[str(n)]                    # 재작성 비교값(103e9)과 같다 — 그 분기 보고서 값(100e9)과는 3% 다르지만
    assert chk[str(n)]["op"] == {"dart": 10e9, "kis": 11e9, "pct": 10.0, "src": "재작성"}


def test_kfin_check_falls_back_to_filed_value_and_ignores_small_or_missing():
    n = 2025 * 4                                       # 2025Q1 — 다음 해 보고서 없음
    pts = [_kp(n, rev=1e9, op=None)]
    chk, ncmp = SRV.kfin_check(pts, [{"ym": "202503", "rev": 1.05e9, "op": 5e8}])
    assert ncmp == 1 and chk == {}                     # 5% 차이지만 1억 원 이하 · 영업이익은 DART 쪽 없음
    chk, _ = SRV.kfin_check(pts, [{"ym": "202503", "rev": 2e9, "op": None}])
    assert chk[str(n)]["rev"]["src"] == "공시" and chk[str(n)]["rev"]["pct"] == 100.0
    assert SRV.kfin_check(pts, [{"ym": "bad"}, {"ym": "202503"}]) == ({}, 0)


def test_kfin_view_trims_prices_to_a_year_before_first_quarter_and_reports_pending(monkeypatch):
    d = {"v": SRV.KFIN_V, "at": "x", "is_q": {"rows": [{"ym": "201903", "rev": 1, "op": 1}], "why": ""},
         "px": {"t": ["20090105", "20100104", "20110103", "20260119"], "c": [1, 2, 3, 4], "at": "a", "mkt": "UN"}}
    monkeypatch.setattr(SRV, "_kfin_read", lambda code: d)
    monkeypatch.setattr(SRV, "_kfin_kick", lambda code, stale=False: False)
    v = SRV.kfin_view("005930", [_kp(2011 * 4, rev=1), _kp(2026 * 4, rev=1)])
    assert v["px"]["t"] == ["20100104", "20110103", "20260119"] and v["px"]["c"] == [2, 3, 4]
    assert v["pending"] is False and v["is_from"] == "201903"
    monkeypatch.setattr(SRV, "_kfin_read", lambda code: None)
    monkeypatch.setattr(SRV, "_kfin_kick", lambda code, stale=False: True)
    v = SRV.kfin_view("005930", [])
    assert v["px"] is None and v["pending"] is True


def test_kfin_kick_respects_ttl_retry_and_readonly(monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(SRV, "_kfin_ok", lambda: True)
    monkeypatch.setattr(SRV, "_kfin_path", lambda code: str(tmp_path / (code + ".json")))
    monkeypatch.setattr(SRV.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda self: started.append(1)})())
    monkeypatch.setattr(SRV, "KFIN", {"running": False, "code": None, "queue": {}, "tried": {}, "sup": (0.0, False)})
    assert SRV._kfin_kick("005930") is True and started == [1]          # 파일 없음 → 받는다
    assert SRV._kfin_kick("005930") is True and started == [1]          # 이미 차례 — 다시 띄우지 않는다
    SRV.KFIN["queue"].clear(); SRV.KFIN["running"] = False
    (tmp_path / "000660.json").write_text("{}", encoding="utf-8")
    assert SRV._kfin_kick("000660") is False                            # 갓 받은 파일
    SRV.KFIN["tried"]["000270"] = (time.time(), 1, "실패")
    assert SRV._kfin_kick("000270") is False                            # 방금 실패 — 30분 쉼
    assert SRV._kfin_kick("../bad") is False
    monkeypatch.setattr(SRV, "READONLY", True)
    assert SRV._kfin_kick("035420") is False


def test_kfin_kick_unwinds_when_thread_cannot_start_and_refetches_old_version(monkeypatch, tmp_path):
    def boom(target, daemon):
        class T:
            def start(self):
                raise RuntimeError("can't start new thread")
        return T()
    monkeypatch.setattr(SRV, "_kfin_ok", lambda: True)
    monkeypatch.setattr(SRV, "_kfin_path", lambda code: str(tmp_path / (code + ".json")))
    monkeypatch.setattr(SRV, "KFIN", {"running": False, "code": None, "queue": {}, "tried": {}, "sup": (0.0, False)})
    monkeypatch.setattr(SRV.threading, "Thread", boom)
    assert SRV._kfin_kick("005930") is False
    assert SRV.KFIN["running"] is False and SRV.KFIN["queue"] == {}       # '받는 중'에 묶이지 않는다
    (tmp_path / "000660.json").write_text('{"v": 1}', encoding="utf-8")  # 갓 받은 옛 판 파일
    started = []
    monkeypatch.setattr(SRV.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda self: started.append(1)})())
    assert SRV._kfin_kick("000660") is False                            # 판을 모르면 그대로 둔다
    assert SRV._kfin_kick("000660", stale=True) is True and started == [1]   # 판이 달라 못 읽으면 묵지 않았어도 다시 받는다


# ---------------------------------------------------------------- 실적 발표 반응 · 업종 중앙값(가속도 '한눈에' 판)
def _days(start, n):
    import datetime as _dt
    d, out = _dt.date(*start), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d += _dt.timedelta(days=1)
    return out


def test_react_events_prefers_prelim_in_window_and_measures_vs_market():
    ds = _days((2025, 10, 1), 60)
    px = {d: 100.0 for d in ds}
    mkt = {d: 1000.0 for d in ds}
    i0 = ds.index("20251031")                       # 잠정실적 날(금)
    for j, d in enumerate(ds[i0:]):
        px[d] = 110.0 if j < 4 else 120.0           # 첫날 +10%, 5거래일째 +20%
        mkt[d] = 1010.0                              # 시장 +1%
    disc = [{"d": "20251031", "title": "연결재무제표기준영업(잠정)실적(공정공시)"},
            {"d": "20251101", "title": "[기재정정]연결재무제표기준영업(잠정)실적(공정공시)"},
            {"d": "20251020", "title": "영업(잠정)실적(공정공시)(자회사의 주요경영사항)"}]
    n = 2025 * 4 + 2                                 # 2025Q3
    pts = [{"n": n, "fs": "CFS", "기준일": "20251114"}, {"n": n + 1, "fs": None, "기준일": None}]
    ev = SRV.react_events(pts, disc, px, mkt)
    assert len(ev) == 1 and ev[0]["d"] == "20251031" and ev[0]["src"] == "잠정실적"
    assert ev[0]["r1"] == 10.0 and ev[0]["x1"] == 9.0 and ev[0]["r5"] == 20.0 and ev[0]["x5"] == 19.0


def test_react_events_falls_back_to_report_date_and_ignores_prelim_after_report():
    ds = _days((2025, 10, 1), 60)
    px = {d: 100.0 for d in ds}
    n = 2025 * 4 + 2
    disc = [{"d": "20251120", "title": "영업(잠정)실적(공정공시)"}]           # 정기보고서(11-14) 뒤 — 다음 분기 것일 수 있다
    ev = SRV.react_events([{"n": n, "fs": "OFS", "기준일": "20251114"}], disc, px, {})
    assert ev[0]["d"] == "20251114" and ev[0]["src"] == "정기보고서" and ev[0]["r1"] == 0.0 and "x1" not in ev[0]
    assert SRV.react_events([{"n": n, "fs": "OFS", "기준일": "20251114"}], None, {}, {})[0].get("r1") is None


def test_peer_view_median_excludes_self_and_needs_five(monkeypatch):
    monkeypatch.setattr(SRV, "_sector", lambda code: "반도체")
    rows = [("A%05d" % i, float(i), 10.0 + i) for i in range(6)] + [("005930", 99.0, 99.0)]
    cells = {"반도체": {8100: rows, 8101: rows[:4] + [("005930", 1.0, 1.0)]}}
    v = SRV.peer_view("005930", cells)
    assert v["sector"] == "반도체" and v["firms"] == 6
    assert v["med"]["8100"] == {"s": 2.5, "ks": 6, "m": 12.5, "km": 6}      # 자기(99) 빼고 0..5 중앙
    assert "8101" not in v["med"]                                         # 다른 회사 4곳뿐
    monkeypatch.setattr(SRV, "_sector", lambda code: None)
    assert SRV.peer_view("005930", cells)["sector"] is None


def test_idx_quarter_close_last_trading_day_of_each_quarter_through_today():
    import datetime as _dt
    idx = {"20250328": 100.0, "20250331": 101.0, "20250630": 110.0, "20250701": 111.0, "20251015": 120.0}
    pts = [{"n": 2025 * 4}, {"n": 2025 * 4 + 1}]
    mq = SRV.idx_quarter_close(idx, pts, today=_dt.date(2025, 10, 20))
    assert mq == {str(2025 * 4): 101.0, str(2025 * 4 + 1): 110.0, str(2025 * 4 + 2): 111.0, str(2025 * 4 + 3): 120.0}
    assert SRV.idx_quarter_close({}, pts) == {} and SRV.idx_quarter_close(idx, []) == {}

# -*- coding: utf-8 -*-
"""전 종목 미리 계산(2026-10-11) — 풍경 지난 판 먼저(SWR) · 부정 캐시 · 오류 창 · 저장 거부, 궤도 요약 캐시, /api/prebuild,
도구/전종목_미리계산.py(가짜 서버 모듈로 — DART · 드라이브 · 색인 쓰기 없음)."""
import os, sys, json, time, copy, types, datetime as dt, importlib.util as ilu
import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("서버_미리계산_시험", os.path.join(BASE, "서버.py"))
SRV = ilu.module_from_spec(_sp); _sp.loader.exec_module(SRV)
_tp = ilu.spec_from_file_location("전종목_미리계산", os.path.join(BASE, "도구", "전종목_미리계산.py"))
TOOL = ilu.module_from_spec(_tp); _tp.loader.exec_module(TOOL)

TODAY = dt.date.today().isoformat()
REPS = [{"stamp": s, "label": lb, "tag": "", "rcept": rc, "sections": []}
        for s, lb, rc in (("2024-12", "사업보고서", "20250310000001"), ("2025-03", "분기보고서", "20250515000002"),
                          ("2025-06", "반기보고서", "20250814000003"))]


@pytest.fixture
def co(monkeypatch, tmp_path):
    c = {"code": "000001", "name": "가짜", "dir": "가짜_000001", "reports": copy.deepcopy(REPS)}
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "company_by_code", lambda code: c if code == "000001" else None)
    monkeypatch.setattr(SRV, "LANDING", {})
    return c


# ---------------------------------------------------------------- 풍경: 지난 판 먼저(SWR)
def _payload(c, date, v=None):
    v = SRV.LAND_V if v is None else v
    return {"v": v, "code": c["code"], "rows": [1], "decide": {"pct": 40},
            "sig": "%s:%d:%s:%d" % (c["reports"][-1]["rcept"], len(c["reports"]), date, v)}


def _put(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)


@pytest.fixture
def kicks(monkeypatch):
    got = []
    monkeypatch.setattr(SRV, "_run_land", lambda code: got.append(code))
    return got


def test_land_fresh_cache_returned_as_is(co, kicks):
    _put(SRV._land_path("000001"), _payload(co, SRV._land_day()))     # 판의 날 = 가장 최근 장 마감 날
    d = SRV.landscape_view("000001")
    assert d["rows"] == [1] and "stale" not in d and kicks == []


def test_land_old_day_served_stale_and_rebuilt_once(co, kicks):
    _put(SRV._land_path("000001"), _payload(co, "2026-10-10"))
    d = SRV.landscape_view("000001")
    assert d["stale"] is True and d["stale_date"] == "2026-10-10" and d["refreshing"] is True and d["rows"] == [1]
    time.sleep(0.05)
    assert kicks == ["000001"]
    d2 = SRV.landscape_view("000001")              # 이미 돌고 있다 — 다시 띄우지 않는다
    assert d2["stale"] is True
    time.sleep(0.05)
    assert kicks == ["000001"]


def test_land_new_report_also_served_stale(co, kicks):
    _put(SRV._land_path("000001"), _payload(co, SRV._land_day()))
    co["reports"].append({"stamp": "2025-09", "label": "분기보고서", "tag": "", "rcept": "20251114000004", "sections": []})
    assert SRV.landscape_view("000001")["stale"] is True


def test_land_other_version_is_pending(co, kicks):
    _put(SRV._land_path("000001"), _payload(co, "2026-10-10", v=SRV.LAND_V - 1))
    d = SRV.landscape_view("000001")
    assert d.get("pending") is True and "rows" not in d


def test_land_gate_waits_for_today(co, kicks):
    _put(SRV._land_path("000001"), _payload(co, "2026-10-10"))
    assert SRV.landscape_view("000001", stale_ok=False).get("pending") is True


def test_land_short_history_negative_cache(co, kicks, monkeypatch):
    monkeypatch.setattr(SRV, "landscape_build", lambda c, prog=None: {"error": SRV.LAND_SHORT, "_transient": None})
    d, how = SRV.land_build(co)
    assert how == "short"
    neg = json.load(open(SRV._land_path("000001"), encoding="utf-8"))
    assert neg["error"] == SRV.LAND_SHORT and neg["nsig"] == SRV._land_nsig(co) and neg["v"] == SRV.LAND_V
    assert SRV.landscape_view("000001") == {"error": SRV.LAND_SHORT} and kicks == []      # 다음 날에도 바로 오류
    co["reports"].append({"stamp": "2025-12", "label": "사업보고서", "tag": "", "rcept": "20260310000009", "sections": []})
    assert SRV.landscape_view("000001").get("pending") is True                            # 새 보고서 — 다시 센다


def test_land_short_history_from_transient_not_cached(co, monkeypatch):
    monkeypatch.setattr(SRV, "landscape_build", lambda c, prog=None: {"error": SRV.LAND_SHORT, "_transient": "연간 원장 일시 오류"})
    d, how = SRV.land_build(co)
    assert how == "error" and d["transient"] and not os.path.exists(SRV._land_path("000001"))
    # 도구의 DART 셈이 본 일시 오류도 같다
    monkeypatch.setattr(SRV, "landscape_build", lambda c, prog=None: {"error": SRV.LAND_SHORT})
    d, how = SRV.land_build(co, transient=lambda: "DART 020")
    assert how == "error" and not os.path.exists(SRV._land_path("000001"))


def test_land_transient_payload_not_saved(co, monkeypatch):
    monkeypatch.setattr(SRV, "landscape_build", lambda c, prog=None: {"v": SRV.LAND_V, "rows": [2], "_transient": "주가 없음"})
    d, how = SRV.land_build(co)
    assert how == "transient" and d["transient"] == "주가 없음" and "_transient" not in d
    assert not os.path.exists(SRV._land_path("000001"))


def test_land_built_written_atomically(co, monkeypatch):
    monkeypatch.setattr(SRV, "landscape_build", lambda c, prog=None: {"v": SRV.LAND_V, "rows": [3]})
    d, how = SRV.land_build(co)
    assert how == "built"
    got = json.load(open(SRV._land_path("000001"), encoding="utf-8"))
    assert got["sig"] == SRV._land_sig(co) and got["rows"] == [3]
    assert not [f for f in os.listdir(os.path.dirname(SRV._land_path("000001"))) if f.endswith(".tmp")]


def test_run_land_transient_holds_soft_result_then_retries(co, monkeypatch):
    monkeypatch.setattr(SRV, "landscape_build", lambda c, prog=None: {"v": SRV.LAND_V, "rows": [4], "_transient": "주가 없음"})
    SRV.LANDING["000001"] = {"step": "x", "at": time.time()}
    SRV._run_land("000001")
    st = SRV.LANDING["000001"]
    assert "주가 없음" in st["error"] and st["soft"]["rows"] == [4]
    kicked = []
    monkeypatch.setattr(SRV, "_run_land", lambda code: kicked.append(code))
    d = SRV.landscape_view("000001")                  # 지난 판이 없다 — 메모리 판을 준다(저장은 안 함), 다시 그리지 않는다
    assert d["rows"] == [4] and d["transient"] and kicked == []
    st["err_at"] = time.time() - SRV.LAND_RETRY - 1
    assert SRV.landscape_view("000001").get("pending") is True
    time.sleep(0.05)
    assert kicked == ["000001"]


def test_land_stale_with_failed_refresh_stops_refreshing(co, monkeypatch):
    _put(SRV._land_path("000001"), _payload(co, "2026-10-10"))
    SRV.LANDING["000001"] = {"step": "x", "at": time.time() - 100, "error": "새로 그리지 못했습니다(주가 없음)", "err_at": time.time()}
    kicked = []
    monkeypatch.setattr(SRV, "_run_land", lambda code: kicked.append(code))
    d = SRV.landscape_view("000001")
    assert d["stale"] is True and d["refreshing"] is False and "주가 없음" in d["stale_error"] and kicked == []


def test_land_error_window_counts_from_error_time(co, monkeypatch):
    # 빌드가 100초 걸려 끝난 오류 — 시작 시각(at)이 아니라 오류 난 시각(err_at)부터 30초
    SRV.LANDING["000001"] = {"step": "x", "at": time.time() - 100, "error": "ValueError: x", "err_at": time.time()}
    kicked = []
    monkeypatch.setattr(SRV, "_run_land", lambda code: kicked.append(code))
    assert SRV.landscape_view("000001") == {"error": "ValueError: x"}
    SRV.LANDING["000001"]["err_at"] = time.time() - SRV.LAND_ERR_HOLD - 1
    assert SRV.landscape_view("000001").get("pending") is True
    time.sleep(0.05)
    assert kicked == ["000001"]


def test_land_shares_skips_pre2015_and_flags_transient(monkeypatch, tmp_path):
    calls = []
    fin_dir = str(tmp_path)

    def fetch_shares(corp, y, reprt):
        calls.append((y, reprt))
        p = os.path.join(fin_dir, "shares_%s_%s_%s.json" % (corp, y, reprt))
        if os.path.exists(p):
            return json.load(open(p, encoding="utf-8"))
        if y == 2016:
            return {"shares": None}                       # 일시 오류 — 캐시 파일이 안 생긴다
        _put(os.path.join(fin_dir, "shares_%s_%s_%s.json" % (corp, y, reprt)), {"shares": 100})
        return {"shares": 100}
    _put(os.path.join(fin_dir, "shares_C_2013_11011.json"), {"shares": 90})      # 캐시에 있는 옛 해는 읽는다
    monkeypatch.setattr(SRV, "FIN", types.SimpleNamespace(fetch_shares=fetch_shares, FIN_DIR=fin_dir))
    F = [{"year": y} for y in range(2011, 2018)]
    bad = []
    adj, splits, raw = SRV._land_shares(F, "C", (2018, "11012"), bad)
    asked = sorted({y for y, _ in calls})
    assert asked == [2013, 2015, 2016, 2017, 2018]            # 2011 · 2012 · 2014 는 묻지 않는다
    assert raw[2011] is None and raw[2013] == 90 and bad == [(2016, "11011")]
    assert SRV._land_shares(F, "C", None)[2] == raw            # bad 없이 불러도 같은 값(변곡점 쪽 호출)


def test_landscape_build_flags_empty_prices(co, monkeypatch, tmp_path):
    # 연간 원장이 4년 안 되면 짧은 이력 — 원장 일시 오류(transient)가 섞였으면 표시
    def fundamentals(fin, corp, years):
        fin.fetch_statement(corp, years[0], "11011")
        return [{"year": 2024, "rev": 1.0}]
    monkeypatch.setattr(SRV, "corp_code_of", lambda code: "C")
    monkeypatch.setattr(SRV, "INF", types.SimpleNamespace(fundamentals=fundamentals))
    monkeypatch.setattr(SRV, "FIN", types.SimpleNamespace(fetch_statement=lambda *a: {"list": [], "transient": True},
                                                          PRICE_DIR=str(tmp_path)))
    d = SRV.landscape_build(co)
    assert d["error"] == SRV.LAND_SHORT and d["_transient"] == "연간 원장 일시 오류"
    monkeypatch.setattr(SRV, "FIN", types.SimpleNamespace(fetch_statement=lambda *a: {"list": []}, PRICE_DIR=str(tmp_path)))
    assert SRV.landscape_build(co)["_transient"] is None
    assert SRV._price_fresh("000001") is False
    _put(os.path.join(str(tmp_path), "000001.json"), {})
    assert SRV._price_fresh("000001") is True                 # 방금 받은 빈 주가 = 정말 없음(상장 폐지 등) — 일시 오류 아님


def test_land_thread_start_failure_does_not_stick(co, monkeypatch):
    # 32비트 뷰어 "can't start new thread" — 오류 없는 칸이 남으면 돌지 않는 빌드를 뷰어 재시작까지 기다렸다(리뷰 correct-3)
    real = SRV.threading.Thread

    class NoThread:
        def __init__(self, *a, **kw):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")
    kicked = []
    monkeypatch.setattr(SRV, "_run_land", lambda code: kicked.append(code))
    monkeypatch.setattr(SRV.threading, "Thread", NoThread)
    d = SRV.landscape_view("000001")                          # 캐시 없음 — 오류(LAND_ERR_HOLD 창)
    assert "can't start new thread" in d["error"] and SRV.LANDING["000001"]["err_at"]
    SRV.LANDING.clear()
    _put(SRV._land_path("000001"), _payload(co, "2026-10-10"))
    d = SRV.landscape_view("000001")                          # 지난 판 — '새로 그리는 중'이 아니라 실패로 표시
    assert d["stale"] is True and d["refreshing"] is False and "can't start new thread" in d["stale_error"]
    monkeypatch.setattr(SRV.threading, "Thread", real)
    SRV.LANDING["000001"]["err_at"] = time.time() - SRV.LAND_RETRY - 1
    d = SRV.landscape_view("000001")                          # 창이 지나면 다시 띄운다
    assert d["stale"] is True and d["refreshing"] is True
    time.sleep(0.05)
    assert kicked == ["000001"]


def test_fin_watch_nested_and_thread_local(monkeypatch):
    import threading
    monkeypatch.setattr(SRV.FIN, "fetch_statement", lambda *a, **kw: {"list": [], "transient": True})
    SRV.FIN.fetch_statement("C", 2020, "11011")               # 밖 — 아무 데도 안 남는다
    with SRV._fin_watch() as outer:
        with SRV._fin_watch() as inner:
            SRV.FIN.fetch_statement("C", 2021, "11011")
        SRV.FIN.fetch_statement("C", 2022, "11011", "OFS")
        t = threading.Thread(target=SRV.FIN.fetch_statement, args=("C", 2023, "11011"))
        t.start(); t.join()                                   # 다른 스레드(뷰어의 다른 요청)는 이 목록에 안 남는다
    assert inner == [(2021, "11011")] and outer == [(2021, "11011"), (2022, "11011")]
    assert SRV._FIN_TL.stack == []
    monkeypatch.setattr(SRV.FIN, "fetch_statement", lambda *a, **kw: {"list": []})
    with SRV._fin_watch() as bad:
        SRV.FIN.fetch_statement("C", 2024, "11011")
    assert bad == []


def test_matrix_cached_not_written_when_ledger_transient(co, monkeypatch):
    # 미리 계산 DART 상한 · 020 · 점검으로 원장 일부가 transient — 그 판을 sig(최신 접수번호)로 굳히지 않는다(리뷰 tool-1).
    # 진짜 재무.statement_matrix 를 돌린다(그 안은 fetch_statement 를 모듈 이름으로 부른다)
    calls, bad_years = [], {dt.date.today().year - 1}         # n=2 → 작년 · 올해 — 작년 원장이 막혔다

    def fetch_statement(corp, year, reprt, fs_div="CFS", force=False):
        calls.append((year, reprt, fs_div))
        if year in bad_years:
            return {"status": "net", "list": [], "transient": True}
        return {"status": "013", "list": []}
    monkeypatch.setattr(SRV.FIN, "fetch_statement", fetch_statement)
    p = os.path.join(SRV.CACHE_DIR, "matrix", "000001_IS_q_2.json")
    res = SRV.matrix_cached(co, "C", "IS", "q", 2)
    assert res["transient"] and res["sig"] == co["reports"][-1]["rcept"] and not os.path.exists(p)
    n = len(calls)
    SRV.matrix_cached(co, "C", "IS", "q", 2)                  # 다음 부름은 다시 짠다 — 반쪽 판이 캐시로 남지 않았다
    assert len(calls) > n
    bad_years.clear()
    res = SRV.matrix_cached(co, "C", "IS", "q", 2)
    assert "transient" not in res and json.load(open(p, encoding="utf-8"))["sig"] == co["reports"][-1]["rcept"]
    n = len(calls)
    SRV.matrix_cached(co, "C", "IS", "q", 2)
    assert len(calls) == n                                    # 깨끗한 판은 캐시에서
    assert not [f for f in os.listdir(os.path.dirname(p)) if f.endswith(".tmp")]


def test_inflect_not_cached_when_transient(co, monkeypatch):
    # 변곡점 캐시는 sig 에 오늘 날짜 — 원장 · 주식 수 일시 오류가 낀 판을 쓰면 그날 내내 굳는다(리뷰 tool-1)
    monkeypatch.setattr(SRV, "corp_code_of", lambda code: "C")
    state = {"tr": True, "sh": False}

    def fetch_statement(corp, year, reprt, fs_div="CFS", force=False):
        return dict({"status": "020", "list": []}, **({"transient": True} if state["tr"] else {}))
    monkeypatch.setattr(SRV.FIN, "fetch_statement", fetch_statement)

    def build(c, code, corp, sig, sbad):
        SRV.FIN.fetch_statement(corp, 2025, "11011")
        if state["sh"]:
            sbad.append((2025, "11011"))
        return {"sig": sig, "code": code, "events": []}
    monkeypatch.setattr(SRV, "_inflect_build", build)
    p = os.path.join(SRV.CACHE_DIR, "inflect", "000001.json")
    assert SRV.inflect("000001")["transient"] == "재무 원장 일시 오류" and not os.path.exists(p)
    state.update(tr=False, sh=True)
    assert SRV.inflect("000001")["transient"] == "주식 수 일시 오류" and not os.path.exists(p)
    state["sh"] = False
    d = SRV.inflect("000001")
    assert "transient" not in d and json.load(open(p, encoding="utf-8"))["sig"] == d["sig"]


def test_landscape_build_flags_ledger_transient_anywhere(co, monkeypatch):
    # 연간 원장 밖(분기 matrix — _land_ttm · 변곡점)에서 본 원장 일시 오류도 그 판을 저장하지 않게 표시
    monkeypatch.setattr(SRV.FIN, "fetch_statement", lambda *a, **kw: {"list": [], "transient": True})
    got = {"tr": None}

    def inner(c, prog=None):
        SRV.FIN.fetch_statement("C", 2026, "11014")
        return {"v": SRV.LAND_V, "rows": [1], "_transient": got["tr"]}
    monkeypatch.setattr(SRV, "_landscape_build", inner)
    assert SRV.landscape_build(co)["_transient"] == "재무 원장 일시 오류"
    d, how = SRV.land_build(co)
    assert how == "transient" and not os.path.exists(SRV._land_path("000001"))
    got["tr"] = "주가 없음"
    assert SRV.landscape_build(co)["_transient"] == "주가 없음"          # 먼저 단 이유는 그대로
    got["tr"] = None
    monkeypatch.setattr(SRV.FIN, "fetch_statement", lambda *a, **kw: {"list": []})
    assert SRV.landscape_build(co)["_transient"] is None


# ---------------------------------------------------------------- 궤도 요약
def _brief(rcept, score, gist_v=None):
    b = {"code": "000001", "report": {"rcept": rcept}, "kind": "직전", "first": score == 0, "score": score, "tags": {"수주·계약": 1},
         "sections": ([{"section": "사업의 내용", "weight": 1.0, "added_chars": 400 * score, "removed_chars": 50, "numeric": 2,
                        "score": score}] if score else [])}
    if gist_v is not None:
        b["gist"], b["gist_v"] = [{"sec": "사업의 내용", "text": "새 공장 %s" % rcept}], gist_v
    return b


@pytest.fixture
def orbit_co(co, monkeypatch):
    for i, rep in enumerate(co["reports"]):
        _put(SRV.brief_path("000001", rep["rcept"]), _brief(rep["rcept"], i, SRV.GIST_V))
    monkeypatch.setattr(SRV, "BUILDING", {})
    monkeypatch.setattr(SRV, "GISTING", {})
    started = []
    monkeypatch.setattr(SRV, "_run_orbit", lambda code: started.append(("orbit", code)))
    monkeypatch.setattr(SRV, "_run_gists", lambda code: started.append(("gists", code)))
    co["_started"] = started
    return co


def test_orbit_summary_written_and_used_without_briefs(orbit_co):
    first = SRV.orbit("000001")
    assert first["finished"] and first["gist_pending"] == 0
    assert os.path.exists(SRV._orbit_sum_path("000001"))
    import shutil
    shutil.rmtree(os.path.join(SRV.CACHE_DIR, "brief"))         # 요약만으로 — brief 를 하나도 안 연다
    again = SRV.orbit("000001")
    assert json.dumps(again, ensure_ascii=False, sort_keys=False) == json.dumps(first, ensure_ascii=False, sort_keys=False)
    assert orbit_co["_started"] == []


def test_orbit_summary_invalidated_by_new_report_and_gist_v(orbit_co, monkeypatch):
    SRV.orbit("000001")
    assert SRV._orbit_sum_rows(orbit_co) is not None
    monkeypatch.setattr(SRV, "GIST_V", SRV.GIST_V + 1)
    assert SRV._orbit_sum_rows(orbit_co) is None
    monkeypatch.setattr(SRV, "GIST_V", SRV.GIST_V - 1)
    assert SRV._orbit_sum_rows(orbit_co) is not None
    orbit_co["reports"].append({"stamp": "2025-09", "label": "분기보고서", "tag": "", "rcept": "20251114000004", "sections": []})
    assert SRV._orbit_sum_rows(orbit_co) is None
    d = SRV.orbit("000001")                                     # 새 보고서 brief 가 없다 — 예전처럼 쌓기 시작, 요약은 안 씀
    assert d["finished"] is False and ("orbit", "000001") in orbit_co["_started"]


def test_orbit_summary_not_written_with_old_gist(co, monkeypatch):
    for i, rep in enumerate(co["reports"]):
        _put(SRV.brief_path("000001", rep["rcept"]), _brief(rep["rcept"], i, SRV.GIST_V - 1 if i == 2 else SRV.GIST_V))
    monkeypatch.setattr(SRV, "BUILDING", {})
    monkeypatch.setattr(SRV, "GISTING", {})
    monkeypatch.setattr(SRV, "_run_gists", lambda code: None)
    monkeypatch.setattr(SRV, "_run_orbit", lambda code: None)
    rows, have, current = SRV._orbit_collect(co, deadline=0)    # 시간 창 밖 — 옛 gist 를 여기서 뽑지 않는다
    assert have == 3 and current is False and rows[2]["gist"] is None
    monkeypatch.setattr(SRV, "brief_gist", lambda c, rep, b: [{"text": "다시 뽑음"}])
    SRV.orbit("000001")                                         # 1초 창 안에서 뽑으면 다 맞는다 — 그때 요약을 쓴다
    assert SRV._orbit_sum_rows(co)[2]["gist"] == [{"text": "다시 뽑음"}]
    b = json.load(open(SRV.brief_path("000001", co["reports"][2]["rcept"]), encoding="utf-8"))
    assert b["gist_v"] == SRV.GIST_V
    assert not [f for f in os.listdir(os.path.dirname(SRV.brief_path("000001", "x"))) if f.endswith(".tmp")]


def test_orbit_rows_from_summary_equal_original(orbit_co):
    rows, have, current = SRV._orbit_collect(orbit_co)
    assert current and have == 3
    SRV._orbit_sum_write(orbit_co, rows)
    assert SRV._orbit_sum_rows(orbit_co) == rows


# ---------------------------------------------------------------- /api/prebuild
@pytest.fixture
def pre(monkeypatch, tmp_path):
    monkeypatch.setattr(SRV, "PREBUILD_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "PREBUILD", {"proc": None, "py": None, "started": None, "error": None})
    return tmp_path


class _Proc:
    def __init__(self, rc=None):
        self.rc = rc

    def poll(self):
        return self.rc


def test_pid_alive_and_reuse_guard():
    assert SRV._pid_alive(os.getpid()) is True
    assert SRV._pid_alive(os.getpid(), since=time.time()) is True      # 시작 시각 전에 만든 프로세스
    assert SRV._pid_alive(os.getpid(), since=1000.0) is False          # 1970년 시작이라면 — 나중에 만든 남(pid 재사용)
    assert SRV._pid_alive(0) is False and SRV._pid_alive(None) is False and SRV._pid_alive(4000000) is False


def test_prebuild_status_shape_and_log_tail(pre):
    _put(os.path.join(str(pre), "state.json"), {"v": 1, "pid": 4000000, "phase": "orbit", "started": "2026-10-11T10:00:00",
                                               "land": {"done": 3}, "orbit": {"done": 1}, "dart": {"used": 5}})
    with open(os.path.join(str(pre), "run.log"), "w", encoding="utf-8") as fh:
        fh.write("".join("줄 %d\n" % i for i in range(20)))
    s = SRV.prebuild_status()
    assert s["phase"] == "orbit" and s["alive"] is False and s["running"] is False
    assert s["log"] == ["줄 %d" % i for i in range(12, 20)] and s["stop_pending"] is False


def test_prebuild_run_once(pre, monkeypatch):
    spawned = []

    def spawn(cmd, first):
        spawned.append(cmd)
        SRV.PREBUILD.update(proc=_Proc(), py=" ".join(cmd), started=time.time())
        return True
    monkeypatch.setattr(SRV, "_prebuild_spawn", spawn)
    monkeypatch.setattr(SRV, "_prebuild_watch", lambda p: None)
    open(os.path.join(str(pre), "stop"), "w").close()
    s = SRV.prebuild_run()
    assert len(spawned) == 1 and s["running"] is True and s["phase"] == "start"
    assert not os.path.exists(os.path.join(str(pre), "stop"))          # 지난 멈춤 파일은 지우고 띄운다
    SRV.prebuild_run()
    assert len(spawned) == 1                                            # 한 번에 하나


def test_prebuild_run_falls_back_when_launcher_missing(pre, monkeypatch):
    tried = []

    def spawn(cmd, first):
        tried.append(cmd)
        if cmd != [sys.executable]:
            return False
        SRV.PREBUILD.update(proc=_Proc(), py=" ".join(cmd), started=time.time())
        return True
    monkeypatch.setattr(SRV, "_prebuild_spawn", spawn)
    monkeypatch.setattr(SRV, "BT_PY", "없는실행기 -3.13")
    SRV.prebuild_run()
    assert tried == [["없는실행기", "-3.13"], [sys.executable]]


def test_prebuild_stop(pre):
    SRV.PREBUILD["proc"] = _Proc()                                      # 돌고 있다 — stop 파일
    SRV.prebuild_stop()
    assert os.path.exists(os.path.join(str(pre), "stop"))
    os.remove(os.path.join(str(pre), "stop"))
    SRV.PREBUILD["proc"] = _Proc(0)                                     # 안 돈다 — 자동 이어 하기만 막는다
    _put(os.path.join(str(pre), "state.json"), {"v": 1, "pid": 4000000, "phase": "land", "stopped": None})
    SRV.prebuild_stop()
    assert not os.path.exists(os.path.join(str(pre), "stop"))
    assert json.load(open(os.path.join(str(pre), "state.json"), encoding="utf-8"))["stopped"] == "user"


def test_prebuild_should_resume_rules():
    now = dt.datetime(2026, 10, 12, 9, 0)
    R = SRV._prebuild_should_resume
    assert R({}, now) is False                                          # 한 번도 안 눌렀다
    assert R({"phase": "orbit", "stopped": None}, now) is True          # 꺼졌다(뷰어 재시작 · 로그오프)
    assert R({"phase": "orbit", "stopped": "user"}, now) is False
    assert R({"phase": "land", "codes": ["005930"]}, now) is False       # 골라 돌린 시험 판
    assert R({"phase": "done", "land": {"deferred": 0}}, now) is False
    assert R({"phase": "done", "land": {"deferred": 9}, "dart": {"date": "2026-10-12"}}, now) is False     # 같은 날 — 한도
    assert R({"phase": "done", "land": {"deferred": 9}, "dart": {"date": "2026-10-11"}}, now) is True
    # 07:00–23:30 밖이라 미룬 풍경 — 같은 날에도 창 안이면 이어 한다(밤 01:00 에 누른 판 → 07:xx)
    assert R({"phase": "done", "land": {"deferred": 9, "stop": "time"}, "dart": {"date": "2026-10-12"}}, now) is True
    assert R({"phase": "done", "land": {"deferred": 9, "stop": "cap"}, "dart": {"date": "2026-10-12"}}, now) is False
    assert R({"phase": "land", "stopped": "error", "at": "2026-10-12T08:30:00"}, now) is False
    assert R({"phase": "land", "stopped": "error", "at": "2026-10-12T05:00:00"}, now) is True


def _handler(path, host, **hdr):
    from http.client import HTTPMessage                 # 진짜 요청처럼 머리 이름은 대소문자를 안 가린다
    h = object.__new__(SRV.Handler)
    m = HTTPMessage()
    m["Host"] = host
    for k, v in hdr.items():
        m[k.replace("_", "-")] = v
    h.path, h.headers = path, m
    h.server = types.SimpleNamespace(server_address=("127.0.0.1", 8766))
    sent = []
    h._send = lambda code, body, ctype=None: sent.append((code, body))
    return h, sent


def test_prebuild_route_local_only(pre, monkeypatch):
    ran = []
    monkeypatch.setattr(SRV, "prebuild_run", lambda auto=False: ran.append("run") or {"ok": 1})
    monkeypatch.setattr(SRV, "prebuild_stop", lambda: ran.append("stop") or {"ok": 1})
    h, sent = _handler("/api/prebuild?run=1", "evil.example:8766")
    h.do_GET()
    assert sent[0][0] == 403 and ran == []
    h, sent = _handler("/api/prebuild?run=1", "127.0.0.1:8766")
    h.do_GET()
    assert sent[0][0] == 200 and ran == ["run"]
    h, sent = _handler("/api/prebuild?stop=1", "localhost:8766")
    h.do_GET()
    assert ran == ["run", "stop"]
    h, sent = _handler("/api/prebuild", "evil.example:8766")           # 상태 보기는 누구나(읽기 전용)
    h.do_GET()
    assert sent[0][0] == 200 and "running" in sent[0][1]


@pytest.mark.parametrize("hdr, ok", [
    ({"sec_fetch_site": "same-origin", "referer": "http://127.0.0.1:8766/"}, True),     # 화면의 fetch
    ({"sec_fetch_site": "none"}, True),                                                 # 주소창에 직접
    ({"origin": "http://localhost:8766", "sec_fetch_site": "same-origin"}, True),
    ({"sec_fetch_site": "cross-site"}, False),                                          # 다른 사이트의 <img src=…> · no-cors fetch
    ({"sec_fetch_site": "same-site"}, False),                                           # 같은 localhost 의 다른 포트
    ({"origin": "https://evil.example"}, False),
    ({"origin": "null"}, False),                                                        # 샌드박스 iframe · file://
    ({"referer": "https://evil.example/page"}, False),                                  # Sec-Fetch 없는 옛 브라우저
    ({"referer": "http://127.0.0.1:87660/x"}, False),                                   # 앞만 같은 다른 포트
])
def test_prebuild_run_stop_same_origin_only(pre, monkeypatch, hdr, ok):
    # Host 만 보면 다른 사이트의 하위 요청도 Host: 127.0.0.1:포트 로 와서 통과했다(리뷰 tool-4)
    ran = []
    monkeypatch.setattr(SRV, "prebuild_run", lambda auto=False: ran.append("run") or {"ok": 1})
    monkeypatch.setattr(SRV, "prebuild_stop", lambda: ran.append("stop") or {"ok": 1})
    for q in ("run=1", "stop=1"):
        h, sent = _handler("/api/prebuild?" + q, "127.0.0.1:8766", **hdr)
        h.do_GET()
        assert sent[0][0] == (200 if ok else 403)
    assert ran == (["run", "stop"] if ok else [])
    h, sent = _handler("/api/prebuild", "127.0.0.1:8766", sec_fetch_site="cross-site")   # 상태 보기(GET)는 그대로
    h.do_GET()
    assert sent[0][0] == 200 and ran == (["run", "stop"] if ok else [])


# ---------------------------------------------------------------- 도구(가짜 서버 모듈)
class _Resp:
    def __init__(self, status, code=200):
        self.status, self.status_code = status, code

    def json(self):
        return {"status": self.status}


def _orig(statuses):
    calls = []

    def orig(sess, method, url, *a, **kw):
        calls.append(url)
        return _Resp(statuses.get(url, "000"))
    return orig, calls


DART_URL = "https://opendart.fss.or.kr/api/stockTotqySttus.json"


def test_dart_meter_counts_and_caps():
    import requests
    orig, calls = _orig({})
    m = TOOL.DartMeter(cap=2)
    req = m.wrap(orig)
    req(None, "GET", "https://api.finance.naver.com/siseJson.naver")      # 네이버는 세지 않는다
    req(None, "GET", DART_URL)
    req(None, method="GET", url=DART_URL)
    assert m.used == 2 and m.halted() and m.reason() is None
    with pytest.raises(requests.ConnectionError):
        req(None, "GET", DART_URL)
    assert len(calls) == 3 and m.used == 2 and m.halt == "cap" and m.reason() == "DART 상한"


@pytest.mark.parametrize("st", ["020", "800"])
def test_dart_meter_halts_on_limit_and_maintenance(st):
    import requests
    orig, calls = _orig({DART_URL: st})
    m = TOOL.DartMeter(cap=100)
    req = m.wrap(orig)
    req(None, "GET", DART_URL)
    assert m.halt == st and m.reason() == "DART %s" % st
    with pytest.raises(requests.ConnectionError):
        req(None, "GET", DART_URL)
    assert len(calls) == 1 and m.used == 1


def test_dart_meter_marks_other_errors_without_halting():
    orig, calls = _orig({DART_URL: "900"})
    m = TOOL.DartMeter(cap=100)
    m.wrap(orig)(None, "GET", DART_URL)
    assert m.halt is None and m.reason() == "DART 900"
    m.begin()
    assert m.reason() is None


class FakeS:
    """서버 모듈 흉내 — 풍경 · 궤도 함수만. 회사 A · B · C, 회사마다 DART 를 dart_per 건 부르는 풍경."""
    LAND_V = 9
    GIST_V = 6

    def __init__(self, root, dart_per=2, statuses=None):
        self.CACHE_DIR = os.path.join(root, ".cache")
        self.PREBUILD_DIR = os.path.join(self.CACHE_DIR, "prebuild")
        self.INDEX_PATH = os.path.join(self.CACHE_DIR, "색인.json")
        self.INDEX = {"companies": []}
        self.DRUCK_SOFT = {}
        self.dart_per, self.statuses = dart_per, statuses or {}
        self.req, self.built, self.brief_calls, self.alive = None, [], [], set()
        self.on_brief = None
        comps = [{"code": k, "name": "회사" + k, "reports": [{"stamp": "2025-0%d" % i, "label": "분기보고서", "tag": "",
                                                            "rcept": "2025%s%04d" % (k, i)} for i in range(1, n + 1)]}
                 for k, n in (("A", 2), ("B", 3), ("C", 1))]
        _put(self.INDEX_PATH, {"companies": comps, "sig": "x"})

    def build_index(self, force=False):
        raise AssertionError("도구는 색인을 다시 쓰면 안 된다")

    # 공용
    def _atomic_json(self, path, obj):
        _put(path, obj)
        return True

    def _no_secret(self, msg):
        return str(msg)

    def _pid_alive(self, pid, since=None):
        return pid in self.alive

    def _druck_order(self, comps, has_cache):
        return list(comps)

    def _druck_path(self, code):
        return os.path.join(self.CACHE_DIR, "druck", code + ".json")

    # 풍경
    def _land_path(self, code):
        return os.path.join(self.CACHE_DIR, "landscape", code + ".json")

    def _land_read(self, code):
        try:
            return json.load(open(self._land_path(code), encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _land_v(self, d):
        return d.get("v")

    def _land_nsig(self, c):
        return "%s:%d:%d" % (c["reports"][-1]["rcept"], len(c["reports"]), self.LAND_V)

    def land_build(self, c, prog=None, transient=None):
        for _ in range(self.dart_per):
            try:
                self.req(None, "GET", DART_URL + "?c=" + c["code"])
            except Exception:
                pass                                 # 재무.fetch_* 처럼 삼킨다
        self.built.append(c["code"])
        tr = transient() if transient else None
        if tr:
            return {"transient": tr}, "transient"
        self._atomic_json(self._land_path(c["code"]), {"v": self.LAND_V, "code": c["code"], "sig": "s"})
        return {}, "built"

    # 궤도
    def brief_path(self, code, rcept):
        return os.path.join(self.CACHE_DIR, "brief", code, rcept + ".json")

    def build_brief(self, c, rep):
        p = self.brief_path(c["code"], rep["rcept"])
        if os.path.exists(p):
            return json.load(open(p, encoding="utf-8"))
        self.brief_calls.append(rep["rcept"])
        if self.on_brief:
            self.on_brief(len(self.brief_calls))
        b = {"sections": [], "score": 1.0}
        self._atomic_json(p, b)
        return b

    def _gist_of(self, c, rep, b, p, allow=True):
        b["gist"], b["gist_v"] = ["g" + rep["rcept"]], self.GIST_V
        self._atomic_json(p, b)
        return b["gist"]

    def _orbit_row(self, rep, b, gist=None):
        return {"rcept": rep["rcept"], "score": b["score"], "gist": gist}

    def _orbit_sum_path(self, code):
        return os.path.join(self.CACHE_DIR, "orbit", code + ".json")

    def _orbit_sum_rows(self, c):
        try:
            s = json.load(open(self._orbit_sum_path(c["code"]), encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return s["rows"] if s.get("sig") == [r["rcept"] for r in c["reports"]] else None

    def _orbit_sum_write(self, c, rows):
        return self._atomic_json(self._orbit_sum_path(c["code"]), {"sig": [r["rcept"] for r in c["reports"]], "rows": rows})


@pytest.fixture
def fake(monkeypatch, tmp_path):
    S = FakeS(str(tmp_path))
    monkeypatch.setattr(TOOL.DartMeter, "install", lambda self: None)      # 진짜 requests 는 건드리지 않는다

    def begin(self, _orig_begin=TOOL.Prebuild.begin):
        _orig_begin(self)
        orig, S.dart_calls = _orig(S.statuses)
        S.req = self.meter.wrap(orig)
    monkeypatch.setattr(TOOL.Prebuild, "begin", begin)
    return S


def _run(S, **kw):
    kw.setdefault("echo", False)
    kw.setdefault("anytime", True)          # 시험을 밤에 돌려도 같게 — 풍경 시간 창은 따로 시험한다
    pb = TOOL.Prebuild(S, S.PREBUILD_DIR, **kw)
    rc = pb.run()
    st = json.load(open(os.path.join(S.PREBUILD_DIR, "state.json"), encoding="utf-8"))
    return rc, st, pb


def test_tool_full_run_skips_done_and_writes_state(fake):
    S = fake
    _put(S._land_path("A"), {"v": S.LAND_V, "code": "A", "sig": "old:2:2026-10-09:9"})          # 날짜 지난 판 — 건너뜀
    _put(S._land_path("B"), {"v": S.LAND_V, "error": "연간 재무가 4년 치도 안 됩니다.", "nsig": "2025B0003:3:9"})   # 부정 캐시
    rc, st, pb = _run(S, dart_cap=10)
    assert rc == 0 and st["phase"] == "done" and st["stopped"] is None and st["pid"] == os.getpid()
    assert st["land"] == {"total": 3, "done": 3, "fresh": 1, "built": 1, "short": 1, "failed": 0, "deferred": 0}
    assert S.built == ["C"] and st["dart"]["used"] == 2 and st["dart"]["cap"] == 10 and st["dart"]["date"] == TODAY
    assert st["orbit"]["done"] == 3 and st["orbit"]["reports"] == 6 and st["orbit"]["gists"] == 6 and st["orbit"]["written"] == 3
    log = open(os.path.join(S.PREBUILD_DIR, "run.log"), encoding="utf-8").read()
    assert "풍경 C 회사C — 새로 씀" in log and "궤도 B 회사B" in log and "풍경 A" not in log
    # 다시 돌리면 모두 건너뛴다
    S.built.clear(); S.brief_calls.clear()
    rc, st, pb = _run(S, dart_cap=10)
    assert S.built == [] and S.brief_calls == [] and st["orbit"]["fresh"] == 3 and st["land"]["fresh"] == 2
    assert st["dart"]["used"] == 2                                      # 같은 날 — 이어 센다


def test_tool_orbit_order_fewest_reports_first(fake):
    S = fake
    rc, st, pb = _run(S, phase="orbit")
    log = open(os.path.join(S.PREBUILD_DIR, "run.log"), encoding="utf-8").read()
    assert log.index("궤도 C") < log.index("궤도 A") < log.index("궤도 B")
    assert st["land"]["total"] == 0 and S.built == []


def test_tool_dart_cap_defers_rest_then_orbit(fake):
    S = fake
    rc, st, pb = _run(S, dart_cap=3)
    # A: 2건(새로 씀), B: 1건 쓰고 상한 — 일시 오류로 미룸, C: 시도하지 않고 미룸
    assert S.built == ["A", "B"] and st["land"]["built"] == 1 and st["land"]["deferred"] == 2
    assert st["land"]["stop"] == "cap" and st["dart"]["used"] == 3 and len(S.dart_calls) == 3
    assert st["phase"] == "done" and st["stopped"] == "dart" and st["orbit"]["written"] == 3
    assert not os.path.exists(S._land_path("B"))
    assert SRV._prebuild_should_resume(st, dt.datetime.now()) is False   # 같은 날은 다시 안 띄운다
    tomorrow = dt.datetime.now() + dt.timedelta(days=1)
    st2 = dict(st, codes=None)
    assert SRV._prebuild_should_resume(st2, tomorrow) is True


def test_tool_dart_020_stops_land(fake):
    S = fake
    S.statuses = {DART_URL + "?c=A": "020"}
    rc, st, pb = _run(S, dart_cap=100)
    assert S.built == ["A"] and st["land"]["deferred"] == 3 and st["land"]["stop"] == "020"
    assert st["dart"]["halt"] == "020" and len(S.dart_calls) == 1


def test_tool_dart_counter_new_day_resets(fake):
    S = fake
    _put(os.path.join(S.PREBUILD_DIR, "state.json"), {"dart": {"date": "2000-01-01", "used": 2999}})
    rc, st, pb = _run(S, dart_cap=3000, phase="land")
    assert st["dart"]["used"] == 6 and st["land"]["built"] == 3
    _put(os.path.join(S.PREBUILD_DIR, "state.json"), {"dart": {"date": TODAY, "used": 3000}})
    for k in "ABC":
        os.remove(S._land_path(k))
    S.built.clear()
    rc, st, pb = _run(S, dart_cap=3000, phase="land")
    assert S.built == [] and st["land"]["deferred"] == 3                 # 오늘 몫을 이미 다 썼다


def test_tool_stop_file_between_companies(fake):
    S = fake
    os.makedirs(S.PREBUILD_DIR, exist_ok=True)
    open(os.path.join(S.PREBUILD_DIR, "stop"), "w").close()
    rc, st, pb = _run(S)
    assert st["stopped"] == "user" and st["phase"] == "land" and st["land"]["done"] == 0 and S.built == []
    assert not os.path.exists(os.path.join(S.PREBUILD_DIR, "stop"))     # 끝나면 지운다


def test_tool_stop_file_between_orbit_companies(fake):
    S = fake
    S.on_brief = lambda n: open(os.path.join(S.PREBUILD_DIR, "stop"), "w").close() if n == 1 else None
    rc, st, pb = _run(S, phase="orbit", workers=1)
    # C(보고서 1건)는 끝내고 요약까지 — 다음 회사 앞에서 멈춘다
    assert st["stopped"] == "user" and st["phase"] == "orbit" and st["orbit"]["written"] == 1 and st["orbit"]["done"] == 1
    assert os.path.exists(S._orbit_sum_path("C")) and not os.path.exists(S._orbit_sum_path("A"))
    assert not os.path.exists(os.path.join(S.PREBUILD_DIR, "stop"))


def test_tool_stop_file_inside_orbit_company(fake):
    S = fake
    idx = json.load(open(S.INDEX_PATH, encoding="utf-8"))
    idx["companies"].append({"code": "D", "name": "회사D", "reports": [
        {"stamp": "2024-%02d" % i, "label": "분기보고서", "tag": "", "rcept": "2024D%04d" % i} for i in range(1, 13)]})
    _put(S.INDEX_PATH, idx)
    S.on_brief = lambda n: open(os.path.join(S.PREBUILD_DIR, "stop"), "w").close() if n == 2 else None
    rc, st, pb = _run(S, phase="orbit", workers=1, codes=["D"])
    # 보고서 5건마다 stop 파일을 본다 — 12건을 다 하지 않고 멈추고, 요약은 쓰지 않는다(다음에 이어서)
    assert st["stopped"] == "user" and len(S.brief_calls) < 12 and not os.path.exists(S._orbit_sum_path("D"))
    assert st["orbit"]["done"] == 0 and "cur" not in st["orbit"]


def test_tool_codes_and_index_retry(fake, monkeypatch):
    S = fake
    good = open(S.INDEX_PATH, encoding="utf-8").read()
    with open(S.INDEX_PATH, "w", encoding="utf-8") as fh:
        fh.write(good[:40])                                             # 뷰어가 다시 쓰는 중 — 반쯤 쓴 파일
    slept = []

    def sleep(s):
        slept.append(s)
        with open(S.INDEX_PATH, "w", encoding="utf-8") as fh:
            fh.write(good)
    monkeypatch.setattr(TOOL.time, "sleep", sleep)
    rc, st, pb = _run(S, codes=["B"], dart_cap=10)
    assert rc == 0 and slept and st["codes"] == ["B"] and S.built == ["B"]
    assert st["land"]["total"] == 1 and st["orbit"]["total"] == 1


def test_tool_refuses_when_another_alive(fake):
    S = fake
    prev = {"pid": 4242, "started": "2026-10-11T10:00:00", "phase": "orbit", "orbit": {"done": 7}}
    _put(os.path.join(S.PREBUILD_DIR, "state.json"), prev)
    S.alive.add(4242)
    rc, st, pb = _run(S)
    assert rc == 0 and st == prev and S.built == []


def test_tool_error_recorded_in_state(fake, monkeypatch):
    S = fake

    def boom(*a, **kw):
        raise RuntimeError("터짐 crtfc_key=SECRET")
    monkeypatch.setattr(S, "_orbit_sum_rows", boom)
    S._no_secret = SRV._no_secret
    rc, st, pb = _run(S, phase="orbit")
    assert rc == 1 and st["stopped"] == "error" and "SECRET" not in st["error"] and "터짐" in st["error"]


def test_tool_main_parses_env(fake, monkeypatch):
    monkeypatch.setenv("PREBUILD_CODES", "C, A")
    monkeypatch.setenv("PREBUILD_DART_CAP", "7")
    a = TOOL.parse_args([])
    assert a.codes == "C, A" and a.dart_cap == 7 and a.workers == 4 and a.phase == "all"
    assert a.dart_reserve == TOOL.DART_RESERVE and a.anytime is False
    a = TOOL.parse_args(["--dart-reserve", "5", "--anytime"])
    assert a.dart_reserve == 5 and a.anytime is True


def test_dart_meter_counts_per_calendar_day():
    # 시작한 날로만 세면 자정을 넘겨 돈 판이 다음 날 몫을 상한 넘게 쓴다(리뷰 tool-2) — 부를 때마다 날짜를 본다
    import requests
    day = ["2026-10-11"]
    orig, calls = _orig({})
    m = TOOL.DartMeter(cap=2, used=1, date="2026-10-11", today=lambda: day[0])
    req = m.wrap(orig)
    req(None, "GET", DART_URL)
    assert m.halted() and m.used == 2
    with pytest.raises(requests.ConnectionError):
        req(None, "GET", DART_URL)
    assert m.halt == "cap"
    day[0] = "2026-10-12"                                      # 자정 — 상한 멈춤은 풀리고 0 부터
    assert not m.halted() and m.used == 0 and m.date == "2026-10-12" and m.halt is None
    req(None, "GET", DART_URL)
    assert m.used == 1 and len(calls) == 2
    m.halt = "800"                                             # 점검 · 키 오류는 날짜가 바뀌어도 그대로
    day[0] = "2026-10-13"
    assert m.halted() and m.halt == "800" and m.used == 0


def test_dart_meter_room_reserves_per_company():
    m = TOOL.DartMeter(cap=100, used=85)
    assert m.room(10) and m.halt is None
    assert not m.room(20) and m.halt == "cap" and m.halted()
    assert TOOL.DartMeter(cap=100, used=99).room(0) and not TOOL.DartMeter(cap=100, used=100).room(0)


def test_tool_reserve_defers_company_before_cap(fake):
    # 회사 하나를 반쯤 하다 상한에 막히면 원장 · matrix 가 반쪽 — 여유가 모자라면 그 회사를 시작하지 않는다(리뷰 tool-1)
    S = fake
    _put(os.path.join(S.PREBUILD_DIR, "state.json"), {"dart": {"date": TODAY, "used": 30}})
    rc, st, pb = _run(S, dart_cap=40, dart_reserve=10, phase="land")
    assert pb.reserve == 10 and S.built == ["A"]                         # A 뒤 8건 남음 < 10 — B · C 는 시작하지 않는다
    assert st["land"]["built"] == 1 and st["land"]["deferred"] == 2 and st["land"]["stop"] == "cap"
    assert st["dart"]["used"] == 32 and st["dart"]["halt"] == "cap" and st["stopped"] == "dart"
    assert "남은 곳은 미룸(DART 상한" in open(os.path.join(S.PREBUILD_DIR, "run.log"), encoding="utf-8").read()
    assert TOOL.Prebuild(S, S.PREBUILD_DIR, dart_cap=3000).reserve == 80
    assert TOOL.Prebuild(S, S.PREBUILD_DIR, dart_cap=50).reserve == 12   # 시험용 작은 상한 — 상한의 1/4 까지


def test_tool_land_only_inside_hours(fake):
    # 22:00 에 눌러도 23:30 이 지나면 풍경(DART)은 미루고 궤도만 — 00:10 수집 · 02:00 druck 와 하루 한도를 겹쳐 쓰지 않게(리뷰 tool-2)
    S = fake
    T = [dt.datetime(2026, 10, 11, 23, 29)]
    orig = S.land_build

    def lb(c, prog=None, transient=None):
        out = orig(c, prog, transient)
        T[0] = dt.datetime(2026, 10, 11, 23, 31)                 # 첫 회사가 끝나니 23:31
        return out
    S.land_build = lb
    rc, st, pb = _run(S, dart_cap=100, anytime=False, now=lambda: T[0])
    assert S.built == ["A"] and st["land"]["built"] == 1 and st["land"]["deferred"] == 2 and st["land"]["stop"] == "time"
    assert st["phase"] == "done" and st["stopped"] is None and st["orbit"]["written"] == 3      # 궤도는 그대로
    assert "남은 곳은 미룸(07:00–23:30 밖)" in open(os.path.join(S.PREBUILD_DIR, "run.log"), encoding="utf-8").read()
    assert SRV._prebuild_should_resume(st, dt.datetime(2026, 10, 12, 7, 15)) is True
    # 01:00 에 누른 판 — 풍경은 하나도 안 하고 미룸(DART 0건), 같은 날 07:xx 에 뷰어가 이어 붙인다
    os.remove(S._land_path("A"))
    S.built.clear()
    S.land_build = orig
    T[0] = dt.datetime(2026, 10, 12, 1, 0)
    rc, st, pb = _run(S, dart_cap=100, anytime=False, now=lambda: T[0])
    assert S.built == [] and st["land"]["deferred"] == 3 and st["dart"]["used"] == 0 and st["dart"]["date"] == "2026-10-12"
    assert SRV._prebuild_should_resume(st, dt.datetime(2026, 10, 12, 7, 15)) is True
    T[0] = dt.datetime(2026, 10, 12, 7, 15)
    rc, st, pb = _run(S, dart_cap=100, anytime=False, now=lambda: T[0])
    assert S.built == ["A", "B", "C"] and st["land"]["built"] == 3 and "stop" not in st["land"]


def test_tool_dart_count_follows_midnight_into_state(fake):
    # --anytime 으로 자정을 넘겨 돈 판 — 새 날 몫을 0 부터 세고 state 의 날짜도 새 날(같은 날 다시 켜면 거기서 이어 센다)
    S = fake
    T = [dt.datetime(2026, 10, 11, 23, 59)]
    _put(os.path.join(S.PREBUILD_DIR, "state.json"), {"dart": {"date": "2026-10-11", "used": 2998}})
    orig = S.land_build

    def lb(c, prog=None, transient=None):
        out = orig(c, prog, transient)
        T[0] = dt.datetime(2026, 10, 12, 0, 1)
        return out
    S.land_build = lb
    rc, st, pb = _run(S, dart_cap=3000, dart_reserve=0, phase="land", now=lambda: T[0])
    # A 가 시작한 날 몫을 다 썼다(2,998 + 2) — 예전엔 B · C 가 미뤄졌다(시작한 날 몫으로 셈)
    assert S.built == ["A", "B", "C"] and st["land"]["built"] == 3 and st["land"]["deferred"] == 0
    assert st["dart"]["date"] == "2026-10-12" and st["dart"]["used"] == 4 and st["dart"]["halt"] is None
    for k in "ABC":
        os.remove(S._land_path(k))
    S.built.clear()
    rc, st, pb = _run(S, dart_cap=3000, dart_reserve=0, phase="land", now=lambda: T[0])
    assert st["dart"]["used"] == 10                                   # 같은 날 — 이어 센다

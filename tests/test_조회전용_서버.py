# -*- coding: utf-8 -*-
"""조회 전용 모드 — 서버 쪽(2026-10-15). 서버.py --readonly · _ro_block · /api/mode · 색인 그대로 · 웹 띠 · 기업추적_조회.bat.
조회전용.enable()(프로세스 전체 패치)은 켜지 않는다 — 그건 tests/test_조회전용.py 가 별도 프로세스에서 본다.
여기서는 서버 모듈의 READONLY 값만 monkeypatch 로 바꾼다."""
import os, sys, json, time, types, socket, subprocess, importlib.util as ilu
import datetime as dt

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("서버_조회전용_시험", os.path.join(BASE, "서버.py"))
SRV = ilu.module_from_spec(_sp); _sp.loader.exec_module(SRV)

RO_MSG = "조회 전용 — 계산 · 수집 · 쓰기는 메인 PC 에서"
BAT = os.path.join(BASE, "기업추적_조회.bat")


# ------------------------------------------------------------------ _ro_block 규칙 표
@pytest.mark.parametrize("path, q, blocked", [
    # 보기만 — 통과
    ("/api/value", {}, False),
    ("/api/synergy", {}, False),
    ("/api/landscape", {"code": "066570"}, False),
    ("/api/export", {}, False),
    ("/api/export/auto", {}, False),                       # 상태 보기
    ("/api/tech", {}, False),                              # 상태 보기
    ("/api/prebuild", {}, False),                          # 상태 보기
    ("/api/druck", {"code": "066570", "bg": "1"}, False),
    ("/api/mode", {}, False),
    ("/api/trades", {}, False),                            # 매매 일지 읽기
    ("/api/value", {"force": "0"}, False),
    ("/", {"force": "1"}, False),                          # API 가 아닌 화면 파일은 규칙 밖
    # 일을 시키는 GET — 막음
    ("/api/value", {"force": "1"}, True),
    ("/api/synergy", {"force": "1"}, True),
    ("/api/matrix", {"code": "005930", "force": "1"}, True),
    ("/api/druck", {"code": "066570", "force": "1"}, True),
    ("/api/tech", {"run": "1"}, True),
    ("/api/druck/pre", {"run": "1"}, True),
    ("/api/prebuild", {"run": "1"}, True),
    ("/api/prebuild", {"stop": "1"}, True),
    ("/api/vcmap", {"code": "066570", "refresh": "1"}, True),
    ("/api/story", {"code": "066570", "refresh": "1"}, True),
    ("/api/export/auto", {"on": "1"}, True),
    ("/api/export/auto", {"on": "0"}, True),
    ("/api/export/auto", {"check": "1"}, True),            # 관세청에 지금 묻기
    ("/api/reindex", {}, True),                            # 수집 폴더를 다시 훑어 색인을 쓴다
    ("/api/reports/collect", {}, True),                    # 리포트 수집
    ("/api/value", {"force": "true"}, True),               # '1' 이 아니어도 0 · 빈 값이 아니면 막는다(보수적으로)
])
def test_ro_block_rules(path, q, blocked):
    why = SRV._ro_block(path, q)
    assert (why is not None) == blocked, (path, q, why)
    if blocked:
        assert isinstance(why, str) and why


# ------------------------------------------------------------------ 처리기
def _handler(path, host="127.0.0.1:8770", **hdr):
    from http.client import HTTPMessage
    h = object.__new__(SRV.Handler)
    m = HTTPMessage()
    m["Host"] = host
    for k, v in hdr.items():
        m[k.replace("_", "-")] = v
    h.path, h.headers = path, m
    h.server = types.SimpleNamespace(server_address=("127.0.0.1", 8770))
    sent = []
    h._send = lambda code, body, ctype=None: sent.append((code, body))
    return h, sent


@pytest.fixture
def calls(monkeypatch):
    """일을 시키는 함수들을 기록만 하는 가짜로 — 진짜로 돌지 않게."""
    got = []
    monkeypatch.setattr(SRV, "value_view", lambda force=False: got.append(("value", force)) or {"rows": [], "at": 1})
    monkeypatch.setattr(SRV, "synergy_view", lambda force=False: got.append(("synergy", force)) or {"rows": []})
    monkeypatch.setattr(SRV, "build_index", lambda force=False: got.append(("index", force)) or SRV.INDEX)
    monkeypatch.setattr(SRV, "_vc_refresh_all", lambda: None)     # /api/reindex 가 뒤에서 띄운다 — 기록하면 순서가 흔들린다
    monkeypatch.setattr(SRV, "prebuild_run", lambda auto=False: got.append(("prebuild_run",)) or {"ok": 1})
    monkeypatch.setattr(SRV, "prebuild_stop", lambda: got.append(("prebuild_stop",)) or {"ok": 1})
    monkeypatch.setattr(SRV, "prebuild_status", lambda: {"phase": None})
    monkeypatch.setattr(SRV, "tech_run", lambda: got.append(("tech_run",)) or {"running": True})
    monkeypatch.setattr(SRV, "tech_status", lambda: {"running": False})
    monkeypatch.setattr(SRV, "_rep_collect", lambda: got.append(("rep_collect",)))
    monkeypatch.setattr(SRV, "reports_status", lambda: {"running": False})
    monkeypatch.setattr(SRV, "trades_change", lambda body: got.append(("trades", body)) or {"ok": 1})
    return got


SAME = {"sec_fetch_site": "same-origin", "referer": "http://127.0.0.1:8770/"}


@pytest.mark.parametrize("path, want", [
    ("/api/value?force=1", ("value", True)),
    ("/api/synergy?force=1", ("synergy", True)),
    ("/api/reindex", ("index", True)),
    ("/api/prebuild?run=1", ("prebuild_run",)),
    ("/api/prebuild?stop=1", ("prebuild_stop",)),
    ("/api/tech?run=1", ("tech_run",)),
    ("/api/reports/collect", ("rep_collect",)),
])
def test_readonly_work_get_403(monkeypatch, calls, path, want):
    # 메인(READONLY=False)에서는 그대로 돈다
    monkeypatch.setattr(SRV, "READONLY", False)
    h, sent = _handler(path, **SAME)
    h.do_GET()
    assert sent[0][0] == 200 and calls == [want]
    # 조회 전용에서는 403 JSON · 일을 하나도 안 시킨다(같은 출처 화면에서 와도)
    calls.clear()
    monkeypatch.setattr(SRV, "READONLY", True)
    h, sent = _handler(path, **SAME)
    h.do_GET()
    code, body = sent[0]
    assert code == 403 and body["error"] == RO_MSG and body.get("readonly") is True
    assert calls == []


def test_readonly_plain_get_still_served(monkeypatch, calls):
    monkeypatch.setattr(SRV, "READONLY", True)
    for path, want in (("/api/value", ("value", False)), ("/api/synergy", ("synergy", False))):
        calls.clear()
        h, sent = _handler(path)
        h.do_GET()
        assert sent[0][0] == 200 and calls == [want]
    h, sent = _handler("/api/prebuild")
    h.do_GET()
    assert sent[0][0] == 200 and sent[0][1] == {"phase": None}


def test_readonly_post_403(monkeypatch, calls):
    # 매매 일지 쓰기 — 같은 출처 · JSON 이어도 조회 전용이면 몸통을 읽기 전에 403
    monkeypatch.setattr(SRV, "READONLY", True)
    h, sent = _handler("/api/trades", origin="http://127.0.0.1:8770", content_type="application/json", content_length="2")
    h.rfile = None                                   # 몸통을 읽으려 들면 AttributeError → 500 이 된다
    h.do_POST()
    code, body = sent[0]
    assert code == 403 and body["error"] == RO_MSG and calls == []
    h, sent = _handler("/api/whatever", origin="http://127.0.0.1:8770")
    h.do_POST()
    assert sent[0][0] == 403 and sent[0][1]["error"] == RO_MSG


def test_post_main_unchanged(monkeypatch, calls):
    import io
    monkeypatch.setattr(SRV, "READONLY", False)
    raw = json.dumps({"op": "x"}).encode("utf-8")
    h, sent = _handler("/api/trades", origin="http://127.0.0.1:8770", content_type="application/json", content_length=str(len(raw)))
    h.rfile = io.BytesIO(raw)
    h.do_POST()
    assert sent[0][0] == 200 and calls == [("trades", {"op": "x"})]


# ------------------------------------------------------------------ /api/mode
def test_api_mode(monkeypatch, tmp_path):
    idx = tmp_path / "색인.json"
    idx.write_text("{}", encoding="utf-8")
    t = dt.datetime(2026, 10, 15, 9, 41, 30).timestamp()
    os.utime(idx, (t, t))
    monkeypatch.setattr(SRV, "INDEX_PATH", str(idx))
    monkeypatch.setenv("GIUP_RO_SHADOW", r"C:\shadow\here")

    monkeypatch.setattr(SRV, "READONLY", True)
    h, sent = _handler("/api/mode")
    h.do_GET()
    code, body = sent[0]
    assert code == 200
    assert body["readonly"] is True and body["index_at"] == "2026-10-15 09:41" and body["shadow"] == r"C:\shadow\here"

    monkeypatch.setattr(SRV, "READONLY", False)
    h, sent = _handler("/api/mode")
    h.do_GET()
    body = sent[0][1]
    assert body["readonly"] is False and body["index_at"] == "2026-10-15 09:41" and body["shadow"] is None

    monkeypatch.setattr(SRV, "INDEX_PATH", str(tmp_path / "없음.json"))
    assert SRV.mode_view()["index_at"] is None


# ------------------------------------------------------------------ 색인 그대로
@pytest.fixture
def idx_world(monkeypatch, tmp_path):
    p = tmp_path / "색인.json"
    cached = {"sig": "옛 지문", "built": 1.0,
              "companies": [{"code": "066570", "name": "LG전자", "dir": "LG전자_066570", "sig": "1:x", "reports": [],
                             "from": "2011-03", "to": "2026-06", "count": 1, "bytes": 1}]}
    p.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(SRV, "INDEX_PATH", str(p))
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "INDEX", {"companies": [], "built": 0})
    monkeypatch.setattr(SRV, "INDEX_STATE", {"ready": False, "building": False, "error": None, "at": 0})
    seen = []
    monkeypatch.setattr(SRV, "out_dir_signature", lambda: seen.append("sig") or "새 지문")
    monkeypatch.setattr(SRV, "scan", lambda prev=None: seen.append("scan") or {"companies": [], "built": 2.0})
    return p, cached, seen


def test_build_index_readonly_keeps_cached(monkeypatch, idx_world):
    p, cached, seen = idx_world
    before = p.stat().st_mtime_ns
    monkeypatch.setattr(SRV, "READONLY", True)
    out = SRV.build_index()
    assert [c["code"] for c in out["companies"]] == ["066570"] and SRV.INDEX_STATE["ready"] is True
    assert SRV.INDEX_STATE["building"] is False
    assert seen == []                                    # 수집 폴더를 훑지도(지문), 다시 읽지도 않는다
    assert p.stat().st_mtime_ns == before                # 색인 파일도 다시 쓰지 않는다


def test_build_index_main_rescans_on_new_sig(monkeypatch, idx_world):
    p, cached, seen = idx_world
    monkeypatch.setattr(SRV, "READONLY", False)
    out = SRV.build_index()
    assert seen == ["sig", "scan"] and out["companies"] == [] and out["sig"] == "새 지문"


def test_build_index_readonly_without_cache_scans(monkeypatch, idx_world):
    p, cached, seen = idx_world
    p.unlink()
    monkeypatch.setattr(SRV, "READONLY", True)
    SRV.build_index()
    assert seen == ["sig", "scan"]                       # 색인이 없으면 어쩔 수 없이 만든다(조회전용이 shadow 로 돌린다)


# ------------------------------------------------------------------ main --readonly: 자동 루프 끔
def test_main_readonly_starts_no_auto_loops(monkeypatch):
    started = []

    class FakeThread:
        def __init__(self, target=None, args=(), daemon=None, **kw):
            self.target = target

        def start(self):
            started.append(getattr(self.target, "__name__", str(self.target)))

    class FakeSrv:
        def serve_forever(self):
            pass

    def stop(_s):
        raise KeyboardInterrupt

    # 이 시험 모듈의 서버 사본에서만 threading · time 을 바꾼다(전역 threading.Thread · time.sleep 은 그대로)
    monkeypatch.setattr(SRV, "threading", types.SimpleNamespace(Thread=FakeThread, Timer=FakeThread))
    monkeypatch.setattr(SRV, "time", types.SimpleNamespace(sleep=stop, time=time.time))
    monkeypatch.setattr(SRV, "_open_server", lambda port: FakeSrv())
    monkeypatch.setattr(SRV, "READONLY", False)
    loops = {"_exp_auto_loop", "_val_auto_loop", "_vc_auto_loop", "_rep_auto_loop", "_ind_auto_loop",
             "_tech_auto_loop", "_druck_auto_loop", "_prebuild_auto_loop"}

    monkeypatch.setattr(SRV.sys, "argv", ["서버.py", "--port", "8770", "--no-browser", "--readonly"])
    assert SRV.main() == 0
    assert SRV.READONLY is True
    assert not loops & set(started) and "_index" in started

    started.clear()
    monkeypatch.setattr(SRV.sys, "argv", ["서버.py", "--port", "8770", "--no-browser"])
    assert SRV.main() == 0
    assert SRV.READONLY is False and loops <= set(started)


# ------------------------------------------------------------------ 웹 화면 · bat
def test_index_html_readonly_banner():
    with open(os.path.join(BASE, "웹", "index.html"), "r", encoding="utf-8") as fh:
        s = fh.read()
    assert "fetch('/api/mode')" in s
    assert "조회 전용 — 이 PC 는 보기만 합니다. 계산 · 수집 · 매매 일지 쓰기는 메인 PC 에서." in s
    assert 'id="roBanner"' in s


def test_bat_is_ascii_and_has_steps():
    with open(BAT, "rb") as fh:
        raw = fh.read()
    assert all(b < 128 for b in raw), "기업추적_조회.bat 은 ASCII 만(cmd 가 비ASCII 를 깨뜨린다)"
    s = raw.decode("ascii")
    for need in ("chcp 65001", "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8", "PYTHONDONTWRITEBYTECODE=1",
                 "where python", "py -3", r"%LOCALAPPDATA%\Programs\Python\Python3", "python.org",
                 "8765", "8770", "LISTENING", "requests", "pip install --user requests openpyxl",
                 "viewer_readonly.py", "--make-shortcut", "--no-shortcut", "pythonw"):
        assert need in s, need
    # 순서(머리 주석 말고 실제 줄에서): 파이썬 → 8765 → 8770 → requests → 바로가기 → pythonw 로 띄우기
    code = "\n".join(ln for ln in s.splitlines() if not ln.lstrip().lower().startswith("rem"))
    order = [code.index(k) for k in ("where python", "%GIUP_RO_MAIN_PORT%", "%GIUP_RO_PORT%", "import requests",
                                     "--make-shortcut", '"%PYWEXE%" "%HERE%viewer_readonly.py"')]
    assert order == sorted(order), order
    assert b"\r\n" in raw and raw.count(b"\n") == raw.count(b"\r\n"), "CRLF 로(LF 만이면 cmd 가 :라벨을 놓칠 수 있다)"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _run_bat(main_port, ro_port):
    env = dict(os.environ, GIUP_RO_DRYRUN="1", GIUP_RO_MAIN_PORT=str(main_port), GIUP_RO_PORT=str(ro_port))
    p = subprocess.run(["cmd.exe", "/d", "/c", BAT], capture_output=True, stdin=subprocess.DEVNULL, env=env, timeout=180)
    return p.returncode, p.stdout.decode("utf-8", "replace")


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe")
def test_bat_dryrun_decisions():
    """bat 의 판단만(GIUP_RO_DRYRUN=1 — 브라우저 · pip · 바로가기 · pythonw 는 echo 만): 메인 포트가 LISTENING 이면 그 주소만,
    아니고 조회 포트가 LISTENING 이면 그 주소만, 둘 다 아니면 띄울 차례를 찍는다."""
    a, b = _free_port(), _free_port()
    ls = socket.socket()
    ls.bind(("127.0.0.1", a))
    ls.listen(1)
    try:
        rc, out = _run_bat(a, b)                       # 메인 포트(a) LISTENING
        assert rc == 0, out
        assert "DRYRUN open http://127.0.0.1:%d/" % a in out and "DRYRUN start" not in out and ":%d/" % b not in out
        rc, out = _run_bat(b, a)                       # 조회 포트(a) LISTENING, 메인(b) 없음
        assert rc == 0, out
        assert "DRYRUN open http://127.0.0.1:%d/" % a in out and "DRYRUN start" not in out
    finally:
        ls.close()
    rc, out = _run_bat(a, b)                           # 둘 다 없음 — 띄울 차례(바로가기 → pythonw → 브라우저)
    assert rc == 0, out
    i_sc, i_st, i_op = out.find("DRYRUN shortcut"), out.find("DRYRUN start"), out.find("DRYRUN open http://127.0.0.1:%d/" % b)
    assert -1 < i_sc < i_st < i_op, out
    assert "--no-shortcut" in out[i_st:i_op] and "--port %d" % b in out[i_st:i_op]


# ------------------------------------------------------------------ 묵은 캐시 — 조회 전용이면 다시 받지 않는다(바깥이 막혀 빈 값이 된다)
def test_age_stale(monkeypatch):
    now = time.time()
    monkeypatch.setattr(SRV, "READONLY", False)
    assert SRV._age_stale(0, 3600) is True and SRV._age_stale(None, 3600) is True
    assert SRV._age_stale(now - 7200, 3600) is True and SRV._age_stale(now - 60, 3600) is False
    monkeypatch.setattr(SRV, "READONLY", True)
    assert SRV._age_stale(0, 3600) is True                # 없으면 어쩔 수 없이 만든다
    assert SRV._age_stale(now - 30 * 86400, 3600) is False


def test_hojae_scan_readonly_keeps_old_cache(monkeypatch, tmp_path):
    # 2026-10-15 확인 때 실제로 본 것: 조회 전용 서버가 6시간 묵은 scan_14d.json(561KB)을 다시 훑으려다 DART 가 막혀
    # 빈 목록(scanned 0)을 shadow 에 써서 그 실행 내내 호재기업 · 시너지가 비었다
    sp = ilu.spec_from_file_location("호재_조회전용_시험", os.path.join(BASE, "호재.py"))
    GOOD = ilu.module_from_spec(sp); sp.loader.exec_module(GOOD)
    monkeypatch.setattr(GOOD, "CACHE_DIR", str(tmp_path))
    cache = tmp_path / "scan_14d.json"
    cache.write_text(json.dumps({"days": 14, "scanned": 1234, "good": [{"code": "000001"}], "check": [], "bad": []}), encoding="utf-8")
    old = time.time() - 6 * 3600
    os.utime(cache, (old, old))
    fetched = []
    monkeypatch.setattr(GOOD, "fetch_recent", lambda key, days: fetched.append(days) or ([], 0))
    monkeypatch.setenv("GIUP_READONLY", "1")
    assert GOOD.scan("KEY", 14, False, 300)["scanned"] == 1234 and fetched == []
    monkeypatch.delenv("GIUP_READONLY")
    assert GOOD.scan("KEY", 14, False, 300)["scanned"] == 0 and fetched == [14]     # 메인 PC 는 전처럼 다시 훑는다


def test_dip_get_readonly_keeps_old_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(SRV, "DIP_DIR", str(tmp_path))
    p = tmp_path / "k.json"
    p.write_text(json.dumps({"status": "000", "list": [1]}), encoding="utf-8")
    old = time.time() - 2 * 86400
    os.utime(p, (old, old))
    import requests
    hits = []
    monkeypatch.setattr(requests, "get", lambda *a, **k: hits.append(a) or (_ for _ in ()).throw(OSError("막힘")))
    monkeypatch.setattr(SRV, "READONLY", True)
    assert SRV._dip_get("http://x", {}, "k") == {"status": "000", "list": [1]} and hits == []
    monkeypatch.setattr(SRV, "READONLY", False)
    assert SRV._dip_get("http://x", {}, "k") is None and len(hits) == 1


# ------------------------------------------------------------------ 키 없는 GET 이 전 종목 뒤 계산을 다시 시작하지 않는다(2026-10-15 검토 RO-1)
@pytest.fixture
def starts(monkeypatch):
    """이 시험 모듈의 서버 사본에서만 threading.Thread 를 '띄운 이름 기록'으로 — 진짜로 돌지 않게."""
    got = []

    class FakeThread:
        def __init__(self, target=None, args=(), daemon=None, **kw):
            self.target = target

        def start(self):
            got.append(getattr(self.target, "__name__", str(self.target)))
    monkeypatch.setattr(SRV, "threading", types.SimpleNamespace(Thread=FakeThread, Timer=FakeThread, Lock=SRV.threading.Lock))
    return got


OLD = time.time() - 30 * 86400          # 한 달 묵은 결과(메인 PC 가 드라이브에 남긴 판)


def _old_world(monkeypatch):
    for k, v in {"running": False, "at": OLD, "rows": [{"x": 1}], "funnel": {}, "drop": []}.items():
        monkeypatch.setitem(SRV.DIP, k, v)
    monkeypatch.setattr(SRV, "_dip_bt", lambda: {})
    monkeypatch.setattr(SRV, "_dip_v2", lambda: None)
    for k, v in {"running": False, "at": OLD, "rows": [], "done": 0, "total": 0}.items():
        monkeypatch.setitem(SRV.BACKLOG, k, v)
    for k, v in {"running": False, "at": OLD, "rows": [{"reliable": False}]}.items():
        monkeypatch.setitem(SRV.SYNERGY, k, v)
    monkeypatch.setattr(SRV, "_syn_bt", lambda: None)
    for k, v in {"running": False, "built": OLD, "rows": []}.items():
        monkeypatch.setitem(SRV.SCREEN, k, v)
    if SRV.SCR is not None:
        for k, v in {"running": False, "at": OLD, "error": None,
                     "result": {"schema": getattr(SRV.SCR, "SCHEMA", None), "inputs_mtime": 0}}.items():
            monkeypatch.setitem(SRV.SCORE, k, v)
        monkeypatch.setattr(SRV, "_score_inputs_mtime", lambda: time.time())    # 재료도 새로 왔다
    if SRV.VOC is not None:
        for k, v in {"running": False, "at": OLD, "results": {"short": {}}, "error": None, "_loaded": True}.items():
            monkeypatch.setitem(SRV.VOCAL, k, v)
        monkeypatch.setattr(SRV, "_vocal_bt", lambda: None)


def _call_views():
    SRV.dip_view()
    SRV.backlog_view()
    SRV.synergy_view()
    SRV.screen()
    if SRV.SCR is not None:
        SRV.score_view()
    if SRV.VOC is not None and SRV.FIN is not None:
        SRV.vocal_view()


def test_readonly_views_keep_old_results(monkeypatch, starts):
    _old_world(monkeypatch)
    monkeypatch.setattr(SRV, "READONLY", True)
    _call_views()
    assert starts == []                                   # 하나도 다시 세지 않는다
    assert SRV.DIP["running"] is False and SRV.SYNERGY["running"] is False and SRV.BACKLOG["running"] is False
    assert SRV.dip_view()["rows"] == [{"x": 1}]           # 드라이브의 메인 PC 판 그대로


def test_main_views_still_refresh_old_results(monkeypatch, starts):
    _old_world(monkeypatch)
    monkeypatch.setattr(SRV, "READONLY", False)
    _call_views()
    want = {"_run_dip", "_run_backlog", "_run_synergy"}
    want |= {"_run_score"} if SRV.SCR is not None else set()
    want |= {"_run_vocal"} if SRV.VOC is not None and SRV.FIN is not None else set()
    assert want <= set(starts) and "_run_screen" in starts     # 메인은 전처럼(스크리너는 행이 비면 다시)


def test_readonly_views_compute_once_when_nothing_saved(monkeypatch, starts):
    # 메모리에만 있는 결과(수주 · 시너지 · 스크리너)는 새 프로세스에서 한 번은 센다 — 그 뒤엔 0줄이어도 다시 안 센다
    monkeypatch.setattr(SRV, "READONLY", True)
    for d, k in ((SRV.BACKLOG, "at"), (SRV.SYNERGY, "at"), (SRV.SCREEN, "built")):
        monkeypatch.setitem(d, k, 0)
        monkeypatch.setitem(d, "rows", [])
        monkeypatch.setitem(d, "running", False)
    monkeypatch.setattr(SRV, "_syn_bt", lambda: None)
    SRV.backlog_view()
    SRV.synergy_view()
    SRV.screen()
    assert sorted(starts) == ["_run_backlog", "_run_screen", "_run_synergy"]
    starts.clear()
    for d, k in ((SRV.BACKLOG, "at"), (SRV.SYNERGY, "at"), (SRV.SCREEN, "built")):
        d["running"] = False
        d[k] = time.time()                                # 다 셌는데 0줄
    SRV.backlog_view()
    SRV.synergy_view()
    SRV.screen()
    assert starts == []


def test_readonly_druck_and_story_news_do_not_kick(monkeypatch):
    called = []
    monkeypatch.setattr(SRV, "druck", lambda *a, **k: called.append(a))
    monkeypatch.setattr(SRV, "_story_news_ok", lambda: True)
    monkeypatch.setattr(SRV, "READONLY", True)
    monkeypatch.setattr(SRV, "DRUCK_STALE_KICKED", set())
    assert SRV._druck_kick_stale("066570") is False and called == []
    assert SRV._story_news_kick("066570", refresh=True) is False
    assert SRV._story_news_note("066570", False, True) == SRV.RO_NEWS_NOTE
    assert "조회 전용" in SRV.RO_NEWS_NOTE
    monkeypatch.setattr(SRV, "READONLY", False)
    assert SRV._druck_kick_stale("066570") is True and len(called) == 1


def test_readonly_sector_map_and_story_mkt_no_rebuild(monkeypatch, starts):
    if SRV.SECT is not None:
        monkeypatch.setitem(SRV.SECT_STATE, "map", {"stale": True, "stocks": {}})
        monkeypatch.setitem(SRV.SECT_STATE, "building", False)
        monkeypatch.setattr(SRV, "READONLY", True)
        assert SRV.sector_map() == {"stale": True, "stocks": {}} and starts == []
        monkeypatch.setattr(SRV, "READONLY", False)
        SRV.sector_map()
        assert starts == ["_run"]
        starts.clear()
        monkeypatch.setitem(SRV.SECT_STATE, "building", False)
    monkeypatch.setitem(SRV.STORY_MKT, "built", "2020-01-01 05:00")
    monkeypatch.setitem(SRV.STORY_MKT, "building", False)
    monkeypatch.setattr(SRV, "_story_mtime", lambda p: 0)
    monkeypatch.setattr(SRV, "READONLY", True)
    SRV._story_mkt()
    assert starts == []
    monkeypatch.setattr(SRV, "READONLY", False)
    SRV._story_mkt()
    assert starts == ["_story_mkt_run"]


def test_readonly_ord_list_uses_saved_list_only(monkeypatch, tmp_path):
    monkeypatch.setattr(SRV, "ORD_DIR", str(tmp_path))
    (tmp_path / "066570.json").write_text(json.dumps({"fetched": "20200101", "ts": 1.0, "items": [{"rcept": "1"}]}), encoding="utf-8")
    import requests
    hits = []
    monkeypatch.setattr(requests, "get", lambda *a, **k: hits.append(a) or (_ for _ in ()).throw(OSError("막힘")))
    monkeypatch.setattr(SRV, "corp_code_of", lambda code: "00401731")
    monkeypatch.setattr(SRV, "READONLY", True)
    assert SRV._ord_list({"code": "066570"}) == [{"rcept": "1"}] and hits == []
    monkeypatch.setattr(SRV, "READONLY", False)
    assert SRV._ord_list({"code": "066570"}) == [{"rcept": "1"}] and len(hits) == 1     # 메인은 12시간 지났으니 묻는다


def test_readonly_fin_no_fetch_without_cache(monkeypatch, tmp_path):
    FIN = SRV.FIN
    if FIN is None:
        pytest.skip("재무 모듈 없음")
    monkeypatch.setattr(FIN, "FIN_DIR", str(tmp_path))
    monkeypatch.setattr(FIN, "CONSENSUS_DIR", str(tmp_path))
    hits = []
    monkeypatch.setattr(FIN.requests, "get", lambda *a, **k: hits.append(a) or (_ for _ in ()).throw(OSError("막힘")))
    monkeypatch.setenv("GIUP_READONLY", "1")
    assert FIN.fetch_shares("00401731", 2026, "11012") == {"shares": None}
    assert FIN.fetch_consensus("066570", "annual") == {"cols": [], "rows": {}}
    assert hits == [] and os.listdir(tmp_path) == []      # 묻지도 않고 빈 값을 캐시하지도 않는다
    monkeypatch.delenv("GIUP_READONLY")
    FIN.fetch_shares("00401731", 2026, "11012")
    FIN.fetch_consensus("066570", "annual")
    assert len(hits) == 2


def test_readonly_vocal_listing_and_fin_use_old_cache(monkeypatch, tmp_path):
    sp = ilu.spec_from_file_location("보컬_조회전용_시험", os.path.join(BASE, "보컬.py"))
    VOC = ilu.module_from_spec(sp)
    sp.loader.exec_module(VOC)
    lst = tmp_path / "listing.json"
    lst.write_text(json.dumps({"at": 1.0, "stocks": {"005930": {}}}), encoding="utf-8")
    monkeypatch.setattr(VOC, "LISTING", str(lst))
    monkeypatch.setattr(VOC, "FIN_DIR", str(tmp_path / "fin"))
    (tmp_path / "fin").mkdir()
    (tmp_path / "fin" / "005930.json").write_text(json.dumps({"q": "2026.06"}), encoding="utf-8")
    old = time.time() - 30 * 86400
    os.utime(tmp_path / "fin" / "005930.json", (old, old))
    fetched = []
    monkeypatch.setattr(VOC, "fetch_listing", lambda: fetched.append("listing") or {"at": time.time(), "stocks": {}})
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: fetched.append("fin") or (_ for _ in ()).throw(OSError("막힘")))
    monkeypatch.setenv("GIUP_READONLY", "1")
    assert VOC.load_listing()["stocks"] == {"005930": {}}
    assert VOC.fetch_fin("005930") == {"q": "2026.06"} and VOC.fetch_fin("000660") is None
    lst.unlink()
    assert VOC.load_listing() is None and fetched == []
    monkeypatch.delenv("GIUP_READONLY")
    VOC.load_listing()
    VOC.fetch_fin("000660")
    assert fetched == ["listing", "fin"]


# ------------------------------------------------------------------ 웹 화면 — 조회 전용이면 일을 시키는 단추를 만들지 않는다(검토 C2 · C3 · C6)
def test_index_html_readonly_buttons():
    with open(os.path.join(BASE, "웹", "index.html"), "r", encoding="utf-8") as fh:
        s = fh.read()
    assert "if(!RO.on){ const rf=el('button','ghost','다시 계산'); rf.onclick=()=>load(true)" in s      # 시너지 다시 계산
    assert "S.synErr=d.error" in s and "S.synData=null" in s                                            # 오류를 표 캐시에 넣지 않는다
    assert "if(!RO.on){     // 조회 전용 — 리포트 수집" in s and "e=r.ok?null:" in s                         # 리포트 지금 받기
    assert "if(N.ok!==false&&!RO.on){ const b=el('button','ghost','뉴스 새로 받기')" in s                  # 뉴스 새로 받기

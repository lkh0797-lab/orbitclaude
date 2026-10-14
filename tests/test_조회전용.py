# -*- coding: utf-8 -*-
"""조회 전용 모드(2026-10-15) — 같은 구글 드라이브를 받는 다른 PC 에서 화면을 '보기만' 할 때.
조회전용.enable() 은 open · os · socket · subprocess 를 프로세스 전체에서 바꾸므로, 켜 보는 검사는 모두
**별도 python 프로세스**(subprocess.run, sys.executable)에서 한다 — pytest 프로세스를 오염시키지 않게.
자식은 한 일과 본 것을 JSON 한 줄로 내고, 파일 시스템은 부모(패치 안 됨)가 직접 들여다본다."""
import os, sys, json, time, hashlib, base64, textwrap, subprocess, importlib.util as ilu
import datetime as dt

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MSG_NET = "조회 전용 — 바깥 호출 안 함"
MSG_PROC = "조회 전용 — 다른 프로그램을 띄우지 않음"


def _child(code, *args, cwd=None):
    """자식 python 에서 code 를 돌린다. 머리에 sys.path · 조회전용 import 를 붙인다. 마지막 줄 JSON 을 돌려준다."""
    head = "import sys, os, json\nsys.dont_write_bytecode = True\nsys.path.insert(0, %r)\nimport 조회전용 as RO\n" % BASE
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    env.pop("GIUP_READONLY", None)
    p = subprocess.run([sys.executable, "-X", "utf8", "-c", head + textwrap.dedent(code)] + [str(a) for a in args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd, env=env, timeout=120)
    assert p.returncode == 0, "자식 실패\n--- stdout\n%s\n--- stderr\n%s" % (p.stdout, p.stderr)
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    return json.loads(lines[-1])


def _snap(root):
    """root 아래 전부 — 상대 경로 → (종류, 크기, mtime_ns, 내용 해시)."""
    out = {}
    for d, dirs, files in os.walk(root):
        for n in dirs:
            p = os.path.join(d, n)
            out[os.path.relpath(p, root)] = ("d", os.stat(p).st_mtime_ns)
        for n in files:
            p = os.path.join(d, n)
            st = os.stat(p)
            with open(p, "rb") as fh:
                h = hashlib.sha1(fh.read()).hexdigest()
            out[os.path.relpath(p, root)] = ("f", st.st_size, st.st_mtime_ns, h)
    return out


def _read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture
def tree(tmp_path):
    base = tmp_path / "드라이브" / "기업추적"
    (base / "sub").mkdir(parents=True)
    (base / ".cache").mkdir()
    for name, text in {"keep.txt": "원래", "log.txt": "원래", "gone.txt": "지울 것", "keep2.txt": "시각",
                       "sub/old.json": '{"v": 0}', ".cache/색인.json": "{}"}.items():
        (base / name).write_text(text, encoding="utf-8")
    old = time.time() - 86400 * 3
    os.utime(base / "keep2.txt", (old, old))
    shadow = tmp_path / "로컬" / "조회전용" / "shadow"
    outside = tmp_path / "밖"
    outside.mkdir()
    return base, shadow, outside


# ------------------------------------------------------------------ 쓰기 돌리기
FILE_OPS = r"""
import tempfile, pathlib
base, shadow, outside = sys.argv[1:4]
RO.enable(base=base, shadow=shadow)
J = os.path.join
r = {}
with open(J(base, "new.txt"), "w", encoding="utf-8") as fh:            # 새 파일
    fh.write("새것")
with open(J(base, "keep.txt"), "w", encoding="utf-8") as fh:           # 있는 파일 덮어쓰기
    fh.write("바뀜")
r["keep"] = open(J(base, "keep.txt"), encoding="utf-8").read()          # 다시 읽기는 shadow 먼저
with open(J(base, "log.txt"), "a", encoding="utf-8") as fh:            # 이어 쓰기 — base 를 먼저 복사
    fh.write("+1")
r["log"] = open(J(base, "log.txt"), encoding="utf-8").read()
r["untouched"] = open(J(base, "sub", "old.json"), encoding="utf-8").read()   # 안 쓴 파일은 base 그대로
os.chdir(base)                                                         # 상대 경로는 cwd 기준
with open("rel.txt", "w", encoding="utf-8") as fh:
    fh.write("상대")
r["rel"] = open("rel.txt", encoding="utf-8").read()
tmp = J(base, "sub", "a.json.%d.tmp" % os.getpid())                  # 재무._write_json 과 같은 순서
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump({"a": 1}, fh)
os.replace(tmp, J(base, "sub", "a.json"))
r["replaced"] = json.load(open(J(base, "sub", "a.json"), encoding="utf-8"))
r["tmp_left"] = os.path.exists(tmp)
fd, name = tempfile.mkstemp(dir=base, suffix=".tmp")
os.write(fd, b"mk")
os.close(fd)
r["mkstemp"] = os.path.basename(name)
r["mkstemp_read"] = open(name, "rb").read().decode()
os.makedirs(J(base, "d1", "d2"))
os.makedirs(J(base, "d1", "d2"), exist_ok=True)
try:
    os.makedirs(J(base, "d1", "d2"))
    r["makedirs_again"] = "ok"
except FileExistsError:
    r["makedirs_again"] = "FileExistsError"
r["isdir_d2"] = os.path.isdir(J(base, "d1", "d2"))
os.makedirs(J(base, ".cache"), exist_ok=True)                          # 이미 있는 폴더
os.mkdir(J(base, "m1"))
with open(J(base, "d1", "d2", "deep.txt"), "w", encoding="utf-8") as fh:
    fh.write("깊이")
os.remove(J(base, "gone.txt"))                                         # base 는 그대로, 이번 실행에서는 없는 것
r["gone_exists"] = os.path.exists(J(base, "gone.txt"))
try:
    open(J(base, "gone.txt"), encoding="utf-8").read()
    r["gone_read"] = "read"
except FileNotFoundError:
    r["gone_read"] = "FileNotFoundError"
os.unlink(J(base, "new.txt"))
r["new_after_unlink"] = os.path.exists(J(base, "new.txt"))
try:
    os.remove(J(base, "없는파일.txt"))
    r["remove_missing"] = "ok"
except FileNotFoundError:
    r["remove_missing"] = "FileNotFoundError"
try:
    open(J(base, "없는폴더", "x.txt"), "w")
    r["no_parent"] = "ok"
except FileNotFoundError:
    r["no_parent"] = "FileNotFoundError"
fd = os.open(J(base, "osopen.bin"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
os.write(fd, b"z")
os.close(fd)
os.utime(J(base, "keep2.txt"), (1000000000, 1000000000))
r["keep2_mtime"] = int(os.path.getmtime(J(base, "keep2.txt")))
pathlib.Path(base, "pl.txt").write_text("패스", encoding="utf-8")
r["pl"] = pathlib.Path(base, "pl.txt").read_text(encoding="utf-8")
os.rename(J(base, "pl.txt"), J(base, "pl2.txt"))
r["pl2"] = open(J(base, "pl2.txt"), encoding="utf-8").read()
os.rmdir(J(base, "m1"))
r["m1"] = os.path.isdir(J(base, "m1"))
with open(J(outside, "out.txt"), "w", encoding="utf-8") as fh:         # base 밖은 그대로
    fh.write("밖")
os.makedirs(J(outside, "od"), exist_ok=True)
r["env"] = os.environ.get("GIUP_READONLY")
r["dont_write_bytecode"] = sys.dont_write_bytecode
print(json.dumps(r, ensure_ascii=False))
"""


def test_writes_go_to_shadow_and_base_is_untouched(tree):
    base, shadow, outside = tree
    before = _snap(base)
    r = _child(FILE_OPS, base, shadow, outside, cwd=str(outside))
    assert _snap(base) == before                                     # 드라이브 쪽은 한 바이트도 안 바뀜
    assert r["keep"] == "바뀜" and r["log"] == "원래+1" and r["untouched"] == '{"v": 0}'
    assert r["rel"] == "상대" and r["replaced"] == {"a": 1} and r["tmp_left"] is False
    assert r["mkstemp_read"] == "mk" and r["makedirs_again"] == "FileExistsError" and r["isdir_d2"] is True
    assert r["gone_exists"] is False and r["gone_read"] == "FileNotFoundError"
    assert r["new_after_unlink"] is False and r["remove_missing"] == "FileNotFoundError"
    assert r["no_parent"] == "FileNotFoundError"
    assert r["keep2_mtime"] == 1000000000
    assert r["pl"] == "패스" and r["pl2"] == "패스" and r["m1"] is False
    assert r["env"] == "1" and r["dont_write_bytecode"] is True
    S = lambda *p: os.path.join(shadow, *p)
    assert _read(S("keep.txt")) == "바뀜" and _read(S("log.txt")) == "원래+1"
    assert _read(S("rel.txt")) == "상대" and _read(S("d1", "d2", "deep.txt")) == "깊이"
    assert json.load(open(S("sub", "a.json"), encoding="utf-8")) == {"a": 1}
    assert not [f for f in os.listdir(S("sub")) if f.endswith(".tmp")]
    assert os.path.exists(S(r["mkstemp"])) and not os.path.exists(os.path.join(base, r["mkstemp"]))
    assert open(S("osopen.bin"), "rb").read() == b"z"
    assert int(os.path.getmtime(S("keep2.txt"))) == 1000000000 and _read(S("keep2.txt")) == "시각"
    assert _read(S("pl2.txt")) == "패스" and not os.path.exists(S("pl.txt"))
    assert not os.path.exists(S("new.txt")) and not os.path.exists(S("m1"))
    assert _read(os.path.join(outside, "out.txt")) == "밖" and os.path.isdir(os.path.join(outside, "od"))


SHADOW_FRESH = r"""
base, shadow = sys.argv[1:3]
RO.enable(base=base, shadow=shadow)
r = {"keep": open(os.path.join(base, "keep.txt"), encoding="utf-8").read(),
     "stale_left": os.path.exists(os.path.join(shadow, "keep.txt")),
     "mark": os.path.exists(os.path.join(shadow, RO.MARK))}
print(json.dumps(r, ensure_ascii=False))
"""


def test_shadow_is_emptied_on_enable_so_old_runs_never_hide_new_drive_files(tree):
    base, shadow, _ = tree
    shadow.mkdir(parents=True)
    (shadow / ".조회전용_shadow").write_text("", encoding="utf-8")
    (shadow / "keep.txt").write_text("지난 실행 것", encoding="utf-8")
    r = _child(SHADOW_FRESH, base, shadow)
    assert r == {"keep": "원래", "stale_left": False, "mark": True}


GUARDS = r"""
base, shadow, foreign = sys.argv[1:4]
r = {}
for name, b, s in (("inside", base, os.path.join(base, "shadow")), ("same", base, base),
                   ("parent", base, os.path.dirname(base)), ("foreign", base, foreign)):
    try:
        RO.enable(base=b, shadow=s)
        r[name] = "on"
        RO.disable()
    except ValueError:
        r[name] = "ValueError"
r["foreign_kept"] = os.path.exists(os.path.join(foreign, "남의파일.txt"))
r["env"] = os.environ.get("GIUP_READONLY")
print(json.dumps(r, ensure_ascii=False))
"""


def test_enable_refuses_shadow_inside_base_or_a_foreign_folder(tree, tmp_path):
    base, _, _ = tree
    foreign = tmp_path / "남의폴더"
    foreign.mkdir()
    (foreign / "남의파일.txt").write_text("x", encoding="utf-8")
    before = _snap(base)
    r = _child(GUARDS, base, base / "shadow", foreign)
    assert r == {"inside": "ValueError", "same": "ValueError", "parent": "ValueError", "foreign": "ValueError",
                 "foreign_kept": True, "env": None}
    assert _snap(base) == before


NO_PYC = r"""
base, shadow = sys.argv[1:3]
sys.dont_write_bytecode = False            # enable 이 다시 켜야 한다(importlib 의 pyc 쓰기는 os.open 패치를 안 거친다)
RO.enable(base=base, shadow=shadow)
sys.path.insert(0, base)
import 작은모듈
print(json.dumps({"v": 작은모듈.V, "flag": sys.dont_write_bytecode}, ensure_ascii=False))
"""


def test_imports_from_base_write_no_pycache(tree):
    base, shadow, _ = tree
    (base / "작은모듈.py").write_text("V = 7\n", encoding="utf-8")
    r = _child(NO_PYC, base, shadow)
    assert r == {"v": 7, "flag": True}
    assert not (base / "__pycache__").exists()


# ------------------------------------------------------------------ 바깥 연결 · 프로그램 실행 막기
NET = r"""
import socket, threading, urllib.request
base, shadow = sys.argv[1:3]
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(5)
port = srv.getsockname()[1]
def _acc():
    while True:
        try:
            c, _ = srv.accept(); c.close()
        except OSError:
            return
threading.Thread(target=_acc, daemon=True).start()
RO.enable(base=base, shadow=shadow)
r = {}
def tryit(name, fn):
    try:
        fn(); r[name] = "ok"
    except OSError as e:
        r[name] = str(e)
tryit("create_connection_out", lambda: socket.create_connection(("203.0.113.9", 80), timeout=2))
tryit("create_connection_name", lambda: socket.create_connection(("opendart.fss.or.kr", 443), timeout=2))
tryit("connect_out", lambda: socket.socket().connect(("8.8.8.8", 53)))
tryit("urlopen", lambda: urllib.request.urlopen("http://example.com/", timeout=2))
tryit("loop_create", lambda: socket.create_connection(("127.0.0.1", port), timeout=2).close())
tryit("loop_localhost", lambda: socket.create_connection(("localhost", port), timeout=2).close())
s = socket.socket(); tryit("loop_connect", lambda: s.connect(("127.0.0.1", port))); s.close()
os.environ["HTTP_PROXY"] = "http://127.0.0.1:%d" % port                # loopback 프록시가 있어도 바깥으로 못 나간다
tryit("urlopen_proxy", lambda: urllib.request.build_opener().open("http://example.com/", timeout=2))   # 새 opener 가 프록시 환경을 읽는다
import asyncio                                                         # 텔레그램(telethon) 길 — Windows 는 Proactor 루프
async def _aio():
    await asyncio.open_connection("203.0.113.9", 443)
tryit("asyncio", lambda: asyncio.run(_aio()))
print(json.dumps(r, ensure_ascii=False))
"""


def test_outside_connections_blocked_loopback_allowed(tree):
    base, shadow, _ = tree
    r = _child(NET, base, shadow)
    for k in ("create_connection_out", "create_connection_name", "connect_out", "urlopen", "urlopen_proxy", "asyncio"):
        assert MSG_NET in r[k], (k, r[k])
    assert r["loop_create"] == "ok" and r["loop_localhost"] == "ok" and r["loop_connect"] == "ok"


PROC = r"""
import subprocess
base, shadow = sys.argv[1:3]
RO.enable(base=base, shadow=shadow)
r = {}
def tryit(name, fn):
    try:
        fn(); r[name] = "ok"
    except OSError as e:
        r[name] = str(e)
tryit("popen", lambda: subprocess.Popen([sys.executable, "-c", "pass"]))
tryit("run", lambda: subprocess.run([sys.executable, "-c", "pass"]))
tryit("call", lambda: subprocess.call("echo hi", shell=True))
tryit("system", lambda: os.system("echo hi"))
if hasattr(os, "startfile"):
    tryit("startfile", lambda: os.startfile(os.path.join(base, "없는파일.zzz")))   # 안 막혀도 창은 안 뜨는 경로
if "조회 전용" in r.get("startfile", "조회 전용") and "조회 전용" in r["popen"]:
    import webbrowser                                          # 막힌 게 확인됐을 때만 — 기본 브라우저는 os.startfile
    r["webbrowser"] = webbrowser.open("http://127.0.0.1:1/")
print(json.dumps(r, ensure_ascii=False))
"""


def test_launching_other_programs_blocked(tree):
    base, shadow, _ = tree
    r = _child(PROC, base, shadow)
    for k in ("popen", "run", "call", "system") + (("startfile",) if os.name == "nt" else ()):
        assert MSG_PROC in r[k], (k, r[k])
    assert r.get("webbrowser") is False


# ------------------------------------------------------------------ 재무: 조회 전용이면 캐시가 있으면 그대로
_sp = ilu.spec_from_file_location("재무_조회전용_시험", os.path.join(BASE, "재무.py"))
FIN = ilu.module_from_spec(_sp)
sys.path.insert(0, BASE)
_sp.loader.exec_module(FIN)
D = dt.datetime


def _old_file(tmp_path, name, text="{}", days=30):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    t = time.time() - days * 86400
    os.utime(p, (t, t))
    return str(p)


def test_cache_ok_readonly_keeps_any_existing_file(tmp_path, monkeypatch):
    p = _old_file(tmp_path, "x.json")
    monkeypatch.delenv("GIUP_READONLY", raising=False)
    assert not FIN._cache_ok(p, 86400)                               # 평소: 오래됐으니 다시 받는다
    monkeypatch.setenv("GIUP_READONLY", "1")
    assert FIN._cache_ok(p, 86400)                                   # 조회 전용: 있으면 그대로(만기 · 20:10 규칙 안 봄)
    assert FIN._cache_ok(p, 86400, now=D(2030, 1, 1, 21, 0))
    assert not FIN._cache_ok(str(tmp_path / "없음.json"), 86400)     # 없는 파일은 여전히 False
    monkeypatch.setenv("GIUP_READONLY", "0")
    assert not FIN._cache_ok(p, 86400)


def test_readonly_consensus_and_013_use_old_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(FIN, "CONSENSUS_DIR", str(tmp_path))
    body = {"cols": [{"key": "202606", "title": "2026.06", "consensus": False}], "rows": {"매출액": {"202606": 1.0}}}
    _old_file(tmp_path, "066570_quarter.json", json.dumps(body, ensure_ascii=False))

    def _no_net(*a, **k):
        raise OSError(MSG_NET)
    monkeypatch.setattr(FIN.requests, "get", _no_net)
    monkeypatch.setenv("GIUP_READONLY", "1")
    assert FIN.fetch_consensus("066570", "quarter") == body          # 6시간 지났어도 받은 것 그대로
    p = _old_file(tmp_path, "013.json")
    t = time.mktime((2026, 7, 10, 0, 0, 0, 0, 0, -1))              # 2026 반기(06-30) 마감 열흘 뒤에 받은 '없음'(013)
    os.utime(p, (t, t))
    d = {"status": "013", "list": []}
    assert FIN._stale_013(d, p, 2026, "11012") is False             # 조회 전용: 다시 받으려 하지 않는다
    monkeypatch.delenv("GIUP_READONLY")
    assert FIN.fetch_consensus("066570", "quarter") == {"cols": [], "rows": {}}
    assert FIN._stale_013(d, p, 2026, "11012") is True


# ------------------------------------------------------------------ viewer_readonly.py
@pytest.fixture
def VR(monkeypatch):
    keep = sys.dont_write_bytecode
    sp = ilu.spec_from_file_location("viewer_readonly_시험", os.path.join(BASE, "viewer_readonly.py"))
    m = ilu.module_from_spec(sp)
    sp.loader.exec_module(m)
    yield m
    sys.dont_write_bytecode = keep


def _decode(cmd):
    i = cmd.index("-EncodedCommand")
    return base64.b64decode(cmd[i + 1]).decode("utf-16-le")


def test_shortcut_script_and_encoding(VR):
    s = VR.shortcut_ps(r"G:\내 드라이브\Claude\주식\기업추적\기업추적_조회.bat", r"G:\내 드라이브\it's")
    assert "[Environment]::GetFolderPath('Desktop')" in s
    assert "'기업추적.lnk'" in s and "기업추적_조회.bat" in s
    assert r"'G:\내 드라이브\it''s'" in s                              # 작은따옴표는 두 번
    assert base64.b64decode(VR.encode_ps(s)).decode("utf-16-le") == s


def test_ensure_shortcut_exists_or_makes_through_powershell(VR, tmp_path, monkeypatch):
    monkeypatch.delenv("GIUP_NO_SHORTCUT", raising=False)
    calls = []

    class P:
        returncode, stdout, stderr = 0, "made\r\n", ""

    def run(cmd, **kw):
        calls.append((cmd, kw))
        return P()
    (tmp_path / "기업추적.lnk").write_bytes(b"x")
    assert VR.ensure_shortcut(desktop=str(tmp_path), run=run) == "exists" and calls == []
    other = tmp_path / "빈바탕화면"
    other.mkdir()
    assert VR.ensure_shortcut(desktop=str(other), run=run) == "made"
    cmd, kw = calls[0]
    assert os.path.basename(cmd[0]).lower().startswith("powershell") and "-NoProfile" in cmd
    script = _decode(cmd)
    assert os.path.join(BASE, "기업추적_조회.bat") in script and "WScript.Shell" in script
    assert kw.get("timeout") and kw.get("creationflags") is not None
    monkeypatch.setenv("GIUP_NO_SHORTCUT", "1")
    assert VR.ensure_shortcut(desktop=str(other), run=run) == "skip" and len(calls) == 1


def test_ensure_shortcut_never_raises(VR, tmp_path, monkeypatch):
    monkeypatch.delenv("GIUP_NO_SHORTCUT", raising=False)

    def boom(cmd, **kw):
        raise OSError("powershell 없음")
    assert VR.ensure_shortcut(desktop=str(tmp_path), run=boom).startswith("failed")


def test_server_args(VR):
    a = VR.server_args([])
    assert a[a.index("--port") + 1] == "8770"
    assert {"--readonly", "--no-auto", "--no-browser"} <= set(a)
    b = VR.server_args(["--port", "8771", "--no-shortcut", "--make-shortcut"])
    assert b[b.index("--port") + 1] == "8771" and "--no-shortcut" not in b and "--make-shortcut" not in b
    assert b.count("--port") == 1


def test_main_makes_shortcut_before_readonly_then_runs_server(VR, monkeypatch, tmp_path):
    order = []
    monkeypatch.setattr(VR, "ensure_shortcut", lambda **k: order.append("shortcut") or "exists")
    monkeypatch.setattr(VR.RO, "enable", lambda **k: order.append(("enable", k["base"], k["shadow"])))
    monkeypatch.setattr(VR.runpy, "run_path", lambda p, run_name=None: order.append(("run", p, list(sys.argv))))
    monkeypatch.setattr(sys, "argv", ["viewer_readonly.py"])
    monkeypatch.setattr(VR, "LOCAL", str(tmp_path))
    VR.main(["--port", "8770"])
    assert order[0] == "shortcut"
    assert order[1] == ("enable", BASE, os.path.join(str(tmp_path), "shadow"))
    assert order[2][:2] == ("run", os.path.join(BASE, "서버.py"))
    assert order[2][2][0] == os.path.join(BASE, "서버.py") and {"--readonly", "--no-auto", "--no-browser"} <= set(order[2][2])
    order.clear()
    VR.main(["--port", "8770", "--no-shortcut"])                     # 확인용 — 바탕화면을 건드리지 않는다
    assert order[0][0] == "enable"
    order.clear()
    with pytest.raises(SystemExit):
        VR.main(["--make-shortcut"])                                 # 바로가기만 만들고 끝(서버 안 띄움)
    assert order == ["shortcut"]

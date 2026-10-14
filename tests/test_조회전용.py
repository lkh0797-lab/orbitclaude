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


# ------------------------------------------------------------------ 패치 밖 길 — 감사 훅 백스톱 · 접두 · 먼저 잡힌 open (2026-10-15 검토 RO-3 · RO-4)
SIDE = r"""
import io, _io, bz2, tarfile, shutil, sqlite3, importlib
base, shadow, outside, junction = sys.argv[1:5]
RO.enable(base=base, shadow=shadow)
J = os.path.join
r = {}
def tryit(name, fn):
    try:
        fn(); r[name] = "ok"
    except OSError as e:
        r[name] = "%s: %s" % (type(e).__name__, e)
def _w(opener, path):
    with opener(path) as fh:
        fh.write(b"x")
tryit("fileio", lambda: _w(lambda p: io.FileIO(p, "w"), J(base, "fileio.txt")))
tryit("_io_open", lambda: _w(lambda p: _io.open(p, "wb"), J(base, "_io.txt")))
tryit("_io_fileio_sub", lambda: _w(lambda p: _io.FileIO(p, "a"), J(base, "sub", "old.json")))
r["fileio_read"] = io.FileIO(J(base, "keep.txt"), "r").read().decode("utf-8")         # 읽기는 그대로
tryit("bz2", lambda: _w(lambda p: bz2.open(p, "wb"), J(base, "x.bz2")))             # shutil 이 먼저 읽은 bz2 — shadow 로
tryit("tar", lambda: tarfile.open(J(base, "x.tar"), "w").close())                    # 먼저 읽은 tarfile — shadow 로
tryit("link_in", lambda: os.link(J(base, "keep.txt"), J(base, "hard.txt")))
tryit("link_out", lambda: os.link(J(base, "keep.txt"), J(outside, "hard.txt")))     # base 파일을 밖에서 고칠 길 — 막는다
tryit("sqlite", lambda: sqlite3.connect(J(base, "db.sqlite")).execute("create table t(x)"))
tryit("sqlite_mem", lambda: sqlite3.connect(":memory:").execute("create table t(x)"))
tryit("copy2", lambda: shutil.copy2(J(base, "keep.txt"), J(base, "copy2.txt")))      # 3.12+ 는 _winapi.CopyFile2 → 거절 → copyfile(shadow)
r["copy2_read"] = open(J(base, "copy2.txt"), encoding="utf-8").read() if r["copy2"] == "ok" else None
P = "\\\\?\\"
tryit("prefixed", lambda: _w(lambda p: open(p, "wb"), P + J(base, "prefixed.txt")))
tryit("prefixed_replace", lambda: os.replace(P + J(base, "keep.txt"), P + J(base, "keep_moved.txt")))
r["keep_after"] = os.path.exists(J(base, "keep.txt"))
r["moved_read"] = open(J(base, "keep_moved.txt"), encoding="utf-8").read()
if junction:                                                                         # base 를 가리키는 junction — realpath 로 알아본다
    tryit("junction", lambda: _w(lambda p: open(p, "wb"), J(junction, "via_junction.txt")))
    tryit("junction_fileio", lambda: _w(lambda p: io.FileIO(p, "w"), J(junction, "via_junction2.txt")))
tryit("outside", lambda: _w(lambda p: io.FileIO(p, "w"), J(outside, "fine.txt")))   # base 밖은 그대로
sys.path.insert(0, base)
sys.dont_write_bytecode = False                                                      # 꺼져도 pyc 는 base 에 안 생긴다(훅이 막고 importlib 은 넘긴다)
importlib.invalidate_caches()
import 훅모듈
r["mod"] = 훅모듈.V
print(json.dumps(r, ensure_ascii=False))
"""


def test_side_doors_cannot_change_base(tree, tmp_path):
    base, shadow, outside = tree
    (base / "훅모듈.py").write_text("V = 3\n", encoding="utf-8")
    junction = ""
    if os.name == "nt":
        try:
            import _winapi
            _winapi.CreateJunction(str(base), str(tmp_path / "정션"))
            junction = str(tmp_path / "정션")
        except (ImportError, AttributeError, OSError):
            junction = ""
    try:
        before = _snap(base)
        r = _child(SIDE, base, shadow, outside, junction)
    finally:
        if junction:
            os.rmdir(junction)                                       # junction 만 지운다(가리키는 폴더는 그대로)
    assert _snap(base) == before, sorted(set(_snap(base)) ^ set(before))   # 드라이브 쪽은 하나도 안 바뀜
    for k in ("fileio", "_io_open", "_io_fileio_sub", "link_in", "link_out", "sqlite"):
        assert r[k].startswith("PermissionError") and "조회 전용" in r[k], (k, r[k])
    if junction:
        assert r["junction"].startswith("PermissionError") and r["junction_fileio"].startswith("PermissionError"), r
    assert r["fileio_read"] == "원래" and r["sqlite_mem"] == "ok" and r["outside"] == "ok"
    assert r["bz2"] == "ok" and os.path.exists(os.path.join(shadow, "x.bz2"))
    assert r["tar"] == "ok" and os.path.exists(os.path.join(shadow, "x.tar"))
    assert r["copy2"] == "ok" and r["copy2_read"] == "원래" and _read(os.path.join(shadow, "copy2.txt")) == "원래"
    assert r["prefixed"] == "ok" and open(os.path.join(shadow, "prefixed.txt"), "rb").read() == b"x"
    assert r["prefixed_replace"] == "ok" and r["keep_after"] is False and r["moved_read"] == "원래"
    assert _read(os.path.join(shadow, "keep_moved.txt")) == "원래"
    assert not os.path.exists(os.path.join(outside, "hard.txt")) and os.path.exists(os.path.join(outside, "fine.txt"))
    assert r["mod"] == 3 and not (base / "__pycache__").exists()


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
# DNS 질의도 바깥 호출(검토 RO-2) — 이름을 묻는 순간 막는다. IP 리터럴 · localhost 는 묻지 않으니 통과
tryit("gai_name", lambda: socket.getaddrinfo("opendart.fss.or.kr", 443))
tryit("ghbn", lambda: socket.gethostbyname("m.stock.naver.com"))
tryit("ghbn_ex", lambda: socket.gethostbyname_ex("api.finance.naver.com"))
tryit("ghba", lambda: socket.gethostbyaddr("8.8.8.8"))
tryit("gni", lambda: socket.getnameinfo(("8.8.8.8", 53), 0))
tryit("gai_literal", lambda: socket.getaddrinfo("203.0.113.9", 80))
tryit("gai_local", lambda: socket.getaddrinfo("localhost", port))
tryit("gai_none", lambda: socket.getaddrinfo(None, port))
async def _aio_dns():
    await asyncio.get_running_loop().getaddrinfo("opendart.fss.or.kr", 443)
tryit("asyncio_dns", lambda: asyncio.run(_aio_dns()))
try:
    import requests
    tryit("requests", lambda: requests.get("https://opendart.fss.or.kr/api/list.json", timeout=3))
except ImportError:
    r["requests"] = "없음"
# UDP 는 connect 없이 나가고, _socket 은 socket.socket 패치를 지나친다(검토 RO-5) — 감사 훅이 막는다
import _socket
tryit("udp_out", lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("192.0.2.1", 9)))
tryit("udp_out_flags", lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", 0, ("192.0.2.1", 9)))
tryit("raw_udp_out", lambda: _socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("192.0.2.1", 9)))
tryit("raw_connect_out", lambda: _socket.socket().connect(("192.0.2.1", 9)))
u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); u.bind(("127.0.0.1", 0))
tryit("udp_loop", lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", u.getsockname()))
rs = _socket.socket(); tryit("raw_loop", lambda: rs.connect(("127.0.0.1", port))); rs.close()
print(json.dumps(r, ensure_ascii=False))
"""


DNS_SEEN = r"""
seen = []
sys.addaudithook(lambda ev, a: seen.append(str(a[0])) if ev in ("socket.getaddrinfo", "socket.gethostbyname") else None)
"""


def test_outside_connections_blocked_loopback_allowed(tree):
    base, shadow, _ = tree
    r = _child(NET, base, shadow)
    for k in ("create_connection_out", "create_connection_name", "connect_out", "urlopen", "urlopen_proxy", "asyncio",
              "gai_name", "ghbn", "ghbn_ex", "ghba", "gni", "asyncio_dns",
              "udp_out", "udp_out_flags", "raw_udp_out", "raw_connect_out"):
        assert MSG_NET in r[k], (k, r[k])
    if r["requests"] != "없음":
        assert MSG_NET in r["requests"], r["requests"]
    assert r["loop_create"] == "ok" and r["loop_localhost"] == "ok" and r["loop_connect"] == "ok"
    assert r["gai_literal"] == "ok" and r["gai_local"] == "ok" and r["gai_none"] == "ok"
    assert r["udp_loop"] == "ok" and r["raw_loop"] == "ok"


def test_no_dns_query_leaves_the_process(tree):
    """먼저 건 기록 훅이 C 수준 getaddrinfo · gethostbyname 이벤트를 하나도 못 본다 = 이름을 묻기 전에(파이썬 쪽에서) 막혔다."""
    base, shadow, _ = tree
    code = DNS_SEEN + r"""
base, shadow = sys.argv[1:3]
RO.enable(base=base, shadow=shadow)
import socket, urllib.request
for f in (lambda: socket.getaddrinfo("opendart.fss.or.kr", 443), lambda: socket.create_connection(("m.stock.naver.com", 443), timeout=2),
          lambda: urllib.request.urlopen("https://api.finance.naver.com/", timeout=2)):
    try:
        f()
    except OSError:
        pass
try:
    import requests
    requests.get("https://opendart.fss.or.kr/api/list.json", timeout=3)
except Exception:
    pass
print(json.dumps({"seen": [s for s in seen if "naver" in s or "opendart" in s]}))
"""
    assert _child(code, base, shadow) == {"seen": []}


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
    assert "'기업추적.lnk'" in s and "'기업추적 조회.lnk'" in s and "기업추적_조회.bat" in s
    assert ".TargetPath" in s and "-ieq $bat" in s                    # 이름이 아니라 가리키는 대상으로(검토 C1)
    assert r"'G:\내 드라이브\it''s'" in s                              # 작은따옴표는 두 번
    assert base64.b64decode(VR.encode_ps(s)).decode("utf-16-le") == s
    for ln in s.splitlines():                                        # 표준 출력은 ASCII 만(코드 페이지를 타지 않게)
        if "Write-Output" in ln:
            assert all(ord(c) < 128 for c in ln), ln


class _PS:
    def __init__(self, out):
        self.returncode, self.stdout, self.stderr = 0, out + "\r\n", ""


def test_ensure_shortcut_checks_target_not_name(VR, tmp_path, monkeypatch):
    monkeypatch.delenv("GIUP_NO_SHORTCUT", raising=False)
    calls, outs = [], []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        return _PS(outs.pop(0))
    here = tmp_path / "이미있음"
    here.mkdir()
    (here / "기업추적.lnk").write_bytes(b"L\0\0\0" + "기업추적_조회.bat".encode("utf-16-le") + b"\0\0")    # bat 을 가리킨다
    assert VR.ensure_shortcut(desktop=str(here), run=run) == "exists" and calls == []
    main = tmp_path / "메인뷰어"
    main.mkdir()
    (main / "기업추적.lnk").write_bytes(b"L\0\0\0" + "powershell.exe Start-ScheduledTask GiupChujeok_Viewer".encode("utf-16-le"))
    outs.append("made 1")                                            # PowerShell 이 TargetPath 를 보고 둘째 이름으로
    assert VR.ensure_shortcut(desktop=str(main), run=run) == "made 기업추적 조회.lnk"
    cmd, kw = calls[0]
    assert os.path.basename(cmd[0]).lower().startswith("powershell") and "-NoProfile" in cmd
    script = _decode(cmd)
    assert os.path.join(BASE, "기업추적_조회.bat") in script and "WScript.Shell" in script
    assert kw.get("timeout") and kw.get("creationflags") is not None
    empty = tmp_path / "빈바탕화면"
    empty.mkdir()
    outs.append("made 0")
    assert VR.ensure_shortcut(desktop=str(empty), run=run) == "made 기업추적.lnk"
    outs.append("taken")
    assert VR.ensure_shortcut(desktop=str(empty), run=run).startswith("failed")
    monkeypatch.setenv("GIUP_NO_SHORTCUT", "1")
    assert VR.ensure_shortcut(desktop=str(empty), run=run) == "skip" and len(calls) == 3


def _ps_exe():
    p = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return p if os.path.exists(p) else None


@pytest.mark.skipif(os.name != "nt" or _ps_exe() is None, reason="Windows PowerShell")
def test_shortcut_powershell_real_lnk_in_temp_desktop(VR, tmp_path):
    """진짜 PowerShell · WScript.Shell 로 — 바탕화면 자리만 tmp 로 바꿔서(이 PC 바탕화면은 건드리지 않는다).
    같은 이름의 '다른 것을 여는' 바로가기가 있으면 그대로 두고 둘째 이름으로 만들고, 다시 부르면 exists."""
    desk = tmp_path / "바탕화면"
    desk.mkdir()
    bat = os.path.join(BASE, "기업추적_조회.bat")
    other = os.path.join(BASE, "기업추적_뷰어.bat") if os.path.exists(os.path.join(BASE, "기업추적_뷰어.bat")) else _ps_exe()

    def ps(target):
        s = VR.shortcut_ps(target, BASE).replace("[Environment]::GetFolderPath('Desktop')", VR._ps_quote(str(desk)))
        assert str(desk) in s
        p = subprocess.run([_ps_exe(), "-NoProfile", "-NonInteractive", "-EncodedCommand", VR.encode_ps(s)],
                           capture_output=True, text=True, errors="replace", timeout=120)
        return p.returncode, (p.stdout or "").strip().splitlines()[-1:], p.stderr
    rc, out, err = ps(other)                                         # 먼저 '기업추적.lnk' = 다른 것(메인 뷰어 자리)
    assert rc == 0 and out == ["made 0"], (out, err)
    first = (desk / "기업추적.lnk").read_bytes()
    assert not VR.lnk_points_here(str(desk / "기업추적.lnk"), bat)
    rc, out, err = ps(bat)
    assert rc == 0 and out == ["made 1"], (out, err)
    assert (desk / "기업추적.lnk").read_bytes() == first             # 메인 뷰어 바로가기는 그대로
    assert VR.lnk_points_here(str(desk / "기업추적 조회.lnk"), bat)   # 빠른 확인이 진짜 .lnk 에서도 맞다
    rc, out, err = ps(bat)
    assert rc == 0 and out == ["exists"], (out, err)
    assert sorted(os.listdir(desk)) == ["기업추적 조회.lnk", "기업추적.lnk"]


def test_store_python_log_location(VR, tmp_path):
    """Microsoft Store 파이썬은 %LOCALAPPDATA% 쓰기를 Packages\\<계열>\\LocalCache\\Local 로 옮긴다(검토 C5) — 실제 위치를 찍는다."""
    sp = VR.store_package
    assert sp([r"C:\Users\u\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe"]) \
        == "PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0"
    assert sp([r"C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.13_3.13.3824.0_x64__qbz5n2kfra8p0"]) \
        == "PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0"
    assert sp([r"C:\Users\u\AppData\Local\Microsoft\WindowsApps\python.exe"]) is None
    assert sp([r"C:\Users\u\AppData\Local\Programs\Python\Python311-32\python.exe"]) is None
    la = tmp_path / "Local"
    log = la / "기업추적" / "조회전용" / "viewer_ro.log"
    pkg = "PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0"
    virt = la / "Packages" / pkg / "LocalCache" / "Local" / "기업추적" / "조회전용" / "viewer_ro.log"
    assert VR.real_path(str(log), str(la), pkg="") == str(log)                  # Store 파이썬이 아니면 그대로
    assert VR.real_path(str(log), str(la), pkg=pkg) == str(virt)               # 아직 없으면 가상화될 자리
    virt.parent.mkdir(parents=True)
    virt.write_text("x", encoding="utf-8")
    assert VR.real_path(str(log), str(la), pkg=pkg) == str(virt)
    assert VR.real_path(str(tmp_path / "밖.log"), str(la), pkg=pkg) == str(tmp_path / "밖.log")


def test_where_log_prints_path(tmp_path):
    (tmp_path / "x.log").write_text("", encoding="utf-8")            # 있는 파일 — Store 파이썬이어도 그 자리(가상화된 쪽은 없음)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", GIUP_RO_LOG=str(tmp_path / "x.log"))
    p = subprocess.run([sys.executable, "-X", "utf8", os.path.join(BASE, "viewer_readonly.py"), "--where-log"],
                       capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
    assert p.returncode == 0 and p.stdout.strip() == str(tmp_path / "x.log")


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

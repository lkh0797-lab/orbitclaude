# -*- coding: utf-8 -*-
"""조회 전용 모드(2026-10-15) — 같은 구글 드라이브를 받는 다른 PC 에서 기업추적 화면을 '보기만' 할 때.

viewer_readonly.py 가 서버 모듈을 읽기 **전에** enable(base=기업추적 폴더, shadow=%LOCALAPPDATA%\\기업추적\\조회전용\\shadow) 를 켠다.
그 뒤 이 프로세스는
  * 드라이브 파일을 하나도 바꾸지 않는다 — base 아래로 가는 쓰기를 shadow(드라이브 밖) 같은 상대 경로로 돌린다.
  * 바깥(DART · 네이버 · KIS · 관세청 · 텔레그램)을 부르지 않는다 — loopback 아닌 연결은 OSError(MSG_NET).
  * 다른 프로그램을 띄우지 않는다 — subprocess · os.system · os.startfile 은 OSError(MSG_PROC).
  * os.environ['GIUP_READONLY'] = '1' (재무._cache_ok 등이 '캐시가 있으면 그대로' 로 바뀐다), GIUP_RO_SHADOW = shadow 경로.
순수 표준 라이브러리. 한 프로세스에 한 번 켠다(disable() 은 시험용).

쓰기 돌리기
  builtins.open / io.open 의 w · a · x · + 모드, os.open 의 쓰기 플래그, os.replace · rename · remove · unlink · makedirs · mkdir ·
  rmdir · utime (+ truncate · chmod). 상대 경로는 cwd 기준으로 풀고 normcase 로 비교한다. base 밖 경로는 그대로.
  '\\\\?\\' · '\\\\.\\' · '\\\\?\\UNC\\' 접두는 벗기고 비교한다(같은 파일의 다른 표기로 base 를 지나치지 않게).
  패치 전에 원래 open 을 잡아 둔 모듈(bz2._builtin_open · tarfile.bltn_open)도 바꾼다.
  a · + 모드 · utime · truncate 는 base 파일을 shadow 로 먼저 복사한 뒤(copy-on-write) 고친다. base 쪽 지우기 · 옮기기는
  base 를 그대로 두고 '이번 실행에서는 없는 것'(_gone) 으로만 친다.
읽기
  이번 실행에서 shadow 에 쓴 것(_mine)은 shadow 에서, 나머지는 base 에서 — open 읽기 · os.stat · os.lstat
  (os.path.exists · isfile · isdir · getmtime · getsize 가 이 위에 선다).
  shadow 는 켤 때 비운다 — 지난 실행에서 쓴 것이 드라이브가 새로 받아 온 파일을 가리지 않게. 표시 파일(MARK)이 있는 폴더만 비운다.
감사 훅 백스톱(sys.addaudithook — 닫힌 쪽으로 실패)
  위 패치를 거치지 않는 길(io.FileIO · _io.open · os.link · os.symlink · sqlite3.connect · 3.12+ shutil.copy2 의 _winapi.CopyFile2 ·
  junction · subst · 심볼릭 링크로 base 를 가리키는 경로)이 base 를 바꾸려 하면 PermissionError(winerror 5 — copy2 는 이걸 보고
  패치된 copyfile 로 물러나 shadow 로 간다). C 수준 socket(_socket) 의 connect · sendto · sendmsg · DNS 와 프로세스 실행도 막는다.
  훅은 프로세스에서 지울 수 없어 disable() 뒤에는 아무것도 안 한다(_on 을 본다).
바깥 연결
  loopback 아닌 연결(create_connection · connect · connect_ex · sendto · sendmsg · asyncio sock_connect)과 DNS 질의
  (getaddrinfo · gethostbyname(_ex) · gethostbyaddr · getnameinfo — loopback 이름 · IP 리터럴만 통과, 나머지는 socket.gaierror)를 막는다.
  프록시 환경변수가 있어도 NO_PROXY=* 로 직접 연결하게 해서 막힌다.
못 하는 것(알려진 한계)
  os.listdir · os.scandir · glob 은 base 만 본다(이번 실행에서 새로 만든 파일은 목록에 안 나온다).
  C · C++ 확장이 파이썬 감사 이벤트 없이 직접 여는 파일(pyarrow 등)은 못 막는다 — 기업추적은 쓰지 않는다.
  importlib 의 pyc 쓰기는 os.open 패치를 거치지 않는다(nt 모듈 직접) — 그래서 sys.dont_write_bytecode=True 가 꼭 있어야 하고 여기서도 켠다
  (켜 두지 않아도 감사 훅이 막고 importlib 은 쓰기 실패를 넘긴다).
  _socket.socket.connect((이름, 포트)) 처럼 C 가 이름을 직접 푸는 길은 DNS 질의가 나간 뒤 연결에서 막힌다.
"""
import builtins
import errno
import io
import ipaddress
import os
import shutil
import socket
import stat as _st
import subprocess
import sys
import threading

MSG_NET = "조회 전용 — 바깥 호출 안 함"
MSG_PROC = "조회 전용 — 다른 프로그램을 띄우지 않음"
MSG_WRITE = "조회 전용 — 드라이브(기업추적 폴더)를 바꾸지 않음"
MARK = ".조회전용_shadow"           # shadow 폴더 표시 — 이게 있는 폴더만 켤 때 비운다

# 원래 함수 — 이 모듈을 읽을 때(패치 전) 잡아 둔다
_open = io.open
_oopen = os.open
_oreplace = os.replace
_orename = os.rename
_oremove = os.remove
_omkdir = os.mkdir
_ormdir = os.rmdir
_outime = os.utime
_ostat = os.stat
_olstat = os.lstat
_ochmod = os.chmod
_otruncate = getattr(os, "truncate", None)
_omakedirs = os.makedirs
_olistdir = os.listdir
_ocreate_connection = socket.create_connection
_osock_connect = socket.socket.connect
_osock_connect_ex = socket.socket.connect_ex
_osock_sendto = socket.socket.sendto
_osock_sendmsg = getattr(socket.socket, "sendmsg", None)
_ogetaddrinfo = socket.getaddrinfo
_ogethostbyname = socket.gethostbyname
_ogethostbyname_ex = socket.gethostbyname_ex
_ogethostbyaddr = socket.gethostbyaddr
_ogetnameinfo = socket.getnameinfo

_WFLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_MISSING = object()

_lock = threading.RLock()
_on = False
_hooked = False     # 감사 훅은 프로세스에 한 번만 건다(지울 수 없다)
_base = _base_nc = _shadow = _shadow_nc = None
_base_real_nc = None    # realpath(base) — junction · subst 로 base 를 가리키는 경로를 감사 훅이 알아본다
_mine = set()       # normcase 상대 경로 — 이번 실행에서 shadow 에 만든 파일 · 폴더
_gone = set()       # normcase 상대 경로 — 이번 실행에서 지운(것으로 친) base 파일 · 폴더
_patched = []       # (대상, 이름, 원래 값) — disable() 이 되돌린다


# ------------------------------------------------------------------ 경로
def _fs(p):
    """경로 인자 → str. fd(정수) 등 경로가 아닌 것은 None."""
    if isinstance(p, int):
        return None
    try:
        p = os.fspath(p)
    except TypeError:
        return None
    if isinstance(p, bytes):
        p = os.fsdecode(p)
    return p


def _plain(s):
    """Windows 긴 경로 · 장치 접두를 벗긴다: '\\\\?\\G:\\x' · '\\\\.\\G:\\x' → 'G:\\x', '\\\\?\\UNC\\서버\\공유' → '\\\\서버\\공유'.
    os.path.abspath 는 접두를 그대로 둬서, 그대로 비교하면 같은 base 파일이 base 밖으로 보인다(2026-10-15 검토 RO-4).
    드라이브 문자가 아닌 장치 이름('\\\\.\\pipe\\…' · '\\\\?\\Volume{…}\\…')은 그대로 — 감사 훅이 realpath 로 다시 본다."""
    if os.name != "nt" or len(s) < 6 or s[0] not in "\\/" or s[1] not in "\\/":
        return s
    t = s.replace("/", "\\")
    if t[2] not in "?." or t[3] != "\\":
        return s
    if t[4:8].upper() == "UNC\\":
        return "\\\\" + t[8:]
    if t[4].isalpha() and t[5] == ":":
        return t[4:]
    return s


def _rel(p):
    """base 아래면 base 기준 상대 경로('' = base 자신), 아니면 None."""
    if not _on:
        return None
    s = _fs(p)
    if s is None or s == "":
        return None
    a = os.path.abspath(_plain(s))
    n = os.path.normcase(a)
    if n == _base_nc:
        return ""
    if n.startswith(_base_nc + os.sep):
        if len(n) == len(a):
            return a[len(_base_nc) + 1:]
        return os.path.relpath(a, _base)
    return None


def _key(rel):
    return os.path.normcase(rel)


def _sh(rel):
    return os.path.join(_shadow, rel) if rel else _shadow


def _bp(rel):
    return os.path.join(_base, rel) if rel else _base


def _err(code, path):
    cls = {errno.ENOENT: FileNotFoundError, errno.EEXIST: FileExistsError}.get(code, OSError)
    return cls(code, os.strerror(code), path)


def _is_gone(key):
    if not _gone:
        return False
    k = key
    while k:
        if k in _gone:
            return True
        k = os.path.dirname(k)
    return False


def _real_mode(path):
    try:
        return _ostat(path).st_mode
    except (OSError, ValueError):
        return None


def _base_mode(rel):
    return _real_mode(_bp(rel))


def _vmode(rel):
    """이번 실행에서 보이는 그 경로의 st_mode(없으면 None)."""
    k = _key(rel)
    if k in _mine:
        return _real_mode(_sh(rel))
    if _is_gone(k):
        return None
    return _base_mode(rel)


def _visdir(rel):
    m = _vmode(rel)
    return m is not None and _st.S_ISDIR(m)


def _mk_shadow_dirs(path):
    """shadow 쪽 폴더를 만든다(원래 함수만 — 패치를 다시 타지 않게)."""
    todo = []
    p = path
    while p and _real_mode(p) is None:
        todo.append(p)
        q = os.path.dirname(p)
        if q == p:
            break
        p = q
    for p in reversed(todo):
        try:
            _omkdir(p)
        except FileExistsError:
            pass


def _need_parent(rel, orig):
    """쓰기 전에 — 부모 폴더가 (이번 실행에서 보기에) 있어야 한다. 있으면 shadow 쪽에도 만든다."""
    par = os.path.dirname(rel)
    if not _visdir(par):
        raise _err(errno.ENOENT, orig)
    _mk_shadow_dirs(_sh(par))


def _drop_stale(path):
    """내 것(_mine)이 아닌 shadow 파일(켤 때 못 지운 지난 실행 것)을 치운다."""
    m = _real_mode(path)
    if m is not None and not _st.S_ISDIR(m):
        try:
            _oremove(path)
        except OSError:
            pass


def _copy(src, dst):
    with _open(src, "rb") as a, _open(dst, "wb") as b:
        shutil.copyfileobj(a, b, 1 << 20)
    st = _ostat(src)
    _outime(dst, ns=(st.st_atime_ns, st.st_mtime_ns))


def _cow(rel):
    """base 파일을 shadow 로 복사해 둔다(아직 내 것이 아니고 base 에 파일이 있을 때)."""
    k = _key(rel)
    if k in _mine:
        return
    dst = _sh(rel)
    m = None if _is_gone(k) else _base_mode(rel)
    if m is not None and _st.S_ISREG(m):
        _copy(_bp(rel), dst)
    else:
        _drop_stale(dst)


def _claim(rel):
    k = _key(rel)
    _mine.add(k)
    _gone.discard(k)


def _forget(rel, base_had):
    k = _key(rel)
    _mine.discard(k)
    pre = k + os.sep
    for x in [x for x in _mine if x.startswith(pre)]:
        _mine.discard(x)
    if base_had:
        _gone.add(k)


def _rekey(src_rel, dst_rel):
    """폴더를 옮겼을 때 그 아래 내 것들의 열쇠를 바꾼다."""
    ks, kd = _key(src_rel), _key(dst_rel)
    pre = ks + os.sep
    for x in [x for x in _mine if x.startswith(pre)]:
        _mine.discard(x)
        _mine.add(kd + x[len(ks):])


def _prep_write(rel, orig, excl, trunc):
    """쓰기용 실제 경로(shadow)를 준비한다. 호출하는 쪽이 연 뒤 _claim 한다(_lock 안에서)."""
    if excl and _vmode(rel) is not None:
        raise _err(errno.EEXIST, orig)
    _need_parent(rel, orig)
    if _key(rel) not in _mine:
        if excl or trunc:
            _drop_stale(_sh(rel))
        else:
            _cow(rel)
    return _sh(rel)


def _read_target(rel, orig):
    k = _key(rel)
    if k in _mine:
        return _sh(rel)
    if _is_gone(k):
        raise _err(errno.ENOENT, orig)
    return orig


# ------------------------------------------------------------------ 파일 함수 바꿔치기
def _p_open(file, mode="r", *args, **kwargs):
    rel = _rel(file)
    if rel is None:
        return _open(file, mode, *args, **kwargs)
    if not any(c in mode for c in "wax+"):
        return _open(_read_target(rel, file), mode, *args, **kwargs)
    with _lock:
        target = _prep_write(rel, file, "x" in mode, "w" in mode)
        fh = _open(target, mode, *args, **kwargs)
        _claim(rel)
        return fh


def _p_os_open(path, flags, mode=0o777, *, dir_fd=None):
    rel = _rel(path) if dir_fd is None else None
    if rel is None:
        return _oopen(path, flags, mode, dir_fd=dir_fd)
    if not flags & _WFLAGS:
        return _oopen(_read_target(rel, path), flags, mode)
    with _lock:
        excl = bool(flags & os.O_EXCL) and bool(flags & os.O_CREAT)
        target = _prep_write(rel, path, excl, bool(flags & os.O_TRUNC))
        fd = _oopen(target, flags, mode)
        _claim(rel)
        return fd


def _move(src, dst, overwrite, orig_fn, kw):
    if any(v is not None for v in kw.values()):
        return orig_fn(src, dst, **kw)
    rs, rd = _rel(src), _rel(dst)
    if rs is None and rd is None:
        return orig_fn(src, dst)
    with _lock:
        # 옮길 것의 실제 위치
        if rs is None:
            real_src, from_base, base_had = src, False, False
        else:
            ks = _key(rs)
            bm = None if _is_gone(ks) else _base_mode(rs)
            base_had = bm is not None
            if ks in _mine:
                real_src, from_base = _sh(rs), False
            elif base_had:
                real_src, from_base = _bp(rs), True
                if _st.S_ISDIR(bm):
                    raise PermissionError(errno.EACCES, "조회 전용 — 드라이브 폴더는 옮기지 않음", src)
            else:
                raise _err(errno.ENOENT, src)
        # 갈 곳
        if rd is None:
            if not overwrite and _real_mode(dst) is not None:
                raise _err(errno.EEXIST, dst)
            real_dst = dst
        else:
            if not overwrite and _vmode(rd) is not None:
                raise _err(errno.EEXIST, dst)
            _need_parent(rd, dst)
            real_dst = _sh(rd)
            if _key(rd) not in _mine:
                _drop_stale(real_dst)
        # 옮기기 — base 는 건드리지 않는다(복사만 하고 base 쪽은 지운 것으로 친다)
        if from_base:
            _copy(real_src, real_dst)
        else:
            try:
                _oreplace(real_src, real_dst)
            except OSError as e:
                if getattr(e, "winerror", None) != 17 and e.errno != errno.EXDEV:
                    raise
                _copy(real_src, real_dst)       # 다른 드라이브 — 파일만
                _oremove(real_src)
        if rs is not None and rd is not None:
            _rekey(rs, rd)
        if rs is not None:
            _forget(rs, base_had)
        if rd is not None:
            _claim(rd)


def _p_replace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
    return _move(src, dst, True, _oreplace, {"src_dir_fd": src_dir_fd, "dst_dir_fd": dst_dir_fd})


def _p_rename(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
    return _move(src, dst, False, _orename, {"src_dir_fd": src_dir_fd, "dst_dir_fd": dst_dir_fd})


def _p_remove(path, *, dir_fd=None):
    rel = _rel(path) if dir_fd is None else None
    if rel is None:
        return _oremove(path, dir_fd=dir_fd)
    with _lock:
        k = _key(rel)
        bm = None if _is_gone(k) else _base_mode(rel)
        if k in _mine:
            _oremove(_sh(rel))
        elif bm is None:
            raise _err(errno.ENOENT, path)
        elif _st.S_ISDIR(bm):
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), path)
        _forget(rel, bm is not None)


def _p_rmdir(path, *, dir_fd=None):
    rel = _rel(path) if dir_fd is None else None
    if rel is None:
        return _ormdir(path, dir_fd=dir_fd)
    with _lock:
        k = _key(rel)
        bm = None if _is_gone(k) else _base_mode(rel)
        if bm is not None and _st.S_ISDIR(bm):
            pre = k + os.sep
            left = [n for n in _olistdir(_bp(rel)) if not _is_gone(_key(os.path.join(rel, n)))]
            if left or any(x.startswith(pre) for x in _mine):
                raise OSError(errno.ENOTEMPTY, os.strerror(errno.ENOTEMPTY), path)
        if k in _mine:
            _ormdir(_sh(rel))
        elif bm is None:
            raise _err(errno.ENOENT, path)
        elif not _st.S_ISDIR(bm):
            raise NotADirectoryError(errno.ENOTDIR, os.strerror(errno.ENOTDIR), path)
        _forget(rel, bm is not None)


def _p_makedirs(name, mode=0o777, exist_ok=False):
    rel = _rel(name)
    if rel is None:
        return _omakedirs(name, mode, exist_ok)
    with _lock:
        m = _vmode(rel)
        if m is not None:
            if exist_ok and _st.S_ISDIR(m):
                return
            raise _err(errno.EEXIST, name)
        todo, r = [], rel
        while r and _vmode(r) is None:
            todo.append(r)
            r = os.path.dirname(r)
        if not _visdir(r):
            raise _err(errno.ENOENT, name)
        _mk_shadow_dirs(_sh(rel))
        for r in todo:
            _claim(r)


def _p_mkdir(path, mode=0o777, *, dir_fd=None):
    rel = _rel(path) if dir_fd is None else None
    if rel is None:
        return _omkdir(path, mode, dir_fd=dir_fd)
    with _lock:
        if _vmode(rel) is not None:
            raise _err(errno.EEXIST, path)
        _need_parent(rel, path)
        try:
            _omkdir(_sh(rel), mode)
        except FileExistsError:                 # 지난 실행이 남긴 빈 폴더
            if not _visdir_real(_sh(rel)):
                raise
        _claim(rel)


def _visdir_real(p):
    m = _real_mode(p)
    return m is not None and _st.S_ISDIR(m)


def _own_file(rel, path):
    """utime · truncate 처럼 파일을 고치는 일 — 내 것이 아니면 base 를 shadow 로 복사해 온다. 폴더면 None."""
    k = _key(rel)
    if k not in _mine:
        bm = None if _is_gone(k) else _base_mode(rel)
        if bm is None:
            raise _err(errno.ENOENT, path)
        if _st.S_ISDIR(bm):
            return None
        _need_parent(rel, path)
        _copy(_bp(rel), _sh(rel))
        _claim(rel)
    return _sh(rel)


def _p_utime(path, *args, **kwargs):
    rel = _rel(path) if kwargs.get("dir_fd") is None else None
    if rel is None:
        return _outime(path, *args, **kwargs)
    with _lock:
        target = _own_file(rel, path)
        if target is None:                      # 드라이브 폴더 시각은 바꾸지 않는다(조용히 넘김)
            return None
        return _outime(target, *args, **kwargs)


def _p_truncate(path, length):
    rel = _rel(path)
    if rel is None:
        return _otruncate(path, length)
    with _lock:
        target = _own_file(rel, path)
        if target is None:
            raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), path)
        return _otruncate(target, length)


def _p_chmod(path, mode, *, dir_fd=None, follow_symlinks=True):
    rel = _rel(path) if dir_fd is None else None
    if rel is None:
        return _ochmod(path, mode, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
    k = _key(rel)
    if k in _mine:
        return _ochmod(_sh(rel), mode, follow_symlinks=follow_symlinks)
    if _is_gone(k) or _base_mode(rel) is None:
        raise _err(errno.ENOENT, path)
    return None                                 # 드라이브 파일 속성은 바꾸지 않는다


def _stat_target(path, dir_fd):
    if dir_fd is not None or (not _mine and not _gone):
        return path
    rel = _rel(path)
    if rel is None:
        return path
    k = _key(rel)
    if k in _mine:
        return _sh(rel)
    if _is_gone(k):
        raise _err(errno.ENOENT, path)
    return path


def _p_stat(path, *, dir_fd=None, follow_symlinks=True):
    return _ostat(_stat_target(path, dir_fd), dir_fd=dir_fd, follow_symlinks=follow_symlinks)


def _p_lstat(path, *, dir_fd=None):
    return _olstat(_stat_target(path, dir_fd), dir_fd=dir_fd)


def _wrap_pathq(orig):
    """파이썬 3.12+ 의 os.path.exists · isfile · isdir 는 nt 의 C 함수라 os.stat 패치를 안 거친다 — 그때만 감싼다."""
    def f(path):
        try:
            p = _stat_target(path, None)
        except FileNotFoundError:
            return False
        return orig(p)
    f.__name__ = getattr(orig, "__name__", "pathq")
    f.__doc__ = getattr(orig, "__doc__", None)
    return f


# ------------------------------------------------------------------ 바깥 연결 · 프로그램 실행
def _loopback(host):
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    h = host.strip().lower()
    if h in ("localhost", "localhost."):
        return True
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    h = h.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    m = getattr(ip, "ipv4_mapped", None)
    return bool(m is not None and m.is_loopback)


def _addr_ok(address):
    if isinstance(address, (tuple, list)):
        return bool(address) and _loopback(address[0])
    return isinstance(address, (str, bytes))    # AF_UNIX 경로 — 이 PC 안


def _name_ok(host):
    """DNS 를 묻지 않고 풀리는 이름인가 — None · ''(이 PC) · localhost · IP 리터럴(바깥 IP 여도 연결에서 막힌다)."""
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    h = host.strip().lower()
    if h in ("", "localhost", "localhost."):
        return True
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    try:
        ipaddress.ip_address(h.split("%", 1)[0])
        return True
    except ValueError:
        return False


def _gai_denied():
    return socket.gaierror(getattr(socket, "EAI_NONAME", 8), MSG_NET)


def _p_getaddrinfo(host, port, *args, **kwargs):
    if not _name_ok(host):
        raise _gai_denied()
    return _ogetaddrinfo(host, port, *args, **kwargs)


def _p_gethostbyname(hostname):
    if not _name_ok(hostname):
        raise _gai_denied()
    return _ogethostbyname(hostname)


def _p_gethostbyname_ex(hostname):
    if not _name_ok(hostname):
        raise _gai_denied()
    return _ogethostbyname_ex(hostname)


def _p_gethostbyaddr(ip_address):
    if not _loopback(ip_address):                # 거꾸로 찾기(PTR)도 DNS 질의 — loopback 만
        raise _gai_denied()
    return _ogethostbyaddr(ip_address)


def _p_getnameinfo(sockaddr, flags):
    # 감사 이벤트(socket.getnameinfo)에는 flags 가 없어 NI_NUMERICHOST 여부를 모른다 — 둘 다 loopback 만(같은 규칙)
    if not (isinstance(sockaddr, (tuple, list)) and sockaddr and _loopback(sockaddr[0])):
        raise _gai_denied()
    return _ogetnameinfo(sockaddr, flags)


def _p_sendto(self, data, *args):
    """sendto(data, address) · sendto(data, flags, address) — UDP 는 connect 없이 바로 나간다(검토 RO-5)."""
    if args and not _addr_ok(args[-1]):
        raise OSError(MSG_NET)
    return _osock_sendto(self, data, *args)


def _p_sendmsg(self, buffers, *args):
    """sendmsg(buffers[, ancdata[, flags[, address]]]) — 주소가 있으면(연결 없이 보냄) loopback 만."""
    if len(args) >= 3 and args[2] is not None and not _addr_ok(args[2]):
        raise OSError(MSG_NET)
    return _osock_sendmsg(self, buffers, *args)


def _p_create_connection(address, *args, **kwargs):
    if not _addr_ok(address):
        raise OSError(MSG_NET)
    return _ocreate_connection(address, *args, **kwargs)


def _p_connect(self, address):
    if not _addr_ok(address):
        raise OSError(MSG_NET)
    return _osock_connect(self, address)


def _p_connect_ex(self, address):
    if not _addr_ok(address):
        raise OSError(MSG_NET)
    return _osock_connect_ex(self, address)


def _wrap_sock_connect(orig):
    async def sock_connect(self, sock, address):
        if not _addr_ok(address):
            raise OSError(MSG_NET)
        return await orig(self, sock, address)
    return sock_connect


def _no_proc(*args, **kwargs):
    raise OSError(MSG_PROC)


def _no_popen(self, *args, **kwargs):
    raise OSError(MSG_PROC)


# ------------------------------------------------------------------ 감사 훅 백스톱(2026-10-15 검토 RO-3 · RO-4 · RO-5)
# 위 패치는 파이썬 이름을 바꿔 치는 것이라, 패치 전에 잡아 둔 함수나 C 수준 길(io.FileIO · _io.open · os.link · sqlite3 ·
# _winapi.CopyFile2 · _socket)은 지나친다. 감사 이벤트는 그 길도 다 지나가므로 여기서 마지막으로 막는다 — 닫힌 쪽으로.
# 패치가 이미 shadow 로 돌린 호출은 실제 경로가 shadow 라 그냥 지나간다. 이벤트 이름 · 인자는 파이썬 감사 이벤트 표(3.8+) 그대로.
_tl = threading.local()
_HOOK_PATHS = {                     # 이벤트 → 경로 인자 자리
    "os.rename": (0, 1), "os.remove": (0,), "os.rmdir": (0,), "os.mkdir": (0,), "os.link": (0, 1),
    "os.symlink": (0, 1), "os.truncate": (0,), "os.utime": (0,), "os.chmod": (0,), "os.chown": (0,),
    "os.chflags": (0,), "os.setxattr": (0,), "os.removexattr": (0,), "os.mkfifo": (0,), "os.mknod": (0,),
    "_winapi.CopyFile2": (1,),
}
_HOOK_NET = {"socket.connect", "socket.sendto", "socket.sendmsg"}
_HOOK_DNS = {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo"}
_HOOK_PROC = {"subprocess.Popen", "os.system", "os.startfile", "os.spawn", "os.exec", "os.posix_spawn",
              "os.fork", "os.forkpty", "_winapi.CreateProcess", "pty.spawn"}


def _within(n, root):
    return bool(root) and (n == root or n.startswith(root + os.sep))


def _hits_base(p):
    """감사 훅 — 이 경로를 바꾸면 base(드라이브)가 바뀌나. 접두 · junction · subst · 심볼릭 링크도 본다. 확인 못 하면 True(닫힌 쪽)."""
    s = _fs(p)
    if s is None or s == "":
        return False                            # fd — 이미 연 파일(열 때 검사했다)
    try:
        n = os.path.normcase(os.path.abspath(_plain(s)))
        if _within(n, _shadow_nc):
            return False
        if _within(n, _base_nc):
            return True
        r = os.path.normcase(_plain(os.path.realpath(s)))
        return _within(r, _base_real_nc) or _within(r, _base_nc)
    except Exception:
        return True


def _deny_write(p):
    s = _fs(p)
    return PermissionError(errno.EACCES, MSG_WRITE, s if s is not None else str(p), 5)   # winerror 5 = ERROR_ACCESS_DENIED


def _sqlite_target(db):
    """sqlite3.connect 의 database → 바꿀 수 있는 파일 경로 | None(메모리 · 읽기 전용 URI)."""
    s = _fs(db)
    if s is None or s in ("", ":memory:"):
        return None
    if s.startswith("file:"):
        path, _, q = s[5:].partition("?")
        if "mode=ro" in q or "immutable=1" in q or path in ("", ":memory:") or "mode=memory" in q:
            return None
        return path
    return s


def _audit(event, args):
    if not _on:
        return
    if not (event in _HOOK_PATHS or event == "open" or event == "sqlite3.connect"
            or event in _HOOK_NET or event in _HOOK_DNS or event in _HOOK_PROC):
        return
    if getattr(_tl, "busy", False):             # 훅 안에서 부른 것(realpath 등)은 다시 보지 않는다
        return
    _tl.busy = True
    try:
        if event == "open":                     # (path, mode, flags) — io.FileIO · _io.open · os.open 모두
            fl = args[2] if len(args) > 2 else 0
            if isinstance(fl, int) and fl & _WFLAGS and _hits_base(args[0]):
                raise _deny_write(args[0])
        elif event in _HOOK_PATHS:
            for i in _HOOK_PATHS[event]:
                if i < len(args) and _hits_base(args[i]):
                    raise _deny_write(args[i])
        elif event == "sqlite3.connect":
            t = _sqlite_target(args[0] if args else None)
            if t is not None and _hits_base(t):
                raise _deny_write(t)
        elif event in _HOOK_NET:                # (socket, address) — address None = 이미 연결된 소켓
            a = args[1] if len(args) > 1 else None
            if a is not None and not _addr_ok(a):
                raise OSError(MSG_NET)
        elif event in _HOOK_DNS:
            a = args[0] if args else None
            if event == "socket.getaddrinfo" or event == "socket.gethostbyname":
                ok = _name_ok(a)
            elif event == "socket.getnameinfo":
                ok = isinstance(a, (tuple, list)) and bool(a) and _loopback(a[0])
            else:
                ok = _loopback(a)
            if not ok:
                raise _gai_denied()
        else:
            raise OSError(MSG_PROC)
    finally:
        _tl.busy = False


# ------------------------------------------------------------------ 켜기 · 끄기
def _set(obj, name, new):
    if isinstance(obj, type):
        orig = obj.__dict__.get(name, _MISSING)
    else:
        orig = getattr(obj, name, _MISSING)
    _patched.append((obj, name, orig))
    setattr(obj, name, new)


def _prepare_shadow(shadow, fresh):
    """shadow 를 비우고(표시 파일이 있을 때만) 표시 파일을 둔다. 패치 전에 부른다."""
    mark = os.path.join(shadow, MARK)
    if os.path.isdir(shadow):
        if os.path.exists(mark):
            if fresh:
                for n in os.listdir(shadow):
                    if n == MARK:
                        continue
                    p = os.path.join(shadow, n)
                    if os.path.isdir(p) and not os.path.islink(p):
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        try:
                            os.remove(p)
                        except OSError:
                            pass
        elif os.listdir(shadow):
            raise ValueError("shadow 폴더에 조회 전용 표시 없이 다른 파일이 있어 쓰지 않는다: %s" % shadow)
    os.makedirs(shadow, exist_ok=True)
    with open(mark, "w", encoding="utf-8") as fh:
        fh.write("기업추적 조회 전용 그림자 폴더 — 드라이브(base)로 가던 쓰기가 여기로 온다. 켤 때마다 비운다.\n")


def enable(base, shadow, fresh=True):
    """조회 전용을 켠다. base: 기업추적 폴더(드라이브), shadow: 드라이브 밖 폴더(쓰기가 여기로).
    fresh=True 면 shadow 를 비우고 시작한다. 두 폴더가 겹치면 ValueError."""
    global _on, _hooked, _base, _base_nc, _shadow, _shadow_nc, _base_real_nc
    b = os.path.abspath(_plain(_fs(base)))
    s = os.path.abspath(_plain(_fs(shadow)))
    nb = os.path.normcase(b).rstrip(os.sep)
    ns = os.path.normcase(s).rstrip(os.sep)
    with _lock:
        if _on:
            if (nb, ns) == (_base_nc, _shadow_nc):
                return
            raise RuntimeError("조회 전용이 이미 다른 폴더로 켜져 있다")
        if not os.path.isdir(b):
            raise ValueError("base 폴더가 없다: %s" % b)

        def _real(p):
            try:
                return os.path.normcase(_plain(os.path.realpath(p))).rstrip(os.sep)
            except (OSError, ValueError):
                return os.path.normcase(p).rstrip(os.sep)
        rb, rs = _real(b), _real(s)
        for x, y in ((nb, ns), (rb, rs), (nb, rs), (rb, ns)):     # junction · subst 로 겹쳐도 안 된다
            if y == x or y.startswith(x + os.sep) or x.startswith(y + os.sep):
                raise ValueError("shadow 는 base 밖, base 는 shadow 밖이어야 한다: base=%s shadow=%s" % (b, s))
        sys.dont_write_bytecode = True          # importlib 의 pyc 쓰기는 아래 패치를 안 거친다
        _prepare_shadow(s, fresh)
        _base, _base_nc, _shadow, _shadow_nc, _base_real_nc = b, nb, s, ns, rb
        _mine.clear()
        _gone.clear()
        _on = True
        if not _hooked:                         # 백스톱 — 지울 수 없으니 한 번만, 꺼지면(_on False) 아무것도 안 한다
            sys.addaudithook(_audit)
            _hooked = True

        _set(builtins, "open", _p_open)
        _set(io, "open", _p_open)
        _set(os, "open", _p_os_open)
        _set(os, "replace", _p_replace)
        _set(os, "rename", _p_rename)
        _set(os, "remove", _p_remove)
        _set(os, "unlink", _p_remove)
        _set(os, "makedirs", _p_makedirs)
        _set(os, "mkdir", _p_mkdir)
        _set(os, "rmdir", _p_rmdir)
        _set(os, "utime", _p_utime)
        _set(os, "stat", _p_stat)
        _set(os, "lstat", _p_lstat)
        _set(os, "chmod", _p_chmod)
        if _otruncate is not None:
            _set(os, "truncate", _p_truncate)
        for n in ("exists", "isfile", "isdir"):
            f = getattr(os.path, n)
            if getattr(f, "__module__", "") != "genericpath":
                _set(os.path, n, _wrap_pathq(f))
        # 이 모듈보다 먼저 읽혀 원래 open 을 잡아 둔 표준 모듈 — shutil 이 bz2 를 읽는다(검토 RO-3)
        for mod, name in (("bz2", "_builtin_open"), ("tarfile", "bltn_open")):
            m = sys.modules.get(mod)
            if m is not None and hasattr(m, name):
                _set(m, name, _p_open)

        _set(socket, "create_connection", _p_create_connection)
        _set(socket.socket, "connect", _p_connect)
        _set(socket.socket, "connect_ex", _p_connect_ex)
        _set(socket.socket, "sendto", _p_sendto)
        if _osock_sendmsg is not None:
            _set(socket.socket, "sendmsg", _p_sendmsg)
        _set(socket, "getaddrinfo", _p_getaddrinfo)          # DNS 질의도 바깥 호출(검토 RO-2) — requests · urllib3 · asyncio 가 이걸 부른다
        _set(socket, "gethostbyname", _p_gethostbyname)
        _set(socket, "gethostbyname_ex", _p_gethostbyname_ex)
        _set(socket, "gethostbyaddr", _p_gethostbyaddr)
        _set(socket, "getnameinfo", _p_getnameinfo)
        try:
            import asyncio.selector_events as _ase
            import asyncio.proactor_events as _ape
            for cls in (_ase.BaseSelectorEventLoop, _ape.BaseProactorEventLoop):
                _set(cls, "sock_connect", _wrap_sock_connect(cls.sock_connect))
        except Exception:                       # asyncio 를 못 읽어도 socket.connect 패치는 남는다
            pass

        _set(subprocess.Popen, "__init__", _no_popen)
        for n in ("system", "startfile", "popen", "spawnv", "spawnve", "spawnvp", "spawnvpe",
                  "execv", "execve", "posix_spawn", "posix_spawnp", "fork", "forkpty"):
            if hasattr(os, n):
                _set(os, n, _no_proc)
        try:
            import _winapi
            _set(_winapi, "CreateProcess", _no_proc)
        except ImportError:
            pass

        os.environ["GIUP_READONLY"] = "1"
        os.environ["GIUP_RO_SHADOW"] = s
        for n in ("NO_PROXY", "no_proxy"):     # 프록시(loopback 이어도)를 거쳐 바깥으로 나가지 않게 — 직접 연결은 위에서 막힌다
            os.environ[n] = "*"


def disable():
    """시험용 — 바꿔 친 것을 되돌린다. 환경변수 GIUP_READONLY 는 지운다."""
    global _on
    with _lock:
        while _patched:
            obj, name, orig = _patched.pop()
            if orig is _MISSING:
                try:
                    delattr(obj, name)
                except AttributeError:
                    pass
            else:
                setattr(obj, name, orig)
        _on = False
        _mine.clear()
        _gone.clear()
        os.environ.pop("GIUP_READONLY", None)
        os.environ.pop("GIUP_RO_SHADOW", None)


def is_on():
    return _on


def state():
    """/api/mode 등에 — 켜졌나 · 폴더 · 이번 실행에서 shadow 로 돌린 수 · 감사 훅."""
    return {"readonly": _on, "base": _base, "shadow": _shadow, "written": len(_mine), "hidden": len(_gone),
            "audit_hook": _hooked and _on}

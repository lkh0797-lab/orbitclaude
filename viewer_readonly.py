# -*- coding: utf-8 -*-
"""ASCII-named launcher for the READ-ONLY viewer (another PC on the same Google Drive).
cmd.exe garbles non-ASCII text inside .bat files, so 기업추적_조회.bat calls this file.

조회 전용(2026-10-15) — 이 PC 가 아닌 다른 PC 에서 기업추적 화면을 '보기만' 한다:
  1) 바탕화면에 기업추적_조회.bat 을 가리키는 바로가기가 없으면 만든다 — 이름은 '기업추적.lnk', 그 이름이 이미 다른 것
     (메인 뷰어 바로가기 등)을 가리키면 '기업추적 조회.lnk'. 이름이 아니라 가리키는 대상(TargetPath)으로 '있다'를 가린다.
     다른 프로그램(powershell)을 부르는 일이라 조회 전용을 켜기 **전에** 한다. --no-shortcut(또는 GIUP_NO_SHORTCUT=1)이면
     건너뛴다(메인 PC 에서 확인할 때). --make-shortcut 이면 바로가기만 만들고 끝낸다(서버 안 띄움).
  2) 조회전용.enable(base=이 폴더, shadow=%LOCALAPPDATA%\\기업추적\\조회전용\\shadow) — 서버 모듈을 읽기 전에.
     드라이브 쪽 쓰기는 shadow 로, 바깥 연결 · 다른 프로그램 실행은 막힌다.
  3) runpy 로 서버.py 를 --readonly --no-auto --no-browser --port 8770(기본) 으로 부른다. 브라우저는 bat 이 연다.
로그: pythonw(콘솔 없음)일 때 %LOCALAPPDATA%\\기업추적\\조회전용\\viewer_ro.log (드라이브 밖). GIUP_RO_LOG 로 바꿀 수 있다.
  Microsoft Store 파이썬은 %LOCALAPPDATA% 쓰기를 %LOCALAPPDATA%\\Packages\\<패키지>\\LocalCache\\Local\\… 로 옮긴다(가상화) —
  --where-log 가 실제 위치를 찍는다(bat 이 실패 안내에 쓴다).
"""
import sys

sys.dont_write_bytecode = True      # 아래 import 부터 — 이 폴더(드라이브)에 __pycache__ 를 쓰지 않게

import base64                       # noqa: E402
import io                           # noqa: E402
import os                           # noqa: E402
import runpy                        # noqa: E402
import subprocess                   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import 조회전용 as RO               # noqa: E402

TARGET = os.path.join(HERE, "서버.py")
BAT = os.path.join(HERE, "기업추적_조회.bat")
LNK_NAME = "기업추적.lnk"
LNK_ALT = "기업추적 조회.lnk"     # '기업추적.lnk' 가 이미 다른 것(메인 뷰어 · 예전 메인 PC 에서 따라온 것)을 가리킬 때
DEFAULT_PORT = "8770"
LOCAL = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "기업추적", "조회전용")
OWN_FLAGS = ("--no-shortcut", "--make-shortcut", "--where-log")


# ------------------------------------------------------------------ 로그 위치(Store 파이썬 가상화)
def store_package(paths=None):
    """Microsoft Store 파이썬이면 패키지 계열 이름(PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0), 아니면 None.
    sys.executable(…\\WindowsApps\\<계열 이름>\\python.exe) 이나 sys.prefix(…\\WindowsApps\\<이름>_<판>_<아키>__<게시자>) 에서 읽는다."""
    for p in (paths if paths is not None else (sys.executable, sys.prefix, sys.base_prefix)):
        parts = os.path.normpath(p or "").split(os.sep)
        for i, seg in enumerate(parts[:-1]):
            if seg.lower() != "windowsapps":
                continue
            pkg = parts[i + 1]
            if "__" in pkg:
                return pkg.split("_", 1)[0] + "_" + pkg.rsplit("__", 1)[1]
            if "_" in pkg and not pkg.lower().endswith(".exe"):
                return pkg
    return None


def real_path(path, local_appdata=None, pkg=None):
    """이 파이썬이 path 에 쓴 파일이 탐색기에서 실제로 있는 곳. Store 파이썬은 %LOCALAPPDATA% 아래 쓰기를
    %LOCALAPPDATA%\\Packages\\<계열>\\LocalCache\\Local\\… 로 옮긴다(2026-10-15 검토 C5 — 이 PC 3.13 에서 확인).
    둘 다 있으면(진짜 위치에 먼저 있던 파일은 제자리에서 고친다) 더 최근 것."""
    la = local_appdata or os.environ.get("LOCALAPPDATA") or ""
    pkg = pkg if pkg is not None else store_package()
    if not pkg or not la:
        return path
    a, nl = os.path.abspath(path), os.path.normcase(os.path.abspath(la))
    if not os.path.normcase(a).startswith(nl + os.sep):
        return path
    virt = os.path.join(la, "Packages", pkg, "LocalCache", "Local", a[len(nl) + 1:])
    have = [p for p in (virt, a) if os.path.exists(p)]
    if not have:
        return virt
    return max(have, key=lambda p: os.path.getmtime(p))


def log_path():
    return os.environ.get("GIUP_RO_LOG") or os.path.join(LOCAL, "viewer_ro.log")


# ------------------------------------------------------------------ 바탕화면 바로가기
def desktop_dir():
    """바탕화면 폴더(OneDrive 로 옮긴 바탕화면 포함) — [Environment]::GetFolderPath('Desktop') 와 같은 SHGetFolderPathW."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf) == 0 and buf.value:
            return buf.value
    except Exception:
        pass
    return None


def _ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def shortcut_ps(bat, workdir, names=(LNK_NAME, LNK_ALT)):
    """바탕화면에 bat 을 가리키는 바로가기가 없으면 만드는 PowerShell. 'exists' | 'made <이름>' | 'taken' 을 찍는다.
    이름만 보지 않는다(2026-10-15 검토 C1) — 같은 이름의 메인 뷰어 바로가기(예약 작업 GiupChujeok_Viewer + 8765)가 있으면
    그건 그대로 두고 다음 이름(LNK_ALT)으로 만든다. 1) 이름들 중 하나가 이미 bat 을 가리키면 exists 2) 아니면 비어 있는 첫 이름에 만든다.
    출력은 ASCII 만('made 1' = names[1]) — powershell 표준 출력의 코드 페이지를 타지 않게."""
    arr = "@(" + ", ".join(_ps_quote(n) for n in names) + ")"
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "$d = [Environment]::GetFolderPath('Desktop')",
        "if (-not $d) { Write-Output 'nodesktop'; exit 2 }",
        "$bat = [IO.Path]::GetFullPath(%s)" % _ps_quote(bat),
        "$w = New-Object -ComObject WScript.Shell",
        "$names = %s" % arr,
        "foreach ($n in $names) {",
        "  $p = Join-Path $d $n",
        "  if (Test-Path -LiteralPath $p) {",
        "    $t = $w.CreateShortcut($p).TargetPath",
        "    try { $t = [IO.Path]::GetFullPath($t) } catch { }",
        "    if ($t -and ($t -ieq $bat)) { Write-Output 'exists'; exit 0 }",
        "  }",
        "}",
        "for ($i = 0; $i -lt $names.Count; $i++) {",
        "  $p = Join-Path $d $names[$i]",
        "  if (Test-Path -LiteralPath $p) { continue }",
        "  $s = $w.CreateShortcut($p)",
        "  $s.TargetPath = $bat",
        "  $s.WorkingDirectory = %s" % _ps_quote(workdir),
        "  $s.Description = %s" % _ps_quote("기업추적 조회 전용 — 이 PC 는 보기만 합니다"),
        "  $s.Save()",
        "  Write-Output ('made ' + $i)",
        "  exit 0",
        "}",
        "Write-Output 'taken'",
        "exit 3",
    ])


def encode_ps(script):
    """powershell -EncodedCommand 용 — UTF-16LE 를 base64 로. 한글 경로가 cmd · 코드 페이지를 거치지 않는다."""
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _powershell():
    p = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return p if os.path.exists(p) else "powershell.exe"


def lnk_points_here(path, bat=BAT):
    """바로가기 파일이 bat 을 가리키는 것 같은가 — 빠른 확인(PowerShell 없이). .lnk 의 대상 경로는 셸 항목 목록(UTF-16)과
    LinkInfo(ANSI 코드 페이지)에 들어 있다. 파일 이름이 둘 중 하나에 있으면 True. 아니면 False — 그때는 PowerShell 이 TargetPath 로 다시 본다."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(1 << 16)
    except OSError:
        return False
    name = os.path.basename(bat)
    for enc in ("utf-16-le", "mbcs", "cp949"):
        try:
            if name.encode(enc) in data:
                return True
        except (LookupError, UnicodeError):
            continue
    return False


def ensure_shortcut(desktop=None, run=None):
    """바탕화면에 기업추적_조회.bat 바로가기가 없으면 만든다. 'skip' | 'exists' | 'made <이름>' | 'failed: ...' — 예외는 내지 않는다.
    '기업추적.lnk' 가 있어도 다른 것(메인 뷰어)을 가리키면 'exists' 가 아니다(검토 C1) — PowerShell 이 TargetPath 를 보고
    '기업추적 조회.lnk' 로 만든다. 조회 전용을 켜기 전에 불러야 한다(켠 뒤에는 powershell 실행이 막힌다)."""
    if os.environ.get("GIUP_NO_SHORTCUT") == "1":
        return "skip"
    try:
        d = desktop or desktop_dir()
        if d and any(lnk_points_here(os.path.join(d, n)) for n in (LNK_NAME, LNK_ALT)):
            return "exists"
        cmd = [_powershell(), "-NoProfile", "-NonInteractive", "-EncodedCommand", encode_ps(shortcut_ps(BAT, HERE))]
        p = (run or subprocess.run)(cmd, capture_output=True, text=True, errors="replace", timeout=60,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        lines = [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]
        out = lines[-1] if lines else ""
        if p.returncode == 0 and out == "exists":
            return out
        names = (LNK_NAME, LNK_ALT)
        if p.returncode == 0 and out.startswith("made ") and out[5:].isdigit() and int(out[5:]) < len(names):
            return "made " + names[int(out[5:])]
        return "failed: rc=%s %s %s" % (p.returncode, out, (p.stderr or "").strip()[:300])
    except Exception as e:
        return "failed: %s" % e


# ------------------------------------------------------------------ 서버 인자 · 로그
def server_args(argv):
    """서버.py 에 넘길 인자 — 이 실행기 것(--no-shortcut · --make-shortcut)은 빼고, 조회 전용 · 자동 루프 끔 · 브라우저 안 염을 붙인다."""
    out = [a for a in argv if a not in OWN_FLAGS]
    if "--port" not in out:
        out += ["--port", DEFAULT_PORT]
    for f in ("--readonly", "--no-auto", "--no-browser"):
        if f not in out:
            out.append(f)
    return out


def _attach_log():
    """pythonw(콘솔 없음)면 로그를 드라이브 밖 파일로. 조회 전용을 켜기 전에 연다."""
    if sys.stdout is not None and os.environ.get("GIUP_RO_LOG") is None:
        return
    path = log_path()
    if os.path.normcase(os.path.abspath(path)).startswith(os.path.normcase(HERE) + os.sep):
        path = os.path.join(LOCAL, "viewer_ro.log")     # 드라이브 안으로는 쓰지 않는다
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fh = open(path, "a", encoding="utf-8", buffering=1, errors="replace")
    sys.stdout = fh
    sys.stderr = fh
    if sys.stdin is None:
        sys.stdin = io.StringIO("")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--where-log" in argv:           # bat 의 실패 안내 — Store 파이썬이면 가상화된 실제 위치
        print("  " + real_path(log_path()), flush=True)
        sys.exit(0)
    if "--make-shortcut" in argv:
        print("desktop shortcut:", ensure_shortcut(), flush=True)
        sys.exit(0)
    _attach_log()
    if store_package():
        print("Microsoft Store 파이썬 — 이 로그 · shadow 는 탐색기에서 %s 아래에 있다"
              % real_path(LOCAL), flush=True)
    if "--no-shortcut" in argv:
        print("바탕화면 바로가기: 건너뜀(--no-shortcut)", flush=True)
    else:
        print("바탕화면 바로가기:", ensure_shortcut(), flush=True)
    if not os.path.exists(TARGET):
        print("server script not found:", TARGET, flush=True)
        sys.exit(1)
    shadow = os.path.join(LOCAL, "shadow")
    RO.enable(base=HERE, shadow=shadow)
    print("조회 전용 — 드라이브 쓰기는 %s 로, 바깥 연결 · 다른 프로그램 실행은 막음" % shadow, flush=True)
    sys.argv = [TARGET] + server_args(argv)
    runpy.run_path(TARGET, run_name="__main__")


if __name__ == "__main__":
    main()

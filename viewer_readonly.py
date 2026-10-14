# -*- coding: utf-8 -*-
"""ASCII-named launcher for the READ-ONLY viewer (another PC on the same Google Drive).
cmd.exe garbles non-ASCII text inside .bat files, so 기업추적_조회.bat calls this file.

조회 전용(2026-10-15) — 이 PC 가 아닌 다른 PC 에서 기업추적 화면을 '보기만' 한다:
  1) 바탕화면에 '기업추적' 바로가기(.lnk → 기업추적_조회.bat)가 없으면 만든다 — 다른 프로그램(powershell)을 부르는 일이라
     조회 전용을 켜기 **전에** 한다. --no-shortcut(또는 GIUP_NO_SHORTCUT=1)이면 건너뛴다(메인 PC 에서 확인할 때).
     --make-shortcut 이면 바로가기만 만들고 끝낸다(서버 안 띄움).
  2) 조회전용.enable(base=이 폴더, shadow=%LOCALAPPDATA%\\기업추적\\조회전용\\shadow) — 서버 모듈을 읽기 전에.
     드라이브 쪽 쓰기는 shadow 로, 바깥 연결 · 다른 프로그램 실행은 막힌다.
  3) runpy 로 서버.py 를 --readonly --no-auto --no-browser --port 8770(기본) 으로 부른다. 브라우저는 bat 이 연다.
로그: pythonw(콘솔 없음)일 때 %LOCALAPPDATA%\\기업추적\\조회전용\\viewer_ro.log (드라이브 밖). GIUP_RO_LOG 로 바꿀 수 있다.
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
DEFAULT_PORT = "8770"
LOCAL = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "기업추적", "조회전용")
OWN_FLAGS = ("--no-shortcut", "--make-shortcut")


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


def shortcut_ps(bat, workdir, lnk_name=LNK_NAME):
    """바탕화면에 lnk_name 이 없으면 bat 을 가리키는 바로가기를 만드는 PowerShell. 'exists' | 'made' 를 찍는다."""
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "$d = [Environment]::GetFolderPath('Desktop')",
        "if (-not $d) { Write-Output 'nodesktop'; exit 2 }",
        "$p = Join-Path $d %s" % _ps_quote(lnk_name),
        "if (Test-Path -LiteralPath $p) { Write-Output 'exists'; exit 0 }",
        "$w = New-Object -ComObject WScript.Shell",
        "$s = $w.CreateShortcut($p)",
        "$s.TargetPath = %s" % _ps_quote(bat),
        "$s.WorkingDirectory = %s" % _ps_quote(workdir),
        "$s.Description = %s" % _ps_quote("기업추적 조회 전용 — 이 PC 는 보기만 합니다"),
        "$s.Save()",
        "Write-Output 'made'",
    ])


def encode_ps(script):
    """powershell -EncodedCommand 용 — UTF-16LE 를 base64 로. 한글 경로가 cmd · 코드 페이지를 거치지 않는다."""
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _powershell():
    p = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return p if os.path.exists(p) else "powershell.exe"


def ensure_shortcut(desktop=None, run=None):
    """바탕화면에 '기업추적' 바로가기가 없으면 만든다. 'skip' | 'exists' | 'made' | 'failed: ...' — 예외는 내지 않는다.
    조회 전용을 켜기 전에 불러야 한다(켠 뒤에는 powershell 실행이 막힌다)."""
    if os.environ.get("GIUP_NO_SHORTCUT") == "1":
        return "skip"
    try:
        d = desktop or desktop_dir()
        if d and os.path.exists(os.path.join(d, LNK_NAME)):
            return "exists"
        cmd = [_powershell(), "-NoProfile", "-NonInteractive", "-EncodedCommand", encode_ps(shortcut_ps(BAT, HERE))]
        p = (run or subprocess.run)(cmd, capture_output=True, text=True, errors="replace", timeout=60,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        lines = [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]
        out = lines[-1] if lines else ""
        if p.returncode == 0 and out in ("made", "exists"):
            return out
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
    path = os.environ.get("GIUP_RO_LOG") or os.path.join(LOCAL, "viewer_ro.log")
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
    if "--make-shortcut" in argv:
        print("desktop shortcut:", ensure_shortcut(), flush=True)
        sys.exit(0)
    _attach_log()
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

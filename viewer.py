# -*- coding: utf-8 -*-
"""ASCII-named launcher for 서버.py. cmd.exe garbles non-ASCII text inside
.bat files, so the .bat calls this file, and this file calls the real server.

작업 스케줄러에서는 pythonw.exe 로 이 파일을 직접 부른다 (콘솔 창 없음,
Ctrl+C 로 죽지 않음). pythonw 에는 stdout 이 없으므로 로그를 파일로 돌린다.
GIUP_LOG 환경변수로 경로를 바꿀 수 있다.
"""
import io
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "서버.py")
DEFAULT_LOG = os.path.join(HERE, "viewer_auto.log")


def _attach_log():
    if sys.stdout is not None and os.environ.get("GIUP_LOG") is None:
        return
    path = os.environ.get("GIUP_LOG") or DEFAULT_LOG
    fh = open(path, "a", encoding="utf-8", buffering=1, errors="replace")
    sys.stdout = fh
    sys.stderr = fh
    if sys.stdin is None:
        sys.stdin = io.StringIO("")


_attach_log()

if not os.path.exists(TARGET):
    print("server script not found:", TARGET)
    sys.exit(1)

runpy.run_path(TARGET, run_name="__main__")

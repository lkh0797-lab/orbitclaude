# -*- coding: utf-8 -*-
"""ASCII-named launcher. cmd.exe garbles non-ASCII text inside .bat files,
so the .bat calls this file, and this file calls the real collector.

작업 스케줄러에서는 pythonw.exe 로 이 파일을 직접 부른다. 그러면
  * 콘솔 창이 아예 안 뜨고 (bat 을 거치면 cmd 창이 뜬다)
  * 콘솔이 없으니 Ctrl+C 가 닿지 않는다
     (전에는 STATUS_CONTROL_C_EXIT 0xC000013A 로 계속 죽었다)
다만 pythonw 에는 stdout 이 없어서 print 가 터진다. 그래서 여기서
로그 파일로 직접 돌려준다. GIUP_LOG 환경변수로 경로를 바꿀 수 있다.
"""
import io
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "기업추적_수집기.py")
DEFAULT_LOG = os.path.join(HERE, "collect_auto.log")


def _attach_log():
    if sys.stdout is not None and os.environ.get("GIUP_LOG") is None:
        return
    path = os.environ.get("GIUP_LOG") or DEFAULT_LOG
    fh = open(path, "a", encoding="utf-8", buffering=1, errors="replace")
    sys.stdout = fh
    sys.stderr = fh
    # pythonw 는 stdin 도 없다. input() 을 부르는 코드가 있으면 여기서 막힌다.
    if sys.stdin is None:
        sys.stdin = io.StringIO("")


_attach_log()

if not os.path.exists(TARGET):
    print("collector script not found:", TARGET)
    sys.exit(1)

runpy.run_path(TARGET, run_name="__main__")

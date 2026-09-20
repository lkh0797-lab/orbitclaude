# -*- coding: utf-8 -*-
"""ASCII-named launcher for 서버.py. cmd.exe garbles non-ASCII text inside
.bat files, so the .bat calls this file, and this file calls the real server."""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "서버.py")

if not os.path.exists(TARGET):
    print("server script not found:", TARGET)
    sys.exit(1)

runpy.run_path(TARGET, run_name="__main__")

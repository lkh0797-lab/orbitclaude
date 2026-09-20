# -*- coding: utf-8 -*-
"""ASCII-named launcher. cmd.exe garbles non-ASCII text inside .bat files,
so the .bat calls this file, and this file calls the real collector."""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "기업추적_수집기.py")

if not os.path.exists(TARGET):
    print("collector script not found:", TARGET)
    sys.exit(1)

runpy.run_path(TARGET, run_name="__main__")

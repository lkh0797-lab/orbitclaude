@echo off
rem ASCII-only on purpose: cmd.exe garbles non-ASCII text inside .bat files.
rem Launched by Windows Task Scheduler so it survives Claude / console closing.
rem No 'pause' here -- a scheduled task must never wait for input.
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

rem pythonw.exe has no console at all. Two things follow from that:
rem   * no black window pops up
rem   * console control events (Ctrl+C) can never reach it, which is what used
rem     to kill these runs with STATUS_CONTROL_C_EXIT (0xC000013A)
rem Fall back to python.exe only if pythonw is missing.
set "PYW="
where pythonw >nul 2>nul
if not errorlevel 1 set "PYW=pythonw"
if not defined PYW (
  if exist "%LOCALAPPDATA%\Programs\Python\Python311-32\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python311-32\pythonw.exe"
)
if not defined PYW (
  where python >nul 2>nul
  if not errorlevel 1 set "PYW=python"
)
if not defined PYW exit /b 1

rem %1 = max calls for this run (default 17000)
set "MAXCALLS=%~1"
if "%MAXCALLS%"=="" set "MAXCALLS=17000"

"%PYW%" "%~dp0run.py" --years 15 --max-calls %MAXCALLS% >> "%~dp0collect_auto.log" 2>&1
exit /b %ERRORLEVEL%

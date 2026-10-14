@echo off
rem ASCII-only on purpose: cmd.exe garbles non-ASCII text inside .bat files.
rem CRLF line endings on purpose: cmd.exe can miss :labels in LF-only batch files.
rem
rem READ-ONLY viewer for ANOTHER PC that gets this folder through Google Drive.
rem That PC only looks. It changes no file on the drive, calls no outside service
rem (DART, Naver, KIS, customs, Telegram) and starts no other program.
rem viewer_readonly.py switches that mode on before the server code loads, then
rem runs the server with --readonly on port 8770. The main PC keeps doing all
rem collecting, computing and git work.
rem
rem Steps:
rem   1. find Python 3.9+ : where python, then py -3, then
rem      %LOCALAPPDATA%\Programs\Python\Python3*\python.exe
rem      none -> English help, open python.org, pause
rem   2. port 8765 LISTENING on this PC (the main viewer) -> open it in the browser, done
rem   3. port 8770 LISTENING (read-only viewer already up) -> open it, done
rem   4. Python package requests missing -> pip install --user requests openpyxl
rem   5. desktop shortcut to this file missing -> viewer_readonly.py makes it
rem      (Python + PowerShell -EncodedCommand, because its name is Korean)
rem   6. start the read-only server with pythonw (no console window),
rem      wait up to 90 s for port 8770 LISTENING, then open the browser
rem Log: viewer_ro.log under %LOCALAPPDATA% (outside the drive), path printed on failure.
rem
rem Test switches (environment):
rem   GIUP_RO_DRYRUN=1   print what it would do (browser, pip, shortcut, start) instead of doing it
rem   GIUP_RO_MAIN_PORT / GIUP_RO_PORT   override 8765 / 8770
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONDONTWRITEBYTECODE=1"
set "HERE=%~dp0"
if not defined GIUP_RO_MAIN_PORT set "GIUP_RO_MAIN_PORT=8765"
if not defined GIUP_RO_PORT set "GIUP_RO_PORT=8770"
set "DRY="
if "%GIUP_RO_DRYRUN%"=="1" set "DRY=1"

rem ---------------------------------------------------------------- 1. Python
set "PYEXE="
set "PYTMP=%TEMP%\giup_ro_python_%RANDOM%.txt"
where python >nul 2>nul
if not errorlevel 1 call :try_py python
if defined PYEXE goto :have_py
where py >nul 2>nul
if not errorlevel 1 call :try_py py -3
if defined PYEXE goto :have_py
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
  if not defined PYEXE if exist "%%~fD\python.exe" call :try_py "%%~fD\python.exe"
)
if defined PYEXE goto :have_py

echo.
echo   Python 3.9 or newer was not found on this PC.
echo.
echo   1. The Python download page opens now. Download and run the installer.
echo   2. On the first installer screen, tick "Add python.exe to PATH".
echo   3. When it is done, double-click this file again.
echo.
call :open "https://www.python.org/downloads/"
pause
exit /b 1

:have_py
if exist "%PYTMP%" del "%PYTMP%" >nul 2>nul
for %%F in ("%PYEXE%") do set "PYWEXE=%%~dpFpythonw.exe"
if not exist "%PYWEXE%" set "PYWEXE=%PYEXE%"
echo Python: %PYEXE%

rem ---------------------------------------------------------------- 2. main viewer on this PC
call :listening %GIUP_RO_MAIN_PORT%
if errorlevel 1 goto :no_main
echo The main viewer is running on this PC - opening it.
call :open "http://127.0.0.1:%GIUP_RO_MAIN_PORT%/"
exit /b 0
:no_main

rem ---------------------------------------------------------------- 3. read-only viewer already up
call :listening %GIUP_RO_PORT%
if errorlevel 1 goto :no_ro
echo The read-only viewer is already running - opening it.
call :open "http://127.0.0.1:%GIUP_RO_PORT%/"
exit /b 0
:no_ro

rem ---------------------------------------------------------------- 4. packages
"%PYEXE%" -c "import requests, openpyxl" >nul 2>nul
if not errorlevel 1 goto :have_pkgs
echo Installing Python packages for this user: requests openpyxl
if defined DRY (
  echo DRYRUN "%PYEXE%" -m pip install --user requests openpyxl
) else (
  "%PYEXE%" -m pip install --user requests openpyxl
)
:have_pkgs

rem ---------------------------------------------------------------- 5. desktop shortcut
if defined DRY (
  echo DRYRUN shortcut "%PYEXE%" "%HERE%viewer_readonly.py" --make-shortcut
) else (
  "%PYEXE%" "%HERE%viewer_readonly.py" --make-shortcut
)

rem ---------------------------------------------------------------- 6. start the read-only server
echo Starting the read-only viewer on port %GIUP_RO_PORT% ...
if defined DRY (
  echo DRYRUN start "%PYWEXE%" "%HERE%viewer_readonly.py" --no-shortcut --port %GIUP_RO_PORT%
  call :open "http://127.0.0.1:%GIUP_RO_PORT%/"
  exit /b 0
)
start "" "%PYWEXE%" "%HERE%viewer_readonly.py" --no-shortcut --port %GIUP_RO_PORT%
set /a WAITED=0
:wait_loop
call :listening %GIUP_RO_PORT%
if not errorlevel 1 goto :ready
if %WAITED% GEQ 90 goto :not_ready
ping -n 2 127.0.0.1 >nul
set /a WAITED+=1
goto :wait_loop

:ready
call :open "http://127.0.0.1:%GIUP_RO_PORT%/"
exit /b 0

:not_ready
echo.
echo   The read-only viewer did not open port %GIUP_RO_PORT% within 90 seconds.
echo   Its log file:
"%PYEXE%" -c "import os; print('  ' + os.path.join(os.environ.get('LOCALAPPDATA', ''), '\uae30\uc5c5\ucd94\uc801', '\uc870\ud68c\uc804\uc6a9', 'viewer_ro.log'))"
echo.
pause
exit /b 1

rem ================================================================ helpers
:try_py
rem Usable = runs and is 3.9+. The Microsoft Store stub on PATH fails here (exit 9009).
%* -c "import sys; assert sys.version_info >= (3, 9); print(sys.executable)" >"%PYTMP%" 2>nul
if errorlevel 1 exit /b 1
set "PYEXE="
set /p PYEXE=<"%PYTMP%"
if defined PYEXE if not exist "%PYEXE%" set "PYEXE="
exit /b 0

:listening
rem errorlevel 0 when some local address :PORT is in LISTENING state
netstat -an | findstr /R /C:":%~1 .*LISTENING" >nul
exit /b %errorlevel%

:open
if defined DRY (
  echo DRYRUN open %~1
) else (
  start "" "%~1"
)
exit /b 0

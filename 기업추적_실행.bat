@echo off
rem ASCII-only on purpose: cmd.exe garbles non-ASCII text inside .bat files.
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

set "PY="
where python >nul 2>nul
if not errorlevel 1 set "PY=python"

if not defined PY (
  if exist "%LOCALAPPDATA%\Programs\Python\Python311-32\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311-32\python.exe"
)

if not defined PY (
  where py >nul 2>nul
  if not errorlevel 1 set "PY=py"
)

if not defined PY (
  echo [ERROR] Python not found on this PC.
  echo Install Python 3, or tell Claude your python.exe path.
  pause
  exit /b 1
)

"%PY%" -c "import requests" >nul 2>nul
if errorlevel 1 (
  echo Installing 'requests' ...
  "%PY%" -m pip install requests
)

"%PY%" "%~dp0run.py" %*
set RC=%ERRORLEVEL%

echo.
echo ===== DONE (exit code %RC%) =====
pause
exit /b %RC%

@echo off
rem City Infrastructure Designer - start it and open it in your web browser.
rem Double-click this file. Keep the black window open while you work.
cd /d "%~dp0backend"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is needed. Install it from https://www.python.org/downloads/
  echo and tick "Add Python to PATH" during installation. Then double-click this file again.
  pause
  exit /b 1
)
%PY% -c "import yaml, numpy, scipy" >nul 2>nul
if errorlevel 1 (
  echo First start: installing the parts the program needs - one time only...
  %PY% -m pip install --user -e .
  if errorlevel 1 (
    echo Installation failed. Ask your IT support to run: pip install -e backend
    pause
    exit /b 1
  )
)
if not exist "..\engines\lib\swmm5.dll" (
  echo First start: downloading the calculation engines EPA SWMM and EPANET - one time only...
  powershell -NoProfile -ExecutionPolicy Bypass -File "..\engines\get_engines_windows.ps1"
  if not exist "..\engines\lib\swmm5.dll" (
    echo The engines could not be downloaded. Water supply checks and network simulations will be skipped;
    echo everything else works. See docs\platform\VSCODE_AND_WEBSITE.md
  )
)
%PY% -m cityinfra.app %*
pause

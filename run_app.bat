@echo off
setlocal enabledelayedexpansion

REM Change to the directory of this script
cd /d "%~dp0"

echo.
echo === Timetabling App Launcher ===

REM Validate Python 3.11-3.13 availability
set "PYCMD="
set "PYDISPLAY="
call :try_python "py -3.13"
if not defined PYCMD call :try_python "py -3.12"
if not defined PYCMD call :try_python "py -3.11"
if not defined PYCMD call :try_python "python"

if not defined PYCMD (
  echo.
  echo [ERROR] Python 3.11^–3.13 is required but was not found on PATH.
  echo Please install Python 3.13 from https://www.python.org/downloads/ and re-run.
  pause
  exit /b 1
)

echo Using Python !PYDISPLAY! via: %PYCMD%

REM Create virtual environment if missing
if not exist "venv\Scripts\activate.bat" (
  echo Creating virtual environment in .\venv ...
  %PYCMD% -m venv venv
  if errorlevel 1 (
    echo.
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
  )
)

REM Activate virtual environment
call "venv\Scripts\activate.bat"
if errorlevel 1 (
  echo.
  echo [ERROR] Failed to activate virtual environment.
  pause
  exit /b 1
)

REM Use the venv's interpreter for subsequent python invocations
set "PYCMD=python"

REM Install/upgrade dependencies
echo Installing dependencies from requirements.txt ...
%PYCMD% -m pip install --upgrade pip >nul 2>&1
%PYCMD% -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo [ERROR] Dependency installation failed.
  echo You can try running: %PYCMD% -m pip install -r requirements.txt
  pause
  exit /b 1
)

REM Initialize DB and start the Flask app
echo Launching the app...
echo Open your browser to http://127.0.0.1:5000/
%PYCMD% app.py

echo.
echo App exited. Press any key to close.
pause

goto :eof

:try_python
set "CAND=%~1"
set "PYTMP_OUT="
for /f "tokens=1,2" %%a in ('cmd /c %CAND% --version 2^>nul') do (
  if /i "%%a"=="Python" (
    set "PYTMP_OUT=%%b"
  )
)
if not defined PYTMP_OUT exit /b 1

set "PYTMP_MAJOR="
set "PYTMP_MINOR="
for /f "tokens=1,2 delims=." %%i in ("!PYTMP_OUT!") do (
  set "PYTMP_MAJOR=%%i"
  set "PYTMP_MINOR=%%j"
)

if not "!PYTMP_MAJOR!"=="3" exit /b 1
if not defined PYTMP_MINOR exit /b 1

for /f "tokens=1 delims=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-+_ " %%i in ("!PYTMP_MINOR!") do set "PYTMP_MINOR=%%i"
if not defined PYTMP_MINOR exit /b 1

set /a PYTMP_MINOR_NUM=PYTMP_MINOR >nul 2>&1
if errorlevel 1 exit /b 1
if !PYTMP_MINOR_NUM! LSS 11 exit /b 1
if !PYTMP_MINOR_NUM! GTR 13 exit /b 1

set "PYCMD=%CAND%"
set "PYDISPLAY=!PYTMP_OUT!"
exit /b 0


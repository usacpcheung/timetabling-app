@echo off
setlocal enabledelayedexpansion

REM Change to the directory of this script
cd /d "%~dp0"

echo.
echo === Timetabling App Launcher ===

REM Prefer python, fall back to py -3 if needed
set "PYCMD=python"
where %PYCMD% >nul 2>nul
if errorlevel 1 (
  set "PYCMD=py -3"
  where %PYCMD% >nul 2>nul
  if errorlevel 1 (
    echo.
    echo [ERROR] Python was not found on PATH.
    echo Please install Python 3.9+ from https://www.python.org/downloads/ and re-run.
    pause
    exit /b 1
  )
)

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

REM Install/upgrade dependencies
echo Installing dependencies from requirements.txt ...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo [ERROR] Dependency installation failed.
  echo You can try running: python -m pip install -r requirements.txt
  pause
  exit /b 1
)

REM Initialize DB and start the Flask app
echo Launching the app...
echo Open your browser to http://127.0.0.1:5000/
python app.py

echo.
echo App exited. Press any key to close.
pause


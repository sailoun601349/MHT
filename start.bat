@echo off
chcp 65001 >nul
title Kivi Order System
cd /d %~dp0

rem --- 1. Create venv (first run only) ---
if not exist venv (
  echo [1/3] Creating virtual environment...
  python -m venv venv
  if errorlevel 1 goto :no_python
)
call venv\Scripts\activate.bat

rem --- 2. Install dependencies ---
echo [2/3] Installing dependencies...
pip install -r requirements.txt -q

rem --- 3. Start server ---
echo [3/3] Starting server: http://127.0.0.1:5000
echo Admin login: http://127.0.0.1:5000/admin/login
echo Press Ctrl+C to stop
echo.
python run.py
pause
exit /b

:no_python
echo.
echo Python not found. Install Python 3.10+ and add it to PATH, or use "py" instead.
pause
exit /b

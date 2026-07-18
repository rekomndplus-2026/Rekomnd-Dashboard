@echo off
title REKOMND+ Dashboard
color 0b

echo ===================================================
echo     REKOMND+ Lead Intelligence Startup Script
echo ===================================================

cd /d "%~dp0"

echo [1/4] Checking Python environment...
if not exist ".venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Error: Could not create virtual environment. Is Python installed?
        pause
        exit /b 1
    )
)

call .venv\Scripts\activate.bat

echo [2/4] Installing dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo Error: Failed to install requirements.
    pause
    exit /b 1
)

echo [3/4] Ensuring browsers are installed for the scraper...
playwright install chromium

echo [4/4] Starting the engine and dashboard...
echo The dashboard will open in your default browser momentarily.
echo Keep this window open to keep the engine running!
echo ===================================================

:: Start the browser slightly delayed
start "" powershell -WindowStyle Hidden -Command "Start-Sleep -Seconds 4; Start-Process 'http://127.0.0.1:8000/'"

:: Start the Python backend which will serve the frontend
python api\server.py

pause

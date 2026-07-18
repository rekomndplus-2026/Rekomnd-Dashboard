@echo off
title REKOMND+ v3 — Unified Platform
color 0b

echo.
echo  ██████╗ ███████╗██╗  ██╗ ██████╗ ███╗   ███╗███╗   ██╗██████╗       
echo  ██╔══██╗██╔════╝██║ ██╔╝██╔═══██╗████╗ ████║████╗  ██║██╔══██╗ ██╗  
echo  ██████╔╝█████╗  █████╔╝ ██║   ██║██╔████╔██║██╔██╗ ██║██║  ██║ ╚═╝  
echo  ██╔══██╗██╔══╝  ██╔═██╗ ██║   ██║██║╚██╔╝██║██║╚██╗██║██║  ██║ ██╗  
echo  ██║  ██║███████╗██║  ██╗╚██████╔╝██║ ╚═╝ ██║██║ ╚████║██████╔╝ ╚═╝  
echo  ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═══╝╚═════╝      
echo.
echo  v3 — Multi-User Platform · No Docker Required
echo  ══════════════════════════════════════════════════════════════
echo.

REM ── Set working directory to this script's location ──
cd /d "%~dp0"

REM ── Check Python ──
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Please install Python 3.10+
    pause & exit /b 1
)

REM ── Check Node.js ──
node --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Node.js not found. Please install Node.js 18+ from https://nodejs.org
    pause & exit /b 1
)

REM ── Install Python dependencies ──
echo  [1/6] Installing Python dependencies...
pip install -q -r rekomnd_plus\requirements.txt
pip install -q flask-cors
pip install -q -r fb_buyers_egypt\requirements.txt
pip install -q -r whatsapp-bulk-sender\whatsapp-bulk-sender\backend\requirements.txt

REM ── Install Baileys WA server dependencies ──
echo  [2/6] Installing WhatsApp Baileys gateway (first run takes ~60s)...
cd /d "%~dp0whatsapp-bulk-sender\wa-server"
if not exist node_modules (
    call npm install --prefer-offline --no-audit --no-fund >nul 2>&1
    if errorlevel 1 (
        echo  [WARN] npm install had issues — retrying...
        call npm install --no-audit --no-fund
    )
)
cd /d "%~dp0"

REM ── Free all ports ──
echo  [3/6] Freeing ports 5000, 5001, 7070, 8000, 8085, 3001...

for %%P in (3001 5000 5001 7070 8000 8085) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%P " ^| findstr LISTENING 2^>nul') do (
        taskkill /F /PID %%a >nul 2>&1
    )
)

timeout /t 2 /nobreak >nul

REM ── Start FB Auto Poster ──
echo  [4/6] Starting services...
start "FB Auto Poster :5000" /min cmd /c "cd /d "%~dp0fb-auto-poster" && python app.py"

REM ── Start FB Commenter V2 ──
start "FB Commenter :5001" /min cmd /c "cd /d "%~dp0fb-commenter-v2" && set FLASK_PORT=5001 && python app.py"

REM ── Start Buyers Leads API ──
start "Buyers API :8000" /min cmd /c "cd /d "%~dp0fb_buyers_egypt" && python -m uvicorn api.server:app --host 0.0.0.0 --port 8000 --no-access-log"

REM ── Start Baileys WhatsApp Gateway (replaces Evolution API Docker) ──
start "WA Baileys Gateway :8085" /min cmd /c "cd /d "%~dp0whatsapp-bulk-sender\wa-server" && set PORT=8085 && node server.js"

REM ── Start WhatsApp FastAPI Backend ──
start "WA Backend :3001" /min cmd /c "cd /d "%~dp0whatsapp-bulk-sender\whatsapp-bulk-sender\backend" && python -m uvicorn main:app --host 0.0.0.0 --port 3001 --no-access-log"

REM ── Wait for services ──
echo.
echo  Waiting for services to initialize (8 seconds)...
timeout /t 8 /nobreak >nul

echo.
echo  ══════════════════════════════════════════════════════════════
echo   REKOMND+ v3 — All Services Starting
echo  ══════════════════════════════════════════════════════════════
echo   🌐  Main App:         http://localhost:7070
echo   🔐  Login:            http://localhost:7070/login
echo   👥  User Management:  http://localhost:7070/admin/users
echo   🗺   GMaps Scraper:    http://localhost:7070/gmaps
echo   📢  FB Auto Poster:   http://localhost:7070/poster
echo   💬  FB Commenter:     http://localhost:7070/commenter
echo   🏠  Buyer Leads:      http://localhost:7070/buyers
echo   📲  WhatsApp Sender:  http://localhost:7070/whatsapp
echo  ══════════════════════════════════════════════════════════════
echo   Default admin login:  admin / admin123
echo  ══════════════════════════════════════════════════════════════
echo   WhatsApp Architecture (NO DOCKER):
echo     :8085  Baileys Gateway  (replaces Evolution API)
echo     :3001  FastAPI Backend
echo  ══════════════════════════════════════════════════════════════
echo.

REM ── Start REKOMND+ main shell ──
cd /d "%~dp0rekomnd_plus"
python main.py

pause

@echo off
title WhatsApp Bulk Sender - Startup
echo =========================================
echo    Starting WhatsApp Bulk Sender...
echo =========================================
echo.

:: Navigate to the directory where this script is located
cd /d "%~dp0"

:: Check if Docker is running
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker is not running.
    echo Please start Docker Desktop and run this script again.
    echo.
    pause
    exit /b
)

:: Start the containers in detached mode
echo Starting Docker containers...
docker compose up -d

:: Wait a few seconds to ensure the frontend server has time to bind the port
echo.
echo Waiting for services to initialize...
timeout /t 3 /nobreak >nul

:: Open the dashboard in the default web browser
echo.
echo Opening dashboard (http://localhost:3000) in your browser...
start http://localhost:3000

echo.
echo =========================================
echo    Dashboard is ready! 
echo    You can close this window now.
echo =========================================
timeout /t 5 >nul
exit

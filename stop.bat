@echo off
title Stop Words
cd /d "%~dp0"
echo [Words] Stopping application and background services...

:: Attempt graceful HTTP engine shutdown
curl -s -m 2 -X POST http://127.0.0.1:8787/shutdown >nul 2>&1

:: Cleanly terminate LLM engine if lingering
taskkill /f /im llama-server.exe >nul 2>&1

:: Close any remaining Words UI windows
taskkill /f /fi "WINDOWTITLE eq Words*" >nul 2>&1

echo [Words] All services stopped cleanly.
timeout /t 1 >nul
exit /b 0

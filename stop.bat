@echo off
setlocal
title Stop Words
cd /d "%~dp0"
echo [Words] Stopping application and background services...

:: 1. Trigger graceful HTTP shutdown of Node.js engine and llama-server
curl -s -m 2 -X POST http://127.0.0.1:8787/shutdown >nul 2>&1

:: 2. Terminate Words UI process specifically (Safe: never kills other apps titled Words)
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"(Name = 'python.exe' OR Name = 'pythonw.exe') AND CommandLine LIKE '%%app.py%%'\" -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

:: 3. Terminate any orphan process specifically bound to engine port 8787
powershell -NoProfile -Command "try { $p = Get-NetTCPConnection -LocalPort 8787 -ErrorAction Stop | Select-Object -ExpandProperty OwningProcess -Unique; foreach ($id in $p) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue } } catch {}" >nul 2>&1

:: 4. Clean up any lingering llama-server instance
taskkill /f /im llama-server.exe >nul 2>&1

echo [Words] Application and background services stopped cleanly.
timeout /t 1 >nul
exit /b 0

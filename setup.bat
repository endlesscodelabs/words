@echo off
setlocal
title Words - Setup & Environment Initializer
cd /d "%~dp0"

echo ========================================================
echo        Words: Offline Writing Assistant Setup
echo ========================================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python 3.10+ is required but not found in PATH.
    echo Please install Python from https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python detected.

:: 2. Check Node.js
node --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Node.js 18+ is required but not found in PATH.
    echo Please install Node.js from https://nodejs.org/
    pause
    exit /b 1
)
echo [OK] Node.js detected.

:: 3. Python dependencies
echo.
echo Installing Python dependencies from requirements.txt...
python -m pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo [WARNING] Failed to install Python dependencies. Please check pip output.
)

:: 4. Node.js engine dependencies
echo.
echo Installing Node.js engine dependencies...
cd engine
call npm install
cd ..
if %ERRORLEVEL% neq 0 (
    echo [WARNING] Failed to install npm dependencies for engine.
)

:: 5. Directory structure checks
if not exist "models" mkdir models
if not exist "bin" mkdir bin

echo.
echo ========================================================
echo                 Setup Complete!
echo ========================================================
echo To run the application:
echo   - Execute start.bat (or python app.py)
echo   - To stop background services: stop.bat
echo.
pause
exit /b 0

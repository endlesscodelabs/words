@echo off
setlocal enabledelayedexpansion
title Words - Desktop Assistant
cd /d "%~dp0"

:: Check for Node.js
where node >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Node.js is not installed or not in PATH.
    echo Please install Node.js (v18+) from https://nodejs.org/
    pause
    exit /b 1
)

:: Detect Python executable (venv or system)
set "PYTHON_EXE="
if exist ".venv\Scripts\pythonw.exe" (
    set "PYTHON_EXE=.venv\Scripts\pythonw.exe"
) else if exist "venv\Scripts\pythonw.exe" (
    set "PYTHON_EXE=venv\Scripts\pythonw.exe"
) else (
    where pythonw >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        set "PYTHON_EXE=pythonw"
    ) else (
        where python >nul 2>&1
        if !ERRORLEVEL! equ 0 (
            set "PYTHON_EXE=python"
        )
    )
)

if "%PYTHON_EXE%"=="" (
    echo [ERROR] Python is not found.
    echo Please install Python 3.10+ and run setup.bat
    pause
    exit /b 1
)

:: Launch Words
start "" "%PYTHON_EXE%" app.py
exit /b 0

@echo off
chcp 65001 >nul
title VaultLedger Launcher
color 0A
echo ===================================================
echo             VaultLedger Launcher
echo ===================================================
echo.
echo Launching VaultLedger application...

cd /d "%~dp0"

:: Ensure python is available
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python from https://python.org
    pause
    exit /b 1
)

:: Ensure Flask is installed
python -c "import flask" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing required packages...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Could not install dependencies. Run: pip install -r requirements.txt
        pause
        exit /b 1
    )
)

:: Start Flask app
start "VaultLedger Server" /min python app.py

:: Wait for server boot
timeout /t 3 /nobreak >nul

:: Open browser
start "" http://127.0.0.1:5000/

echo.
echo [SUCCESS] VaultLedger running live at http://127.0.0.1:5000/
echo.
echo Keep this window open while using the app.
echo Press any key to stop the server and exit.
pause >nul

echo Stopping VaultLedger server...
taskkill /f /t /fi "WINDOWTITLE eq VaultLedger Server*" >nul 2>&1
echo Done.

@echo off
setlocal
echo ==========================================
echo          StudyFlow Quick Setup
echo ==========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [-] Python was not found in your PATH.
    echo     Please install Python 3.8+ from https://www.python.org/downloads/
    echo     NOTE: Make sure to check "Add python.exe to PATH" during installation!
    echo.
    pause
    exit /b 1
)

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

if not exist ".venv" (
    echo [+] Creating virtual environment in .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [-] Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo [+] Existing virtual environment found in .venv
)

echo [+] Installing dependencies...
"%SCRIPT_DIR%.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
"%SCRIPT_DIR%.venv\Scripts\pip.exe" install -r requirements.txt

echo.
echo ==========================================
echo [✓] Setup completed successfully!
echo ==========================================
echo.
echo To launch StudyFlow, double-click run.bat or run:
echo   run.bat
echo.
echo Press any key to exit...
pause >nul
endlocal

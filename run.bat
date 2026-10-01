@echo off
setlocal
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

rem Check for virtual environment first
if exist "%SCRIPT_DIR%.venv\Scripts\pythonw.exe" (
    start "" "%SCRIPT_DIR%.venv\Scripts\pythonw.exe" "%SCRIPT_DIR%study_timer.py" %*
) else if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    "%SCRIPT_DIR%.venv\Scripts\python.exe" "%SCRIPT_DIR%study_timer.py" %*
) else if exist "%SCRIPT_DIR%venv\Scripts\pythonw.exe" (
    start "" "%SCRIPT_DIR%venv\Scripts\pythonw.exe" "%SCRIPT_DIR%study_timer.py" %*
) else if exist "%SCRIPT_DIR%venv\Scripts\python.exe" (
    "%SCRIPT_DIR%venv\Scripts\python.exe" "%SCRIPT_DIR%study_timer.py" %*
) else (
    python "%SCRIPT_DIR%study_timer.py" %*
)
endlocal

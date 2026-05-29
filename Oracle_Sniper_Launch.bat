@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Python not found in .venv\Scripts\python.exe
    pause
    exit /b 1
)

if not exist "Oracle_Sniper.py" (
    echo Oracle_Sniper.py not found.
    pause
    exit /b 1
)

if exist "oracle_sniper.lock" (
    for /f "usebackq delims=" %%P in ("oracle_sniper.lock") do set SNIPER_PID=%%P
    tasklist /FI "PID eq %SNIPER_PID%" | find "%SNIPER_PID%" >nul
    if errorlevel 1 (
        echo Removing stale Oracle Sniper lock for PID %SNIPER_PID%...
        del /f /q "oracle_sniper.lock"
    ) else (
        echo Oracle Sniper is already active.
        echo Close the existing Sniper window or stop it from Launcher Pro before starting a new one.
        pause
        exit /b 0
    )
)

echo Launching Oracle Sniper...
".venv\Scripts\python.exe" "Oracle_Sniper.py"

echo.
echo Oracle Sniper closed.
pause

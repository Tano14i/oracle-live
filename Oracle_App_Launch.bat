@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\streamlit.exe" (
    echo Streamlit not found in .venv\Scripts\streamlit.exe
    pause
    exit /b 1
)

if not exist "Oracle_App.py" (
    echo Oracle_App.py not found.
    pause
    exit /b 1
)

echo Starting Oracle App on http://localhost:8501
".venv\Scripts\streamlit.exe" run "Oracle_App.py" --server.headless true --server.port 8501

echo.
echo Oracle App stopped or failed to start.
pause

@echo off
REM ============================================================
REM  Meeting Notes - Single-Origin Launcher (one-click)
REM  Flask backend on 127.0.0.1:8765 serves:
REM    /            -> Meeting Notes UI
REM    /health      -> health check
REM    /transcribe  -> Whisper + speaker diarization + LLM
REM ============================================================

REM ---- Hardcode the venv pythonw path (where pythonw finds Windows Store stub instead) ----
set "VENV_PYTHONW=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\pythonw.exe"
set "LOG_FILE=%~dp0meeting_notes_server.log"
set "SERVER_URL=http://127.0.0.1:8765"

if defined HF_TOKEN (
    echo   HF_TOKEN environment variable is set.
) else (
    echo   HF_TOKEN not in CMD env - launcher reads it from Windows registry via setx.
)

REM ---- Step 1: detect existing server ----
echo Checking for an existing Meeting Notes server on 127.0.0.1:8765 ...
curl -s --max-time 2 %SERVER_URL%/health >nul 2>&1
if not errorlevel 1 (
    echo:
    echo   A Meeting Notes server is already running. Opening it in your browser.
    start "" %SERVER_URL%/
    exit /b 0
)

REM ---- Step 2: Start the Flask backend (hidden) ----
echo No server responding yet. Starting a fresh instance hidden ...
cd /d "%~dp0"
echo [%date% %time%] Starting Meeting Notes server > "%LOG_FILE%"
echo [%date% %time%] pythonw: %VENV_PYTHONW% >> "%LOG_FILE%"
echo [%date% %time%] script: %~dp0launch.py >> "%LOG_FILE%"
echo: >> "%LOG_FILE%"

start "Meeting Notes Server" "%VENV_PYTHONW%" "%~dp0launch.py"

REM ---- Step 3: Wait for /health (up to 90 seconds) ----
echo Waiting for the server to load Whisper + diarization (up to 90s) ...
set /a attempt=0
:waitloop
set /a attempt+=1
if %attempt% GTR 90 goto :notready
curl -s --max-time 3 %SERVER_URL%/health >nul 2>&1
if not errorlevel 1 goto :ready
timeout /t 1 /nobreak >nul
goto :waitloop

:ready
echo Server is ready after %attempt% seconds.
curl -s --max-time 5 %SERVER_URL%/health
echo:
echo Opening Meeting Notes in your browser ...
start "" %SERVER_URL%/
echo:
echo The Meeting Notes UI is now open.
echo Server log: %LOG_FILE%
echo To stop later: taskkill /F /FI "WINDOWTITLE eq Meeting Notes Server"
exit /b 0

:notready
echo:
echo *** Server did not become ready within 90 seconds. ***
echo    Check the log: %LOG_FILE%
echo    Model load (Whisper large-v3) takes 30-40s on first run.

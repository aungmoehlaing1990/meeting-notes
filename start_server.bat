@echo off
REM ============================================================
REM  Meeting Notes - Transcription Server (one-click launcher)
REM
REM  HuggingFace token: set it ONCE as a user environment
REM  variable named HF_TOKEN (no secret ever appears in the repo):
REM
REM   1. get a free token: https://huggingface.co/settings/tokens
REM      (default "read" scope is fine)
REM   2. accept the pyannote model agreements (three pages, each gated):
REM      https://huggingface.co/pyannote/speaker-diarization-3.1
REM      https://huggingface.co/pyannote-speaker-diarization-community-1
REM      https://huggingface.co/pyannote/segmentation-3.0
REM   3. win + r -> run:  setx HF_TOKEN "hf_YOUR_TOKEN"
REM      Then CLOSE Explorer / this terminal and open a NEW one
REM      before double-clicking start_server.bat.
REM
REM  Without HF_TOKEN set, the server still starts — transcription +
REM  AI report work, just not Speaker 1/2/3 labels.
REM ============================================================

set PYTHON=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe

echo.
echo Starting transcription server on http://localhost:8765
echo  - Whisper large-v3 transcription
echo  - Speaker diarization (needs HF token, from HF_TOKEN env var)
echo  - Local LLM report (Ollama, llama3.1:8b)
echo Keep this window open while you transcribe.
echo.

REM Check the Ollama service is running; start it if not
curl -s --max-time 2 http://localhost:11434/api/version >nul 2>&1
if errorlevel 1 (
  echo Ollama not running - starting it...
  start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
  timeout /t 5 /nobreak >nul
)

REM Run with diarization if a non-empty token is set, without otherwise
if "%HF_TOKEN%"=="" (
  echo [note] No HF_TOKEN env var set - running without speaker labels.
  "%PYTHON%" "%~dp0whisper_server.py" --no-diarization --llm
) else (
  "%PYTHON%" "%~dp0whisper_server.py" --hf-token "%HF_TOKEN%" --llm
)

echo.
echo Server stopped.
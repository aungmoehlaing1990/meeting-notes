#!/usr/bin/env python3
"""Single-origin server launcher: reads HF_TOKEN from the Windows registry,
then spawns the Flask server (serves UI at / + API at /health, /transcribe).
Run via pythonw.exe to keep it hidden; this file bridges the registry-token
gap so Start Meeting Notes.bat never needs %HF_TOKEN% in its own env.
"""
import os, sys, winreg, subprocess

_log = r"C:\Users\Aung moe Hlaing\meeting-notes\meeting_notes_server.log"

# Open log file and redirect stdout/stderr there (pythonw has no console)
_logfile = open(_log, "a", encoding="utf-8")
sys.stdout = _logfile
os.dup2(_logfile.fileno(), 1)
sys.stderr = _logfile
os.dup2(_logfile.fileno(), 2)

token = ""
try:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
        token = winreg.QueryValueEx(h, "HF_TOKEN")[0]
except Exception as e:
    print(f"[ERROR] Cannot read HF_TOKEN from registry: {e}")
    print("        Run in CMD: setx HF_TOKEN hf_yourtoken")
    sys.exit(1)
if not token.startswith("hf_"):
    print("[ERROR] Token invalid. Run: setx HF_TOKEN hf_yourtoken")
    sys.exit(1)

# Bundled FFmpeg on PATH
_ffmpeg_bin = r"C:\Users\Aung moe Hlaing\ffmpeg\bin"
if os.path.isdir(_ffmpeg_bin):
    os.environ["PATH"] = _ffmpeg_bin + os.pathsep + os.environ.get("PATH", "")

print(f"[startup] HF_TOKEN: {token[:6]}...{token[-4:]} (len={len(token)}) - valid")
print("[startup] starting single-origin server on 127.0.0.1:8765 ...")
print("[startup] serving: / (UI), /health, /transcribe")
sys.stdout.flush()

# Use subprocess.Popen (NOT os.execv) because os.execv on Windows does NOT properly quote
# argv elements containing spaces, which breaks paths like 'C:\Users\Aung moe Hlaing\...'
PY = r"C:\Users\Aung moe Hlaing\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
SERVER = r"C:\Users\Aung moe Hlaing\meeting-notes\whisper_server.py"
CREATE_NO_WINDOW = 0x08000000  # sw.hide: no console window appears
proc = subprocess.Popen(
    [PY, SERVER, "--hf-token", token, "--llm", "--port", "8765", "--host", "127.0.0.1"],
    stdout=_logfile, stderr=subprocess.STDOUT,
    creationflags=CREATE_NO_WINDOW
)
print(f"[startup] server PID: {proc.pid}")
sys.stdout.flush()
sys.exit(proc.wait())

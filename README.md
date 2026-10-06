# Meeting Notes

A single-file, offline meeting note-taking app with local AI transcription, speaker labels, and professional-grade report generation.

**Live app:** [meeting-notes.html](https://aungmoehlaing1990.github.io/meeting-notes/meeting-notes.html)

Record the meeting on your phone (audio + photos), then after the meeting use this app to auto-transcribe, structure, and export a professional meeting report.

## What it does

- **Transcribe** — runs local **Whisper large-v3** on your machine (no cloud, no API billing)
- **Speaker labels** — pyannote speaker diarization (Speaker 1, Speaker 2, ...)
- **AI Report** — a local LLM (Ollama, `llama3.1:8b`) writes an executive summary, topics, conclusions, decisions, action items (owner + due date), and next-meeting expectations
- **Structured notes** — title, date, attendees, transcript, decisions, action-item table, photo captions, follow-up links to previous meetings
- **Exports** — `.docx` (photos embedded, ready to send to superiors) + Markdown (archive) + one-meeting JSON transfer (move a note between phone and desktop)
- **Works on phone and desktop** — same file, responsive layout, IndexedDB local storage

## Files

| File | What it is |
|---|---|
| `meeting-notes.html` | The app. Open in Chrome/Edge. No build step, no dependencies. |
| `whisper_server.py` | Local transcription server (Whisper + pyannote + Ollama LLM). |
| `start_server.bat` | One-click launcher for the server (Windows). |
| `SETUP.md` | Full installation & usage guide. |

## Quick start (Windows)

1. `winget install Gyan.FFmpeg`
2. `pip install flask openai-whisper pyannote.audio`
3. Install [Ollama](https://ollama.com) and run `ollama pull llama3.1:8b`
4. Create a free HuggingFace token (needed only for speaker labels) and paste it into `start_server.bat`
5. Double-click `start_server.bat`
6. Open `meeting-notes.html` in a browser, tap **New Meeting**, import your recording, tap **Transcribe**

Full details, troubleshooting, and the phone workflow: see [SETUP.md](SETUP.md).

## Privacy

Everything stays on your machine: transcription, speaker separation, and report writing all run locally. Nothing is sent to any cloud service except the one-time model downloads (HuggingFace / Ollama).

# Meeting Notes — Setup Guide (Windows)

Complete installation and usage guide for the Meeting Notes app + local transcription server.

---

## What you need

| Item | Why | Cost |
|---|---|---|
| Windows 10/11 | The launcher and server target Windows | — |
| Python 3.11+ | Runs the server | Free |
| ffmpeg | Required by Whisper and pyannote | Free |
| [Ollama](https://ollama.com) | Runs the local LLM for reports | Free |
| HuggingFace account | Free token for speaker models | Free |
| Chrome or Edge | The app runs in the browser | Free |

---

## 1. Install prerequisites

Open PowerShell:

```powershell
winget install Ollama.Ollama
```

**ffmpeg — IMPORTANT (shared build):**

Whisper needs ffmpeg to convert audio. pyannote additionally needs FFmpeg's **shared** DLLs
(`avcodec-63.dll`, `avformat-63.dll`, etc.) because its audio decoder (torchcodec) links against them.

The easy way — the repo ships `get_ffmpeg.py` which downloads the right shared build (~90 MB)
and extracts the DLLs automatically:

```powershell
cd meeting-notes          # the cloned repo folder
python get_ffmpeg.py
```

Or do it by hand: download "ffmpeg-master-latest-win64-gpl-shared.zip" from
https://github.com/BtbN/FFmpeg-Builds/releases (NOT the static build from `winget install Gyan.FFmpeg`,
which is a single 242 MB exe with no DLLs) and extract `bin\*.dll` into a `ffmpeg\bin` folder.

Verify:
```powershell
.\ffmpeg\bin\ffmpeg.exe -version    # should print version info
```

Verify pyannote can see the shared libs (optional):
```powershell
$env:PATH = "C:\full\path\to\meeting-notes\ffmpeg\bin;" + $env:PATH
python -c "import torchcodec._internally_replaced_utils as u; print(u.load_core_libraries())"
# should print (9, '...\\libtorchcodec_core9.dll') with no error
```

If this step is skipped, transcription works but speaker diarization fails with
"Could not load libtorchcodec" — you'll see all speakers as "Speaker ?".

> **Note on Python:** this guide assumes the Python that has the packages installed is on your PATH as `python`. If `python` isn't recognized in your PowerShell, use `py` instead (e.g. `py -m pip install ...` and `py whisper_server.py`). If `pip` isn't recognized, use `python -m pip` instead.

Install the Python packages:

```powershell
pip install flask openai-whisper pyannote.audio
```

(First install downloads ~3–4 GB of dependencies. The Whisper **large-v3** model (~2.9 GB) and pyannote models (~1 GB) download automatically the first time the server runs.)

## 2. Install Ollama + the LLM

```powershell
winget install Ollama.Ollama
ollama pull llama3.1:8b
```

(`ollama pull` downloads ~4.7 GB once. Ollama usually starts itself on install; if the icon isn't in your tray, run `ollama serve` in a terminal.)

Optional: for a sharper report on a powerful GPU, pull a bigger model and pass it to the server:

```powershell
ollama pull llama3.1:70b
```
then start the server with `--llm-model llama3.1:70b` (append that flag to the command in `start_server.bat`).

## 3. Create your free HuggingFace token (speaker labels only)

1. Join at **https://huggingface.co/join**
2. Create a token at **https://huggingface.co/settings/tokens** — the default "read" scope is fine
3. Accept the model agreements by visiting (and clicking "Agree") on:
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0
4. Open `start_server.bat` in Notepad and replace `YOUR_HUGGINGFACE_TOKEN_HERE` on the `set HF_TOKEN=` line with your token. Save.

> Without the token everything still works — transcription and the AI report just won't have Speaker 1/2/3 labels (lines show "Speaker ?").

## 4. Run it

1. **Double-click `start_server.bat`** (leave the window open).
   - First start: models download (a few minutes), then you'll see `Server starting on http://127.0.0.1:8765`.
2. **Open `meeting-notes.html`** in Chrome or Edge (double-click the file).
3. Tap **⚙️** (top right) → **Test Connection** → should show a green check → **Save**.
4. Tap **New Meeting** → import your audio recording (and photos) → tap **🔊 Transcribe**.
5. Wait. large-v3 on CPU can take several minutes for a long meeting; the LLM report adds ~1–2 minutes. The status text tells you it's working.
6. Light-edit the result (fix names, map Speaker 1/2 to real people), fill title/attendees, **Save Meeting**.
7. **Export .docx** to share with superiors. **Export Markdown** for your archive.

---

## Typical meeting workflow

1. During the meeting: phone records audio + snaps whiteboard photos. Laptop presents. The app does nothing.
2. After the meeting: copy the audio + photos to the PC (or open the app on the phone — see below).
3. `start_server.bat` → open the app → New Meeting → import → **Transcribe**.
4. Review: speaker-labeled transcript, AI Report (summary/topics/conclusions/next steps), decisions, action items with owners + due dates.
5. Edit the few wrong names/numbers, add title/attendees, save, export.

## Using it on the phone

The app is fully usable in mobile Chrome (import, edit, save, export). Two modes:

- **Phone-only mode (no transcription):** open `meeting-notes.html` on the phone (e.g. from this repo via the live URL), import the recording + photos from the phone, type or paste a transcript, structure it, export `.docx` to the phone.
- **Phone + desktop transcription:** run `start_server.bat` on the desktop, then on the phone tap ⚙️ and set the server URL to your desktop's LAN address (e.g. `http://192.168.1.20:8765`) — both devices must be on the same Wi-Fi. Large uploads take a while over Wi-Fi. (Note: Windows Firewall may prompt on first connection from the phone — allow it.)

Moving a finished note between devices: **Export Note** on one device → **Import Note** on the other.

## What the "intelligence" does — and its limits

- **Speaker labels** are acoustic (pyannote). Consistent per recording but *unlabeled* — you map Speaker 1 = Jane in the transcript text.
- **AI Report** (with Ollama running) is real understanding from a local LLM: executive summary, conclusions, next-meeting expectations. It will still occasionally mis-hear names or over/under-state a decision — **always review before sending to superiors.**
- **Without Ollama** the server falls back to keyword/pattern extraction: a rough first draft.

## Troubleshooting

| Problem | Fix |
|---|---|
| `ffmpeg: command not found` | `winget install Gyan.FFmpeg`, then open a *new* terminal |
| `pip: command not found` | Use `python -m pip install ...` or `py -m pip install ...` |
| App can't reach server | Is `start_server.bat`'s window still open? Does "Server starting" appear? Tap ⚙️ → Test Connection |
| Transcribe hangs with no status | CPU transcription is slow — large-v3 can take 10× real-time on CPU. Smaller meeting or `--model medium` in the bat file speeds it up |
| No speaker labels | HF token not set (server line says "No HuggingFace token"), or you didn't accept the model agreements, or you're running with `--no-diarization` |
| No AI Report / "LLM failed" in logs | Ollama not running (tray icon), or model not pulled (`ollama pull llama3.1:8b`) |
| Ollama first call is very slow | First inference loads the model into RAM — one-time ~30s; subsequent calls are faster |
| Phone can't reach desktop server | Same Wi-Fi? Desktop LAN IP correct (check `ipconfig`)? Allow Python in Windows Firewall when prompted |
| `.docx` won't open | Use a current Chrome/Edge; the DOCX generator uses modern browser APIs |

## Data & privacy

- Notes live in your browser's IndexedDB per device. Clearing browser data clears notes — use **Export Note** as backup if you want copies.
- Audio, transcripts, and reports never leave your machine. The only network traffic is one-time model downloads (HuggingFace, Ollama) and — if you use phone mode — the audio upload to your *own* desktop.

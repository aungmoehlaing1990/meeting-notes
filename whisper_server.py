#!/usr/bin/env python3
"""
Local Whisper Transcription Server with Speaker Diarization
============================================================
Runs OpenAI Whisper (large-v3) + pyannote.audio speaker diarization locally.

What it does:
  - Accepts an audio file upload
  - Transcribes with Whisper (large-v3 by default)
  - Runs speaker diarization (pyannote) to label Speaker 1, Speaker 2, ...
  - Merges speaker labels into the transcript
  - Heuristically extracts: decisions, action items, topics, next steps

Requirements (system):
  - ffmpeg (must be on PATH) — required by both Whisper and pyannote
  - Python 3.11+

Python packages:
  pip install flask openai-whisper pyannote.audio

HuggingFace token (free):
  - pyannote models require a HuggingFace token (even though they are free).
  - Get one at https://huggingface.co/settings/tokens (select "read" scope).
  - Accept the user agreement for pyannote/speaker-diarization-3.1 on the model page.
  - Pass it via --hf-token or set the HF_TOKEN environment variable.

Run:
  python whisper_server.py --hf-token YOUR_TOKEN
  # or
  HF_TOKEN=your_token python whisper_server.py

The server starts on http://localhost:8765 by default.

Endpoints:
  GET  /health              -> {"status": "ok", "models_loaded": true}
  POST /transcribe         -> multipart form, field "audio"
                             -> {"success":true, "transcript_with_speakers":..., ...}
"""

import os
import sys
import io
import json
import tempfile
import argparse
import logging
import urllib.request
from threading import Lock

# ----------------------------------------------------------------------
# FFmpeg shared libraries
# pyannote's torchcodec audio decoder needs FFmpeg's shared DLLs
# (avcodec-XX.dll etc.) on PATH, not just the ffmpeg.exe binary.
# If a bundled ffmpeg\bin dir sits next to this script, put it on PATH.
# ----------------------------------------------------------------------
_ffmpeg_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg", "bin")
if os.path.isdir(_ffmpeg_bin) and _ffmpeg_bin not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _ffmpeg_bin + os.pathsep + os.environ.get("PATH", "")
    print(f"[setup] Added bundled FFmpeg to PATH: {_ffmpeg_bin}")

from flask import Flask, request, jsonify

import whisper

try:
    from pyannote.audio import Pipeline
    HAVE_PYANNOTE = True
except ImportError:
    Pipeline = None
    HAVE_PYANNOTE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("whisper_server")

app = Flask(__name__)

# ----------------------------------------------------------------------
# Model state (loaded once at startup)
# ----------------------------------------------------------------------
whisper_model = None
diarization_pipeline = None
MODEL_NAME = "large-v3"
LLM_ENABLED = False
LLM_URL = ""
LLM_MODEL = ""


def load_models(model_name: str, hf_token: str, no_diarization: bool = False):
    global whisper_model, diarization_pipeline
    log.info("Loading Whisper model: %s ...", model_name)
    whisper_model = whisper.load_model(model_name)
    log.info("Whisper model loaded: %s", model_name)

    if no_diarization:
        log.info("Diarization disabled by flag.")
        return
    if not HAVE_PYANNOTE:
        log.warning("pyannote.audio not installed — speaker labels disabled.")
        return
    if not hf_token:
        log.warning("No HuggingFace token — speaker labels disabled (models need auth).")
        return

    log.info("Loading pyannote speaker-diarization pipeline ...")
    try:
        # pyannote.audio 4.x renamed use_auth_token -> token
        diarization_pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=hf_token,
        )
    except TypeError:
        diarization_pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )
    log.info("Speaker-diarization pipeline loaded.")


# ----------------------------------------------------------------------
# Speaker + transcript merging
# ----------------------------------------------------------------------
def merge_speakers(transcription_result, diarization, audio_path: str):
    """
    Whisper gives segments with [start, end, text].
    pyannote gives speaker turns with [start, end, speaker].
    For each Whisper segment, pick the dominant speaker.
    Returns list of dicts: {speaker_label, text, start, end}.
    """
    segments = transcription_result.get("segments", [])
    if not segments:
        return []

    out = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start, end = float(seg["start"]), float(seg["end"])

        # speakers active during this segment (if diarization available)
        speaker_label = "Speaker ?"
        if diarization is not None:
            try:
                from pyannote.core import Segment
                seg_diag = diarization.crop(Segment(start, end))
                speaker_dur = {}
                for turn, _track, label in seg_diag.itertracks(yield_label=True):
                    dur = float(turn.end) - float(turn.start)
                    speaker_dur[label] = speaker_dur.get(label, 0.0) + dur
                if speaker_dur:
                    dominant = max(speaker_dur, key=speaker_dur.get)
                    speaker_label = _pretty_speaker(dominant)
            except Exception as exc:
                log.warning("Speaker crop failed for segment [%s-%s]: %s", start, end, exc)

        out.append({
            "speaker_label": speaker_label,
            "text": text,
            "start": start,
            "end": end,
        })
    return out


def _pretty_speaker(label: str) -> str:
    """Turn 'SPEAKER_00' into 'Speaker 1', keep unknown labels as-is."""
    if label is None:
        return "Speaker ?"
    label = str(label).strip()
    if label.upper().startswith("SPEAKER_"):
        suffix = label[len("SPEAKER_"):].strip()
        try:
            n = int(suffix)
            return f"Speaker {n + 1}"
        except ValueError:
            return f"Speaker {suffix}"
    return label


# ----------------------------------------------------------------------
# Heuristic insight extraction
# ----------------------------------------------------------------------
def extract_insights(segments):
    """
    Heuristics over the speaker-labeled segments.

    Returns:
      decisions   - list of sentences that look like decisions/conclusions
      action_items - list of sentences that look like action assignments
      topics      - rough topic segments detected from discourse cues
      next_steps  - sentences referencing future follow-up / next meeting
    """
    decisions = []
    action_items = []
    topics = []
    next_steps = []

    # Collect sentences (split on sentence boundaries)
    sentences = []
    for s in segments:
        text = s["text"]
        for part in _split_sentences(text):
            part = part.strip()
            if part:
                sentences.append(part)

    decision_kw = [
        "decide", "decided", "decision", "agreed", "agreement",
        "conclusion", "concluded", "resolved", "resolve",
        "final", "finalize", "finalized", "approved", "rejected",
        "confirmed", "confirm", "determined", "determine",
        "voted", "vote", "consensus", "unanimous",
    ]
    action_kw = [
        "action item", "action items", "will do", "i will", "he will",
        "she will", "they will", "we will", "will handle", "will take",
        "will follow", "will provide", "will send", "will prepare",
        "owner:", "responsible:", "assigned to", "owning",
        "task", "todo", "to-do", "follow up", "follow-up",
        "take care of", "responsible for", "in charge of",
    ]
    next_kw = [
        "next meeting", "next time", "next session", "next week",
        "next sprint", "next quarter", "future meeting", "upcoming",
        "follow up", "follow-up", "revisit", "revisit",
        "in the next", "will meet", "scheduled", "carried over",
        "carry over", "deferred", "parked", "save for",
        "agenda for", "agenda of", "discuss further",
    ]
    topic_kw = [
        "topic:", "agenda item", "regarding", "about the",
        "discussed", "we discussed", "we talked", "talking about",
        "the issue of", "the matter of", "on the subject",
        "moving on", "next topic", "the next item",
    ]

    # Determine a per-sentence "topic" by tracking topic-shift cues.
    current_topic = "General Discussion"
    topic_seen = set()

    for sent in sentences:
        s_low = sent.lower()

        # Topic shifts
        for kw in topic_kw:
            if kw in s_low:
                rest = s_low.split(kw, 1)[1] if kw in s_low else ""
                topic = rest.strip().rstrip(".,;:!?")
                if topic and len(topic) < 120:
                    current_topic = topic
                    if current_topic not in topic_seen:
                        topic_seen.add(current_topic)
                        topics.append(current_topic)
                break

        # Decisions
        if any(k in s_low for k in decision_kw):
            decisions.append(sent)

        # Action items
        if any(k in s_low for k in action_kw):
            action_items.append(sent)

        # Next steps
        if any(k in s_low for k in next_kw):
            next_steps.append(sent)

    # Deduplicate while preserving order
    def dedup(lst):
        seen = set()
        out = []
        for it in lst:
            k = it.strip().lower()
            if k and k not in seen:
                seen.add(k)
                out.append(it.strip())
        return out

    return {
        "decisions": dedup(decisions),
        "action_items": dedup(action_items),
        "topics": topics if topics else ["General Discussion"],
        "next_steps": dedup(next_steps),
    }


def _split_sentences(text: str):
    """Very rough sentence splitter. Good enough for extraction heuristics."""
    parts = []
    for chunk in text.replace("\n", " ").split(". "):
        chunk = chunk.strip()
        if not chunk:
            continue
        # Re-attach the period for cleaner sentences
        parts.append(chunk if chunk.endswith(".") else chunk + ".")
    return parts


# ----------------------------------------------------------------------
# Local LLM (Ollama, OpenAI-compatible) — professional-grade summary
# ----------------------------------------------------------------------
def llm_summarize(transcript_with_speakers: str):
    """
    Calls the configured local LLM (Ollama's /v1/chat/completions) to produce
    a structured JSON summary of the meeting. Returns a dict with:
      summary, topics, decisions, action_items, conclusions, next_steps, notes
    Returns None on any failure (caller falls back to heuristics).
    """
    if not LLM_ENABLED or not LLM_URL:
        return None
    prompt = (
        "You are a professional meeting note taker and report writer. "
        "Given the speaker-labeled transcript of a meeting, produce a concise, "
        "accurate JSON summary. Do NOT invent details that are not in the "
        "transcript. Output ONLY valid JSON, no markdown fences, in exactly "
        "this shape:\n"
        "{\n"
        '  "summary": "2-4 sentence executive summary of the meeting",\n'
        '  "topics": ["topic 1", "topic 2"],\n'
        '  "decisions": ["decision 1", "decision 2"],\n'
        '  "action_items": [{"task": "...", "owner": "... or empty", "due": "... or empty"}],\n'
        '  "conclusions": ["conclusion 1"],\n'
        '  "next_steps": ["what is expected / to be discussed next meeting"]\n'
        "}\n\n"
        "Transcript:\n"
        + transcript_with_speakers[:60000]  # safety cap
    )
    try:
        payload = json.dumps({
            "model": LLM_MODEL,
            "messages": [
                {"role": "system",
                 "content": "You are a precise meeting scribe. Respond with valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            LLM_URL.rstrip("/") + "/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        return _parse_json_loose(content)
    except Exception as exc:
        log.warning("LLM summarization failed (falling back to heuristics): %s", exc)
        return None


def _parse_json_loose(text: str):
    """Extract a JSON object from model output even if wrapped in fences/prose."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def health_info():
    return {
        "status": "ok",
        "models_loaded": whisper_model is not None,
        "model": MODEL_NAME,
        "diarization": diarization_pipeline is not None,
        "llm": LLM_ENABLED,
        "llm_model": LLM_MODEL if LLM_ENABLED else None,
    }


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------
@app.route("/health")
def health():
    return jsonify(health_info())


@app.route("/transcribe", methods=["POST"])
def transcribe():
    if whisper_model is None:
        return jsonify({
            "success": False,
            "error": "Models not loaded yet. Wait for the server to finish starting.",
            "ready": False,
        }), 503

    if "audio" not in request.files:
        return jsonify({
            "success": False,
            "error": "No audio file provided. Send the file as the 'audio' field.",
        }), 400

    file = request.files["audio"]
    if not file.filename:
        return jsonify({
            "success": False,
            "error": "Empty filename.",
        }), 400

    suffix = os.path.splitext(file.filename)[1] or ".wav"
    # Whisper + pyannote both need a real file on disk (ffmpeg-based).
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(file.read())
        tmp.close()
        audio_path = tmp.name

        log.info("Transcribing %s (model=%s) ...", file.filename, MODEL_NAME)
        whisper_result = whisper_model.transcribe(audio_path, fp16=False)

        diarization = None
        if diarization_pipeline is not None:
            log.info("Running speaker diarization ...")
            _diag_out = diarization_pipeline(audio_path)
            # pyannote 4.x returns a DiarizeOutput holding Annotations; 3.x returned an Annotation.
            if hasattr(_diag_out, "speaker_diarization") and hasattr(_diag_out, "exclusive_speaker_diarization"):
                diarization = _diag_out.speaker_diarization
            elif hasattr(_diag_out, "crop"):
                diarization = _diag_out
            else:
                diarization = _diag_out
        else:
            log.info("Diarization disabled — transcript will have no speaker labels.")

        merged = merge_speakers(whisper_result, diarization, audio_path)
        transcript_with_speakers = "\n".join(
            f"{m['speaker_label']}: {m['text']}" for m in merged
        )
        raw_transcript = (whisper_result.get("text") or "").strip()

        insights = extract_insights(merged)
        speakers = list(dict.fromkeys(m["speaker_label"] for m in merged))

        # LLM pass (if enabled) — overrides heuristics when it succeeds
        llm_data = llm_summarize(transcript_with_speakers)
        summary_mode = "llm" if llm_data else "heuristic"

        return jsonify({
            "success": True,
            "transcript_with_speakers": transcript_with_speakers,
            "raw_transcript": raw_transcript,
            "speakers": speakers,
            "decisions": (llm_data or {}).get("decisions") or insights["decisions"],
            "action_items": (llm_data or {}).get("action_items") or insights["action_items"],
            "topics": (llm_data or {}).get("topics") or insights["topics"],
            "next_steps": (llm_data or {}).get("next_steps") or insights["next_steps"],
            "summary": (llm_data or {}).get("summary", ""),
            "conclusions": (llm_data or {}).get("conclusions", []),
            "summary_mode": summary_mode,
            "segments_count": len(merged),
            "duration_seconds": float(whisper_result.get("duration", 0)) or (merged[-1]["end"] if merged else 0),
        })

    except Exception as exc:
        log.error("Transcription failed: %s", exc, exc_info=True)
        return jsonify({
            "success": False,
            "error": str(exc),
            "type": type(exc).__name__,
        }), 500

    finally:
        try:
            os.unlink(audio_path)
        except Exception:
            pass


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
def main():
    global MODEL_NAME
    parser = argparse.ArgumentParser(
        description="Local Whisper + speaker-diarization transcription server"
    )
    parser.add_argument(
        "--model", default=MODEL_NAME,
        help=f"Whisper model name (default: {MODEL_NAME})"
    )
    parser.add_argument(
        "--port", type=int, default=8765,
        help="Port to listen on (default: 8765)"
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Bind host (default: 127.0.0.1 — localhost only)"
    )
    parser.add_argument(
        "--hf-token", default=os.environ.get("HF_TOKEN", ""),
        help="HuggingFace token for pyannote models (or set HF_TOKEN env var)"
    )
    parser.add_argument(
        "--no-diarization", action="store_true",
        help="Disable speaker diarization (faster; no speaker labels)"
    )
    parser.add_argument(
        "--llm", action="store_true",
        help="Enable local LLM (Ollama) for professional-grade summary"
    )
    parser.add_argument(
        "--llm-url", default="http://localhost:11434/v1",
        help="OpenAI-compatible LLM base URL (default: Ollama at http://localhost:11434/v1)"
    )
    parser.add_argument(
        "--llm-model", default="llama3.1:8b",
        help="LLM model name to pass to the endpoint (default: llama3.1:8b)"
    )
    args = parser.parse_args()

    global LLM_ENABLED, LLM_URL, LLM_MODEL, diarization_pipeline
    if args.llm:
        LLM_ENABLED = True
        LLM_URL = args.llm_url
        LLM_MODEL = args.llm_model
        log.info("LLM enabled: %s (model=%s)", LLM_URL, LLM_MODEL)

    if not args.hf_token:
        log.warning(
            "No HuggingFace token provided. Speaker diarization will likely fail "
            "unless --no-diarization is set. Get a free token at "
            "https://huggingface.co/settings/tokens and pass it with --hf-token."
        )
        if not args.no_diarization:
            log.warning(
                "Set --no-diarization to skip speaker labels, or pass --hf-token."
            )

    MODEL_NAME = args.model

    try:
        load_models(args.model, args.hf_token, no_diarization=args.no_diarization)
    except Exception as exc:
        log.error("Failed to load models: %s", exc, exc_info=True)
        if not args.no_diarization:
            log.error(
                "Speaker diarization failed. Try --no-diarization, or check your "
                "HuggingFace token and internet connection (models download once)."
            )
        # Continue without diarization if Whisper loaded
        if whisper_model is None:
            log.error("Whisper also failed to load. Exiting.")
            sys.exit(1)
        log.warning("Continuing with transcription only (no diarization).")
        diarization_pipeline = None

    log.info(
        "Server starting on http://%s:%d  (model=%s, diarization=%s)",
        args.host, args.port, args.model, "ready" if diarization_pipeline is not None else "disabled"
    )
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()

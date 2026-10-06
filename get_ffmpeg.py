"""Get FFmpeg shared libraries for the meeting-notes transcription server.

pyannote speaker diarization uses torchcodec to decode audio, and torchcodec's
bundled core libraries link against FFmpeg's SHARED DLLs (avcodec-63.dll,
avformat-63.dll, etc.). A static FFmpeg build (the default from `winget install
Gyan.FFmpeg`) does NOT provide these — so the server will fail with "Could not
load libtorchcodec_core..." unless you install shared libraries.

This script downloads the official BtbN FFmpeg-Builds shared build (~90 MB)
and extracts just the DLLs (plus ffmpeg.exe / ffprobe.exe) into ./ffmpeg/bin,
right next to whisper_server.py. One-time setup, no admin rights needed.
"""
import os, sys, zipfile, urllib.request

HOME = os.path.dirname(os.path.abspath(__file__))
URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl-shared.zip"
DEST = os.path.join(HOME, "ffmpeg", "bin")
ZIP = os.path.join(os.environ.get("TMPDIR", os.environ.get("TEMP", ".")), "ffmpeg-shared.zip")

def main():
    os.makedirs(DEST, exist_ok=True)
    print(f"Downloading FFmpeg shared build (~90 MB) ...", flush=True)
    def prog(block, bs, total):
        pct = block * bs / total if total else 0
        print(f"\r{pct:5.1f}%  {block*bs/1e6:.0f} / {total/1e6:.0f} MB", end="", flush=True)
    urllib.request.urlretrieve(URL, ZIP, prog)
    print("\nExtracting shared DLLs to ffmpeg/bin ...\n", flush=True)

    with zipfile.ZipFile(ZIP) as z:
        root = z.namelist()[0].split("/")[0]
        bin_prefix = f"{root}/bin/"
        for name in z.namelist():
            if name.startswith(bin_prefix) and not name.endswith("/"):
                with z.open(name) as src, open(os.path.join(DEST, os.path.basename(name)), "wb") as dst:
                    dst.write(src.read())
    os.remove(ZIP)
    dlls = sorted(f for f in os.listdir(DEST) if f.endswith(".dll"))
    print(f"Done. {len(dlls)} DLLs in {DEST}:\n  " + "\n  ".join(dlls))
    print("\nYou can now run: python whisper_server.py --hf-token YOUR_TOKEN")

if __name__ == "__main__":
    main()

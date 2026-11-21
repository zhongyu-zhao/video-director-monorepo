"""Optional ASR adapter.

The default evidence path uses ffmpeg silence/loudness events and does
not require a speech model.  Set ``--asr`` and install ``faster-whisper``
to add transcripts; the transcript is pinned to shot times.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any


class AsrUnavailable(RuntimeError):
    """Raised when the optional speech model is not installed."""


def transcribe(path: str | Path, model_size: str = "small") -> list[dict[str, Any]]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise AsrUnavailable("faster-whisper is not installed; install the asr extra") from error

    if not shutil.which("ffmpeg"):
        raise AsrUnavailable("ffmpeg is required to decode audio for ASR")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    with tempfile.TemporaryDirectory(prefix="auto-shot-asr-") as directory:
        wav = Path(directory) / "audio.wav"
        completed = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                str(wav),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0 or not wav.is_file():
            detail = (completed.stderr or "").strip().splitlines()
            raise AsrUnavailable(f"cannot decode audio: {detail[-1] if detail else 'ffmpeg failed'}")
        try:
            import numpy as np
        except ImportError as error:
            raise AsrUnavailable("numpy is required for ASR") from error
        with wave.open(str(wav), "rb") as handle:
            frames = handle.readframes(handle.getnframes())
        audio = np.frombuffer(frames, dtype=np.int16).astype("float32") / 32768.0
        segments, _info = model.transcribe(audio, vad_filter=True)
        return [
            {
                "start": round(float(segment.start), 3),
                "end": round(float(segment.end), 3),
                "text": segment.text.strip(),
            }
            for segment in segments
        ]

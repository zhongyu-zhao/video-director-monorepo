"""Read media facts with ffprobe.

Timecodes, durations and frame rates are facts.  They must never be
reported by a language model; this module is the only writer of those
fields in the shot table.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .models import MediaInfo


class ProbeError(RuntimeError):
    """Raised when ffprobe is unavailable or cannot read the input."""


def probe(path: str | Path) -> MediaInfo:
    source = Path(path)
    if not source.is_file():
        raise ProbeError(f"input not found: {source}")

    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "--",
        str(source),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as error:
        raise ProbeError("ffprobe not found; install ffmpeg (it bundles ffprobe)") from error

    if completed.returncode != 0:
        detail = _last_line(completed.stderr)
        raise ProbeError(f"ffprobe failed for {source}: {detail}")

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ProbeError(f"ffprobe returned invalid JSON for {source}") from error

    video = _first_video_stream(payload)
    if video is None:
        raise ProbeError(f"no video stream found in {source}")

    duration = _pick_float(
        payload.get("format", {}).get("duration"),
        video.get("duration"),
    )
    if duration is None or duration <= 0:
        raise ProbeError(f"cannot determine positive duration for {source}")

    return MediaInfo(
        path=str(source),
        duration=duration,
        fps=_parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate")),
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        has_audio=any(stream.get("codec_type") == "audio" for stream in payload.get("streams", [])),
    )


def _first_video_stream(payload: dict[str, Any]) -> dict[str, Any] | None:
    for stream in payload.get("streams", []):
        if stream.get("codec_type") != "video":
            continue
        if stream.get("disposition", {}).get("attached_pic"):
            continue
        return stream
    return None


def _pick_float(*values: Any) -> float | None:
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def _parse_rate(value: Any) -> float:
    if not value or not isinstance(value, str):
        return 0.0
    numerator, _, denominator = value.partition("/")
    try:
        top = float(numerator)
        bottom = float(denominator) if denominator else 1.0
    except ValueError:
        return 0.0
    if bottom == 0:
        return 0.0
    return round(top / bottom, 3)


def _last_line(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else "unknown ffprobe error"

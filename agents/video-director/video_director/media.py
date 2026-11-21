"""Thin ffmpeg/ffprobe boundary for the deterministic kernel."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class MediaError(RuntimeError):
    """Raised when ffmpeg/ffprobe is unavailable or a media file is invalid."""


@dataclass(frozen=True)
class MediaFacts:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def probe_media(path: str | Path) -> MediaFacts:
    source = Path(path)
    if not source.is_file():
        raise MediaError(f"media file not found: {source}")

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
        raise MediaError("ffprobe not found; install ffmpeg") from error

    if completed.returncode != 0:
        raise MediaError(f"ffprobe failed for {source}: {_last_line(completed.stderr)}")

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise MediaError(f"ffprobe returned invalid JSON for {source}") from error

    video = _first_video_stream(payload)
    if video is None:
        raise MediaError(f"no video stream found in {source}")

    duration = _pick_float(payload.get("format", {}).get("duration"), video.get("duration"))
    if duration is None:
        raise MediaError(f"cannot determine duration for {source}")

    return MediaFacts(
        duration=duration,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=_parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate")),
        has_audio=any(stream.get("codec_type") == "audio" for stream in payload.get("streams", [])),
    )


def run_ffmpeg(command: list[str]) -> None:
    """Run ffmpeg and raise an actionable error on failure."""

    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as error:
        raise MediaError("ffmpeg not found; install ffmpeg") from error
    if completed.returncode != 0:
        raise MediaError(f"ffmpeg failed: {_last_line(completed.stderr)}")


def _first_video_stream(payload: dict) -> dict | None:
    for stream in payload.get("streams", []):
        if stream.get("codec_type") != "video":
            continue
        if stream.get("disposition", {}).get("attached_pic"):
            continue
        return stream
    return None


def _pick_float(*values: object) -> float | None:
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def _parse_rate(value: object) -> float:
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
    return lines[-1] if lines else "unknown ffmpeg error"

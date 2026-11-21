"""Test helpers: synthetic videos and small shot-table fixtures."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from auto_shot.models import DetectorInfo, MediaInfo, ShotTable


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def make_color_video(
    path: Path,
    colors: tuple[str, ...] = ("black", "white", "red"),
    seconds: float = 2.0,
    width: int = 320,
    height: int = 240,
    fps: int = 25,
) -> Path:
    """Create a hard-cut test video with one solid colour per segment."""

    inputs: list[str] = []
    for color in colors:
        inputs.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s={width}x{height}:d={seconds}:r={fps}",
            ]
        )
    concat = "".join(f"[{index}:v]" for index in range(len(colors)))
    filter_complex = f"{concat}concat=n={len(colors)}:v=1:a=0,format=yuv420p[v]"
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "23",
        str(path),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    return path


def sample_table() -> ShotTable:
    return ShotTable(
        video=MediaInfo(
            path="sample.mp4",
            duration=6.0,
            fps=25.0,
            width=320,
            height=240,
            has_audio=False,
        ),
        detector=DetectorInfo(name="ffmpeg-scene", threshold=0.25),
        shots=[],
    )

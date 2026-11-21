"""Shot-boundary detection.

Milestone 0 uses ffmpeg's built-in scene score as a deliberately simple,
dependency-free baseline.  It is a *candidate generator*, not the final
detector: it compares adjacent frames and is weak on dissolves, colour-
only cuts and flash frames.  Later milestones add ML detectors behind
the same function.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import round_time

_PTS_TIME = re.compile(r"pts_time:\s*([-+0-9.eE]+)")
_SCENE_SCORE = re.compile(r"lavfi\.scene_score=([-+0-9.eE]+)")


class DetectError(RuntimeError):
    """Raised when ffmpeg is unavailable or shot detection fails."""


@dataclass(frozen=True)
class Cut:
    time: float
    score: float | None = None


def detect_cuts(path: str | Path, threshold: float = 0.3) -> list[Cut]:
    if not 0.0 < threshold <= 1.0:
        raise ValueError("threshold must be in (0.0, 1.0]")

    source = Path(path)
    if not source.is_file():
        raise DetectError(f"input not found: {source}")

    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "info",
        "-i",
        str(source),
        "-an",
        "-vf",
        f"select='gt(scene,{threshold})',metadata=print",
        "-f",
        "null",
        "-",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as error:
        raise DetectError("ffmpeg not found; install ffmpeg (it bundles ffprobe)") from error

    if completed.returncode != 0:
        detail = _last_line(completed.stderr)
        raise DetectError(f"ffmpeg scene detection failed for {source}: {detail}")

    return _parse_cuts(completed.stderr)


def _parse_cuts(stderr: str) -> list[Cut]:
    cuts: list[Cut] = []
    current_time: float | None = None
    for line in stderr.splitlines():
        time_match = _PTS_TIME.search(line)
        if time_match:
            try:
                current_time = round_time(float(time_match.group(1)))
            except ValueError:
                current_time = None

        score_match = _SCENE_SCORE.search(line)
        if score_match and current_time is not None:
            try:
                score: float | None = round(float(score_match.group(1)), 3)
            except ValueError:
                score = None
            cuts.append(Cut(time=current_time, score=score))
            current_time = None

    return cuts


def _last_line(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else "unknown ffmpeg error"

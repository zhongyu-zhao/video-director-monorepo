"""Test helpers: synthetic clips and project fixtures."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from video_director.models import Asset, Project, Timeline, TimelineClip
from video_director.project import create_project


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def make_solid_clip(
    path: Path,
    color: str = "black",
    seconds: float = 2.0,
    width: int = 320,
    height: int = 180,
    fps: int = 25,
) -> Path:
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s={width}x{height}:d={seconds}:r={fps}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    return path


def blank_project(root: Path, clip_paths: tuple[str, ...] = ("assets/a.mp4", "assets/b.mp4")) -> Project:
    """Create a project with placeholder asset files (no ffmpeg required)."""

    project = create_project(root, "test project", fps=25.0, width=320, height=180, project_id="proj-test")
    for index, relative in enumerate(clip_paths, start=1):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"placeholder")
        project.assets.append(Asset(id=f"A{index:03d}", path=relative, duration=2.0))
    return project


def project_with_clips(root: Path) -> Project:
    project = blank_project(root)
    project.timeline = Timeline(
        clips=[
            TimelineClip(id="C001", asset_id="A001", start=0.0, source_in=0.0, source_out=2.0),
            TimelineClip(id="C002", asset_id="A002", start=2.0, source_in=0.0, source_out=2.0),
        ]
    )
    project.revision = 1
    return project

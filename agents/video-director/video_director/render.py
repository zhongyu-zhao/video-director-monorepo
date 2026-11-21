"""Deterministic single-track renderer.

M0 deliberately supports only video clips on one continuous track: each
clip is trimmed and normalised to the project resolution/fps, then the
segments are concatenated losslessly.  Audio, transitions, overlays and
multi-track composition belong to later schema versions.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .media import MediaError, MediaFacts, ffmpeg_available, probe_media, run_ffmpeg
from .models import Project
from .project import resolve_asset_path
from .validate import FAIL, PASS, SKIP, Check, validate_project

RENDER_REPORT = "render_report.json"


class RenderError(RuntimeError):
    """Raised when a project cannot be rendered or ffmpeg fails."""


@dataclass(frozen=True)
class RenderReport:
    project_revision: int
    output: str
    clip_count: int
    expected_duration: float
    actual_duration: float
    width: int
    height: int
    fps: float
    checks: list[Check]
    schema_version: int = 1

    @property
    def ok(self) -> bool:
        return all(check.status != FAIL for check in self.checks)

    def counts(self) -> dict[str, int]:
        return {
            PASS: sum(1 for check in self.checks if check.status == PASS),
            FAIL: sum(1 for check in self.checks if check.status == FAIL),
            SKIP: sum(1 for check in self.checks if check.status == SKIP),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_revision": self.project_revision,
            "output": self.output,
            "clip_count": self.clip_count,
            "expected_duration": round(self.expected_duration, 3),
            "actual_duration": round(self.actual_duration, 3),
            "width": self.width,
            "height": self.height,
            "fps": round(self.fps, 3),
            "ok": self.ok,
            "checks": [check.to_dict() for check in self.checks],
        }


def render_project(
    project: Project,
    root: str | Path,
    output: str | Path | None = None,
) -> RenderReport:
    base = Path(root)
    validation = validate_project(project, base)
    if not validation.ok:
        failed = ", ".join(check.id for check in validation.failed)
        raise RenderError(f"project validation failed: {failed}")
    if not project.timeline.clips:
        raise RenderError("timeline is empty; add at least one clip")
    if not ffmpeg_available():
        raise RenderError("ffmpeg/ffprobe not found; install ffmpeg")

    for clip in project.timeline.clips:
        asset = project.asset(clip.asset_id)
        if asset is None:
            raise RenderError(f"clip {clip.id} references unknown asset {clip.asset_id}")
        if asset.kind != "video":
            raise RenderError(f"asset {asset.id} has unsupported kind '{asset.kind}' for M0 rendering")

    destination = Path(output) if output is not None else base / "renders" / f"render-r{project.revision:03d}.mp4"
    destination.parent.mkdir(parents=True, exist_ok=True)

    work = Path(tempfile.mkdtemp(prefix=".render-", dir=destination.parent))
    try:
        segments = _encode_segments(project, base, work)
        _concat_segments(segments, work / "concat.txt", destination)
        report = _verify(project, base, destination)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    report_path = base / "renders" / RENDER_REPORT
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def _encode_segments(project: Project, root: Path, work: Path) -> list[Path]:
    segments: list[Path] = []
    for index, clip in enumerate(project.timeline.clips):
        asset = project.asset(clip.asset_id)
        if asset is None:
            raise RenderError(f"clip {clip.id} references unknown asset {clip.asset_id}")
        source = resolve_asset_path(root, asset)
        segment = work / f"segment-{index:03d}.mp4"
        filter_graph = (
            f"scale={project.width}:{project.height}:force_original_aspect_ratio=decrease,"
            f"pad={project.width}:{project.height}:(ow-iw)/2:(oh-ih)/2,"
            f"setsar=1,fps={_number(project.fps)}"
        )
        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-ss",
            f"{clip.source_in:.3f}",
            "-i",
            str(source),
            "-t",
            f"{clip.duration:.3f}",
            "-an",
            "-vf",
            filter_graph,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(segment),
        ]
        run_ffmpeg(command)
        segments.append(segment)
    return segments


def _concat_segments(segments: list[Path], list_path: Path, output: Path) -> None:
    lines = []
    for segment in segments:
        escaped = str(segment.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )


def _verify(project: Project, root: Path, output: Path) -> RenderReport:
    if not output.is_file():
        raise RenderError(f"render output was not produced: {output}")
    try:
        facts = probe_media(output)
    except MediaError as error:
        raise RenderError(f"cannot verify render output: {error}") from error

    expected = round(sum(clip.duration for clip in project.timeline.clips), 3)
    tolerance = max(0.25, 2.0 / max(project.fps, 1.0))
    checks = [
        Check("output_exists", PASS, f"{_display_path(output, root)}"),
        Check("clip_count", PASS, f"{len(project.timeline.clips)} clips"),
        _duration_check(expected, facts.duration, tolerance),
        _resolution_check(project, facts),
        _fps_check(project.fps, facts.fps),
        Check("audio_track", SKIP, "audio is not rendered in M0"),
    ]
    return RenderReport(
        project_revision=project.revision,
        output=_display_path(output, root),
        clip_count=len(project.timeline.clips),
        expected_duration=expected,
        actual_duration=facts.duration,
        width=facts.width,
        height=facts.height,
        fps=facts.fps,
        checks=checks,
    )


def _duration_check(expected: float, actual: float, tolerance: float) -> Check:
    if abs(actual - expected) <= tolerance:
        return Check(
            "duration_matches",
            PASS,
            f"expected {expected:.3f}s, measured {actual:.3f}s",
        )
    return Check(
        "duration_matches",
        FAIL,
        f"expected {expected:.3f}s, measured {actual:.3f}s (tolerance {tolerance:.3f}s)",
    )


def _resolution_check(project: Project, facts: MediaFacts) -> Check:
    width = facts.width
    height = facts.height
    if (width, height) == (project.width, project.height):
        return Check("resolution_matches", PASS, f"{width}x{height}")
    return Check(
        "resolution_matches",
        FAIL,
        f"expected {project.width}x{project.height}, measured {width}x{height}",
    )


def _fps_check(expected: float, actual: float) -> Check:
    if abs(actual - expected) <= 0.5:
        return Check("fps_matches", PASS, f"expected {expected:.3f}, measured {actual:.3f}")
    return Check(
        "fps_matches",
        FAIL,
        f"expected {expected:.3f}, measured {actual:.3f}",
    )


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _number(value: float) -> str:
    return f"{value:g}"

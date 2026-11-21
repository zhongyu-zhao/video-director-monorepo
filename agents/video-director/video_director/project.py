"""Project storage and the small set of M0 editing operations."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from .media import MediaError, probe_media
from .models import Asset, Project, TimelineClip

PROJECT_FILE = "project.json"
PROJECT_DIRECTORIES = ("artifacts", "assets", "renders", "history")
_SOURCE_TOLERANCE = 0.05

_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


class ProjectError(RuntimeError):
    """Raised for invalid project operations or unreadable project files."""


def project_file(root: str | Path) -> Path:
    return Path(root) / PROJECT_FILE


def create_project(
    root: str | Path,
    title: str,
    fps: float = 25.0,
    width: int = 1920,
    height: int = 1080,
    project_id: str | None = None,
) -> Project:
    base = Path(root)
    target = project_file(base)
    if target.exists():
        raise ProjectError(f"project already exists: {target}")

    for name in PROJECT_DIRECTORIES:
        (base / name).mkdir(parents=True, exist_ok=True)

    project = Project(
        project_id=project_id or f"proj-{uuid.uuid4().hex[:8]}",
        title=title,
        fps=fps,
        width=width,
        height=height,
    )
    _persist(project, base)
    return project


def load_project(root: str | Path) -> Project:
    target = project_file(root)
    if not target.is_file():
        raise ProjectError(f"project not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ProjectError(f"invalid JSON in {target}: {error}") from error
    try:
        return Project.from_dict(payload)
    except (KeyError, TypeError, ValueError) as error:
        raise ProjectError(f"invalid project in {target}: {error}") from error


def save_project(project: Project, root: str | Path) -> Project:
    project.revision += 1
    _persist(project, Path(root))
    return project


def add_asset(
    project: Project,
    root: str | Path,
    source: str | Path,
    asset_id: str | None = None,
) -> Asset:
    source_path = Path(source)
    if not source_path.is_file():
        raise ProjectError(f"asset source not found: {source_path}")

    chosen_id = asset_id or _next_id("A", [asset.id for asset in project.assets])
    if project.asset(chosen_id) is not None:
        raise ProjectError(f"asset id already exists: {chosen_id}")

    destination = Path(root) / "assets" / f"{chosen_id}{source_path.suffix.lower()}"
    if destination.exists():
        raise ProjectError(f"asset file already exists: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination)

    kind = _kind_for(source_path)
    duration: float | None = None
    if kind == "video":
        try:
            duration = probe_media(destination).duration
        except MediaError as error:
            destination.unlink(missing_ok=True)
            raise ProjectError(f"cannot read video asset {source_path}: {error}") from error

    asset = Asset(
        id=chosen_id,
        path=destination.relative_to(Path(root)).as_posix(),
        kind=kind,
        duration=duration,
    )
    project.assets.append(asset)
    return asset


def add_clip(
    project: Project,
    asset_id: str,
    source_in: float,
    source_out: float,
    start: float | None = None,
    clip_id: str | None = None,
) -> TimelineClip:
    asset = project.asset(asset_id)
    if asset is None:
        raise ProjectError(f"unknown asset: {asset_id}")
    if source_in < 0:
        raise ProjectError("source_in must be >= 0")
    if source_out <= source_in:
        raise ProjectError("source_out must be greater than source_in")
    if asset.duration is not None and source_out > asset.duration + _SOURCE_TOLERANCE:
        raise ProjectError(
            f"source_out {source_out:.3f}s exceeds asset {asset_id} duration {asset.duration:.3f}s"
        )

    if start is None:
        start = (
            project.timeline.clips[-1].start + project.timeline.clips[-1].duration
            if project.timeline.clips
            else 0.0
        )
    if start < 0:
        raise ProjectError("start must be >= 0")

    chosen_id = clip_id or _next_id("C", [clip.id for clip in project.timeline.clips])
    if any(clip.id == chosen_id for clip in project.timeline.clips):
        raise ProjectError(f"clip id already exists: {chosen_id}")

    clip = TimelineClip(
        id=chosen_id,
        asset_id=asset_id,
        start=round(start, 3),
        source_in=round(source_in, 3),
        source_out=round(source_out, 3),
    )
    project.timeline.clips.append(clip)
    return clip


def resolve_asset_path(root: str | Path, asset: Asset) -> Path:
    relative = Path(asset.path)
    if relative.is_absolute():
        raise ProjectError(f"asset path must be relative: {asset.path}")

    base = Path(root).resolve()
    resolved = (base / relative).resolve()
    if resolved != base and base not in resolved.parents:
        raise ProjectError(f"asset path escapes the project directory: {asset.path}")
    return resolved


def _persist(project: Project, root: Path) -> None:
    text = json.dumps(project.to_dict(), ensure_ascii=False, indent=2) + "\n"
    target = project_file(root)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(target)

    history = root / "history" / f"project-r{project.revision:03d}.json"
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_text(text, encoding="utf-8")


def _next_id(prefix: str, existing: list[str]) -> str:
    highest = 0
    for value in existing:
        if not value.startswith(prefix):
            continue
        try:
            highest = max(highest, int(value[len(prefix) :]))
        except ValueError:
            continue
    return f"{prefix}{highest + 1:03d}"


def _kind_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _VIDEO_SUFFIXES:
        return "video"
    if suffix in _AUDIO_SUFFIXES:
        return "audio"
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    return "video"

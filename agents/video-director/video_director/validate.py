"""Project validation gates.

Rendering must never start with an invalid project.  A check can pass,
fail or be skipped; skipped checks are reported, never treated as a
pass.  The M0 kernel only knows a single video track.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import SCHEMA_VERSION, Project
from .project import ProjectError, resolve_asset_path

PASS = "pass"
FAIL = "fail"
SKIP = "skip"
_TIMELINE_TOLERANCE = 0.001
_SOURCE_TOLERANCE = 0.05


@dataclass(frozen=True)
class Check:
    id: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "status": self.status, "detail": self.detail}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Check:
        return cls(id=str(data["id"]), status=str(data["status"]), detail=str(data["detail"]))


@dataclass(frozen=True)
class ValidationReport:
    checks: list[Check]

    @property
    def ok(self) -> bool:
        return all(check.status != FAIL for check in self.checks)

    @property
    def failed(self) -> list[Check]:
        return [check for check in self.checks if check.status == FAIL]

    def counts(self) -> dict[str, int]:
        return {
            PASS: sum(1 for check in self.checks if check.status == PASS),
            FAIL: sum(1 for check in self.checks if check.status == FAIL),
            SKIP: sum(1 for check in self.checks if check.status == SKIP),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "checks": [check.to_dict() for check in self.checks]}


def validate_project(project: Project, root: str | Path) -> ValidationReport:
    checks = [
        _schema_version(project),
        _project_identity(project),
        _fps_positive(project),
        _resolution_positive(project),
        _resolution_even(project),
        _asset_ids_unique(project),
        _clip_ids_unique(project),
        _assets_exist(project, root),
        _asset_durations(project),
        _clip_assets_exist(project),
        _clip_ranges(project),
        _timeline_present(project),
        _timeline_starts_at_zero(project),
        _timeline_contiguous(project),
        _asset_kinds(project),
        Check("audio_track", SKIP, "audio is not rendered in M0"),
    ]
    return ValidationReport(checks=checks)


def _schema_version(project: Project) -> Check:
    if project.schema_version == SCHEMA_VERSION:
        return Check("schema_version", PASS, f"schema_version={SCHEMA_VERSION}")
    return Check(
        "schema_version",
        FAIL,
        f"expected {SCHEMA_VERSION}, got {project.schema_version}",
    )


def _project_identity(project: Project) -> Check:
    if project.project_id.strip() and project.title.strip():
        return Check("project_identity", PASS, f"{project.project_id} / {project.title}")
    return Check("project_identity", FAIL, "project_id and title must be non-empty")


def _fps_positive(project: Project) -> Check:
    if project.fps > 0:
        return Check("fps_positive", PASS, f"{project.fps:.3f}fps")
    return Check("fps_positive", FAIL, f"invalid fps: {project.fps}")


def _resolution_positive(project: Project) -> Check:
    if project.width > 0 and project.height > 0:
        return Check("resolution_positive", PASS, f"{project.width}x{project.height}")
    return Check(
        "resolution_positive",
        FAIL,
        f"invalid resolution: {project.width}x{project.height}",
    )


def _resolution_even(project: Project) -> Check:
    if project.width % 2 == 0 and project.height % 2 == 0:
        return Check("resolution_even", PASS, f"{project.width}x{project.height}")
    return Check(
        "resolution_even",
        FAIL,
        f"M0 renders yuv420p and needs even dimensions, got {project.width}x{project.height}",
    )


def _asset_ids_unique(project: Project) -> Check:
    ids = [asset.id for asset in project.assets]
    if len(ids) == len(set(ids)):
        return Check("asset_ids_unique", PASS, f"{len(ids)} asset ids")
    return Check("asset_ids_unique", FAIL, "duplicate asset ids")


def _clip_ids_unique(project: Project) -> Check:
    ids = [clip.id for clip in project.timeline.clips]
    if len(ids) == len(set(ids)):
        return Check("clip_ids_unique", PASS, f"{len(ids)} clip ids")
    return Check("clip_ids_unique", FAIL, "duplicate clip ids")


def _assets_exist(project: Project, root: str | Path) -> Check:
    if not project.assets:
        return Check("assets_exist", SKIP, "no assets")
    for asset in project.assets:
        try:
            path = resolve_asset_path(root, asset)
        except ProjectError as error:
            return Check("assets_exist", FAIL, str(error))
        if not path.is_file():
            return Check("assets_exist", FAIL, f"missing asset file: {asset.path}")
    return Check("assets_exist", PASS, f"{len(project.assets)} asset files exist")


def _asset_durations(project: Project) -> Check:
    known = [asset for asset in project.assets if asset.duration is not None]
    if not known:
        return Check("asset_durations", SKIP, "no asset durations recorded")
    for asset in known:
        if asset.duration is not None and asset.duration <= 0:
            return Check("asset_durations", FAIL, f"asset {asset.id} has invalid duration")
    if len(known) != len(project.assets):
        return Check(
            "asset_durations",
            SKIP,
            f"{len(project.assets) - len(known)} assets have no recorded duration",
        )
    return Check("asset_durations", PASS, f"{len(known)} durations are positive")


def _clip_assets_exist(project: Project) -> Check:
    if not project.timeline.clips:
        return Check("clip_assets_exist", SKIP, "no clips")
    for clip in project.timeline.clips:
        if project.asset(clip.asset_id) is None:
            return Check("clip_assets_exist", FAIL, f"clip {clip.id} references unknown asset {clip.asset_id}")
    return Check("clip_assets_exist", PASS, f"{len(project.timeline.clips)} clip references")


def _clip_ranges(project: Project) -> Check:
    if not project.timeline.clips:
        return Check("clip_ranges", SKIP, "no clips")
    for clip in project.timeline.clips:
        if clip.source_in < 0:
            return Check("clip_ranges", FAIL, f"clip {clip.id} has negative source_in")
        if clip.source_out <= clip.source_in:
            return Check("clip_ranges", FAIL, f"clip {clip.id} has empty source range")
        asset = project.asset(clip.asset_id)
        if (
            asset is not None
            and asset.duration is not None
            and clip.source_out > asset.duration + _SOURCE_TOLERANCE
        ):
            return Check(
                "clip_ranges",
                FAIL,
                f"clip {clip.id} ends at {clip.source_out:.3f}s beyond asset "
                f"{asset.id} duration {asset.duration:.3f}s",
            )
    return Check("clip_ranges", PASS, f"{len(project.timeline.clips)} source ranges")


def _timeline_present(project: Project) -> Check:
    if project.timeline.clips:
        return Check("timeline_present", PASS, f"{len(project.timeline.clips)} clips")
    return Check("timeline_present", SKIP, "timeline is empty (valid draft, not renderable)")


def _timeline_starts_at_zero(project: Project) -> Check:
    if not project.timeline.clips:
        return Check("timeline_starts_at_zero", SKIP, "no clips")
    start = project.timeline.clips[0].start
    if abs(start) <= _TIMELINE_TOLERANCE:
        return Check("timeline_starts_at_zero", PASS, "first clip starts at 0")
    return Check("timeline_starts_at_zero", FAIL, f"first clip starts at {start:.3f}s")


def _timeline_contiguous(project: Project) -> Check:
    if len(project.timeline.clips) < 2:
        return Check("timeline_contiguous", SKIP, "fewer than two clips")
    for previous, current in zip(project.timeline.clips, project.timeline.clips[1:]):
        expected = previous.start + previous.duration
        if abs(current.start - expected) > _TIMELINE_TOLERANCE:
            return Check(
                "timeline_contiguous",
                FAIL,
                f"{current.id} starts at {current.start:.3f}s, expected {expected:.3f}s "
                f"(gap or overlap after {previous.id})",
            )
    return Check("timeline_contiguous", PASS, f"{len(project.timeline.clips)} clips are contiguous")


def _asset_kinds(project: Project) -> Check:
    if not project.assets:
        return Check("asset_kinds", SKIP, "no assets")
    unsupported = [asset.id for asset in project.assets if asset.kind != "video"]
    if unsupported:
        return Check(
            "asset_kinds",
            SKIP,
            f"non-video assets are not rendered in M0: {', '.join(unsupported)}",
        )
    return Check("asset_kinds", PASS, "all assets are video")

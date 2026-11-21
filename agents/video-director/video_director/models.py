"""Project, asset and timeline data structures.

`project.json` is the editable source of truth for a video project.  The
models here only describe the M0 kernel: a single video track, local
assets and monotonic revisions.  Scenes, shots, generation metadata and
multi-track timelines arrive in later schema versions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1
TIME_PRECISION = 3


def round_time(value: float) -> float:
    return round(float(value), TIME_PRECISION)


@dataclass(frozen=True)
class Asset:
    id: str
    path: str
    kind: str = "video"
    duration: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "kind": self.kind,
            "duration": None if self.duration is None else round_time(self.duration),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Asset:
        duration = data.get("duration")
        return cls(
            id=str(data["id"]),
            path=str(data["path"]),
            kind=str(data.get("kind", "video")),
            duration=None if duration is None else float(duration),
        )


@dataclass(frozen=True)
class TimelineClip:
    id: str
    asset_id: str
    start: float
    source_in: float
    source_out: float

    @property
    def duration(self) -> float:
        return round_time(self.source_out - self.source_in)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "start": round_time(self.start),
            "source_in": round_time(self.source_in),
            "source_out": round_time(self.source_out),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TimelineClip:
        return cls(
            id=str(data["id"]),
            asset_id=str(data["asset_id"]),
            start=float(data["start"]),
            source_in=float(data["source_in"]),
            source_out=float(data["source_out"]),
        )


@dataclass
class Timeline:
    clips: list[TimelineClip] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"clips": [clip.to_dict() for clip in self.clips]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Timeline:
        return cls(clips=[TimelineClip.from_dict(clip) for clip in data.get("clips", [])])


@dataclass
class Project:
    project_id: str
    title: str
    fps: float
    width: int
    height: int
    assets: list[Asset] = field(default_factory=list)
    timeline: Timeline = field(default_factory=Timeline)
    status: str = "draft"
    revision: int = 1
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "title": self.title,
            "status": self.status,
            "revision": self.revision,
            "fps": round(float(self.fps), 3),
            "width": self.width,
            "height": self.height,
            "assets": [asset.to_dict() for asset in self.assets],
            "timeline": self.timeline.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
        return cls(
            project_id=str(data["project_id"]),
            title=str(data["title"]),
            fps=float(data["fps"]),
            width=int(data["width"]),
            height=int(data["height"]),
            assets=[Asset.from_dict(asset) for asset in data.get("assets", [])],
            timeline=Timeline.from_dict(data.get("timeline", {})),
            status=str(data.get("status", "draft")),
            revision=int(data.get("revision", 1)),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        )

    def asset(self, asset_id: str) -> Asset | None:
        return next((asset for asset in self.assets if asset.id == asset_id), None)

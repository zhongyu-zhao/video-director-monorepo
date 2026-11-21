"""Core data structures for the auto-shot shot table.

The shot table is the single source of truth for every downstream view
(report, CSV, HTML, Q&A).  Measured facts and model judgments live in
separate fields once labeling lands; the first milestone only emits the
detected timeline.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
TIME_PRECISION = 3
MIN_SHOT_SECONDS = 0.05
TRANSITIONS = ("start", "cut", "dissolve", "fade", "wipe", "whip", "morph")


def round_time(value: float) -> float:
    """Round a timestamp to the precision used in every artifact."""

    return round(float(value), TIME_PRECISION)


def normalize_cuts(cuts: list[float], duration: float) -> list[float]:
    """Return sorted, in-range cut points that leave non-degenerate shots.

    FFmpeg scene detection occasionally reports two boundaries a few
    milliseconds apart.  Keeping them would create sub-frame shots that
    break the timeline gates, so they are dropped here and can be
    reintroduced by a manual recut later.
    """

    if duration <= 0:
        raise ValueError("video duration must be positive")

    end = round_time(duration)
    normalized: list[float] = []
    previous = 0.0
    for raw in sorted(float(value) for value in cuts):
        cut = round_time(raw)
        if cut <= previous + MIN_SHOT_SECONDS:
            continue
        if cut >= end - MIN_SHOT_SECONDS:
            continue
        normalized.append(cut)
        previous = cut
    return normalized


def shots_from_cuts(cuts: list[float], duration: float) -> list[Shot]:
    """Build a contiguous shot table from detected cut points."""

    end = round_time(duration)
    boundaries = [0.0, *normalize_cuts(cuts, duration), end]
    shots: list[Shot] = []
    for start, stop in itertools.pairwise(boundaries):
        if stop - start < MIN_SHOT_SECONDS:
            continue
        index = len(shots) + 1
        shots.append(
            Shot(
                shot_id=f"S{index:03d}",
                start=round_time(start),
                end=round_time(stop),
                transition_in="start" if index == 1 else "cut",
            )
        )
    return shots


@dataclass(frozen=True)
class MediaInfo:
    path: str
    duration: float
    fps: float
    width: int
    height: int
    has_audio: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "duration": round_time(self.duration),
            "fps": round(float(self.fps), 3),
            "width": self.width,
            "height": self.height,
            "has_audio": self.has_audio,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MediaInfo:
        return cls(
            path=str(data["path"]),
            duration=float(data["duration"]),
            fps=float(data["fps"]),
            width=int(data["width"]),
            height=int(data["height"]),
            has_audio=bool(data["has_audio"]),
        )


@dataclass(frozen=True)
class DetectorInfo:
    name: str
    threshold: float

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "threshold": round(float(self.threshold), 3)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DetectorInfo:
        return cls(name=str(data["name"]), threshold=float(data["threshold"]))


@dataclass(frozen=True)
class Shot:
    shot_id: str
    start: float
    end: float
    transition_in: str = "cut"
    source: str = "detected"

    @property
    def duration(self) -> float:
        return round_time(self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "start": round_time(self.start),
            "end": round_time(self.end),
            "duration": self.duration,
            "transition_in": self.transition_in,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Shot:
        return cls(
            shot_id=str(data["shot_id"]),
            start=float(data["start"]),
            end=float(data["end"]),
            transition_in=str(data.get("transition_in", "cut")),
            source=str(data.get("source", "detected")),
        )


@dataclass
class ShotTable:
    video: MediaInfo
    detector: DetectorInfo
    shots: list[Shot] = field(default_factory=list)
    manual_cuts: list[float] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "video": self.video.to_dict(),
            "detector": self.detector.to_dict(),
            "shots": [shot.to_dict() for shot in self.shots],
            "manual_cuts": [round_time(cut) for cut in self.manual_cuts],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ShotTable:
        return cls(
            video=MediaInfo.from_dict(data["video"]),
            detector=DetectorInfo.from_dict(data["detector"]),
            shots=[Shot.from_dict(shot) for shot in data.get("shots", [])],
            manual_cuts=[float(cut) for cut in data.get("manual_cuts", [])],
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        )

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)

    @classmethod
    def load(cls, path: str | Path) -> ShotTable:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

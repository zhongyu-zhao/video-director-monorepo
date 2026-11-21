"""Deterministic quality gates for the shot table.

A gate can pass, fail or be skipped.  Skipped is deliberately distinct
from passed: a check that has no evidence yet (for example a label enum
check before labeling exists) must not look like a green result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import SCHEMA_VERSION, TRANSITIONS, ShotTable

PASS = "pass"
FAIL = "fail"
SKIP = "skip"
_TIMELINE_TOLERANCE = 0.001


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
class QualityReport:
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QualityReport:
        return cls(checks=[Check.from_dict(check) for check in data.get("checks", [])])


def validate_shot_table(table: ShotTable) -> QualityReport:
    checks = [
        _schema_version(table),
        _shots_present(table),
        _timeline_starts_at_zero(table),
        _timeline_contiguous(table),
        _timeline_covers_media(table),
        _positive_durations(table),
        _sequential_ids(table),
        _transition_vocabulary(table),
        _manual_cuts(table),
        _not_implemented("label_enums", "labels are added in M2"),
        _not_implemented("evidence_present", "evidence is added in M2"),
        _not_implemented("motion_consistency", "measured motion is added in M1"),
    ]
    return QualityReport(checks=checks)


def _schema_version(table: ShotTable) -> Check:
    if table.schema_version == SCHEMA_VERSION:
        return Check("schema_version", PASS, f"schema_version={SCHEMA_VERSION}")
    return Check(
        "schema_version",
        FAIL,
        f"expected {SCHEMA_VERSION}, got {table.schema_version}",
    )


def _shots_present(table: ShotTable) -> Check:
    if table.shots:
        return Check("shots_present", PASS, f"{len(table.shots)} shots")
    return Check("shots_present", FAIL, "shot table is empty")


def _timeline_starts_at_zero(table: ShotTable) -> Check:
    if not table.shots:
        return Check("timeline_starts_at_zero", SKIP, "no shots")
    start = table.shots[0].start
    if abs(start) <= _TIMELINE_TOLERANCE:
        return Check("timeline_starts_at_zero", PASS, f"first shot starts at {start:.3f}s")
    return Check("timeline_starts_at_zero", FAIL, f"first shot starts at {start:.3f}s, expected 0")


def _timeline_contiguous(table: ShotTable) -> Check:
    if len(table.shots) < 2:
        return Check("timeline_contiguous", SKIP, "fewer than two shots")
    for previous, current in zip(table.shots, table.shots[1:]):
        gap = current.start - previous.end
        if abs(gap) > _TIMELINE_TOLERANCE:
            return Check(
                "timeline_contiguous",
                FAIL,
                f"{previous.shot_id} ends at {previous.end:.3f}s, "
                f"{current.shot_id} starts at {current.start:.3f}s",
            )
    return Check("timeline_contiguous", PASS, f"{len(table.shots)} shots are contiguous")


def _timeline_covers_media(table: ShotTable) -> Check:
    if not table.shots:
        return Check("timeline_covers_media", SKIP, "no shots")
    end = table.shots[-1].end
    expected = table.video.duration
    frame_tolerance = 1.0 / table.video.fps if table.video.fps > 0 else 0.05
    if abs(end - expected) <= max(_TIMELINE_TOLERANCE, frame_tolerance):
        return Check("timeline_covers_media", PASS, f"last shot ends at {end:.3f}s")
    return Check(
        "timeline_covers_media",
        FAIL,
        f"last shot ends at {end:.3f}s, media duration is {expected:.3f}s",
    )


def _positive_durations(table: ShotTable) -> Check:
    if not table.shots:
        return Check("positive_durations", SKIP, "no shots")
    bad = [shot.shot_id for shot in table.shots if shot.end <= shot.start]
    if bad:
        return Check("positive_durations", FAIL, f"non-positive duration: {', '.join(bad)}")
    return Check("positive_durations", PASS, "all durations are positive")


def _sequential_ids(table: ShotTable) -> Check:
    if not table.shots:
        return Check("sequential_ids", SKIP, "no shots")
    for index, shot in enumerate(table.shots, start=1):
        expected = f"S{index:03d}"
        if shot.shot_id != expected:
            return Check(
                "sequential_ids",
                FAIL,
                f"shot {index} is {shot.shot_id}, expected {expected}",
            )
    return Check("sequential_ids", PASS, f"S001..S{len(table.shots):03d}")


def _transition_vocabulary(table: ShotTable) -> Check:
    if not table.shots:
        return Check("transition_vocabulary", SKIP, "no shots")
    first = table.shots[0]
    if first.transition_in != "start":
        return Check(
            "transition_vocabulary",
            FAIL,
            f"{first.shot_id} must start with 'start', got '{first.transition_in}'",
        )
    for shot in table.shots[1:]:
        if shot.transition_in not in TRANSITIONS or shot.transition_in == "start":
            return Check(
                "transition_vocabulary",
                FAIL,
                f"{shot.shot_id} has invalid transition_in '{shot.transition_in}'",
            )
    return Check("transition_vocabulary", PASS, "transitions are in the vocabulary")


def _manual_cuts(table: ShotTable) -> Check:
    if not table.manual_cuts:
        return Check("manual_cuts_valid", SKIP, "no manual cuts recorded in M0")
    previous = 0.0
    for cut in table.manual_cuts:
        if not 0.0 < cut < table.video.duration:
            return Check(
                "manual_cuts_valid",
                FAIL,
                f"manual cut {cut:.3f}s is outside (0, {table.video.duration:.3f})",
            )
        if cut <= previous:
            return Check("manual_cuts_valid", FAIL, "manual cuts are not strictly increasing")
        previous = cut
    return Check("manual_cuts_valid", PASS, f"{len(table.manual_cuts)} manual cuts are in range")


def _not_implemented(gate_id: str, detail: str) -> Check:
    return Check(gate_id, SKIP, detail)

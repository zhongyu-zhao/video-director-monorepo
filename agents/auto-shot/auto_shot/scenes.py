"""M3 scene aggregation, full-film statistics and evidence backlinks.

Scenes are grouped from per-shot VLM labels and measurements: a new
scene starts on a strong feature change, with a generous hard cap rather
than a fixed 12-shot block.  When no labels/measurements are available
the fixed max-shots/max-seconds fallback still applies.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Shot, ShotTable, round_time

SCENE_SCHEMA_VERSION = 1
DEFAULT_SCENE_SHOTS = 30
DEFAULT_SCENE_SECONDS = 300.0
DEFAULT_MIN_SHOTS = 3
DEFAULT_SCENE_THRESHOLD = 0.55

_CATEGORICAL = ("scale", "camera", "lighting", "color", "angle", "dof")
_NUMERIC = ("brightness", "contrast", "saturation", "motion", "face_ratio")
_CATEGORY_WEIGHTS = {
    "scale": 0.22,
    "camera": 0.20,
    "lighting": 0.14,
    "color": 0.14,
    "angle": 0.07,
    "dof": 0.05,
}
_NUMERIC_WEIGHTS = {
    "brightness": 0.05,
    "contrast": 0.03,
    "saturation": 0.03,
    "motion": 0.04,
    "face_ratio": 0.03,
}


class SceneError(RuntimeError):
    """Raised when scenes or the report cannot be built."""


@dataclass
class Scene:
    scene_id: str
    start: float
    end: float
    shots: list[Shot]
    stats: dict[str, Any]
    title: str = ""
    summary: str = ""
    boundary_reason: str = ""

    @property
    def duration(self) -> float:
        return round_time(self.end - self.start)


@dataclass
class SceneResult:
    output_dir: Path
    scenes_path: Path
    stats_path: Path
    report_path: Path
    scenes: list[Scene]
    stats: dict[str, Any]


def build_scenes(
    table: ShotTable,
    output_dir: str | Path,
    evidence: dict[str, Any] | None = None,
    labels: dict[str, Any] | None = None,
    evidence_path: str | Path | None = None,
    max_shots: int = DEFAULT_SCENE_SHOTS,
    max_seconds: float = DEFAULT_SCENE_SECONDS,
    semantic: bool = True,
    min_shots: int = DEFAULT_MIN_SHOTS,
    threshold: float = DEFAULT_SCENE_THRESHOLD,
    plan: list[dict[str, Any]] | None = None,
    reduce_mode: str = "semantic",
) -> SceneResult:
    if evidence is not None and evidence_path is not None:
        evidence = dict(evidence)
        evidence["_root"] = str(Path(evidence_path).parent)
    if max_shots <= 0 or max_seconds <= 0:
        raise SceneError("scene-shots and scene-seconds must be positive")
    if min_shots <= 0 or threshold < 0:
        raise SceneError("min-shots must be positive and threshold non-negative")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    if plan is not None:
        groups = _group_from_plan(table.shots, plan)
        meta = plan
    else:
        if semantic and (labels or evidence):
            groups = _group_semantic(
                table.shots,
                labels,
                evidence,
                max_shots,
                max_seconds,
                min_shots,
                threshold,
            )
        else:
            groups = _group(table.shots, max_shots, max_seconds)
        meta = [{} for _ in groups]
    scenes = [
        Scene(
            scene_id=f"SC{index:03d}",
            start=group[0].start,
            end=group[-1].end,
            shots=group,
            stats=_scene_stats(group, evidence, labels),
            title=str(meta[index - 1].get("title", "")) if index - 1 < len(meta) else "",
            summary=str(meta[index - 1].get("summary", "")) if index - 1 < len(meta) else "",
            boundary_reason=str(meta[index - 1].get("boundary_reason", "")) if index - 1 < len(meta) else "",
        )
        for index, group in enumerate(groups, start=1)
    ]
    stats = _full_stats(table, scenes, evidence, labels)
    payload = {
        "schema_version": SCENE_SCHEMA_VERSION,
        "video": {
            "path": table.video.path,
            "duration": round_time(table.video.duration),
            "fps": round(float(table.video.fps), 3),
        },
        "config": {"max_shots": max_shots, "max_seconds": max_seconds, "semantic": semantic, "min_shots": min_shots, "threshold": threshold, "reduce": reduce_mode},
        "scenes": [
            {
                "scene_id": scene.scene_id,
                "start": round_time(scene.start),
                "end": round_time(scene.end),
                "duration": scene.duration,
                "shot_ids": [shot.shot_id for shot in scene.shots],
                "title": scene.title,
                "summary": scene.summary,
                "boundary_reason": scene.boundary_reason,
                "stats": scene.stats,
                "evidence": _scene_evidence(scene, evidence),
            }
            for scene in scenes
        ],
        "stats": stats,
    }
    scenes_path = destination / "scenes.json"
    scenes_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    stats_path = destination / "stats.json"
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path = destination / "scenes.md"
    report_path.write_text(_render_report(payload, table, evidence, labels, destination), encoding="utf-8")
    return SceneResult(
        output_dir=destination,
        scenes_path=scenes_path,
        stats_path=stats_path,
        report_path=report_path,
        scenes=scenes,
        stats=stats,
    )


def _group_from_plan(shots: list[Shot], plan: list[dict[str, Any]]) -> list[list[Shot]]:
    index_by_id = {shot.shot_id: index for index, shot in enumerate(shots)}
    groups: list[list[Shot]] = []
    cursor = 0
    for item in plan:
        start = index_by_id[item["start_shot"]]
        end = index_by_id[item["end_shot"]]
        if start != cursor or end < start:
            raise SceneError("scene plan is not contiguous")
        groups.append(shots[start : end + 1])
        cursor = end + 1
    if cursor != len(shots):
        raise SceneError("scene plan does not cover all shots")
    return groups


def _group_semantic(
    shots: list[Shot],
    labels: dict[str, Any] | None,
    evidence: dict[str, Any] | None,
    max_shots: int,
    max_seconds: float,
    min_shots: int,
    threshold: float,
) -> list[list[Shot]]:
    features = [_shot_features(shot, labels, evidence) for shot in shots]
    groups: list[list[Shot]] = []
    current: list[Shot] = []
    for shot, feature in zip(shots, features):
        if current:
            distance = _feature_distance(
                _shot_features(current[-1], labels, evidence), feature
            )
            duration = shot.end - current[0].start
            strong_change = len(current) >= min_shots and distance >= threshold
            hard_limit = len(current) >= max_shots or duration >= max_seconds
            if strong_change or hard_limit:
                groups.append(current)
                current = []
        current.append(shot)
    if current:
        groups.append(current)
    return groups


def _shot_features(
    shot: Shot,
    labels: dict[str, Any] | None,
    evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    label_entry = labels.get("shots", {}).get(shot.shot_id, {}) if labels else {}
    label_values = label_entry.get("labels", {})
    content = label_entry.get("content", {})
    measured = (
        evidence.get("shots", {}).get(shot.shot_id, {}).get("measured", {})
        if evidence
        else {}
    )
    return {
        "labels": label_values,
        "measured": measured,
        "subjects": set(content.get("subjects", [])) if content else set(),
    }


def _feature_distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    total = 0.0
    weighted = 0.0
    for field in _CATEGORICAL:
        a = left["labels"].get(field)
        b = right["labels"].get(field)
        if not a or not b or a == "unknown" or b == "unknown":
            continue
        weight = _CATEGORY_WEIGHTS[field]
        weighted += weight
        if a != b:
            total += weight
    for field in _NUMERIC:
        a = left["measured"].get(field)
        b = right["measured"].get(field)
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            continue
        weight = _NUMERIC_WEIGHTS[field]
        weighted += weight
        total += min(1.0, abs(float(a) - float(b))) * weight
    left_subjects = left["subjects"]
    right_subjects = right["subjects"]
    if left_subjects and right_subjects:
        union = left_subjects | right_subjects
        overlap = len(left_subjects & right_subjects) / len(union) if union else 1.0
        weight = 0.15
        weighted += weight
        total += (1.0 - overlap) * weight
    return round(total / weighted, 4) if weighted > 0 else 0.0


def _group(shots: list[Shot], max_shots: int, max_seconds: float) -> list[list[Shot]]:
    groups: list[list[Shot]] = []
    current: list[Shot] = []
    for shot in shots:
        if current and (
            len(current) >= max_shots or shot.end - current[0].start > max_seconds
        ):
            groups.append(current)
            current = []
        current.append(shot)
    if current:
        groups.append(current)
    return groups


def _scene_stats(
    shots: list[Shot],
    evidence: dict[str, Any] | None,
    labels: dict[str, Any] | None,
) -> dict[str, Any]:
    duration = sum(shot.duration for shot in shots)
    measured = [entry.get("measured", {}) for entry in _evidence_entries(shots, evidence)]
    audio = [entry.get("audio", {}) for entry in _evidence_entries(shots, evidence)]
    label_entries = [
        labels["shots"][shot.shot_id]
        for shot in shots
        if labels and shot.shot_id in labels.get("shots", {})
    ]
    return {
        "shot_count": len(shots),
        "duration": round_time(duration),
        "mean_shot_duration": round(duration / len(shots), 3) if shots else 0.0,
        "cuts_per_minute": round(len(shots) / (duration / 60.0), 2) if duration > 0 else 0.0,
        "scale": _distribution(label_entries, "scale"),
        "camera": _distribution(label_entries, "camera"),
        "lighting": _distribution(label_entries, "lighting"),
        "color": _distribution(label_entries, "color"),
        "brightness": _mean_measured(measured, "brightness"),
        "contrast": _mean_measured(measured, "contrast"),
        "saturation": _mean_measured(measured, "saturation"),
        "motion": _mean_measured(measured, "motion"),
        "face_ratio": _mean_measured(measured, "face_ratio"),
        "silence_ratio": _mean_audio(audio, "silence_ratio"),
    }


def _full_stats(
    table: ShotTable,
    scenes: list[Scene],
    evidence: dict[str, Any] | None,
    labels: dict[str, Any] | None,
) -> dict[str, Any]:
    durations = [shot.duration for shot in table.shots]
    label_entries = list(labels.get("shots", {}).values()) if labels else []
    evidence_entries = _evidence_entries(table.shots, evidence)
    measured = [entry.get("measured", {}) for entry in evidence_entries]
    audio = [entry.get("audio", {}) for entry in evidence_entries]
    return {
        "total_shots": len(table.shots),
        "total_duration": round_time(table.video.duration),
        "mean_shot_duration": round(sum(durations) / len(durations), 3) if durations else 0.0,
        "median_shot_duration": _percentile(durations, 0.5),
        "p90_shot_duration": _percentile(durations, 0.9),
        "cuts_per_minute": round(len(table.shots) / (table.video.duration / 60.0), 2)
        if table.video.duration > 0
        else 0.0,
        "scene_count": len(scenes),
        "scene_mean_shots": round(len(table.shots) / len(scenes), 2) if scenes else 0.0,
        "scale": _distribution(label_entries, "scale"),
        "camera": _distribution(label_entries, "camera"),
        "angle": _distribution(label_entries, "angle"),
        "lighting": _distribution(label_entries, "lighting"),
        "color": _distribution(label_entries, "color"),
        "dof": _distribution(label_entries, "dof"),
        "brightness": _mean_measured(measured, "brightness"),
        "contrast": _mean_measured(measured, "contrast"),
        "saturation": _mean_measured(measured, "saturation"),
        "motion": _mean_measured(measured, "motion"),
        "face_ratio": _mean_measured(measured, "face_ratio"),
        "silence_ratio": _mean_audio(audio, "silence_ratio"),
        "labeled_shots": len(label_entries),
        "evidence_shots": len(measured),
        "audio_events": len(evidence.get("audio_events", [])) if evidence else 0,
        "black_bars": evidence.get("black_bars") if evidence else None,
    }


def _scene_evidence(scene: Scene, evidence: dict[str, Any] | None) -> dict[str, Any]:
    if not evidence:
        return {"contact_sheet": None, "keyframes": []}
    first = evidence.get("shots", {}).get(scene.shots[0].shot_id, {})
    return {
        "contact_sheet": first.get("contact_sheet"),
        "keyframes": first.get("keyframes", []),
    }


def _render_report(
    payload: dict[str, Any],
    table: ShotTable,
    evidence: dict[str, Any] | None,
    labels: dict[str, Any] | None,
    output_dir: Path,
) -> str:
    stats = payload["stats"]
    lines = [
        "# 全片场景与统计",
        "",
        f"- 视频：`{table.video.path}`",
        f"- 时长：{_timecode(table.video.duration)}；镜头：{stats['total_shots']}；场景：{stats['scene_count']}",
        f"- 平均镜长：{stats['mean_shot_duration']:.2f}s；剪辑率：{stats['cuts_per_minute']:.2f} cuts/min",
        (
            f"- 场景聚合：标签/证据变长，硬上限 {payload['config']['max_shots']} 镜/{payload['config']['max_seconds']:.0f}s，"
            f"最少 {payload['config']['min_shots']} 镜，阈值 {payload['config']['threshold']:.2f}"
            if payload['config'].get('semantic', True)
            else f"- 场景基线：每 {payload['config']['max_shots']} 镜或 {payload['config']['max_seconds']:.0f}s 分组"
        ),
        f"- 已标注镜头：{stats['labeled_shots']}；有测量证据：{stats['evidence_shots']}",
        "",
        "## 全片统计",
        "",
        "| 指标 | 值 |",
        "|---|---:|",
        f"| 镜长中位数 | {stats['median_shot_duration']:.2f}s |",
        f"| 镜长 P90 | {stats['p90_shot_duration']:.2f}s |",
        f"| 平均亮度 | {_fmt(stats['brightness'])} |",
        f"| 平均运动 | {_fmt(stats['motion'])} |",
        f"| 平均饱和度 | {_fmt(stats['saturation'])} |",
        f"| 平均人脸占比 | {_fmt(stats['face_ratio'])} |",
        f"| 平均静音比 | {_fmt(stats['silence_ratio'])} |",
        f"| 黑边 | `{stats['black_bars']}` |",
        "",
        "## 标签分布",
        "",
    ]
    for field, label in (("scale", "景别"), ("camera", "运镜"), ("lighting", "光线"), ("color", "色彩")):
        counts = stats.get(field, {})
        lines.append(f"- {label}：{_format_distribution(counts)}")
    lines += [
        "",
        "## 场景卡",
        "",
    ]
    evidence_root = _evidence_root(output_dir, evidence)
    for scene in payload["scenes"]:
        scene_id = scene["scene_id"]
        summary = (
            f"{scene['stats']['shot_count']} 镜 / {scene['duration']:.1f}s；"
            f"平均镜长 {scene['stats']['mean_shot_duration']:.2f}s；"
            f"亮度 {_fmt(scene['stats']['brightness'])}；运动 {_fmt(scene['stats']['motion'])}"
        )
        lines += [
            f"### {scene_id} · {_timecode(scene['start'])}–{_timecode(scene['end'])}",
            "",
            summary,
        ]
        if scene["stats"].get("scale") or scene["stats"].get("camera"):
            lines.append(
                f"景别：{_format_distribution(scene['stats'].get('scale', {}))}；"
                f"运镜：{_format_distribution(scene['stats'].get('camera', {}))}"
            )
        lines.append("")
        for shot_id in scene["shot_ids"]:
            shot = next((item for item in table.shots if item.shot_id == shot_id), None)
            if shot is None:
                continue
            link = ""
            if evidence_root:
                entry = evidence.get("shots", {}).get(shot_id, {}) if evidence else {}
                contact = entry.get("contact_sheet")
                if contact:
                    link = f" · [证据]({_relative_link(output_dir, evidence_root / contact)})"
            lines.append(f"- {shot_id} {_timecode(shot.start)}–{_timecode(shot.end)}{link}")
        lines.append("")
    return "\n".join(lines)


def _evidence_entries(shots: list[Shot], evidence: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not evidence:
        return []
    entries = evidence.get("shots", {})
    return [entries.get(shot.shot_id, {}) for shot in shots]


def _distribution(entries: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        value = entry.get("labels", {}).get(field, "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _mean_measured(entries: list[dict[str, Any]], field: str) -> float | None:
    values = [
        float(entry[field])
        for entry in entries
        if isinstance(entry.get(field), (int, float))
    ]
    return round(sum(values) / len(values), 4) if values else None


def _mean_audio(entries: list[dict[str, Any]], field: str) -> float | None:
    values = [
        float(entry[field])
        for entry in entries
        if isinstance(entry.get(field), (int, float))
    ]
    return round(sum(values) / len(values), 4) if values else None


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return round(ordered[index], 3)


def _timecode(seconds: float) -> str:
    total = max(0, round(seconds))
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{sec:02d}" if hours else f"{minutes:02d}:{sec:02d}"


def _format_distribution(counts: dict[str, int]) -> str:
    if not counts:
        return "未标注"
    return "、".join(f"{key} {value}" for key, value in counts.items())


def _fmt(value: Any) -> str:
    return "-" if value is None else f"{float(value):.3f}"


def _evidence_root(output_dir: Path, evidence: dict[str, Any] | None) -> Path | None:
    if not evidence:
        return None
    value = evidence.get("_root")
    return Path(value) if value else None


def _relative_link(output_dir: Path, target: Path) -> str:
    try:
        return os.path.relpath(target, output_dir)
    except ValueError:
        return str(target)

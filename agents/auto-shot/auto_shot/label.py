"""Per-shot VLM labeling with strict enums and an explicit cache.

Labels are written to a separate artifact so the measured shot table
stays immutable.  Labels use three frames (15%/50%/85%) from one shot as a single
contact sheet.  Camera motion can be inferred from the three frames, but
remains ``unknown`` when the model is unsure.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Shot, ShotTable, round_time
from .taxonomy import (
    ANGLES,
    CAMERAS,
    COLORS,
    COMPOSITIONS,
    DOF,
    LIGHTING,
    SCALES,
    validate_label_values,
)
from .vlm import VlmClient, VlmError

LABEL_SCHEMA_VERSION = 1
PROMPT_VERSION = "vlm-labels-v2"


class LabelError(RuntimeError):
    """Raised when a frame or a model response cannot produce a valid label."""


@dataclass(frozen=True)
class LabelResult:
    labeled: int
    skipped: int
    errors: list[dict[str, str]]
    labels_path: Path
    markdown_path: Path


def shot_hash(shot: Shot) -> str:
    payload = f"{shot.start:.3f}:{shot.end:.3f}:{shot.transition_in}".encode()
    return hashlib.sha1(payload).hexdigest()[:16]


def video_key(table: ShotTable) -> str:
    return (
        f"{table.video.path}|{table.video.duration:.3f}|{table.video.fps:.3f}|"
        f"{table.video.width}x{table.video.height}"
    )


def build_prompt(shot: Shot) -> str:
    return f"""镜头 {shot.shot_id}，时长 {shot.duration:.3f}s。下面是同一镜头的三帧（约 15%/50%/85%，左/中/右）。

只输出一个 JSON 对象，不要 markdown，不要解释。结构：
{{
  "labels": {{
    "scale": "<one of {", ".join(SCALES)}>",
    "angle": "<one of {", ".join(ANGLES)}>",
    "camera": "<one of {", ".join(CAMERAS)}>",
    "composition": "<one of {", ".join(COMPOSITIONS)}>",
    "lighting": "<one of {", ".join(LIGHTING)}>",
    "color": "<one of {", ".join(COLORS)}>",
    "dof": "<one of {", ".join(DOF)}>"
  }},
  "content": {{"subjects": ["画面中的主体，没有则空数组"], "action": "一句可核对的画面描述"}},
  "evidence": {{"scale": "判断依据", "angle": "判断依据", "lighting": "判断依据", "color": "判断依据"}},
  "confidence": {{"scale": 0.0, "angle": 0.0, "camera": 0.0, "composition": 0.0, "lighting": 0.0, "color": 0.0, "dof": 0.0}}
}}

规则：
- 角度按被摄主体相对机位：eye-level 平视，high-angle 俯拍，low-angle 仰拍，birds-eye 正上方，dutch 倾斜，over-the-shoulder 过肩，point-of-view 主观；不确定填 "unknown"。
- 三帧可用于判断运镜；如果三帧机位稳定、只有主体微动，选 static；不确定时填 "unknown"。
- 不确定的维度填 "unknown"，不要猜。
- action 必须描述画面里可看见的内容，不写“氛围感/高级感/视觉冲击”这类空话。
- confidence 每个字段 0 到 1。
- 不要输出时间码。"""


def extract_contact_sheet(video: str | Path, shot: Shot, output: str | Path) -> Path:
    if not shutil.which("ffmpeg"):
        raise LabelError("ffmpeg not found; install ffmpeg")
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".label-", dir=destination.parent))
    try:
        frames: list[Path] = []
        for index, position in enumerate((0.15, 0.5, 0.85), start=1):
            time = round_time(shot.start + shot.duration * position)
            frame = work / f"{index}.jpg"
            completed = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{time:.3f}",
                    "-i",
                    str(video),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=480:-2",
                    "-q:v",
                    "4",
                    str(frame),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0 or not frame.is_file():
                detail = (completed.stderr or "").strip().splitlines()
                raise LabelError(
                    f"cannot extract frame for {shot.shot_id}: "
                    f"{detail[-1] if detail else 'ffmpeg failed'}"
                )
            frames.append(frame)
        command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
        for frame in frames:
            command += ["-i", str(frame)]
        command += [
            "-filter_complex",
            f"hstack=inputs={len(frames)}",
            "-frames:v",
            "1",
            str(destination),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0 or not destination.is_file():
            detail = (completed.stderr or "").strip().splitlines()
            raise LabelError(
                f"cannot build contact sheet for {shot.shot_id}: "
                f"{detail[-1] if detail else 'ffmpeg failed'}"
            )
        return destination
    finally:
        shutil.rmtree(work, ignore_errors=True)


def validate_response(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LabelError("VLM response must be a JSON object")
    labels = payload.get("labels")
    if not isinstance(labels, dict):
        raise LabelError("VLM response has no 'labels' object")
    errors = validate_label_values(labels)
    if errors:
        raise LabelError("; ".join(errors))

    content = payload.get("content")
    if not isinstance(content, dict):
        raise LabelError("VLM response has no 'content' object")
    subjects = content.get("subjects", [])
    if not isinstance(subjects, list) or any(not isinstance(item, str) for item in subjects):
        raise LabelError("content.subjects must be a list of strings")
    action = content.get("action")
    if not isinstance(action, str) or not action.strip():
        raise LabelError("content.action must be a non-empty string")

    evidence = payload.get("evidence")
    if not isinstance(evidence, dict) or not any(
        isinstance(value, str) and value.strip() for value in evidence.values()
    ):
        raise LabelError("evidence must contain at least one non-empty observation")

    confidence = payload.get("confidence")
    if not isinstance(confidence, dict):
        raise LabelError("VLM response has no 'confidence' object")
    resolved_confidence: dict[str, float] = {}
    for field in ("scale", "angle", "camera", "composition", "lighting", "color", "dof"):
        value = confidence.get(field)
        if not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
            raise LabelError(f"confidence.{field} must be a number between 0 and 1")
        resolved_confidence[field] = round(float(value), 3)

    return {
        "labels": {field: labels[field] for field in ("scale", "angle", "camera", "composition", "lighting", "color", "dof")},
        "content": {
            "subjects": [subject.strip() for subject in subjects if subject.strip()],
            "action": action.strip(),
            "dialogue": "",
            "audio": [],
        },
        "function": {"beat": "unknown", "emotion": "unknown"},
        "evidence": {key: value.strip() for key, value in evidence.items() if isinstance(value, str)},
        "confidence": resolved_confidence,
    }


def label_shots(
    table: ShotTable,
    video: str | Path,
    output_dir: str | Path,
    client: VlmClient,
    limit: int | None = 20,
    force: bool = False,
    workers: int = 2,
    retries: int = 1,
    contact_sheets_dir: str | Path | None = None,
    frame_extractor: Callable[[str | Path, Shot, str | Path], Path] = extract_contact_sheet,
) -> LabelResult:
    """Label up to ``limit`` uncached shots and write labels.json + labels.md.

    ``limit=None`` labels every uncached shot.  Failures are collected per
    shot so one bad response does not discard the rest of the batch.
    """

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    labels_path = destination / "labels.json"
    markdown_path = destination / "labels.md"
    model = getattr(client, "model", "unknown")
    identity = video_key(table)
    existing = _load_existing(labels_path, table)
    cached = {
        shot.shot_id: existing[shot.shot_id]
        for shot in table.shots
        if shot.shot_id in existing and _is_cached(existing[shot.shot_id], shot, model, identity)
    }
    targets = [shot for shot in table.shots if force or shot.shot_id not in cached]
    if limit is not None:
        targets = targets[: max(0, limit)]

    entries: dict[str, dict[str, Any]] = dict(cached)
    successes: set[str] = set()
    errors: list[dict[str, str]] = []
    frames_dir = destination / "frames"

    def label_one(shot: Shot) -> dict[str, Any]:
        frame = frames_dir / f"{shot.shot_id}.jpg"
        if force or not frame.is_file():
            existing = (
                Path(contact_sheets_dir) / f"{shot.shot_id}.jpg"
                if contact_sheets_dir
                else None
            )
            if existing is not None and existing.is_file():
                frame.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(existing, frame)
            else:
                frame_extractor(video, shot, frame)
        last_error: Exception | None = None
        for attempt in range(max(0, retries) + 1):
            try:
                response = client.label_image(frame.read_bytes(), build_prompt(shot))
                normalized = validate_response(response)
                break
            except (LabelError, VlmError, OSError) as error:
                last_error = error
                if attempt >= retries:
                    raise LabelError(str(last_error)) from last_error
                time.sleep(0.5 * (attempt + 1))
        else:  # pragma: no cover - the loop always breaks or raises
            raise LabelError(str(last_error) if last_error else "label failed")
        return {
            "shot_hash": shot_hash(shot),
            "video_key": identity,
            **normalized,
            "provenance": {
                "labeled_by": f"deepseek:{model}",
                "prompt_version": PROMPT_VERSION,
                "review": "unreviewed",
            },
        }

    if workers <= 1:
        for shot in targets:
            _label_into(entries, successes, errors, shot, label_one, labels_path, table, model)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_safe_label, label_one, shot): shot for shot in targets}
            for future in as_completed(futures):
                shot = futures[future]
                _record_future(entries, successes, errors, shot, future, labels_path, table, model)

    _write_labels(labels_path, table, entries, errors, model)
    _write_markdown(markdown_path, table, entries, model)
    return LabelResult(
        labeled=len(successes),
        skipped=len(table.shots) - len(targets),
        errors=errors,
        labels_path=labels_path,
        markdown_path=markdown_path,
    )


def _safe_label(label_one: Callable[[Shot], dict[str, Any]], shot: Shot) -> dict[str, Any]:
    try:
        return label_one(shot)
    except (LabelError, VlmError, OSError) as error:
        raise LabelError(str(error)) from error


def _label_into(
    entries: dict[str, dict[str, Any]],
    successes: set[str],
    errors: list[dict[str, str]],
    shot: Shot,
    label_one: Callable[[Shot], dict[str, Any]],
    labels_path: Path,
    table: ShotTable,
    model: str,
) -> None:
    try:
        entries[shot.shot_id] = label_one(shot)
        successes.add(shot.shot_id)
        _write_labels(labels_path, table, entries, errors, model)
    except (LabelError, VlmError, OSError) as error:
        errors.append({"shot_id": shot.shot_id, "error": str(error)})


def _record_future(
    entries: dict[str, dict[str, Any]],
    successes: set[str],
    errors: list[dict[str, str]],
    shot: Shot,
    future: Any,
    labels_path: Path,
    table: ShotTable,
    model: str,
) -> None:
    try:
        entries[shot.shot_id] = future.result()
        successes.add(shot.shot_id)
    except (LabelError, VlmError, OSError) as error:
        errors.append({"shot_id": shot.shot_id, "error": str(error)})
        return
    _write_labels(labels_path, table, entries, errors, model)


def _load_existing(path: Path, table: ShotTable) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise LabelError(f"cannot read {path}: {error}") from error
    shots = payload.get("shots", {})
    if not isinstance(shots, dict):
        raise LabelError(f"{path} has no shots object")
    current = {shot.shot_id for shot in table.shots}
    return {shot_id: entry for shot_id, entry in shots.items() if shot_id in current and isinstance(entry, dict)}


def _is_cached(entry: dict[str, Any], shot: Shot, model: str, identity: str) -> bool:
    provenance = entry.get("provenance", {})
    return (
        entry.get("shot_hash") == shot_hash(shot)
        and entry.get("video_key") == identity
        and provenance.get("prompt_version") == PROMPT_VERSION
        and provenance.get("labeled_by") == f"deepseek:{model}"
    )


def _write_labels(
    path: Path,
    table: ShotTable,
    entries: dict[str, dict[str, Any]],
    errors: list[dict[str, str]],
    model: str,
) -> None:
    payload = {
        "schema_version": LABEL_SCHEMA_VERSION,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "video": {"path": table.video.path, "duration": round_time(table.video.duration)},
        "shots": {shot.shot_id: entries[shot.shot_id] for shot in table.shots if shot.shot_id in entries},
        "errors": errors,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path, table: ShotTable, entries: dict[str, dict[str, Any]], model: str) -> None:
    lines = [
        "# VLM 逐镜标注",
        "",
        f"- 模型：{model}",
        f"- prompt：{PROMPT_VERSION}",
        f"- 已标注：{len(entries)} / {len(table.shots)}",
        "",
        "| 镜号 | 景别 | 角度 | 构图 | 光线 | 色彩 | 景深 | 描述 | 景别置信度 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for shot in table.shots:
        entry = entries.get(shot.shot_id)
        if not entry:
            continue
        labels = entry["labels"]
        lines.append(
            f"| {shot.shot_id} | {labels['scale']} | {labels['angle']} | "
            f"{labels['composition']} | {labels['lighting']} | {labels['color']} | "
            f"{labels['dof']} | {_escape(entry['content']['action'])} | "
            f"{entry['confidence'].get('scale', 0):.2f} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _escape(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")

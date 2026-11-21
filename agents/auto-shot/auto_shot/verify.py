"""VLM verification for short-shot boundaries.

A very short shot is often a false cut caused by a flash, a fast pan or a
sub-shot.  This module asks a VLM one conservative question at each
boundary of a short shot: are the frames before and after the boundary
the same shot?  Only clear, confident "same shot" answers remove a
boundary; everything else is kept.

The verifier never changes the input shot table.  It writes a
``verifications.json`` cache and one ``*-verified.json`` per input table.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Shot, ShotTable, round_time
from .quality import validate_shot_table
from .report import render_report
from .vlm import VlmClient, VlmError

VERIFICATION_SCHEMA_VERSION = 1
PROMPT_VERSION = "vlm-short-cut-v1"
DEFAULT_MAX_DURATION = 1.0
DEFAULT_CONFIDENCE = 0.7
_BOUNDARY_TOLERANCE = 0.2


class VerificationError(RuntimeError):
    """Raised when candidate frames or a verified table are invalid."""


@dataclass(frozen=True)
class BoundaryVerdict:
    time: float
    same_shot: bool
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "time": round(self.time, 3),
            "same_shot": self.same_shot,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BoundaryVerdict:
        return cls(
            time=float(data["time"]),
            same_shot=bool(data["same_shot"]),
            confidence=float(data["confidence"]),
            reason=str(data.get("reason", "")),
        )


@dataclass
class VerificationResult:
    output_dir: Path
    verifications_path: Path
    report_path: Path
    verified_paths: dict[str, Path]
    boundaries: dict[float, BoundaryVerdict]
    removed: dict[str, list[float]]
    errors: list[dict[str, str]]


def video_key(table: ShotTable) -> str:
    video = table.video
    payload = (
        f"{video.path}|{video.duration:.3f}|{video.fps:.3f}|"
        f"{video.width}x{video.height}"
    )
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


def short_shot_boundaries(
    table: ShotTable,
    window: tuple[float, float] | None = None,
    max_duration: float = DEFAULT_MAX_DURATION,
) -> set[float]:
    boundaries: set[float] = set()
    for shot in table.shots:
        if shot.duration >= max_duration:
            continue
        if window is not None and (shot.start < window[0] or shot.end > window[1]):
            continue
        for value in (shot.start, shot.end):
            if value > 0 and value < table.video.duration:
                boundaries.add(round_time(value))
    return boundaries


def collect_boundaries(
    tables: Sequence[ShotTable],
    window: tuple[float, float] | None,
    max_duration: float,
) -> list[float]:
    merged = sorted(
        {
            boundary
            for table in tables
            for boundary in short_shot_boundaries(table, window, max_duration)
        }
    )
    # Different detectors can put the same visual boundary a few frames
    # apart; keep one candidate per ~0.12s cluster.
    clustered: list[float] = []
    for boundary in merged:
        if not clustered or boundary - clustered[-1] > 0.12:
            clustered.append(boundary)
    return clustered


def build_prompt() -> str:
    return """这是同一条视频在一个切点前后的两帧（左=切点前，右=切点后）。
判断左右是否属于同一镜头：
- 同一场景、同一机位、连续动作，或只是同一画面内的运动/闪光 → same_shot=true。
- 真正切到另一个镜头（包括同一场景换机位、明显景别/主体变化、黑场/白场过渡）→ same_shot=false。
保守原则：不确定时选 false，不要为了合并而猜 true。
只输出 JSON，不要 markdown：
{"same_shot": true 或 false, "confidence": 0 到 1, "reason": "一句可核对的话"}"""


def validate_verdict(payload: dict[str, Any]) -> tuple[bool, float, str]:
    if not isinstance(payload, dict):
        raise VerificationError("VLM response must be a JSON object")
    same = payload.get("same_shot")
    if not isinstance(same, bool):
        raise VerificationError("VLM response 'same_shot' must be a boolean")
    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
        raise VerificationError("VLM response 'confidence' must be between 0 and 1")
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise VerificationError("VLM response 'reason' must be a non-empty string")
    return same, round(float(confidence), 3), reason.strip()


def extract_pair_images(
    video: str | Path,
    table: ShotTable,
    boundaries: Sequence[float],
    work_dir: str | Path,
) -> dict[float, Path]:
    """Extract before/after frames and hstack each pair into one image."""

    media = table.video
    if media.fps <= 0:
        raise VerificationError("video fps is required for boundary extraction")
    if not shutil.which("ffmpeg"):
        raise VerificationError("ffmpeg not found; install ffmpeg")

    root = Path(work_dir)
    frames_dir = root / "frames"
    pairs_dir = root / "pairs"
    frames_dir.mkdir(parents=True, exist_ok=True)
    pairs_dir.mkdir(parents=True, exist_ok=True)

    frame_numbers: set[int] = set()
    for boundary in boundaries:
        index = round(boundary * media.fps)
        frame_numbers.add(max(0, index - 1))
        frame_numbers.add(max(0, index))
    ordered = sorted(frame_numbers)
    expression = "+".join(f"eq(n,{number})" for number in ordered)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-vf",
        f"select='{expression}',scale=480:-2",
        "-fps_mode",
        "vfr",
        "-q:v",
        "3",
        "-f",
        "image2",
        str(frames_dir / "frame-%06d.jpg"),
    ]
    _run(command, "extract boundary frames")

    frame_paths: dict[int, Path] = {}
    for position, number in enumerate(ordered, start=1):
        path = frames_dir / f"frame-{position:06d}.jpg"
        if not path.is_file():
            raise VerificationError(f"missing extracted frame {path}")
        frame_paths[number] = path

    pairs: dict[float, Path] = {}
    for boundary in boundaries:
        index = round(boundary * media.fps)
        before = frame_paths.get(max(0, index - 1))
        after = frame_paths.get(max(0, index))
        if before is None or after is None:
            raise VerificationError(f"cannot map frames for boundary {boundary:.3f}s")
        pair = pairs_dir / f"{boundary:010.3f}.jpg"
        _run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(before),
                "-i",
                str(after),
                "-filter_complex",
                "hstack=inputs=2",
                "-frames:v",
                "1",
                str(pair),
            ],
            f"stack frames for boundary {boundary:.3f}s",
        )
        pairs[boundary] = pair
    return pairs


def verify_short_shots(
    tables: Sequence[ShotTable],
    video: str | Path,
    output_dir: str | Path,
    client: VlmClient,
    window: tuple[float, float] | None = None,
    max_duration: float = DEFAULT_MAX_DURATION,
    confidence_threshold: float = DEFAULT_CONFIDENCE,
    limit: int | None = 20,
    force: bool = False,
    workers: int = 2,
    pair_extractor: Callable[[str | Path, ShotTable, Sequence[float], str | Path], dict[float, Path]] = extract_pair_images,
) -> VerificationResult:
    if not tables:
        raise VerificationError("at least one shot table is required")
    if confidence_threshold < 0.0 or confidence_threshold > 1.0:
        raise VerificationError("confidence threshold must be between 0 and 1")
    if max_duration <= 0:
        raise VerificationError("max duration must be positive")
    first = tables[0]
    for table in tables[1:]:
        if table.video.path != first.video.path or abs(table.video.duration - first.video.duration) > 0.01:
            raise VerificationError("all shot tables must use the same video")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    verifications_path = destination / "verifications.json"
    report_path = destination / "verification-report.md"
    identity = video_key(first)
    model = getattr(client, "model", "unknown")
    candidates = collect_boundaries(tables, window, max_duration)
    existing = _load_existing(verifications_path, identity, model)
    cached = {
        time: verdict
        for time, verdict in existing.items()
        if _is_cached(existing, time, identity, model)
    }
    targets = [time for time in candidates if force or time not in cached]
    if limit is not None:
        targets = targets[: max(0, limit)]

    verdicts: dict[float, BoundaryVerdict] = dict(cached)
    errors: list[dict[str, str]] = []
    if targets:
        pairs = pair_extractor(video, first, targets, destination)
        prompt = build_prompt()

        def work(time: float) -> BoundaryVerdict:
            pair = pairs[time]
            payload = client.label_image(pair.read_bytes(), prompt)
            same, confidence, reason = validate_verdict(payload)
            return BoundaryVerdict(time=time, same_shot=same, confidence=confidence, reason=reason)

        if workers <= 1:
            for time in targets:
                _record_verdict(verdicts, errors, time, work, verifications_path, identity, model, first)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_safe_work, work, time): time for time in targets}
                for future in as_completed(futures):
                    time = futures[future]
                    _record_future(verdicts, errors, time, future, verifications_path, identity, model, first)

    _write_verifications(verifications_path, identity, first, model, verdicts, errors)
    removed: dict[str, list[float]] = {}
    verified_paths: dict[str, Path] = {}
    for table, source in zip(tables, _source_names(tables)):
        table_boundaries = short_shot_boundaries(table, window, max_duration)
        false_times = [
            time
            for time, verdict in verdicts.items()
            if verdict.same_shot
            and verdict.confidence >= confidence_threshold
            and any(abs(time - boundary) <= _BOUNDARY_TOLERANCE for boundary in table_boundaries)
        ]
        corrected = apply_verdicts(table, false_times)
        path = destination / f"{source}-verified.json"
        corrected.save(path)
        verified_paths[source] = path
        before_starts = [shot.start for shot in table.shots]
        after_starts = [shot.start for shot in corrected.shots]
        removed[source] = sorted(
            start
            for start in before_starts
            if not any(abs(start - kept) <= _BOUNDARY_TOLERANCE for kept in after_starts)
        )
        quality = validate_shot_table(corrected)
        if not quality.ok:
            failed = ", ".join(check.id for check in quality.failed)
            raise VerificationError(f"verified table {source} failed quality gates: {failed}")
        report = render_report(corrected, quality)
        (destination / f"{source}-verified-report.md").write_text(report, encoding="utf-8")

    _write_report(
        report_path,
        first,
        window,
        max_duration,
        confidence_threshold,
        model,
        verdicts,
        errors,
        removed,
    )
    return VerificationResult(
        output_dir=destination,
        verifications_path=verifications_path,
        report_path=report_path,
        verified_paths=verified_paths,
        boundaries=verdicts,
        removed=removed,
        errors=errors,
    )


def apply_verdicts(
    table: ShotTable,
    false_times: Sequence[float],
    tolerance: float = _BOUNDARY_TOLERANCE,
) -> ShotTable:
    """Merge boundaries judged to be the same shot; renumber the result."""

    false_sorted = sorted(round_time(time) for time in false_times)
    if not false_sorted:
        return ShotTable(
            video=table.video,
            detector=table.detector,
            shots=list(table.shots),
            manual_cuts=list(table.manual_cuts),
            schema_version=table.schema_version,
        )

    shots: list[Shot] = []
    for shot in table.shots:
        is_false = any(abs(shot.start - value) <= tolerance for value in false_sorted)
        if is_false and shots:
            previous = shots[-1]
            shots[-1] = Shot(
                shot_id=previous.shot_id,
                start=previous.start,
                end=shot.end,
                transition_in=previous.transition_in,
                source="vlm",
            )
            continue
        shots.append(
            Shot(
                shot_id=shot.shot_id,
                start=shot.start,
                end=shot.end,
                transition_in=shot.transition_in,
                source=shot.source,
            )
        )

    renumbered = [
        Shot(
            shot_id=f"S{index:03d}",
            start=round_time(shot.start),
            end=round_time(shot.end),
            transition_in="start" if index == 1 else shot.transition_in,
            source=shot.source,
        )
        for index, shot in enumerate(shots, start=1)
    ]
    corrected = ShotTable(
        video=table.video,
        detector=table.detector,
        shots=renumbered,
        manual_cuts=list(table.manual_cuts),
        schema_version=table.schema_version,
    )
    quality = validate_shot_table(corrected)
    if not quality.ok:
        failed = ", ".join(check.id for check in quality.failed)
        raise VerificationError(f"verified table failed quality gates: {failed}")
    return corrected


def _safe_work(work: Callable[[float], BoundaryVerdict], time: float) -> BoundaryVerdict:
    return work(time)


def _record_verdict(
    verdicts: dict[float, BoundaryVerdict],
    errors: list[dict[str, str]],
    time: float,
    work: Callable[[float], BoundaryVerdict],
    path: Path,
    identity: str,
    model: str,
    table: ShotTable,
) -> None:
    try:
        verdicts[time] = work(time)
        _write_verifications(path, identity, table, model, verdicts, errors)
    except (VerificationError, VlmError, OSError) as error:
        errors.append({"time": f"{time:.3f}", "error": str(error)})


def _record_future(
    verdicts: dict[float, BoundaryVerdict],
    errors: list[dict[str, str]],
    time: float,
    future: Any,
    path: Path,
    identity: str,
    model: str,
    table: ShotTable,
) -> None:
    try:
        verdicts[time] = future.result()
    except (VerificationError, VlmError, OSError) as error:
        errors.append({"time": f"{time:.3f}", "error": str(error)})
        return
    _write_verifications(path, identity, table, model, verdicts, errors)


def _load_existing(path: Path, identity: str, model: str) -> dict[float, BoundaryVerdict]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise VerificationError(f"cannot read {path}: {error}") from error
    if payload.get("video_key") != identity or payload.get("model") != model:
        return {}
    if payload.get("prompt_version") != PROMPT_VERSION:
        return {}
    result: dict[float, BoundaryVerdict] = {}
    for key, value in payload.get("boundaries", {}).items():
        try:
            result[float(key)] = BoundaryVerdict.from_dict(value)
        except (KeyError, TypeError, ValueError):
            continue
    return result


def _is_cached(
    values: dict[float, BoundaryVerdict],
    time: float,
    identity: str,
    model: str,
) -> bool:
    return time in values


def _write_verifications(
    path: Path,
    identity: str,
    table: ShotTable,
    model: str,
    verdicts: dict[float, BoundaryVerdict],
    errors: list[dict[str, str]],
) -> None:
    payload = {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "video_key": identity,
        "video": {
            "path": table.video.path,
            "duration": round_time(table.video.duration),
            "fps": round(float(table.video.fps), 3),
        },
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "boundaries": {
            f"{time:.3f}": verdict.to_dict() for time, verdict in sorted(verdicts.items())
        },
        "errors": errors,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_report(
    path: Path,
    table: ShotTable,
    window: tuple[float, float] | None,
    max_duration: float,
    confidence_threshold: float,
    model: str,
    verdicts: dict[float, BoundaryVerdict],
    errors: list[dict[str, str]],
    removed: dict[str, list[float]],
) -> None:
    lines = [
        "# 短镜头切点 VLM 复核",
        "",
        f"- 视频：`{table.video.path}`",
        f"- 窗口：{window[0]:.3f}–{window[1]:.3f}s" if window else "- 窗口：全片",
        f"- 短镜头阈值：< {max_duration:.3f}s",
        f"- 模型 / prompt：{model} / {PROMPT_VERSION}",
        f"- 合并阈值：same_shot 且 confidence ≥ {confidence_threshold:.2f}",
        f"- 判定切点：{len(verdicts)}；错误：{len(errors)}",
        "",
        "| 切点 | same_shot | confidence | 说明 |",
        "|---|---:|---:|---|",
    ]
    for time, verdict in sorted(verdicts.items()):
        lines.append(
            f"| {time:.3f}s | {'是' if verdict.same_shot else '否'} | "
            f"{verdict.confidence:.2f} | {verdict.reason.replace('|', '\\|')} |"
        )
    if errors:
        lines += ["", "## 错误", ""]
        for error in errors:
            lines.append(f"- {error['time']}s: {error['error']}")
    lines += ["", "## 应用结果", ""]
    for source, times in removed.items():
        lines.append(f"- {source}: 合并 {len(times)} 个切点")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _source_names(tables: Sequence[ShotTable]) -> list[str]:
    return [f"table-{index}" for index in range(1, len(tables) + 1)]


def _run(command: list[str], action: str) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        raise VerificationError(f"{action} failed: {detail[-1] if detail else 'ffmpeg error'}")

"""Command line entry point for auto-shot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .detect import DetectError
from .detectors import DetectorUnavailable
from .evidence import EvidenceError, build_evidence
from .label import LabelError, label_shots
from .models import ShotTable
from .pipeline import analyze
from .probe import ProbeError
from .quality import validate_shot_table
from .report import render_report
from .review import ReviewError, apply_review, render_review_html
from .scenes import SceneError, build_scenes
from .verify import (
    VerificationError,
    collect_boundaries,
    short_shot_boundaries,
    verify_short_shots,
)
from .vlm import DeepSeekVlmClient, VlmError, resolve_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="auto-shot",
        description="Deterministic shot table extraction for film analysis.",
    )
    parser.add_argument("--version", action="version", version=f"auto-shot {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    analyze_parser = commands.add_parser(
        "analyze",
        help="detect shots and write shots.json, quality.json and report.md",
    )
    analyze_parser.add_argument("input", help="video file to analyze")
    analyze_parser.add_argument("--out", required=True, help="directory for output artifacts")
    analyze_parser.add_argument(
        "--threshold",
        type=float,
        default=0.25,
        help="ffmpeg scene score threshold in (0, 1]; default 0.25",
    )
    analyze_parser.add_argument(
        "--detector",
        choices=("auto", "ffmpeg", "pyscenedetect", "transnetv2"),
        default="auto",
        help="shot detector, or auto to route by motion (default auto)",
    )
    analyze_parser.add_argument(
        "--prefer-neural",
        action="store_true",
        help="with --detector auto, prefer TransNetV2 for high-motion video when installed",
    )
    analyze_parser.add_argument(
        "--no-review",
        action="store_true",
        help="do not write/refresh review.html after analysis",
    )

    review_parser = commands.add_parser(
        "review",
        help="generate a local HTML page for reviewing cuts",
    )
    review_parser.add_argument("--shots", required=True, help="shots.json from analyze")
    review_parser.add_argument("--video", required=True, help="source video")
    review_parser.add_argument("--out", default=None, help="output HTML (default: next to shots.json)")
    review_parser.add_argument("--status", default="自动检测", help="stage label shown in the page header")
    review_parser.add_argument("--labels", default=None, help="labels.json to embed")
    review_parser.add_argument("--scenes", default=None, help="scenes.json to embed")
    review_parser.add_argument("--evidence", default=None, help="evidence.json to embed")
    review_parser.add_argument("--source-shots", default=None, help="original shots.json for time-based label/scene mapping")

    apply_parser = commands.add_parser(
        "apply-review",
        help="apply review-flags.json and write a corrected shot table",
    )
    apply_parser.add_argument("--shots", required=True, help="shots.json from analyze")
    apply_parser.add_argument("--flags", required=True, help="review-flags.json exported by the review page")
    apply_parser.add_argument("--out", default=None, help="corrected shots JSON (default: shots-reviewed.json)")

    label_parser = commands.add_parser(
        "label",
        help="label shots with a VLM (one mid-shot frame per shot)",
    )
    label_parser.add_argument("--shots", required=True, help="shots.json from analyze")
    label_parser.add_argument("--video", required=True, help="source video")
    label_parser.add_argument("--out", default=None, help="output directory for labels.json/labels.md (default: next to shots.json)")
    label_parser.add_argument("--limit", type=int, default=20, help="label at most N uncached shots (default 20)")
    label_parser.add_argument("--all", action="store_true", help="label every uncached shot")
    label_parser.add_argument("--force", action="store_true", help="ignore the label cache")
    label_parser.add_argument("--workers", type=int, default=2, help="parallel VLM requests (default 2)")
    label_parser.add_argument("--model", default=None, help="override model name")
    label_parser.add_argument("--base-url", default=None, help="override OpenAI-compatible base URL")
    label_parser.add_argument("--env-file", default=None, help="dotenv file with the API key, e.g. /mnt/d/Super-Agent/.env")
    label_parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY", help="environment variable name")
    label_parser.add_argument("--dry-run", action="store_true", help="show what would be labeled, without API calls")

    verify_parser = commands.add_parser(
        "verify-short",
        help="use a VLM to merge short-shot boundaries that are the same shot",
    )
    verify_parser.add_argument(
        "--shots",
        action="append",
        required=True,
        help="shot table to verify; repeat for multiple methods",
    )
    verify_parser.add_argument("--video", required=True, help="source video")
    verify_parser.add_argument("--out", default=None, help="output directory (default: next to the first shots file)")
    verify_parser.add_argument("--window", default=None, help="evaluation window START:END in seconds")
    verify_parser.add_argument("--max-duration", type=float, default=1.0, help="short shot threshold in seconds (default 1.0)")
    verify_parser.add_argument("--confidence", type=float, default=0.7, help="minimum same-shot confidence to merge (default 0.7)")
    verify_parser.add_argument("--limit", type=int, default=20, help="verify at most N uncached boundaries (default 20)")
    verify_parser.add_argument("--all", action="store_true", help="verify every uncached boundary")
    verify_parser.add_argument("--workers", type=int, default=2, help="parallel VLM requests (default 2)")
    verify_parser.add_argument("--model", default=None, help="override model name")
    verify_parser.add_argument("--base-url", default=None, help="override OpenAI-compatible base URL")
    verify_parser.add_argument("--env-file", default=None, help="dotenv file with the API key")
    verify_parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY", help="environment variable name")
    verify_parser.add_argument("--force", action="store_true", help="ignore the verification cache")
    verify_parser.add_argument("--dry-run", action="store_true", help="list candidates without API/frame extraction")

    evidence_parser = commands.add_parser(
        "evidence",
        help="build M1 evidence: proxy, bars, keyframes, measurements and audio events",
    )
    evidence_parser.add_argument("--shots", required=True, help="shots.json")
    evidence_parser.add_argument("--video", required=True, help="source video")
    evidence_parser.add_argument("--out", default=None, help="output directory (default: shots parent/evidence)")
    evidence_parser.add_argument("--proxy-width", type=int, default=480, help="proxy width (default 480)")
    evidence_parser.add_argument("--keyframes", type=int, default=3, help="keyframes per shot (default 3)")
    evidence_parser.add_argument("--face", action="store_true", help="measure face ratio (needs OpenCV)")
    evidence_parser.add_argument("--face-model", default=None, help="YuNet ONNX model for OpenCV 5 face detection")
    evidence_parser.add_argument("--asr", action="store_true", help="transcribe audio (needs faster-whisper)")
    evidence_parser.add_argument("--force", action="store_true", help="rebuild existing proxy/keyframes")

    scenes_parser = commands.add_parser(
        "scenes",
        help="aggregate shots into scenes and write full-film statistics",
    )
    scenes_parser.add_argument("--shots", required=True, help="shots.json")
    scenes_parser.add_argument("--out", default=None, help="output directory (default: shots parent/scenes)")
    scenes_parser.add_argument("--evidence", default=None, help="evidence.json from the evidence command")
    scenes_parser.add_argument("--labels", default=None, help="labels.json from the label command")
    scenes_parser.add_argument("--scene-shots", type=int, default=12, help="max shots per scene (default 12)")
    scenes_parser.add_argument("--scene-seconds", type=float, default=180.0, help="max scene seconds (default 180)")
    scenes_parser.add_argument("--review-out", default=None, help="also write an enriched review.html here")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "analyze":
            return _command_analyze(arguments)
        if arguments.command == "review":
            return _command_review(arguments)
        if arguments.command == "apply-review":
            return _command_apply_review(arguments)
        if arguments.command == "label":
            return _command_label(arguments)
        if arguments.command == "verify-short":
            return _command_verify_short(arguments)
        if arguments.command == "evidence":
            return _command_evidence(arguments)
        if arguments.command == "scenes":
            return _command_scenes(arguments)
    except (
        ProbeError,
        DetectError,
        DetectorUnavailable,
        ReviewError,
        VerificationError,
        EvidenceError,
        SceneError,
        LabelError,
        VlmError,
        ValueError,
        OSError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 2


def _command_analyze(arguments: argparse.Namespace) -> int:
    result = analyze(
        arguments.input,
        arguments.out,
        threshold=arguments.threshold,
        detector=arguments.detector,
        prefer_neural=arguments.prefer_neural,
        review=not arguments.no_review,
    )
    counts = result.quality.counts()
    status = "pass" if result.quality.ok else "FAIL"
    print(
        f"shots={len(result.table.shots)} duration={result.table.video.duration:.3f}s "
        f"detector={result.detection.detector} route={result.detection.route} "
        f"latency={result.detection.latency_seconds:.2f}s "
        f"quality={status} ({counts['pass']} pass / {counts['fail']} fail / {counts['skip']} skip)"
    )
    artifacts = [result.shots_path, result.quality_path, result.detection_path, result.report_path]
    if result.review_path is not None:
        artifacts.append(result.review_path)
    for artifact in artifacts:
        print(f"wrote: {artifact}")
    if not result.quality.ok:
        failed = ", ".join(check.id for check in result.quality.failed)
        print(f"failed gates: {failed}", file=sys.stderr)
        return 1
    return 0


def _load_json_arg(path: str | None) -> dict | None:
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else None


def _command_review(arguments: argparse.Namespace) -> int:
    shots_path = Path(arguments.shots)
    video_path = Path(arguments.video)
    if not shots_path.is_file():
        raise ReviewError(f"shots file not found: {shots_path}")
    if not video_path.is_file():
        raise ReviewError(f"video not found: {video_path}")
    table = ShotTable.load(shots_path)
    destination = Path(arguments.out) if arguments.out else shots_path.parent / "review.html"
    labels = _load_json_arg(arguments.labels)
    scenes = _load_json_arg(arguments.scenes)
    evidence = _load_json_arg(arguments.evidence)
    source_table = ShotTable.load(Path(arguments.source_shots)) if arguments.source_shots else None
    written = render_review_html(
        table,
        video_path,
        destination,
        status=arguments.status,
        labels=labels,
        scenes=scenes,
        evidence=evidence,
        source_table=source_table,
        evidence_dir=Path(arguments.evidence).parent if arguments.evidence else None,
    )
    print(f"review page: {written}")
    print("open it in a browser; export review-flags.json, then run apply-review")
    return 0


def _command_apply_review(arguments: argparse.Namespace) -> int:
    shots_path = Path(arguments.shots)
    flags_path = Path(arguments.flags)
    table = ShotTable.load(shots_path)
    flags = json.loads(flags_path.read_text(encoding="utf-8"))
    corrected = apply_review(table, flags)
    destination = Path(arguments.out) if arguments.out else shots_path.with_name("shots-reviewed.json")
    corrected.save(destination)
    quality = validate_shot_table(corrected)
    report_path = destination.with_name(destination.stem + "-report.md")
    report_path.write_text(render_report(corrected, quality), encoding="utf-8")
    manual = len(corrected.manual_cuts)
    print(f"shots={len(corrected.shots)} manual_cuts={manual} quality={'pass' if quality.ok else 'FAIL'}")
    print(f"wrote: {destination}")
    print(f"wrote: {report_path}")
    return 0 if quality.ok else 1


def _command_scenes(arguments: argparse.Namespace) -> int:
    shots_path = Path(arguments.shots)
    table = ShotTable.load(shots_path)
    evidence_path = Path(arguments.evidence) if arguments.evidence else None
    evidence = (
        json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path else None
    )
    labels = (
        json.loads(Path(arguments.labels).read_text(encoding="utf-8")) if arguments.labels else None
    )
    destination = Path(arguments.out) if arguments.out else shots_path.parent / "scenes"
    result = build_scenes(
        table,
        destination,
        evidence=evidence,
        labels=labels,
        evidence_path=evidence_path,
        max_shots=arguments.scene_shots,
        max_seconds=arguments.scene_seconds,
    )
    if arguments.review_out:
        scenes_payload = json.loads(result.scenes_path.read_text(encoding="utf-8"))
        render_review_html(
            table,
            table.video.path,
            arguments.review_out,
            status="场景报告（最新）",
            labels=labels,
            scenes=scenes_payload,
            evidence=evidence,
            evidence_dir=evidence_path.parent if evidence_path else None,
        )
        print(f"wrote: {Path(arguments.review_out).resolve()}")
    print(f"scenes={len(result.scenes)} stats={len(result.stats)}")
    for path in (result.scenes_path, result.stats_path, result.report_path):
        print(f"wrote: {path}")
    return 0


def _command_evidence(arguments: argparse.Namespace) -> int:
    shots_path = Path(arguments.shots)
    table = ShotTable.load(shots_path)
    destination = Path(arguments.out) if arguments.out else shots_path.parent / "evidence"
    result = build_evidence(
        table,
        arguments.video,
        destination,
        proxy_width=arguments.proxy_width,
        keyframes=arguments.keyframes,
        face=arguments.face,
        face_model=arguments.face_model,
        asr=arguments.asr,
        force=arguments.force,
    )
    print(f"shots={len(result.shots)} notes={len(result.notes)}")
    for path in (result.evidence_path, result.media_path, result.report_path):
        print(f"wrote: {path}")
    for note in result.notes[:5]:
        print(f"  note: {note}", file=sys.stderr)
    return 0


def _command_verify_short(arguments: argparse.Namespace) -> int:
    shots_paths = [Path(path) for path in arguments.shots]
    tables = [ShotTable.load(path) for path in shots_paths]
    window = _parse_window(arguments.window)
    limit = None if arguments.all else max(0, arguments.limit)

    if arguments.dry_run:
        union = collect_boundaries(tables, window, arguments.max_duration)
        for path, table in zip(shots_paths, tables):
            count = len(short_shot_boundaries(table, window, arguments.max_duration))
            print(f"{path}: {count} short-shot boundaries")
        print(f"union: {len(union)} boundaries")
        print("dry run: no API call, no files written")
        return 0

    config = resolve_config(
        env_file=arguments.env_file,
        model=arguments.model,
        base_url=arguments.base_url,
        api_key_env=arguments.api_key_env,
    )
    client = DeepSeekVlmClient(config)
    destination = Path(arguments.out) if arguments.out else shots_paths[0].parent / "vlm-verify"
    result = verify_short_shots(
        tables,
        arguments.video,
        destination,
        client,
        window=window,
        max_duration=arguments.max_duration,
        confidence_threshold=arguments.confidence,
        limit=limit,
        force=arguments.force,
        workers=max(1, arguments.workers),
    )
    print(f"boundaries={len(result.boundaries)} errors={len(result.errors)}")
    for source, path in result.verified_paths.items():
        print(f"wrote: {path} (removed {len(result.removed[source])} boundaries)")
        if source in result.review_paths:
            print(f"wrote: {result.review_paths[source]}")
    if result.review_path is not None:
        print(f"wrote: {result.review_path} (latest review)")
    print(f"wrote: {result.verifications_path}")
    print(f"wrote: {result.report_path}")
    for error in result.errors[:5]:
        print(f"  {error['time']}: {error['error']}", file=sys.stderr)
    return 0 if not result.errors else 1


def _parse_window(value: str | None) -> tuple[float, float] | None:
    if value is None:
        return None
    parts = value.split(":", 1)
    if len(parts) != 2:
        raise VerificationError("window must be START:END")
    try:
        start, end = float(parts[0]), float(parts[1])
    except ValueError as error:
        raise VerificationError("window must be START:END in seconds") from error
    if start < 0 or end <= start:
        raise VerificationError("window must satisfy 0 <= START < END")
    return start, end


def _command_label(arguments: argparse.Namespace) -> int:
    shots_path = Path(arguments.shots)
    video_path = Path(arguments.video)
    if not video_path.is_file():
        raise LabelError(f"video not found: {video_path}")
    table = ShotTable.load(shots_path)
    limit = None if arguments.all else max(0, arguments.limit)

    if arguments.dry_run:
        targets = table.shots if limit is None else table.shots[:limit]
        print(f"would label {len(targets)} / {len(table.shots)} shots with one frame each")
        print("dry run: no API call, no files written")
        return 0

    config = resolve_config(
        env_file=arguments.env_file,
        model=arguments.model,
        base_url=arguments.base_url,
        api_key_env=arguments.api_key_env,
    )
    client = DeepSeekVlmClient(config)
    destination = Path(arguments.out) if arguments.out else shots_path.parent
    result = label_shots(
        table,
        video_path,
        destination,
        client,
        limit=limit,
        force=arguments.force,
        workers=max(1, arguments.workers),
    )
    print(f"labeled={result.labeled} skipped={result.skipped} errors={len(result.errors)}")
    print(f"wrote: {result.labels_path}")
    print(f"wrote: {result.markdown_path}")
    for error in result.errors[:5]:
        print(f"  {error['shot_id']}: {error['error']}", file=sys.stderr)
    return 0 if not result.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Command line entry point for auto-shot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .detect import DetectError
from .label import LabelError, label_shots
from .models import ShotTable
from .pipeline import analyze
from .probe import ProbeError
from .quality import validate_shot_table
from .report import render_report
from .review import ReviewError, apply_review, render_review_html
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

    review_parser = commands.add_parser(
        "review",
        help="generate a local HTML page for reviewing cuts",
    )
    review_parser.add_argument("--shots", required=True, help="shots.json from analyze")
    review_parser.add_argument("--video", required=True, help="source video")
    review_parser.add_argument("--out", default=None, help="output HTML (default: next to shots.json)")

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
    label_parser.add_argument("--out", default=None, help="labels.json (default: next to shots.json)")
    label_parser.add_argument("--limit", type=int, default=20, help="label at most N uncached shots (default 20)")
    label_parser.add_argument("--all", action="store_true", help="label every uncached shot")
    label_parser.add_argument("--force", action="store_true", help="ignore the label cache")
    label_parser.add_argument("--workers", type=int, default=2, help="parallel VLM requests (default 2)")
    label_parser.add_argument("--model", default=None, help="override model name")
    label_parser.add_argument("--base-url", default=None, help="override OpenAI-compatible base URL")
    label_parser.add_argument("--env-file", default=None, help="dotenv file with the API key, e.g. /mnt/d/Super-Agent/.env")
    label_parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY", help="environment variable name")
    label_parser.add_argument("--dry-run", action="store_true", help="show what would be labeled, without API calls")
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
    except (
        ProbeError,
        DetectError,
        ReviewError,
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
    )
    counts = result.quality.counts()
    status = "pass" if result.quality.ok else "FAIL"
    print(
        f"shots={len(result.table.shots)} duration={result.table.video.duration:.3f}s "
        f"quality={status} ({counts['pass']} pass / {counts['fail']} fail / {counts['skip']} skip)"
    )
    for artifact in (result.shots_path, result.quality_path, result.report_path):
        print(f"wrote: {artifact}")
    if not result.quality.ok:
        failed = ", ".join(check.id for check in result.quality.failed)
        print(f"failed gates: {failed}", file=sys.stderr)
        return 1
    return 0


def _command_review(arguments: argparse.Namespace) -> int:
    shots_path = Path(arguments.shots)
    video_path = Path(arguments.video)
    if not shots_path.is_file():
        raise ReviewError(f"shots file not found: {shots_path}")
    if not video_path.is_file():
        raise ReviewError(f"video not found: {video_path}")
    table = ShotTable.load(shots_path)
    destination = Path(arguments.out) if arguments.out else shots_path.parent / "review.html"
    written = render_review_html(table, video_path, destination)
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

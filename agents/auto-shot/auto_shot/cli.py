"""Command line entry point for auto-shot."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .detect import DetectError
from .pipeline import analyze
from .probe import ProbeError


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
        default=0.3,
        help="ffmpeg scene score threshold in (0, 1]; default 0.3",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command != "analyze":
        return 2

    try:
        result = analyze(
            arguments.input,
            arguments.out,
            threshold=arguments.threshold,
        )
    except (ProbeError, DetectError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

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


if __name__ == "__main__":
    raise SystemExit(main())

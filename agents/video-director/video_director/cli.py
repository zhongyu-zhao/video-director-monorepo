"""Command line entry point for video-director."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .media import MediaError
from .project import (
    ProjectError,
    add_asset,
    add_clip,
    create_project,
    load_project,
    save_project,
)
from .render import RenderError, render_project
from .validate import validate_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-director",
        description="Artifact-first video project kernel: validate and render a timeline.",
    )
    parser.add_argument("--version", action="version", version=f"video-director {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create a project directory")
    init.add_argument("--root", default=".", help="project directory (default: current directory)")
    init.add_argument("--title", required=True, help="project title")
    init.add_argument("--fps", type=float, default=25.0, help="project fps (default 25)")
    init.add_argument(
        "--size",
        type=_parse_size,
        default="1920x1080",
        help="WIDTHxHEIGHT (default 1920x1080)",
    )

    asset = commands.add_parser("asset", help="manage local assets")
    asset_commands = asset.add_subparsers(dest="asset_command", required=True)
    asset_add = asset_commands.add_parser("add", help="copy a media file into assets/")
    asset_add.add_argument("path", help="source media file")
    asset_add.add_argument("--root", default=".", help="project directory")
    asset_add.add_argument("--id", default=None, help="explicit asset id")

    clip = commands.add_parser("clip", help="edit the timeline")
    clip_commands = clip.add_subparsers(dest="clip_command", required=True)
    clip_add = clip_commands.add_parser("add", help="append a clip to the end of the timeline")
    clip_add.add_argument("--asset", required=True, help="asset id, for example A001")
    clip_add.add_argument("--in", dest="source_in", type=float, required=True, help="source in point (seconds)")
    clip_add.add_argument("--out", dest="source_out", type=float, required=True, help="source out point (seconds)")
    clip_add.add_argument("--start", type=float, default=None, help="timeline start (default: end of timeline)")
    clip_add.add_argument("--id", default=None, help="explicit clip id")
    clip_add.add_argument("--root", default=".", help="project directory")

    validate = commands.add_parser("validate", help="run project validation gates")
    validate.add_argument("--root", default=".", help="project directory")

    render = commands.add_parser("render", help="render the timeline with ffmpeg")
    render.add_argument("--root", default=".", help="project directory")
    render.add_argument("--out", default=None, help="output file (default: renders/render-r<revision>.mp4)")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        return _dispatch(arguments)
    except (ProjectError, MediaError, RenderError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _dispatch(arguments: argparse.Namespace) -> int:
    if arguments.command == "init":
        width, height = arguments.size
        project = create_project(
            arguments.root,
            title=arguments.title,
            fps=arguments.fps,
            width=width,
            height=height,
        )
        print(f"project: {Path(arguments.root)} (revision {project.revision})")
        return 0

    if arguments.command == "asset" and arguments.asset_command == "add":
        project = load_project(arguments.root)
        asset = add_asset(project, arguments.root, arguments.path, asset_id=arguments.id)
        save_project(project, arguments.root)
        duration = "unknown" if asset.duration is None else f"{asset.duration:.3f}s"
        print(f"asset: {asset.id} {asset.path} ({asset.kind}, {duration}) revision {project.revision}")
        return 0

    if arguments.command == "clip" and arguments.clip_command == "add":
        project = load_project(arguments.root)
        clip = add_clip(
            project,
            asset_id=arguments.asset,
            source_in=arguments.source_in,
            source_out=arguments.source_out,
            start=arguments.start,
            clip_id=arguments.id,
        )
        save_project(project, arguments.root)
        print(
            f"clip: {clip.id} {clip.asset_id} start={clip.start:.3f} "
            f"source={clip.source_in:.3f}..{clip.source_out:.3f} revision {project.revision}"
        )
        return 0

    if arguments.command == "validate":
        project = load_project(arguments.root)
        report = validate_project(project, arguments.root)
        return _print_validation(report)

    if arguments.command == "render":
        project = load_project(arguments.root)
        validation = validate_project(project, arguments.root)
        if not validation.ok:
            return _print_validation(validation)
        if not project.timeline.clips:
            print("error: timeline is empty; add at least one clip", file=sys.stderr)
            return 1
        report = render_project(project, arguments.root, output=arguments.out)
        return _print_render(report, arguments.root)

    print(f"error: unknown command {arguments.command}", file=sys.stderr)
    return 2


def _print_validation(report) -> int:
    counts = report.counts()
    status = "pass" if report.ok else "FAIL"
    print(f"validation: {status} ({counts['pass']} pass / {counts['fail']} fail / {counts['skip']} skip)")
    for check in report.checks:
        print(f"  [{check.status}] {check.id}: {check.detail}")
    return 0 if report.ok else 1


def _print_render(report, root: str) -> int:
    counts = report.counts()
    status = "pass" if report.ok else "FAIL"
    print(
        f"render: {report.output} ({report.actual_duration:.3f}s, "
        f"{report.width}x{report.height} @ {report.fps:.3f}fps) {status} "
        f"({counts['pass']} pass / {counts['fail']} fail / {counts['skip']} skip)"
    )
    for check in report.checks:
        if check.status != "pass":
            print(f"  [{check.status}] {check.id}: {check.detail}")
    print(f"render report: {(Path(root) / 'renders' / 'render_report.json').as_posix()}")
    return 0 if report.ok else 1


def _parse_size(value: str) -> tuple[int, int]:
    parts = value.lower().split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"invalid size: {value}; expected WIDTHxHEIGHT")
    try:
        width, height = int(parts[0]), int(parts[1])
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid size: {value}") from error
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError(f"invalid size: {value}")
    return width, height


if __name__ == "__main__":
    raise SystemExit(main())

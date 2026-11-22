"""Command line entry point for screenplay-adapter."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .cast import extract_cast, load_cast_file
from .draft import merge_screenplay
from .fountain import render_fountain, render_markdown
from .models import (
    FORMATS,
    SCHEMA_VERSION,
    AdaptationPlan,
    AdapterError,
    SourceDocument,
)
from .plan import build_plan, make_brief, render_briefs
from .project import (
    BRIEFS_FILENAME,
    PLAN_FILENAME,
    SOURCE_RELATIVE_PATH,
    ensure_root,
    load_drafts,
    load_plan,
    load_screenplay,
    load_source,
    read_env_file,
    save_briefs,
    save_draft,
    save_plan,
    save_report,
    save_screenplay,
    write_exports,
    write_source,
)
from .source import parse_source, read_source_text
from .validate import Report, make_report, validate_plan, validate_screenplay
from .writer import OpenAICompatibleWriter, WriterConfig, WriterError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="screenplay-adapter",
        description="Adapt a novel or outline into a traceable, validated screenplay plan.",
    )
    parser.add_argument("--version", action="version", version=f"screenplay-adapter {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    adapt = commands.add_parser("adapt", help="parse a source and build the adaptation plan")
    adapt.add_argument("source", help="novel or outline file (UTF-8 text/Markdown)")
    adapt.add_argument("--root", required=True, help="project directory to create")
    adapt.add_argument("--title", default=None, help="project title (default: detected title)")
    adapt.add_argument("--format", choices=FORMATS, default="short-drama", help="target format")
    adapt.add_argument("--episodes", type=int, default=None, help="number of episodes")
    adapt.add_argument("--episode-minutes", type=float, default=None, help="minutes per episode")
    adapt.add_argument("--scene-seconds", type=float, default=None, help="target seconds per scene")
    adapt.add_argument("--genre", default="", help="genre label")
    adapt.add_argument("--logline", default="", help="one-sentence story")
    adapt.add_argument("--audience", default="", help="target audience")
    adapt.add_argument("--aspect", choices=("vertical", "horizontal"), default="vertical")
    adapt.add_argument("--language", choices=("zh", "en", "auto"), default="auto")
    adapt.add_argument("--mode", choices=("adapt", "expand"), default="adapt")
    adapt.add_argument("--cast", default=None, help="explicit cast JSON file")
    adapt.add_argument("--force", action="store_true", help="overwrite an existing plan")

    draft = commands.add_parser("draft", help="write scenes with an OpenAI-compatible endpoint")
    draft.add_argument("--root", required=True, help="project directory")
    draft.add_argument("--writer", choices=("openai",), default="openai")
    draft.add_argument("--env-file", default=None, help="KEY=VALUE file with provider credentials")
    draft.add_argument("--base-url", default=None, help="chat-completions base URL (usually ends in /v1)")
    draft.add_argument("--model", default=None, help="model name")
    draft.add_argument("--scene", action="append", default=None, help="only write this scene id (repeatable)")
    draft.add_argument("--limit", type=int, default=None, help="write at most N scenes")
    draft.add_argument("--force", action="store_true", help="overwrite existing drafts")
    draft.add_argument("--timeout", type=float, default=90.0, help="request timeout in seconds")

    assemble = commands.add_parser("assemble", help="merge drafts, export Fountain/Markdown and validate")
    assemble.add_argument("--root", required=True, help="project directory")

    validate = commands.add_parser("validate", help="run deterministic plan/screenplay gates")
    validate.add_argument("--root", required=True, help="project directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        return _dispatch(arguments)
    except (AdapterError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _dispatch(arguments: argparse.Namespace) -> int:
    if arguments.command == "adapt":
        return _adapt(arguments)
    if arguments.command == "draft":
        return _draft(arguments)
    if arguments.command == "assemble":
        return _assemble(arguments)
    if arguments.command == "validate":
        return _validate(arguments)
    raise AdapterError(f"unknown command: {arguments.command}")


def _adapt(arguments: argparse.Namespace) -> int:
    source_path = Path(arguments.source)
    text = read_source_text(source_path)
    root = ensure_root(Path(arguments.root))
    if (root / PLAN_FILENAME).is_file() and not arguments.force:
        raise AdapterError(
            f"{root / PLAN_FILENAME} already exists; pass --force to overwrite it "
            "(existing drafts will then fail their plan-hash check)"
        )
    document = parse_source(
        text,
        path=SOURCE_RELATIVE_PATH,
        title=arguments.title,
        fallback_title=source_path.stem,
    )
    title = arguments.title or document.title
    brief = make_brief(
        title,
        arguments.format,
        episodes=arguments.episodes,
        episode_minutes=arguments.episode_minutes,
        scene_seconds=arguments.scene_seconds,
        genre=arguments.genre,
        logline=arguments.logline,
        audience=arguments.audience,
        aspect=arguments.aspect,
        language=arguments.language,
        mode=arguments.mode,
    )
    explicit = load_cast_file(Path(arguments.cast)) if arguments.cast else None
    cast = extract_cast(document, explicit=explicit)
    write_source(root, text)
    plan = build_plan(document, brief, cast)
    save_plan(root, plan)
    save_briefs(root, render_briefs(plan, document))
    report = validate_plan(plan, document)
    save_report(root, _report_payload(report))
    _print_plan(plan, report)
    print(f"  -> {root / PLAN_FILENAME}")
    print(f"  -> {root / BRIEFS_FILENAME}")
    return 0 if report.status != "fail" else 1


def _draft(arguments: argparse.Namespace) -> int:
    root = Path(arguments.root)
    plan = load_plan(root)
    document = load_source(root)
    if plan.plan_hash and plan.plan_hash != _current_plan_hash(plan, document):
        raise AdapterError("adaptation.json plan_hash does not match its source; re-run adapt")
    plan_report = validate_plan(plan, document)
    if plan_report.status == "fail":
        _print_report(plan_report)
        print("error: plan has failing gates; fix the plan before writing drafts", file=sys.stderr)
        return 1

    selected = list(plan.scenes)
    if arguments.scene:
        wanted = set(arguments.scene)
        unknown = sorted(wanted - {scene.id for scene in plan.scenes})
        if unknown:
            raise AdapterError("unknown scene ids: " + ", ".join(unknown))
        selected = [scene for scene in plan.scenes if scene.id in wanted]
    if arguments.limit is not None:
        if arguments.limit < 1:
            raise AdapterError("--limit must be at least 1")
        selected = selected[: arguments.limit]

    existing = load_drafts(root)
    if not arguments.force:
        stale = sorted(
            scene.id
            for scene in selected
            if scene.id in existing
            and (
                (existing[scene.id].plan_hash and existing[scene.id].plan_hash != plan.plan_hash)
                or (
                    existing[scene.id].source_sha256
                    and existing[scene.id].source_sha256 != str(plan.source.get("sha256", ""))
                )
            )
        )
        if stale:
            preview = ", ".join(stale[:8]) + (" …" if len(stale) > 8 else "")
            raise AdapterError(
                f"{len(stale)} drafts were written against a different plan or source: {preview}. "
                "Pass --force to rewrite them."
            )
        selected = [scene for scene in selected if scene.id not in existing]
    if not selected:
        print("draft: nothing to do (all selected scenes already have drafts)")
        return 0

    env = read_env_file(Path(arguments.env_file)) if arguments.env_file else {}
    config = _writer_config(arguments, env)
    writer = OpenAICompatibleWriter(config)
    failures = 0
    consecutive_failures = 0
    for position, scene in enumerate(selected, start=1):
        print(f"draft: {scene.id} ({position}/{len(selected)}) …", end="", flush=True)
        try:
            draft = writer.write_scene(plan, scene, document)
        except WriterError as error:
            print(" failed")
            print(f"error: {scene.id}: {error}", file=sys.stderr)
            failures += 1
            consecutive_failures += 1
            if _is_fatal_provider_error(str(error)):
                print("error: stopping after a configuration/authentication failure", file=sys.stderr)
                return 2
            if consecutive_failures >= 3:
                print("error: stopping after 3 consecutive scene failures", file=sys.stderr)
                return 1
            continue
        consecutive_failures = 0
        save_draft(root, draft)
        print(f" {len(draft.action)} action blocks, {len(draft.dialogue)} dialogue lines")
    remaining = [scene.id for scene in plan.scenes if scene.id not in load_drafts(root)]
    if failures:
        print(f"draft: {failures} scene(s) failed; {len(remaining)} scene(s) still missing", file=sys.stderr)
        return 1
    if remaining:
        print(f"draft: {len(remaining)} scene(s) still missing: " + ", ".join(remaining[:8]))
        return 0
    print("draft: all scenes have drafts; run `assemble` next")
    return 0


def _assemble(arguments: argparse.Namespace) -> int:
    root = Path(arguments.root)
    plan = load_plan(root)
    document = load_source(root)
    plan_report = validate_plan(plan, document)
    if plan_report.status == "fail":
        save_report(root, _report_payload(plan_report))
        _print_report(plan_report)
        print("error: plan has failing gates; fix the plan before assembling", file=sys.stderr)
        return 1
    drafts = load_drafts(root)
    screenplay = merge_screenplay(plan, drafts)
    save_screenplay(root, screenplay)
    fountain = render_fountain(screenplay, plan)
    markdown = render_markdown(screenplay, plan, document)
    write_exports(root, fountain, markdown)
    screenplay_report = validate_screenplay(plan, screenplay, document)
    stats = dict(screenplay_report.stats)
    stats["plan_status"] = plan_report.status
    report = make_report("screenplay", plan_report.gates + screenplay_report.gates, stats)
    save_report(root, _report_payload(report))
    _print_report(report)
    print(f"  -> {root / 'screenplay.json'}")
    print(f"  -> {root / 'screenplay.fountain'}")
    print(f"  -> {root / 'screenplay.md'}")
    return 0 if report.status != "fail" else 1


def _validate(arguments: argparse.Namespace) -> int:
    root = Path(arguments.root)
    plan = load_plan(root)
    document = load_source(root)
    screenplay = load_screenplay(root)
    plan_report = validate_plan(plan, document)
    if screenplay is None:
        report = plan_report
    else:
        screenplay_report = validate_screenplay(plan, screenplay, document)
        stats = dict(screenplay_report.stats)
        stats["plan_status"] = plan_report.status
        report = make_report("screenplay", plan_report.gates + screenplay_report.gates, stats)
    save_report(root, _report_payload(report))
    _print_report(report)
    return 0 if report.status != "fail" else 1


def _writer_config(arguments: argparse.Namespace, env: dict[str, str]) -> WriterConfig:
    base_url = _first_value(arguments.base_url, env, "SCREENPLAY_ADAPTER_BASE_URL", "OPENAI_BASE_URL")
    api_key = _first_value(None, env, "SCREENPLAY_ADAPTER_API_KEY", "OPENAI_API_KEY")
    model = _first_value(arguments.model, env, "SCREENPLAY_ADAPTER_MODEL", "OPENAI_MODEL", default="gpt-4o-mini")
    if not base_url:
        base_url = "https://api.openai.com/v1"
    return WriterConfig(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=arguments.timeout,
    )


def _first_value(cli: str | None, env: dict[str, str], *names: str, default: str = "") -> str:
    if cli:
        return cli
    for name in names:
        if env.get(name):
            return env[name]
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    return default


def _current_plan_hash(plan: AdaptationPlan, document: SourceDocument) -> str:
    from .models import plan_hash_for

    return plan_hash_for(document.sha256, plan.brief, plan.scenes, plan.cast)


def _is_fatal_provider_error(message: str) -> bool:
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in ("authentication failed", "api key is required", "endpoint not found", "base url must")
    )


def _report_payload(report: Report) -> dict:
    payload = report.to_dict()
    payload["schema_version"] = SCHEMA_VERSION
    return payload


def _print_plan(plan: AdaptationPlan, report: Report) -> None:
    print(
        f"plan: {len(plan.scenes)} scenes / {plan.brief.episodes} episodes / "
        f"{plan.brief.total_minutes:g} min ({plan.brief.format})"
    )
    print(
        f"  source: {plan.source.get('chars', 0)} chars, "
        f"{plan.source.get('sentence_count', 0)} sentences, "
        f"{plan.source.get('chapter_count', 0)} chapters"
    )
    print(f"  cast: {len(plan.cast)} characters ({_cast_sources(plan)})")
    print(f"  validation: {report.status} ({len(report.failures)} fail, {len(report.warnings)} warn)")
    for gate in report.failures + report.warnings:
        print(f"  {gate.status.upper():4} {gate.id} {gate.message}")


def _print_report(report: Report) -> None:
    print(
        f"validation: {report.status} ({len(report.failures)} fail, {len(report.warnings)} warn) "
        f"[{report.stage}]"
    )
    for gate in report.gates:
        if gate.status in ("fail", "warn"):
            print(f"  {gate.status.upper():4} {gate.id} {gate.message}")
    stats = report.stats
    if report.stage == "screenplay":
        print(
            f"screenplay: {stats.get('scene_count', 0)} scenes, "
            f"{stats.get('dialogue_lines', 0)} dialogue lines, "
            f"estimated {float(stats.get('estimated_seconds', 0)) / 60:.1f} min "
            f"(target {float(stats.get('target_seconds', 0)) / 60:.1f} min)"
        )


def _cast_sources(plan: AdaptationPlan) -> str:
    sources = sorted({character.source for character in plan.cast}) or ["none"]
    return "/".join(sources)

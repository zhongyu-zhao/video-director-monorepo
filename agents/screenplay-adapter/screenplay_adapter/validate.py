"""Deterministic gates for the adaptation plan and the drafted screenplay.

`fail` means the artifact is structurally unusable and blocks export/delivery;
`warn` means a human should look but the artifact is still reviewable.  Semantic
quality (voice, theme, performance) is deliberately not scored here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .beats import beat_index
from .draft import screenplay_stats
from .models import (
    DIALOGUE_BASES,
    Dialogue,
    estimate_draft_seconds,
    plan_hash_for,
    INT_EXT_VALUES,
    FORMATS,
    SCHEMA_VERSION,
    TIME_VALUES,
    AdaptationPlan,
    Scene,
    Screenplay,
    SourceDocument,
)

PASS = "pass"
WARN = "warn"
FAIL = "fail"


@dataclass(frozen=True)
class Gate:
    id: str
    status: str
    message: str
    scenes: tuple[str, ...] = ()


@dataclass
class Report:
    stage: str
    status: str
    gates: list[Gate] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "screenplay-adapter-report",
            "stage": self.stage,
            "status": self.status,
            "stats": self.stats,
            "gates": [
                {"id": gate.id, "status": gate.status, "message": gate.message, "scenes": list(gate.scenes)}
                for gate in self.gates
            ],
        }

    @property
    def failures(self) -> list[Gate]:
        return [gate for gate in self.gates if gate.status == FAIL]

    @property
    def warnings(self) -> list[Gate]:
        return [gate for gate in self.gates if gate.status == WARN]


def make_report(stage: str, gates: list[Gate], stats: dict[str, Any]) -> Report:
    if any(gate.status == FAIL for gate in gates):
        status = FAIL
    elif any(gate.status == WARN for gate in gates):
        status = WARN
    else:
        status = PASS
    return Report(stage=stage, status=status, gates=gates, stats=stats)


def validate_plan(plan: AdaptationPlan, document: SourceDocument) -> Report:
    gates = [
        _gate_schema(plan),
        _gate_brief(plan),
        _gate_source(plan, document),
        _gate_coverage(plan, document),
        _gate_scene_order(plan),
        _gate_episodes(plan),
        _gate_durations(plan),
        _gate_cast(plan),
        _gate_beats(plan),
        _gate_chapters(plan, document),
        _gate_plan_warnings(plan),
        _gate_plan_hash(plan, document),
    ]
    stats = {
        "scene_count": len(plan.scenes),
        "episode_count": len({scene.episode for scene in plan.scenes}),
        "requested_scenes": plan.requested_scenes,
        "source_sentences": len(document.sentences),
        "covered_sentences": sum(scene.source.sentence_count for scene in plan.scenes),
        "cast_count": len(plan.cast),
        "target_seconds": plan.brief.total_seconds,
        "planned_seconds": plan.total_seconds,
        "average_scene_seconds": round(plan.total_seconds / len(plan.scenes), 3) if plan.scenes else 0.0,
        "source_chars": document.chars,
        "source_word_units": document.word_units,
    }
    return make_report("plan", gates, stats)


def validate_screenplay(plan: AdaptationPlan, screenplay: Screenplay, document: SourceDocument) -> Report:
    shape_error = _screenplay_shape_error(screenplay)
    if shape_error is not None:
        return make_report("screenplay", [shape_error], {"scene_count": len(screenplay.scenes)})
    gates = [
        _gate_screenplay_schema(screenplay),
        _gate_plan_link(plan, screenplay),
        _gate_scene_link(plan, screenplay),
        _gate_headings(screenplay),
        _gate_bodies(screenplay),
        _gate_speakers(plan, screenplay),
        _gate_basis(screenplay),
        _gate_runtime(plan, screenplay),
        _gate_dialogue_presence(screenplay),
        _gate_invention(plan, screenplay),
        _gate_scene_cast(plan, screenplay),
    ]
    stats = dict(screenplay_stats(screenplay))
    stats["source_sentences"] = len(document.sentences)
    stats["covered_sentences"] = sum(
        max(0, int(scene.get("source", {}).get("sentence_end", -1)) - int(scene.get("source", {}).get("sentence_start", 0)) + 1)
        for scene in screenplay.scenes
    )
    stats["target_seconds"] = plan.brief.total_seconds
    stats["planned_seconds"] = plan.total_seconds
    return make_report("screenplay", gates, stats)


def _screenplay_shape_error(screenplay: Screenplay) -> Gate | None:
    if not isinstance(screenplay.scenes, list):
        return Gate("S000", FAIL, "screenplay scenes must be a list")
    for index, scene in enumerate(screenplay.scenes):
        label = f"scene {index + 1}"
        if not isinstance(scene, dict):
            return Gate("S000", FAIL, f"{label} must be an object")
        if not isinstance(scene.get("heading"), dict):
            return Gate("S000", FAIL, f"{label} heading must be an object")
        if not isinstance(scene.get("source"), dict):
            return Gate("S000", FAIL, f"{label} source must be an object")
        if not isinstance(scene.get("action"), list):
            return Gate("S000", FAIL, f"{label} action must be a list")
        dialogue = scene.get("dialogue")
        if not isinstance(dialogue, list):
            return Gate("S000", FAIL, f"{label} dialogue must be a list")
        for line in dialogue:
            if not isinstance(line, dict):
                return Gate("S000", FAIL, f"{label} dialogue entries must be objects")
            if not str(line.get("character", "")).strip() or not str(line.get("line", "")).strip():
                return Gate("S000", FAIL, f"{label} dialogue entries need character and line")
    return None


# ---------------------------------------------------------------------------
# Plan gates
# ---------------------------------------------------------------------------


def _gate_schema(plan: AdaptationPlan) -> Gate:
    if plan.schema_version != SCHEMA_VERSION:
        return Gate("P001", FAIL, f"plan schema_version {plan.schema_version} != {SCHEMA_VERSION}")
    if not plan.scenes:
        return Gate("P001", FAIL, "plan has no scenes")
    return Gate("P001", PASS, f"schema_version {SCHEMA_VERSION}, {len(plan.scenes)} scenes")


def _gate_brief(plan: AdaptationPlan) -> Gate:
    brief = plan.brief
    if brief.format not in FORMATS:
        return Gate("P012", FAIL, f"unknown format {brief.format!r}")
    if brief.episodes < 1:
        return Gate("P012", FAIL, "episodes must be at least 1")
    if brief.episode_minutes <= 0 or brief.scene_seconds <= 0:
        return Gate("P012", FAIL, "episode_minutes and scene_seconds must be positive")
    if brief.format == "feature" and brief.episodes != 1:
        return Gate("P012", FAIL, "feature format must have exactly one episode")
    return Gate("P012", PASS, f"{brief.format}, {brief.episodes} episodes")


def _gate_source(plan: AdaptationPlan, document: SourceDocument) -> Gate:
    if plan.source.get("sha256") != document.sha256:
        return Gate("P002", FAIL, "plan source sha256 does not match the project source")
    if plan.source.get("path") != document.path:
        return Gate("P002", FAIL, f"plan source path {plan.source.get('path')!r} != {document.path!r}")
    return Gate("P002", PASS, f"source {document.sha256[:12]}…, {document.chars} chars")


def _gate_coverage(plan: AdaptationPlan, document: SourceDocument) -> Gate:
    expected = 0
    problems: list[str] = []
    for scene in plan.scenes:
        span = scene.source
        if span.sentence_start != expected:
            problems.append(f"{scene.id} starts at sentence {span.sentence_start}, expected {expected}")
            break
        if span.sentence_end < span.sentence_start:
            problems.append(f"{scene.id} has an empty sentence range")
            break
        if span.sentence_start < 0 or span.sentence_end >= len(document.sentences):
            problems.append(f"{scene.id} sentence range is out of bounds")
            break
        first = document.sentences[span.sentence_start]
        last = document.sentences[span.sentence_end]
        if span.char_start != first.start or span.char_end != last.end:
            problems.append(f"{scene.id} char anchors do not match its sentences")
            break
        expected = span.sentence_end + 1
    if not problems and expected != len(document.sentences):
        problems.append(f"coverage ends at sentence {expected - 1}, source has {len(document.sentences)}")
    if problems:
        return Gate("P003", FAIL, problems[0])
    return Gate("P003", PASS, f"all {len(document.sentences)} sentences covered exactly once")


def _gate_scene_order(plan: AdaptationPlan) -> Gate:
    expected = 1
    previous_episode = 0
    per_episode: dict[int, int] = {}
    for scene in plan.scenes:
        if scene.id != f"S{expected:03d}":
            return Gate("P004", FAIL, f"scene id {scene.id} is not sequential at position {expected}")
        expected += 1
        if scene.episode < 1 or scene.episode > plan.brief.episodes:
            return Gate("P004", FAIL, f"{scene.id} episode {scene.episode} outside 1..{plan.brief.episodes}")
        if scene.episode < previous_episode:
            return Gate("P004", FAIL, f"{scene.id} episode goes backwards")
        previous_episode = scene.episode
        per_episode[scene.episode] = per_episode.get(scene.episode, 0) + 1
        expected_index = per_episode[scene.episode]
        if scene.index_in_episode != expected_index:
            return Gate(
                "P004",
                FAIL,
                f"{scene.id} index_in_episode {scene.index_in_episode} != {expected_index}",
            )
    return Gate("P004", PASS, f"{len(plan.scenes)} sequential scenes")


def _gate_episodes(plan: AdaptationPlan) -> Gate:
    present = {scene.episode for scene in plan.scenes}
    missing = [episode for episode in range(1, plan.brief.episodes + 1) if episode not in present]
    if missing:
        preview = ", ".join(str(value) for value in missing[:10]) + (" …" if len(missing) > 10 else "")
        return Gate("P005", FAIL, f"{len(missing)} episodes have no scene: {preview}")
    return Gate("P005", PASS, f"all {plan.brief.episodes} episodes have scenes")


def _gate_durations(plan: AdaptationPlan) -> Gate:
    bad = [scene.id for scene in plan.scenes if scene.duration_s <= 0]
    if bad:
        return Gate("P006", FAIL, "non-positive duration in: " + ", ".join(bad[:8]), tuple(bad))
    total = plan.total_seconds
    if abs(total - plan.brief.total_seconds) > 0.5:
        return Gate(
            "P006",
            FAIL,
            f"scene durations sum to {total:g}s, target is {plan.brief.total_seconds:g}s",
        )
    return Gate("P006", PASS, f"{total:g}s across {len(plan.scenes)} scenes")


def _gate_cast(plan: AdaptationPlan) -> Gate:
    known = {name for character in plan.cast for name in character.names}
    bad: list[str] = []
    for scene in plan.scenes:
        for name in scene.cast:
            if name not in known:
                bad.append(f"{scene.id}:{name}")
    if bad:
        return Gate("P007", FAIL, "scene cast references unknown characters: " + ", ".join(bad[:8]), tuple(bad[:8]))
    if not plan.cast:
        return Gate("P007", WARN, "cast is empty; dialogue speakers will be hard to validate")
    return Gate("P007", PASS, f"{len(plan.cast)} characters, scene references resolve")


def _gate_beats(plan: AdaptationPlan) -> Gate:
    if plan.brief.format == "feature":
        previous = -1
        for scene in plan.scenes:
            index = beat_index(scene.beat, plan.brief.format)
            if index < 0:
                return Gate("P008", FAIL, f"{scene.id} uses unknown beat {scene.beat!r}")
            if index < previous:
                return Gate("P008", FAIL, f"{scene.id} beat goes backwards")
            previous = index
        return Gate("P008", PASS, "feature beats are monotonic")

    grouped: dict[int, list[Scene]] = {}
    for scene in plan.scenes:
        grouped.setdefault(scene.episode, []).append(scene)
    for episode, scenes in grouped.items():
        previous = -1
        for scene in scenes:
            index = beat_index(scene.beat, plan.brief.format)
            if index < 0:
                return Gate("P008", FAIL, f"{scene.id} uses unknown beat {scene.beat!r}")
            if index < previous:
                return Gate("P008", FAIL, f"{scene.id} beat goes backwards in episode {episode}")
            previous = index
    return Gate("P008", PASS, "per-episode beats are monotonic")


def _gate_chapters(plan: AdaptationPlan, document: SourceDocument) -> Gate:
    referenced = {chapter for scene in plan.scenes for chapter in scene.source.chapter_ids}
    with_sentences = {chapter.id for chapter in document.chapters if chapter.sentence_ids}
    missing = sorted(with_sentences - referenced)
    if missing:
        return Gate("P009", WARN, "chapters with sentences but no scene: " + ", ".join(missing[:8]))
    return Gate("P009", PASS, f"{len(with_sentences)} source chapters referenced")


def _gate_plan_warnings(plan: AdaptationPlan) -> Gate:
    if plan.warnings:
        return Gate("P010", WARN, " | ".join(plan.warnings))
    return Gate("P010", PASS, "no planner warnings")


def _gate_plan_hash(plan: AdaptationPlan, document: SourceDocument) -> Gate:
    expected = plan_hash_for(document.sha256, plan.brief, plan.scenes, plan.cast)
    if plan.plan_hash != expected:
        return Gate("P011", FAIL, "plan_hash does not match the plan content; re-run adapt")
    return Gate("P011", PASS, f"plan_hash {plan.plan_hash[:12]}…")


# ---------------------------------------------------------------------------
# Screenplay gates
# ---------------------------------------------------------------------------


def _gate_screenplay_schema(screenplay: Screenplay) -> Gate:
    if screenplay.schema_version != SCHEMA_VERSION:
        return Gate("S001", FAIL, f"screenplay schema_version {screenplay.schema_version} != {SCHEMA_VERSION}")
    if not screenplay.scenes:
        return Gate("S001", FAIL, "screenplay has no scenes")
    return Gate("S001", PASS, f"{len(screenplay.scenes)} scenes")


def _gate_plan_link(plan: AdaptationPlan, screenplay: Screenplay) -> Gate:
    if screenplay.plan_hash != plan.plan_hash:
        return Gate("S002", FAIL, "screenplay plan_hash does not match adaptation.json")
    if screenplay.source_sha256 != str(plan.source.get("sha256", "")):
        return Gate("S002", FAIL, "screenplay source hash does not match the plan")
    return Gate("S002", PASS, "screenplay is linked to the current plan and source")


def _gate_scene_link(plan: AdaptationPlan, screenplay: Screenplay) -> Gate:
    if len(screenplay.scenes) != len(plan.scenes):
        return Gate(
            "S003",
            FAIL,
            f"screenplay has {len(screenplay.scenes)} scenes, plan has {len(plan.scenes)}",
        )
    for expected, scene in zip(plan.scenes, screenplay.scenes):
        if scene.get("id") != expected.id:
            return Gate("S003", FAIL, f"expected {expected.id}, found {scene.get('id')!r}")
        try:
            episode = int(scene.get("episode", 0))
        except (TypeError, ValueError):
            return Gate("S003", FAIL, f"{expected.id} episode is not an integer")
        if episode != expected.episode:
            return Gate("S003", FAIL, f"{expected.id} episode does not match the plan")
        if scene.get("beat") != expected.beat:
            return Gate("S003", FAIL, f"{expected.id} beat does not match the plan")
        try:
            target = float(scene.get("target_seconds", -1))
        except (TypeError, ValueError):
            return Gate("S003", FAIL, f"{expected.id} target_seconds is not a number")
        if abs(target - expected.duration_s) > 0.01:
            return Gate("S003", FAIL, f"{expected.id} target_seconds does not match the plan")
        source = scene.get("source")
        if not isinstance(source, dict) or source.get("sentence_start") != expected.source.sentence_start:
            return Gate("S003", FAIL, f"{expected.id} source anchor does not match the plan")
    return Gate("S003", PASS, "all scenes match the plan order and anchors")


def _gate_headings(screenplay: Screenplay) -> Gate:
    for scene in screenplay.scenes:
        heading = scene.get("heading")
        label = scene.get("id", "?")
        if not isinstance(heading, dict):
            return Gate("S004", FAIL, f"{label} has no heading")
        if heading.get("int_ext") not in INT_EXT_VALUES:
            return Gate("S004", FAIL, f"{label} heading.int_ext {heading.get('int_ext')!r} is invalid")
        if not str(heading.get("location", "")).strip():
            return Gate("S004", FAIL, f"{label} heading.location is empty")
        if heading.get("time") not in TIME_VALUES:
            return Gate("S004", FAIL, f"{label} heading.time {heading.get('time')!r} is invalid")
    return Gate("S004", PASS, "scene headings are well-formed")


def _gate_bodies(screenplay: Screenplay) -> Gate:
    for scene in screenplay.scenes:
        label = scene.get("id", "?")
        action = scene.get("action")
        dialogue = scene.get("dialogue")
        if not isinstance(action, list) or not isinstance(dialogue, list):
            return Gate("S005", FAIL, f"{label} needs action and dialogue lists")
        if any(not str(block).strip() for block in action):
            return Gate("S005", FAIL, f"{label} has an empty action block")
        for line in dialogue:
            if not isinstance(line, dict) or not str(line.get("line", "")).strip():
                return Gate("S005", FAIL, f"{label} has an empty dialogue line")
            if not str(line.get("character", "")).strip():
                return Gate("S005", FAIL, f"{label} has a dialogue line without a character")
        if not action and not dialogue:
            return Gate("S005", FAIL, f"{label} has neither action nor dialogue")
    return Gate("S005", PASS, "every scene has action or dialogue")


def _gate_speakers(plan: AdaptationPlan, screenplay: Screenplay) -> Gate:
    unknown: list[str] = []
    for scene in screenplay.scenes:
        for line in scene.get("dialogue", []):
            character = str(line.get("character", ""))
            if plan.character(character) is None:
                unknown.append(f"{scene.get('id')}:{character}")
    if unknown:
        return Gate(
            "S006",
            FAIL,
            "dialogue speakers are not in the cast: " + ", ".join(unknown[:8])
            + ". Add them to the cast file or rewrite the line.",
            tuple(unknown[:8]),
        )
    return Gate("S006", PASS, "all dialogue speakers resolve to the cast")


def _gate_basis(screenplay: Screenplay) -> Gate:
    unknown: list[str] = []
    for scene in screenplay.scenes:
        for line in scene.get("dialogue", []):
            if line.get("basis") not in DIALOGUE_BASES:
                unknown.append(f"{scene.get('id')}:{line.get('basis')!r}")
    if unknown:
        return Gate("S007", FAIL, "dialogue basis must be source/adapted/invented: " + ", ".join(unknown[:8]))
    return Gate("S007", PASS, "dialogue provenance is labelled")


def _gate_runtime(plan: AdaptationPlan, screenplay: Screenplay) -> Gate:
    problems: list[str] = []
    total_estimated = 0.0
    for scene in screenplay.scenes:
        target = float(scene.get("target_seconds", 0.0))
        action = tuple(str(item) for item in scene.get("action", []))
        dialogue = tuple(Dialogue.from_dict(item) for item in scene.get("dialogue", []))
        estimated = estimate_draft_seconds(action, dialogue)
        total_estimated += estimated
        if target <= 0:
            continue
        ratio = estimated / target
        if ratio < 0.35 or ratio > 2.5:
            problems.append(f"{scene.get('id')} {estimated:g}s vs target {target:g}s")
    total_target = plan.brief.total_seconds
    total_ratio = total_estimated / total_target if total_target else 1.0
    if total_ratio < 0.7 or total_ratio > 1.3:
        problems.append(f"total {total_estimated:g}s vs target {total_target:g}s ({total_ratio:.2f}x)")
    if problems:
        return Gate("S008", WARN, "runtime estimate is off; review before production: " + "; ".join(problems[:6]))
    return Gate("S008", PASS, f"runtime estimate {total_estimated:g}s / {total_target:g}s")


def _gate_dialogue_presence(screenplay: Screenplay) -> Gate:
    silent = [str(scene.get("id")) for scene in screenplay.scenes if not scene.get("dialogue")]
    if silent:
        return Gate("S009", WARN, "scenes without dialogue (allowed, but check they are intentional): " + ", ".join(silent[:8]))
    return Gate("S009", PASS, "every scene has dialogue")


def _gate_invention(plan: AdaptationPlan, screenplay: Screenplay) -> Gate:
    total = 0
    invented = 0
    for scene in screenplay.scenes:
        for line in scene.get("dialogue", []):
            total += 1
            if line.get("basis") == "invented":
                invented += 1
    if total == 0:
        return Gate("S010", WARN, "no dialogue lines to measure invention ratio")
    ratio = invented / total
    if ratio > 0.4:
        return Gate(
            "S010",
            WARN,
            f"{invented}/{total} dialogue lines are marked invented ({ratio:.0%}); "
            "review for plot drift and character voice",
        )
    return Gate("S010", PASS, f"{invented}/{total} dialogue lines marked invented ({ratio:.0%})")


def _gate_scene_cast(plan: AdaptationPlan, screenplay: Screenplay) -> Gate:
    mismatches: list[str] = []
    for plan_scene, scene in zip(plan.scenes, screenplay.scenes):
        planned = set(plan_scene.cast)
        speakers = {str(line.get("character", "")) for line in scene.get("dialogue", [])}
        extra = sorted(name for name in speakers if name and name not in planned)
        if extra:
            mismatches.append(f"{plan_scene.id}:{','.join(extra)}")
    if mismatches:
        return Gate(
            "S011",
            WARN,
            "draft speakers not detected in the planned scene (may be a detection miss): " + "; ".join(mismatches[:8]),
        )
    return Gate("S011", PASS, "draft speakers are consistent with planned scene cast")

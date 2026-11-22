"""Merge per-scene drafts into a screenplay and compute reviewable statistics."""

from __future__ import annotations

from typing import Any

from .models import AdaptationPlan, AdapterError, Dialogue, SceneDraft, Screenplay, estimate_draft_seconds


def merge_screenplay(plan: AdaptationPlan, drafts: dict[str, SceneDraft]) -> Screenplay:
    missing = [scene.id for scene in plan.scenes if scene.id not in drafts]
    if missing:
        preview = ", ".join(missing[:8]) + (" …" if len(missing) > 8 else "")
        raise AdapterError(f"missing drafts for {len(missing)} scenes: {preview}")
    planned_ids = {scene.id for scene in plan.scenes}
    extras = sorted(set(drafts) - planned_ids)
    if extras:
        preview = ", ".join(extras[:8]) + (" …" if len(extras) > 8 else "")
        raise AdapterError(f"drafts reference scenes that are not in the plan: {preview}")

    stale: list[str] = []
    for scene in plan.scenes:
        draft = drafts[scene.id]
        if not draft.plan_hash or draft.plan_hash != plan.plan_hash:
            stale.append(scene.id)
        if not draft.source_sha256 or draft.source_sha256 != str(plan.source.get("sha256", "")):
            stale.append(scene.id)
    if stale:
        unique = sorted(set(stale))
        preview = ", ".join(unique[:8]) + (" …" if len(unique) > 8 else "")
        raise AdapterError(
            f"{len(unique)} drafts were written against a different plan or source: {preview}. "
            "Re-run draft for those scenes or restore the matching plan."
        )

    scenes: list[dict[str, Any]] = []
    for scene in plan.scenes:
        draft = drafts[scene.id]
        scenes.append(
            {
                "id": scene.id,
                "episode": scene.episode,
                "index_in_episode": scene.index_in_episode,
                "beat": scene.beat,
                "beat_label": scene.beat_label,
                "target_seconds": round(scene.duration_s, 3),
                "estimated_seconds": draft.estimated_seconds(),
                "heading": draft.heading.to_dict(),
                "action": list(draft.action),
                "dialogue": [line.to_dict() for line in draft.dialogue],
                "transition": draft.transition,
                "source": scene.source.to_dict(),
                "writer": {"provider": draft.provider, "model": draft.model},
                "notes": draft.notes,
            }
        )
    screenplay = Screenplay(
        title=plan.title,
        plan_hash=plan.plan_hash,
        source_sha256=str(plan.source.get("sha256", "")),
        scenes=scenes,
    )
    screenplay.stats = screenplay_stats(screenplay)
    return screenplay


def screenplay_stats(screenplay: Screenplay) -> dict[str, Any]:
    dialogue_lines = 0
    action_blocks = 0
    basis = {"source": 0, "adapted": 0, "invented": 0}
    speaking: list[str] = []
    estimated = 0.0
    for scene in screenplay.scenes:
        action_blocks += len(scene.get("action", []))
        for line in scene.get("dialogue", []):
            dialogue_lines += 1
            speaker = str(line.get("character", ""))
            if speaker and speaker not in speaking:
                speaking.append(speaker)
            line_basis = str(line.get("basis", "adapted"))
            if line_basis not in basis:
                line_basis = "adapted"
            basis[line_basis] += 1
        action = tuple(str(item) for item in scene.get("action", []))
        dialogue = tuple(Dialogue.from_dict(item) for item in scene.get("dialogue", []))
        estimated += estimate_draft_seconds(action, dialogue)
    total_target = sum(float(scene.get("target_seconds", 0.0)) for scene in screenplay.scenes)
    total = len(screenplay.scenes)
    return {
        "scene_count": total,
        "episode_count": len({int(scene.get("episode", 0)) for scene in screenplay.scenes}),
        "dialogue_lines": dialogue_lines,
        "action_blocks": action_blocks,
        "characters_speaking": speaking,
        "dialogue_basis": basis,
        "estimated_seconds": round(estimated, 3),
        "target_seconds": round(total_target, 3),
        "average_scene_seconds": round(estimated / total, 3) if total else 0.0,
    }

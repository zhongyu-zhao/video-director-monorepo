"""Export views: Fountain for screenplay tools, Markdown for review.

`screenplay.json` stays the source of truth; both exports are deterministic
views of it.  Fountain notes carry the scene id and source anchor, so a human
can trace a line back to the plan without cluttering the readable text.
"""

from __future__ import annotations

from .draft import screenplay_stats
from .models import AdaptationPlan, Screenplay, SourceDocument

_FOUNTAIN_UNSAFE_STARTS = ("INT.", "EXT.", "EST.", "INT/EXT", "#", "=", ">", ".")


def render_fountain(screenplay: Screenplay, plan: AdaptationPlan) -> str:
    lines: list[str] = [
        f"Title: {screenplay.title}",
        f"Credit: Adapted from {plan.source.get('path', 'source')}",
        "Author: screenplay-adapter (M0 draft)",
        f"Source: {plan.source.get('sha256', '')[:16]}",
        "",
    ]
    current_episode = 0
    for scene in screenplay.scenes:
        episode = int(scene.get("episode", 1))
        if episode != current_episode:
            current_episode = episode
            lines.extend([f"# 第 {episode} 集", ""])
        heading = scene.get("heading", {})
        int_ext = str(heading.get("int_ext", "INT"))
        prefix = "INT./EXT." if int_ext == "INT/EXT" else f"{int_ext}."
        location = str(heading.get("location", "")).strip()
        time_value = str(heading.get("time", "UNKNOWN"))
        lines.extend([f"{prefix} {location} - {time_value}", ""])
        for block in scene.get("action", []):
            text = _escape_action(str(block))
            lines.extend([text, ""])
        for line in scene.get("dialogue", []):
            character = str(line.get("character", "")).strip().upper()
            parenthetical = str(line.get("parenthetical", "")).strip()
            dialogue_line = str(line.get("line", "")).strip()
            lines.append(character)
            if parenthetical:
                if not (parenthetical.startswith("(") and parenthetical.endswith(")")):
                    parenthetical = f"({parenthetical})"
                lines.append(parenthetical)
            lines.append(dialogue_line)
            lines.append("")
        transition = str(scene.get("transition", "")).strip()
        if transition:
            lines.extend([transition.upper(), ""])
        source = scene.get("source", {})
        anchor = (
            f"[[source: {scene.get('id')} | "
            f"{','.join(source.get('chapter_ids', [])) or '?'} | "
            f"{scene.get('target_seconds', 0):g}s]]"
        )
        lines.extend([anchor, ""])
    return "\n".join(lines).rstrip() + "\n"


def render_markdown(screenplay: Screenplay, plan: AdaptationPlan, document: SourceDocument) -> str:
    stats = screenplay.stats or screenplay_stats(screenplay)
    lines: list[str] = [
        f"# {screenplay.title} · 剧本草稿",
        "",
        f"> 由确定性改编计划生成，共 {stats.get('scene_count', len(screenplay.scenes))} 场 / "
        f"{stats.get('episode_count', plan.brief.episodes)} 集；估算时长 "
        f"{stats.get('estimated_seconds', 0) / 60:.1f} 分钟，目标 "
        f"{plan.brief.total_minutes:g} 分钟。",
        "",
        "## 项目参数",
        "",
        f"- 格式：`{plan.brief.format}`，{plan.brief.episodes} 集 × {plan.brief.episode_minutes:g} 分钟",
        f"- 类型：{plan.brief.genre or '未指定'}；画幅：{plan.brief.aspect}；语言：{plan.brief.language}",
        f"- 原文：`{plan.source.get('path')}`（{plan.source.get('chars', 0)} 字符）",
        "",
    ]
    current_episode = 0
    for scene in screenplay.scenes:
        episode = int(scene.get("episode", 1))
        if episode != current_episode:
            current_episode = episode
            lines.extend([f"## 第 {episode} 集", ""])
        heading = scene.get("heading", {})
        lines.extend(
            [
                f"### {scene.get('id')} · 第 {episode} 集第 {scene.get('index_in_episode')} 场 · "
                f"{scene.get('beat_label', scene.get('beat'))}",
                "",
                f"**{heading.get('int_ext')}. {heading.get('location')} - {heading.get('time')}**",
                "",
            ]
        )
        for block in scene.get("action", []):
            lines.extend([str(block), ""])
        for line in scene.get("dialogue", []):
            parenthetical = str(line.get("parenthetical", "")).strip()
            suffix = f"（{parenthetical}）" if parenthetical else ""
            lines.extend([f"**{line.get('character')}**{suffix}：{line.get('line')}", ""])
        transition = str(scene.get("transition", "")).strip()
        if transition:
            lines.extend([f"*{transition}*", ""])
        source = scene.get("source", {})
        sentence_start = int(source.get("sentence_start", 0))
        sentence_end = int(source.get("sentence_end", sentence_start))
        excerpt = _source_slice(document, source)
        lines.extend(
            [
                f"<sub>来源：{', '.join(source.get('chapter_ids', [])) or '—'} · "
                f"句 {sentence_start + 1}–{sentence_end + 1} · 目标 {scene.get('target_seconds', 0):g}s · "
                f"估算 {scene.get('estimated_seconds', 0):g}s · 对白新增/改写/来源 "
                f"{_basis_counts(scene)}</sub>",
                "",
                f"> {excerpt}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _escape_action(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith(_FOUNTAIN_UNSAFE_STARTS):
        return "!" + stripped
    return stripped


def _basis_counts(scene: dict) -> str:
    counts = {"source": 0, "adapted": 0, "invented": 0}
    for line in scene.get("dialogue", []):
        basis = str(line.get("basis", "adapted"))
        counts[basis if basis in counts else "adapted"] += 1
    return f"{counts['invented']}/{counts['adapted']}/{counts['source']}"


def _source_slice(document: SourceDocument, source: dict) -> str:
    sentence_start = int(source.get("sentence_start", 0))
    sentence_end = int(source.get("sentence_end", sentence_start))
    text = " ".join(
        document.sentences[index].text for index in range(sentence_start, min(sentence_end + 1, len(document.sentences)))
    ).strip()
    if len(text) > 320:
        text = text[:320].rstrip() + "…"
    return text or "（无原文片段）"

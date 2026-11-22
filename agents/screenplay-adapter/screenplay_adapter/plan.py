"""Build the adaptation plan: cast, scenes, beats, durations and coverage.

The plan is deterministic.  It never writes dialogue or invents a character; it
decides where scenes start and end in the source, how long each scene should
run, which structural beat it serves, and what must be expanded or compressed.
The writer (LLM or human) fills each scene afterwards.
"""

from __future__ import annotations

import math
from dataclasses import replace

from .beats import beat_for, beat_guidance, beats_for
from .cast import find_characters
from .source import scene_source_text
from .models import (
    DEFAULT_FORMAT_PRESETS,
    FORMATS,
    AdaptationBrief,
    AdaptationPlan,
    AdapterError,
    Character,
    Scene,
    SourceDocument,
    SourceSpan,
    plan_hash_for,
)

_DIALOGUE_QUOTES = "“”\"「」『』"
_EXPANSION_NOTES = {
    "compress": "原文信息密度高于目标时长：改写时要做选择、合并或删除，不要照抄叙述。",
    "expand": "原文信息量低于目标时长：需要补动作、反应和对白；新增内容不得改变既有事实。",
    "add_dialogue": "原文没有直接引语：考虑用对白或可见动作外化，而不是旁白复述。",
    "establish_cast": "场景里没有检测到人物表中的角色：写之前先确定谁在场、为什么在场。",
    "crowded_cast": "出场人物较多：考虑聚焦 2–3 人，或拆成两场，避免一场戏没有主次。",
    "split_scene": "时长超过 5 分钟：考虑拆成两场或压缩，避免单场承载过多信息。",
}


def make_brief(
    title: str,
    format: str,
    *,
    episodes: int | None = None,
    episode_minutes: float | None = None,
    scene_seconds: float | None = None,
    genre: str = "",
    logline: str = "",
    audience: str = "",
    aspect: str = "vertical",
    language: str = "zh",
    mode: str = "adapt",
) -> AdaptationBrief:
    if format not in FORMATS:
        raise AdapterError(f"format must be one of {', '.join(FORMATS)}")
    preset = DEFAULT_FORMAT_PRESETS[format]
    resolved_episodes = int(episodes if episodes is not None else preset["episodes"])
    resolved_minutes = float(episode_minutes if episode_minutes is not None else preset["episode_minutes"])
    resolved_scene = float(scene_seconds if scene_seconds is not None else preset["scene_seconds"])
    if resolved_episodes < 1:
        raise AdapterError("episodes must be at least 1")
    if resolved_minutes <= 0:
        raise AdapterError("episode_minutes must be positive")
    if resolved_scene <= 0:
        raise AdapterError("scene_seconds must be positive")
    if format == "feature" and resolved_episodes != 1:
        raise AdapterError("feature format has exactly one episode; use series or short-drama for multiple episodes")
    if aspect not in ("vertical", "horizontal"):
        raise AdapterError("aspect must be 'vertical' or 'horizontal'")
    if language not in ("zh", "en", "auto"):
        raise AdapterError("language must be zh, en or auto")
    if mode not in ("adapt", "expand"):
        raise AdapterError("mode must be adapt or expand")
    return AdaptationBrief(
        title=title.strip(),
        format=format,
        episodes=resolved_episodes,
        episode_minutes=resolved_minutes,
        scene_seconds=resolved_scene,
        genre=genre.strip(),
        logline=logline.strip(),
        audience=audience.strip(),
        aspect=aspect,
        language=language,
        mode=mode,
    )


def build_plan(document: SourceDocument, brief: AdaptationBrief, cast: list[Character]) -> AdaptationPlan:
    if not brief.title:
        raise AdapterError("title is required")
    total_seconds = brief.total_seconds
    if total_seconds <= 0:
        raise AdapterError("target duration must be positive")
    requested = max(1, int(round(total_seconds / brief.scene_seconds)))
    sentence_count = len(document.sentences)
    count = max(1, min(requested, sentence_count))
    if count < requested:
        warnings = [
            f"source only has {sentence_count} sentences; planned {count} scenes instead of {requested}. "
            "The source is too sparse for this duration unless it is expanded externally."
        ]
    else:
        warnings = []
    if count < brief.episodes:
        warnings.append(
            f"planned {count} scenes for {brief.episodes} episodes; some episodes will have no scene. "
            "Reduce episodes, shorten episode duration, or add source material."
        )

    groups, requested_groups = partition_document(document, count)
    count = len(groups)
    if requested_groups != count:
        warnings.append(
            f"source chapters are too sparse for {requested_groups} scenes; planned {count} instead."
        )
    durations = _durations(total_seconds, count)
    global_density = document.chars / total_seconds if total_seconds else 0.0
    resolved_language = (document.language if document.language in ("zh", "en") else "zh") if brief.language == "auto" else brief.language
    brief = replace(brief, language=resolved_language)

    episode_for_scene = [
        min(brief.episodes, (index - 1) * brief.episodes // count + 1) for index in range(1, count + 1)
    ]
    episode_totals: dict[int, int] = {}
    for episode in episode_for_scene:
        episode_totals[episode] = episode_totals.get(episode, 0) + 1

    scenes: list[Scene] = []
    episode_indexes: dict[int, int] = {}
    for index, (start, end) in enumerate(groups, start=1):
        duration = durations[index - 1]
        episode = episode_for_scene[index - 1]
        episode_indexes[episode] = episode_indexes.get(episode, 0) + 1
        scene_id = f"S{index:03d}"
        first_sentence = document.sentences[start]
        last_sentence = document.sentences[end - 1]
        text = "\n".join(document.sentences[i].text for i in range(start, end))
        if brief.format == "feature":
            progress = (index - 1) / (count - 1) if count > 1 else 0.0
        else:
            position = episode_indexes[episode]
            total_in_episode = episode_totals[episode]
            progress = (position - 1) / (total_in_episode - 1) if total_in_episode > 1 else 0.0
        beat = beat_for(progress, beats_for(brief.format))
        scene_cast = find_characters(text, cast)
        flags = _expansion_flags(text, duration, global_density, scene_cast)
        if brief.mode == "expand" and "compress" not in flags and "expand" not in flags:
            flags.insert(0, "expand")
        span = SourceSpan(
            sentence_start=start,
            sentence_end=end - 1,
            char_start=first_sentence.start,
            char_end=last_sentence.end,
            chapter_ids=tuple(_unique(document.sentences[i].chapter_id for i in range(start, end))),
            paragraph_ids=tuple(_unique(document.sentences[i].paragraph_id for i in range(start, end))),
            excerpt=_excerpt(text, 240),
        )
        scenes.append(
            Scene(
                id=scene_id,
                episode=episode,
                index_in_episode=episode_indexes[episode],
                beat=beat.id,
                beat_label=beat.label,
                duration_s=duration,
                source=span,
                cast=tuple(scene_cast),
                expansion=tuple(flags),
                notes=tuple(_EXPANSION_NOTES[flag] for flag in flags),
            )
        )

    plan = AdaptationPlan(
        title=brief.title,
        brief=brief,
        source=document.meta(),
        cast=cast,
        scenes=scenes,
        requested_scenes=requested,
        warnings=warnings,
    )
    plan.plan_hash = plan_hash_for(document.sha256, brief, scenes, cast)
    return plan


def partition_document(document, count: int) -> tuple[list[tuple[int, int]], int]:
    """Split the document into scene ranges, preferring chapter boundaries.

    When there are enough scenes for every chapter, each chapter gets at least
    one scene and large chapters are subdivided.  When there are fewer scenes
    than chapters, contiguous chapters are grouped first and each group becomes
    one scene, so a scene never starts in the middle of a chapter heading.
    """

    ranges = _chapter_sentence_ranges(document)
    if not ranges:
        raise AdapterError("source has no sentences")
    if count <= len(ranges):
        weights = [_range_chars(document.sentences, start, end) for start, end in ranges]
        chapter_groups = _partition_by_weights(weights, count)
        groups: list[tuple[int, int]] = []
        for group in chapter_groups:
            start = ranges[group[0]][0]
            end = ranges[group[-1]][1]
            groups.extend(partition_sentences(document.sentences, 1, start, end))
        return groups, count

    weights = [_range_chars(document.sentences, start, end) for start, end in ranges]
    quotas = _allocate_quotas(weights, count)
    for index, (start, end) in enumerate(ranges):
        quotas[index] = min(quotas[index], end - start)
    leftover = count - sum(quotas)
    while leftover > 0:
        candidates = [index for index, (start, end) in enumerate(ranges) if quotas[index] < end - start]
        if not candidates:
            break
        index = max(candidates, key=lambda value: weights[value] / (quotas[value] + 1))
        quotas[index] += 1
        leftover -= 1
    groups = []
    for (start, end), quota in zip(ranges, quotas):
        groups.extend(partition_sentences(document.sentences, quota, start, end))
    return groups, count - leftover


def _chapter_sentence_ranges(document) -> list[tuple[int, int]]:
    by_id = {sentence.id: index for index, sentence in enumerate(document.sentences)}
    ranges: list[tuple[int, int]] = []
    for chapter in document.chapters:
        indexes = [by_id[sentence_id] for sentence_id in chapter.sentence_ids if sentence_id in by_id]
        if indexes:
            ranges.append((min(indexes), max(indexes) + 1))
    return ranges


def _range_chars(sentences, start: int, end: int) -> int:
    return sum(len(sentences[index].text) for index in range(start, end))


def _partition_by_weights(weights: list[int], count: int) -> list[list[int]]:
    if count >= len(weights):
        return [[index] for index in range(len(weights))]
    total = sum(weights)
    if total <= 0:
        total = len(weights)
        weights = [1] * len(weights)
    groups: list[list[int]] = []
    start = 0
    for group in range(count - 1):
        remaining = count - group
        target = total * (group + 1) / count
        best_end = start + 1
        best_distance = math.inf
        cumulative = 0
        last_index = len(weights) - remaining
        for index in range(start, last_index + 1):
            cumulative += weights[index]
            distance = abs(cumulative - target)
            if distance < best_distance:
                best_distance = distance
                best_end = index + 1
            if cumulative >= target:
                break
        groups.append(list(range(start, best_end)))
        start = best_end
    groups.append(list(range(start, len(weights))))
    return groups


def _allocate_quotas(weights: list[int], count: int) -> list[int]:
    quotas = [1] * len(weights)
    total = sum(weights) or len(weights)
    if not weights:
        return quotas
    weights = weights or [1] * len(weights)
    remaining = count - len(weights)
    while remaining > 0:
        index = max(
            range(len(weights)),
            key=lambda value: weights[value] / total - quotas[value],
        )
        quotas[index] += 1
        remaining -= 1
    return quotas


def partition_sentences(sentences: list, count: int, start: int | None = None, end: int | None = None) -> list[tuple[int, int]]:
    """Split sentence indexes into `count` contiguous, non-empty groups.

    Boundaries are chosen near equal character shares so each scene has a
    comparable amount of source material.  Callers normally partition within a
    chapter; a range that spans chapters is allowed for very short sources.
    """

    if start is None:
        start = 0
    if end is None:
        end = len(sentences)
    if count < 1:
        raise AdapterError("scene count must be positive")
    if count > end - start:
        raise AdapterError("cannot create more scenes than sentences in the range")
    if count == end - start:
        return [(index, index + 1) for index in range(start, end)]

    total_chars = sum(len(sentences[index].text) for index in range(start, end))
    boundaries: list[int] = []
    range_start = start
    cursor = start
    for group in range(count - 1):
        remaining_groups = count - group
        target = total_chars * (group + 1) / count
        best_end = cursor + 1
        best_distance = math.inf
        cumulative = 0
        last_index = end - remaining_groups
        for index in range(cursor, last_index + 1):
            cumulative += len(sentences[index].text)
            distance = abs(cumulative - target)
            if distance < best_distance:
                best_distance = distance
                best_end = index + 1
            if cumulative >= target:
                break
        boundaries.append(best_end)
        cursor = best_end
    boundaries.append(end)
    groups = []
    previous = range_start
    for boundary in boundaries:
        groups.append((previous, boundary))
        previous = boundary
    return groups


def _durations(total_seconds: float, count: int) -> list[float]:
    base = round(total_seconds / count, 3)
    durations = [base] * (count - 1)
    durations.append(round(total_seconds - base * (count - 1), 3))
    return durations


def _expansion_flags(text: str, duration: float, global_density: float, scene_cast: list[str]) -> list[str]:
    flags: list[str] = []
    density = len(text) / duration if duration else 0.0
    if global_density and density > global_density * 1.6:
        flags.append("compress")
    if global_density and density < global_density * 0.6:
        flags.append("expand")
    if not any(quote in text for quote in _DIALOGUE_QUOTES):
        flags.append("add_dialogue")
    if not scene_cast:
        flags.append("establish_cast")
    if len(scene_cast) >= 5:
        flags.append("crowded_cast")
    if duration > 300:
        flags.append("split_scene")
    return flags


def _unique(values) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _excerpt(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "…"


def render_briefs(plan: AdaptationPlan, document: SourceDocument) -> str:
    brief = plan.brief
    lines: list[str] = [
        f"# 逐场写作 brief：{plan.title}",
        "",
        "本文件由确定性改编计划生成，不是剧本正文。每场只给写作器提供必要的原文、结构位置、人物和目标时长。",
        "",
        "## 项目参数",
        "",
        "| 字段 | 值 |",
        "|---|---|",
        f"| 格式 | `{brief.format}` |",
        f"| 集数 | {brief.episodes} |",
        f"| 单集时长 | {brief.episode_minutes:g} 分钟 |",
        f"| 总目标时长 | {brief.total_minutes:g} 分钟 |",
        f"| 目标单场时长 | {brief.scene_seconds:g} 秒 |",
        f"| 模式 | `{brief.mode}` |",
        f"| 画幅 | {brief.aspect} |",
        f"| 语言 | {brief.language} |",
        f"| 类型 | {brief.genre or '未指定'} |",
        f"| 受众 | {brief.audience or '未指定'} |",
        "",
    ]
    if brief.logline:
        lines.extend([f"**一句话故事**：{brief.logline}", ""])
    lines.extend(
        [
            "## 全局硬约束",
            "",
            "- 不得新增人物表中没有的有名角色；需要新角色时先改人物表，不要直接在剧本里出现。",
            "- 每场必须发生在原文锚点覆盖的事件范围内；新增的动作/对白只能用于外化和补过程，不能改变既有事实。",
            "- 场景头写 `内/外景 · 地点 · 日夜`；每场至少一个动作块或一句对白。",
            "- 对白用 `basis` 标注：`source` 来自原文，`adapted` 由原文改写，`invented` 为新增。",
            "- 输出 JSON，不要输出 Markdown 代码围栏。",
            "",
            "## 人物表",
            "",
            "| ID | 姓名 | 别名 | 首次出现 | 对白提及 | 来源 |",
            "|---|---|---|---|---|---|",
        ]
    )
    for character in plan.cast:
        aliases = "、".join(character.aliases) or "—"
        lines.append(
            f"| {character.id} | {character.name} | {aliases} | {character.first_chapter or '—'} | "
            f"{character.dialogue_mentions} | {character.source} |"
        )
    lines.append("")

    current_episode = 0
    for scene in plan.scenes:
        if scene.episode != current_episode:
            current_episode = scene.episode
            lines.extend([f"## 第 {current_episode} 集", ""])
        source_text = _excerpt(scene_source_text(document, scene).strip(), 4000)
        lines.extend(
            [
                f"### {scene.id} · 第 {scene.episode} 集第 {scene.index_in_episode} 场 · {scene.beat_label}",
                "",
                f"- 目标时长：{scene.duration_s:g} 秒",
                f"- 结构功能：{beat_guidance(scene.beat, brief.format) or scene.beat_label}",
                f"- 来源：{', '.join(scene.source.chapter_ids)} / "
                f"{', '.join(scene.source.paragraph_ids[:6])}"
                f"{' …' if len(scene.source.paragraph_ids) > 6 else ''}",
                f"- 已知在场人物：{'、'.join(scene.cast) if scene.cast else '未检测到'}",
            ]
        )
        for note in scene.notes:
            lines.append(f"- 注意：{note}")
        lines.extend(["", "原文片段：", "", "> " + source_text.replace("\n", "\n> "), ""])
    lines.append("")
    return "\n".join(lines)

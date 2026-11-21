"""Narrative scene reduction over per-shot VLM labels.

This is a text reduce, not another image-by-image labeling pass: the
model sees compact per-shot audiovisual labels and action descriptions
and returns contiguous narrative scenes with titles/summaries.  The
result is validated to cover every shot exactly once; invalid output is
rejected so the deterministic grouping remains the fallback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from .models import ShotTable

PROMPT_VERSION = "narrative-scenes-v1"
MAX_TOKENS = 8000


class SceneReduceError(RuntimeError):
    """Raised when the model's scene plan does not cover the shot table."""


class TextClient(Protocol):
    def complete_text(self, prompt: str, max_tokens: int = MAX_TOKENS) -> dict[str, Any]:
        """Return one parsed JSON object for a text prompt."""


def _shot_lines(
    table: ShotTable,
    labels: dict[str, Any],
    only_ids: set[str] | None = None,
) -> str:
    lines = []
    for shot in table.shots:
        if only_ids is not None and shot.shot_id not in only_ids:
            continue
        entry = labels.get("shots", {}).get(shot.shot_id, {})
        values = entry.get("labels", {})
        content = entry.get("content", {})
        subjects = "、".join(content.get("subjects", [])) if content else ""
        action = (content.get("action") or "") if content else ""
        if len(action) > 70:
            action = action[:70] + "…"
        lines.append(
            " | ".join(
                [
                    shot.shot_id,
                    values.get("scale", "unknown"),
                    values.get("camera", "unknown"),
                    values.get("lighting", "unknown"),
                    values.get("color", "unknown"),
                    f"主体:{subjects or '—'}",
                    f"动作:{action or '—'}",
                ]
            )
        )
    return "\n".join(lines)


def build_boundary_prompt(table: ShotTable, labels: dict[str, Any]) -> str:
    return f"""下面是一部影片按时间顺序的 {len(table.shots)} 个镜头，每行：
镜号 | 景别 | 运镜 | 光线 | 色彩 | 主体 | 动作

请按**视听语言 + 叙事场景**只给出场景起点，不要逐镜输出，也不要写摘要：
- 同一时间/地点/人物关系/情节单元通常同一场景；
- 景别/机位/光线/色彩持续突变，或主体/动作切到另一组人物/地点，可作为边界证据；
- 不要按固定镜数切；目标 15–30 个场景，每个场景至少 2 镜；
- 第一个场景必须从 S001 开始，所有镜头连续覆盖，不重叠/不遗漏；
- 只输出 JSON：{{"scenes":[{{"start_shot":"S001","title":"不超过 15 字的场景标题"}}]}}
不要输出 end_shot；下一场景的 start 就是上一场景的结束。

镜头表：
{_shot_lines(table, labels)}"""


def summarize_existing(
    table: ShotTable,
    labels: dict[str, Any],
    scenes: list[dict[str, Any]],
    client: TextClient,
    max_tokens: int = MAX_TOKENS,
) -> list[dict[str, Any]]:
    """Attach narrative titles/summaries to an existing contiguous scene plan."""
    boundaries = []
    for index, scene in enumerate(scenes):
        shot_ids = scene.get("shot_ids", [])
        if not shot_ids:
            continue
        boundaries.append(
            {
                "scene_id": scene.get("scene_id", f"SC{index + 1:03d}"),
                "start_shot": shot_ids[0],
                "end_shot": shot_ids[-1],
                "title": scene.get("title") or f"场景 {index + 1}",
            }
        )
    result: list[dict[str, Any]] = []
    for start in range(0, len(boundaries), 6):
        chunk = boundaries[start : start + 6]
        only_ids = set()
        for item in chunk:
            start_index = next(i for i, shot in enumerate(table.shots) if shot.shot_id == item["start_shot"])
            end_index = next(i for i, shot in enumerate(table.shots) if shot.shot_id == item["end_shot"])
            only_ids.update(shot.shot_id for shot in table.shots[start_index : end_index + 1])
        result.extend(_attach_summaries(table, labels, chunk, client, max_tokens, only_ids))
    return result


def build_summary_prompt(
    table: ShotTable,
    labels: dict[str, Any],
    boundaries: list[dict[str, Any]],
    only_ids: set[str] | None = None,
) -> str:
    ranges = []
    by_id = {shot.shot_id: index for index, shot in enumerate(table.shots)}
    for index, item in enumerate(boundaries):
        start = item["start_shot"]
        end = boundaries[index + 1]["start_shot"] if index + 1 < len(boundaries) else None
        if end is None:
            end_shot = table.shots[-1].shot_id
        else:
            end_shot = table.shots[by_id[end] - 1].shot_id
        ranges.append(f'{item["scene_id"]}: {start}–{end_shot} · {item["title"]}')
    return f"""下面已经按视听语言/叙事给了 {len(boundaries)} 个场景，请为每个场景写一个不超过 15 字的叙事标题、1–2 句摘要（不超过 80 字）和一句边界理由。
不要改场景边界，不要增加/删除场景。只输出 JSON：
{{"scenes":[{{"scene_id":"SC001","title":"场景标题","summary":"这一场发生了什么","boundary_reason":"为什么下一场开始新场景"}}]}}

场景：
{chr(10).join(ranges)}

镜头详细：
{_shot_lines(table, labels, only_ids)}"""


def reduce_scenes(
    table: ShotTable,
    labels: dict[str, Any],
    client: TextClient,
    max_tokens: int = MAX_TOKENS,
) -> list[dict[str, Any]]:
    if not labels.get("shots"):
        raise SceneReduceError("no per-shot labels to reduce")
    boundaries = _reduce_boundaries(table, labels, client)
    scenes = _attach_summaries(table, labels, boundaries, client, max_tokens)
    return validate_plan(table, scenes)


def _reduce_boundaries(
    table: ShotTable,
    labels: dict[str, Any],
    client: TextClient,
) -> list[dict[str, Any]]:
    payload = client.complete_text(build_boundary_prompt(table, labels), max_tokens=8000)
    raw = payload.get("scenes") if isinstance(payload, dict) else None
    if not isinstance(raw, list) or not raw:
        raise SceneReduceError("model returned no boundary scenes")
    ids = {shot.shot_id: index for index, shot in enumerate(table.shots)}
    starts: list[dict[str, Any]] = []
    previous = -1
    for item in raw:
        if not isinstance(item, dict):
            raise SceneReduceError("boundary entry must be an object")
        start = item.get("start_shot")
        title = item.get("title")
        if start not in ids or not isinstance(title, str) or not title.strip():
            raise SceneReduceError(f"invalid boundary {item!r}")
        index = ids[start]
        if index <= previous:
            raise SceneReduceError(f"boundary shots not strictly increasing at {start}")
        starts.append({"start_shot": start, "title": title.strip()})
        previous = index
    if starts[0]["start_shot"] != table.shots[0].shot_id:
        raise SceneReduceError("first scene must start at the first shot")
    if len(starts) < 2 or len(starts) > 60:
        raise SceneReduceError(f"scene count {len(starts)} outside 2..60; ask for a coarser plan")
    # Derive the contiguous end for each start; only the summary step needs
    # the explicit ranges, the final plan is checked by validate_plan.
    result = []
    for index, item in enumerate(starts):
        end_index = ids[starts[index + 1]["start_shot"]] - 1 if index + 1 < len(starts) else len(table.shots) - 1
        result.append(
            {
                "scene_id": f"SC{index + 1:03d}",
                "start_shot": item["start_shot"],
                "end_shot": table.shots[end_index].shot_id,
                "title": item["title"],
            }
        )
    return result


def _attach_summaries(
    table: ShotTable,
    labels: dict[str, Any],
    boundaries: list[dict[str, Any]],
    client: TextClient,
    max_tokens: int,
    only_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    payload = client.complete_text(
        build_summary_prompt(table, labels, boundaries, only_ids), max_tokens=max_tokens
    )
    raw = payload.get("scenes") if isinstance(payload, dict) else None
    by_id = {item["scene_id"]: item for item in boundaries}
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("scene_id") in by_id:
                title = item.get("title")
                if isinstance(title, str) and title.strip():
                    by_id[item["scene_id"]]["title"] = title.strip()
                summary = item.get("summary")
                if isinstance(summary, str) and summary.strip():
                    by_id[item["scene_id"]]["summary"] = summary.strip()
                reason = item.get("boundary_reason")
                if isinstance(reason, str):
                    by_id[item["scene_id"]]["boundary_reason"] = reason.strip()
    result = []
    for item in boundaries:
        scene = dict(item)
        if not scene.get("summary"):
            scene["summary"] = scene["title"]
        result.append(scene)
    return result


def validate_plan(table: ShotTable, scenes: list[Any]) -> list[dict[str, Any]]:
    index_by_id = {shot.shot_id: index for index, shot in enumerate(table.shots)}
    cursor = 0
    cleaned: list[dict[str, Any]] = []
    for raw in scenes:
        if not isinstance(raw, dict):
            raise SceneReduceError("scene entry must be an object")
        start_id = raw.get("start_shot")
        end_id = raw.get("end_shot")
        if start_id not in index_by_id or end_id not in index_by_id:
            raise SceneReduceError(f"unknown shot id in scene {raw!r}")
        start = index_by_id[start_id]
        end = index_by_id[end_id]
        if start != cursor or end < start:
            raise SceneReduceError(
                f"scene coverage gap/overlap at {start_id}-{end_id}; expected start {table.shots[cursor].shot_id if cursor < len(table.shots) else 'end'}"
            )
        title = raw.get("title")
        summary = raw.get("summary")
        if not isinstance(title, str) or not title.strip():
            raise SceneReduceError("scene title must be non-empty")
        if not isinstance(summary, str) or not summary.strip():
            raise SceneReduceError("scene summary must be non-empty")
        cleaned.append(
            {
                "start_shot": start_id,
                "end_shot": end_id,
                "title": title.strip(),
                "summary": summary.strip(),
                "boundary_reason": str(raw.get("boundary_reason", "")).strip(),
            }
        )
        cursor = end + 1
    if cursor != len(table.shots):
        raise SceneReduceError(
            f"scene plan covers {cursor}/{len(table.shots)} shots; last scene must end at {table.shots[-1].shot_id}"
        )
    return cleaned


def save_plan(path: str | Path, plan: list[dict[str, Any]], table: ShotTable, labels: dict[str, Any]) -> None:
    payload = {
        "schema_version": 1,
        "prompt_version": PROMPT_VERSION,
        "video": table.video.path,
        "shots": len(table.shots),
        "labels_shots": len(labels.get("shots", {})),
        "scenes": plan,
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_plan(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("prompt_version") != PROMPT_VERSION:
        raise SceneReduceError("scene plan prompt version mismatch")
    scenes = payload.get("scenes")
    if not isinstance(scenes, list):
        raise SceneReduceError("scene plan has no scenes")
    return scenes


def _timecode(seconds: float) -> str:
    total = max(0, round(seconds))
    minutes, sec = divmod(total, 60)
    return f"{minutes:02d}:{sec:02d}"

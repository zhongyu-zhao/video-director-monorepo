"""Reconstruct a readable screenplay draft from shots, labels, scenes and ASR.

This is deliberately an evidence-backed draft, not a fabricated polished
script: shot descriptions come from measured/labeled facts, dialogue comes
from the ASR transcript, and the header marks the transcript as automatic
and speaker-agnostic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .models import Shot, ShotTable, round_time

SCREENPLAY_SCHEMA_VERSION = 1


class TextClient(Protocol):
    def complete_text(self, prompt: str, max_tokens: int = 8000) -> dict[str, Any]:
        """Return one parsed JSON object for a text prompt."""


class ScreenplayError(RuntimeError):
    """Raised when the screenplay inputs are not usable."""


@dataclass
class ScreenplayResult:
    output_dir: Path
    markdown_path: Path
    json_path: Path
    scenes: list[dict[str, Any]]


def build_screenplay(
    table: ShotTable,
    output_dir: str | Path,
    labels: dict[str, Any] | None = None,
    scenes: dict[str, Any] | None = None,
    asr: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
) -> ScreenplayResult:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    label_map = labels.get("shots", {}) if labels else {}
    evidence_map = evidence.get("shots", {}) if evidence else {}
    segments = _segments(asr)
    scene_list = scenes.get("scenes", []) if scenes else []

    if not scene_list:
        scene_list = [
            {
                "scene_id": "SC001",
                "start": 0.0,
                "end": table.video.duration,
                "shot_ids": [shot.shot_id for shot in table.shots],
                "title": "未聚合场景",
                "summary": "",
                "stats": {},
            }
        ]

    shot_to_scene: dict[str, str] = {}
    for scene in scene_list:
        for shot_id in scene.get("shot_ids", []):
            shot_to_scene[shot_id] = scene["scene_id"]

    segments_by_shot: dict[str, list[dict[str, Any]]] = {shot.shot_id: [] for shot in table.shots}
    for segment in segments:
        shot = _shot_at(table, (segment["start"] + segment["end"]) / 2)
        if shot is not None:
            segments_by_shot[shot.shot_id].append(segment)

    payload_scenes: list[dict[str, Any]] = []
    for scene in scene_list:
        entries = []
        for shot_id in scene.get("shot_ids", []):
            shot = next((item for item in table.shots if item.shot_id == shot_id), None)
            if shot is None:
                continue
            entries.append(
                {
                    "shot_id": shot.shot_id,
                    "start": round_time(shot.start),
                    "end": round_time(shot.end),
                    "duration": shot.duration,
                    "labels": label_map.get(shot_id, {}).get("labels", {}),
                    "content": label_map.get(shot_id, {}).get("content", {}),
                    "measured": evidence_map.get(shot_id, {}).get("measured", {}),
                    "dialogue": segments_by_shot.get(shot_id, []),
                }
            )
        payload_scenes.append(
            {
                "scene_id": scene["scene_id"],
                "title": scene.get("title", ""),
                "summary": scene.get("summary", ""),
                "start": round_time(float(scene.get("start", 0.0))),
                "end": round_time(float(scene.get("end", table.video.duration))),
                "shots": entries,
            }
        )

    payload = {
        "schema_version": SCREENPLAY_SCHEMA_VERSION,
        "video": {
            "path": table.video.path,
            "duration": round_time(table.video.duration),
        },
        "asr": {
            "model": (asr or {}).get("model"),
            "language": (asr or {}).get("language"),
            "segments": len(segments),
            "automatic": True,
            "diarized": False,
        },
        "scenes": payload_scenes,
    }
    json_path = destination / "screenplay.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path = destination / "screenplay.md"
    markdown_path.write_text(_render(payload, table), encoding="utf-8")
    return ScreenplayResult(
        output_dir=destination,
        markdown_path=markdown_path,
        json_path=json_path,
        scenes=payload_scenes,
    )


def translate_segments(
    segments: list[dict[str, Any]],
    client: TextClient,
    batch_size: int = 30,
) -> list[dict[str, Any]]:
    """Add a Chinese translation to ASR segments, preserving ids/times."""
    result = [dict(segment) for segment in segments]
    for start in range(0, len(result), batch_size):
        batch = result[start : start + batch_size]
        lines = "\n".join(f'{index + 1}. {item["text"]}' for index, item in enumerate(batch))
        prompt = f"""把下面的日语 ASR 逐条翻译成简体中文，保留编号，不要合并/拆分，不要解释。
只输出 JSON：{{"segments":[{{"id":1,"text":"中文翻译"}}]}}

{lines}"""
        payload = client.complete_text(prompt, max_tokens=4000)
        raw = payload.get("segments") if isinstance(payload, dict) else None
        if not isinstance(raw, list):
            raise ScreenplayError("translation response has no segments")
        by_id = {item.get("id"): item.get("text") for item in raw if isinstance(item, dict)}
        for index, item in enumerate(batch, start=1):
            translated = by_id.get(index)
            if isinstance(translated, str) and translated.strip():
                item["text_zh"] = translated.strip()
    return result


def _segments(asr: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not asr:
        return []
    raw = asr.get("segments", [])
    if not isinstance(raw, list):
        raise ScreenplayError("ASR segments must be a list")
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item["start"])
            end = float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        text = str(item.get("text", "")).strip()
        if text and end > start:
            item_out = {"start": round(start, 3), "end": round(end, 3), "text": text}
            if isinstance(item.get("text_zh"), str) and item["text_zh"].strip():
                item_out["text_zh"] = item["text_zh"].strip()
            result.append(item_out)
    return sorted(result, key=lambda item: item["start"])


def _shot_at(table: ShotTable, time: float) -> Shot | None:
    for shot in table.shots:
        if shot.start <= time < shot.end:
            return shot
    return None


def _render(payload: dict[str, Any], table: ShotTable) -> str:
    lines = [
        "# 剧本还原（自动转写草稿）",
        "",
        f"- 视频：`{table.video.path}`",
        f"- ASR：{(payload['asr'].get('model') or '未提供')} / language {payload['asr'].get('language') or 'unknown'} / {payload['asr']['segments']} 段",
        "- 注意：台词来自自动语音识别，**可能听错、没有说话人分离**；镜头/场景说明来自代码和 VLM 标签，不是人工剧本。",
        "",
    ]
    for scene in payload["scenes"]:
        title = f"{scene['scene_id']} · {scene['title']}" if scene.get("title") else scene["scene_id"]
        lines += [
            f"## {title} · {_timecode(scene['start'])}–{_timecode(scene['end'])}",
            "",
        ]
        if scene.get("summary"):
            lines += [scene["summary"], ""]
        for shot in scene["shots"]:
            labels = shot.get("labels", {})
            content = shot.get("content", {})
            measured = shot.get("measured", {})
            label_bits = [
                labels.get("scale", "unknown"),
                labels.get("camera", "unknown"),
                labels.get("lighting", "unknown"),
                labels.get("color", "unknown"),
            ]
            lines.append(
                f"### {shot['shot_id']} {_timecode(shot['start'])}–{_timecode(shot['end'])} · "
                + " / ".join(label_bits)
            )
            action = content.get("action") if content else ""
            subjects = "、".join(content.get("subjects", [])) if content else ""
            if action or subjects:
                lines.append(f"画面：{subjects + '：' if subjects else ''}{action}")
            if measured:
                lines.append(
                    f"测量：亮度 {_fmt(measured.get('brightness'))} · 运动 {_fmt(measured.get('motion'))} · 人脸 {_fmt(measured.get('face_ratio'))}"
                )
            dialogue = shot.get("dialogue", [])
            if dialogue:
                lines.append("台词（ASR 自动转写 / 中译）：")
                for segment in dialogue:
                    lines.append(f"- [{_timecode(segment['start'])}] {segment['text']}")
                    if segment.get("text_zh"):
                        lines.append(f"  中译：{segment['text_zh']}")
            lines.append("")
    return "\n".join(lines)


def _timecode(seconds: float) -> str:
    total = max(0, round(seconds))
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{sec:02d}" if hours else f"{minutes:02d}:{sec:02d}"


def _fmt(value: Any) -> str:
    return "-" if not isinstance(value, (int, float)) else f"{float(value):.3f}"

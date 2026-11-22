"""Scene writer: prompt construction and an OpenAI-compatible HTTP adapter.

The kernel never calls a model on its own.  `draft` builds one prompt per scene
from the plan, writes each returned scene as an independent draft file, and
records the model/provider plus prompt/source/plan hashes.  Any compatible
chat-completions endpoint can be used; tests run against a local fake server.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .beats import beat_guidance
from .source import scene_source_text
from .models import (
    DIALOGUE_BASES,
    INT_EXT_VALUES,
    TIME_VALUES,
    AdaptationPlan,
    AdapterError,
    Dialogue,
    Heading,
    Scene,
    SceneDraft,
    SourceDocument,
    normalize_int_ext,
    normalize_time,
    sha256_json,
)

SYSTEM_PROMPT = (
    "你是一名职业编剧，负责把小说或故事大纲改编成可拍摄的视频剧本。"
    "只输出一个 JSON 对象，不要输出 Markdown 代码围栏，不要解释。"
    "只能使用给定人物表里的有名角色；不得新增有名角色。"
    "不得改变原文中的既有事实、人物关系和结局；可以在既有事件之间补动作、反应和对白。"
    "每场戏必须有可见动作或场面，不能只有解释性旁白。"
)

_TIME_PROMPT = ", ".join(TIME_VALUES)
_BASIS_MAP = {
    "source": "source",
    "adapted": "adapted",
    "rewrite": "adapted",
    "rewritten": "adapted",
    "invented": "invented",
    "new": "invented",
    "added": "invented",
}


class WriterError(AdapterError):
    """A provider, prompt or response error that should be shown to the user."""


@dataclass(frozen=True)
class WriterConfig:
    base_url: str
    api_key: str = field(repr=False)
    model: str
    timeout: float = 90.0
    max_retries: int = 2


def build_prompt(plan: AdaptationPlan, scene: Scene, document: SourceDocument) -> tuple[list[dict[str, str]], str]:
    excerpt = _clip(scene_source_text(document, scene), 5000)
    cast_lines = []
    for character in plan.cast:
        aliases = "、".join(character.aliases)
        cast_lines.append(f"- {character.name}" + (f"（别名：{aliases}）" if aliases else ""))
    if not cast_lines:
        cast_lines.append("- （人物表为空；不要新增有名角色，尽量用无名群像）")
    neighbours = _neighbours(plan, scene, document)
    constraints = [
        f"目标时长约 {scene.duration_s:g} 秒；对白和动作要能支撑这个时长，不要写成长篇叙述。",
        f"本场结构功能：{beat_guidance(scene.beat, plan.brief.format).rstrip('。') or scene.beat_label}。",
        f"语言：{'中文' if plan.brief.language == 'zh' else 'English'}；画幅：{plan.brief.aspect}。",
        "场景头只能使用 INT / EXT / INT/EXT，时间只能使用：" + _TIME_PROMPT + "。",
        "不得新增有名角色；人物表之外的名字不能出现在对白里。",
        "对白角色必须来自人物表；不要用“旁白”代替戏剧动作，除非人物表里明确有它。",
        "对白 basis 只能取 source / adapted / invented；invented 表示原文没有、由你新增。",
        "至少一个 action 块或一句 dialogue；动作写可拍的内容，不写“他心想”。",
    ]
    if scene.expansion:
        constraints.extend(scene.notes)
    user = f"""# 项目
标题：{plan.title}
格式：{plan.brief.format}
集数：{plan.brief.episodes}
单集时长：{plan.brief.episode_minutes:g} 分钟
总目标时长：{plan.brief.total_minutes:g} 分钟
类型：{plan.brief.genre or '未指定'}
受众：{plan.brief.audience or '未指定'}
一句话故事：{plan.brief.logline or '未指定'}
改编模式：{plan.brief.mode}

# 人物表
{chr(10).join(cast_lines)}

# 本场
场号：{scene.id}
位置：第 {scene.episode} 集第 {scene.index_in_episode} 场
结构节拍：{scene.beat_label}（{scene.beat}）
目标时长：{scene.duration_s:g} 秒
来源章节：{', '.join(scene.source.chapter_ids) or '未标注'}
计划中检测到的在场人物：{'、'.join(scene.cast) if scene.cast else '无'}

# 原文片段（本场唯一事实来源，可能被截断）
{excerpt}

# 相邻场（只用于衔接，不要占用本场篇幅）
{neighbours}

# 硬约束
{chr(10).join(f'- {line}' for line in constraints)}

# 输出 JSON
{{
  "scene_id": "{scene.id}",
  "heading": {{"int_ext": "INT", "location": "具体地点", "time": "DAY"}},
  "action": ["可拍摄的动作/场面描述", "..."],
  "dialogue": [
    {{"character": "人物表姓名", "parenthetical": "", "line": "台词", "basis": "adapted"}}
  ],
  "transition": "",
  "notes": "可选，写给导演/下一场的备注"
}}
"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    return messages, sha256_json(messages)


def _neighbours(plan: AdaptationPlan, scene: Scene, document: SourceDocument) -> str:
    index = next((position for position, item in enumerate(plan.scenes) if item.id == scene.id), -1)
    if index < 0:
        return "无"
    lines: list[str] = []
    if index > 0:
        previous = plan.scenes[index - 1]
        text = scene_source_text(document, previous)
        lines.append(f"- 上一场 {previous.id}（{previous.beat_label}）：{_clip(text, 120)}")
    if index + 1 < len(plan.scenes):
        following = plan.scenes[index + 1]
        text = scene_source_text(document, following)
        lines.append(f"- 下一场 {following.id}（{following.beat_label}）：{_clip(text, 120)}")
    return "\n".join(lines) if lines else "无"


def _clip(text: str, limit: int) -> str:
    compact = text.strip()
    if len(compact) <= limit:
        return compact
    head = limit * 3 // 4
    tail = limit - head
    return compact[:head] + "\n…（中略）…\n" + compact[-tail:]


class OpenAICompatibleWriter:
    """Minimal chat-completions adapter with bounded retries.

    The endpoint is `{base_url}/chat/completions`; `base_url` normally ends in
    `/v1`.  No SDK dependency is needed, and the API key is never logged.
    """

    provider = "openai-compatible"

    def __init__(self, config: WriterConfig):
        if not config.base_url:
            raise WriterError("base URL is required (for example https://api.openai.com/v1)")
        if not config.api_key:
            raise WriterError("API key is required; set it in the environment or --env-file")
        if not config.model:
            raise WriterError("model is required")
        if config.timeout <= 0:
            raise WriterError("timeout must be positive")
        base = config.base_url.rstrip("/")
        self.endpoint = base if base.endswith("/chat/completions") else base + "/chat/completions"
        if not self.endpoint.startswith(("http://", "https://")):
            raise WriterError(f"base URL must start with http:// or https://: {config.base_url}")
        self.config = config

    def write_scene(self, plan: AdaptationPlan, scene: Scene, document: SourceDocument) -> SceneDraft:
        messages, prompt_sha256 = build_prompt(plan, scene, document)
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.7,
        }
        response = self._post(payload)
        content = _response_content(response)
        data = extract_json_object(content)
        return parse_scene_payload(
            data,
            plan=plan,
            scene=scene,
            prompt_sha256=prompt_sha256,
            provider=self.provider,
            model=self.config.model,
        )

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
            "User-Agent": "screenplay-adapter/0.1",
        }
        attempt = 0
        last_error = ""
        while attempt <= self.config.max_retries:
            request = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                    raw = response.read().decode("utf-8", "replace")
                return _decode_response(raw)
            except urllib.error.HTTPError as error:
                detail = _http_error_detail(error)
                last_error = f"HTTP {error.code}: {detail}"
                if error.code in (408, 409, 425, 429, 500, 502, 503, 504) and attempt < self.config.max_retries:
                    time.sleep(1.5 * (attempt + 1))
                    attempt += 1
                    continue
                if error.code in (401, 403):
                    last_error = "authentication failed; check the API key and endpoint permissions"
                elif error.code == 404:
                    last_error = "endpoint not found; check the base URL (it usually includes /v1)"
                raise WriterError(last_error) from error
            except urllib.error.URLError as error:
                last_error = f"cannot reach provider: {error.reason}"
                if attempt < self.config.max_retries:
                    time.sleep(1.5 * (attempt + 1))
                    attempt += 1
                    continue
                raise WriterError(last_error) from error
            except TimeoutError as error:
                last_error = f"provider timed out after {self.config.timeout:g}s"
                if attempt < self.config.max_retries:
                    time.sleep(1.5 * (attempt + 1))
                    attempt += 1
                    continue
                raise WriterError(last_error) from error
        raise WriterError(last_error or "provider request failed")


def _decode_response(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise WriterError(f"provider returned non-JSON response: {error}") from error
    if not isinstance(data, dict):
        raise WriterError("provider response must be a JSON object")
    return data


def _response_content(data: dict[str, Any]) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise WriterError("provider response has no choices[0].message.content") from error
    if not isinstance(content, str) or not content.strip():
        raise WriterError("provider returned empty content")
    return content


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise WriterError("model response contains no JSON object")
    candidate = stripped[start:end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise WriterError(f"model response JSON is invalid: {error}") from error
    if not isinstance(data, dict):
        raise WriterError("model response JSON must be an object")
    return data


def parse_scene_payload(
    data: dict[str, Any],
    *,
    plan: AdaptationPlan,
    scene: Scene,
    prompt_sha256: str = "",
    provider: str = "",
    model: str = "",
) -> SceneDraft:
    payload_scene = str(data.get("scene_id", scene.id))
    if payload_scene != scene.id:
        raise WriterError(f"model returned scene_id {payload_scene!r} for {scene.id}")

    heading_raw = data.get("heading")
    if not isinstance(heading_raw, dict):
        raise WriterError(f"{scene.id}: heading must be an object")
    int_ext = normalize_int_ext(str(heading_raw.get("int_ext", "")))
    if int_ext not in INT_EXT_VALUES:
        raise WriterError(f"{scene.id}: heading.int_ext must be one of {', '.join(INT_EXT_VALUES)}")
    location = str(heading_raw.get("location", "")).strip()
    if not location:
        raise WriterError(f"{scene.id}: heading.location must not be empty")
    time_value = normalize_time(str(heading_raw.get("time", "UNKNOWN")))
    if time_value not in TIME_VALUES:
        raise WriterError(f"{scene.id}: heading.time must be one of {', '.join(TIME_VALUES)}")
    heading = Heading(int_ext=int_ext, location=location, time=time_value)

    action = _string_list(data.get("action"), f"{scene.id}: action")
    dialogue_raw = data.get("dialogue", [])
    if not isinstance(dialogue_raw, list):
        raise WriterError(f"{scene.id}: dialogue must be a list")
    dialogue: list[Dialogue] = []
    for index, item in enumerate(dialogue_raw, start=1):
        if not isinstance(item, dict):
            raise WriterError(f"{scene.id}: dialogue[{index}] must be an object")
        character = str(item.get("character", "")).strip()
        line = str(item.get("line", "")).strip()
        if not character:
            raise WriterError(f"{scene.id}: dialogue[{index}] needs a character")
        if not line:
            raise WriterError(f"{scene.id}: dialogue[{index}] needs a non-empty line")
        basis = _BASIS_MAP.get(str(item.get("basis", "adapted")).strip().lower(), "adapted")
        dialogue.append(
            Dialogue(
                character=character,
                line=line,
                parenthetical=str(item.get("parenthetical", "")).strip(),
                basis=basis if basis in DIALOGUE_BASES else "adapted",
            )
        )
    if not action and not dialogue:
        raise WriterError(f"{scene.id}: scene needs at least one action block or dialogue line")
    transition = str(data.get("transition", "")).strip()
    notes = str(data.get("notes", "")).strip()
    return SceneDraft(
        scene_id=scene.id,
        heading=heading,
        action=tuple(action),
        dialogue=tuple(dialogue),
        transition=transition,
        plan_hash=plan.plan_hash,
        source_sha256=str(plan.source.get("sha256", "")),
        provider=provider,
        model=model,
        prompt_sha256=prompt_sha256,
        notes=notes,
    )


def _string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise WriterError(f"{field} must be a list of strings")
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _http_error_detail(error: urllib.error.HTTPError) -> str:
    try:
        body = error.read().decode("utf-8", "replace")
    except (OSError, UnicodeError):  # pragma: no cover - defensive around a broken stream
        return error.reason or "request failed"
    try:
        payload = json.loads(body)
        if isinstance(payload, dict):
            inner = payload.get("error")
            if isinstance(inner, dict) and inner.get("message"):
                return str(inner["message"])[:300]
            if payload.get("message"):
                return str(payload["message"])[:300]
    except json.JSONDecodeError:
        pass
    return body.strip()[:300] or (error.reason or "request failed")

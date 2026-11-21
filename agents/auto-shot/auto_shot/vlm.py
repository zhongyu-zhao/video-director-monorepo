"""Minimal OpenAI-compatible VLM client.

The API key is read from an environment file or process environment and
is never written to an artifact, log line or exception message.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class VlmError(RuntimeError):
    """Raised when the VLM provider cannot return a usable JSON object."""


@dataclass(frozen=True)
class VlmConfig:
    api_key: str
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-flash"
    timeout: float = 120.0


class VlmClient(Protocol):
    def complete_text(self, prompt: str, max_tokens: int = 8000) -> dict[str, Any]:
        """Return one parsed JSON object for a text prompt."""

    def label_image(self, image: bytes, prompt: str, max_tokens: int = 3500) -> dict[str, Any]:
        """Return the model's parsed JSON response for one image."""


def load_env_file(path: str | Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE file; values are never printed."""

    values: dict[str, str] = {}
    source = Path(path)
    if not source.is_file():
        raise VlmError(f"env file not found: {source}")
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def resolve_config(
    env_file: str | Path | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key_env: str = "DEEPSEEK_API_KEY",
) -> VlmConfig:
    file_values = load_env_file(env_file) if env_file else {}

    def pick(*names: str) -> str | None:
        for name in names:
            value = os.environ.get(name) or file_values.get(name)
            if value:
                return value
        return None

    api_key = pick(api_key_env)
    if not api_key:
        hint = f" in {env_file}" if env_file else ""
        raise VlmError(
            f"{api_key_env} not found{hint}; pass --env-file or set the environment variable"
        )

    resolved_base = (
        base_url
        or pick("DEEPSEEK_API_BASE", "DEEPSEEK_BASE_URL")
        or "https://api.deepseek.com/v1"
    ).rstrip("/")
    resolved_model = model or pick("DEEPSEEK_MODEL_FLASH", "DEEPSEEK_MODEL") or "deepseek-flash"
    return VlmConfig(api_key=api_key, base_url=resolved_base, model=resolved_model)


class DeepSeekVlmClient:
    """DeepSeek's OpenAI-compatible chat completions endpoint."""

    def __init__(self, config: VlmConfig) -> None:
        self.config = config
        self.model = config.model

    def complete_text(self, prompt: str, max_tokens: int = 8000) -> dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": "你是影视叙事分析助手。只输出合法 JSON，不要 markdown 代码块。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        request = urllib.request.Request(
            f"{self.config.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            message = _http_error_message(error)
            raise VlmError(f"VLM HTTP {error.code}: {message}") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise VlmError(f"VLM request failed: {error}") from error
        try:
            choice = body["choices"][0]
            content = choice["message"].get("content") or ""
            finish = choice.get("finish_reason")
        except (KeyError, IndexError, TypeError) as error:
            raise VlmError("VLM response has no choices[0].message.content") from error
        if not content.strip():
            raise VlmError(f"VLM returned empty content (finish_reason={finish})")
        if finish == "length":
            raise VlmError("VLM response was truncated (finish_reason=length); increase max_tokens")
        return parse_json_object(content)

    def label_image(self, image: bytes, prompt: str, max_tokens: int = 3500) -> dict[str, Any]:
        encoded = base64.b64encode(image).decode("ascii")
        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是电影视听语言分析助手。只输出合法 JSON，不要 markdown 代码块。",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                        },
                    ],
                },
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        request = urllib.request.Request(
            f"{self.config.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            message = _http_error_message(error)
            raise VlmError(f"VLM HTTP {error.code}: {message}") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise VlmError(f"VLM request failed: {error}") from error

        try:
            choice = body["choices"][0]
            content = choice["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as error:
            raise VlmError("VLM response has no choices[0].message.content") from error
        finish = choice.get("finish_reason")
        if not content.strip():
            raise VlmError(f"VLM returned empty content (finish_reason={finish})")
        if finish == "length":
            raise VlmError(
                "VLM response was truncated (finish_reason=length); increase max_tokens or simplify the prompt"
            )
        return parse_json_object(content)


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as error:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise VlmError(f"VLM did not return JSON: {cleaned[:200]}") from error
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as nested:
            raise VlmError(f"VLM returned invalid JSON: {cleaned[:200]}") from nested
    if not isinstance(value, dict):
        raise VlmError("VLM JSON response must be an object")
    return value


def _http_error_message(error: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(error.read().decode("utf-8", errors="replace"))
        message = payload.get("error", {}).get("message") or payload.get("message")
        if message:
            return str(message)[:300]
    except (json.JSONDecodeError, AttributeError):
        pass
    return error.reason or "request failed"

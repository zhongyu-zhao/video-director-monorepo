"""Data structures for the screenplay-adapter kernel.

`adaptation.json` is the adaptation plan and the single source of truth for a
project; `screenplay.json` is the drafted screenplay that references it.  The
models here only describe the M0 kernel: source parsing, cast, scene planning
and scene drafts.  Character state machines, causal plot graphs and shot
planning arrive in later schema versions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1
FORMATS = ("feature", "series", "short-drama")
INT_EXT_VALUES = ("INT", "EXT", "INT/EXT")
TIME_VALUES = ("DAY", "NIGHT", "DAWN", "DUSK", "MORNING", "EVENING", "CONTINUOUS", "LATER", "UNKNOWN")
DIALOGUE_BASES = ("source", "adapted", "invented")

DEFAULT_FORMAT_PRESETS: dict[str, dict[str, Any]] = {
    "feature": {"episodes": 1, "episode_minutes": 100.0, "scene_seconds": 150.0},
    "series": {"episodes": 6, "episode_minutes": 45.0, "scene_seconds": 180.0},
    "short-drama": {"episodes": 30, "episode_minutes": 2.0, "scene_seconds": 45.0},
}


class AdapterError(ValueError):
    """A user-facing input, project or provider error."""



# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Chapter:
    id: str
    index: int
    title: str
    start: int
    end: int
    paragraph_ids: tuple[str, ...] = ()
    sentence_ids: tuple[str, ...] = ()

    @property
    def chars(self) -> int:
        return max(0, self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "index": self.index,
            "title": self.title,
            "chars": self.chars,
            "paragraph_count": len(self.paragraph_ids),
            "sentence_count": len(self.sentence_ids),
        }


@dataclass(frozen=True)
class Paragraph:
    id: str
    chapter_id: str
    text: str
    start: int
    end: int
    sentence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Sentence:
    id: str
    paragraph_id: str
    chapter_id: str
    text: str
    start: int
    end: int


@dataclass
class SourceDocument:
    path: str
    sha256: str
    text: str
    title: str
    language: str
    chapters: list[Chapter]
    paragraphs: list[Paragraph]
    sentences: list[Sentence]

    @property
    def chars(self) -> int:
        return len(self.text)

    @property
    def word_units(self) -> int:
        return count_word_units(self.text)

    def meta(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "title": self.title,
            "language": self.language,
            "chars": self.chars,
            "word_units": self.word_units,
            "chapter_count": len(self.chapters),
            "paragraph_count": len(self.paragraphs),
            "sentence_count": len(self.sentences),
            "chapters": [chapter.to_dict() for chapter in self.chapters],
        }


# ---------------------------------------------------------------------------
# Cast and plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Character:
    id: str
    name: str
    aliases: tuple[str, ...] = ()
    first_chapter: str = ""
    last_chapter: str = ""
    mentions: int = 0
    dialogue_mentions: int = 0
    source: str = "auto"
    role: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "aliases": list(self.aliases),
            "first_chapter": self.first_chapter,
            "last_chapter": self.last_chapter,
            "mentions": self.mentions,
            "dialogue_mentions": self.dialogue_mentions,
            "source": self.source,
            "role": self.role,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Character":
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            aliases=tuple(str(alias) for alias in data.get("aliases", [])),
            first_chapter=str(data.get("first_chapter", "")),
            last_chapter=str(data.get("last_chapter", "")),
            mentions=int(data.get("mentions", 0)),
            dialogue_mentions=int(data.get("dialogue_mentions", 0)),
            source=str(data.get("source", "auto")),
            role=str(data.get("role", "")),
            note=str(data.get("note", "")),
        )

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass(frozen=True)
class AdaptationBrief:
    title: str
    format: str = "short-drama"
    episodes: int = 30
    episode_minutes: float = 2.0
    scene_seconds: float = 45.0
    genre: str = ""
    logline: str = ""
    audience: str = ""
    aspect: str = "vertical"
    language: str = "zh"
    mode: str = "adapt"

    @property
    def total_minutes(self) -> float:
        return round(self.episodes * self.episode_minutes, 3)

    @property
    def total_seconds(self) -> float:
        return round(self.total_minutes * 60.0, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "format": self.format,
            "episodes": self.episodes,
            "episode_minutes": round(float(self.episode_minutes), 3),
            "scene_seconds": round(float(self.scene_seconds), 3),
            "total_minutes": self.total_minutes,
            "total_seconds": self.total_seconds,
            "genre": self.genre,
            "logline": self.logline,
            "audience": self.audience,
            "aspect": self.aspect,
            "language": self.language,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AdaptationBrief":
        return cls(
            title=str(data["title"]),
            format=str(data.get("format", "short-drama")),
            episodes=int(data.get("episodes", 30)),
            episode_minutes=float(data.get("episode_minutes", 2.0)),
            scene_seconds=float(data.get("scene_seconds", 45.0)),
            genre=str(data.get("genre", "")),
            logline=str(data.get("logline", "")),
            audience=str(data.get("audience", "")),
            aspect=str(data.get("aspect", "vertical")),
            language=str(data.get("language", "zh")),
            mode=str(data.get("mode", "adapt")),
        )


@dataclass(frozen=True)
class SourceSpan:
    sentence_start: int
    sentence_end: int
    char_start: int
    char_end: int
    chapter_ids: tuple[str, ...] = ()
    paragraph_ids: tuple[str, ...] = ()
    excerpt: str = ""

    @property
    def sentence_count(self) -> int:
        return max(0, self.sentence_end - self.sentence_start + 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sentence_start": self.sentence_start,
            "sentence_end": self.sentence_end,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "chapter_ids": list(self.chapter_ids),
            "paragraph_ids": list(self.paragraph_ids),
            "excerpt": self.excerpt,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceSpan":
        return cls(
            sentence_start=int(data["sentence_start"]),
            sentence_end=int(data["sentence_end"]),
            char_start=int(data["char_start"]),
            char_end=int(data["char_end"]),
            chapter_ids=tuple(str(value) for value in data.get("chapter_ids", [])),
            paragraph_ids=tuple(str(value) for value in data.get("paragraph_ids", [])),
            excerpt=str(data.get("excerpt", "")),
        )


@dataclass(frozen=True)
class Scene:
    id: str
    episode: int
    index_in_episode: int
    beat: str
    beat_label: str
    duration_s: float
    source: SourceSpan
    cast: tuple[str, ...] = ()
    expansion: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "episode": self.episode,
            "index_in_episode": self.index_in_episode,
            "beat": self.beat,
            "beat_label": self.beat_label,
            "duration_s": round(float(self.duration_s), 3),
            "source": self.source.to_dict(),
            "cast": list(self.cast),
            "expansion": list(self.expansion),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scene":
        return cls(
            id=str(data["id"]),
            episode=int(data["episode"]),
            index_in_episode=int(data["index_in_episode"]),
            beat=str(data["beat"]),
            beat_label=str(data.get("beat_label", "")),
            duration_s=float(data["duration_s"]),
            source=SourceSpan.from_dict(data["source"]),
            cast=tuple(str(value) for value in data.get("cast", [])),
            expansion=tuple(str(value) for value in data.get("expansion", [])),
            notes=tuple(str(value) for value in data.get("notes", [])),
        )


@dataclass
class AdaptationPlan:
    title: str
    brief: AdaptationBrief
    source: dict[str, Any]
    cast: list[Character]
    scenes: list[Scene]
    requested_scenes: int
    plan_hash: str = ""
    warnings: list[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": "screenplay-adapter-plan",
            "title": self.title,
            "brief": self.brief.to_dict(),
            "source": self.source,
            "cast": [character.to_dict() for character in self.cast],
            "scenes": [scene.to_dict() for scene in self.scenes],
            "requested_scenes": self.requested_scenes,
            "plan_hash": self.plan_hash,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AdaptationPlan":
        return cls(
            title=str(data["title"]),
            brief=AdaptationBrief.from_dict(data["brief"]),
            source=dict(data["source"]),
            cast=[Character.from_dict(item) for item in data.get("cast", [])],
            scenes=[Scene.from_dict(item) for item in data.get("scenes", [])],
            requested_scenes=int(data.get("requested_scenes", len(data.get("scenes", [])))),
            plan_hash=str(data.get("plan_hash", "")),
            warnings=[str(item) for item in data.get("warnings", [])],
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        )

    def scene(self, scene_id: str) -> Scene | None:
        return next((scene for scene in self.scenes if scene.id == scene_id), None)

    def character(self, name: str) -> Character | None:
        for character in self.cast:
            if name in character.names:
                return character
        return None

    @property
    def total_seconds(self) -> float:
        return round(sum(scene.duration_s for scene in self.scenes), 3)


# ---------------------------------------------------------------------------
# Draft and screenplay
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Heading:
    int_ext: str
    location: str
    time: str

    def to_dict(self) -> dict[str, Any]:
        return {"int_ext": self.int_ext, "location": self.location, "time": self.time}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Heading":
        return cls(
            int_ext=str(data["int_ext"]),
            location=str(data["location"]),
            time=str(data.get("time", "UNKNOWN")),
        )

    def as_text(self) -> str:
        return f"{self.int_ext}. {self.location} - {self.time}"


@dataclass(frozen=True)
class Dialogue:
    character: str
    line: str
    parenthetical: str = ""
    basis: str = "adapted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "character": self.character,
            "line": self.line,
            "parenthetical": self.parenthetical,
            "basis": self.basis,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Dialogue":
        return cls(
            character=str(data["character"]),
            line=str(data["line"]),
            parenthetical=str(data.get("parenthetical", "")),
            basis=str(data.get("basis", "adapted")),
        )


@dataclass(frozen=True)
class SceneDraft:
    scene_id: str
    heading: Heading
    action: tuple[str, ...]
    dialogue: tuple[Dialogue, ...]
    transition: str = ""
    plan_hash: str = ""
    source_sha256: str = ""
    provider: str = ""
    model: str = ""
    prompt_sha256: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "scene_id": self.scene_id,
            "heading": self.heading.to_dict(),
            "action": list(self.action),
            "dialogue": [line.to_dict() for line in self.dialogue],
            "transition": self.transition,
            "plan_hash": self.plan_hash,
            "source_sha256": self.source_sha256,
            "writer": {"provider": self.provider, "model": self.model},
            "prompt_sha256": self.prompt_sha256,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SceneDraft":
        writer = data.get("writer", {})
        return cls(
            scene_id=str(data["scene_id"]),
            heading=Heading.from_dict(data["heading"]),
            action=tuple(str(item) for item in data.get("action", [])),
            dialogue=tuple(Dialogue.from_dict(item) for item in data.get("dialogue", [])),
            transition=str(data.get("transition", "")),
            plan_hash=str(data.get("plan_hash", "")),
            source_sha256=str(data.get("source_sha256", "")),
            provider=str(writer.get("provider", "")),
            model=str(writer.get("model", "")),
            prompt_sha256=str(data.get("prompt_sha256", "")),
            notes=str(data.get("notes", "")),
        )

    def estimated_seconds(self) -> float:
        return estimate_draft_seconds(self.action, self.dialogue)


@dataclass
class Screenplay:
    title: str
    plan_hash: str
    source_sha256: str
    scenes: list[dict[str, Any]]
    stats: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": "screenplay",
            "title": self.title,
            "plan_hash": self.plan_hash,
            "source_sha256": self.source_sha256,
            "stats": self.stats,
            "scenes": self.scenes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Screenplay":
        return cls(
            title=str(data["title"]),
            plan_hash=str(data.get("plan_hash", "")),
            source_sha256=str(data.get("source_sha256", "")),
            scenes=list(data.get("scenes", [])),
            stats=dict(data.get("stats", {})),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def count_word_units(text: str) -> int:
    """Count CJK characters plus Latin/number word tokens.

    This is a language-neutral size proxy for allocation; it is never used as
    a claim about runtime or literary quality.
    """

    cjk = sum(1 for char in text if "\u3400" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff")
    latin = 0
    in_word = False
    for char in text:
        if char.isascii() and (char.isalnum() or char in "'’"):
            if not in_word:
                latin += 1
                in_word = True
        else:
            in_word = False
    return cjk + latin


def estimate_draft_seconds(action: tuple[str, ...] | list[str], dialogue: tuple[Dialogue, ...] | list[Dialogue]) -> float:
    """Rough runtime estimate used only for order-of-magnitude gates.

    Chinese dialogue is estimated at ~4 characters per second, mixed text uses
    four non-space characters per second, and each action block carries a
    small staging overhead.  This is deliberately conservative, not precise.
    """

    seconds = 0.0
    for block in action:
        seconds += max(1.5, count_word_units(block) / 4.0) + 1.0
    for line in dialogue:
        seconds += max(1.0, count_word_units(line.line) / 4.0) + 0.6
        if line.parenthetical.strip():
            seconds += 0.8
    return round(seconds, 3)


def plan_hash_for(
    source_sha256: str,
    brief: AdaptationBrief,
    scenes: list[Scene],
    cast: list[Character] | None = None,
) -> str:
    payload = {
        "source_sha256": source_sha256,
        "brief": brief.to_dict(),
        "cast": [character.to_dict() for character in cast or []],
        "scenes": [scene.to_dict() for scene in scenes],
    }
    return sha256_json(payload)


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_time(value: str) -> str:
    mapping = {
        "日": "DAY",
        "白天": "DAY",
        "夜": "NIGHT",
        "夜晚": "NIGHT",
        "晨": "DAWN",
        "清晨": "DAWN",
        "黄昏": "DUSK",
        "傍晚": "DUSK",
        "早": "MORNING",
        "上午": "MORNING",
        "晚": "EVENING",
        "连续": "CONTINUOUS",
        "稍后": "LATER",
        "未知": "UNKNOWN",
    }
    text = value.strip()
    upper = text.upper().replace(" ", "").rstrip(".")
    if upper in TIME_VALUES:
        return upper
    return mapping.get(text, upper or "UNKNOWN")


def normalize_int_ext(value: str) -> str:
    text = value.strip().upper().replace(" ", "").rstrip(".")
    mapping = {
        "INT": "INT",
        "内": "INT",
        "内景": "INT",
        "EXT": "EXT",
        "外": "EXT",
        "外景": "EXT",
        "INT/EXT": "INT/EXT",
        "内外": "INT/EXT",
        "EXT/INT": "INT/EXT",
    }
    return mapping.get(text, text)

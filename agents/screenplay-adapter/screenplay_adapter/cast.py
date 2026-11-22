"""Deterministic cast extraction from dialogue attribution.

Chinese prose rarely marks names with capital letters, so the default extractor
uses speech tags ("林昭说", "她问道", '"..." said Mara') plus an explicit cast
file for precision.  Extracted names are always advisory: the plan records the
source and a human can pin the real cast with `--cast`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import AdapterError, Character, SourceDocument

_ZH_ADVERB = (
    r"(?:冷笑|苦笑|嘲笑|讥笑|冷哼|轻哼|低声|高声|轻声|大声|沉声|冷声|柔声|缓缓|淡淡|冷冷|慢慢|"
    r"忽然|突然|终于|点头|摇头|皱眉|挑眉|咬牙|哽咽|笑着|哭着|连忙|急忙|继续|又|才|就|先|却|则|也|都|还|便|忙)?"
)
_ZH_VERB = (
    r"(?:说|道|问|答|喊|叫|嚷|笑道|哭道|回答|回应|反问|追问|解释|补充|提醒|宣布|承认|否认|"
    r"嘀咕|嘟囔|喃喃|开口|叹道|骂道|吼道|应道|自语|承认|坚持|抱怨|建议|反驳|同意|拒绝)"
)
_ZH_SPEECH = re.compile(rf"([\u4e00-\u9fff]{{2,4}}?){_ZH_ADVERB}{_ZH_VERB}")
_ZH_SCRIPT = re.compile(r"^\s*([\u4e00-\u9fff]{2,4})[：:]\s*[“\"「『]")
_EN_SPEECH = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:said|asked|replied|answered|shouted|whispered|"
    r"murmured|added|explained|called|yelled|muttered|continued|began|told)\b"
)
_EN_SCRIPT = re.compile(r"^\s*([A-Z][A-Z .'-]{1,30}):\s+[“\"']")

_STOP_NAMES = {
    "他", "她", "它", "他们", "她们", "它们", "我们", "你们", "我", "你", "自己", "对方",
    "有人", "众人", "大家", "所有人", "两人", "三人", "一人", "那人", "这人", "别人",
    "男人", "女人", "少年", "少女", "老人", "孩子", "小孩", "青年", "中年", "男子", "女子",
    "声音", "一个", "两个", "三人", "此时", "这时", "那时", "然后", "于是", "但是", "可是",
    "只是", "不过", "因为", "所以", "如果", "虽然", "然而", "同时", "立刻", "马上", "终于",
    "突然", "忽然", "已经", "还是", "就是", "不是", "没有", "什么", "怎么", "为什么",
    "母亲", "父亲", "妈妈", "爸爸", "哥哥", "姐姐", "弟弟", "妹妹", "爷爷", "奶奶",
    "医生", "护士", "警察", "老师", "学生", "老板", "记者", "司机", "管家", "侍卫", "丫鬟",
    "将军", "皇帝", "皇后", "太子", "公主", "王爷", "小姐", "公子", "夫人", "老太太", "老头",
    "所有", "每个", "任何", "其他", "另外", "接着", "随后", "最后", "第一", "第二", "第三",
}

_EN_STOP = {
    "I", "He", "She", "It", "They", "We", "You", "The", "A", "An", "This", "That", "These", "Those",
    "Then", "But", "And", "So", "When", "While", "After", "Before", "If", "As", "At", "In", "On",
}


def load_cast_file(path: Path) -> list[dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise AdapterError(f"cannot read cast file {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise AdapterError(f"cast file {path} is not valid JSON: {error}") from error
    items = payload.get("characters") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise AdapterError("cast file must be a list or an object with a 'characters' list")
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            entry: dict[str, object] = {"name": item}
        elif isinstance(item, dict):
            entry = dict(item)
        else:
            raise AdapterError("each cast entry must be a string or an object")
        name = str(entry.get("name", "")).strip()
        if not name:
            raise AdapterError("each cast entry needs a non-empty 'name'")
        if name in seen:
            raise AdapterError(f"duplicate cast name: {name}")
        seen.add(name)
        aliases = entry.get("aliases", [])
        if not isinstance(aliases, list):
            raise AdapterError(f"aliases for {name} must be a list")
        entry["name"] = name
        entry["aliases"] = [str(alias).strip() for alias in aliases if str(alias).strip()]
        result.append(entry)
    if not result:
        raise AdapterError("cast file contains no characters")
    return result


def extract_cast(
    document: SourceDocument,
    *,
    explicit: list[dict[str, object]] | None = None,
    min_mentions: int = 2,
) -> list[Character]:
    """Extract a cast list, preferring an explicit cast file when provided."""

    if explicit is not None:
        return _explicit_cast(document, explicit)

    counts: dict[str, int] = {}
    dialogue_counts: dict[str, int] = {}
    first_offset: dict[str, int] = {}
    for sentence in document.sentences:
        for name, offset in _candidate_names_with_offsets(sentence.text, sentence.start):
            counts[name] = counts.get(name, 0) + 1
            dialogue_counts[name] = dialogue_counts.get(name, 0) + 1
            first_offset.setdefault(name, offset)

    for candidate in list(counts):
        total = document.text.count(candidate)
        if total > counts[candidate]:
            counts[candidate] = total

    merged = _merge_alias_candidates(counts, first_offset)
    characters: list[Character] = []
    for name, aliases in merged.items():
        total = counts.get(name, 0)
        dialogue = dialogue_counts.get(name, 0) + sum(dialogue_counts.get(alias, 0) for alias in aliases)
        if total < min_mentions and dialogue == 0:
            continue
        if dialogue == 0 and total < max(min_mentions, 3):
            continue
        first_chapter, last_chapter = _chapter_range(document, (name, *aliases))
        characters.append(
            Character(
                id="",
                name=name,
                aliases=tuple(sorted(aliases)),
                first_chapter=first_chapter,
                last_chapter=last_chapter,
                mentions=total,
                dialogue_mentions=dialogue,
                source="auto",
            )
        )
    characters.sort(key=lambda item: (-item.dialogue_mentions, -item.mentions, first_offset.get(item.name, 0), item.name))
    return [
        Character(
            id=f"C{index:03d}",
            name=character.name,
            aliases=character.aliases,
            first_chapter=character.first_chapter,
            last_chapter=character.last_chapter,
            mentions=character.mentions,
            dialogue_mentions=character.dialogue_mentions,
            source=character.source,
        )
        for index, character in enumerate(characters, start=1)
    ]


def _candidate_names_with_offsets(text: str, base_offset: int) -> list[tuple[str, int]]:
    names: list[tuple[str, int]] = []
    for match in _ZH_SPEECH.finditer(text):
        if _inside_quotes(text, match.start()) or not _has_quote_near(text, match.start(), match.end()):
            continue
        name = _clean_name(match.group(1))
        if name:
            names.append((name, base_offset + match.start(1)))
    for match in _ZH_SCRIPT.finditer(text):
        if _inside_quotes(text, match.start()):
            continue
        name = _clean_name(match.group(1))
        if name:
            names.append((name, base_offset + match.start(1)))
    for match in _EN_SPEECH.finditer(text):
        name = match.group(1).strip()
        if not _inside_quotes(text, match.start()) and _has_quote_near(text, match.start(), match.end()):
            if name and name not in _EN_STOP and not _EN_STOP.issuperset(name.split()):
                names.append((name, base_offset + match.start(1)))
    for match in _EN_SCRIPT.finditer(text):
        name = match.group(1).strip().title()
        if name and name not in _EN_STOP:
            names.append((name, base_offset + match.start(1)))
    return names


_QUOTES = "“”\"「」『』"


def _has_quote_near(text: str, start: int, end: int, window: int = 30) -> bool:
    left = max(0, start - window)
    right = min(len(text), end + window)
    return any(quote in text[left:right] for quote in _QUOTES)


def _inside_quotes(text: str, index: int) -> bool:
    depth = 0
    double_quote = False
    for char in text[:index]:
        if char in "“「『":
            depth += 1
        elif char in "”」』":
            depth = max(0, depth - 1)
        elif char == '"':
            double_quote = not double_quote
    return depth > 0 or double_quote


def _clean_name(raw: str) -> str:
    name = raw.strip()
    for suffix in ("冷笑", "苦笑", "摇头", "点头", "皱眉", "咬牙", "哽咽", "低声", "高声", "轻声", "大声"):
        if name.endswith(suffix) and len(name) > len(suffix) + 1:
            name = name[: -len(suffix)]
    name = name.strip()
    if len(name) < 2 or len(name) > 4:
        return ""
    if name in _STOP_NAMES:
        return ""
    if any(name.endswith(verb) for verb in ("说道", "问道", "答道", "喊道", "叫道")):
        return ""
    return name


def _merge_alias_candidates(counts: dict[str, int], first_offset: dict[str, int]) -> dict[str, list[str]]:
    names = sorted(counts, key=lambda item: (-counts[item], first_offset.get(item, 0), item))
    merged: dict[str, list[str]] = {}
    for name in names:
        merged[name] = []
    for name in list(merged):
        if name not in merged:
            continue
        for other in list(merged):
            if other == name or other not in merged:
                continue
            if len(other) > len(name) and other.endswith(name) and counts.get(name, 0) >= 2:
                merged[other].append(name)
                del merged[name]
                break
    return merged


def _chapter_range(document: SourceDocument, names: tuple[str, ...]) -> tuple[str, str]:
    first = ""
    last = ""
    for sentence in document.sentences:
        if any(name in sentence.text for name in names):
            if not first:
                first = sentence.chapter_id
            last = sentence.chapter_id
    return first, last


def _explicit_cast(document: SourceDocument, entries: list[dict[str, object]]) -> list[Character]:
    names_to_counts = {
        str(entry["name"]): tuple(str(alias) for alias in entry.get("aliases", [])) for entry in entries
    }
    dialogue_counts: dict[str, int] = {name: 0 for name in names_to_counts}
    for sentence in document.sentences:
        for candidate, _ in _candidate_names_with_offsets(sentence.text, sentence.start):
            for name, aliases in names_to_counts.items():
                if candidate == name or candidate in aliases:
                    dialogue_counts[name] += 1
                    break

    characters: list[Character] = []
    for index, entry in enumerate(entries, start=1):
        name = str(entry["name"])
        aliases = tuple(str(alias) for alias in entry.get("aliases", []))
        first_chapter, last_chapter = _chapter_range(document, (name, *aliases))
        mentions = sum(document.text.count(value) for value in (name, *aliases))
        characters.append(
            Character(
                id=f"C{index:03d}",
                name=name,
                aliases=aliases,
                first_chapter=first_chapter,
                last_chapter=last_chapter,
                mentions=mentions,
                dialogue_mentions=dialogue_counts.get(name, 0),
                source="explicit",
                role=str(entry.get("role", "")),
                note=str(entry.get("note", "")),
            )
        )
    return characters


def find_characters(text: str, cast: list[Character]) -> list[str]:
    """Return names from the cast that appear in `text`, preserving cast order."""

    found: list[str] = []
    for character in cast:
        for name in character.names:
            if not name:
                continue
            if name.isascii():
                if re.search(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", text, re.IGNORECASE):
                    found.append(character.name)
                    break
            elif name in text:
                found.append(character.name)
                break
    return found

"""Parse a novel or outline into chapters, paragraphs and sentences.

The parser is intentionally conservative: it only decides boundaries that can
be re-derived from the text.  Chapter titles are metadata for the plan; they
are never rewritten.  Every sentence keeps its character offsets so a scene
can be traced back to the exact source span later.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .models import AdapterError, Chapter, Paragraph, Sentence, SourceDocument

_CHAPTER_ZH = re.compile(
    r"^\s*(第[0-9零〇一二三四五六七八九十百千万两]+[章节回卷集部篇][^\n]{0,60})\s*$"
)
_CHAPTER_SPECIAL = re.compile(r"^\s*((?:序章|楔子|引子|尾声|终章|后记|番外|前言)[^\n]{0,60})\s*$")
_CHAPTER_EN = re.compile(
    r"^\s*((?:Chapter|CHAPTER)\s+[0-9IVXLCDM]+[.:：、\s]?[^\n]{0,60})\s*$"
)
_CHAPTER_NUM = re.compile(r"^\s*([0-9]{1,3})[.、]\s+([^\n]{1,50})\s*$")
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")

_SENTENCE_END = set("。！？!?…")
_CLOSERS = set("”’」』）)]】》〉…")
_TIME_HEADING = re.compile(r"^\s*(?:正文|目录|简介|内容简介|作者的话)\s*$")
_EN_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e", "no", "fig", "vol",
}


@dataclass(frozen=True)
class _Line:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class _Marker:
    start: int
    end: int
    title: str
    level: int = 0
    kind: str = "text"


def read_source_text(path: Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise AdapterError(f"cannot read source {path}: {error}") from error
    except UnicodeDecodeError as error:
        raise AdapterError(f"source {path} is not valid UTF-8: {error}") from error
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise AdapterError(f"source {path} is empty")
    return text


def parse_source(
    text: str,
    *,
    path: str = "source/source.md",
    title: str | None = None,
    fallback_title: str | None = None,
) -> SourceDocument:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise AdapterError("source is empty")
    lines = _lines(text)
    markers, markdown_title = _detect_markers(lines)
    document_title = title or markdown_title or fallback_title or _guess_title(lines, path)

    start_offset = 0
    if not markers and markdown_title:
        for line in lines:
            match = _MARKDOWN_HEADING.match(line.text)
            if match and match.group(2).strip() == markdown_title:
                start_offset = line.end
                break
    spans = _chapter_spans(text, markers, start_offset)
    chapters: list[Chapter] = []
    paragraphs: list[Paragraph] = []
    sentences: list[Sentence] = []
    paragraph_counter = 0
    sentence_counter = 0

    for index, (start, end, chapter_title) in enumerate(spans, start=1):
        chapter_id = f"CH{index:03d}"
        chapter_paragraphs: list[Paragraph] = []
        chapter_sentences: list[Sentence] = []
        for paragraph_start, paragraph_end in _paragraph_spans(text, start, end):
            paragraph_counter += 1
            paragraph_id = f"P{paragraph_counter:04d}"
            paragraph_text = text[paragraph_start:paragraph_end]
            unit = _split_sentences(text, paragraph_start, paragraph_end)
            for sentence_start, sentence_end in unit:
                sentence_counter += 1
                sentence_id = f"T{sentence_counter:05d}"
                sentence = Sentence(
                    id=sentence_id,
                    paragraph_id=paragraph_id,
                    chapter_id=chapter_id,
                    text=text[sentence_start:sentence_end].strip(),
                    start=sentence_start,
                    end=sentence_end,
                )
                if not sentence.text:
                    continue
                sentences.append(sentence)
                chapter_sentences.append(sentence)
            paragraph = Paragraph(
                id=paragraph_id,
                chapter_id=chapter_id,
                text=paragraph_text,
                start=paragraph_start,
                end=paragraph_end,
                sentence_ids=tuple(sentence.id for sentence in chapter_sentences if sentence.paragraph_id == paragraph_id),
            )
            paragraphs.append(paragraph)
            chapter_paragraphs.append(paragraph)
        chapters.append(
            Chapter(
                id=chapter_id,
                index=index,
                title=chapter_title,
                start=start,
                end=end,
                paragraph_ids=tuple(paragraph.id for paragraph in chapter_paragraphs),
                sentence_ids=tuple(sentence.id for sentence in chapter_sentences),
            )
        )

    if not sentences:
        raise AdapterError("source contains no readable sentences")

    language = _detect_language(text)
    return SourceDocument(
        path=path,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text=text,
        title=document_title,
        language=language,
        chapters=chapters,
        paragraphs=paragraphs,
        sentences=sentences,
    )


def _lines(text: str) -> list[_Line]:
    result: list[_Line] = []
    start = 0
    for raw in text.splitlines(keepends=True):
        end = start + len(raw)
        result.append(_Line(start=start, end=end, text=raw.rstrip("\n")))
        start = end
    if not result:
        result.append(_Line(start=0, end=0, text=""))
    return result


def _detect_markers(lines: list[_Line]) -> tuple[list[_Marker], str | None]:
    markdown: dict[int, list[_Marker]] = {}
    for line in lines:
        match = _MARKDOWN_HEADING.match(line.text)
        if not match:
            continue
        level = len(match.group(1))
        heading = match.group(2).strip()
        if not heading:
            continue
        markdown.setdefault(level, []).append(
            _Marker(start=line.start, end=line.end, title=heading, level=level, kind="markdown")
        )

    selected: list[_Marker] = []
    chapter_levels = [
        level
        for level in sorted(markdown)
        if any(_looks_like_chapter(marker.title) for marker in markdown[level])
    ]
    if chapter_levels:
        selected = [marker for marker in markdown[chapter_levels[0]] if _looks_like_chapter(marker.title)]
    if not selected:
        for level in sorted(markdown):
            if len(markdown[level]) >= 2:
                selected = markdown[level]
                break
    if not selected:
        headings = [marker for level in sorted(markdown) for marker in markdown[level]]
        non_top = [marker for marker in headings if lines[0].start != marker.start]
        if len(non_top) == 1:
            selected = non_top
        elif len(headings) == 1:
            # A lone heading at the very top is a title, not a chapter.
            selected = [] if lines[0].start == headings[0].start else [headings[0]]

    text_markers: list[_Marker] = []
    numeric_markers: list[_Marker] = []
    for line in lines:
        if _MARKDOWN_HEADING.match(line.text):
            continue
        stripped = line.text.strip()
        if not stripped or len(stripped) > 90:
            continue
        if _TIME_HEADING.match(stripped):
            continue
        if _CHAPTER_ZH.match(stripped) or _CHAPTER_SPECIAL.match(stripped) or _CHAPTER_EN.match(stripped):
            text_markers.append(_Marker(start=line.start, end=line.end, title=stripped))
            continue
        numeric = _CHAPTER_NUM.match(stripped)
        if numeric:
            numeric_markers.append(_Marker(start=line.start, end=line.end, title=stripped))

    if not selected:
        if len(text_markers) >= 1:
            selected = text_markers
        elif len(numeric_markers) >= 2:
            selected = numeric_markers

    title = _markdown_title(lines, selected)
    return selected, title


def _looks_like_chapter(title: str) -> bool:
    return bool(
        _CHAPTER_ZH.match(title)
        or _CHAPTER_SPECIAL.match(title)
        or _CHAPTER_EN.match(title)
    )


def _markdown_title(lines: list[_Line], markers: list[_Marker]) -> str | None:
    heading_markers = [
        _Marker(
            start=line.start,
            end=line.end,
            title=match.group(2).strip(),
            level=len(match.group(1)),
            kind="markdown",
        )
        for line in lines
        if (match := _MARKDOWN_HEADING.match(line.text))
    ]
    if not heading_markers:
        return None
    if markers:
        first_marker = min(marker.start for marker in markers)
        before = [heading for heading in heading_markers if heading.start < first_marker]
        if before:
            return before[0].title
        return None
    if len(heading_markers) == 1 and lines[0].start == heading_markers[0].start:
        return heading_markers[0].title
    return None


def _guess_title(lines: list[_Line], path: str) -> str:
    return Path(path).stem


def _chapter_spans(text: str, markers: list[_Marker], start_offset: int = 0) -> list[tuple[int, int, str]]:
    if not markers:
        return [(start_offset, len(text), "全文")]
    spans: list[tuple[int, int, str]] = []
    first = markers[0]
    if _has_prose(text, 0, first.start):
        spans.append((0, first.start, "前言"))
    for index, marker in enumerate(markers):
        end = markers[index + 1].start if index + 1 < len(markers) else len(text)
        title = marker.title or f"第{index + 1}章"
        spans.append((marker.end, end, title))
    return spans


def _has_prose(text: str, start: int, end: int) -> bool:
    """True when the range contains content other than blanks and headings."""

    for _, _, line in _iter_lines(text, start, end):
        stripped = line.strip()
        if not stripped:
            continue
        if _MARKDOWN_HEADING.match(stripped):
            continue
        return True
    return False


def _paragraph_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    block_start: int | None = None
    block_end: int | None = None
    for line_start, line_end, line_text in _iter_lines(text, start, end):
        stripped = line_text.strip()
        if _MARKDOWN_HEADING.match(stripped):
            if block_start is not None and block_end is not None:
                spans.append(_trim_span(text, block_start, block_end))
                block_start = block_end = None
            continue
        if stripped:
            if block_start is None:
                block_start = line_start
            block_end = line_end
        elif block_start is not None and block_end is not None:
            spans.append(_trim_span(text, block_start, block_end))
            block_start = block_end = None
    if block_start is not None and block_end is not None:
        spans.append(_trim_span(text, block_start, block_end))
    return [(left, right) for left, right in spans if right > left and text[left:right].strip()]


def _iter_lines(text: str, start: int, end: int):
    offset = start
    while offset < end:
        newline = text.find("\n", offset, end)
        if newline == -1:
            yield offset, end, text[offset:end]
            break
        yield offset, newline, text[offset:newline]
        offset = newline + 1


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _split_sentences(text: str, start: int, end: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    sentence_start = start
    cursor = start
    depth = 0
    double_quote = False
    while cursor < end:
        char = text[cursor]
        if char in "“「『":
            depth += 1
        elif char in "”」』":
            depth = max(0, depth - 1)
        elif char == '"':
            double_quote = not double_quote
        boundary = False
        in_quote = depth > 0 or double_quote
        if not in_quote:
            if char in _SENTENCE_END:
                boundary = True
            elif char == "." and _is_english_period(text, cursor, start, end):
                boundary = True
        if boundary:
            boundary_end = cursor + 1
            while boundary_end < end and text[boundary_end] in _CLOSERS:
                boundary_end += 1
            left, right = _trim_span(text, sentence_start, boundary_end)
            if right > left:
                spans.append((left, right))
            sentence_start = boundary_end
            cursor = boundary_end
            continue
        cursor += 1
    left, right = _trim_span(text, sentence_start, end)
    if right > left:
        spans.append((left, right))
    return spans


def _is_english_period(text: str, index: int, start: int, end: int) -> bool:
    if index + 1 < end and not text[index + 1].isspace():
        return False
    before = text[index - 1] if index > start else ""
    if before.isdigit():
        return False
    token_start = index - 1
    while token_start > start and not text[token_start - 1].isspace():
        token_start -= 1
    token = text[token_start:index].lower().strip("\"'")
    if token in _EN_ABBREVIATIONS or (len(token) == 1 and token.isalpha()):
        return False
    cursor = index + 1
    while cursor < end and text[cursor].isspace():
        cursor += 1
    if cursor >= end:
        return True
    next_char = text[cursor]
    return next_char.isupper() or next_char in "“\"'\u201c\u2018("


def _detect_language(text: str) -> str:
    cjk = sum(1 for char in text if "\u3400" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff")
    latin = sum(1 for char in text if char.isascii() and char.isalpha())
    if cjk + latin == 0:
        return "unknown"
    return "zh" if cjk / (cjk + latin) >= 0.3 else "en"


def scene_source_text(document: SourceDocument, scene) -> str:
    """Source text for a scene, joining its sentences without chapter headings."""

    start = scene.source.sentence_start
    end = scene.source.sentence_end
    return "\n".join(document.sentences[index].text for index in range(start, end + 1))

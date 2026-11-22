from __future__ import annotations

import unittest

from screenplay_adapter.models import AdapterError
from screenplay_adapter.source import parse_source, scene_source_text

from tests.support import NOVEL, make_document


class SourceParsingTest(unittest.TestCase):
    def test_markdown_title_and_chapters(self) -> None:
        document = make_document()

        self.assertEqual(document.title, "雨夜")
        self.assertEqual([chapter.title for chapter in document.chapters], ["第一章 咖啡馆", "第二章 信封", "第三章 天台"])
        self.assertGreaterEqual(len(document.sentences), 20)
        for paragraph in document.paragraphs:
            self.assertNotIn("##", paragraph.text)

    def test_sentence_offsets_match_text(self) -> None:
        document = make_document()

        for sentence in document.sentences:
            self.assertEqual(document.text[sentence.start:sentence.end], sentence.text)
            self.assertTrue(sentence.text)

    def test_sentences_do_not_split_inside_quotes(self) -> None:
        text = "“你父亲。”林昭说，“钥匙能打开仓库。明天见。”\n"
        document = parse_source(text, title="测试")

        self.assertEqual(len(document.sentences), 1)
        self.assertIn("明天见", document.sentences[0].text)

    def test_english_abbreviations_do_not_split(self) -> None:
        document = parse_source("Mr. Smith left. Dr. Jones stayed.", title="Test")

        self.assertEqual([sentence.text for sentence in document.sentences], ["Mr. Smith left.", "Dr. Jones stayed."])

    def test_sentences_split_outside_quotes(self) -> None:
        text = "她走了。他没有动。\n"
        document = parse_source(text, title="测试")

        self.assertEqual([sentence.text for sentence in document.sentences], ["她走了。", "他没有动。"])

    def test_chinese_chapter_headings_without_markdown(self) -> None:
        text = "第一章 起点\n\n他出发了。\n\n第二章 转折\n\n他停下了。\n"
        document = parse_source(text, title="路")

        self.assertEqual([chapter.title for chapter in document.chapters], ["第一章 起点", "第二章 转折"])
        self.assertEqual([sentence.text for sentence in document.sentences], ["他出发了。", "他停下了。"])

    def test_single_markdown_chapter_under_a_title(self) -> None:
        document = parse_source("# 书名\n\n## 第一章 起点\n\n他出发了。\n", title="书名")

        self.assertEqual([chapter.title for chapter in document.chapters], ["第一章 起点"])
        self.assertEqual(document.sentences[0].text, "他出发了。")

    def test_chapter_heading_wins_over_subsection_headings(self) -> None:
        text = "# 书名\n\n## 第一章 起点\n\n### 1.1 早晨\n\n他出发了。\n\n### 1.2 傍晚\n\n他停下了。\n"
        document = parse_source(text, title="书名")

        self.assertEqual([chapter.title for chapter in document.chapters], ["第一章 起点"])

    def test_subsection_headings_are_not_story_text(self) -> None:
        text = "## 第一章 起点\n\n### 1.1 早晨\n\n他出发了。\n"
        document = parse_source(text, title="书名")

        self.assertEqual([sentence.text for sentence in document.sentences], ["他出发了。"])

    def test_volume_heading_does_not_swallow_chapters(self) -> None:
        text = "# 书名\n\n# 第一卷 风起\n\n## 第一章 起点\n\n他出发了。\n\n## 第二章 转折\n\n他停下了。\n"
        document = parse_source(text, title="书名")

        self.assertEqual([chapter.title for chapter in document.chapters], ["第一章 起点", "第二章 转折"])
        self.assertNotEqual(document.title, "第一卷 风起")

    def test_single_chinese_chapter_heading(self) -> None:
        document = parse_source("第一章 起点\n\n他出发了。\n", title="路")

        self.assertEqual([chapter.title for chapter in document.chapters], ["第一章 起点"])
        self.assertEqual(document.sentences[0].text, "他出发了。")

    def test_no_headings_is_one_chapter(self) -> None:
        document = parse_source("只有一段。\n\n还有一段。\n", path="novel.md")

        self.assertEqual(len(document.chapters), 1)
        self.assertEqual(document.chapters[0].title, "全文")
        self.assertEqual(document.title, "novel")

    def test_title_heading_is_not_a_prologue(self) -> None:
        document = make_document()

        self.assertEqual(document.chapters[0].title, "第一章 咖啡馆")
        self.assertEqual(document.chapters[0].index, 1)

    def test_crlf_is_normalized(self) -> None:
        document = parse_source("# 标题\r\n\r\n第一段。\r\n", title="标题")

        self.assertNotIn("\r", document.text)
        self.assertEqual(document.sentences[0].text, "第一段。")

    def test_empty_source_raises(self) -> None:
        with self.assertRaises(AdapterError):
            parse_source("   \n\n", title="空")

    def test_scene_source_text_excludes_chapter_headings(self) -> None:
        document = make_document()
        sentence_start = document.chapters[1].sentence_ids[0]
        index = next(i for i, sentence in enumerate(document.sentences) if sentence.id == sentence_start)
        from screenplay_adapter.models import Scene, SourceSpan

        scene = Scene(
            id="S001",
            episode=1,
            index_in_episode=1,
            beat="hook",
            beat_label="钩子",
            duration_s=30,
            source=SourceSpan(index, index + 1, 0, 0),
        )

        self.assertNotIn("##", scene_source_text(document, scene))


if __name__ == "__main__":
    unittest.main()

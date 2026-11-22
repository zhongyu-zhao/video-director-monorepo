from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from screenplay_adapter.cast import extract_cast, find_characters, load_cast_file
from screenplay_adapter.models import AdapterError
from screenplay_adapter.source import parse_source

from tests.support import make_document


class CastExtractionTest(unittest.TestCase):
    def test_extracts_speakers_from_dialogue(self) -> None:
        cast = extract_cast(make_document())

        self.assertEqual([character.name for character in cast], ["林昭", "顾远"])
        self.assertTrue(all(character.dialogue_mentions >= 1 for character in cast))

    def test_ignores_speech_verb_inside_quoted_line(self) -> None:
        document = parse_source("“看完之后，你就知道真相。”\n", title="测试")

        cast = extract_cast(document)

        self.assertEqual(cast, [])

    def test_ignores_narration_with_dao(self) -> None:
        document = parse_source("她注意到他的袖口有一道新的划痕。\n", title="测试")

        self.assertEqual(extract_cast(document), [])

    def test_explicit_cast_overrides_and_keeps_aliases(self) -> None:
        document = make_document()
        explicit = [
            {"name": "林昭", "aliases": ["阿昭"], "role": "主角", "note": "记者"},
            {"name": "顾远"},
        ]

        cast = extract_cast(document, explicit=explicit)

        self.assertEqual([character.name for character in cast], ["林昭", "顾远"])
        self.assertEqual(cast[0].aliases, ("阿昭",))
        self.assertEqual(cast[0].source, "explicit")
        self.assertEqual(cast[0].role, "主角")
        self.assertEqual(cast[0].first_chapter, "CH001")

    def test_find_characters_uses_aliases_and_order(self) -> None:
        document = make_document()
        cast = extract_cast(
            document,
            explicit=[{"name": "林昭", "aliases": ["阿昭"]}, {"name": "顾远"}],
        )

        found = find_characters("阿昭看着顾远。", cast)

        self.assertEqual(found, ["林昭", "顾远"])

    def test_load_cast_file_accepts_list_and_object(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cast.json"
            path.write_text(json.dumps({"characters": [{"name": "林昭", "aliases": ["阿昭"]}]}), encoding="utf-8")

            entries = load_cast_file(path)

        self.assertEqual(entries[0]["name"], "林昭")

    def test_load_cast_file_rejects_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cast.json"
            path.write_text(json.dumps([{"name": "林昭"}, {"name": "林昭"}]), encoding="utf-8")

            with self.assertRaises(AdapterError):
                load_cast_file(path)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest

from auto_shot.models import ShotTable, shots_from_cuts
from auto_shot.screenplay import build_screenplay
from tests.support import sample_table


def table() -> ShotTable:
    value = sample_table()
    value.shots = shots_from_cuts([2.0, 4.0], 6.0)
    return value


class ScreenplayTest(unittest.TestCase):
    def test_aligns_asr_to_shots_and_scenes(self) -> None:
        labels = {
            "shots": {
                "S001": {
                    "labels": {"scale": "close", "camera": "static", "lighting": "low-key", "color": "warm"},
                    "content": {"subjects": ["女孩"], "action": "女孩抬头"},
                }
            }
        }
        scenes = {
            "scenes": [
                {"scene_id": "SC001", "start": 0.0, "end": 4.0, "shot_ids": ["S001", "S002"], "title": "初见", "summary": "两人在门口相遇", "stats": {}},
                {"scene_id": "SC002", "start": 4.0, "end": 6.0, "shot_ids": ["S003"], "title": "离开", "summary": "女孩离开", "stats": {}},
            ]
        }
        asr = {
            "model": "fake-asr",
            "language": "ja",
            "segments": [
                {"start": 0.5, "end": 1.5, "text": "こんにちは"},
                {"start": 2.5, "end": 3.5, "text": "またね"},
            ],
        }
        evidence = {"shots": {"S001": {"measured": {"brightness": 0.4, "motion": 0.1}}}}
        with tempfile.TemporaryDirectory() as directory:
            result = build_screenplay(table(), directory, labels=labels, scenes=scenes, asr=asr, evidence=evidence)
            markdown = result.markdown_path.read_text(encoding="utf-8")
            payload = json.loads(result.json_path.read_text(encoding="utf-8"))

        self.assertIn("SC001", markdown)
        self.assertIn("こんにちは", markdown)
        self.assertIn("自动转写", markdown)
        self.assertEqual(len(payload["scenes"][0]["shots"][0]["dialogue"]), 1)
        self.assertEqual(payload["scenes"][0]["shots"][0]["dialogue"][0]["text"], "こんにちは")
        self.assertEqual(len(payload["scenes"][1]["shots"]), 1)

    def test_without_asr_still_renders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = build_screenplay(table(), directory)
            markdown = result.markdown_path.read_text(encoding="utf-8")
        self.assertIn("未提供", markdown)
        self.assertIn("未聚合场景", markdown)

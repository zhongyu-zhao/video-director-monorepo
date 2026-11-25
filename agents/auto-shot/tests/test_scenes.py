from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from auto_shot.models import ShotTable, shots_from_cuts
from auto_shot.scenes import SceneError, build_scenes
from tests.support import sample_table


def table() -> ShotTable:
    value = sample_table()
    value.shots = shots_from_cuts([1.0, 2.0, 3.0, 4.0, 5.0], 6.0)
    return value


class SceneBuildTest(unittest.TestCase):
    def test_groups_by_max_shots_and_writes_stats(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = build_scenes(table(), root, max_shots=3, max_seconds=180)
            payload = json.loads(result.scenes_path.read_text(encoding="utf-8"))
            self.assertTrue(result.report_path.is_file())
            report = result.report_path.read_text(encoding="utf-8")

        self.assertEqual(len(result.scenes), 2)
        self.assertEqual(payload["stats"]["total_shots"], 6)
        self.assertEqual(payload["stats"]["scene_count"], 2)
        self.assertIn("SC001", report)

    def test_uses_labels_and_evidence_in_scene_cards(self) -> None:
        evidence = {
            "_root": "/tmp/evidence",
            "black_bars": {"left": 0, "top": 0, "right": 0, "bottom": 0},
            "shots": {
                "S001": {
                    "contact_sheet": "contact-sheets/S001.jpg",
                    "keyframes": ["frames/S001-k1.jpg"],
                    "measured": {"brightness": 0.4, "motion": 0.1, "saturation": 0.2, "contrast": 0.3, "face_ratio": 0.05},
                    "audio": {"silence_ratio": 0.0},
                }
            },
            "audio_events": [],
        }
        labels = {
            "shots": {
                "S001": {
                    "labels": {"scale": "close", "camera": "static", "lighting": "low-key", "color": "cool", "angle": "eye-level", "dof": "shallow"},
                    "content": {"subjects": ["女孩"], "action": "女孩抬头"},
                    "function": {"beat": "unknown", "emotion": "unknown"},
                    "confidence": {},
                }
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            result = build_scenes(table(), directory, evidence=evidence, labels=labels, max_shots=3)
            payload = json.loads(result.scenes_path.read_text(encoding="utf-8"))
            report = result.report_path.read_text(encoding="utf-8")

        self.assertEqual(payload["stats"]["labeled_shots"], 1)
        self.assertEqual(payload["stats"]["scale"]["close"], 1)
        self.assertEqual(payload["stats"]["angle"]["eye-level"], 1)
        self.assertEqual(payload["scenes"][0]["stats"]["angle"]["eye-level"], 1)
        self.assertIn("角度", report)
        self.assertAlmostEqual(payload["stats"]["brightness"], 0.4)
        self.assertIn("S001.jpg", report)

    def test_semantic_grouping_uses_label_changes_not_fixed_blocks(self) -> None:
        value = sample_table()
        value.shots = shots_from_cuts([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0], 10.0)
        labels = {"shots": {}}
        evidence = {"shots": {}}
        for index, shot in enumerate(value.shots):
            scale = "close" if index < 5 else "long"
            lighting = "low-key" if index < 5 else "high-key"
            labels["shots"][shot.shot_id] = {
                "labels": {"scale": scale, "camera": "static", "lighting": lighting, "color": "cool", "angle": "eye-level", "dof": "shallow"},
                "content": {"subjects": ["A"] if index < 5 else ["B"], "action": "x"},
                "confidence": {},
            }
            evidence["shots"][shot.shot_id] = {"measured": {"brightness": 0.2 if index < 5 else 0.8}}
        with tempfile.TemporaryDirectory() as directory:
            result = build_scenes(value, directory, labels=labels, evidence=evidence, max_shots=30, min_shots=2, threshold=0.5)
        self.assertEqual(len(result.scenes), 2)
        self.assertEqual(len(result.scenes[0].shots), 5)
        self.assertEqual(len(result.scenes[1].shots), 5)

    def test_narrative_plan_sets_titles_and_summaries(self) -> None:
        plan = [
            {"start_shot": "S001", "end_shot": "S003", "title": "初见", "summary": "两人在门口相遇", "boundary_reason": "切到室内"},
            {"start_shot": "S004", "end_shot": "S006", "title": "对话", "summary": "两人开始交谈", "boundary_reason": ""},
        ]
        with tempfile.TemporaryDirectory() as directory:
            result = build_scenes(table(), directory, plan=plan, reduce_mode="narrative")
            payload = json.loads(result.scenes_path.read_text(encoding="utf-8"))
        self.assertEqual(len(result.scenes), 2)
        self.assertEqual(result.scenes[0].title, "初见")
        self.assertEqual(payload["scenes"][0]["summary"], "两人在门口相遇")
        self.assertEqual(payload["config"]["reduce"], "narrative")

    def test_rejects_invalid_grouping(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(SceneError):
            build_scenes(table(), directory, max_shots=0)

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
        self.assertAlmostEqual(payload["stats"]["brightness"], 0.4)
        self.assertIn("S001.jpg", report)

    def test_rejects_invalid_grouping(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(SceneError):
            build_scenes(table(), directory, max_shots=0)

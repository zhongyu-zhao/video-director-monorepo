from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from auto_shot.models import ShotTable, shots_from_cuts
from auto_shot.review import (
    ReviewError,
    apply_review,
    build_review_annotations,
    render_review_html,
)
from tests.support import sample_table


def table() -> ShotTable:
    value = sample_table()
    value.shots = shots_from_cuts([2.0, 4.0], 6.0)
    return value


class ReviewPageTest(unittest.TestCase):
    def test_writes_self_contained_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "input.mp4"
            video.write_bytes(b"not a real video")
            out = root / "out" / "review.html"

            written = render_review_html(table(), video, out, status="测试阶段")
            page = written.read_text(encoding="utf-8")

        self.assertEqual(written, out)
        self.assertIn("auto-shot 切点检查", page)
        self.assertIn("测试阶段", page)
        self.assertIn('"shot_id": "S001"', page)
        self.assertIn("input.mp4", page)
        for placeholder in ("__SHOTS_JSON__", "__SOURCE_JSON__", "__REVIEW_KEY_JSON__", "__VIDEO_SRC__", "__COUNT__", "__STATUS__", "__GENERATED__", "__DETECTOR__", "__ANNOTATIONS_JSON__", "__SCENES_JSON__"):
            self.assertNotIn(placeholder, page)

    def test_embeds_labels_scenes_and_evidence(self) -> None:
        labels = {
            "shots": {
                "S001": {
                    "labels": {"scale": "close", "angle": "eye-level", "camera": "static", "composition": "centered", "lighting": "low-key", "color": "warm", "dof": "shallow"},
                    "content": {"subjects": ["女孩"], "action": "女孩抬头"},
                    "function": {"beat": "unknown", "emotion": "unknown"},
                    "evidence": {"scale": "占满画面"},
                    "confidence": {"scale": 0.9, "angle": 0.8, "camera": 0.9, "composition": 0.8, "lighting": 0.8, "color": 0.9, "dof": 0.7},
                }
            }
        }
        scenes = {
            "scenes": [
                {
                    "scene_id": "SC001",
                    "start": 0.0,
                    "end": 4.0,
                    "shot_ids": ["S001", "S002"],
                    "stats": {"shot_count": 2, "scale": {"close": 1}, "angle": {"eye-level": 1}, "camera": {"static": 1}, "brightness": 0.4, "motion": 0.1},
                }
            ]
        }
        evidence = {
            "shots": {
                "S001": {
                    "measured": {"brightness": 0.4, "motion": 0.1, "face_ratio": 0.05},
                    "audio": {"silence_ratio": 0.0},
                    "contact_sheet": None,
                    "keyframes": [],
                }
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "input.mp4"
            video.write_bytes(b"not a real video")
            out = root / "out" / "review.html"
            written = render_review_html(table(), video, out, labels=labels, scenes=scenes, evidence=evidence)
            page = written.read_text(encoding="utf-8")

        self.assertIn("SC001", page)
        self.assertIn("scene-card", page)
        self.assertIn("close", page)
        self.assertIn("eye-level", page)
        self.assertIn("<th>角度</th>", page)
        self.assertIn("角度 eye-level 1", page)
        self.assertIn("女孩抬头", page)
        self.assertIn("brightness", page)

    def test_maps_verified_shot_to_longest_source_shot(self) -> None:
        source = table()
        displayed = table()
        displayed.shots = source.shots[:1]
        labels = {"shots": {"S001": {"labels": {"scale": "close"}}}}
        annotations, _cards = build_review_annotations(displayed, labels=labels, source_table=source)
        self.assertEqual(annotations["S001"]["label_source"], "S001")


class ApplyReviewTest(unittest.TestCase):
    def test_merges_false_cut_into_predecessor(self) -> None:
        corrected = apply_review(table(), {"falseCuts": ["S002"], "missedCuts": []})

        self.assertEqual(len(corrected.shots), 2)
        self.assertEqual((corrected.shots[0].start, corrected.shots[0].end), (0.0, 4.0))
        self.assertEqual(corrected.shots[0].source, "manual")
        self.assertEqual(corrected.shots[1].shot_id, "S002")

    def test_splits_missed_cut_and_records_manual_boundary(self) -> None:
        corrected = apply_review(table(), {"falseCuts": [], "missedCuts": [3.0]})

        self.assertEqual([shot.shot_id for shot in corrected.shots], ["S001", "S002", "S003", "S004"])
        self.assertEqual([shot.start for shot in corrected.shots], [0.0, 2.0, 3.0, 4.0])
        self.assertEqual([shot.end for shot in corrected.shots], [2.0, 3.0, 4.0, 6.0])
        self.assertEqual(corrected.shots[1].source, "manual")
        self.assertEqual(corrected.shots[2].source, "manual")
        self.assertEqual(corrected.manual_cuts, [3.0])

    def test_rejects_non_object_flags(self) -> None:
        with self.assertRaises(ReviewError):
            apply_review(table(), [])

    def test_rejects_false_cut_on_first_shot(self) -> None:
        with self.assertRaises(ReviewError):
            apply_review(table(), {"falseCuts": ["S001"], "missedCuts": []})

    def test_rejects_missed_cut_outside_shots(self) -> None:
        with self.assertRaises(ReviewError):
            apply_review(table(), {"falseCuts": [], "missedCuts": [9.0]})

    def test_ignores_missed_cut_already_on_boundary(self) -> None:
        corrected = apply_review(table(), {"falseCuts": [], "missedCuts": [2.0]})

        self.assertEqual(len(corrected.shots), 3)
        self.assertEqual(corrected.manual_cuts, [])

    def test_round_trips_through_json(self) -> None:
        flags = json.loads('{"falseCuts": ["S002"], "missedCuts": []}')

        corrected = apply_review(table(), flags)

        self.assertEqual(corrected.to_dict()["manual_cuts"], [])
        self.assertEqual(len(corrected.to_dict()["shots"]), 2)


if __name__ == "__main__":
    unittest.main()

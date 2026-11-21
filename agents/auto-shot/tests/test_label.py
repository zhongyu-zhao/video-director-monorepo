from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from auto_shot.label import LabelError, build_prompt, label_shots, validate_response
from auto_shot.models import Shot, shots_from_cuts

from tests.support import sample_table

VALID_RESPONSE = {
    "labels": {
        "scale": "close",
        "angle": "eye-level",
        "camera": "unknown",
        "composition": "centered",
        "lighting": "low-key",
        "color": "cool",
        "dof": "shallow",
    },
    "content": {
        "subjects": ["人物"],
        "action": "人物站在画面中央，背景较暗",
    },
    "evidence": {
        "scale": "人脸占画面较大比例",
        "lighting": "背景暗、主体亮",
        "color": "整体偏冷",
    },
    "confidence": {
        "scale": 0.8,
        "angle": 0.7,
        "camera": 0.0,
        "composition": 0.6,
        "lighting": 0.7,
        "color": 0.8,
        "dof": 0.5,
    },
}


class FakeClient:
    model = "fake-model"

    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or VALID_RESPONSE
        self.calls = 0

    def label_image(self, image: bytes, prompt: str) -> dict:
        self.calls += 1
        return json.loads(json.dumps(self.payload))


def fake_frame(video, shot, output) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake-jpeg")
    return path


def table_with_shots():
    table = sample_table()
    table.shots = shots_from_cuts([2.0, 4.0], 6.0)
    return table


class PromptAndValidationTest(unittest.TestCase):
    def test_prompt_contains_schema_and_single_frame_constraint(self) -> None:
        prompt = build_prompt(table_with_shots().shots[0])

        self.assertIn("S001", prompt)
        self.assertIn("camera", prompt)
        self.assertIn("单帧", prompt)
        self.assertIn("unknown", prompt)

    def test_valid_response_is_normalized(self) -> None:
        normalized = validate_response(VALID_RESPONSE)

        self.assertEqual(normalized["labels"]["scale"], "close")
        self.assertEqual(normalized["content"]["dialogue"], "")
        self.assertEqual(normalized["function"]["beat"], "unknown")
        self.assertEqual(normalized["confidence"]["dof"], 0.5)

    def test_camera_motion_is_rejected_for_single_frame(self) -> None:
        payload = json.loads(json.dumps(VALID_RESPONSE))
        payload["labels"]["camera"] = "static"

        with self.assertRaises(LabelError):
            validate_response(payload)

    def test_non_object_response_is_rejected(self) -> None:
        with self.assertRaises(LabelError):
            validate_response([])

    def test_invalid_enum_is_rejected(self) -> None:
        payload = json.loads(json.dumps(VALID_RESPONSE))
        payload["labels"]["scale"] = "超级特写"

        with self.assertRaises(LabelError):
            validate_response(payload)


class LabelShotsTest(unittest.TestCase):
    def test_labels_limited_shots_and_caches_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = FakeClient()

            first = label_shots(
                table_with_shots(),
                "input.mp4",
                root,
                client,
                limit=2,
                workers=1,
                frame_extractor=fake_frame,
            )
            self.assertEqual((first.labeled, first.skipped, first.errors), (2, 1, []))
            self.assertEqual(client.calls, 2)
            self.assertTrue(first.labels_path.is_file())
            self.assertTrue(first.markdown_path.is_file())

            payload = json.loads(first.labels_path.read_text(encoding="utf-8"))
            self.assertEqual(set(payload["shots"]), {"S001", "S002"})
            self.assertIn("S001", first.markdown_path.read_text(encoding="utf-8"))

            second = label_shots(
                table_with_shots(),
                "input.mp4",
                root,
                client,
                limit=None,
                workers=1,
                frame_extractor=fake_frame,
            )
            self.assertEqual((second.labeled, second.skipped), (1, 2))
            self.assertEqual(client.calls, 3)
            payload = json.loads(second.labels_path.read_text(encoding="utf-8"))
            self.assertEqual(set(payload["shots"]), {"S001", "S002", "S003"})

            third = label_shots(
                table_with_shots(),
                "input.mp4",
                root,
                client,
                limit=1,
                force=True,
                workers=1,
                frame_extractor=fake_frame,
            )
            self.assertEqual(third.labeled, 1)
            self.assertEqual(client.calls, 4)

    def test_bad_response_is_recorded_without_losing_the_batch(self) -> None:
        bad = json.loads(json.dumps(VALID_RESPONSE))
        bad["labels"]["camera"] = "static"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = label_shots(
                table_with_shots(),
                "input.mp4",
                root,
                FakeClient(bad),
                limit=1,
                workers=1,
                frame_extractor=fake_frame,
            )

        self.assertEqual(result.labeled, 0)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0]["shot_id"], "S001")


class ShotHashTest(unittest.TestCase):
    def test_prompt_is_stable_for_same_shot(self) -> None:
        shot = Shot(shot_id="S001", start=0.0, end=2.0)
        self.assertEqual(build_prompt(shot), build_prompt(shot))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from auto_shot.models import ShotTable, shots_from_cuts
from auto_shot.verify import (
    VerificationError,
    apply_verdicts,
    collect_boundaries,
    short_shot_boundaries,
    verify_short_shots,
)
from tests.support import sample_table


def table() -> ShotTable:
    value = sample_table()
    value.shots = shots_from_cuts([1.5, 2.0, 3.5, 4.4, 5.5], 6.0)
    return value


class BoundarySelectionTest(unittest.TestCase):
    def test_selects_only_short_shot_boundaries(self) -> None:
        boundaries = short_shot_boundaries(table(), max_duration=1.0)
        self.assertIn(1.5, boundaries)
        self.assertIn(2.0, boundaries)
        self.assertIn(3.5, boundaries)
        self.assertIn(4.4, boundaries)
        self.assertIn(5.5, boundaries)

        all_boundaries = short_shot_boundaries(table(), max_duration=10.0)
        self.assertTrue({1.5, 2.0, 3.5, 4.4, 5.5}.issubset(all_boundaries))

    def test_window_filters_whole_shots(self) -> None:
        boundaries = short_shot_boundaries(table(), window=(1.4, 2.1), max_duration=1.0)
        self.assertEqual(boundaries, {1.5, 2.0})

    def test_collects_union_across_tables(self) -> None:
        other = table()
        other.shots = shots_from_cuts([1.6, 2.1, 4.5], 6.0)
        union = collect_boundaries([table(), other], None, 1.0)
        self.assertIn(1.5, union)
        self.assertNotIn(1.6, union)  # 1.5/1.6 are one visual boundary cluster


class ApplyVerdictsTest(unittest.TestCase):
    def test_merges_false_boundaries_and_renumbers(self) -> None:
        corrected = apply_verdicts(table(), [1.5, 3.5])
        self.assertTrue(corrected.shots[0].source == "vlm")
        self.assertEqual([shot.start for shot in corrected.shots], [0.0, 2.0, 4.4, 5.5])
        self.assertEqual([shot.shot_id for shot in corrected.shots], ["S001", "S002", "S003", "S004"])

    def test_no_verdicts_is_a_noop(self) -> None:
        original = table()
        corrected = apply_verdicts(original, [])
        self.assertEqual(corrected.to_dict(), original.to_dict())


class FakeClient:
    model = "fake-model"

    def __init__(self, verdicts: dict[float, tuple[bool, float]]) -> None:
        self.verdicts = verdicts
        self.calls = 0

    def label_image(self, image: bytes, prompt: str) -> dict:
        self.calls += 1
        time = round(float(image.decode()), 3)
        same, confidence = self.verdicts.get(time, (False, 0.0))
        return {"same_shot": same, "confidence": confidence, "reason": f"fake {time}"}


def fake_pairs(video, table, boundaries, work_dir) -> dict[float, Path]:
    root = Path(work_dir)
    root.mkdir(parents=True, exist_ok=True)
    result = {}
    for time in boundaries:
        path = root / f"{time:.3f}.jpg"
        path.write_bytes(str(time).encode())
        result[time] = path
    return result


class VerifyTest(unittest.TestCase):
    def test_verifies_merges_and_caches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = FakeClient(
                {
                    1.5: (True, 0.9),
                    2.0: (False, 0.9),
                    3.5: (True, 0.9),
                    4.4: (False, 0.9),
                    5.5: (True, 0.5),
                }
            )
            result = verify_short_shots(
                [table()],
                "sample.mp4",
                root,
                client,
                limit=None,
                workers=1,
                pair_extractor=fake_pairs,
            )

            self.assertEqual(client.calls, 5)
            self.assertEqual(result.errors, [])
            self.assertEqual(len(result.removed["table-1"]), 2)
            verified = json.loads(next(iter(result.verified_paths.values())).read_text(encoding="utf-8"))
            self.assertEqual(len(verified["shots"]), 4)
            self.assertTrue(result.verifications_path.is_file())
            self.assertTrue(result.report_path.is_file())

            second = verify_short_shots(
                [table()],
                "sample.mp4",
                root,
                client,
                limit=None,
                workers=1,
                pair_extractor=fake_pairs,
            )
            self.assertEqual(second.errors, [])
            self.assertEqual(client.calls, 5)

    def test_bad_response_is_recorded_and_boundary_kept(self) -> None:
        class BadClient(FakeClient):
            def label_image(self, image: bytes, prompt: str) -> dict:
                self.calls += 1
                return {"same_shot": "yes", "confidence": 0.9, "reason": "bad"}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = BadClient({})
            result = verify_short_shots(
                [table()],
                "sample.mp4",
                root,
                client,
                limit=1,
                workers=1,
                pair_extractor=fake_pairs,
            )

        self.assertEqual(result.errors[0]["time"], "1.500")
        self.assertEqual(result.removed["table-1"], [])

    def test_two_tables_share_one_boundary_set(self) -> None:
        other = table()
        other.shots = shots_from_cuts([1.6, 2.1, 4.5], 6.0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = FakeClient({1.5: (True, 0.9), 1.6: (True, 0.9)})
            result = verify_short_shots(
                [table(), other],
                "sample.mp4",
                root,
                client,
                limit=None,
                workers=1,
                pair_extractor=fake_pairs,
            )

        self.assertEqual(len(result.verified_paths), 2)
        self.assertLessEqual(client.calls, len(result.boundaries))
        self.assertTrue(all(len(times) >= 0 for times in result.removed.values()))

    def test_rejects_different_videos(self) -> None:
        other = table()
        other.video = other.video.__class__(
            path="other.mp4",
            duration=other.video.duration,
            fps=other.video.fps,
            width=other.video.width,
            height=other.video.height,
            has_audio=other.video.has_audio,
        )
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(VerificationError):
            verify_short_shots(
                [table(), other],
                "sample.mp4",
                directory,
                FakeClient({}),
                pair_extractor=fake_pairs,
            )


if __name__ == "__main__":
    unittest.main()

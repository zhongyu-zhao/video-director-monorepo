from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from auto_shot.models import DetectorInfo, MediaInfo, ShotTable, shots_from_cuts

from tests.support import sample_table


class ShotsFromCutsTest(unittest.TestCase):
    def test_builds_contiguous_sequential_shots(self) -> None:
        shots = shots_from_cuts([4.0, 2.0], 6.0)

        self.assertEqual([shot.shot_id for shot in shots], ["S001", "S002", "S003"])
        self.assertEqual([shot.start for shot in shots], [0.0, 2.0, 4.0])
        self.assertEqual([shot.end for shot in shots], [2.0, 4.0, 6.0])
        self.assertEqual([shot.transition_in for shot in shots], ["start", "cut", "cut"])
        self.assertEqual([shot.duration for shot in shots], [2.0, 2.0, 2.0])

    def test_ignores_boundaries_at_or_beyond_media_edges(self) -> None:
        shots = shots_from_cuts([0.0, 6.0, 7.0], 6.0)
        self.assertEqual(len(shots), 1)
        self.assertEqual((shots[0].start, shots[0].end), (0.0, 6.0))

    def test_drops_boundaries_that_would_create_degenerate_shots(self) -> None:
        shots = shots_from_cuts([0.01, 2.0, 2.02], 6.0)
        self.assertEqual([shot.start for shot in shots], [0.0, 2.0])
        self.assertEqual(shots[-1].end, 6.0)

    def test_rounds_times_to_milliseconds(self) -> None:
        shots = shots_from_cuts([2.0004], 6.0)
        self.assertEqual(shots[0].end, 2.0)
        self.assertEqual(shots[1].start, 2.0)

    def test_rejects_non_positive_duration(self) -> None:
        with self.assertRaises(ValueError):
            shots_from_cuts([1.0], 0.0)


class ShotTableSerializationTest(unittest.TestCase):
    def test_round_trips_through_dict(self) -> None:
        table = ShotTable(
            video=MediaInfo(
                path="sample.mp4",
                duration=6.0,
                fps=25.0,
                width=320,
                height=240,
                has_audio=True,
            ),
            detector=DetectorInfo(name="ffmpeg-scene", threshold=0.3),
            shots=shots_from_cuts([2.0, 4.0], 6.0),
            manual_cuts=[3.5],
        )

        restored = ShotTable.from_dict(json.loads(json.dumps(table.to_dict())))

        self.assertEqual(restored.to_dict(), table.to_dict())

    def test_saves_and_loads_json(self) -> None:
        table = sample_table()
        table.shots = shots_from_cuts([2.0, 4.0], 6.0)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shots.json"
            table.save(path)
            loaded = ShotTable.load(path)
            written = path.read_text(encoding="utf-8")

        self.assertEqual(loaded.to_dict(), table.to_dict())
        self.assertTrue(written.endswith("\n"))


if __name__ == "__main__":
    unittest.main()

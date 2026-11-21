from __future__ import annotations

import unittest

from auto_shot.models import ShotTable, shots_from_cuts
from auto_shot.scene_reduce import SceneReduceError, validate_plan
from tests.support import sample_table


def table() -> ShotTable:
    value = sample_table()
    value.shots = shots_from_cuts([1.0, 2.0, 3.0, 4.0, 5.0], 6.0)
    return value


class ValidatePlanTest(unittest.TestCase):
    def test_accepts_contiguous_plan(self) -> None:
        plan = validate_plan(
            table(),
            [
                {"start_shot": "S001", "end_shot": "S003", "title": "A", "summary": "a"},
                {"start_shot": "S004", "end_shot": "S006", "title": "B", "summary": "b"},
            ],
        )
        self.assertEqual(len(plan), 2)

    def test_rejects_gap(self) -> None:
        with self.assertRaises(SceneReduceError):
            validate_plan(
                table(),
                [
                    {"start_shot": "S001", "end_shot": "S002", "title": "A", "summary": "a"},
                    {"start_shot": "S004", "end_shot": "S006", "title": "B", "summary": "b"},
                ],
            )

    def test_rejects_missing_end(self) -> None:
        with self.assertRaises(SceneReduceError):
            validate_plan(
                table(),
                [{"start_shot": "S001", "end_shot": "S003", "title": "A", "summary": "a"}],
            )

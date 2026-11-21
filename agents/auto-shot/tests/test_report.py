from __future__ import annotations

import unittest
from dataclasses import replace

from auto_shot.models import shots_from_cuts
from auto_shot.quality import validate_shot_table
from auto_shot.report import format_timecode, render_report

from tests.support import sample_table


class TimecodeTest(unittest.TestCase):
    def test_formats_hours_minutes_seconds_and_milliseconds(self) -> None:
        self.assertEqual(format_timecode(0), "00:00:00.000")
        self.assertEqual(format_timecode(65.5), "00:01:05.500")
        self.assertEqual(format_timecode(3661.001), "01:01:01.001")


class ReportTest(unittest.TestCase):
    def setUp(self) -> None:
        table = sample_table()
        table.shots = shots_from_cuts([2.0, 4.0], 6.0)
        self.report = render_report(table, validate_shot_table(table))

    def test_contains_summary_and_every_shot(self) -> None:
        self.assertIn("- 镜头数：3", self.report)
        self.assertIn("- 平均镜长：2.000s", self.report)
        self.assertIn("| S001 | 00:00:00.000 | 00:00:02.000 |", self.report)
        self.assertIn("| S003 | 00:00:04.000 | 00:00:06.000 |", self.report)

    def test_lists_gate_results(self) -> None:
        self.assertIn("## 质量门：通过", self.report)
        self.assertIn("| `timeline_contiguous` | 通过 |", self.report)
        self.assertIn("| `motion_consistency` | 跳过 |", self.report)

    def test_failed_gate_changes_verdict(self) -> None:
        table = sample_table()
        table.shots = shots_from_cuts([2.0, 4.0], 6.0)
        table.shots[1] = replace(table.shots[1], start=2.5)

        report = render_report(table, validate_shot_table(table))

        self.assertIn("## 质量门：未通过", report)
        self.assertIn("| `timeline_contiguous` | 失败 |", report)


if __name__ == "__main__":
    unittest.main()

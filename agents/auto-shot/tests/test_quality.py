from __future__ import annotations

import unittest
from dataclasses import replace

from auto_shot.models import ShotTable, shots_from_cuts
from auto_shot.quality import FAIL, PASS, SKIP, validate_shot_table

from tests.support import sample_table


def valid_table() -> ShotTable:
    table = sample_table()
    table.shots = shots_from_cuts([2.0, 4.0], 6.0)
    return table


class QualityGateTest(unittest.TestCase):
    def test_valid_table_passes(self) -> None:
        report = validate_shot_table(valid_table())

        self.assertTrue(report.ok)
        self.assertEqual(report.failed, [])
        statuses = {check.id: check.status for check in report.checks}
        self.assertEqual(statuses["timeline_contiguous"], PASS)
        self.assertEqual(statuses["schema_version"], PASS)

    def test_gap_between_shots_fails(self) -> None:
        table = valid_table()
        table.shots[1] = replace(table.shots[1], start=2.5)

        report = validate_shot_table(table)

        self.assertFalse(report.ok)
        self.assertEqual([check.id for check in report.failed], ["timeline_contiguous"])

    def test_uncovered_media_fails(self) -> None:
        table = valid_table()
        table.shots[-1] = replace(table.shots[-1], end=5.0)

        report = validate_shot_table(table)

        self.assertIn("timeline_covers_media", [check.id for check in report.failed])

    def test_out_of_order_ids_fail(self) -> None:
        table = valid_table()
        table.shots[0] = replace(table.shots[0], shot_id="S999")

        report = validate_shot_table(table)

        self.assertIn("sequential_ids", [check.id for check in report.failed])

    def test_empty_table_fails(self) -> None:
        report = validate_shot_table(sample_table())

        self.assertFalse(report.ok)
        statuses = {check.id: check.status for check in report.checks}
        self.assertEqual(statuses["shots_present"], FAIL)
        self.assertEqual(statuses["timeline_contiguous"], SKIP)

    def test_manual_cuts_are_skipped_when_absent(self) -> None:
        report = validate_shot_table(valid_table())
        statuses = {check.id: check.status for check in report.checks}
        self.assertEqual(statuses["manual_cuts_valid"], SKIP)

    def test_missing_labeling_gates_are_skipped_not_passed(self) -> None:
        report = validate_shot_table(valid_table())
        statuses = {check.id: check.status for check in report.checks}
        for gate in ("label_enums", "evidence_present", "motion_consistency"):
            self.assertEqual(statuses[gate], SKIP)

    def test_counts_are_reported(self) -> None:
        counts = validate_shot_table(valid_table()).counts()
        self.assertGreater(counts[PASS], 0)
        self.assertEqual(counts[FAIL], 0)
        self.assertGreater(counts[SKIP], 0)


if __name__ == "__main__":
    unittest.main()

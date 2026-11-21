from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from video_director.models import Asset
from video_director.validate import FAIL, PASS, SKIP, validate_project

from tests.support import project_with_clips


class ValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name) / "project"
        self.project = project_with_clips(self.root)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def statuses(self):
        report = validate_project(self.project, self.root)
        return report, {check.id: check.status for check in report.checks}

    def test_valid_project_passes(self) -> None:
        report, statuses = self.statuses()

        self.assertTrue(report.ok)
        self.assertEqual(statuses["timeline_contiguous"], PASS)
        self.assertEqual(statuses["clip_ranges"], PASS)
        self.assertEqual(statuses["audio_track"], SKIP)

    def test_missing_asset_file_fails(self) -> None:
        (self.root / "assets" / "b.mp4").unlink()

        report, statuses = self.statuses()

        self.assertFalse(report.ok)
        self.assertEqual(statuses["assets_exist"], FAIL)

    def test_gap_fails_contiguity(self) -> None:
        self.project.timeline.clips[1] = replace(self.project.timeline.clips[1], start=2.5)

        report, statuses = self.statuses()

        self.assertEqual(statuses["timeline_contiguous"], FAIL)
        self.assertFalse(report.ok)

    def test_overlap_fails_contiguity(self) -> None:
        self.project.timeline.clips[1] = replace(self.project.timeline.clips[1], start=1.5)

        _, statuses = self.statuses()

        self.assertEqual(statuses["timeline_contiguous"], FAIL)

    def test_source_out_beyond_asset_duration_fails(self) -> None:
        self.project.timeline.clips[0] = replace(self.project.timeline.clips[0], source_out=3.0)

        _, statuses = self.statuses()

        self.assertEqual(statuses["clip_ranges"], FAIL)

    def test_absolute_asset_path_fails(self) -> None:
        self.project.assets[0] = replace(
            self.project.assets[0],
            path=str(self.root / "assets" / "a.mp4"),
        )

        _, statuses = self.statuses()

        self.assertEqual(statuses["assets_exist"], FAIL)

    def test_escaping_asset_path_fails(self) -> None:
        self.project.assets[0] = replace(self.project.assets[0], path="../outside.mp4")

        _, statuses = self.statuses()

        self.assertEqual(statuses["assets_exist"], FAIL)

    def test_odd_resolution_fails(self) -> None:
        self.project.width = 321
        self.project.height = 181

        _, statuses = self.statuses()

        self.assertEqual(statuses["resolution_even"], FAIL)

    def test_duplicate_asset_ids_fail(self) -> None:
        self.project.assets.append(Asset(id="A001", path="assets/a.mp4", duration=2.0))

        _, statuses = self.statuses()

        self.assertEqual(statuses["asset_ids_unique"], FAIL)

    def test_empty_timeline_is_a_valid_draft(self) -> None:
        self.project.timeline.clips = []

        report, statuses = self.statuses()

        self.assertTrue(report.ok)
        self.assertEqual(statuses["timeline_present"], SKIP)
        self.assertEqual(statuses["timeline_contiguous"], SKIP)

    def test_non_video_assets_are_skipped_not_failed(self) -> None:
        (self.root / "assets" / "image.png").write_bytes(b"placeholder")
        self.project.assets.append(Asset(id="A003", path="assets/image.png", kind="image"))

        report, statuses = self.statuses()

        self.assertTrue(report.ok)
        self.assertEqual(statuses["asset_kinds"], SKIP)


if __name__ == "__main__":
    unittest.main()

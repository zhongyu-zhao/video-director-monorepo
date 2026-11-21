from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from video_director.project import add_asset, add_clip, create_project, save_project
from video_director.render import RenderError, render_project

from tests.support import ffmpeg_available, make_solid_clip


@unittest.skipUnless(ffmpeg_available(), "ffmpeg/ffprobe not installed")
class RenderIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self._temporary.name)
        self.root = self.workspace / "project"
        self.project = create_project(
            self.root,
            "render test",
            fps=25.0,
            width=320,
            height=180,
            project_id="proj-render",
        )
        fixtures = self.workspace / "fixtures"
        fixtures.mkdir()
        first = make_solid_clip(fixtures / "black.mp4", color="black")
        second = make_solid_clip(fixtures / "white.mp4", color="white")
        add_asset(self.project, self.root, first)
        add_asset(self.project, self.root, second)
        add_clip(self.project, "A001", 0.0, 2.0)
        add_clip(self.project, "A002", 0.0, 2.0)
        save_project(self.project, self.root)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_renders_contiguous_timeline_and_verifies_output(self) -> None:
        report = render_project(self.project, self.root)

        output = self.root / report.output
        self.assertTrue(output.is_file())
        self.assertTrue(report.ok)
        self.assertEqual(report.clip_count, 2)
        self.assertAlmostEqual(report.expected_duration, 4.0, places=3)
        self.assertAlmostEqual(report.actual_duration, 4.0, delta=0.2)
        self.assertEqual((report.width, report.height), (320, 180))
        self.assertAlmostEqual(report.fps, 25.0, delta=0.1)

        report_path = self.root / "renders" / "render_report.json"
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["project_revision"], self.project.revision)
        self.assertEqual(payload["clip_count"], 2)

    def test_render_blocks_invalid_timeline(self) -> None:
        self.project.timeline.clips[1] = replace(self.project.timeline.clips[1], start=3.0)

        with self.assertRaises(RenderError):
            render_project(self.project, self.root)

    def test_render_blocks_empty_timeline(self) -> None:
        empty = create_project(self.workspace / "empty", "empty", width=320, height=180, project_id="proj-empty")

        with self.assertRaises(RenderError):
            render_project(empty, self.workspace / "empty")

    def test_custom_output_path(self) -> None:
        destination = self.workspace / "custom" / "cut.mp4"

        report = render_project(self.project, self.root, output=destination)

        self.assertTrue(destination.is_file())
        self.assertTrue(report.ok)

    def test_trims_and_scales_a_longer_source(self) -> None:
        root = self.workspace / "trimmed"
        project = create_project(
            root,
            "trim test",
            fps=25.0,
            width=320,
            height=180,
            project_id="proj-trim",
        )
        source = make_solid_clip(
            self.workspace / "fixtures" / "long.mp4",
            color="red",
            seconds=4.0,
            width=640,
            height=360,
        )
        add_asset(project, root, source)
        add_clip(project, "A001", 1.0, 3.0)
        save_project(project, root)

        report = render_project(project, root)

        self.assertTrue(report.ok)
        self.assertAlmostEqual(report.expected_duration, 2.0, places=3)
        self.assertAlmostEqual(report.actual_duration, 2.0, delta=0.2)
        self.assertEqual((report.width, report.height), (320, 180))


if __name__ == "__main__":
    unittest.main()

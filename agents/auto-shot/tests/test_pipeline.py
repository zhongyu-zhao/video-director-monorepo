from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from auto_shot.cli import main
from auto_shot.pipeline import analyze
from auto_shot.probe import ProbeError

from tests.support import ffmpeg_available, make_color_video


@unittest.skipUnless(ffmpeg_available(), "ffmpeg/ffprobe not installed")
class PipelineIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.video = make_color_video(self.root / "colors.mp4")

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_analyze_writes_artifacts_and_passes_gates(self) -> None:
        result = analyze(self.video, self.root / "out")

        self.assertEqual([shot.start for shot in result.table.shots], [0.0, 2.0, 4.0])
        self.assertEqual([shot.end for shot in result.table.shots], [2.0, 4.0, 6.0])
        self.assertTrue(result.quality.ok)

        self.assertTrue(result.shots_path.is_file())
        self.assertTrue(result.quality_path.is_file())
        self.assertTrue(result.report_path.is_file())

        payload = json.loads(result.shots_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(len(payload["shots"]), 3)
        self.assertEqual(payload["detector"], {"name": "ffmpeg-scene", "threshold": 0.25})

        quality = json.loads(result.quality_path.read_text(encoding="utf-8"))
        self.assertTrue(quality["ok"])

        detection = json.loads(result.detection_path.read_text(encoding="utf-8"))
        self.assertEqual(detection["selected"], "ffmpeg-scene")
        self.assertEqual(detection["route"], "auto")
        self.assertIsNotNone(detection["profile"])
        self.assertFalse(detection["profile"]["high_motion"])

        report = result.report_path.read_text(encoding="utf-8")
        self.assertIn("- 路由：auto", report)
        self.assertIn("| S003 | 00:00:04.000 | 00:00:06.000 |", report)

    def test_missing_input_raises_probe_error(self) -> None:
        with self.assertRaises(ProbeError):
            analyze(self.root / "missing.mp4", self.root / "out")

    def test_invalid_threshold_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            analyze(self.video, self.root / "out", threshold=0.0)

    def test_cli_returns_zero_on_success(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["analyze", str(self.video), "--out", str(self.root / "cli-out")])

        self.assertEqual(code, 0, stderr.getvalue())
        self.assertIn("quality=pass", stdout.getvalue())

    def test_cli_returns_two_for_missing_input(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["analyze", str(self.root / "missing.mp4"), "--out", str(self.root / "out")])

        self.assertEqual(code, 2)
        self.assertIn("error:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

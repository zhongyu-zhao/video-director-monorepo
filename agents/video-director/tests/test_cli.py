from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from video_director.cli import main

from tests.support import ffmpeg_available, make_solid_clip


@unittest.skipUnless(ffmpeg_available(), "ffmpeg/ffprobe not installed")
class CliIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self._temporary.name)
        self.root = self.workspace / "project"
        self.fixtures = self.workspace / "fixtures"
        self.fixtures.mkdir()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def run_cli(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(arguments))
        return code, stdout.getvalue(), stderr.getvalue()

    def init_project(self) -> None:
        code, _, stderr = self.run_cli(
            "init",
            "--root",
            str(self.root),
            "--title",
            "cli test",
            "--fps",
            "25",
            "--size",
            "320x180",
        )
        self.assertEqual(code, 0, stderr)

    def test_init_asset_clip_validate_render(self) -> None:
        self.init_project()
        first = make_solid_clip(self.fixtures / "black.mp4", color="black")
        second = make_solid_clip(self.fixtures / "white.mp4", color="white")

        self.assertEqual(self.run_cli("asset", "add", str(first), "--root", str(self.root))[0], 0)
        self.assertEqual(self.run_cli("asset", "add", str(second), "--root", str(self.root))[0], 0)
        self.assertEqual(
            self.run_cli(
                "clip",
                "add",
                "--root",
                str(self.root),
                "--asset",
                "A001",
                "--in",
                "0",
                "--out",
                "2",
            )[0],
            0,
        )
        self.assertEqual(
            self.run_cli(
                "clip",
                "add",
                "--root",
                str(self.root),
                "--asset",
                "A002",
                "--in",
                "0",
                "--out",
                "2",
            )[0],
            0,
        )

        code, stdout, _ = self.run_cli("validate", "--root", str(self.root))
        self.assertEqual(code, 0)
        self.assertIn("validation: pass", stdout)

        code, stdout, stderr = self.run_cli("render", "--root", str(self.root))
        self.assertEqual(code, 0, stderr)
        self.assertIn("render:", stdout)
        self.assertTrue((self.root / "renders" / "render_report.json").is_file())

    def test_missing_project_returns_two(self) -> None:
        code, _, stderr = self.run_cli("validate", "--root", str(self.root))

        self.assertEqual(code, 2)
        self.assertIn("error:", stderr)


if __name__ == "__main__":
    unittest.main()

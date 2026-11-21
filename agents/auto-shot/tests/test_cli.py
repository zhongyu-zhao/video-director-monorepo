from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from auto_shot.cli import main
from auto_shot.models import ShotTable, shots_from_cuts

from tests.support import sample_table


def table() -> ShotTable:
    value = sample_table()
    value.shots = shots_from_cuts([2.0, 4.0], 6.0)
    return value


class ReviewCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.shots = self.root / "shots.json"
        table().save(self.shots)
        self.video = self.root / "input.mp4"
        self.video.write_bytes(b"not a real video")

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def run_cli(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(arguments))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_review_and_apply(self) -> None:
        page = self.root / "review.html"
        code, stdout, stderr = self.run_cli(
            "review",
            "--shots",
            str(self.shots),
            "--video",
            str(self.video),
            "--out",
            str(page),
        )
        self.assertEqual(code, 0, stderr)
        self.assertTrue(page.is_file())
        self.assertIn("review page", stdout)

        flags = self.root / "review-flags.json"
        flags.write_text(json.dumps({"falseCuts": ["S002"], "missedCuts": []}), encoding="utf-8")
        corrected = self.root / "shots-reviewed.json"
        code, stdout, stderr = self.run_cli(
            "apply-review",
            "--shots",
            str(self.shots),
            "--flags",
            str(flags),
            "--out",
            str(corrected),
        )
        self.assertEqual(code, 0, stderr)
        self.assertTrue(corrected.is_file())
        self.assertIn("manual_cuts=0", stdout)

    def test_label_dry_run_does_not_need_a_key(self) -> None:
        code, stdout, stderr = self.run_cli(
            "label",
            "--shots",
            str(self.shots),
            "--video",
            str(self.video),
            "--dry-run",
        )

        self.assertEqual(code, 0, stderr)
        self.assertIn("would label 3", stdout)
        self.assertFalse((self.root / "labels.json").exists())


if __name__ == "__main__":
    unittest.main()

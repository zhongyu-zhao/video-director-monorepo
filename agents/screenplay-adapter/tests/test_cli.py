from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from screenplay_adapter.cli import main

from tests.support import NOVEL, run_cli, scene_payload, start_fake_server, stop_server


class CliEndToEndTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self._temporary.name)
        self.source = self.workspace / "novel.md"
        self.source.write_text(NOVEL, encoding="utf-8")
        self.root = self.workspace / "project"
        self.env = self.workspace / ".env"
        self.env.write_text("OPENAI_API_KEY=fake\n", encoding="utf-8")
        self.server = None

    def tearDown(self) -> None:
        if self.server is not None:
            stop_server(self.server)
        self._temporary.cleanup()

    def adapt(self):
        return run_cli(
            main,
            "adapt",
            str(self.source),
            "--root",
            str(self.root),
            "--title",
            "雨夜",
            "--format",
            "short-drama",
            "--episodes",
            "3",
            "--episode-minutes",
            "2",
            "--scene-seconds",
            "45",
        )

    def start_fake(self, character: str = "林昭"):
        def builder(request):
            scene_id = request["messages"][1]["content"].split("场号：", 1)[1].split()[0].strip()
            payload = scene_payload(scene_id, character=character)
            return 200, {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}

        self.server, port = start_fake_server(builder)
        return port

    def draft_all(self, port: int) -> None:
        code, _, stderr = run_cli(
            main,
            "draft",
            "--root",
            str(self.root),
            "--env-file",
            str(self.env),
            "--base-url",
            f"http://127.0.0.1:{port}/v1",
            "--model",
            "fake",
        )
        self.assertEqual(code, 0, stderr)

    def test_full_pipeline(self) -> None:
        code, stdout, stderr = self.adapt()
        self.assertEqual(code, 0, stderr)
        self.assertIn("plan:", stdout)
        self.assertTrue((self.root / "adaptation.json").is_file())
        self.assertTrue((self.root / "briefs.md").is_file())

        port = self.start_fake()
        code, stdout, stderr = run_cli(
            main,
            "draft",
            "--root",
            str(self.root),
            "--env-file",
            str(self.env),
            "--base-url",
            f"http://127.0.0.1:{port}/v1",
            "--model",
            "fake",
        )
        self.assertEqual(code, 0, stderr)
        self.assertIn("all scenes have drafts", stdout)

        code, stdout, stderr = run_cli(main, "assemble", "--root", str(self.root))
        self.assertEqual(code, 0, stderr)
        self.assertIn("validation:", stdout)
        self.assertTrue((self.root / "screenplay.json").is_file())
        self.assertTrue((self.root / "screenplay.fountain").is_file())
        self.assertTrue((self.root / "screenplay.md").is_file())
        report = json.loads((self.root / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["stage"], "screenplay")
        self.assertNotEqual(report["status"], "fail")
        self.assertTrue(any(gate["id"].startswith("P") for gate in report["gates"]))

        code, stdout, _ = run_cli(main, "validate", "--root", str(self.root))
        self.assertEqual(code, 0)
        self.assertIn("screenplay", stdout)

    def test_adapt_without_title_uses_markdown_heading(self) -> None:
        code, _, stderr = run_cli(
            main,
            "adapt",
            str(self.source),
            "--root",
            str(self.root),
            "--episodes",
            "3",
            "--episode-minutes",
            "2",
            "--scene-seconds",
            "45",
        )
        self.assertEqual(code, 0, stderr)
        plan = json.loads((self.root / "adaptation.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["title"], "雨夜")

    def test_adapt_without_title_or_heading_uses_file_stem(self) -> None:
        plain = self.workspace / "plain-story.md"
        plain.write_text("他出发了。\n\n她停下了。\n", encoding="utf-8")
        code, _, stderr = run_cli(
            main,
            "adapt",
            str(plain),
            "--root",
            str(self.root),
            "--episodes",
            "1",
            "--episode-minutes",
            "2",
            "--scene-seconds",
            "45",
        )
        self.assertEqual(code, 0, stderr)
        plan = json.loads((self.root / "adaptation.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["title"], "plain-story")

    def test_draft_refuses_a_failing_plan_before_calling_provider(self) -> None:
        code, _, _ = run_cli(
            main,
            "adapt",
            str(self.source),
            "--root",
            str(self.root),
            "--title",
            "雨夜",
            "--episodes",
            "30",
            "--episode-minutes",
            "2",
            "--scene-seconds",
            "45",
        )
        self.assertEqual(code, 1)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "", "SCREENPLAY_ADAPTER_API_KEY": ""}):
            code, _, stderr = run_cli(main, "draft", "--root", str(self.root))

        self.assertEqual(code, 1)
        self.assertIn("plan has failing gates", stderr)

    def test_stale_draft_requires_force(self) -> None:
        self.assertEqual(self.adapt()[0], 0)
        port = self.start_fake()
        code, _, stderr = run_cli(
            main,
            "draft",
            "--root",
            str(self.root),
            "--env-file",
            str(self.env),
            "--base-url",
            f"http://127.0.0.1:{port}/v1",
            "--model",
            "fake",
            "--scene",
            "S001",
        )
        self.assertEqual(code, 0, stderr)

        # Changing the brief changes plan_hash and invalidates the old draft.
        code, _, stderr = run_cli(
            main,
            "adapt",
            str(self.source),
            "--root",
            str(self.root),
            "--title",
            "雨夜",
            "--episodes",
            "3",
            "--episode-minutes",
            "2",
            "--scene-seconds",
            "30",
            "--force",
        )
        self.assertEqual(code, 0, stderr)

        code, _, stderr = run_cli(
            main,
            "draft",
            "--root",
            str(self.root),
            "--env-file",
            str(self.env),
            "--base-url",
            f"http://127.0.0.1:{port}/v1",
            "--model",
            "fake",
        )
        self.assertEqual(code, 2)
        self.assertIn("different plan or source", stderr)

    def test_assemble_failure_writes_no_screenplay_artifacts(self) -> None:
        self.assertEqual(self.adapt()[0], 0)
        (self.root / "screenplay.json").write_text("stale", encoding="utf-8")
        port = self.start_fake(character="陌生人")
        self.draft_all(port)

        code, _, stderr = run_cli(main, "assemble", "--root", str(self.root))

        self.assertEqual(code, 1)
        self.assertIn("no screenplay artifacts", stderr)
        for name in ("screenplay.json", "screenplay.fountain", "screenplay.md"):
            self.assertFalse((self.root / name).exists(), name)
        report = json.loads((self.root / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "fail")
        self.assertIn("S006", [gate["id"] for gate in report["gates"] if gate["status"] == "fail"])

    def test_adapt_force_removes_stale_derived_artifacts(self) -> None:
        self.assertEqual(self.adapt()[0], 0)
        for name in ("screenplay.json", "screenplay.fountain", "screenplay.md"):
            (self.root / name).write_text("stale", encoding="utf-8")

        code, stdout, stderr = self.adapt_with_force()

        self.assertEqual(code, 0, stderr)
        self.assertIn("invalidated:", stdout)
        for name in ("screenplay.json", "screenplay.fountain", "screenplay.md"):
            self.assertFalse((self.root / name).exists(), name)
        report = json.loads((self.root / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["stage"], "plan")

    def test_adapt_twice_needs_force(self) -> None:
        self.assertEqual(self.adapt()[0], 0)

        code, _, stderr = self.adapt()

        self.assertEqual(code, 2)
        self.assertIn("already exists", stderr)

    def adapt_with_force(self):
        return run_cli(
            main,
            "adapt",
            str(self.source),
            "--root",
            str(self.root),
            "--title",
            "雨夜",
            "--format",
            "short-drama",
            "--episodes",
            "3",
            "--episode-minutes",
            "2",
            "--scene-seconds",
            "45",
            "--force",
        )

    def test_draft_without_api_key_returns_two(self) -> None:
        self.assertEqual(self.adapt()[0], 0)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "", "SCREENPLAY_ADAPTER_API_KEY": ""}):
            code, _, stderr = run_cli(
                main,
                "draft",
                "--root",
                str(self.root),
                "--base-url",
                "http://127.0.0.1:1/v1",
                "--model",
                "fake",
            )

        self.assertEqual(code, 2)
        self.assertIn("API key is required", stderr)

    def test_assemble_without_drafts_returns_two(self) -> None:
        self.assertEqual(self.adapt()[0], 0)

        code, _, stderr = run_cli(main, "assemble", "--root", str(self.root))

        self.assertEqual(code, 2)
        self.assertIn("missing drafts", stderr)

    def test_unknown_scene_returns_two(self) -> None:
        self.assertEqual(self.adapt()[0], 0)
        port = self.start_fake()

        code, _, stderr = run_cli(
            main,
            "draft",
            "--root",
            str(self.root),
            "--env-file",
            str(self.env),
            "--base-url",
            f"http://127.0.0.1:{port}/v1",
            "--model",
            "fake",
            "--scene",
            "S999",
        )

        self.assertEqual(code, 2)
        self.assertIn("unknown scene ids", stderr)

    def test_limit_leaves_missing_drafts(self) -> None:
        self.assertEqual(self.adapt()[0], 0)
        port = self.start_fake()
        code, _, stderr = run_cli(
            main,
            "draft",
            "--root",
            str(self.root),
            "--env-file",
            str(self.env),
            "--base-url",
            f"http://127.0.0.1:{port}/v1",
            "--model",
            "fake",
            "--limit",
            "1",
        )
        self.assertEqual(code, 0, stderr)

        code, _, stderr = run_cli(main, "assemble", "--root", str(self.root))

        self.assertEqual(code, 2)
        self.assertIn("missing drafts", stderr)

    def test_validate_missing_project_returns_two(self) -> None:
        code, _, stderr = run_cli(main, "validate", "--root", str(self.root))

        self.assertEqual(code, 2)
        self.assertIn("missing adaptation plan", stderr)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from screenplay_adapter.models import AdapterError
from screenplay_adapter.project import (
    load_drafts,
    load_plan,
    load_screenplay,
    load_source,
    read_env_file,
    save_draft,
    save_plan,
    write_source,
)
from screenplay_adapter.source import parse_source

from tests.support import NOVEL, make_drafts, make_plan


class ProjectIoTest(unittest.TestCase):
    def test_source_copy_roundtrip_keeps_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_source(root, NOVEL)

            document = load_source(root)

        self.assertEqual(document.sha256, parse_source(NOVEL, title="雨夜").sha256)
        self.assertEqual(document.path, "source/source.md")

    def test_plan_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, plan = make_plan(root)

            loaded = load_plan(root)

        self.assertEqual(loaded.plan_hash, plan.plan_hash)
        self.assertEqual([scene.id for scene in loaded.scenes], [scene.id for scene in plan.scenes])

    def test_drafts_roundtrip_and_duplicate_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, plan = make_plan(root)
            drafts = make_drafts(plan)
            for draft in drafts.values():
                save_draft(root, draft)

            loaded = load_drafts(root)
            self.assertEqual(sorted(loaded), sorted(drafts))

            duplicate = root / "drafts" / "S001-extra.json"
            duplicate.write_text(json.dumps(drafts["S001"].to_dict(), ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(AdapterError):
                load_drafts(root)

    def test_malformed_plan_raises_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "adaptation.json").write_text("{}", encoding="utf-8")

            with self.assertRaises(AdapterError) as context:
                load_plan(root)

        self.assertIn("invalid adaptation plan", str(context.exception))

    def test_missing_plan_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(AdapterError):
                load_plan(Path(temporary))

    def test_missing_screenplay_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.assertIsNone(load_screenplay(Path(temporary)))

    def test_env_file_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env"
            path.write_text("# comment\nexport OPENAI_API_KEY='secret'\nMODEL=\"fake\"\n", encoding="utf-8")

            values = read_env_file(path)

        self.assertEqual(values["OPENAI_API_KEY"], "secret")
        self.assertEqual(values["MODEL"], "fake")

    def test_env_file_rejects_bad_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env"
            path.write_text("NOT_AN_ASSIGNMENT\n", encoding="utf-8")

            with self.assertRaises(AdapterError):
                read_env_file(path)


if __name__ == "__main__":
    unittest.main()

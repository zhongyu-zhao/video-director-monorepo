from __future__ import annotations

import unittest

from screenplay_adapter.draft import merge_screenplay
from screenplay_adapter.fountain import render_fountain, render_markdown

from tests.support import make_drafts, make_plan


class ExportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.document, self.plan = make_plan()
        self.screenplay = merge_screenplay(self.plan, make_drafts(self.plan))

    def test_fountain_has_title_scene_and_source_note(self) -> None:
        fountain = render_fountain(self.screenplay, self.plan)

        self.assertIn("Title: 雨夜", fountain)
        self.assertIn("# 第 1 集", fountain)
        self.assertIn("INT. 咖啡馆 - NIGHT", fountain)
        self.assertIn("林昭", fountain)
        self.assertIn("[[source: S001", fountain)
        self.assertIn("(低声)", fountain)

    def test_fountain_int_ext_has_one_period(self) -> None:
        self.screenplay.scenes[0]["heading"]["int_ext"] = "INT/EXT"

        fountain = render_fountain(self.screenplay, self.plan)

        self.assertIn("INT./EXT. 咖啡馆 - NIGHT", fountain)
        self.assertNotIn("INT./EXT..", fountain)

    def test_fountain_escapes_action_that_looks_like_a_heading(self) -> None:
        self.screenplay.scenes[0]["action"] = ["INT. 这是一个动作描述，不是场景头。"]

        fountain = render_fountain(self.screenplay, self.plan)

        self.assertIn("!INT. 这是一个动作描述", fountain)

    def test_markdown_has_scene_anchor_and_basis_counts(self) -> None:
        markdown = render_markdown(self.screenplay, self.plan, self.document)

        self.assertIn("### S001", markdown)
        self.assertIn("来源：CH001", markdown)
        self.assertIn("对白新增/改写/来源", markdown)
        self.assertIn("**林昭**", markdown)

    def test_exports_are_deterministic(self) -> None:
        first = render_fountain(self.screenplay, self.plan)
        second = render_fountain(self.screenplay, self.plan)

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()

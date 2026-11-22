from __future__ import annotations

import copy
import unittest
from dataclasses import replace

from screenplay_adapter.draft import merge_screenplay, screenplay_stats
from screenplay_adapter.models import SourceDocument, SourceSpan
from screenplay_adapter.validate import FAIL, PASS, WARN, validate_plan, validate_screenplay

from tests.support import make_drafts, make_plan, make_document


class PlanValidationTest(unittest.TestCase):
    def test_valid_plan_passes(self) -> None:
        document, plan = make_plan()

        report = validate_plan(plan, document)

        self.assertEqual(report.status, PASS, [gate.message for gate in report.gates if gate.status == FAIL])
        self.assertEqual(report.stats["scene_count"], 8)

    def test_coverage_gap_fails(self) -> None:
        document, plan = make_plan()
        broken = copy.deepcopy(plan)
        broken.scenes[0] = replace(
            broken.scenes[0],
            source=replace(broken.scenes[0].source, sentence_start=5, char_start=0),
        )

        report = validate_plan(broken, document)

        self.assertEqual(report.status, FAIL)
        self.assertEqual(report.failures[0].id, "P003")

    def test_missing_episode_fails(self) -> None:
        document = make_document()
        from screenplay_adapter.plan import build_plan, make_brief

        plan = build_plan(
            document,
            make_brief("雨夜", "short-drama", episodes=30, episode_minutes=2, scene_seconds=45),
            [],
        )

        report = validate_plan(plan, document)

        self.assertEqual(report.status, FAIL)
        self.assertIn("P005", [gate.id for gate in report.failures])

    def test_stale_plan_hash_fails(self) -> None:
        document, plan = make_plan()
        broken = copy.deepcopy(plan)
        broken.plan_hash = "stale"

        report = validate_plan(broken, document)

        self.assertEqual(report.status, FAIL)
        self.assertIn("P011", [gate.id for gate in report.failures])

    def test_unknown_scene_cast_fails(self) -> None:
        document, plan = make_plan()
        broken = copy.deepcopy(plan)
        broken.scenes[0] = replace(broken.scenes[0], cast=("不存在的人",))

        report = validate_plan(broken, document)

        self.assertEqual(report.status, FAIL)
        self.assertIn("P007", [gate.id for gate in report.failures])

    def test_plan_warnings_become_warn(self) -> None:
        document = make_document()
        from screenplay_adapter.plan import build_plan, make_brief

        plan = build_plan(
            document,
            make_brief("雨夜", "feature", episodes=1, episode_minutes=100, scene_seconds=150),
            [],
        )

        report = validate_plan(plan, document)

        self.assertIn(report.status, (PASS, WARN))
        self.assertTrue(any(gate.id == "P010" for gate in report.gates))


class ScreenplayValidationTest(unittest.TestCase):
    def test_valid_screenplay_has_no_failures(self) -> None:
        document, plan = make_plan()
        screenplay = merge_screenplay(plan, make_drafts(plan))

        report = validate_screenplay(plan, screenplay, document)

        self.assertNotEqual(report.status, FAIL, [gate.message for gate in report.failures])
        self.assertEqual(report.stats["scene_count"], 8)

    def test_unknown_speaker_fails(self) -> None:
        document, plan = make_plan()
        drafts = make_drafts(plan)
        first = drafts["S001"]
        drafts["S001"] = replace(
            first,
            dialogue=(replace(first.dialogue[0], character="陌生人"),),
        )
        screenplay = merge_screenplay(plan, drafts)

        report = validate_screenplay(plan, screenplay, document)

        self.assertEqual(report.status, FAIL)
        self.assertIn("S006", [gate.id for gate in report.failures])

    def test_empty_scene_body_fails(self) -> None:
        document, plan = make_plan()
        drafts = make_drafts(plan)
        first = drafts["S001"]
        drafts["S001"] = replace(first, action=(), dialogue=())
        screenplay = merge_screenplay(plan, drafts)

        report = validate_screenplay(plan, screenplay, document)

        self.assertEqual(report.status, FAIL)
        self.assertIn("S005", [gate.id for gate in report.failures])

    def test_stale_draft_is_rejected_at_merge(self) -> None:
        _, plan = make_plan()
        drafts = make_drafts(plan)
        drafts["S001"] = replace(drafts["S001"], plan_hash="stale")

        with self.assertRaises(Exception) as context:
            merge_screenplay(plan, drafts)
        self.assertIn("different plan", str(context.exception))

    def test_missing_draft_is_rejected_at_merge(self) -> None:
        _, plan = make_plan()
        drafts = make_drafts(plan)
        del drafts["S002"]

        with self.assertRaises(Exception) as context:
            merge_screenplay(plan, drafts)
        self.assertIn("missing drafts", str(context.exception))

    def test_runtime_mismatch_warns(self) -> None:
        document, plan = make_plan()
        screenplay = merge_screenplay(plan, make_drafts(plan))

        report = validate_screenplay(plan, screenplay, document)

        self.assertIn("S008", [gate.id for gate in report.warnings])

    def test_invention_ratio_warns(self) -> None:
        document, plan = make_plan()
        screenplay = merge_screenplay(plan, make_drafts(plan, basis="invented"))

        report = validate_screenplay(plan, screenplay, document)

        self.assertIn("S010", [gate.id for gate in report.warnings])

    def test_plan_hash_mismatch_fails(self) -> None:
        document, plan = make_plan()
        screenplay = merge_screenplay(plan, make_drafts(plan))
        screenplay.plan_hash = "wrong"

        report = validate_screenplay(plan, screenplay, document)

        self.assertEqual(report.status, FAIL)
        self.assertIn("S002", [gate.id for gate in report.failures])

    def test_invalid_heading_fails(self) -> None:
        document, plan = make_plan()
        screenplay = merge_screenplay(plan, make_drafts(plan))
        screenplay.scenes[0]["heading"] = {"int_ext": "SOMEWHERE", "location": "", "time": "NIGHT"}

        report = validate_screenplay(plan, screenplay, document)

        self.assertEqual(report.status, FAIL)
        self.assertIn("S004", [gate.id for gate in report.failures])

    def test_malformed_scene_reports_failure_instead_of_crashing(self) -> None:
        document, plan = make_plan()
        screenplay = merge_screenplay(plan, make_drafts(plan))
        screenplay.scenes[0]["dialogue"] = ["not an object"]

        report = validate_screenplay(plan, screenplay, document)

        self.assertEqual(report.status, FAIL)
        self.assertEqual(report.failures[0].id, "S000")

    def test_screenplay_stats_counts_basis(self) -> None:
        _, plan = make_plan()
        screenplay = merge_screenplay(plan, make_drafts(plan, basis="source"))
        stats = screenplay_stats(screenplay)

        self.assertEqual(stats["dialogue_basis"]["source"], 8)
        self.assertEqual(stats["dialogue_basis"]["invented"], 0)


if __name__ == "__main__":
    unittest.main()

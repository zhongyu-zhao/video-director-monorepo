from __future__ import annotations

import unittest

from screenplay_adapter.beats import beat_for, beat_index, beats_for
from screenplay_adapter.models import AdapterError
from screenplay_adapter.plan import (
    build_plan,
    make_brief,
    partition_document,
    partition_sentences,
    render_briefs,
)
from screenplay_adapter.source import parse_source

from tests.support import make_document


class BeatTemplateTest(unittest.TestCase):
    def test_feature_has_contiguous_fifteen_beats(self) -> None:
        beats = beats_for("feature")

        self.assertEqual(len(beats), 15)
        self.assertEqual(beats[0].id, "opening_image")
        self.assertEqual(beats[-1].id, "final_image")
        self.assertEqual(beats[0].start, 0.0)
        self.assertEqual(beats[-1].end, 1.0)
        for left, right in zip(beats, beats[1:]):
            self.assertEqual(left.end, right.start)

    def test_episodic_beats_have_hook_and_cliffhanger(self) -> None:
        for format in ("series", "short-drama"):
            beats = beats_for(format)
            self.assertEqual(beats[0].id, "hook" if format == "short-drama" else "cold_open")
            self.assertEqual(beats[-1].id, "cliffhanger")
            self.assertEqual(beat_for(0.0, beats).id, beats[0].id)
            self.assertEqual(beat_for(1.0, beats).id, beats[-1].id)

    def test_unknown_format_raises(self) -> None:
        with self.assertRaises(ValueError):
            beats_for("podcast")

    def test_beat_index(self) -> None:
        self.assertEqual(beat_index("midpoint", "feature"), 8)
        self.assertEqual(beat_index("missing", "feature"), -1)


class PlanTest(unittest.TestCase):
    def test_scene_plan_covers_source_and_durations(self) -> None:
        document, plan = make_plan_for_test()

        self.assertEqual(len(plan.scenes), 8)
        self.assertAlmostEqual(plan.total_seconds, 360.0, places=3)
        expected = 0
        for scene in plan.scenes:
            self.assertEqual(scene.source.sentence_start, expected)
            expected = scene.source.sentence_end + 1
            self.assertGreater(scene.duration_s, 0)
        self.assertEqual(expected, len(document.sentences))

    def test_scenes_do_not_cross_chapters_for_this_fixture(self) -> None:
        _, plan = make_plan_for_test()

        for scene in plan.scenes:
            self.assertEqual(len(scene.source.chapter_ids), 1, scene.id)

    def test_all_episodes_have_scenes(self) -> None:
        _, plan = make_plan_for_test()

        self.assertEqual({scene.episode for scene in plan.scenes}, {1, 2, 3})

    def test_each_chapter_starts_a_scene(self) -> None:
        _, plan = make_plan_for_test()

        first_chapter = plan.scenes[0].source.chapter_ids[0]
        self.assertEqual(first_chapter, "CH001")
        chapter_starts = [scene.source.chapter_ids[0] for scene in plan.scenes if scene.index_in_episode == 1]
        self.assertIn("CH002", chapter_starts)
        self.assertIn("CH003", chapter_starts)

    def test_plan_hash_is_deterministic_and_brief_sensitive(self) -> None:
        _, first = make_plan_for_test()
        _, second = make_plan_for_test()
        document = make_document()
        other_brief = make_brief("雨夜", "short-drama", episodes=4, episode_minutes=2, scene_seconds=45)
        other = build_plan(document, other_brief, first.cast)

        self.assertEqual(first.plan_hash, second.plan_hash)
        self.assertNotEqual(first.plan_hash, other.plan_hash)

    def test_expand_mode_marks_scenes_for_expansion(self) -> None:
        document = make_document()
        brief = make_brief(
            "雨夜",
            "short-drama",
            episodes=3,
            episode_minutes=2,
            scene_seconds=45,
            mode="expand",
        )
        plan = build_plan(document, brief, [])

        self.assertTrue(all("expand" in scene.expansion for scene in plan.scenes))

    def test_sparse_source_is_capped_with_warning(self) -> None:
        document = parse_source("只有一句话。\n", title="短")
        brief = make_brief("短", "feature", episodes=1, episode_minutes=100, scene_seconds=150)
        plan = build_plan(document, brief, [])

        self.assertEqual(len(plan.scenes), 1)
        self.assertEqual(plan.requested_scenes, 40)
        self.assertTrue(any("too sparse" in warning for warning in plan.warnings))

    def test_fewer_scenes_than_episodes_is_reported(self) -> None:
        document = parse_source("第一句。第二句。\n", title="短")
        brief = make_brief("短", "short-drama", episodes=5, episode_minutes=2, scene_seconds=45)
        plan = build_plan(document, brief, [])

        self.assertLess(len(plan.scenes), 5)
        self.assertTrue(any("episodes" in warning for warning in plan.warnings))

    def test_partition_document_groups_chapters_when_needed(self) -> None:
        text = "第一章 一\n\n甲。\n\n第二章 二\n\n乙。\n\n第三章 三\n\n丙。\n\n第四章 四\n\n丁。\n"
        document = parse_source(text, title="四章")
        groups, requested = partition_document(document, 2)

        self.assertEqual(requested, 2)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0][0], 0)
        self.assertEqual(groups[-1][1], len(document.sentences))

    def test_partition_sentences_range(self) -> None:
        document = make_document()
        groups = partition_sentences(document.sentences, 2, 3, 9)

        self.assertEqual(groups[0][0], 3)
        self.assertEqual(groups[-1][1], 9)
        self.assertEqual(groups[0][1], groups[1][0])

    def test_briefs_include_source_and_constraints(self) -> None:
        document, plan = make_plan_for_test()
        markdown = render_briefs(plan, document)

        self.assertIn("### S001", markdown)
        self.assertIn("不得新增人物表", markdown)
        self.assertIn("林昭", markdown)

    def test_invalid_briefs_are_rejected(self) -> None:
        with self.assertRaises(AdapterError):
            make_brief("x", "feature", episodes=2)
        with self.assertRaises(AdapterError):
            make_brief("x", "short-drama", episodes=0)
        with self.assertRaises(AdapterError):
            make_brief("x", "short-drama", scene_seconds=0)
        with self.assertRaises(AdapterError):
            make_brief("x", "podcast")


def make_plan_for_test():
    from tests.support import make_plan

    return make_plan()


if __name__ == "__main__":
    unittest.main()

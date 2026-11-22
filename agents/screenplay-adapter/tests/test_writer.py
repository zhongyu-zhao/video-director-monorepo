from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from screenplay_adapter.writer import (
    OpenAICompatibleWriter,
    WriterConfig,
    WriterError,
    build_prompt,
    extract_json_object,
)

from tests.support import (
    make_document,
    make_plan,
    prompt_scene_id,
    scene_payload,
    start_fake_server,
    stop_server,
)


def success_builder(character: str = "林昭"):
    def builder(request: dict) -> tuple[int, dict]:
        scene_id = prompt_scene_id(request)
        content = "```json\n" + json.dumps(scene_payload(scene_id, character=character), ensure_ascii=False) + "\n```"
        return 200, {"choices": [{"message": {"content": content}}]}

    return builder


class PromptTest(unittest.TestCase):
    def test_prompt_contains_source_cast_and_constraints(self) -> None:
        document, plan = make_plan()
        scene = plan.scenes[0]

        messages, prompt_hash = build_prompt(plan, scene, document)

        self.assertEqual(len(prompt_hash), 64)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("只输出一个 JSON 对象", messages[0]["content"])
        user = messages[1]["content"]
        self.assertIn(scene.id, user)
        self.assertIn("林昭", user)
        self.assertIn("目标时长", user)
        self.assertIn("不得新增有名角色", user)
        self.assertIn("原文片段", user)

    def test_extract_json_strips_code_fence(self) -> None:
        payload = extract_json_object('```json\n{"scene_id": "S001"}\n```')

        self.assertEqual(payload["scene_id"], "S001")


class WriterHttpTest(unittest.TestCase):
    def start(self, builder):
        server, port = start_fake_server(builder)
        self.addCleanup(stop_server, server)
        writer = OpenAICompatibleWriter(
            WriterConfig(
                base_url=f"http://127.0.0.1:{port}/v1",
                api_key="test-key",
                model="fake-model",
                timeout=5,
                max_retries=1,
            )
        )
        return writer

    def test_successful_scene_write(self) -> None:
        document, plan = make_plan()
        writer = self.start(success_builder())

        draft = writer.write_scene(plan, plan.scenes[0], document)

        self.assertEqual(draft.scene_id, "S001")
        self.assertEqual(draft.heading.location, "咖啡馆")
        self.assertEqual(draft.provider, "openai-compatible")
        self.assertEqual(draft.model, "fake-model")
        self.assertEqual(draft.plan_hash, plan.plan_hash)
        self.assertEqual(draft.dialogue[0].basis, "adapted")
        self.assertEqual(len(draft.prompt_sha256), 64)

    def test_authentication_error_is_actionable(self) -> None:
        document, plan = make_plan()
        writer = self.start(lambda request: (401, {"error": {"message": "invalid key"}}))

        with self.assertRaises(WriterError) as context:
            writer.write_scene(plan, plan.scenes[0], document)

        self.assertIn("authentication failed", str(context.exception))

    def test_non_json_content_fails(self) -> None:
        document, plan = make_plan()
        writer = self.start(lambda request: (200, {"choices": [{"message": {"content": "not json"}}]}))

        with self.assertRaises(WriterError) as context:
            writer.write_scene(plan, plan.scenes[0], document)

        self.assertIn("no JSON object", str(context.exception))

    def test_invalid_heading_fails(self) -> None:
        def builder(request: dict) -> tuple[int, dict]:
            payload = scene_payload(prompt_scene_id(request))
            payload["heading"] = {"int_ext": "INTERIOR", "location": "", "time": "NIGHT"}
            return 200, {"choices": [{"message": {"content": json.dumps(payload)}}]}

        document, plan = make_plan()
        writer = self.start(builder)

        with self.assertRaises(WriterError) as context:
            writer.write_scene(plan, plan.scenes[0], document)

        self.assertIn("int_ext", str(context.exception))

    def test_retries_server_error(self) -> None:
        document, plan = make_plan()
        attempts = {"count": 0}

        def builder(request: dict) -> tuple[int, dict]:
            attempts["count"] += 1
            if attempts["count"] == 1:
                return 503, {"error": {"message": "busy"}}
            scene_id = prompt_scene_id(request)
            payload = scene_payload(scene_id)
            return 200, {"choices": [{"message": {"content": json.dumps(payload)}}]}

        writer = self.start(builder)
        with patch("screenplay_adapter.writer.time.sleep"):
            draft = writer.write_scene(plan, plan.scenes[0], document)

        self.assertEqual(draft.scene_id, "S001")
        self.assertEqual(attempts["count"], 2)

    def test_missing_api_key_is_rejected_before_request(self) -> None:
        with self.assertRaises(WriterError):
            OpenAICompatibleWriter(WriterConfig(base_url="https://example.com/v1", api_key="", model="x"))

    def test_base_url_without_v1_gets_chat_completions(self) -> None:
        writer = OpenAICompatibleWriter(
            WriterConfig(base_url="https://example.com/v1/", api_key="key", model="x")
        )

        self.assertEqual(writer.endpoint, "https://example.com/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()

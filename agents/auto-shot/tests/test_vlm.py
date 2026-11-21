from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from auto_shot.vlm import VlmError, load_env_file, parse_json_object, resolve_config


class ParseJsonTest(unittest.TestCase):
    def test_parses_plain_object(self) -> None:
        self.assertEqual(parse_json_object('{"a": 1}'), {"a": 1})

    def test_parses_fenced_object(self) -> None:
        self.assertEqual(parse_json_object('```json\n{"a": 1}\n```'), {"a": 1})

    def test_extracts_object_from_surrounding_text(self) -> None:
        self.assertEqual(parse_json_object('answer: {"a": 1} done'), {"a": 1})

    def test_rejects_non_json(self) -> None:
        with self.assertRaises(VlmError):
            parse_json_object("not json")


class EnvFileTest(unittest.TestCase):
    def test_reads_values_without_exposing_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text('DEEPSEEK_API_KEY="secret"\nDEEPSEEK_MODEL=test-model\n', encoding="utf-8")

            values = load_env_file(path)

        self.assertEqual(values["DEEPSEEK_API_KEY"], "secret")
        self.assertEqual(values["DEEPSEEK_MODEL"], "test-model")

    def test_resolve_config_prefers_explicit_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "DEEPSEEK_API_KEY=file-key\nDEEPSEEK_MODEL=file-model\nDEEPSEEK_API_BASE=https://example.test/v1\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("DEEPSEEK_API_KEY", None)
                config = resolve_config(path, model="explicit-model", base_url="https://explicit.test/v1")

        self.assertEqual(config.api_key, "file-key")
        self.assertEqual(config.model, "explicit-model")
        self.assertEqual(config.base_url, "https://explicit.test/v1")

    def test_missing_key_has_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("DEEPSEEK_MODEL=test\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("DEEPSEEK_API_KEY", None)
                with self.assertRaises(VlmError) as context:
                    resolve_config(path)

        self.assertIn("DEEPSEEK_API_KEY", str(context.exception))


if __name__ == "__main__":
    unittest.main()

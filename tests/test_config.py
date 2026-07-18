import json
import tempfile
from pathlib import Path
import unittest

from conglomeraite.config import AppConfig


class ConfigTests(unittest.TestCase):
    def test_file_then_environment_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"qwen": {"model": "from-file"}}))
            config = AppConfig.load(
                path,
                environ={
                    "QWEN_API_KEY": "secret",
                    "CONGLOMERAITE_QWEN_MODEL": "from-env",
                    "CONGLOMERAITE_OFFLINE": "true",
                },
            )
        self.assertEqual(config.qwen.model, "from-env")
        self.assertEqual(config.qwen.api_key, "secret")
        self.assertTrue(config.offline)
        self.assertEqual(config.redacted_dict()["qwen"]["api_key"], "***")

    def test_unknown_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"memory": {"typo": 1}}')
            with self.assertRaisesRegex(ValueError, "memory.typo"):
                AppConfig.load(path, environ={})

    def test_api_keys_are_rejected_in_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"qwen": {"api_key": "must-not-be-here"}}')
            with self.assertRaisesRegex(ValueError, "forbidden in JSON"):
                AppConfig.load(path, environ={})

    def test_bad_json_types_are_clean_value_errors(self) -> None:
        bad_configs = [
            {"offline": "false"},
            {"qwen": {"endpoint": 123}},
            {"loop": {"max_iterations": True}},
            {"memory": {"monitor_required": 1}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            for payload in bad_configs:
                path.write_text(json.dumps(payload))
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    AppConfig.load(path, environ={})

    def test_target_score_is_strictly_ten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"loop": {"target_score": 9}}')
            with self.assertRaisesRegex(ValueError, "exactly 10"):
                AppConfig.load(path, environ={})


if __name__ == "__main__":
    unittest.main()

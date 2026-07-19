import argparse
import json
import os
import tempfile
from pathlib import Path
import unittest

from unittest.mock import patch

from conglomeraite.cli import _build_router, _read_task, _write_protected_json
from conglomeraite.config import AppConfig


class CliTests(unittest.TestCase):
    def test_systemd_json_task_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job.json"
            path.write_text(json.dumps({"task": "do work", "rubric": "be exact"}))
            request = _read_task(argparse.Namespace(task_file=path, task=None))
        self.assertEqual(request.task, "do work")
        self.assertEqual(request.rubric, "be exact")
        self.assertTrue(request.cloud_allowed)

    def test_systemd_task_can_disable_cloud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job.json"
            path.write_text(json.dumps({"task": "private", "cloud_allowed": False}))
            request = _read_task(argparse.Namespace(task_file=path, task=None))
        self.assertFalse(request.cloud_allowed)

    def test_task_can_forbid_cloud_before_provider_construction(self) -> None:
        config = AppConfig.load(environ={"QWEN_API_KEY": "secret"})
        with patch("conglomeraite.cli.OpenAICompatibleProvider", autospec=True) as provider:
            local_instance = provider.return_value
            local_instance.name = "local"
            router = _build_router(config, cloud_allowed=False)
        self.assertIsNone(router.primary)
        self.assertEqual(provider.call_count, 1)

    def test_task_and_rubric_limits_are_enforced(self) -> None:
        args = argparse.Namespace(task_file=None, task="12345")
        with self.assertRaisesRegex(ValueError, "task exceeds"):
            _read_task(args, max_task_chars=4)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job.json"
            path.write_text(json.dumps({"task": "ok", "rubric": "12345"}))
            with self.assertRaisesRegex(ValueError, "rubric exceeds"):
                _read_task(
                    argparse.Namespace(task_file=path, task=None),
                    max_rubric_chars=4,
                )

    def test_protected_atomic_result_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            _write_protected_json(path, {"final_draft": "secret"})
            self.assertEqual(json.loads(path.read_text())["final_draft"], "secret")
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_protected_atomic_result_file_without_fchmod(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            with patch.object(os, "fchmod", None, create=True):
                _write_protected_json(path, {"status": "safe"})
            self.assertEqual(json.loads(path.read_text())["status"], "safe")


if __name__ == "__main__":
    unittest.main()

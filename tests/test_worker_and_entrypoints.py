from __future__ import annotations

import json
import runpy
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pyrefman
from pyrefman import worker

from tests.helpers import workspace_dir


class WorkerAndEntrypointTests(unittest.TestCase):
    def test_worker_payload_helpers(self) -> None:
        with workspace_dir() as tmp_path:
            payload_path = tmp_path / "payload.json"
            result_path = tmp_path / "result.json"
            payload_path.write_text(json.dumps({"x": 1}), encoding="utf-8")
            self.assertEqual(worker._load_payload(payload_path), {"x": 1})
            worker._write_payload(result_path, {"ok": True})
            self.assertEqual(json.loads(result_path.read_text(encoding="utf-8")), {"ok": True})

        self.assertIn("anyone with the link", worker._no_urls_message("google_doc"))
        self.assertNotIn("anyone with the link", worker._no_urls_message("file"))

    def test_worker_main_branches(self) -> None:
        with patch.object(sys, "argv", ["worker"]):
            self.assertEqual(worker.main(), 2)

        with workspace_dir() as tmp_path:
            args_path = tmp_path / "args.json"
            result_path = tmp_path / "result.json"
            args_path.write_text(json.dumps({"input_source": "text", "mapping_column_keys": ["url"]}), encoding="utf-8")

            with patch.object(sys, "argv", ["worker", str(args_path), str(result_path)]), patch(
                "pyrefman.worker.build_mapping_columns_from_keys",
                return_value=[("url", lambda row: row["url"])],
            ), patch("pyrefman.worker.process_file_citations", return_value={"markdown_text": "preview", "reference_summary": {"x": 1}}):
                self.assertEqual(worker.main(), 0)
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["success"])
            self.assertEqual(payload["preview_text"], "preview")

            args_path.write_text(json.dumps({"input_source": "text"}), encoding="utf-8")
            with patch.object(sys, "argv", ["worker", str(args_path), str(result_path)]), patch(
                "pyrefman.worker.build_mapping_columns_from_keys",
                return_value=[],
            ), patch("pyrefman.worker.process_file_citations", return_value="plain output"):
                self.assertEqual(worker.main(), 0)

            args_path.write_text(json.dumps({"input_source": "text", "_ui_input_mode": "google_doc"}), encoding="utf-8")
            with patch.object(sys, "argv", ["worker", str(args_path), str(result_path)]), patch(
                "pyrefman.worker.build_mapping_columns_from_keys",
                return_value=[],
            ), patch("pyrefman.worker.process_file_citations", side_effect=pyrefman.NoUrlsFoundError()):
                self.assertEqual(worker.main(), 1)
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["show_error_dialog"])

            with patch.object(sys, "argv", ["worker", str(args_path), str(result_path)]), patch(
                "pyrefman.worker.build_mapping_columns_from_keys",
                return_value=[],
            ), patch("pyrefman.worker.process_file_citations", side_effect=RuntimeError("boom")), patch("traceback.print_exc"):
                self.assertEqual(worker.main(), 1)
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["error"], "boom")

    def test_worker_and_module_entrypoints(self) -> None:
        with workspace_dir() as tmp_path:
            args_path = tmp_path / "args.json"
            result_path = tmp_path / "result.json"
            args_path.write_text(json.dumps({"input_source": "text"}), encoding="utf-8")

            with patch.object(sys, "argv", ["pyrefman.worker", str(args_path), str(result_path)]), patch(
                "pyrefman.build_mapping_file_rows", return_value=[]
            ), patch("pyrefman.process_file_citations", return_value={"markdown_text": "", "reference_summary": {}}):
                with self.assertRaises(SystemExit) as worker_exit:
                    runpy.run_module("pyrefman.worker", run_name="__main__")
            self.assertEqual(worker_exit.exception.code, 0)

        launch_app_mock = MagicMock()
        with patch("pyrefman.ui.launch_app", launch_app_mock):
            runpy.run_module("pyrefman.__main__", run_name="__main__")
        launch_app_mock.assert_called_once()

        captured = {}
        with patch("pprint.pprint", side_effect=lambda value: captured.setdefault("value", value)):
            runpy.run_module("pyrefman.NBIBParser", run_name="__main__")
        self.assertEqual(captured["value"]["PMID"], "37118429")

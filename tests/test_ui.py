from __future__ import annotations

import importlib
import json
import sys
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.helpers import DummyAppearance, DummyEvent, workspace_dir


ui = importlib.import_module("pyrefman.ui")
WX_APP = ui.wx.App.Get() or ui.wx.App(False)
ORIGINAL_LOAD_STATE = ui.PyRefmanFrame._load_state


class FakeDialog:
    def __init__(self, path: str, modal_result: int) -> None:
        self._path = path
        self._modal_result = modal_result
        self.destroyed = False

    def ShowModal(self):
        return self._modal_result

    def GetPath(self):
        return self._path

    def Destroy(self):
        self.destroyed = True


class FakeThread:
    def __init__(self, target=None, args=(), daemon=False):
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True


class FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)
        self.closed = False

    def __iter__(self):
        return iter(self._lines)

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, lines=None, return_code=0, pid=123):
        self.stdout = FakeStdout(lines or [])
        self.return_code = return_code
        self.pid = pid
        self.killed = False

    def wait(self):
        return self.return_code

    def poll(self):
        return None

    def kill(self):
        self.killed = True


@contextmanager
def build_frame(*, state=None, pandoc_available=True):
    with workspace_dir() as tmp_path:
        state_file = tmp_path / "ui_state.json"
        if state is not None:
            state_file.write_text(json.dumps(state), encoding="utf-8")
        with ExitStack() as stack:
            stack.enter_context(patch.object(ui, "STATE_FILE", state_file))
            stack.enter_context(patch.object(ui, "get_downloads_dir", return_value=str(tmp_path)))
            stack.enter_context(patch.object(ui, "is_pandoc_available", return_value=pandoc_available))
            stack.enter_context(patch.object(ui.wx, "CallAfter", side_effect=lambda callback, *args: callback(*args)))
            stack.enter_context(patch.object(ui.wx, "MessageBox", return_value=ui.wx.OK))
            stack.enter_context(patch.object(ui.PyRefmanFrame, "_load_state", return_value=state or {}))
            frame = ui.PyRefmanFrame()
            frame.Hide()
            try:
                yield frame, tmp_path, state_file
            finally:
                completion = getattr(frame, "_completion_frame", None)
                if completion is not None and not completion.IsBeingDeleted():
                    completion.Destroy()
                frame.Destroy()


class UITests(unittest.TestCase):
    def test_discover_reference_styles_and_queue_writer(self) -> None:
        fake_files = [Path("VancouverStyle.py"), Path("DemoStyle.py"), Path("_ignore.py"), Path("ReferencesStyle.py")]
        with patch.object(ui, "STYLE_DIRECTORY", Path.cwd()), patch.object(Path, "exists", return_value=True), patch.object(
            Path, "glob", return_value=fake_files
        ):
            styles = ui.discover_reference_styles()
        self.assertEqual(styles[0], "VancouverStyle")
        self.assertIn("DemoStyle", styles)

        with patch.object(ui, "STYLE_DIRECTORY", Path.cwd()), patch.object(Path, "exists", return_value=False):
            self.assertEqual(ui.discover_reference_styles(), tuple(ui.PREFERRED_STYLE_ORDER))

        lines = []
        writer = ui.QueueWriter(lines.append)
        writer.write("one\ntwo")
        writer.write("\nthree")
        writer.flush()
        self.assertEqual(lines, ["one", "two", "three"])

    def test_completion_frame_paths_and_close(self) -> None:
        with build_frame() as (frame, tmp_path, _state_file):
            output_file = tmp_path / "out.md"
            mapping_file = tmp_path / "map.csv"
            output_file.write_text("x", encoding="utf-8")
            mapping_file.write_text("y", encoding="utf-8")
            completion = ui.CompletionFrame(frame, {"success": True, "output_file": str(output_file), "mapping_file": str(mapping_file)})
            try:
                self.assertEqual(completion._existing_payload_path("output_file"), output_file)
                self.assertEqual(completion._payload_paths(), [str(output_file), str(mapping_file)])
                self.assertGreaterEqual(completion._preferred_width(), 700)
                completion._apply_preferred_size()
                with patch.object(frame, "_open_path") as open_path, patch.object(completion, "Close") as close_method:
                    completion._open_and_close(output_file)
                    open_path.assert_called_once_with(output_file)
                    close_method.assert_called_once()
                event = DummyEvent()
                completion._on_close(event)
                self.assertTrue(event.skipped)
            finally:
                completion.Destroy()

            error_completion = ui.CompletionFrame(frame, {"success": False, "error": "boom"})
            try:
                error_completion._on_close_button(None)
            finally:
                error_completion.Destroy()

    def test_frame_static_helpers_and_state_management(self) -> None:
        saved_state = {
            "citations_dir": "",
            "output_format": "docx",
            "reference_style": "VancouverStyle",
            "mapping_enabled": True,
        }
        with build_frame(state=saved_state, pandoc_available=False) as (frame, tmp_path, state_file):
            self.assertEqual(frame._get_input_mode(), "file")
            self.assertEqual(frame._get_output_format(), "markdown")
            self.assertEqual(frame._get_output_extension(), ".md")
            self.assertIn(".md", frame._get_allowed_output_suffixes())
            self.assertTrue(frame._normalize_output_path_for_format(Path("demo.docx")).name.endswith(".md"))
            self.assertTrue(frame._default_output_name().endswith(".md"))
            self.assertTrue(frame._is_markdown_path(Path("x.md")))
            self.assertTrue(frame._is_text_path(Path("x.txt")))
            self.assertIn("Pandoc", frame._file_input_hint_text())
            self.assertIn("disabled", frame._output_format_hint_text())
            self.assertIn("repair the local Pandoc", frame._missing_pandoc_input_message())
            self.assertEqual(frame._normalize_path_text(f'"{tmp_path}"'), str(tmp_path))
            self.assertTrue(frame._is_standard_google_doc_url("https://docs.google.com/document/d/abc/edit"))
            self.assertFalse(frame._is_standard_google_doc_url("https://example.com"))
            self.assertTrue(frame._example_native_path())

            with patch.object(ui.wx.SystemSettings, "GetAppearance", return_value=DummyAppearance(dark=True)):
                self.assertTrue(frame._get_system_appearance().IsDark())
                frame._apply_system_appearance()
                self.assertTrue(frame._dark_mode_active)

            event = DummyEvent()
            frame._on_system_colours_changed(event)
            self.assertTrue(event.skipped)
            resize_event = DummyEvent()
            frame._on_frame_resize(resize_event)
            self.assertTrue(resize_event.skipped)

            frame._running = True
            with patch.object(frame.progress_gauge, "Pulse") as pulse:
                frame._on_progress_timer(None)
                pulse.assert_called_once()
            focus_event = DummyEvent()
            frame._on_summary_focus(focus_event)
            self.assertTrue(focus_event.skipped)

            frame.citations_dir_ctrl.SetValue(str(tmp_path / "citations"))
            frame._save_state()
            self.assertTrue(state_file.exists())
            self.assertEqual(json.loads(state_file.read_text(encoding="utf-8"))["output_format"], "markdown")
            state_file.write_text("{bad json", encoding="utf-8")
            self.assertEqual(ORIGINAL_LOAD_STATE(frame), {})

    def test_frame_validation_statuses_and_arguments(self) -> None:
        with build_frame(pandoc_available=True) as (frame, tmp_path, _state_file):
            input_file = tmp_path / "input.md"
            input_file.write_text("Text [source](https://pubmed.ncbi.nlm.nih.gov/1/)", encoding="utf-8")
            text_file = tmp_path / "input.txt"
            text_file.write_text("https://pubmed.ncbi.nlm.nih.gov/1/", encoding="utf-8")
            citations_dir = tmp_path / "citations"
            citations_dir.mkdir()

            frame.input_file_ctrl.SetValue(str(input_file))
            frame.citations_dir_ctrl.SetValue(str(citations_dir))
            frame.output_file_ctrl.SetValue(str(tmp_path / "output.md"))
            frame._refresh_dynamic_labels()
            frame._validate_form()
            self.assertTrue(frame.run_button.IsEnabled())
            self.assertEqual(frame._effective_output_path(), tmp_path / "output.md")
            self.assertTrue(frame._effective_mapping_path().name.endswith(ui.DEFAULT_MAPPING_SUFFIX))

            frame.input_file_ctrl.SetValue(str(text_file))
            frame._update_input_file_status()
            self.assertIn("Bare URLs", frame.file_input_status.GetLabel())

            bad_doc = tmp_path / "input.docx"
            bad_doc.write_text("doc", encoding="utf-8")
            frame._pandoc_available = False
            frame.input_file_ctrl.SetValue(str(bad_doc))
            frame._update_input_file_status()
            self.assertIn("requires Pandoc", frame.file_input_status.GetLabel())
            frame._pandoc_available = True

            frame.google_doc_ctrl.SetValue("https://example.com")
            frame._update_google_doc_status()
            self.assertIn("standard Google Doc URL", frame.google_doc_status.GetLabel())
            frame.google_doc_ctrl.SetValue("https://docs.google.com/document/d/abc/edit")
            frame._update_google_doc_status()
            self.assertEqual(frame.google_doc_status.GetLabel(), "")

            frame.raw_text_ctrl.SetValue("https://pubmed.ncbi.nlm.nih.gov/1/")
            frame._update_raw_text_status()
            self.assertIn("converted", frame.raw_text_status.GetLabel().lower())
            converted, changed = frame._prepare_raw_input_text()
            self.assertTrue(changed)
            self.assertIn("[https://pubmed.ncbi.nlm.nih.gov/1/]", converted)
            frame.raw_text_ctrl.SetValue("[x](https://pubmed.ncbi.nlm.nih.gov/1/)")
            self.assertEqual(frame._prepare_raw_input_text(), ("[x](https://pubmed.ncbi.nlm.nih.gov/1/)", False))
            frame.raw_text_ctrl.SetValue("")
            with self.assertRaises(ValueError):
                frame._prepare_raw_input_text()

            frame.output_enabled_checkbox.SetValue(False)
            frame._update_output_file_status()
            self.assertIn("preview tab only", frame.output_file_status.GetLabel())
            frame.output_enabled_checkbox.SetValue(True)
            frame.output_file_ctrl.SetValue("")
            frame._update_output_file_status()
            self.assertIn("If left blank", frame.output_file_status.GetLabel())
            frame.output_file_ctrl.SetValue("relative.md")
            frame._update_output_file_status()
            self.assertIn("absolute local path", frame.output_file_status.GetLabel())
            frame.output_file_ctrl.SetValue(str(tmp_path / "output.docx"))
            frame.output_format_choice.SetSelection(1 if len(frame._output_format_choices) > 1 else 0)
            frame._update_output_file_status()

            frame.citations_dir_ctrl.SetValue("")
            frame._update_citations_dir_status()
            self.assertIn("If left blank", frame.citations_dir_status.GetLabel())
            frame.citations_dir_ctrl.SetValue("relative")
            frame._update_citations_dir_status()
            self.assertIn("absolute local path", frame.citations_dir_status.GetLabel())
            frame.citations_dir_ctrl.SetValue(str(tmp_path / "missing"))
            frame._update_citations_dir_status()
            self.assertIn("will be created", frame.citations_dir_status.GetLabel())
            frame.citations_dir_ctrl.SetValue(str(citations_dir))
            frame._update_citations_dir_status()
            self.assertEqual(frame.citations_dir_status.GetLabel(), "")

            frame.output_enabled_checkbox.SetValue(False)
            frame._update_mapping_info_status()
            self.assertIn("Enable", frame.mapping_status.GetLabel())
            frame.output_enabled_checkbox.SetValue(True)
            frame.mapping_enabled_checkbox.SetValue(False)
            frame._update_mapping_info_status()
            self.assertEqual(frame.mapping_status.GetLabel(), "")
            frame.mapping_enabled_checkbox.SetValue(True)
            frame.output_file_ctrl.SetValue("relative")
            frame._update_mapping_info_status()
            self.assertIn("valid absolute output path", frame.mapping_status.GetLabel())
            frame.output_format_choice.SetSelection(0)
            frame.output_file_ctrl.SetValue(str(tmp_path / "output.md"))
            frame._update_mapping_info_status()
            self.assertIn("Mapping file will be saved", frame.mapping_status.GetLabel())

            output_path, output_error = frame._validate_output_path_text()
            self.assertIsNone(output_error)
            self.assertEqual(output_path, tmp_path / "output.md")
            frame.output_file_ctrl.SetValue(str(tmp_path / "output.txt"))
            _output_path, output_error = frame._validate_output_path_text()
            self.assertIn("must end with", output_error)

            frame._input_mode_buttons["google_doc"].SetValue(True)
            frame.google_doc_ctrl.SetValue("https://docs.google.com/document/d/abc/edit")
            frame.output_file_ctrl.SetValue(str(tmp_path / "doc.md"))
            frame.citations_dir_ctrl.SetValue(str(citations_dir))
            args = frame._collect_arguments()
            self.assertEqual(args["_ui_input_mode"], "google_doc")

            frame._input_mode_buttons["raw_text"].SetValue(True)
            frame.raw_text_ctrl.SetValue("https://pubmed.ncbi.nlm.nih.gov/1/")
            args = frame._collect_arguments()
            self.assertEqual(args["_ui_input_mode"], "raw_text")
            self.assertTrue(frame._pending_run_notes)

            frame._input_mode_buttons["file"].SetValue(True)
            frame.input_file_ctrl.SetValue(str(input_file))
            frame.output_file_ctrl.SetValue(str(tmp_path / "output.md"))
            for checkbox in frame._mapping_checkboxes.values():
                checkbox.SetValue(False)
            frame.mapping_enabled_checkbox.SetValue(True)
            with self.assertRaises(ValueError):
                frame._collect_arguments()

    def test_frame_dialogs_logs_worker_helpers_and_finish_flow(self) -> None:
        with build_frame(pandoc_available=True) as (frame, tmp_path, _state_file):
            input_file = tmp_path / "input.md"
            input_file.write_text("x", encoding="utf-8")
            frame.input_file_ctrl.SetValue(str(input_file))
            frame.output_file_ctrl.SetValue(str(tmp_path / "output.md"))
            frame.citations_dir_ctrl.SetValue(str(tmp_path / "citations"))

            with patch.object(ui.wx, "FileDialog", return_value=FakeDialog(str(input_file), ui.wx.ID_OK)):
                frame._browse_input_file(None)
            with patch.object(ui.wx, "FileDialog", return_value=FakeDialog(str(tmp_path / "chosen"), ui.wx.ID_OK)):
                frame._browse_output_file(None)
            with patch.object(ui.wx, "DirDialog", return_value=FakeDialog(str(tmp_path / "citations"), ui.wx.ID_OK)):
                frame._browse_citations_dir(None)

            frame._append_log_line("hello")
            self.assertIn("hello", frame.log_ctrl.GetValue())
            frame._append_log_block("a\n\nb")
            self.assertIn("b", frame.log_ctrl.GetValue())
            frame._clear_log()
            self.assertEqual(frame.log_ctrl.GetValue(), "")

            self.assertEqual(set(frame._selected_mapping_column_keys()), set(ui.DEFAULT_MAPPING_KEYS))
            for checkbox in frame._mapping_checkboxes.values():
                checkbox.SetValue(False)
            self.assertEqual(frame._selected_mapping_column_keys(), [])
            self.assertIsNone(frame._resolve_result_output_path({"save_output": False}))
            self.assertTrue(frame._resolve_result_output_path({"save_output": True, "output_file": str(tmp_path / "x.md")}).name.endswith(".md"))
            self.assertTrue(frame._resolve_result_output_path({"save_output": True, "input_source": str(input_file)}).name.endswith("_formatted.md"))

            self.assertEqual(
                frame._serialize_worker_args({"path": tmp_path / "x", "flag": True, "items": ["a"], "value": 3}),
                {"path": str(tmp_path / "x"), "flag": True, "items": ["a"], "value": "3"},
            )
            frame._worker_args_file = tmp_path / "args.json"
            frame._worker_result_file = tmp_path / "result.json"
            self.assertIn("pyrefman.worker", frame._worker_command())

            worker_dir = tmp_path / "worker-dir"
            worker_dir.mkdir()
            with patch("tempfile.mkdtemp", return_value=str(worker_dir)), patch("subprocess.Popen", return_value="proc") as popen:
                process = frame._spawn_worker_process({"input_source": "x", "output_file": tmp_path / "out.md"})
            self.assertEqual(process, "proc")
            self.assertTrue((worker_dir / "args.json").exists())

            frame._worker_result_file = worker_dir / "result.json"
            frame._worker_result_file.write_text(json.dumps({"success": True}), encoding="utf-8")
            self.assertTrue(frame._load_worker_result_payload(1)["success"])
            frame._worker_result_file.write_text("{bad json", encoding="utf-8")
            self.assertTrue(frame._load_worker_result_payload(0)["success"])
            self.assertFalse(frame._load_worker_result_payload(1)["success"])

            fake_process = FakeProcess()
            frame._worker_process = fake_process
            frame._worker_args_file = worker_dir / "args.json"
            frame._worker_args_file.write_text("{}", encoding="utf-8")
            frame._worker_result_file = worker_dir / "result.json"
            frame._worker_result_file.write_text("{}", encoding="utf-8")
            frame._cleanup_worker_artifacts()
            self.assertIsNone(frame._worker_process)

            frame._handle_worker_log("line1\nline2")
            self.assertIn("line2", frame.log_ctrl.GetValue())
            with patch.object(ui.os, "startfile", create=True) as startfile:
                frame._open_path(tmp_path / "x")
                startfile.assert_called_once()

            output_file = tmp_path / "done.md"
            output_file.write_text("x", encoding="utf-8")
            mapping_file = tmp_path / "done.csv"
            mapping_file.write_text("x", encoding="utf-8")
            self.assertEqual(frame._completion_open_target({"output_file": str(output_file)}), output_file)
            self.assertEqual(frame._completion_open_target({"mapping_file": str(mapping_file)}), mapping_file)
            self.assertIsNone(frame._completion_open_target({}))
            frame._show_completion_dialog({"success": True, "output_file": str(output_file)})
            self.assertIsNotNone(frame._completion_frame)
            self.assertIn("Total unique references", frame._format_reference_summary({"total_unique_references": 1}))
            self.assertIn("No references", frame._format_reference_summary({}))

            frame._worker_thread = object()
            frame._running = True
            frame._finish_processing({"aborted": True})
            self.assertEqual(frame.run_state_label.GetLabel(), "Aborted")

            frame._worker_thread = object()
            frame._running = True
            frame._finish_processing({"success": True, "preview_text": "preview", "reference_summary": {"total_unique_references": 1}, "output_file": str(output_file), "skip_completion_dialog": True})
            self.assertEqual(frame.run_state_label.GetLabel(), "Completed")

            frame._worker_thread = object()
            frame._running = True
            with patch.object(ui.wx, "MessageBox", return_value=ui.wx.OK) as message_box:
                frame._finish_processing({"success": False, "error": "boom", "show_error_dialog": True, "skip_completion_dialog": True})
                message_box.assert_called_once()
            self.assertEqual(frame.run_state_label.GetLabel(), "Failed")

    def test_frame_run_control_flow_and_launch_app(self) -> None:
        with build_frame(pandoc_available=True) as (frame, tmp_path, _state_file):
            input_file = tmp_path / "input.md"
            input_file.write_text("Text [source](https://pubmed.ncbi.nlm.nih.gov/1/)", encoding="utf-8")
            frame.input_file_ctrl.SetValue(str(input_file))
            frame.output_file_ctrl.SetValue(str(tmp_path / "output.md"))
            frame.citations_dir_ctrl.SetValue(str(tmp_path / "citations"))

            with patch.object(frame, "_start_processing") as start_processing, patch.object(frame, "_request_abort") as request_abort:
                frame._running = False
                frame._on_run_button()
                start_processing.assert_called_once()
                frame._running = True
                frame._on_run_button()
                request_abort.assert_called_once()

            frame._running = True
            frame._abort_requested = False
            with patch.object(frame, "_terminate_worker_process") as terminate:
                frame._request_abort()
                terminate.assert_called_once()

            frame._closing = False
            with patch.object(ui.wx, "CallAfter") as call_after:
                frame._post_to_ui(lambda: None)
                call_after.assert_called_once()
            frame._closing = True
            with patch.object(ui.wx, "CallAfter") as call_after:
                frame._post_to_ui(lambda: None)
                call_after.assert_not_called()

            process = FakeProcess(lines=["one\n", "two\n"], return_code=0)
            frame._cleanup_worker_artifacts = MagicMock()
            frame._load_worker_result_payload = MagicMock(return_value={"success": True, "preview_text": "x", "reference_summary": {}})
            frame._post_to_ui = MagicMock()
            frame._monitor_worker_process(process, {"save_output": False, "mapping_file": None})
            self.assertTrue(frame._post_to_ui.called)

            frame._abort_requested = True
            frame._post_to_ui.reset_mock()
            frame._monitor_worker_process(process, {"save_output": False, "mapping_file": None})
            self.assertTrue(frame._post_to_ui.called)

            frame._worker_process = process
            with patch.object(ui.sys, "platform", "win32"), patch("subprocess.run") as run_taskkill:
                frame._terminate_worker_process()
                run_taskkill.assert_called_once()

            frame._worker_process = process
            with patch.object(ui.sys, "platform", "linux"), patch.object(ui.os, "killpg", side_effect=RuntimeError("boom"), create=True), patch.object(
                ui.os, "getpgid", return_value=1, create=True
            ):
                frame._terminate_worker_process()
                self.assertTrue(process.killed)

            with patch.object(frame, "_collect_arguments", return_value={"save_output": False}), patch.object(
                frame, "_spawn_worker_process", return_value=process
            ), patch.object(ui.threading, "Thread", side_effect=lambda **kwargs: FakeThread(**kwargs)):
                frame._start_processing()
                self.assertTrue(frame._running)

            frame._worker_process = object()
            with patch.object(ui.wx, "MessageBox", return_value=ui.wx.OK) as message_box:
                frame._start_processing()
                message_box.assert_called()

            frame._worker_process = None
            with patch.object(frame, "_collect_arguments", side_effect=ValueError("bad args")), patch.object(
                ui.wx, "MessageBox", return_value=ui.wx.OK
            ) as message_box:
                frame._start_processing()
                message_box.assert_called()

            frame._worker_process = None
            with patch.object(frame, "_collect_arguments", return_value={"save_output": False}), patch.object(
                frame, "_spawn_worker_process", side_effect=RuntimeError("boom")
            ), patch.object(ui.wx, "MessageBox", return_value=ui.wx.OK) as message_box:
                frame._start_processing()
                message_box.assert_called()

            completion = MagicMock()
            completion.IsBeingDeleted.return_value = False
            frame._completion_frame = completion
            frame._running = True
            event = DummyEvent()
            with patch.object(frame, "_terminate_worker_process") as terminate:
                frame._on_close(event)
                terminate.assert_called_once()
            completion.Destroy.assert_called_once()
            self.assertTrue(event.skipped)

        with patch.object(ui, "PyRefmanFrame") as frame_cls, patch.object(ui.wx, "App") as app_cls:
            app = MagicMock()
            app_cls.return_value = app
            frame = MagicMock()
            frame_cls.return_value = frame
            ui.launch_app()
            app.SetAppName.assert_called_once_with("PyRefman")
            frame.Show.assert_called_once()
            app.MainLoop.assert_called_once()

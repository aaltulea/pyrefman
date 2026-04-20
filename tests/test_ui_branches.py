from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import unittest

from tests.helpers import DummyEvent, write_text
from tests.test_ui import FakeDialog, FakeProcess, FakeThread, ORIGINAL_LOAD_STATE, build_frame


ui = importlib.import_module("pyrefman.ui")
WX_APP = ui.wx.App.Get() or ui.wx.App(False)


class FalseyLabel:
    def __bool__(self):
        return False


class ExplodingShownLabel:
    def __bool__(self):
        return True

    def IsBeingDeleted(self):
        return False

    def IsShown(self):
        raise RuntimeError("boom")


class Toggle:
    def __init__(self, value: bool) -> None:
        self.value = value

    def GetValue(self) -> bool:
        return self.value


class HideCaretRaiser:
    def HideNativeCaret(self) -> None:
        raise RuntimeError("boom")


class WorkerKiller:
    def __init__(self, *, poll_value=None, poll_error: Exception | None = None, kill_error: Exception | None = None, pid: int = 123) -> None:
        self._poll_value = poll_value
        self._poll_error = poll_error
        self._kill_error = kill_error
        self.pid = pid
        self.stdout = None
        self.killed = False

    def poll(self):
        if self._poll_error is not None:
            raise self._poll_error
        return self._poll_value

    def kill(self):
        self.killed = True
        if self._kill_error is not None:
            raise self._kill_error


class CloseRaiser:
    def close(self) -> None:
        raise RuntimeError("close boom")


class UIBranchTests(unittest.TestCase):
    def test_discovery_completionframe_and_wrapping_helpers(self) -> None:
        fake_files = [
            Path("VancouverStyle.py"),
            Path("Random.py"),
            Path("_ignore.py"),
            Path("ReferencesStyle.py"),
        ]
        with patch.object(ui, "STYLE_DIRECTORY", Path.cwd()), patch.object(Path, "exists", return_value=True), patch.object(
            Path, "glob", return_value=fake_files
        ):
            styles = ui.discover_reference_styles()
        self.assertEqual(styles, ("VancouverStyle",))

        lines = []
        writer = ui.QueueWriter(lines.append)
        writer.write("")
        writer.write("one")
        writer.flush()
        self.assertEqual(lines, ["one"])

        with build_frame() as (frame, tmp_path, _state_file):
            mapping_file = write_text(tmp_path / "mapping.csv", "x")
            completion = ui.CompletionFrame(frame, {"success": True, "mapping_file": str(mapping_file)})
            try:
                with patch.object(ui.wx.Display, "GetFromWindow", return_value=ui.wx.NOT_FOUND), patch.object(
                    ui.wx, "GetDisplaySize", return_value=SimpleNamespace(width=900, height=700)
                ):
                    area = completion._display_client_area()
                self.assertEqual((area.width, area.height), (900, 700))

                with patch.object(frame, "Enable", side_effect=RuntimeError("boom")):
                    completion._close_owner_block()
            finally:
                completion.Destroy()

    def test_ui_static_helpers_and_small_event_handlers(self) -> None:
        self.assertFalse(ui.PyRefmanFrame._is_markdown_path(None))
        self.assertFalse(ui.PyRefmanFrame._is_text_path(None))
        self.assertEqual(
            ui.PyRefmanFrame._get_input_mode(SimpleNamespace(_input_mode_buttons={key: Toggle(False) for key, _ in ui.INPUT_MODE_CHOICES})),
            "file",
        )
        with patch.object(ui.sys, "platform", "darwin"):
            self.assertEqual(ui.PyRefmanFrame._example_native_path(), "/Users/name/Documents/file.docx")
        with patch.object(ui.sys, "platform", "linux"):
            self.assertEqual(ui.PyRefmanFrame._example_native_path(), "/home/name/file.docx")

        with patch.object(ui.wx.SystemSettings, "GetAppearance", new=None):
            self.assertIsNone(ui.PyRefmanFrame._get_system_appearance())
        with patch.object(ui.wx.SystemSettings, "GetAppearance", side_effect=RuntimeError("boom")):
            self.assertIsNone(ui.PyRefmanFrame._get_system_appearance())

        ui.PyRefmanFrame._hide_text_caret(HideCaretRaiser())

        with build_frame() as (frame, tmp_path, _state_file):
            frame._wrappable_labels = [FalseyLabel(), ExplodingShownLabel()]
            frame._rewrap_labels()
            self.assertEqual(frame._wrappable_labels, [])

            with patch.object(frame, "_get_system_appearance", return_value=None):
                control = MagicMock()
                frame._apply_system_text_colours(control)
                control.SetBackgroundColour.assert_not_called()

            dummy_frame = ui.PyRefmanFrame.__new__(ui.PyRefmanFrame)
            ui.PyRefmanFrame._update_mapping_columns_layout(dummy_frame)

            with patch.object(frame.mapping_details_panel, "IsShown", return_value=True), patch.object(
                frame.mapping_columns_panel, "GetClientSize", return_value=SimpleNamespace(width=500)
            ), patch.object(frame.mapping_columns_sizer, "GetCols", return_value=2), patch.object(
                frame.mapping_columns_sizer, "SetCols"
            ) as set_cols:
                frame._update_mapping_columns_layout()
            set_cols.assert_called_once_with(1)

            with patch.object(frame, "_toggle_input_mode") as toggle_input, patch.object(
                frame, "_refresh_dynamic_labels"
            ) as refresh_dynamic, patch.object(frame, "_validate_form") as validate:
                frame._on_input_mode_changed()
            toggle_input.assert_called_once()
            refresh_dynamic.assert_called_once()
            validate.assert_called_once()

            with patch.object(frame, "_toggle_output_widgets") as toggle_output, patch.object(
                frame, "_refresh_dynamic_labels"
            ) as refresh_dynamic, patch.object(frame, "_validate_form") as validate:
                frame._on_output_toggle_changed()
            toggle_output.assert_called_once()
            refresh_dynamic.assert_called_once()
            validate.assert_called_once()

            with patch.object(frame, "_refresh_dynamic_labels") as refresh_dynamic, patch.object(
                frame, "_validate_form"
            ) as validate:
                frame._on_google_doc_changed()
            refresh_dynamic.assert_called_once()
            validate.assert_called_once()

            with patch.object(frame, "_toggle_mapping_widgets") as toggle_mapping, patch.object(
                frame, "_refresh_dynamic_labels"
            ) as refresh_dynamic, patch.object(frame, "_validate_form") as validate, patch.object(
                frame, "_save_state"
            ) as save_state:
                frame._on_mapping_toggle_changed()
            toggle_mapping.assert_called_once()
            refresh_dynamic.assert_called_once()
            validate.assert_called_once()
            save_state.assert_called_once()

            with patch.object(frame, "_validate_form") as validate:
                frame._on_mapping_columns_changed()
            validate.assert_called_once()

            with patch.object(frame, "_update_style_preview") as update_preview, patch.object(
                frame, "_refresh_dynamic_labels"
            ) as refresh_dynamic, patch.object(frame, "_save_state") as save_state:
                frame._on_reference_style_changed()
            update_preview.assert_called_once()
            refresh_dynamic.assert_called_once()
            save_state.assert_called_once()

            frame.output_file_ctrl.SetValue(str(tmp_path / "demo.md"))
            with patch.object(frame, "_validate_native_path_text", return_value=(tmp_path / "demo.md", None)), patch.object(
                frame, "_normalize_output_path_for_format", return_value=tmp_path / "demo.docx"
            ), patch.object(frame, "_refresh_output_file_hint") as refresh_hint, patch.object(
                frame, "_refresh_dynamic_labels"
            ) as refresh_dynamic, patch.object(frame, "_validate_form") as validate, patch.object(
                frame, "_save_state"
            ) as save_state:
                frame._on_output_format_changed()
            self.assertEqual(frame.output_file_ctrl.GetValue(), str(tmp_path / "demo.docx"))
            refresh_hint.assert_called_once()
            refresh_dynamic.assert_called_once()
            validate.assert_called_once()
            save_state.assert_called_once()

            with patch.object(ui, "init_reference_style_class") as init_style:
                init_style.return_value = SimpleNamespace(
                    format_reference=lambda _inline_reference: None,
                    format_grouped_inline_references=lambda refs: "()",
                    sort_formatted_references=lambda refs: refs,
                )
                self.assertEqual(frame._build_style_preview_text("EmptyStyle"), "Preview unavailable for this style.")

            with patch.object(ui, "init_reference_style_class") as init_style:
                init_style.return_value = SimpleNamespace(
                    format_reference=lambda inline_reference: SimpleNamespace(inline="[x]", full="", inline_reference=inline_reference),
                    format_grouped_inline_references=lambda refs: "[x]",
                    sort_formatted_references=lambda refs: refs,
                )
                preview = frame._build_style_preview_text("InlineOnlyStyle")
            self.assertIn("(This style mainly changes inline citation output.)", preview)

            with patch.object(ui, "init_reference_style_class", side_effect=RuntimeError("boom")):
                self.assertIn("boom", frame._build_style_preview_text("BrokenStyle"))

            frame.output_file_ctrl.SetValue("")
            self.assertEqual(frame._effective_output_path(), frame._default_output_path())

            frame.input_file_ctrl.SetValue("relative-path")
            frame._update_input_file_status()
            self.assertIn("absolute local path", frame.file_input_status.GetLabel())

            docx_path = write_text(tmp_path / "input.docx", "doc")
            frame.input_file_ctrl.SetValue(str(docx_path))
            frame._pandoc_available = True
            frame._update_input_file_status()
            self.assertIn("converted to markdown", frame.file_input_status.GetLabel())

            frame.raw_text_ctrl.SetValue("https://pubmed.ncbi.nlm.nih.gov/1/")
            frame._update_raw_text_status()
            self.assertIn("converted", frame.raw_text_status.GetLabel().lower())
            frame.raw_text_ctrl.SetValue("plain text without links")
            frame._update_raw_text_status()
            self.assertEqual(frame.raw_text_status.GetLabel(), "No URLs detected yet.")

            with patch.object(ui, "normalize_user_path", return_value=None):
                self.assertEqual(frame._validate_native_path_text("not-empty"), (None, "Path is empty."))

            with patch.object(ui, "STATE_FILE", tmp_path / "missing-state.json"):
                self.assertEqual(ORIGINAL_LOAD_STATE(frame), {})

            with patch.object(ui, "STATE_FILE", tmp_path / "blocked.json"):
                frame._state_ready = True
                with patch.object(Path, "write_text", side_effect=RuntimeError("boom")):
                    frame._save_state()

    def test_browsing_collection_and_worker_branches(self) -> None:
        with build_frame(pandoc_available=True) as (frame, tmp_path, _state_file):
            input_file = write_text(tmp_path / "input.md", "hello")
            frame.input_file_ctrl.SetValue(str(input_file))
            frame.citations_dir_ctrl.SetValue(str(tmp_path / "citations"))

            with patch.object(ui.wx, "FileDialog", return_value=FakeDialog("", ui.wx.ID_CANCEL)):
                frame._browse_input_file(None)

            frame.output_format_choice.SetSelection(1 if len(frame._output_format_choices) > 1 else 0)
            frame.output_file_ctrl.SetValue("relative")
            with patch.object(ui.wx, "FileDialog", return_value=FakeDialog(str(tmp_path / "chosen.docx"), ui.wx.ID_CANCEL)):
                frame._browse_output_file(None)

            frame._append_log_line("")
            self.assertEqual(frame.log_ctrl.GetValue(), "")

            output_path = frame._resolve_result_output_path({"save_output": True, "input_source": "not-a-real-path", "output_format": "docx"})
            self.assertEqual(output_path, frame._downloads_dir / "pyrefman_formatted.docx")

            with patch.object(frame, "_validate_native_path_text", return_value=(None, None)):
                with self.assertRaises(ValueError):
                    frame._collect_arguments()

            missing_path = tmp_path / "missing.md"
            with patch.object(frame, "_validate_native_path_text", return_value=(missing_path, "Bad path")):
                with self.assertRaisesRegex(ValueError, "Bad path"):
                    frame._collect_arguments()

            with patch.object(frame, "_validate_native_path_text", return_value=(missing_path, None)):
                with self.assertRaisesRegex(ValueError, "does not exist"):
                    frame._collect_arguments()

            docx_path = write_text(tmp_path / "needs-pandoc.docx", "x")
            with patch.object(frame, "_validate_native_path_text", return_value=(docx_path, None)), patch.object(
                ui, "input_file_requires_pandoc", return_value=True
            ):
                frame._pandoc_available = False
                with self.assertRaisesRegex(ValueError, "requires Pandoc"):
                    frame._collect_arguments()
                frame._pandoc_available = True

            frame._input_mode_buttons["google_doc"].SetValue(True)
            frame.google_doc_ctrl.SetValue("")
            with self.assertRaisesRegex(ValueError, "Paste a standard Google Doc URL"):
                frame._collect_arguments()

            frame.google_doc_ctrl.SetValue("https://example.com")
            with self.assertRaisesRegex(ValueError, "standard Google Doc URL"):
                frame._collect_arguments()

            frame._input_mode_buttons["raw_text"].SetValue(True)
            frame.raw_text_ctrl.SetValue("[x](https://pubmed.ncbi.nlm.nih.gov/1/)")
            frame.output_enabled_checkbox.SetValue(True)
            with patch.object(frame, "_validate_output_path_text", return_value=(None, "Bad output path")):
                with self.assertRaisesRegex(ValueError, "Bad output path"):
                    frame._collect_arguments()

            frame.output_enabled_checkbox.SetValue(False)
            with patch.object(frame, "_validate_native_path_text", return_value=(None, "Bad citations path")):
                with self.assertRaisesRegex(ValueError, "Bad citations path"):
                    frame._collect_arguments()

            with patch.object(frame, "_validate_native_path_text", return_value=(None, None)):
                args = frame._collect_arguments()
            self.assertEqual(args["citations_dir"], Path(frame._default_citations_dir))

            frame._pending_run_notes = []

            def collect_and_note():
                frame._pending_run_notes = ["Converted note"]
                return {"save_output": False}

            with patch.object(frame, "_collect_arguments", side_effect=collect_and_note), patch.object(
                frame, "_spawn_worker_process", return_value=FakeProcess()
            ), patch.object(ui.threading, "Thread", side_effect=lambda **kwargs: FakeThread(**kwargs)):
                frame._start_processing()
            self.assertIsNotNone(frame._worker_process)
            self.assertTrue(frame._worker_thread.started)
            self.assertIn("Converted note", frame.log_ctrl.GetValue())

            frame._running = False
            frame._abort_requested = False
            with patch.object(frame, "_terminate_worker_process") as terminate:
                frame._request_abort()
            terminate.assert_not_called()

            worker_dir = tmp_path / "worker-artifacts"
            worker_dir.mkdir()
            with patch("tempfile.mkdtemp", return_value=str(worker_dir)), patch("subprocess.Popen", return_value="proc") as popen, patch.object(
                ui.sys, "platform", "linux"
            ):
                process = frame._spawn_worker_process({"input_source": "x"})
            self.assertEqual(process, "proc")
            self.assertTrue(popen.call_args.kwargs["start_new_session"])

            process = FakeProcess(lines=["one\n"], return_code=0)
            frame._abort_requested = False
            frame._cleanup_worker_artifacts = MagicMock()
            frame._load_worker_result_payload = MagicMock(return_value={"success": True, "preview_text": "done", "reference_summary": {}})
            frame._post_to_ui = MagicMock()
            frame._monitor_worker_process(process, {"save_output": True, "mapping_file": "map.csv", "input_source": "missing.txt"})
            payload = frame._post_to_ui.call_args_list[-1].args[1]
            self.assertEqual(payload["mapping_file"], "map.csv")
            self.assertTrue(payload["output_file"].name.endswith(".md"))

            frame._cleanup_worker_artifacts = ui.PyRefmanFrame._cleanup_worker_artifacts.__get__(frame, ui.PyRefmanFrame)

            frame._worker_process = None
            frame._terminate_worker_process()

            frame._worker_process = WorkerKiller(poll_value=0)
            frame._terminate_worker_process()

            frame._worker_process = WorkerKiller(poll_error=RuntimeError("poll failed"), kill_error=RuntimeError("kill failed"))
            with patch.object(ui.sys, "platform", "linux"):
                frame._terminate_worker_process()

            frame._worker_process = SimpleNamespace(stdout=CloseRaiser())
            blocked_dir = tmp_path / "blocked"
            blocked_dir.mkdir()
            frame._worker_args_file = blocked_dir / "args.json"
            frame._worker_result_file = blocked_dir / "result.json"
            write_text(frame._worker_args_file, "{}")
            write_text(frame._worker_result_file, "{}")
            with patch.object(Path, "unlink", side_effect=RuntimeError("unlink failed")), patch.object(Path, "rmdir", side_effect=RuntimeError("rmdir failed")):
                frame._cleanup_worker_artifacts()
            self.assertIsNone(frame._worker_process)

    def test_open_dialog_summary_and_finish_branches(self) -> None:
        with build_frame() as (frame, tmp_path, _state_file):
            mapping_file = write_text(tmp_path / "map.csv", "x")
            output_file = write_text(tmp_path / "out.md", "x")

            with patch.object(ui.sys, "platform", "darwin"), patch("subprocess.Popen") as popen:
                frame._open_path(mapping_file)
            popen.assert_called_once_with(["open", str(mapping_file)])

            with patch.object(ui.sys, "platform", "linux"), patch("subprocess.Popen") as popen:
                frame._open_path(mapping_file)
            popen.assert_called_once_with(["xdg-open", str(mapping_file)])

            with patch.object(ui.sys, "platform", "linux"), patch("subprocess.Popen", side_effect=RuntimeError("boom")):
                frame._open_path(mapping_file)

            frame._closing = True
            frame._show_completion_dialog({"success": True})
            frame._closing = False

            existing_completion = MagicMock()
            existing_completion.IsBeingDeleted.return_value = False
            frame._completion_frame = existing_completion
            frame._show_completion_dialog({"success": True, "output_file": str(output_file)})
            existing_completion.Close.assert_called_once()

            self.assertEqual(frame._format_reference_summary({"total_unique_references": 0}), "No references were formatted in this run.")
            summary = frame._format_reference_summary(
                {
                    "total_unique_references": 2,
                    "oldest_year": 2001,
                    "newest_year": 2024,
                    "top_journals": [{"label": "Journal A", "count": 2}],
                    "top_authors": [{"label": "Doe JA", "count": 2}],
                }
            )
            self.assertIn("Oldest reference year: 2001", summary)
            self.assertIn("Newest reference year: 2024", summary)
            self.assertIn("Top cited journals:", summary)
            self.assertIn("Top cited authors:", summary)

            frame._worker_thread = object()
            frame._running = True
            with patch.object(frame, "_show_completion_dialog") as show_completion:
                frame._finish_processing(
                    {
                        "success": True,
                        "preview_text": "preview",
                        "reference_summary": {"total_unique_references": 1},
                        "mapping_file": str(mapping_file),
                    }
                )
            self.assertEqual(frame.run_state_label.GetLabel(), "Completed")
            self.assertIn("Mapping file saved", frame.status_label.GetLabel())
            show_completion.assert_called_once()

            frame._worker_thread = object()
            frame._running = True
            with patch.object(frame, "_show_completion_dialog") as show_completion:
                frame._finish_processing(
                    {
                        "success": True,
                        "preview_text": "preview",
                        "reference_summary": {"total_unique_references": 1},
                    }
                )
            self.assertIn("preview tab", frame.status_label.GetLabel())
            show_completion.assert_called_once()

            frame._worker_thread = object()
            frame._running = True
            with patch.object(frame, "_show_completion_dialog") as show_completion, patch.object(ui.wx, "MessageBox", return_value=ui.wx.OK) as message_box:
                frame._finish_processing(
                    {
                        "success": False,
                        "error": "boom",
                        "show_error_dialog": True,
                        "skip_completion_dialog": True,
                    }
                )
            show_completion.assert_not_called()
            message_box.assert_called_once()

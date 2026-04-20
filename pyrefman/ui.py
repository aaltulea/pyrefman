from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable

import wx
import wx.lib.scrolledpanel as scrolled

from pyrefman import __version__ as PYREFMAN_VERSION
from pyrefman.runtime import input_file_requires_pandoc, is_pandoc_available
from pyrefman.Utils import (
    convert_plain_text_urls_to_markdown,
    get_downloads_dir,
    get_output_file_path,
    has_markdown_hyperlinks,
    init_reference_style_class,
    normalize_user_path,
    strip_wrapping_quotes,
)
from pyrefman.data.InlineReference import InlineReference
from pyrefman.mapping_columns import (
    DEFAULT_MAPPING_KEYS,
    MAPPING_COLUMN_OPTIONS,
)


STYLE_DIRECTORY = Path(__file__).with_name("styles")
STATE_FILE = Path(__file__).with_name("pyrefman_ui_state.json")
DEFAULT_OUTPUT_BASENAME = "pyrefman_formatted"
DEFAULT_MAPPING_SUFFIX = "_mapping_file.csv"
STANDARD_GOOGLE_DOC_URL_RE = re.compile(
    r"^https?://docs\.google\.com/document/d/[^/\s]+(?:/.*)?$",
    re.IGNORECASE,
)
PREFERRED_STYLE_ORDER = [
    "VancouverStyle",
    "VancouverBoldTitleStyle",
    "VancouverColoredStyle",
    "VancouverSuperscriptStyle",
    "PMIDStyle",
]
INPUT_MODE_CHOICES = [
    ("file", "Document file"),
    ("google_doc", "Google Doc URL"),
    ("raw_text", "Pasted text"),
]
OUTPUT_FORMAT_CHOICES = [
    ("markdown", "Markdown (.md)"),
    ("docx", "Word document (.docx)"),
]
OUTPUT_FORMAT_EXTENSIONS = {
    "markdown": ".md",
    "docx": ".docx",
}
OUTPUT_FORMAT_ALLOWED_SUFFIXES = {
    "markdown": {".md", ".markdown"},
    "docx": {".docx"},
}


def discover_reference_styles() -> tuple[str, ...]:
    style_names: list[str] = []

    if STYLE_DIRECTORY.exists():
        for style_file in STYLE_DIRECTORY.glob("*.py"):
            style_name = style_file.stem
            if style_name.startswith("_") or style_name == "ReferencesStyle":
                continue
            if not style_name.endswith("Style"):
                continue
            style_names.append(style_name)

    if not style_names:
        style_names = list(PREFERRED_STYLE_ORDER)

    def style_sort_key(style_name: str) -> tuple[int, int | str]:
        if style_name in PREFERRED_STYLE_ORDER:
            return 0, PREFERRED_STYLE_ORDER.index(style_name)
        return 1, style_name.lower()

    return tuple(sorted(dict.fromkeys(style_names), key=style_sort_key))


REFERENCE_STYLES = discover_reference_styles()


class QueueWriter:
    def __init__(self, callback: Callable[[str], None]) -> None:
        self._callback = callback
        self._buffer = ""

    def write(self, text: str) -> None:
        if not text:
            return

        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip()
            if line:
                self._callback(line)

    def flush(self) -> None:
        remaining = self._buffer.strip()
        if remaining:
            self._callback(remaining)
        self._buffer = ""


class CompletionFrame(wx.Frame):
    def __init__(self, owner: "PyRefmanFrame", payload: dict) -> None:
        title = "PyRefman Finished" if payload.get("success") else "PyRefman Error"
        super().__init__(parent=None, title=title, style=wx.DEFAULT_FRAME_STYLE & ~wx.MAXIMIZE_BOX)
        self._owner = owner
        self._payload = payload

        self.SetMinSize((700, 320))
        self._build_ui()
        self._apply_preferred_size()
        self.CentreOnScreen()

        self.Bind(wx.EVT_CLOSE, self._on_close)

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)

        success = bool(self._payload.get("success"))
        output_path = self._existing_payload_path("output_file")
        mapping_path = self._existing_payload_path("mapping_file")
        if success:
            root.Add(wx.StaticText(panel, label="PyRefman finished successfully."), 0, wx.ALL, 16)

            if output_path is not None:
                self._add_path_row(panel, root, "Output file", output_path)
            else:
                no_output = wx.StaticText(
                    panel,
                    label="No output file was written. The formatted markdown is available in the preview tab.",
                )
                no_output.Wrap(620)
                root.Add(no_output, 0, wx.LEFT | wx.RIGHT | wx.TOP, 16)

            if mapping_path is not None:
                self._add_path_row(panel, root, "Mapping file", mapping_path)
        else:
            root.Add(wx.StaticText(panel, label="PyRefman exited with an error."), 0, wx.ALL, 16)

            error_box = wx.TextCtrl(
                panel,
                value=self._payload.get("error", "Unknown error."),
                style=wx.TE_MULTILINE | wx.TE_READONLY,
                size=(-1, 180),
            )
            self._owner._apply_system_text_colours(error_box)
            root.Add(error_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 16)

            error_hint = wx.StaticText(panel, label="The Status Log tab contains the full processing output.")
            error_hint.Wrap(620)
            root.Add(error_hint, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        actions.AddStretchSpacer()

        default_button: wx.Button | None = None
        if success and output_path is not None:
            open_output_button = wx.Button(panel, label="Open output file")
            open_output_button.Bind(wx.EVT_BUTTON, lambda _event, p=output_path: self._open_and_close(p))
            actions.Add(open_output_button, 0, wx.RIGHT, 8)
            default_button = open_output_button

        if success and mapping_path is not None:
            open_mapping_button = wx.Button(panel, label="Open mapping file")
            open_mapping_button.Bind(wx.EVT_BUTTON, lambda _event, p=mapping_path: self._open_and_close(p))
            actions.Add(open_mapping_button, 0, wx.RIGHT, 8)
            if default_button is None:
                default_button = open_mapping_button

        close_button = wx.Button(panel, label="Close")
        close_button.Bind(wx.EVT_BUTTON, self._on_close_button)
        actions.Add(close_button, 0)
        if default_button is not None:
            default_button.SetDefault()
        else:
            close_button.SetDefault()

        root.Add(actions, 0, wx.EXPAND | wx.ALL, 16)
        panel.SetSizer(root)
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizerAndFit(frame_sizer)

    def _add_path_row(self, parent: wx.Window, sizer: wx.BoxSizer, label_text: str, path: Path) -> None:
        row = wx.BoxSizer(wx.VERTICAL)
        row.Add(wx.StaticText(parent, label=label_text), 0, wx.BOTTOM, 4)
        path_ctrl = wx.TextCtrl(parent, value=str(path), style=wx.TE_READONLY | wx.TE_NOHIDESEL)
        path_ctrl.SetMinSize((460, -1))
        self._owner._apply_system_text_colours(path_ctrl)
        row.Add(path_ctrl, 0, wx.EXPAND)
        sizer.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 16)

    def _existing_payload_path(self, key: str) -> Path | None:
        raw_path = self._payload.get(key)
        if not raw_path:
            return None

        candidate = Path(raw_path)
        return candidate if candidate.exists() else None

    def _payload_paths(self) -> list[str]:
        paths: list[str] = []
        for key in ("output_file", "mapping_file"):
            existing_path = self._existing_payload_path(key)
            if existing_path is not None:
                paths.append(str(existing_path))
        return paths

    def _display_client_area(self) -> wx.Rect:
        display_index = wx.Display.GetFromWindow(self)
        if display_index != wx.NOT_FOUND:
            return wx.Display(display_index).GetClientArea()

        display_size = wx.GetDisplaySize()
        return wx.Rect(0, 0, display_size.width, display_size.height)

    def _preferred_width(self) -> int:
        client_area = self._display_client_area()
        max_width = max(700, client_area.width - 120)
        current_width = max(self.GetBestSize().width, self.GetSize().width, 700)

        path_texts = self._payload_paths()
        if not path_texts:
            return min(current_width, max_width)

        dc = wx.ScreenDC()
        dc.SetFont(self.GetFont())
        text_width = max(dc.GetTextExtent(path_text)[0] for path_text in path_texts)
        desired_width = text_width + 220
        return max(700, min(max_width, max(current_width, desired_width)))

    def _apply_preferred_size(self) -> None:
        current_size = self.GetSize()
        client_area = self._display_client_area()
        preferred_width = self._preferred_width()
        preferred_height = min(max(current_size.height, 320), max(320, client_area.height - 120))
        self.SetSize((preferred_width, preferred_height))
        self.Layout()

    def _close_owner_block(self) -> None:
        try:
            if self._owner and not self._owner.IsBeingDeleted():
                self._owner.Enable(True)
                self._owner._completion_frame = None
                self._owner.Raise()
        except RuntimeError:
            pass

    def _on_close_button(self, _event: wx.CommandEvent) -> None:
        self.Close()

    def _open_and_close(self, path: Path) -> None:
        self._owner._open_path(path)
        self.Close()

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._close_owner_block()
        event.Skip()

class PyRefmanFrame(wx.Frame):
    def __init__(self) -> None:
        downloads_dir = Path(get_downloads_dir())
        saved_state = self._load_state()
        initial_style = saved_state.get("reference_style")
        initial_output_format = saved_state.get("output_format", "markdown")
        saved_citations_dir = str(saved_state.get("citations_dir", "") or "").strip()
        self._pandoc_available = is_pandoc_available()
        self._output_format_choices = list(OUTPUT_FORMAT_CHOICES if self._pandoc_available else OUTPUT_FORMAT_CHOICES[:1])
        valid_output_formats = {value for value, _label in self._output_format_choices}
        if initial_style not in REFERENCE_STYLES:
            initial_style = REFERENCE_STYLES[0] if REFERENCE_STYLES else "VancouverStyle"
        if initial_output_format not in valid_output_formats:
            initial_output_format = "markdown"

        super().__init__(parent=None, title="PyRefman", size=(1080, 860))
        self.SetMinSize((480, 640))

        self._wrappable_labels: list[wx.StaticText] = []
        self._worker_thread: threading.Thread | None = None
        self._worker_process: subprocess.Popen[str] | None = None
        self._worker_args_file: Path | None = None
        self._worker_result_file: Path | None = None
        self._pending_run_notes: list[str] = []
        self._state_ready = False
        self._running = False
        self._abort_requested = False
        self._closing = False
        self._dark_mode_active = False

        self._progress_timer = wx.Timer(self)
        self._input_mode_buttons: dict[str, wx.RadioButton] = {}
        self._mapping_checkboxes: dict[str, wx.CheckBox] = {}
        self._appearance_sensitive_controls: list[wx.TextCtrl] = []
        self._completion_frame: CompletionFrame | None = None

        self._downloads_dir = downloads_dir
        self._default_citations_dir = str(downloads_dir / "Citations")
        self._initial_style = initial_style
        self._initial_output_format = initial_output_format
        self._build_ui()
        self._bind_events()

        self.output_enabled_checkbox.SetValue(True)
        self.input_file_ctrl.SetValue("")
        self.google_doc_ctrl.SetValue("")
        self.raw_text_ctrl.SetValue("")
        self.citations_dir_ctrl.SetHint(self._default_citations_dir)
        self.citations_dir_ctrl.SetValue(saved_citations_dir)
        self.mapping_enabled_checkbox.SetValue(bool(saved_state.get("mapping_enabled", False)))

        for option in MAPPING_COLUMN_OPTIONS:
            self._mapping_checkboxes[option.key].SetValue(option.key in DEFAULT_MAPPING_KEYS)

        if REFERENCE_STYLES:
            self.style_choice.SetStringSelection(self._initial_style)

        for index, (value, _label) in enumerate(self._output_format_choices):
            if value == self._initial_output_format:
                self.output_format_choice.SetSelection(index)
                break

        self._input_mode_buttons["file"].SetValue(True)
        self.output_file_ctrl.SetValue("")

        self._toggle_input_mode()
        self._toggle_output_widgets()
        self._toggle_mapping_widgets()
        self._refresh_output_file_hint()
        self._apply_system_appearance()
        self._update_style_preview()
        self._refresh_dynamic_labels()
        self._validate_form()
        self._state_ready = True

        self.CentreOnScreen()
        wx.CallAfter(self._rewrap_labels)
        wx.CallAfter(self._update_mapping_columns_layout)

    def _build_ui(self) -> None:
        root_panel = wx.Panel(self)
        self.root_panel = root_panel
        root_sizer = wx.BoxSizer(wx.VERTICAL)

        self.scroll_panel = scrolled.ScrolledPanel(root_panel, style=wx.TAB_TRAVERSAL | wx.VSCROLL)
        self.scroll_panel.SetAutoLayout(True)

        content_sizer = wx.BoxSizer(wx.VERTICAL)
        content_sizer.Add(self._build_source_section(), 0, wx.EXPAND | wx.ALL, 14)
        content_sizer.Add(self._build_output_section(), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        content_sizer.Add(self._build_style_section(), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        content_sizer.Add(self._build_run_section(), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        self.scroll_panel.SetSizer(content_sizer)
        self.scroll_panel.SetupScrolling(scroll_x=False, scrollToTop=False, scrollIntoView=False)

        status_panel = wx.Panel(root_panel)
        self.status_panel = status_panel
        status_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.status_label = self._make_wrapped_label(status_panel, self._idle_status_text())
        self.run_state_label = wx.StaticText(status_panel, label="Idle")
        self.progress_gauge = wx.Gauge(status_panel, range=100, size=(180, -1))
        status_sizer.Add(self.status_label, 1, wx.EXPAND | wx.ALL, 10)
        status_row = wx.BoxSizer(wx.HORIZONTAL)
        status_row.Add(self.progress_gauge, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        status_row.Add(self.run_state_label, 0, wx.ALIGN_CENTER_VERTICAL)
        status_sizer.Add(status_row, 0, wx.ALIGN_CENTER_VERTICAL | wx.TOP | wx.BOTTOM | wx.RIGHT, 10)
        status_panel.SetSizer(status_sizer)

        root_sizer.Add(self.scroll_panel, 1, wx.EXPAND)
        root_sizer.Add(wx.StaticLine(root_panel), 0, wx.EXPAND)
        root_sizer.Add(status_panel, 0, wx.EXPAND)
        root_panel.SetSizer(root_sizer)

        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(root_panel, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)

    def _build_source_section(self) -> wx.StaticBoxSizer:
        box = wx.StaticBox(self.scroll_panel, label="1. Choose the Source")
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)
        parent = box

        mode_row = wx.WrapSizer(wx.HORIZONTAL)
        for index, (value, label) in enumerate(INPUT_MODE_CHOICES):
            style = wx.RB_GROUP if index == 0 else 0
            button = wx.RadioButton(parent, label=label, style=style)
            self._input_mode_buttons[value] = button
            mode_row.Add(button, 0, wx.RIGHT, 18 if index < len(INPUT_MODE_CHOICES) - 1 else 0)
        sizer.Add(mode_row, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self.file_input_panel = wx.Panel(parent)
        file_sizer = wx.BoxSizer(wx.VERTICAL)
        file_row = wx.BoxSizer(wx.HORIZONTAL)
        self.input_file_ctrl = wx.TextCtrl(self.file_input_panel)
        self.input_file_ctrl.SetMinSize((1, -1))
        self.input_file_ctrl.SetHint("Choose a local document")
        self._appearance_sensitive_controls.append(self.input_file_ctrl)
        self.input_file_button = wx.Button(self.file_input_panel, label="Browse...")
        file_row.Add(self.input_file_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        file_row.Add(self.input_file_ctrl, 1, wx.EXPAND)
        file_sizer.Add(file_row, 0, wx.EXPAND)
        self.file_input_hint = self._make_wrapped_label(
            self.file_input_panel,
            self._file_input_hint_text(),
        )
        file_sizer.Add(self.file_input_hint, 0, wx.EXPAND | wx.TOP, 6)
        self.file_input_status = self._make_wrapped_label(self.file_input_panel, collapse_when_empty=True)
        file_sizer.Add(self.file_input_status, 0, wx.EXPAND | wx.TOP, 6)
        self.file_input_panel.SetSizer(file_sizer)
        sizer.Add(self.file_input_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.url_input_panel = wx.Panel(parent)
        url_sizer = wx.BoxSizer(wx.VERTICAL)
        self.google_doc_ctrl = wx.TextCtrl(self.url_input_panel)
        self.google_doc_ctrl.SetHint("https://docs.google.com/document/d/<id>/edit")
        self._appearance_sensitive_controls.append(self.google_doc_ctrl)
        url_sizer.Add(self.google_doc_ctrl, 0, wx.EXPAND)
        self.google_doc_hint = self._make_wrapped_label(
            self.url_input_panel,
            "PyRefman exports the document to Markdown before processing.",
        )
        url_sizer.Add(self.google_doc_hint, 0, wx.EXPAND | wx.TOP, 6)
        self.google_doc_status = self._make_wrapped_label(self.url_input_panel, collapse_when_empty=True)
        url_sizer.Add(self.google_doc_status, 0, wx.EXPAND | wx.TOP, 6)
        self.url_input_panel.SetSizer(url_sizer)
        sizer.Add(self.url_input_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.text_input_panel = wx.Panel(parent)
        text_sizer = wx.BoxSizer(wx.VERTICAL)
        text_sizer.Add(
            wx.StaticText(self.text_input_panel, label="Text content"),
            0,
            wx.BOTTOM,
            4,
        )
        self.raw_text_ctrl = wx.TextCtrl(
            self.text_input_panel,
            style=wx.TE_MULTILINE,
            size=(-1, 180),
        )
        self._appearance_sensitive_controls.append(self.raw_text_ctrl)
        text_sizer.Add(self.raw_text_ctrl, 1, wx.EXPAND)
        self.raw_text_hint = self._make_wrapped_label(
            self.text_input_panel,
            "Plain text and Markdown are accepted. Bare URLs will be converted automatically.",
        )
        text_sizer.Add(self.raw_text_hint, 0, wx.EXPAND | wx.TOP, 6)
        self.raw_text_status = self._make_wrapped_label(self.text_input_panel, collapse_when_empty=True)
        text_sizer.Add(self.raw_text_status, 0, wx.EXPAND | wx.TOP, 6)
        self.text_input_panel.SetSizer(text_sizer)
        sizer.Add(self.text_input_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        return sizer

    def _build_output_section(self) -> wx.StaticBoxSizer:
        box = wx.StaticBox(self.scroll_panel, label="2. Choose Output Locations")
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)
        parent = box

        self.output_enabled_checkbox = wx.CheckBox(parent, label="Save formatted output as a file")
        sizer.Add(self.output_enabled_checkbox, 0, wx.ALL, 10)

        format_row = wx.WrapSizer(wx.HORIZONTAL)
        format_row.Add(wx.StaticText(parent, label="Output format"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.output_format_choice = wx.Choice(parent, choices=[label for _value, label in self._output_format_choices])
        format_row.Add(self.output_format_choice, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(format_row, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.output_format_hint = self._make_wrapped_label(parent, collapse_when_empty=True)
        sizer.Add(self.output_format_hint, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)

        sizer.Add(wx.StaticText(parent, label="Formatted output file"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        output_row = wx.BoxSizer(wx.HORIZONTAL)
        self.output_file_ctrl = wx.TextCtrl(parent)
        self.output_file_ctrl.SetMinSize((1, -1))
        self._appearance_sensitive_controls.append(self.output_file_ctrl)
        self.output_file_button = wx.Button(parent, label="Save As...")
        output_row.Add(self.output_file_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        output_row.Add(self.output_file_ctrl, 1, wx.EXPAND)
        sizer.Add(output_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
        self.output_file_status = self._make_wrapped_label(parent, collapse_when_empty=True)
        sizer.Add(self.output_file_status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)

        sizer.Add(wx.StaticText(parent, label="Citation downloads folder"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        citations_row = wx.BoxSizer(wx.HORIZONTAL)
        self.citations_dir_ctrl = wx.TextCtrl(parent)
        self.citations_dir_ctrl.SetMinSize((1, -1))
        self._appearance_sensitive_controls.append(self.citations_dir_ctrl)
        self.citations_dir_button = wx.Button(parent, label="Browse...")
        citations_row.Add(self.citations_dir_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        citations_row.Add(self.citations_dir_ctrl, 1, wx.EXPAND)
        sizer.Add(citations_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
        self.citations_dir_status = self._make_wrapped_label(parent, collapse_when_empty=True)
        sizer.Add(self.citations_dir_status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)

        self.mapping_enabled_checkbox = wx.CheckBox(parent, label="Create a CSV mapping file")
        sizer.Add(self.mapping_enabled_checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.mapping_hint = self._make_wrapped_label(
            parent,
            "Useful when you need citation tracking for tables, figures, or other places where inline replacements are harder to review.",
        )
        sizer.Add(self.mapping_hint, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)

        self.mapping_details_panel = wx.Panel(parent)
        mapping_details_sizer = wx.BoxSizer(wx.VERTICAL)
        self.mapping_status = self._make_wrapped_label(self.mapping_details_panel, collapse_when_empty=True)
        mapping_details_sizer.Add(self.mapping_status, 0, wx.EXPAND | wx.TOP, 6)

        columns_label = wx.StaticText(self.mapping_details_panel, label="Mapping columns")
        mapping_details_sizer.Add(columns_label, 0, wx.TOP, 10)

        self.mapping_columns_panel = wx.Panel(self.mapping_details_panel)
        self.mapping_columns_sizer = wx.GridSizer(0, 2, 6, 12)
        for option in MAPPING_COLUMN_OPTIONS:
            checkbox = wx.CheckBox(
                self.mapping_columns_panel,
                label=f"{option.header} - {option.description}",
            )
            self._mapping_checkboxes[option.key] = checkbox
            self.mapping_columns_sizer.Add(checkbox, 0, wx.EXPAND)
        self.mapping_columns_panel.SetSizer(self.mapping_columns_sizer)
        mapping_details_sizer.Add(self.mapping_columns_panel, 0, wx.EXPAND | wx.TOP, 10)
        self.mapping_details_panel.SetSizer(mapping_details_sizer)
        sizer.Add(self.mapping_details_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        return sizer

    def _build_style_section(self) -> wx.StaticBoxSizer:
        box = wx.StaticBox(self.scroll_panel, label="3. Pick Reference Style")
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)
        parent = box

        style_row = wx.WrapSizer(wx.HORIZONTAL)
        style_row.Add(wx.StaticText(parent, label="Reference style"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.style_choice = wx.Choice(parent, choices=list(REFERENCE_STYLES))
        style_row.Add(self.style_choice, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(style_row, 0, wx.ALL, 10)

        self.style_description_label = self._make_wrapped_label(parent)
        sizer.Add(self.style_description_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        sizer.Add(wx.StaticText(parent, label="Style example output"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.style_preview_ctrl = wx.TextCtrl(
            parent,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            size=(-1, 180),
        )
        self._appearance_sensitive_controls.append(self.style_preview_ctrl)
        sizer.Add(self.style_preview_ctrl, 0, wx.EXPAND | wx.ALL, 10)

        return sizer

    def _build_run_section(self) -> wx.StaticBoxSizer:
        box = wx.StaticBox(self.scroll_panel, label="4. Run and Monitor Status")
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)
        parent = box

        controls = wx.WrapSizer(wx.HORIZONTAL)
        self.run_button = wx.Button(parent, label="Run PyRefman")
        controls.Add(self.run_button, 0, wx.RIGHT | wx.BOTTOM, 8)
        sizer.Add(controls, 0, wx.EXPAND | wx.ALL, 10)

        self.run_hint = self._make_wrapped_label(
            parent,
            "A browser window will open to download citations. Keep it open until PyRefman finishes, and complete any captcha or prompt if the site asks for one.",
        )
        sizer.Add(self.run_hint, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self.results_notebook = wx.Notebook(parent)

        log_panel = wx.Panel(self.results_notebook)
        log_sizer = wx.BoxSizer(wx.VERTICAL)
        self.log_ctrl = wx.TextCtrl(
            log_panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            size=(-1, 280),
        )
        self._appearance_sensitive_controls.append(self.log_ctrl)
        log_sizer.Add(self.log_ctrl, 1, wx.EXPAND | wx.ALL, 8)
        log_panel.SetSizer(log_sizer)
        self.results_notebook.AddPage(log_panel, "Status Log")

        preview_panel = wx.Panel(self.results_notebook)
        preview_sizer = wx.BoxSizer(wx.VERTICAL)
        self.preview_ctrl = wx.TextCtrl(
            preview_panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            size=(-1, 280),
        )
        self._appearance_sensitive_controls.append(self.preview_ctrl)
        preview_sizer.Add(self.preview_ctrl, 1, wx.EXPAND | wx.ALL, 8)
        preview_panel.SetSizer(preview_sizer)
        self.results_notebook.AddPage(preview_panel, "Markdown Preview")

        summary_panel = wx.Panel(self.results_notebook)
        summary_sizer = wx.BoxSizer(wx.VERTICAL)
        self.summary_ctrl = wx.TextCtrl(
            summary_panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_NOHIDESEL,
            size=(-1, 280),
        )
        self._appearance_sensitive_controls.append(self.summary_ctrl)
        self.summary_ctrl.Bind(wx.EVT_SET_FOCUS, self._on_summary_focus)
        summary_sizer.Add(self.summary_ctrl, 1, wx.EXPAND | wx.ALL, 8)
        summary_panel.SetSizer(summary_sizer)
        self.results_notebook.AddPage(summary_panel, "Reference Summary")

        sizer.Add(self.results_notebook, 1, wx.EXPAND | wx.ALL, 10)

        return sizer

    def _bind_events(self) -> None:
        for button in self._input_mode_buttons.values():
            button.Bind(wx.EVT_RADIOBUTTON, self._on_input_mode_changed)

        self.input_file_ctrl.Bind(wx.EVT_TEXT, self._on_path_related_change)
        self.google_doc_ctrl.Bind(wx.EVT_TEXT, self._on_google_doc_changed)
        self.raw_text_ctrl.Bind(wx.EVT_TEXT, self._on_raw_text_changed)
        self.output_enabled_checkbox.Bind(wx.EVT_CHECKBOX, self._on_output_toggle_changed)
        self.output_format_choice.Bind(wx.EVT_CHOICE, self._on_output_format_changed)
        self.output_file_ctrl.Bind(wx.EVT_TEXT, self._on_path_related_change)
        self.citations_dir_ctrl.Bind(wx.EVT_TEXT, self._on_citations_dir_changed)
        self.mapping_enabled_checkbox.Bind(wx.EVT_CHECKBOX, self._on_mapping_toggle_changed)
        self.style_choice.Bind(wx.EVT_CHOICE, self._on_reference_style_changed)

        for checkbox in self._mapping_checkboxes.values():
            checkbox.Bind(wx.EVT_CHECKBOX, self._on_mapping_columns_changed)

        self.input_file_button.Bind(wx.EVT_BUTTON, self._browse_input_file)
        self.output_file_button.Bind(wx.EVT_BUTTON, self._browse_output_file)
        self.citations_dir_button.Bind(wx.EVT_BUTTON, self._browse_citations_dir)
        self.run_button.Bind(wx.EVT_BUTTON, self._on_run_button)

        self.Bind(wx.EVT_TIMER, self._on_progress_timer, self._progress_timer)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_SYS_COLOUR_CHANGED, self._on_system_colours_changed)
        self.Bind(wx.EVT_SIZE, self._on_frame_resize)

    def _make_wrapped_label(
        self,
        parent: wx.Window,
        text: str = "",
        collapse_when_empty: bool = False,
    ) -> wx.StaticText:
        label = wx.StaticText(parent, label=text)
        label._wrap_source_text = text or ""
        label._collapse_when_empty = collapse_when_empty
        if collapse_when_empty and not text:
            label.Hide()
        self._wrappable_labels.append(label)
        return label

    def _set_wrapped_label(self, label: wx.StaticText, text: str) -> None:
        label._wrap_source_text = text or ""
        label.SetLabel(text or "")
        collapse_when_empty = bool(getattr(label, "_collapse_when_empty", False))
        label.Show(bool(text) or not collapse_when_empty)
        self._rewrap_labels()

    def _rewrap_labels(self) -> None:
        valid_labels: list[wx.StaticText] = []
        for label in self._wrappable_labels:
            try:
                if not label or label.IsBeingDeleted():
                    continue
                if not label.IsShown():
                    valid_labels.append(label)
                    continue
                source_text = getattr(label, "_wrap_source_text", label.GetLabel())
                label.SetLabel(source_text)
                parent_width = label.GetParent().GetClientSize().width
                if hasattr(self, "status_label") and label is self.status_label and hasattr(self, "status_panel"):
                    reserved_width = self.progress_gauge.GetBestSize().width + self.run_state_label.GetBestSize().width + 56
                    width = max(self.status_panel.GetClientSize().width - reserved_width, 120)
                else:
                    width = max(parent_width - 24, 120)
                label.Wrap(width)
                valid_labels.append(label)
            except RuntimeError:
                continue
        self._wrappable_labels = valid_labels
        self.scroll_panel.Layout()
        self.scroll_panel.FitInside()

        if hasattr(self, "status_panel"):
            self.status_panel.Layout()
        if hasattr(self, "root_panel"):
            self.root_panel.Layout()
        self.Layout()

    @staticmethod
    def _idle_status_text() -> str:
        return f"PyRefman version {PYREFMAN_VERSION}"

    def _set_status_text(self, text: str) -> None:
        normalized_text = re.sub(r"\s+", " ", str(text or "").strip())
        self.status_label._wrap_source_text = normalized_text
        self.status_label.SetLabel(normalized_text)
        self._rewrap_labels()

    @staticmethod
    def _hide_text_caret(control: wx.TextCtrl) -> None:
        hide_native_caret = getattr(control, "HideNativeCaret", None)
        if callable(hide_native_caret):
            try:
                hide_native_caret()
            except Exception:
                pass

    def _get_input_mode(self) -> str:
        for value, _label in INPUT_MODE_CHOICES:
            if self._input_mode_buttons[value].GetValue():
                return value
        return "file"

    def _get_output_format(self) -> str:
        selection = self.output_format_choice.GetSelection()
        if selection == wx.NOT_FOUND:
            return "markdown"
        return self._output_format_choices[selection][0]

    def _get_output_extension(self) -> str:
        return OUTPUT_FORMAT_EXTENSIONS[self._get_output_format()]

    def _get_allowed_output_suffixes(self) -> set[str]:
        return OUTPUT_FORMAT_ALLOWED_SUFFIXES[self._get_output_format()]

    def _normalize_output_path_for_format(self, path: Path) -> Path:
        return path.with_suffix(self._get_output_extension())

    def _default_output_name(self) -> str:
        return self._default_output_path().name

    def _refresh_output_file_hint(self) -> None:
        self.output_file_ctrl.SetHint(self._default_output_name())

    @staticmethod
    def _is_markdown_path(path: Path | None) -> bool:
        if path is None:
            return False
        return path.suffix.lower() in {".md", ".markdown"}

    @staticmethod
    def _is_text_path(path: Path | None) -> bool:
        if path is None:
            return False
        return path.suffix.lower() == ".txt"

    def _file_input_hint_text(self) -> str:
        if self._pandoc_available:
            return "Choose any local document that Pandoc can read."
        return "Choose a local Markdown or text file. Other document types require Pandoc, which is not available."

    def _output_format_hint_text(self) -> str:
        if self._pandoc_available:
            return ""
        return "Pandoc is not available, so Word (.docx) export is disabled and output is fixed to Markdown."

    @staticmethod
    def _missing_pandoc_input_message() -> str:
        return (
            "This file type requires Pandoc. Use a Markdown or text file, "
            "or repair the local Pandoc download."
        )

    def _update_mapping_columns_layout(self) -> None:
        if not hasattr(self, "mapping_columns_sizer"):
            return
        if hasattr(self, "mapping_details_panel") and not self.mapping_details_panel.IsShown():
            return

        available_width = self.mapping_columns_panel.GetClientSize().width
        columns = 1 if available_width and available_width < 760 else 2
        if self.mapping_columns_sizer.GetCols() != columns:
            self.mapping_columns_sizer.SetCols(columns)
            self.mapping_columns_panel.Layout()
            self.scroll_panel.Layout()
            self.scroll_panel.FitInside()

    @staticmethod
    def _get_system_appearance():
        get_appearance = getattr(wx.SystemSettings, "GetAppearance", None)
        if get_appearance is None:
            return None
        try:
            return get_appearance()
        except Exception:
            return None

    def _apply_system_text_colours(self, control: wx.TextCtrl) -> None:
        appearance = self._get_system_appearance()
        if appearance is None:
            return

        control.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
        control.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT))

    def _apply_system_appearance(self) -> None:
        appearance = self._get_system_appearance()
        self._dark_mode_active = bool(appearance and appearance.IsDark())

        for control in self._appearance_sensitive_controls:
            if control and not control.IsBeingDeleted():
                self._apply_system_text_colours(control)
                control.Refresh()

        if hasattr(self, "summary_ctrl") and self.summary_ctrl and not self.summary_ctrl.IsBeingDeleted():
            self._hide_text_caret(self.summary_ctrl)

        self.Refresh()

    def _on_system_colours_changed(self, event: wx.SysColourChangedEvent) -> None:
        event.Skip()
        self._apply_system_appearance()

    def _on_frame_resize(self, event: wx.SizeEvent) -> None:
        event.Skip()
        wx.CallAfter(self._rewrap_labels)
        wx.CallAfter(self._update_mapping_columns_layout)

    def _on_progress_timer(self, _event: wx.TimerEvent) -> None:
        if self._running:
            self.progress_gauge.Pulse()

    def _on_summary_focus(self, event: wx.FocusEvent) -> None:
        self._hide_text_caret(self.summary_ctrl)
        event.Skip()

    def _on_run_button(self, _event: wx.CommandEvent | None = None) -> None:
        if self._running:
            self._request_abort()
        else:
            self._start_processing()

    def _on_input_mode_changed(self, _event: wx.CommandEvent | None = None) -> None:
        self._toggle_input_mode()
        self._refresh_dynamic_labels()
        self._validate_form()

    def _on_output_toggle_changed(self, _event: wx.CommandEvent | None = None) -> None:
        self._toggle_output_widgets()
        self._refresh_dynamic_labels()
        self._validate_form()

    def _on_output_format_changed(self, _event: wx.CommandEvent | None = None) -> None:
        output_text = self.output_file_ctrl.GetValue().strip()
        if output_text:
            output_path, output_error = self._validate_native_path_text(output_text)
            if output_path and not output_error:
                self.output_file_ctrl.ChangeValue(str(self._normalize_output_path_for_format(output_path)))

        self._refresh_output_file_hint()
        self._refresh_dynamic_labels()
        self._validate_form()
        self._save_state()

    def _on_google_doc_changed(self, _event: wx.CommandEvent | None = None) -> None:
        self._refresh_dynamic_labels()
        self._validate_form()

    def _on_mapping_toggle_changed(self, _event: wx.CommandEvent | None = None) -> None:
        self._toggle_mapping_widgets()
        self._refresh_dynamic_labels()
        self._validate_form()
        self._save_state()

    def _on_mapping_columns_changed(self, _event: wx.CommandEvent | None = None) -> None:
        self._validate_form()

    def _on_reference_style_changed(self, _event: wx.CommandEvent | None = None) -> None:
        self._update_style_preview()
        self._refresh_dynamic_labels()
        self._save_state()

    def _on_path_related_change(self, _event: wx.CommandEvent | None = None) -> None:
        self._refresh_output_file_hint()
        self._refresh_dynamic_labels()
        self._validate_form()

    def _on_citations_dir_changed(self, _event: wx.CommandEvent | None = None) -> None:
        self._refresh_dynamic_labels()
        self._validate_form()
        self._save_state()

    def _on_raw_text_changed(self, _event: wx.CommandEvent | None = None) -> None:
        self._refresh_dynamic_labels()
        self._validate_form()

    def _toggle_input_mode(self) -> None:
        selected = self._get_input_mode()
        self.file_input_panel.Show(selected == "file")
        self.url_input_panel.Show(selected == "google_doc")
        self.text_input_panel.Show(selected == "raw_text")

        self._refresh_output_file_hint()
        self.scroll_panel.Layout()
        self.scroll_panel.FitInside()

    def _toggle_output_widgets(self) -> None:
        enabled = self.output_enabled_checkbox.GetValue()
        self.output_format_choice.Enable(enabled and len(self._output_format_choices) > 1)
        self.output_file_ctrl.Enable(enabled)
        self.output_file_button.Enable(enabled)
        self._toggle_mapping_widgets()

    def _toggle_mapping_widgets(self) -> None:
        checkbox_enabled = self.output_enabled_checkbox.GetValue()
        self.mapping_enabled_checkbox.Enable(checkbox_enabled)

        enabled = checkbox_enabled and self.mapping_enabled_checkbox.GetValue()
        self.mapping_details_panel.Show(enabled)
        self.mapping_columns_panel.Enable(enabled)
        for checkbox in self._mapping_checkboxes.values():
            checkbox.Enable(enabled)

        self.scroll_panel.Layout()
        self.scroll_panel.FitInside()
        wx.CallAfter(self._update_mapping_columns_layout)

    def _sync_run_controls(self) -> None:
        if self._running:
            self.run_button.SetLabel("Stopping..." if self._abort_requested else "Stop")
            self.run_button.Enable(not self._abort_requested)
            return

        self.run_button.SetLabel("Run PyRefman")

    @staticmethod
    def _normalize_path_text(value: str) -> str:
        normalized_path = normalize_user_path(value)
        return str(normalized_path) if normalized_path else ""

    @staticmethod
    def _is_standard_google_doc_url(value: str) -> bool:
        return bool(STANDARD_GOOGLE_DOC_URL_RE.match(strip_wrapping_quotes(value or "")))

    @staticmethod
    def _example_native_path() -> str:
        if sys.platform.startswith("win"):
            return r"C:\Users\name\Documents\file.docx"
        if sys.platform == "darwin":
            return "/Users/name/Documents/file.docx"
        return "/home/name/file.docx"

    def _validate_native_path_text(self, value: str) -> tuple[Path | None, str | None]:
        raw_text = strip_wrapping_quotes(value or "")
        if not raw_text:
            return None, None

        path = normalize_user_path(raw_text)
        if path is None:
            return None, "Path is empty."

        if not path.is_absolute():
            return (
                None,
                "Path must be an absolute local path for this operating system. "
                f"Example: {self._example_native_path()}",
            )

        return path, None

    def _validate_output_path_text(self) -> tuple[Path | None, str | None]:
        if not self.output_file_ctrl.GetValue().strip():
            return None, None

        output_path, output_error = self._validate_native_path_text(self.output_file_ctrl.GetValue())
        if output_error or output_path is None:
            return output_path, output_error

        allowed_suffixes = self._get_allowed_output_suffixes()
        if output_path.suffix.lower() not in allowed_suffixes:
            expected_suffix = self._get_output_extension()
            return output_path, f"Output file must end with {expected_suffix} for the selected output format."

        return output_path, None

    def _load_state(self) -> dict:
        if not STATE_FILE.exists():
            return {}

        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self) -> None:
        if not self._state_ready:
            return

        state = {
            "citations_dir": self._normalize_path_text(self.citations_dir_ctrl.GetValue()),
            "output_format": self._get_output_format(),
            "reference_style": self.style_choice.GetStringSelection(),
            "mapping_enabled": bool(self.mapping_enabled_checkbox.GetValue()),
        }

        try:
            STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._closing = True
        if self._running:
            self._terminate_worker_process()
        if self._completion_frame is not None and not self._completion_frame.IsBeingDeleted():
            self._completion_frame.Destroy()
        self._save_state()
        event.Skip()

    def _build_sample_inline_reference(
        self,
        inline_index: int,
        pmid: str,
        title: str,
        authors: list[str],
        journal: str,
        publication_date: str,
        volume: str,
        issue: str,
        doi_suffix: str,
        pages: str,
    ) -> InlineReference:
        inline_reference = InlineReference(f"[Sample {inline_index}](https://pubmed.ncbi.nlm.nih.gov/{pmid}/)")
        inline_reference.inline_index = inline_index
        inline_reference.parsed_nbib = {
            "FAU": authors,
            "TI": title,
            "TA": journal,
            "DP": publication_date,
            "VI": volume,
            "IP": issue,
            "PG": pages,
            "AID": [f"10.1000/{doi_suffix} [doi]"],
            "PMID": pmid,
        }
        return inline_reference

    def _build_style_preview_text(self, style_name: str) -> str:
        try:
            style = init_reference_style_class(style_name)
            sample_references = [
                self._build_sample_inline_reference(
                    1,
                    "41000001",
                    "Arctic cytokine profiling during respiratory recovery.",
                    ["Okafor, Amaka N"],
                    "Glob Health Immunol",
                    "2024 Jan",
                    "12",
                    "1",
                    "pyrefman.1",
                    "11-19",
                ),
                self._build_sample_inline_reference(
                    2,
                    "41000002",
                    "Mangrove lipid signaling across coastal injury models.",
                    [
                        "Rahman, Farid U",
                        "Santos, Camila P",
                        "Nakamura, Emi K",
                    ],
                    "Transl Syst Biol",
                    "2023 Apr",
                    "8",
                    "2",
                    "pyrefman.2",
                    "77-89",
                ),
                self._build_sample_inline_reference(
                    3,
                    "41000003",
                    "Cross-continental atlas of stromal repair after inflammation.",
                    [
                        "Haddad, Omar J",
                        "Kim, Min Seo",
                        "Singh, Priya R",
                        "Fernandez, Sofia L",
                        "Mensah, Kojo A",
                        "Kowalski, Marta E",
                        "Al-Hassan, Layla M",
                        "Tanaka, Ren I",
                        "Ndlovu, Thabo S",
                        "Muller, Anika V",
                    ],
                    "Cell Repair Netw",
                    "2025 Feb",
                    "15",
                    "4",
                    "pyrefman.3",
                    "201-219",
                ),
                self._build_sample_inline_reference(
                    4,
                    "41000004",
                    "Adaptive fibroblast states in desert wound healing.",
                    [
                        "Ben Youssef, Nadia A",
                        "Garcia, Mateo J",
                    ],
                    "J Tissue Adapt",
                    "2022 Sep",
                    "6",
                    "3",
                    "pyrefman.4",
                    "131-142",
                ),
            ]

            formatted_references = []
            for inline_reference in sample_references:
                formatted_reference = style.format_reference(inline_reference)
                if formatted_reference is None:
                    continue
                formatted_reference.inline_reference = inline_reference
                formatted_references.append(formatted_reference)

            if not formatted_references:
                return "Preview unavailable for this style."

            inline_example = formatted_references[0].inline or "(no inline example available)"
            grouped_example = style.format_grouped_inline_references(formatted_references)
            sorted_references = [
                formatted_reference.full
                for formatted_reference in style.sort_formatted_references(formatted_references)
                if formatted_reference.full
            ]

            preview_lines = [
                "Inline citation example:",
                inline_example,
                "",
                "Grouped citation example:",
                grouped_example,
                "",
                "Reference list example:",
            ]

            if sorted_references:
                preview_lines.extend(sorted_references)
            else:
                preview_lines.append("(This style mainly changes inline citation output.)")

            return "\n".join(preview_lines)
        except Exception as exc:
            return f"Preview unavailable for {style_name}.\n{exc}"

    def _update_style_preview(self) -> None:
        style_name = self.style_choice.GetStringSelection()
        style = init_reference_style_class(style_name)
        self._set_wrapped_label(self.style_description_label, style.describe_style())
        self._replace_text(self.style_preview_ctrl, self._build_style_preview_text(style_name))

    def _default_output_path(self) -> Path:
        input_path = normalize_user_path(self.input_file_ctrl.GetValue())
        if self._get_input_mode() == "file" and input_path:
            return get_output_file_path(input_path, self._get_output_format())
        return self._downloads_dir / f"{DEFAULT_OUTPUT_BASENAME}{self._get_output_extension()}"

    def _effective_output_path(self) -> Path:
        output_path = normalize_user_path(self.output_file_ctrl.GetValue())
        if output_path is None:
            return self._default_output_path()
        return output_path

    def _effective_mapping_path(self) -> Path:
        output_path = self._effective_output_path()
        return output_path.with_name(f"{output_path.stem}{DEFAULT_MAPPING_SUFFIX}")

    def _refresh_dynamic_labels(self) -> None:
        self._update_input_file_status()
        self._update_google_doc_status()
        self._update_raw_text_status()
        self._update_output_format_status()
        self._update_output_file_status()
        self._update_citations_dir_status()
        self._update_mapping_info_status()

    def _update_input_file_status(self) -> None:
        path_text = self.input_file_ctrl.GetValue().strip()
        path, error = self._validate_native_path_text(path_text)

        if not path_text:
            self._set_wrapped_label(self.file_input_status, "")
        elif error:
            self._set_wrapped_label(self.file_input_status, error)
        elif path and path.exists() and path.is_file():
            if input_file_requires_pandoc(path) and not self._pandoc_available:
                self._set_wrapped_label(self.file_input_status, self._missing_pandoc_input_message())
            elif self._is_markdown_path(path):
                self._set_wrapped_label(self.file_input_status, "")
            elif self._is_text_path(path):
                self._set_wrapped_label(
                    self.file_input_status,
                    "Plain text files are processed directly. Bare URLs will be converted to Markdown links.",
                )
            else:
                self._set_wrapped_label(
                    self.file_input_status,
                    "The selected document will be converted to markdown for processing.",
                )
        else:
            self._set_wrapped_label(self.file_input_status, "Input file not found.")

    def _update_output_format_status(self) -> None:
        self._set_wrapped_label(self.output_format_hint, self._output_format_hint_text())

    def _update_google_doc_status(self) -> None:
        url = strip_wrapping_quotes(self.google_doc_ctrl.GetValue())
        if not url:
            self._set_wrapped_label(self.google_doc_status, "")
        elif self._is_standard_google_doc_url(url):
            self._set_wrapped_label(self.google_doc_status, "")
        else:
            self._set_wrapped_label(
                self.google_doc_status,
                "Use a standard Google Doc URL such as https://docs.google.com/document/d/<id>/edit.",
            )

    def _update_raw_text_status(self) -> None:
        raw_text = self.raw_text_ctrl.GetValue().strip()
        if not raw_text:
            self._set_wrapped_label(self.raw_text_status, "")
        elif has_markdown_hyperlinks(raw_text):
            self._set_wrapped_label(self.raw_text_status, "")
        else:
            converted_text = convert_plain_text_urls_to_markdown(raw_text)
            if converted_text != raw_text:
                self._set_wrapped_label(
                    self.raw_text_status,
                    "Bare URLs will be converted to Markdown links before processing.",
                )
            else:
                self._set_wrapped_label(self.raw_text_status, "No URLs detected yet.")

    def _update_output_file_status(self) -> None:
        output_text = self.output_file_ctrl.GetValue().strip()
        _path, error = self._validate_output_path_text()

        if not self.output_enabled_checkbox.GetValue():
            self._set_wrapped_label(
                self.output_file_status,
                "Formatted output will stay in the markdown preview tab only.",
            )
        elif not output_text:
            self._set_wrapped_label(
                self.output_file_status,
                f"If left blank, output will be saved as {self._default_output_path()}",
            )
        elif error:
            self._set_wrapped_label(self.output_file_status, error)
        else:
            if self._get_output_format() == "docx":
                self._set_wrapped_label(
                    self.output_file_status,
                    "PyRefman will save a .docx file and keep the markdown preview in the preview tab.",
                )
            else:
                self._set_wrapped_label(self.output_file_status, "")

    def _update_citations_dir_status(self) -> None:
        citations_dir_text = self.citations_dir_ctrl.GetValue().strip()
        citations_dir, error = self._validate_native_path_text(citations_dir_text)

        if not citations_dir_text:
            self._set_wrapped_label(
                self.citations_dir_status,
                f"If left blank, citations will be downloaded to {self._default_citations_dir}",
            )
        elif error:
            self._set_wrapped_label(self.citations_dir_status, error)
        elif citations_dir and citations_dir.exists():
            self._set_wrapped_label(self.citations_dir_status, "")
        else:
            self._set_wrapped_label(
                self.citations_dir_status,
                "Citations directory does not exist yet. It will be created during processing.",
            )

    def _update_mapping_info_status(self) -> None:
        if not self.output_enabled_checkbox.GetValue():
            self._set_wrapped_label(
                self.mapping_status,
                'Enable "Save formatted output as a file" to create a mapping file.',
            )
        elif not self.mapping_enabled_checkbox.GetValue():
            self._set_wrapped_label(self.mapping_status, "")
        else:
            output_path, output_error = self._validate_output_path_text()
            if output_error:
                self._set_wrapped_label(
                    self.mapping_status,
                    "Mapping file creation requires a valid absolute output path.",
                )
            else:
                if output_path is None:
                    output_path = self._default_output_path()
                mapping_path = output_path.with_name(f"{output_path.stem}{DEFAULT_MAPPING_SUFFIX}")
                self._set_wrapped_label(self.mapping_status, f"Mapping file will be saved to {mapping_path}")

    def _validate_form(self) -> None:
        self._sync_run_controls()

        if self._running:
            return

        can_run = False
        input_mode = self._get_input_mode()
        citations_dir, citations_dir_error = self._validate_native_path_text(self.citations_dir_ctrl.GetValue())
        has_valid_citations_dir = citations_dir_error is None
        has_valid_output_path = True

        if self.output_enabled_checkbox.GetValue():
            output_path, output_error = self._validate_output_path_text()
            has_valid_output_path = output_error is None

        if input_mode == "file":
            input_path, input_error = self._validate_native_path_text(self.input_file_ctrl.GetValue())
            can_run = bool(input_path and not input_error and input_path.exists() and input_path.is_file())
            if can_run and input_file_requires_pandoc(input_path) and not self._pandoc_available:
                can_run = False
        elif input_mode == "google_doc":
            can_run = self._is_standard_google_doc_url(self.google_doc_ctrl.GetValue())
        elif input_mode == "raw_text":
            can_run = bool(self.raw_text_ctrl.GetValue().strip())

        if self.mapping_enabled_checkbox.GetValue() and self.output_enabled_checkbox.GetValue():
            can_run = can_run and any(checkbox.GetValue() for checkbox in self._mapping_checkboxes.values())

        can_run = can_run and has_valid_citations_dir and has_valid_output_path
        self.run_button.Enable(can_run)

    def _prepare_raw_input_text(self) -> tuple[str, bool]:
        raw_text = self.raw_text_ctrl.GetValue().strip()
        if not raw_text:
            raise ValueError("Paste plain text or Markdown in step 1.")

        if has_markdown_hyperlinks(raw_text):
            return raw_text, False

        converted_text = convert_plain_text_urls_to_markdown(raw_text)
        return converted_text, converted_text != raw_text

    def _browse_input_file(self, _event: wx.CommandEvent) -> None:
        dialog = wx.FileDialog(
            self,
            message="Choose an input document",
            wildcard="All files (*.*)|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return

            self.input_file_ctrl.SetValue(self._normalize_path_text(dialog.GetPath()))
            self._refresh_output_file_hint()
        finally:
            dialog.Destroy()

    def _browse_output_file(self, _event: wx.CommandEvent) -> None:
        current_output, current_output_error = self._validate_native_path_text(self.output_file_ctrl.GetValue())
        initial_dir = (
            str(current_output.parent)
            if current_output and not current_output_error
            else str(self._default_output_path().parent)
        )

        output_format = self._get_output_format()
        if output_format == "docx":
            dialog_message = "Save formatted Word document as"
            wildcard = "Word documents (*.docx)|*.docx|All files (*.*)|*.*"
        else:
            dialog_message = "Save formatted Markdown as"
            wildcard = "Markdown files (*.md;*.markdown)|*.md;*.markdown|All files (*.*)|*.*"

        dialog = wx.FileDialog(
            self,
            message=dialog_message,
            defaultDir=initial_dir,
            defaultFile=self._default_output_name(),
            wildcard=wildcard,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        try:
            if dialog.ShowModal() == wx.ID_OK:
                selected_path = normalize_user_path(dialog.GetPath())
                if selected_path is not None:
                    selected_path = self._normalize_output_path_for_format(selected_path)
                self.output_file_ctrl.SetValue(str(selected_path) if selected_path else self._normalize_path_text(dialog.GetPath()))
        finally:
            dialog.Destroy()

    def _browse_citations_dir(self, _event: wx.CommandEvent) -> None:
        current_dir, current_dir_error = self._validate_native_path_text(self.citations_dir_ctrl.GetValue())
        initial_dir = str(current_dir) if current_dir and not current_dir_error else str(Path(self._default_citations_dir).parent)

        dialog = wx.DirDialog(
            self,
            message="Choose the citations folder",
            defaultPath=initial_dir,
        )
        try:
            if dialog.ShowModal() == wx.ID_OK:
                self.citations_dir_ctrl.SetValue(self._normalize_path_text(dialog.GetPath()))
        finally:
            dialog.Destroy()

    def _clear_log(self, _event: wx.CommandEvent | None = None) -> None:
        self._replace_text(self.log_ctrl, "")
        self._replace_text(self.preview_ctrl, "")
        self._replace_text(self.summary_ctrl, "")
        if not self._running:
            self._set_status_text(self._idle_status_text())
            self.run_state_label.SetLabel("Idle")
            self.progress_gauge.SetValue(0)

    def _append_log_line(self, text: str) -> None:
        if not text:
            return
        self.log_ctrl.AppendText(text + os.linesep)

    @staticmethod
    def _replace_text(widget: wx.TextCtrl, text: str) -> None:
        widget.SetValue(text or "")

    def _selected_mapping_column_keys(self) -> list[str]:
        return [
            option.key
            for option in MAPPING_COLUMN_OPTIONS
            if self._mapping_checkboxes[option.key].GetValue()
        ]

    def _resolve_result_output_path(self, args: dict) -> Path | None:
        if not args.get("save_output"):
            return None

        output_file = args.get("output_file")
        if output_file:
            return Path(output_file)

        input_source = args.get("input_source")
        output_format = args.get("output_format", "markdown")
        input_path = normalize_user_path(input_source)
        if input_path and input_path.exists():
            return get_output_file_path(input_path, output_format)

        return self._downloads_dir / f"{DEFAULT_OUTPUT_BASENAME}{OUTPUT_FORMAT_EXTENSIONS.get(output_format, '.md')}"

    def _collect_arguments(self) -> dict:
        input_mode = self._get_input_mode()
        self._pending_run_notes = []

        if input_mode == "file":
            input_source, input_error = self._validate_native_path_text(self.input_file_ctrl.GetValue())
            if input_source:
                self.input_file_ctrl.SetValue(str(input_source))
            if not input_source:
                raise ValueError("Choose a document file in step 1.")
            if input_error:
                raise ValueError(input_error)
            if not input_source.exists():
                raise ValueError(f"The selected input file does not exist at {input_source}")
            if input_file_requires_pandoc(input_source) and not self._pandoc_available:
                raise ValueError(self._missing_pandoc_input_message())
        elif input_mode == "google_doc":
            input_source = strip_wrapping_quotes(self.google_doc_ctrl.GetValue())
            self.google_doc_ctrl.SetValue(input_source)
            if not input_source:
                raise ValueError("Paste a standard Google Doc URL in step 1.")
            if not self._is_standard_google_doc_url(input_source):
                raise ValueError("Use a standard Google Doc URL such as https://docs.google.com/document/d/<id>/edit.")
        else:
            input_source, converted_plain_text = self._prepare_raw_input_text()
            if converted_plain_text:
                self._pending_run_notes.append(
                    "Detected plain text input. Converted URLs to Markdown links before sending the text to PyRefman."
                )

        output_file = None
        if self.output_enabled_checkbox.GetValue():
            output_file, output_error = self._validate_output_path_text()
            if output_error:
                raise ValueError(output_error)
            if output_file is not None:
                output_file = self._normalize_output_path_for_format(output_file)
                self.output_file_ctrl.SetValue(str(output_file))

        citations_dir_text = self.citations_dir_ctrl.GetValue().strip()
        citations_dir, citations_dir_error = self._validate_native_path_text(citations_dir_text)
        if citations_dir_error:
            raise ValueError(citations_dir_error)
        if citations_dir is None:
            citations_dir = Path(self._default_citations_dir)
        elif citations_dir_text:
            self.citations_dir_ctrl.SetValue(str(citations_dir))

        mapping_file = None
        mapping_column_keys = None
        if self.mapping_enabled_checkbox.GetValue() and self.output_enabled_checkbox.GetValue():
            mapping_file = self._effective_mapping_path()
            mapping_column_keys = self._selected_mapping_column_keys()
            if not mapping_column_keys:
                raise ValueError("Select at least one mapping column in step 2.")

        self._save_state()

        return {
            "input_source": input_source,
            "output_file": output_file,
            "citations_dir": citations_dir,
            "mapping_file": mapping_file,
            "reference_style": self.style_choice.GetStringSelection(),
            "mapping_column_keys": mapping_column_keys,
            "save_output": self.output_enabled_checkbox.GetValue(),
            "output_format": self._get_output_format(),
            "_ui_input_mode": input_mode,
        }

    def _start_processing(self, _event: wx.CommandEvent | None = None) -> None:
        if self._worker_process is not None:
            wx.MessageBox("PyRefman is already running.", "PyRefman", wx.OK | wx.ICON_INFORMATION, parent=self)
            return

        try:
            args = self._collect_arguments()
        except ValueError as exc:
            wx.MessageBox(str(exc), "PyRefman", wx.OK | wx.ICON_ERROR, parent=self)
            return

        self._running = True
        self._abort_requested = False
        self._clear_log()
        self._append_log_line("Starting PyRefman...")
        for note in self._pending_run_notes:
            self._append_log_line(note)
        self._append_log_line("The browser will open visibly for citation downloads.")
        self._set_status_text("Preparing citation processing...")
        self.run_state_label.SetLabel("Running")
        self.progress_gauge.SetValue(0)
        self._progress_timer.Start(100)
        self.results_notebook.SetSelection(0)
        try:
            process = self._spawn_worker_process(args)
        except Exception as exc:
            self._running = False
            self._abort_requested = False
            self._progress_timer.Stop()
            self.progress_gauge.SetValue(0)
            self._cleanup_worker_artifacts()
            self._validate_form()
            wx.MessageBox(f"Could not start PyRefman.\n{exc}", "PyRefman", wx.OK | wx.ICON_ERROR, parent=self)
            return

        self._worker_process = process
        self._validate_form()
        self._worker_thread = threading.Thread(target=self._monitor_worker_process, args=(process, args), daemon=True)
        self._worker_thread.start()

    def _request_abort(self) -> None:
        if not self._running or self._abort_requested:
            return

        self._abort_requested = True
        self._append_log_line("Abort requested by user.")
        self._set_status_text("Operation aborted by user")
        self.run_state_label.SetLabel("Aborted")
        self._validate_form()
        self._terminate_worker_process()

    def _post_to_ui(self, callback: Callable, *args) -> None:
        if self._closing:
            return
        wx.CallAfter(callback, *args)

    @staticmethod
    def _serialize_worker_args(args: dict) -> dict:
        serializable: dict = {}
        for key, value in args.items():
            if isinstance(value, Path):
                serializable[key] = str(value)
            elif isinstance(value, (str, bool)) or value is None:
                serializable[key] = value
            elif isinstance(value, list):
                serializable[key] = value
            else:
                serializable[key] = str(value)
        return serializable

    def _worker_command(self) -> list[str]:
        return [
            sys.executable,
            "-u",
            "-m",
            "pyrefman.worker",
            str(self._worker_args_file),
            str(self._worker_result_file),
        ]

    def _spawn_worker_process(self, args: dict) -> subprocess.Popen[str]:
        worker_dir = Path(tempfile.mkdtemp(prefix="pyrefman-ui-"))
        self._worker_args_file = worker_dir / "args.json"
        self._worker_result_file = worker_dir / "result.json"
        self._worker_args_file.write_text(
            json.dumps(self._serialize_worker_args(args), ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

        kwargs: dict = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
            "cwd": str(Path(__file__).resolve().parent.parent),
        }
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True

        return subprocess.Popen(self._worker_command(), **kwargs)

    def _monitor_worker_process(self, process: subprocess.Popen[str], args: dict) -> None:
        output_file = self._resolve_result_output_path(args)
        mapping_file = args.get("mapping_file")

        try:
            self._post_to_ui(self._set_status_text, "Processing citations...")
            if process.stdout is not None:
                for line in process.stdout:
                    text = str(line or "").rstrip()
                    if text:
                        self._post_to_ui(self._handle_worker_log, text)

            return_code = process.wait()
            process_payload = self._load_worker_result_payload(return_code)
        finally:
            self._cleanup_worker_artifacts()

        if self._abort_requested:
            self._post_to_ui(
                self._finish_processing,
                {
                    "aborted": True,
                    "skip_completion_dialog": True,
                },
            )
            return

        payload = {
            "output_file": output_file,
            "mapping_file": mapping_file,
            **process_payload,
        }
        self._post_to_ui(self._finish_processing, payload)

    def _load_worker_result_payload(self, return_code: int) -> dict:
        if self._worker_result_file and self._worker_result_file.exists():
            try:
                return json.loads(self._worker_result_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        if return_code == 0:
            return {
                "success": True,
                "preview_text": "",
                "reference_summary": {},
            }

        return {
            "success": False,
            "error": "PyRefman exited before returning a result.",
        }

    def _terminate_worker_process(self) -> None:
        process = self._worker_process
        if process is None:
            return

        try:
            if process.poll() is not None:
                return

            if sys.platform.startswith("win"):
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except Exception:
                    process.kill()
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _cleanup_worker_artifacts(self) -> None:
        process = self._worker_process
        if process is not None and process.stdout is not None:
            try:
                process.stdout.close()
            except Exception:
                pass

        paths = [self._worker_args_file, self._worker_result_file]
        parent = self._worker_args_file.parent if self._worker_args_file is not None else None
        for path in paths:
            if path and path.exists():
                try:
                    path.unlink()
                except Exception:
                    pass
        if parent and parent.exists():
            try:
                parent.rmdir()
            except Exception:
                pass

        self._worker_process = None
        self._worker_args_file = None
        self._worker_result_file = None

    def _handle_worker_log(self, text: str) -> None:
        for line in str(text).splitlines():
            if line.strip():
                self._append_log_line(line)
                self._set_status_text(line.strip())

    def _append_log_block(self, text: str) -> None:
        for line in str(text).splitlines():
            if line.strip():
                self._append_log_line(line)

    @staticmethod
    def _open_path(path: Path) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception:
            pass

    @staticmethod
    def _completion_open_target(payload: dict) -> Path | None:
        output_file = payload.get("output_file")
        if output_file and Path(output_file).exists():
            return Path(output_file)

        mapping_file = payload.get("mapping_file")
        if mapping_file and Path(mapping_file).exists():
            return Path(mapping_file)

        return None

    def _show_completion_dialog(self, payload: dict) -> None:
        if self._closing:
            return

        if self._completion_frame is not None and not self._completion_frame.IsBeingDeleted():
            self._completion_frame.Close()

        self.Enable(False)
        self._completion_frame = CompletionFrame(self, payload)
        self._completion_frame.Show()
        self._completion_frame.Raise()

    @staticmethod
    def _format_reference_summary(summary: dict | None) -> str:
        if not summary:
            return "No references were formatted in this run."

        total_unique_references = int(summary.get("total_unique_references", 0) or 0)
        if total_unique_references <= 0:
            return "No references were formatted in this run."

        lines = [f"Total unique references: {total_unique_references}"]

        oldest_year = summary.get("oldest_year")
        newest_year = summary.get("newest_year")
        if oldest_year is not None:
            lines.append(f"Oldest reference year: {oldest_year}")
        if newest_year is not None:
            lines.append(f"Newest reference year: {newest_year}")

        top_journals = summary.get("top_journals") or []
        if top_journals:
            lines.extend(["", "Top cited journals:"])
            for item in top_journals:
                lines.append(f"{item['label']} ({item['count']})")

        top_authors = summary.get("top_authors") or []
        if top_authors:
            lines.extend(["", "Top cited authors:"])
            for item in top_authors:
                lines.append(f"{item['label']} ({item['count']})")

        return "\n".join(lines)

    def _finish_processing(self, payload: dict) -> None:
        self._worker_thread = None
        self._running = False
        self._abort_requested = False
        self._progress_timer.Stop()
        self.progress_gauge.SetValue(0)
        self._validate_form()

        if payload.get("aborted"):
            self.results_notebook.SetSelection(0)
            self._replace_text(self.summary_ctrl, "")
            self._hide_text_caret(self.summary_ctrl)
            self._set_status_text("Operation aborted by user")
            self.run_state_label.SetLabel("Aborted")
            return

        if payload.get("success"):
            preview_text = payload.get("preview_text", "")
            summary_text = self._format_reference_summary(payload.get("reference_summary"))
            self._replace_text(self.preview_ctrl, preview_text)
            self._replace_text(self.summary_ctrl, summary_text)
            self._hide_text_caret(self.summary_ctrl)
            self.results_notebook.SetSelection(1 if preview_text else 0)

            output_file = payload.get("output_file")
            mapping_file = payload.get("mapping_file")
            if output_file and Path(output_file).exists():
                self._set_status_text(f"Finished. Output saved to {output_file}")
            elif mapping_file and Path(mapping_file).exists():
                self._set_status_text(f"Finished. Mapping file saved to {mapping_file}")
            else:
                self._set_status_text("Finished. Formatted markdown is ready in the preview tab.")
            self.run_state_label.SetLabel("Completed")
        else:
            self._replace_text(self.summary_ctrl, "")
            self._hide_text_caret(self.summary_ctrl)
            self.results_notebook.SetSelection(0)
            self._set_status_text(f"Failed. {payload.get('error', 'Unknown error.')}")
            self.run_state_label.SetLabel("Failed")

        if payload.get("show_error_dialog"):
            wx.MessageBox(payload.get("error", "Unknown error."), "PyRefman", wx.OK | wx.ICON_WARNING, parent=self)

        if not payload.get("skip_completion_dialog"):
            self._show_completion_dialog(payload)


def launch_app() -> None:
    app = wx.App(False)
    app.SetAppName("PyRefman")
    frame = PyRefmanFrame()
    frame.Show()
    app.MainLoop()

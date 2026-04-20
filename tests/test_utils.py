from __future__ import annotations

import io
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pyrefman import Utils as utils

from tests.helpers import make_formatted_reference, make_inline_reference, workspace_dir


class UtilsTests(unittest.TestCase):
    def test_normalize_google_doc_export_url(self) -> None:
        self.assertEqual(
            utils.normalize_google_doc_export_url("https://docs.google.com/document/d/abc123/edit?tab=t.0"),
            "https://docs.google.com/document/d/abc123/export?format=md",
        )
        self.assertEqual(utils.normalize_google_doc_export_url("https://example.com/doc"), "https://example.com/doc")

    def test_strip_wrapping_quotes_and_normalize_user_path(self) -> None:
        self.assertEqual(utils.strip_wrapping_quotes('"value"'), "value")
        self.assertIsNone(utils.normalize_user_path(None))
        self.assertIsNone(utils.normalize_user_path("   "))
        path = Path("~/demo")
        self.assertEqual(utils.normalize_user_path(path), path.expanduser())

    def test_markdown_link_helpers(self) -> None:
        self.assertTrue(utils.has_markdown_hyperlinks("[x](https://example.com)"))
        self.assertFalse(utils.has_markdown_hyperlinks("https://example.com"))
        converted = utils.convert_plain_text_urls_to_markdown("Visit https://example.com/test, now.")
        self.assertIn("[https://example.com/test](https://example.com/test),", converted)
        already_bracketed = utils.convert_plain_text_urls_to_markdown("[https://example.com]")
        self.assertEqual(already_bracketed, "[https://example.com](https://example.com)")

    def test_extract_markdown_url_prefers_available_matches(self) -> None:
        self.assertEqual(
            utils.extract_markdown_url("[https://inside.example](not-a-url)"),
            "https://inside.example",
        )
        self.assertEqual(
            utils.extract_markdown_url("[text](https://outside.example/path)"),
            "https://outside.example/path",
        )
        self.assertEqual(utils.extract_markdown_url("[https://solo.example]"), "https://solo.example")
        self.assertEqual(utils.extract_markdown_url("(https://paren.example)"), "https://paren.example")
        self.assertEqual(utils.extract_markdown_url(r"\[text\]\(https://escaped.example\)"), "https://escaped.example")
        self.assertIsNone(utils.extract_markdown_url("no links here"))

    def test_build_mapping_file_rows_deduplicates_and_sorts(self) -> None:
        ref1 = make_inline_reference(index=2, doi="10.1000/a")
        ref2 = make_inline_reference(index=1, doi="10.1000/b", pmid="222")
        ref3 = make_inline_reference(index=5, doi="10.1000/a")
        rows = utils.build_mapping_file_rows(
            [
                make_formatted_reference(ref1, inline="[2]", full="2. Ref A"),
                make_formatted_reference(ref2, inline="[1]", full="1. Ref B"),
                make_formatted_reference(ref3, inline="[5]", full="5. Ref A dup"),
            ]
        )
        self.assertEqual([row["inline_index"] for row in rows], [1, 2])
        self.assertEqual(rows[0]["url"], ref2.url)

    def test_read_input_file_handles_markdown_text_and_pandoc(self) -> None:
        with workspace_dir() as tmp_path:
            markdown_path = tmp_path / "demo.md"
            markdown_path.write_text("hello", encoding="utf-8")
            txt_path = tmp_path / "demo.txt"
            txt_path.write_text("https://example.com", encoding="utf-8")
            docx_path = tmp_path / "demo.docx"
            docx_path.write_text("binary-ish", encoding="utf-8")

            self.assertEqual(utils.read_input_file(markdown_path), "hello")
            self.assertIn("[https://example.com](https://example.com)", utils.read_input_file(txt_path))

            with patch.object(utils, "get_pandoc_path_or_none", return_value=None):
                with self.assertRaises(RuntimeError):
                    utils.read_input_file(docx_path)

            with patch.object(utils, "get_pandoc_path_or_none", return_value="pandoc"), patch.object(
                utils, "run_pandoc", return_value="converted"
            ) as run_pandoc:
                self.assertEqual(utils.read_input_file(docx_path), "converted")
                run_pandoc.assert_called_once()

    def test_read_input_file_uses_prompt_when_path_is_missing(self) -> None:
        with workspace_dir() as tmp_path:
            file_path = tmp_path / "prompted.md"
            file_path.write_text("prompted", encoding="utf-8")
            with patch("builtins.input", return_value=str(file_path)):
                self.assertEqual(utils.read_input_file(None), "prompted")

    def test_read_text_file_falls_back_to_replace(self) -> None:
        with workspace_dir() as tmp_path:
            path = tmp_path / "latin1.txt"
            path.write_bytes("caf\xe9".encode("latin-1"))
            text = utils._read_text_file(path)
            self.assertTrue(text.startswith("caf"))

    def test_safe_filename_and_grab_markdown_urls(self) -> None:
        self.assertEqual(utils.safe_filename("Bad:/Name??"), "Bad_Name")
        urls = utils.grab_markdown_urls(
            "[https://example.com] and [x](https://example.com/2)\n[https://example.com]"
        )
        self.assertEqual(urls, ["[x](https://example.com/2)"])

    def test_get_downloads_dir_uses_home_downloads(self) -> None:
        with patch("platform.system", return_value="Windows"):
            self.assertTrue(utils.get_downloads_dir().endswith("Downloads"))
        with patch("platform.system", return_value="Darwin"):
            self.assertTrue(utils.get_downloads_dir().endswith("Downloads"))
        with patch("platform.system", return_value="Linux"):
            self.assertTrue(utils.get_downloads_dir().endswith("Downloads"))

    def test_init_reference_style_class(self) -> None:
        class DemoStyle:
            pass

        module = SimpleNamespace(DemoStyle=DemoStyle)
        with patch("importlib.import_module", return_value=module):
            style = utils.init_reference_style_class("DemoStyle")
        self.assertIsInstance(style, DemoStyle)

        obj = object()
        self.assertIs(utils.init_reference_style_class(obj), obj)

        with patch("importlib.import_module", side_effect=ModuleNotFoundError):
            with self.assertRaises(ValueError):
                utils.init_reference_style_class("MissingStyle")

        with patch("importlib.import_module", return_value=SimpleNamespace()):
            with self.assertRaises(ValueError):
                utils.init_reference_style_class("MissingClassStyle")

    def test_replace_inline_references_with_formatted_references_and_group_detection(self) -> None:
        ref1 = make_inline_reference(index=1)
        ref1.inline_text = "[source](https://example.com/1)"
        ref2 = make_inline_reference(index=2, doi="10.1000/b")
        ref2.inline_text = "[source](https://example.com/2)"
        formatted1 = make_formatted_reference(ref1, inline="[1]", full="1. A")
        formatted2 = make_formatted_reference(ref2, inline="[2]", full="2. B")
        text = r"See \[[source](https://example.com/1)\], [1], [2], [3]."
        replaced = utils.replace_inline_references_with_formatted_references(formatted1, text)
        self.assertIn("[1]", replaced)

        groups = utils.find_tandem_reference_groups("[1], [2] and [3]", [formatted1, formatted2])
        self.assertEqual(len(groups), 1)
        self.assertEqual([fr.inline for fr in groups[0]], ["[1]", "[2]"])
        self.assertEqual(utils.find_tandem_reference_groups("plain text", []), [])

    def test_get_pandoc_path_and_run_pandoc(self) -> None:
        with patch.object(utils, "get_pandoc_path_or_none", return_value="pandoc"):
            self.assertEqual(utils.get_pandoc_path(), "pandoc")

        with patch.object(utils, "get_pandoc_path_or_none", return_value=None):
            with self.assertRaises(FileNotFoundError):
                utils.get_pandoc_path()

        success = SimpleNamespace(returncode=0, stdout="ok", stderr="")
        with patch("subprocess.run", return_value=success), patch.object(utils, "get_pandoc_path", return_value="pandoc"):
            self.assertEqual(utils.run_pandoc(["-t", "gfm"]), "ok")

        failure = SimpleNamespace(returncode=1, stdout="", stderr="boom")
        with patch("subprocess.run", return_value=failure), patch.object(utils, "get_pandoc_path", return_value="pandoc"):
            with self.assertRaises(RuntimeError):
                utils.run_pandoc(["-t", "gfm"])

    def test_output_file_helpers_and_warnings(self) -> None:
        with workspace_dir() as tmp_path:
            output_md = tmp_path / "out.md"
            self.assertEqual(utils.get_output_file_path(tmp_path / "demo.txt"), tmp_path / "demo_formatted.md")

            with patch("builtins.print") as mocked_print:
                utils.write_output_file("hello", output_md)
                self.assertEqual(output_md.read_text(encoding="utf-8"), "hello")
                self.assertTrue(mocked_print.called)

            with patch.object(utils, "run_pandoc") as run_pandoc:
                utils.write_markdown_to_file("hello", tmp_path / "out.docx")
                run_pandoc.assert_called_once()

            ref_missing = make_inline_reference()
            ref_missing.nbib_path = None
            with patch("builtins.print") as mocked_print:
                utils.warn_about_missing_citations(
                    'Loose https://loose.example',
                    ["[https://reject.example]"],
                    [ref_missing],
                )
                printed = "\n".join(str(call.args[0]) for call in mocked_print.call_args_list if call.args)
                self.assertIn("missing", printed.lower())
                self.assertIn("not handled", printed.lower())
                self.assertIn("loose", printed.lower())

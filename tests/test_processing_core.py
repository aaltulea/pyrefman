from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pyrefman
from pyrefman import processing

from tests.helpers import make_formatted_reference, make_inline_reference, workspace_dir


class DummyStyle:
    def format_reference(self, inline_reference):
        return make_formatted_reference(
            inline_reference,
            inline=f"[{inline_reference.inline_index}]",
            full=f"{inline_reference.inline_index}. {inline_reference.get_nbib_title()}",
        )

    def sort_formatted_references(self, references):
        return sorted(references, key=lambda ref: ref.inline_reference.inline_index)

    def format_grouped_inline_references(self, references):
        return "{" + ",".join(str(ref.inline_reference.inline_index) for ref in references) + "}"

    def describe_style(self):
        return "dummy"


class ProcessingTests(unittest.TestCase):
    def test_load_markdown_text_variants(self) -> None:
        with workspace_dir() as tmp_path:
            input_path = tmp_path / "input.md"
            input_path.write_text("hello", encoding="utf-8")
            markdown, output_path = processing.load_markdown_text(input_path)
            self.assertEqual(markdown, "hello")
            self.assertEqual(output_path.name, "input_formatted.md")

            markdown, output_path = processing.load_markdown_text("raw text")
            self.assertEqual(markdown, "raw text")
            self.assertIsNone(output_path)

        response = SimpleNamespace(text="<html><body>Doc text</body></html>")
        with patch("pyrefman.processing.requests.get", return_value=response), patch("builtins.print") as mocked_print:
            markdown, output_path = processing.load_markdown_text("https://docs.google.com/document/d/abc/edit")
        self.assertIn("Doc text", markdown)
        self.assertIsNone(output_path)
        self.assertTrue(mocked_print.called)

    def test_output_and_citation_resolution(self) -> None:
        with workspace_dir() as tmp_path:
            formatted = tmp_path / "demo_formatted.md"
            self.assertIsNone(processing.resolve_output_file(None, formatted, False, "markdown"))
            self.assertEqual(processing.resolve_output_file(tmp_path / "x.md", formatted, True, "markdown"), tmp_path / "x.md")
            self.assertEqual(processing.resolve_output_file(None, formatted, True, "docx"), tmp_path / "demo_formatted.docx")

            with patch("pyrefman.processing.get_downloads_dir", return_value=str(tmp_path)):
                self.assertEqual(
                    processing.resolve_output_file(None, None, True, "markdown"),
                    tmp_path / "pyrefman_formatted.md",
                )
                citations = processing.resolve_citations_dir(None)
                self.assertEqual(citations, tmp_path / "Citations")
                self.assertTrue(citations.exists())

    def test_partition_inline_reference_building_and_mapping_file(self) -> None:
        class DummyLooper:
            def accepts(self, url):
                return "accept" in url or "doi.org" in url

            def fetch_references_from_repos(self, reference):
                reference.nbib_path = "exists.nbib"

        urls = ["accept://one", "reject://two", "accept://three", "[https://doi.org/10.1/example]"]
        accepted, rejected = processing.partition_urls(urls, DummyLooper())
        self.assertEqual(accepted, ["accept://one", "accept://three", "[https://doi.org/10.1/example]"])
        self.assertEqual(rejected, ["reject://two"])

        refs = processing.build_inline_references(accepted, DummyLooper())
        self.assertEqual(len(refs), 3)
        refs[0].parsed_nbib = make_inline_reference(index=1).parsed_nbib
        refs[1].parsed_nbib = make_inline_reference(index=2, doi="10.1000/other").parsed_nbib
        refs[2].parsed_nbib = make_inline_reference(index=3, url="https://doi.org/10.1/example", doi="10.1/example").parsed_nbib
        processing.assign_unique_inline_indices(refs)
        self.assertEqual([ref.inline_index for ref in refs], [1, 2, 3])

        with workspace_dir() as tmp_path:
            first_path = tmp_path / "one.nbib"
            second_path = tmp_path / "two.nbib"
            first_path.write_text("x", encoding="utf-8")
            second_path.write_text("y", encoding="utf-8")
            refs[0].nbib_path = str(first_path)
            refs[1].nbib_path = str(second_path)
            refs[2].nbib_path = str(second_path)
            style = DummyStyle()
            formatted = processing.build_formatted_references(refs, style)
            self.assertEqual(len(formatted), 3)
            rows = processing.resolve_mapping_columns(None)
            mapping_path = tmp_path / "mapping.csv"
            written = processing.write_mapping_file(mapping_path, rows, formatted)
            self.assertEqual(written, mapping_path)
            self.assertIn('"title and year"', mapping_path.read_text(encoding="utf-8"))

    def test_render_markdown_with_references_groups_duplicates_and_spacing(self) -> None:
        style = DummyStyle()
        ref1 = make_inline_reference(index=1)
        ref2 = make_inline_reference(index=2, doi="10.1000/two", pmid="2")
        formatted1 = make_formatted_reference(ref1, inline="[1]", full="1. First.")
        formatted2 = make_formatted_reference(ref2, inline="[2]", full="2. Second.")
        markdown = "[source](https://pubmed.ncbi.nlm.nih.gov/12345/) [source](https://pubmed.ncbi.nlm.nih.gov/12345/)"
        ref1.inline_text = "[source](https://pubmed.ncbi.nlm.nih.gov/12345/)"
        ref2.inline_text = "[source](https://pubmed.ncbi.nlm.nih.gov/12345/)"
        rendered = processing.render_markdown_with_references(markdown, [formatted1, formatted2], style)
        self.assertIn("# References", rendered)

    def test_get_pyrefman_version_and_reference_summary(self) -> None:
        with patch("pyrefman.metadata.version", return_value="1.2.3"):
            self.assertEqual(pyrefman.get_pyrefman_version(), "1.2.3")

        not_found = pyrefman.metadata.PackageNotFoundError
        fake_file = MagicMock()
        fake_file.stat.return_value.st_mtime = 1
        with patch("pyrefman.metadata.version", side_effect=not_found), patch(
            "pyrefman.Path.resolve",
            return_value=Path(__file__),
        ), patch("pathlib.Path.rglob", return_value=[fake_file]):
            self.assertTrue(pyrefman.get_pyrefman_version().startswith("0+local."))

        with patch("pyrefman.metadata.version", side_effect=not_found), patch(
            "pyrefman.Path.resolve",
            return_value=Path(__file__),
        ), patch("pathlib.Path.rglob", return_value=[]):
            self.assertEqual(pyrefman.get_pyrefman_version(), "0+local")

        ref1 = make_inline_reference(dp="2019 Jan", journal="Journal A", authors=["Doe, Jane A", "Smith, John B"])
        ref2 = make_inline_reference(dp="2024 Mar", journal="Journal A", authors=["Doe, Jane A"], doi="10.1000/2", pmid="2")
        ref3 = make_inline_reference(dp="2022 Feb", journal="Journal B", authors=["Roe, Jane B", "Smith, John B"], doi="10.1000/3", pmid="3")
        ref4 = make_inline_reference(dp="2020 Jul", journal="Journal B", authors=["Roe, Jane B"], doi="10.1000/4", pmid="4")
        ref5 = make_inline_reference(dp="2021 Aug", journal="Journal C", authors=["Poe, Jane C", "Lane, Alex Q"], doi="10.1000/5", pmid="5")
        ref6 = make_inline_reference(dp="2023 Sep", journal="Journal C", authors=["Poe, Jane C"], doi="10.1000/6", pmid="6")
        ref7 = make_inline_reference(dp="2018 Nov", journal="Journal D", authors=["Moe, Jane D", "Solo, Single A"], doi="10.1000/7", pmid="7")
        ref8 = make_inline_reference(dp="2025 Jan", journal="Journal D", authors=["Moe, Jane D"], doi="10.1000/8", pmid="8")
        summary = pyrefman.build_reference_summary(
            [
                make_formatted_reference(ref1),
                make_formatted_reference(ref2),
                make_formatted_reference(ref3),
                make_formatted_reference(ref4),
                make_formatted_reference(ref5),
                make_formatted_reference(ref6),
                make_formatted_reference(ref7),
                make_formatted_reference(ref8),
            ]
        )
        self.assertEqual(summary["total_unique_references"], 8)
        self.assertEqual(summary["oldest_year"], 2018)
        self.assertEqual(summary["newest_year"], 2025)
        self.assertEqual(summary["top_journals"][0]["label"], "Journal A")
        self.assertEqual(summary["top_authors"][0]["label"], "Doe JA")
        self.assertEqual([item["label"] for item in summary["top_journals"]], ["Journal A", "Journal B", "Journal C", "Journal D"])
        self.assertEqual(
            [item["label"] for item in summary["top_authors"]],
            ["Doe JA", "Moe JD", "Poe JC", "Roe JB", "Smith JB"],
        )
        self.assertNotIn("Lane AQ", [item["label"] for item in summary["top_authors"]])
        self.assertNotIn("Solo SA", [item["label"] for item in summary["top_authors"]])
        self.assertEqual(pyrefman._extract_publication_year(make_inline_reference(dp="not a year")), None)

    def test_process_file_citations_success_and_errors(self) -> None:
        class DummyLooper:
            def __init__(self, citations_dir):
                self.citations_dir = citations_dir

            def accepts(self, url):
                return "pubmed" in url

            def fetch_references_from_repos(self, reference):
                reference.nbib_path = str(self.path)
                reference.parsed_nbib = make_inline_reference().parsed_nbib

        with workspace_dir() as tmp_path:
            nbib_path = tmp_path / "ref.nbib"
            nbib_path.write_text("PMID- 1\nTI  - Example", encoding="utf-8")
            style = DummyStyle()
            looper = DummyLooper(tmp_path)
            looper.path = nbib_path
            output_path = tmp_path / "output.md"
            mapping_path = tmp_path / "mapping.csv"

            with patch("pyrefman.SourcesLooper", return_value=looper), patch("pyrefman.WebDriver") as driver_cls:
                driver_cls.return_value.quit_driver = MagicMock()
                result = pyrefman.process_file_citations(
                    "Text [source](https://pubmed.ncbi.nlm.nih.gov/1/)",
                    output_file=output_path,
                    citations_dir=tmp_path / "citations",
                    mapping_file=mapping_path,
                    reference_style=style,
                    return_details=True,
                )

            self.assertIn("# References", result["markdown_text"])
            self.assertTrue(output_path.exists())
            self.assertTrue(mapping_path.exists())
            driver_cls.return_value.quit_driver.assert_called_once()

            with patch("pyrefman.can_write_docx", return_value=False):
                with self.assertRaises(RuntimeError):
                    pyrefman.process_file_citations("Text [source](https://pubmed.ncbi.nlm.nih.gov/1/)", output_format="docx")

            with self.assertRaises(pyrefman.NoUrlsFoundError):
                pyrefman.process_file_citations("No links here", reference_style=style)

    def test_process_file_citations_with_bracketed_plain_doi_urls(self) -> None:
        class DummyLooper:
            def __init__(self, citations_dir):
                self.citations_dir = citations_dir
                self.seen = []

            def accepts(self, url):
                self.seen.append(url)
                return url.startswith("https://doi.org/")

            def fetch_references_from_repos(self, reference):
                reference.nbib_path = str(self.path)
                doi = reference.url.replace("https://doi.org/", "")
                reference.parsed_nbib = make_inline_reference(
                    url=reference.url,
                    title=f"Example {doi}",
                    doi=doi,
                    pmid="",
                ).parsed_nbib

        with workspace_dir() as tmp_path:
            nbib_path = tmp_path / "ref.nbib"
            nbib_path.write_text(
                "\n".join(
                    [
                        "TI  - Example DOI paper.",
                        "AU  - Doe JA",
                        "JT  - Test Journal",
                        "DP  - 2024",
                    ]
                ) + "\n",
                encoding="utf-8",
            )
            looper = DummyLooper(tmp_path)
            looper.path = nbib_path
            text = (
                "some scientific statement [https://doi.org/10.1016/j.ebiom.2018.09.015]. "
                "Another statement [https://doi.org/10.1016/j.devcel.2014.11.012]."
            )

            with patch("pyrefman.SourcesLooper", return_value=looper), patch("pyrefman.WebDriver") as driver_cls:
                driver_cls.return_value.quit_driver = MagicMock()
                result = pyrefman.process_file_citations(
                    text,
                    save_output=False,
                    reference_style=DummyStyle(),
                    return_details=True,
                )

            self.assertIn("[1]", result["markdown_text"])
            self.assertIn("[2]", result["markdown_text"])
            self.assertIn("# References", result["markdown_text"])
            self.assertIn("https://doi.org/10.1016/j.ebiom.2018.09.015", looper.seen)
            self.assertIn("https://doi.org/10.1016/j.devcel.2014.11.012", looper.seen)

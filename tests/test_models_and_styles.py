from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from pyrefman.NBIBParser import NBIBParser, demo_sample_text, run_demo
from pyrefman.SingletonClass import Singleton
from pyrefman.data.FormattedReference import FormattedReference
from pyrefman.data.InlineReference import InlineReference
from pyrefman.mapping_columns import build_mapping_columns_from_keys
from pyrefman.sources.ReferencesSource import ReferencesSource
from pyrefman.styles.APAStyle import APAStyle
from pyrefman.styles.PMIDStyle import PMIDStyle
from pyrefman.styles.ReferencesStyle import ReferencesStyle
from pyrefman.styles.VancouverBoldTitleStyle import VancouverBoldTitleStyle
from pyrefman.styles.VancouverStyle import VancouverStyle

from tests.helpers import make_formatted_reference, make_inline_reference, workspace_dir


class ModelAndStyleTests(unittest.TestCase):
    def test_nbib_parser_handles_text_paths_and_demo(self) -> None:
        parsed = NBIBParser.parse("PMID- 12345\nTI  - Sample title\nTI  - Second\n      continuation")
        self.assertEqual(parsed["PMID"], "12345")
        self.assertEqual(parsed["TI"], ["Sample title", "Second continuation"])

        with workspace_dir() as tmp_path:
            path = tmp_path / "sample.nbib"
            path.write_text("PMID- 22222\nTI  - Path title", encoding="utf-8")
            self.assertEqual(NBIBParser.parse(path)["TI"], "Path title")

        with self.assertRaises(TypeError):
            NBIBParser.parse(123)

        captured = {}
        result = run_demo(printer=lambda value: captured.setdefault("value", value))
        self.assertEqual(result["PMID"], "37118429")
        self.assertIn("Heterochronic parabiosis", demo_sample_text())
        self.assertIn("value", captured)

    def test_singleton_and_mapping_columns(self) -> None:
        class DemoSingleton(metaclass=Singleton):
            pass

        self.assertIs(DemoSingleton(), DemoSingleton())

        columns = build_mapping_columns_from_keys(["title_and_year", "missing", "url"])
        self.assertEqual([header for header, _getter in columns], ["title and year", "url"])
        self.assertEqual(build_mapping_columns_from_keys(None), [])

    def test_formatted_reference_and_inline_reference_methods(self) -> None:
        ref = make_inline_reference()
        formatted = FormattedReference(inline_reference=ref, _inline="[1]", _full="1. Ref.")
        self.assertEqual(formatted.inline, "[1]")
        self.assertEqual(formatted.full, "1. Ref.")
        formatted.inline = "(1)"
        formatted.full = "Changed"
        self.assertIn("Changed", str(formatted))
        self.assertEqual(repr(formatted), str(formatted))

        with workspace_dir() as tmp_path:
            nbib_path = tmp_path / "ref.nbib"
            nbib_path.write_text("PMID- 10\nTI  - Title", encoding="utf-8")
            inline = InlineReference("[https://pubmed.ncbi.nlm.nih.gov/10/]")
            inline.associate_nbib(nbib_path)
            self.assertEqual(inline.get_nbib_title(), "Title.")

            with patch("pyrefman.data.InlineReference.NBIBParser.parse", side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    inline.associate_nbib(nbib_path)

            with patch("builtins.print") as mocked_print:
                inline.associate_nbib(str(tmp_path / "missing.nbib"))
                self.assertTrue(mocked_print.called)

        inline = make_inline_reference(
            title="Plain title",
            authors=["Last, First Middle", "Other, Test"],
            so="Journal. 2024;1(2):3-4. doi: 10.1000/x.",
        )
        inline.parsed_nbib["AID"] = ["10.1000/x [doi]"]
        self.assertEqual(inline.get_nbib_volume(), "10")
        self.assertEqual(inline.get_nbib_issue(), "2")
        self.assertEqual(inline.get_nbib_pages(), "11-19")
        self.assertEqual(inline.get_nbib_pmid(), "12345")
        self.assertEqual(inline.get_nbib_journal(), "Test Journal")
        self.assertEqual(inline.get_nbib_dp(), "2024 Jan")
        self.assertIn("Journal.", inline.get_nbib_so())
        self.assertEqual(inline.get_nbib_authors_list(), ["Last FM", "Other T"])
        self.assertEqual(inline.get_linearized_authors(), "Last FM, Other T.")
        self.assertEqual(inline.get_nbib_doi(), "10.1000/x")

        inline.parsed_nbib["FAU"] = None
        inline.parsed_nbib["AU"] = ["Doe JA"]
        self.assertEqual(inline.get_nbib_authors_list(), ["Doe JA"])
        inline.parsed_nbib["AID"] = ["not a doi", "12.3456/abc"]
        self.assertEqual(inline.get_nbib_doi(), "12.3456/abc")
        inline.parsed_nbib["AID"] = None
        inline.parsed_nbib["SO"] = "Journal. doi: 10.9999/xyz."
        self.assertEqual(inline.get_nbib_doi(), "10.9999/xyz")
        inline.parsed_nbib["SO"] = ""
        inline.parsed_nbib["DOI"] = "10.2222/final"
        self.assertEqual(inline.get_nbib_doi(), "10.2222/final")
        self.assertIn("10.2222/final", inline.nbib_summary())

        many_authors = make_inline_reference(authors=[f"Last, Author {idx}" for idx in range(8)])
        self.assertIn("et al.", many_authors.get_linearized_authors())

    def test_references_style_base_methods_can_be_called_via_super(self) -> None:
        class DelegatingStyle(ReferencesStyle):
            def format_reference(self, inline_reference):
                return super().format_reference(inline_reference)

            def sort_formatted_references(self, references):
                return super().sort_formatted_references(references)

            def format_grouped_inline_references(self, references):
                return super().format_grouped_inline_references(references)

            def describe_style(self):
                return super().describe_style()

        style = DelegatingStyle()
        ref = make_inline_reference()
        self.assertEqual(style.get_title(ref), "Example title.")
        self.assertEqual(style.get_authors(ref), ref.get_nbib_authors_list())
        self.assertEqual(style.get_journal(ref), "Test Journal")
        self.assertEqual(style.get_volume(ref), "10")
        self.assertEqual(style.get_issue(ref), "2")
        self.assertEqual(style.get_pages(ref), "11-19")
        self.assertEqual(style.get_doi(ref), "10.1000/example")
        self.assertEqual(style.get_so(ref), ref.get_nbib_so())
        self.assertEqual(style.get_dp(ref), "2024 Jan")
        with self.assertRaises(NotImplementedError):
            style.format_reference(ref)
        with self.assertRaises(NotImplementedError):
            style.sort_formatted_references([])
        with self.assertRaises(NotImplementedError):
            style.format_grouped_inline_references([])
        with self.assertRaises(NotImplementedError):
            style.describe_style()

    def test_references_source_base_methods(self) -> None:
        class DelegatingSource(ReferencesSource):
            def accepts(self, url: str) -> bool:
                return super().accepts(url)

            def download(self, reference: InlineReference) -> bool:
                return super().download(reference)

        source = DelegatingSource(Path.cwd())
        self.assertIsNone(source.driver)
        self.assertEqual(source.citations_dir, Path.cwd())
        self.assertIsNone(source.accepts("https://example.com"))
        self.assertIsNone(source.download(make_inline_reference()))

    def test_vancouver_styles(self) -> None:
        style = VancouverStyle()
        ref1 = make_inline_reference(index=2)
        ref2 = make_inline_reference(index=1, doi="10.1000/second", pmid="2")
        refs = [make_formatted_reference(ref1), make_formatted_reference(ref2)]
        self.assertEqual([r.inline_reference.inline_index for r in style.sort_formatted_references(refs)], [1, 2])
        self.assertEqual(style.format_grouped_inline_references([]), "[]")
        self.assertEqual(style.format_grouped_inline_references(refs), "[1, 2]")
        ref3 = make_inline_reference(index=3, doi="10.1000/third", pmid="3")
        ref4 = make_inline_reference(index=5, doi="10.1000/fourth", pmid="4")
        grouped = style.format_grouped_inline_references(
            [
                make_formatted_reference(ref2),
                make_formatted_reference(ref1),
                make_formatted_reference(ref3),
                make_formatted_reference(ref4),
            ]
        )
        self.assertEqual(grouped, "[1-3, 5]")
        self.assertEqual(style.get_year_month(ref1), "2024 Jan")
        self.assertEqual(style.get_inline_reference(ref1), "[2]")
        self.assertIn("doi: 10.1000/example.", style.get_full_reference(ref1))
        empty = make_inline_reference(title="", authors=[], journal="", volume="", issue="", pages="", doi="")
        empty.parsed_nbib["SO"] = "Fallback SO"
        self.assertEqual(style.get_full_reference(empty), "Fallback SO.")
        self.assertEqual(style.format_reference(ref1).full.split(".")[0], "2")
        self.assertEqual(style.format_reference(empty).full, "1. Fallback SO.")

        bold = VancouverBoldTitleStyle()
        self.assertIn("bolded titles", bold.describe_style())
        self.assertTrue(bold.get_title(ref1).startswith("**"))

    def test_pmid_style(self) -> None:
        style = PMIDStyle()
        ref = make_inline_reference(pmid="999")
        formatted = style.format_reference(ref)
        formatted.inline_reference = ref
        self.assertEqual(formatted.inline, "[PMID: 999]")
        self.assertEqual(formatted.full, "")
        self.assertEqual(style.describe_style(), "Shows inline PMID markers without a reference list; useful for reviewer rebuttals.")
        sorted_refs = style.sort_formatted_references([make_formatted_reference(ref)])
        self.assertEqual(sorted_refs[0].inline_reference.get_nbib_pmid(), "999")
        self.assertIn("PMID: 999", style.format_grouped_inline_references([formatted]))
        self.assertEqual(style.get_full_reference(ref), "Example title.")
        blank = make_inline_reference(title="")
        self.assertIsNone(style.get_full_reference(blank))
        self.assertIsNone(style.format_reference(blank))

    def test_apa_style(self) -> None:
        style = APAStyle()
        ref_one = make_inline_reference(authors=["Smith JA"], dp="2020 Jan", title="A Long Title Example")
        ref_two = make_inline_reference(authors=["Lee, Jane", "Kim, A"], dp="2021 Feb", doi="10.1000/two", pmid="2")
        ref_three = make_inline_reference(authors=["Adams, A", "Baker, B", "Clark, C"], dp="2022", doi="10.1000/three", pmid="3")
        self.assertEqual(style.get_year(ref_one), "2020")
        self.assertEqual(style._reference_sort_key(ref_one)[0], "smith")
        self.assertIn("Smith, 2020", style.get_inline_reference(ref_one))
        self.assertIn("Lee & Kim, 2021", style.get_inline_reference(ref_two))
        self.assertIn("Adams et al., 2022", style.get_inline_reference(ref_three))
        grouped = style.format_grouped_inline_references(
            [make_formatted_reference(ref_three), make_formatted_reference(ref_one), make_formatted_reference(ref_three)]
        )
        self.assertTrue(grouped.startswith("("))
        self.assertEqual(
            style._get_parenthetical_citation(make_inline_reference(authors=[], title="Untitled Example")),
            '"Untitled Example", 2024',
        )
        self.assertIn("https://doi.org/10.1000/two", style.get_full_reference(ref_two))
        no_meta = make_inline_reference(authors=[], title="", journal="", volume="", issue="", pages="", doi="")
        no_meta.parsed_nbib["SO"] = "Fallback source"
        self.assertEqual(style.get_full_reference(no_meta), "(2024).")
        self.assertIsNotNone(style.format_reference(ref_one))
        self.assertEqual(style._build_journal_block(ref_one), "Test Journal, 10(2), 11-19.")
        self.assertIsNone(style._build_journal_block(make_inline_reference(journal="", volume="", issue="", pages="")))
        self.assertEqual(style._format_apa_authors(["Doe, Jane"]), "Doe, J.")
        many = [f"Doe, Author {idx}" for idx in range(21)]
        formatted_many = style._format_apa_authors(many)
        self.assertIn("...", formatted_many)
        self.assertEqual(style._to_apa_author_name("Doe, Jane A"), "Doe, J. A.")
        self.assertEqual(style._to_apa_author_name("Doe JA"), "Doe, J. A.")
        self.assertEqual(style._to_apa_author_name("JA Doe"), "Doe, J. A.")
        self.assertEqual(style._to_apa_author_name("Jane Alice Doe"), "Doe, J. A.")
        self.assertEqual(style._author_family_name("Doe, Jane"), "Doe")
        self.assertEqual(style._author_family_name("Doe JA"), "Doe")
        self.assertEqual(style._author_family_name("JA Doe"), "Doe")
        self.assertEqual(style._author_family_name("Single"), "Single")
        self.assertEqual(style._given_names_to_initials("Jane Ann"), "J. A.")
        self.assertEqual(style._given_names_to_initials("Jean-Luc"), "J.-L.")
        self.assertEqual(style._token_to_initial("JA"), "J. A.")
        self.assertEqual(style._token_to_initial("Jane"), "J.")
        self.assertEqual(style._token_to_initial("123"), "")
        self.assertTrue(style._looks_like_initials("JA"))
        self.assertFalse(style._looks_like_initials("Jane"))
        self.assertEqual(style._normalize_doi("doi: https://doi.org/10.1/xyz"), "https://doi.org/10.1/xyz")
        self.assertEqual(style._short_title_for_citation("One two three four five"), '"One two three four"')
        self.assertEqual(style._ensure_terminal_punctuation("Text"), "Text.")
        self.assertEqual(style._ensure_terminal_punctuation("Text!"), "Text!")

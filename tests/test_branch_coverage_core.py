from __future__ import annotations

import importlib
import io
import json
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pyrefman
from pyrefman import Utils as utils
from pyrefman import processing, runtime
from pyrefman.NBIBParser import NBIBParser
from pyrefman.WebDriver import By, WebDriver
from pyrefman.data.InlineReference import InlineReference
from pyrefman.sources.BioRxivSource import BioRxivSource
from pyrefman.sources.NCBIGeoSource import NCBIGeoSource
from pyrefman.sources.PubMedSource import PubMedSource
from pyrefman.sources.SourcesLooper import SourcesLooper
from pyrefman.styles.APAStyle import APAStyle
from pyrefman.styles.VancouverStyle import VancouverStyle
from scripts import launch
from tests.helpers import make_formatted_reference, make_inline_reference, workspace_dir
from tests.test_sources_and_webdriver import (
    FakeLocatorCollection,
    FakePage,
    FakeTextLocator,
    FakeWaitableLocator,
)


webdriver_module = importlib.import_module("pyrefman.WebDriver")


class ExplodingCloser:
    def close(self) -> None:
        raise RuntimeError("boom")


class ExplodingStopper:
    def stop(self) -> None:
        raise RuntimeError("boom")


class BadAuthorCell:
    def locator(self, _selector):
        raise RuntimeError("bad anchors")

    def inner_text(self):
        return "Alice, Bob"

    def text_content(self):
        return "Alice, Bob"


class BrokenRow:
    def locator(self, _selector):
        raise RuntimeError("bad row")


class FakeXPathPage:
    def __init__(self, rows, author_links=None, author_error: Exception | None = None) -> None:
        self._rows = rows
        self._author_links = author_links
        self._author_error = author_error

    def locator(self, selector):
        if selector == "tr":
            return self._rows
        if selector.startswith("xpath="):
            if self._author_error is not None:
                raise self._author_error
            return self._author_links or FakeLocatorCollection([])
        raise AssertionError(selector)


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
        return "[" + ", ".join(str(ref.inline_reference.inline_index) for ref in references) + "]"


class BranchCoverageCoreTests(unittest.TestCase):
    def tearDown(self) -> None:
        runtime.get_local_pandoc_path.cache_clear()
        runtime.get_system_pandoc_path.cache_clear()
        runtime.get_pandoc_path_or_none.cache_clear()
        WebDriver._instance = None

    def test_inline_reference_and_parser_additional_branches(self) -> None:
        inline = InlineReference("plain text only")
        self.assertEqual(str(inline), "None")
        self.assertEqual(repr(inline), "None")
        self.assertIsNone(inline.get_nbib_field("TI"))

        inline.parsed_nbib = {
            "title": ["Fallback title"],
            "VOLUME": ["11"],
            "ISSUE": ["7"],
            "PAGES": ["42-45"],
            "JT": ["Fallback Journal"],
            "DP": ["2020 Feb"],
            "SO": ["Fallback Journal. 2020 Feb;11(7):42-45."],
            "AU": "Doe JA",
        }
        self.assertEqual(inline.get_nbib_title(), "Fallback title.")
        self.assertEqual(inline.get_nbib_volume(), "11")
        self.assertEqual(inline.get_nbib_issue(), "7")
        self.assertEqual(inline.get_nbib_pages(), "42-45")
        self.assertEqual(inline.get_nbib_journal(), "Fallback Journal")
        self.assertEqual(inline.get_nbib_dp(), "2020 Feb")
        self.assertEqual(inline.get_nbib_so(), "Fallback Journal. 2020 Feb;11(7):42-45.")
        self.assertEqual(inline.get_nbib_authors_list(), ["Doe JA"])
        self.assertEqual(inline.get_nbib_doi(), None)

        inline.parsed_nbib = {"FAU": "Doe, Jane Ann"}
        self.assertEqual(inline.get_nbib_authors_list(), ["Doe JA"])
        self.assertEqual(InlineReference._format_author_from_fau("Solo"), "Solo")

        inline.parsed_nbib = {"AID": "10.1234/demo [doi]"}
        self.assertEqual(inline.get_nbib_doi(), "10.1234/demo")
        inline.parsed_nbib = {"AID": "10.1234/demo"}
        self.assertEqual(inline.get_nbib_doi(), "10.1234/demo")
        inline.parsed_nbib = {"SO": ["Journal. doi: 10.5555/from-so."]}
        self.assertEqual(inline.get_nbib_doi(), "10.5555/from-so")

        parsed = NBIBParser.parse("\ncontinued before tag\nPMID- 7\n still same\n")
        self.assertEqual(parsed["PMID"], "7 still same")

    def test_processing_runtime_and_utils_additional_branches(self) -> None:
        ref = make_inline_reference()
        with workspace_dir() as tmp_path:
            nbib_path = tmp_path / "ref.nbib"
            nbib_path.write_text("x", encoding="utf-8")
            ref.nbib_path = str(nbib_path)

            style = MagicMock()
            style.format_reference.return_value = None
            self.assertEqual(processing.build_formatted_references([ref], style), [])

            custom_columns = [("only", lambda row: row["url"])]
            self.assertEqual(processing.resolve_mapping_columns(custom_columns), custom_columns)
            with self.assertRaises(ValueError):
                processing.write_mapping_file("", custom_columns, [])

        self.assertEqual(pyrefman._extract_publication_year(make_inline_reference(dp="")), None)
        with patch("pyrefman.build_mapping_file_rows", return_value=[{}]):
            self.assertEqual(pyrefman.build_reference_summary([object()])["total_unique_references"], 1)

        with workspace_dir() as tmp_path:
            nbib_path = tmp_path / "ref.nbib"
            nbib_path.write_text("PMID- 1\nTI  - Example", encoding="utf-8")

            class DummyLooper:
                def __init__(self, citations_dir):
                    self.citations_dir = citations_dir

                def accepts(self, url):
                    return "pubmed" in url

                def fetch_references_from_repos(self, reference):
                    reference.nbib_path = str(nbib_path)
                    reference.parsed_nbib = make_inline_reference().parsed_nbib

            with patch("pyrefman.SourcesLooper", return_value=DummyLooper(tmp_path)), patch("pyrefman.WebDriver") as driver_cls:
                driver_cls.return_value.quit_driver = MagicMock()
                result = pyrefman.process_file_citations(
                    "Text [source](https://pubmed.ncbi.nlm.nih.gov/1/)",
                    save_output=False,
                    reference_style=DummyStyle(),
                )
            self.assertIn("# References", result)

        with patch("pyrefman.runtime.LOCAL_PANDOC_ROOT", Path.cwd() / "definitely-missing"):
            runtime.get_local_pandoc_path.cache_clear()
            self.assertIsNone(runtime.get_local_pandoc_path())

        with workspace_dir() as tmp_path:
            local_root = tmp_path / "pandoc-root"
            local_root.mkdir()
            runtime.get_local_pandoc_path.cache_clear()
            with patch.object(runtime, "LOCAL_PANDOC_ROOT", local_root), patch.object(
                runtime, "_pandoc_executable_name", return_value="pandoc"
            ), patch.object(runtime, "_is_working_pandoc", return_value=False):
                self.assertIsNone(runtime.get_local_pandoc_path())

        runtime.get_pandoc_path_or_none.cache_clear()
        with patch.dict("os.environ", {}, clear=True), patch.object(runtime, "get_local_pandoc_path", return_value="local-pandoc"), patch.object(
            runtime, "get_system_pandoc_path", return_value=None
        ):
            self.assertEqual(runtime.get_pandoc_path_or_none(), "local-pandoc")

        with patch.object(runtime, "is_pandoc_available", return_value=True):
            self.assertTrue(runtime.can_write_docx())

        self.assertEqual(utils.convert_plain_text_urls_to_markdown(""), "")
        self.assertEqual(utils.extract_markdown_url("prefix https://fallback.example/path suffix"), "https://fallback.example/path")

        with workspace_dir() as tmp_path:
            path = tmp_path / "text.txt"
            path.write_text("unused", encoding="utf-8")
            with patch("pyrefman.Utils.locale.getpreferredencoding", return_value="utf-8"), patch.object(
                Path, "read_text", side_effect=[UnicodeDecodeError("utf-8", b"", 0, 1, "bad"), "fallback"]
            ):
                self.assertEqual(utils._read_text_file(path), "fallback")

            with patch("pyrefman.Utils.locale.getpreferredencoding", return_value="utf-8-sig"), patch.object(
                Path,
                "read_text",
                side_effect=[
                    UnicodeDecodeError("utf-8", b"", 0, 1, "bad"),
                    UnicodeDecodeError("utf-8-sig", b"", 0, 1, "bad"),
                    "replaced",
                ],
            ):
                self.assertEqual(utils._read_text_file(path), "replaced")

        ref_one = make_inline_reference(index=1)
        ref_two = make_inline_reference(index=3, doi="10.1000/two", pmid="2")
        groups = utils.find_tandem_reference_groups(
            "[1] and [3]",
            [make_formatted_reference(ref_one, inline="[1]"), make_formatted_reference(ref_two, inline="[3]")],
        )
        self.assertEqual(groups, [])

    def test_styles_and_sources_additional_branches(self) -> None:
        apa = APAStyle()
        self.assertEqual(apa.describe_style(), "Author-date citations with a full reference list in APA style.")
        ref_a = make_inline_reference(authors=["Beta, Author"], dp="2024", title="B title")
        ref_b = make_inline_reference(authors=["Alpha, Author"], dp="2020", title="A title", doi="10.1000/b", pmid="2")
        sorted_refs = apa.sort_formatted_references([make_formatted_reference(ref_a), make_formatted_reference(ref_b)])
        self.assertEqual(sorted_refs[0].inline_reference.get_nbib_pmid(), "2")
        self.assertEqual(apa.format_grouped_inline_references([]), "()")
        self.assertIsNone(apa.get_year(make_inline_reference(dp="n.d.")))

        minimal = make_inline_reference(title="", authors=[], journal="", volume="", issue="", pages="", doi="", dp="")
        minimal.parsed_nbib["SO"] = ""
        self.assertEqual(apa.get_full_reference(minimal), "(n.d.).")
        self.assertEqual(apa._build_journal_block(make_inline_reference(journal="", volume="9", issue="", pages="")), "9.")
        self.assertEqual(apa._build_journal_block(make_inline_reference(journal="", volume="", issue="", pages="14-18")), "14-18.")
        self.assertEqual(apa.format_reference(minimal).full, "* (n.d.).")
        self.assertEqual(apa._format_apa_authors([]), "")
        self.assertEqual(apa._to_apa_author_name(""), "")
        self.assertEqual(apa._to_apa_author_name("Single"), "Single")
        self.assertEqual(apa._author_family_name(""), "")
        self.assertEqual(apa._author_family_name("Jane Alice Doe"), "Doe")
        self.assertEqual(apa._given_names_to_initials(""), "")
        self.assertEqual(apa._given_names_to_initials("Jane  Ann"), "J. A.")
        self.assertFalse(apa._looks_like_initials("123"))
        self.assertEqual(apa._ensure_terminal_punctuation(""), "")

        van = VancouverStyle()
        self.assertEqual(
            van.format_grouped_inline_references(
                [
                    make_formatted_reference(make_inline_reference(index=1), inline="[1]"),
                    make_formatted_reference(make_inline_reference(index=3), inline="[3]"),
                ]
            ),
            "[1, 3]",
        )
        self.assertEqual(
            van.format_grouped_inline_references(
                [
                    make_formatted_reference(make_inline_reference(index=1), inline="[1]"),
                    make_formatted_reference(make_inline_reference(index=2), inline="[2]"),
                    make_formatted_reference(make_inline_reference(index=4), inline="[4]"),
                ]
            ),
            "[1, 2, 4]",
        )
        no_dp = make_inline_reference(dp="")
        self.assertIsNone(van.get_year_month(no_dp))
        pages_only = make_inline_reference(title="", authors=[], journal="Journal", volume="", issue="", pages="20-30", doi="", dp="")
        self.assertIn("Journal 20-30.", van.get_full_reference(pages_only))
        no_parts = make_inline_reference(title="", authors=[], journal="", volume="", issue="", pages="", doi="", dp="")
        no_parts.parsed_nbib["SO"] = ""
        self.assertIsNone(van.get_full_reference(no_parts))
        self.assertIsNone(van.format_reference(no_parts))

        looper = SourcesLooper(Path.cwd())
        looper.SOURCES = [SimpleNamespace(accepts=lambda _url: False)]
        self.assertFalse(looper.accepts("https://example.com"))

        pubmed = PubMedSource(Path.cwd())
        page = FakePage()
        driver = MagicMock()
        driver.get_page.return_value = page
        driver.find_element.side_effect = [RuntimeError("no selector"), RuntimeError("no selector"), SimpleNamespace(click=lambda: None)]
        page.role_clicker.clicked = False
        with patch("pyrefman.sources.PubMedSource.WebDriver", return_value=driver):
            pubmed._open_citation_ui(is_pmc=True)
            pubmed._click_export()
        self.assertTrue(page.role_clicker.clicked)

        page = FakePage()
        driver = MagicMock()
        driver.get_page.return_value = page
        driver.find_element.side_effect = [SimpleNamespace(click=lambda: None), SimpleNamespace(click=lambda: None)]
        with patch("pyrefman.sources.PubMedSource.WebDriver", return_value=driver):
            pubmed._open_citation_ui(is_pmc=False)
            pubmed._click_export()

        biorxiv = BioRxivSource(Path.cwd())
        page = FakePage()
        driver = MagicMock()
        driver.get_page.return_value = page
        driver.find_element.side_effect = [RuntimeError("no selector"), RuntimeError("no selector")]
        with patch("pyrefman.sources.BioRxivSource.WebDriver", return_value=driver):
            biorxiv._open_export_panel()
            biorxiv._click_medlars()
        self.assertTrue(page.role_clicker.clicked)

        driver = MagicMock()
        driver.get_page.return_value = page
        driver.find_element.side_effect = [SimpleNamespace(click=lambda: None)]
        with patch("pyrefman.sources.BioRxivSource.WebDriver", return_value=driver):
            biorxiv._click_medlars()

        geo = NCBIGeoSource(Path.cwd())
        self.assertEqual(geo._extract_authors_from_cell(BadAuthorCell()), ["Alice", "Bob"])

        with workspace_dir() as tmp_path:
            geo = NCBIGeoSource(tmp_path)
            ref = make_inline_reference(url="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE123")
            rows = FakeLocatorCollection(
                [
                    FakeTextLocator(children={"td": FakeLocatorCollection([FakeTextLocator("only one")])}),
                    FakeTextLocator(children={"td": FakeLocatorCollection([FakeTextLocator(""), FakeTextLocator("blank")])}),
                    FakeTextLocator(children={"td": FakeLocatorCollection([FakeTextLocator("Series"), FakeTextLocator("skip")])}),
                    BrokenRow(),
                    FakeTextLocator(children={"td": FakeLocatorCollection([FakeTextLocator("Title"), FakeTextLocator("Dataset title")])}),
                    FakeTextLocator(children={"td": FakeLocatorCollection([FakeTextLocator("Summary"), FakeTextLocator("Dataset summary")])}),
                    FakeTextLocator(children={"td": FakeLocatorCollection([FakeTextLocator("Contributor(s)"), FakeTextLocator("Alice, Bob")])}),
                    FakeTextLocator(children={"td": FakeLocatorCollection([FakeTextLocator("Status"), FakeTextLocator("Updated Mar 5, 2024")])}),
                ]
            )
            page = FakeXPathPage(rows)
            strong = SimpleNamespace(locator=lambda _selector: (_ for _ in ()).throw(RuntimeError("bad row anchor")))
            driver = MagicMock()
            driver.navigate_to = MagicMock()
            driver.get_page.return_value = page
            driver.find_element.side_effect = [strong]
            with patch("pyrefman.sources.NCBIGeoSource.WebDriver", return_value=driver), patch.object(
                geo, "_extract_authors_from_cell", return_value=[]
            ):
                written = geo.download(ref)
            self.assertIsNotNone(written)
            text = written.read_text(encoding="utf-8")
            self.assertIn("AU  - Alice", text)
            self.assertIn("DP  - 2024 Mar 05", text)

            rows = FakeLocatorCollection(
                [
                    FakeTextLocator(children={"td": FakeLocatorCollection([FakeTextLocator("Title"), FakeTextLocator("Contact title")])}),
                    FakeTextLocator(children={"td": FakeLocatorCollection([FakeTextLocator("Contact name"), FakeTextLocator("Dr Contact")])}),
                ]
            )
            page = FakeXPathPage(rows)
            driver.find_element.side_effect = [RuntimeError("missing"), RuntimeError("missing")]
            driver.get_page.return_value = page
            contact_ref = make_inline_reference(url="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE124")
            with patch("pyrefman.sources.NCBIGeoSource.WebDriver", return_value=driver):
                contact_written = geo.download(contact_ref)
            self.assertIn("AU  - Dr Contact", contact_written.read_text(encoding="utf-8"))

            rows = FakeLocatorCollection([FakeTextLocator(children={"td": FakeLocatorCollection([FakeTextLocator("Title"), FakeTextLocator("Author title")])})])
            author_links = FakeLocatorCollection([FakeTextLocator("Alpha"), FakeTextLocator("Alpha"), FakeTextLocator("Beta")])
            page = FakeXPathPage(rows, author_links=author_links)
            driver.find_element.side_effect = [RuntimeError("missing"), RuntimeError("missing")]
            driver.get_page.return_value = page
            author_ref = make_inline_reference(url="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE125")
            with patch("pyrefman.sources.NCBIGeoSource.WebDriver", return_value=driver):
                author_written = geo.download(author_ref)
            author_text = author_written.read_text(encoding="utf-8")
            self.assertEqual(author_text.count("AU  - Alpha"), 1)
            self.assertEqual(author_text.count("AU  - Beta"), 1)

            rows = FakeLocatorCollection([FakeTextLocator(children={"td": FakeLocatorCollection([FakeTextLocator("Title"), FakeTextLocator("No authors title")])})])
            page = FakeXPathPage(rows, author_error=RuntimeError("author lookup failed"))
            driver.find_element.side_effect = [RuntimeError("missing"), RuntimeError("missing")]
            driver.get_page.return_value = page
            no_author_ref = make_inline_reference(url="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE126")
            with patch("pyrefman.sources.NCBIGeoSource.WebDriver", return_value=driver):
                no_author_written = geo.download(no_author_ref)
            self.assertNotIn("AU  -", no_author_written.read_text(encoding="utf-8"))

    def test_webdriver_and_launch_additional_branches(self) -> None:
        driver = WebDriver()
        driver._page = None
        driver._start = MagicMock(side_effect=lambda: setattr(driver, "_page", "page"))
        self.assertEqual(driver.get_page(), "page")
        with patch.object(driver, "quit_driver") as quit_driver:
            driver.prepare_run()
            driver.request_abort()
        self.assertEqual(quit_driver.call_count, 2)
        self.assertFalse(driver.is_abort_requested())
        self.assertIsNone(driver.ensure_not_aborted())
        self.assertIsNone(driver.raise_if_aborted(RuntimeError("ignored")))
        self.assertEqual(driver.get_download_timeout(7), 7)
        self.assertIsNone(driver.mark_download_detected())
        self.assertFalse(driver.should_fallback_to_headed())
        self.assertIsNone(driver.switch_to_headed_mode("reason"))

        driver._page = ExplodingCloser()
        driver._context = ExplodingCloser()
        driver._browser = ExplodingCloser()
        driver._pw = ExplodingStopper()
        driver.quit_driver()
        self.assertIsNone(driver._page)
        self.assertIsNone(driver._context)
        self.assertIsNone(driver._browser)
        self.assertIsNone(driver._pw)

        page = SimpleNamespace(goto=MagicMock(side_effect=RuntimeError("nav failed")))
        driver.get_page = MagicMock(return_value=page)
        driver.quit_driver = MagicMock(side_effect=RuntimeError("quit failed"))
        with patch("time.sleep"), self.assertRaises(RuntimeError):
            driver.navigate_to2("https://example.com", retries=1, retry_sleep=0)

        page = FakePage()
        driver.browser_name = "chromium"
        driver._page = page
        driver._context = SimpleNamespace(new_cdp_session=MagicMock(side_effect=RuntimeError("session boom")))
        driver._apply_preferred_window_size()

        retrying_locator = FakeWaitableLocator()
        wait_calls = []

        def wait_for(state=None, timeout=None):
            wait_calls.append((state, timeout))
            if len(wait_calls) == 1:
                raise RuntimeError("wait")

        retrying_locator.wait_for = wait_for
        locators = FakeLocatorCollection([retrying_locator])
        page = FakePage()
        driver._to_locator = MagicMock(return_value=locators)
        driver.get_page = MagicMock(return_value=page)
        with patch.object(webdriver_module, "PWTimeoutError", RuntimeError):
            self.assertIs(driver.find_element(By.CSS_SELECTOR, "demo"), retrying_locator)
        self.assertGreaterEqual(len(wait_calls), 2)

        failing_locator = FakeWaitableLocator(wait_error=RuntimeError("wait"))
        locators = FakeLocatorCollection([failing_locator])
        page = FakePage()
        page.evaluate = MagicMock(side_effect=RuntimeError("scroll failed"))
        driver._to_locator = MagicMock(return_value=locators)
        driver.get_page = MagicMock(return_value=page)
        with patch.object(webdriver_module, "PWTimeoutError", RuntimeError), self.assertRaises(TimeoutError):
            driver.find_element(By.CSS_SELECTOR, "demo")

        with workspace_dir() as tmp_path:
            state_file = tmp_path / "state.json"
            state_file.write_text("{bad json", encoding="utf-8")
            with patch.object(launch, "STATE_FILE", state_file):
                self.assertEqual(launch.load_state(), {})

        with self.assertRaises(ValueError):
            launch.retry_on_internet_failure("step", lambda: (_ for _ in ()).throw(ValueError("boom")))

        error = subprocess.CalledProcessError(1, ["pip"])
        with patch("scripts.launch.retry_on_internet_failure", side_effect=error), patch("platform.system", return_value="Linux"):
            with self.assertRaises(RuntimeError):
                launch.install_requirements()
        with patch("scripts.launch.retry_on_internet_failure", side_effect=error), patch("platform.system", return_value="Windows"):
            with self.assertRaises(subprocess.CalledProcessError):
                launch.install_requirements()

        with patch("scripts.launch.retry_on_internet_failure", side_effect=error):
            with self.assertRaises(RuntimeError):
                launch.install_playwright_browser()

        with patch.object(launch, "pandoc_asset_name", return_value=None), patch("builtins.print") as mocked_print:
            self.assertIsNone(launch.ensure_local_pandoc())
        self.assertTrue(mocked_print.called)

        with workspace_dir() as tmp_path:
            asset_name = "pandoc-demo.zip"
            target_dir = tmp_path / f"{launch.PANDOC_VERSION}-{asset_name}"
            target_dir.mkdir()
            with patch.object(launch, "PANDOC_ROOT", tmp_path), patch.object(launch, "pandoc_asset_name", return_value=asset_name), patch.object(
                launch, "find_local_pandoc", side_effect=[None, "existing-pandoc"]
            ):
                self.assertEqual(launch.ensure_local_pandoc(), "existing-pandoc")

        with workspace_dir() as tmp_path:
            asset_name = "pandoc-demo.zip"
            target_dir = tmp_path / f"{launch.PANDOC_VERSION}-{asset_name}"
            target_dir.mkdir()
            temp_dir = tmp_path / "temp-download"
            temp_dir.mkdir()

            class FakeTemporaryDirectory:
                def __enter__(self_inner):
                    return str(temp_dir)

                def __exit__(self_inner, exc_type, exc, tb):
                    return False

            with patch.object(launch, "PANDOC_ROOT", tmp_path), patch.object(launch, "pandoc_asset_name", return_value=asset_name), patch.object(
                launch, "find_local_pandoc", side_effect=[None, None, None]
            ), patch.object(launch, "download_file"), patch.object(launch, "extract_archive"), patch(
                "tempfile.TemporaryDirectory", return_value=FakeTemporaryDirectory()
            ), patch("shutil.rmtree") as rmtree:
                with self.assertRaises(RuntimeError):
                    launch.ensure_local_pandoc()
            rmtree.assert_called_once()

        with workspace_dir() as tmp_path:
            asset_name = "pandoc-demo.zip"
            target_dir = tmp_path / f"{launch.PANDOC_VERSION}-{asset_name}"
            expected = str(target_dir / "pandoc.exe")
            temp_dir = tmp_path / "temp-success"
            temp_dir.mkdir()

            class FakeTemporaryDirectory:
                def __enter__(self_inner):
                    return str(temp_dir)

                def __exit__(self_inner, exc_type, exc, tb):
                    return False

            with patch.object(launch, "PANDOC_ROOT", tmp_path), patch.object(launch, "pandoc_asset_name", return_value=asset_name), patch.object(
                launch, "find_local_pandoc", side_effect=[None, expected, expected]
            ), patch.object(launch, "download_file"), patch.object(launch, "extract_archive"), patch(
                "tempfile.TemporaryDirectory", return_value=FakeTemporaryDirectory()
            ), patch("shutil.move") as move:
                self.assertEqual(launch.ensure_local_pandoc(), expected)
            move.assert_called_once()

        with patch("platform.machine", return_value="sparc"):
            self.assertEqual(launch.normalized_machine(), "sparc")
        with patch("platform.system", return_value="Windows"), patch.object(launch, "normalized_machine", return_value="x86"):
            self.assertIsNone(launch.pandoc_asset_name())
        with patch("platform.system", return_value="Darwin"), patch.object(launch, "normalized_machine", return_value="x86_64"):
            self.assertIn("x86_64-macOS.zip", launch.pandoc_asset_name())
        with patch("platform.system", return_value="Darwin"), patch.object(launch, "normalized_machine", return_value="ppc"):
            self.assertIsNone(launch.pandoc_asset_name())
        with patch("platform.system", return_value="Linux"), patch.object(launch, "normalized_machine", return_value="arm64"):
            self.assertIn("linux-arm64.tar.gz", launch.pandoc_asset_name())
        with patch("platform.system", return_value="Linux"), patch.object(launch, "normalized_machine", return_value="ppc"):
            self.assertIsNone(launch.pandoc_asset_name())
        with patch("platform.system", return_value="Plan9"), patch.object(launch, "normalized_machine", return_value="x86_64"):
            self.assertIsNone(launch.pandoc_asset_name())

        with workspace_dir() as tmp_path:
            file_path = tmp_path / "requirements.txt"
            file_path.write_text("requests\n", encoding="utf-8")
            runtime_dir = tmp_path / ".runtime"
            runtime_dir.mkdir()
            state_file = runtime_dir / "launch-state.json"
            state_file.write_text("{}", encoding="utf-8")
            with patch.object(launch, "REPO_ROOT", tmp_path), patch.object(launch, "RUNTIME_DIR", runtime_dir), patch.object(
                launch, "STATE_FILE", state_file
            ), patch.object(launch, "dependencies_look_installed", return_value=False), patch.object(
                launch, "install_requirements"
            ) as install_requirements, patch.object(launch, "package_version", return_value="1.0"), patch.object(
                launch, "needs_playwright_install", return_value=True
            ), patch.object(launch, "install_playwright_browser") as install_browser, patch.object(
                launch, "ensure_local_pandoc", return_value="pandoc"
            ), patch.object(launch, "save_state") as save_state, patch.object(launch, "launch_app", return_value=3):
                self.assertEqual(launch.main(), 3)
            install_requirements.assert_called_once()
            install_browser.assert_called_once()
            save_state.assert_called_once()

            good_hash = launch.file_sha256(file_path)
            with patch.object(launch, "REPO_ROOT", tmp_path), patch.object(launch, "RUNTIME_DIR", runtime_dir), patch.object(
                launch, "STATE_FILE", state_file
            ), patch.object(launch, "load_state", return_value={"requirements_hash": good_hash, "playwright_version": "1.0"}), patch.object(
                launch, "dependencies_look_installed", return_value=True
            ), patch.object(launch, "package_version", return_value="1.0"), patch.object(
                launch, "needs_playwright_install", return_value=False
            ), patch.object(launch, "ensure_local_pandoc", side_effect=RuntimeError("pandoc failed")), patch.object(
                launch, "save_state"
            ) as save_state, patch.object(launch, "launch_app", return_value=0), patch("builtins.print") as mocked_print:
                self.assertEqual(launch.main(), 0)
            save_state.assert_not_called()
            self.assertGreaterEqual(mocked_print.call_count, 2)

        with workspace_dir() as tmp_path:
            launch_dir = tmp_path / ".playwright-missing"
            with patch.object(launch, "PLAYWRIGHT_BROWSERS_DIR", launch_dir):
                self.assertFalse(launch.has_local_playwright_browser())

        with workspace_dir() as tmp_path:
            launch_dir = tmp_path / ".playwright"
            launch_dir.mkdir()
            with patch.object(launch, "PLAYWRIGHT_BROWSERS_DIR", launch_dir):
                self.assertFalse(launch.has_local_playwright_browser())
            self.assertFalse(launch.is_runnable(tmp_path / "missing"))
            self.assertFalse(launch.is_runnable(tmp_path))

        with workspace_dir() as tmp_path:
            asset_name = "pandoc-demo.zip"
            with patch.object(launch, "PANDOC_ROOT", tmp_path), patch.object(launch, "pandoc_asset_name", return_value=asset_name), patch.object(
                launch, "find_local_pandoc", return_value="already-there"
            ):
                self.assertEqual(launch.ensure_local_pandoc(), "already-there")

        with patch("scripts.launch.os.name", "nt"), patch.object(Path, "exists", return_value=False):
            self.assertIsNone(launch.windows_pythonw_path())

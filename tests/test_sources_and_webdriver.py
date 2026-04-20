from __future__ import annotations

import importlib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pyrefman.WebDriver import By, WebDriver, expect_download_save_as
from pyrefman.sources.BioRxivSource import BioRxivSource
from pyrefman.sources.NCBIGeoSource import NCBIGeoSource
from pyrefman.sources.PubMedSource import PubMedSource
from pyrefman.sources.SourcesLooper import SourcesLooper

from tests.helpers import make_inline_reference, workspace_dir


webdriver_module = importlib.import_module("pyrefman.WebDriver")


class FakeClickTarget:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.clicked = False

    def click(self, timeout=None) -> None:
        if self.error is not None:
            raise self.error
        self.clicked = True


class FakeExpectDownload:
    def __init__(self, download) -> None:
        self.value = download

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeDownload:
    def __init__(self) -> None:
        self.saved_path = None

    def save_as(self, path: str) -> None:
        self.saved_path = path


class FakeLocatorCollection:
    def __init__(self, items):
        self.items = list(items)
        self.first = self.items[0] if self.items else FakeWaitableLocator()

    def nth(self, index):
        return self.items[index]

    def count(self):
        return len(self.items)


class FakeWaitableLocator:
    def __init__(self, wait_error: Exception | None = None) -> None:
        self.wait_error = wait_error
        self.wait_calls = []

    def wait_for(self, state=None, timeout=None):
        self.wait_calls.append((state, timeout))
        if self.wait_error is not None:
            raise self.wait_error


class FakePage:
    def __init__(self) -> None:
        self.download = FakeDownload()
        self.role_clicker = FakeClickTarget()
        self.text_clicker = FakeClickTarget()
        self.last_goto = None
        self.locators = {}
        self.evaluate_result = {"width": 1200, "height": 900}

    def expect_download(self, timeout=None):
        self.expected_timeout = timeout
        return FakeExpectDownload(self.download)

    def goto(self, url, wait_until=None):
        self.last_goto = (url, wait_until)

    def locator(self, value):
        return self.locators[value]

    def get_by_role(self, *args, **kwargs):
        return self.role_clicker

    def get_by_text(self, *args, **kwargs):
        return self.text_clicker

    def evaluate(self, script):
        return self.evaluate_result


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.closed = False
        self.session = MagicMock()
        self.session.send.side_effect = [{"windowId": 1}, None]

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True

    def new_cdp_session(self, page):
        return self.session


class FakeBrowser:
    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.closed = False

    def new_context(self, accept_downloads=True):
        self.accept_downloads = accept_downloads
        return self.context

    def close(self):
        self.closed = True


class FakePlaywrightStart:
    def __init__(self, browser: FakeBrowser) -> None:
        self.chromium = SimpleNamespace(launch=lambda headless=False: browser)
        self.firefox = self.chromium
        self.webkit = self.chromium
        self.stopped = False

    def stop(self):
        self.stopped = True


class FakePlaywrightFactory:
    def __init__(self, playwright: FakePlaywrightStart) -> None:
        self.playwright = playwright

    def start(self):
        return self.playwright


class FakeTextLocator:
    def __init__(self, text="", children=None, anchors=None):
        self._text = text
        self.children = children or {}
        self.anchors = anchors or []

    def inner_text(self):
        return self._text

    def text_content(self):
        return self._text

    def locator(self, selector):
        if selector == "a":
            return FakeLocatorCollection(self.anchors)
        return self.children.get(selector, FakeLocatorCollection([]))

    def count(self):
        return len(self.anchors)

    def nth(self, index):
        return self.anchors[index]


class SourcesAndWebDriverTests(unittest.TestCase):
    def tearDown(self) -> None:
        WebDriver._instance = None

    def test_expect_download_save_as_and_webdriver_lifecycle(self) -> None:
        with workspace_dir() as tmp_path:
            page = FakePage()
            saved = expect_download_save_as(page, lambda: None, tmp_path / "file.txt", timeout_s=2)
            self.assertEqual(saved, tmp_path / "file.txt")
            self.assertEqual(page.download.saved_path, str(tmp_path / "file.txt"))
            self.assertEqual(page.expected_timeout, 2000)

        page = FakePage()
        context = FakeContext(page)
        browser = FakeBrowser(context)
        playwright = FakePlaywrightStart(browser)
        with patch("pyrefman.WebDriver.sync_playwright", return_value=FakePlaywrightFactory(playwright)), patch(
            "pyrefman.WebDriver.get_downloads_dir", return_value=str(Path.cwd() / ".tmp-tests")
        ):
            driver = WebDriver(browser_name="chromium")
            driver._instance = None
            driver._start()
            self.assertIs(driver.get_page(), page)
            self.assertTrue(browser.accept_downloads)

        driver._page = page
        driver._context = context
        driver._browser = browser
        driver._pw = playwright
        driver.quit_driver()
        self.assertIsNone(driver._page)
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)
        self.assertTrue(playwright.stopped)

    def test_webdriver_window_size_navigation_and_locators(self) -> None:
        driver = WebDriver()
        page = FakePage()
        context = FakeContext(page)
        driver._context = context
        driver._page = page
        driver.browser_name = "chromium"
        driver._apply_preferred_window_size()
        self.assertTrue(context.session.send.called)

        page.evaluate_result = {"width": 0, "height": 0}
        driver._apply_preferred_window_size()
        driver.browser_name = "firefox"
        driver._apply_preferred_window_size()

        driver.browser_name = "chromium"
        driver.get_page = MagicMock(return_value=page)
        driver.navigate_to("https://example.com")
        self.assertEqual(page.last_goto, ("https://example.com", "domcontentloaded"))

        attempts = {"count": 0}

        def flaky_get_page():
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("boom")
            return page

        driver.get_page = MagicMock(side_effect=flaky_get_page)
        with patch("time.sleep"):
            driver.navigate_to2("https://example.com", retries=2, retry_sleep=0)
        self.assertEqual(attempts["count"], 2)

        driver.get_page = MagicMock(side_effect=RuntimeError("boom"))
        with patch("time.sleep"), self.assertRaises(RuntimeError):
            driver.navigate_to2("https://example.com", retries=1, retry_sleep=0)

        page.locators = {
            "css": FakeLocatorCollection([FakeWaitableLocator()]),
            "#demo": FakeLocatorCollection([FakeWaitableLocator()]),
            "xpath=//div": FakeLocatorCollection([FakeWaitableLocator()]),
            "span": FakeLocatorCollection([FakeWaitableLocator(), FakeWaitableLocator()]),
        }
        driver.get_page = MagicMock(return_value=page)
        self.assertIs(driver._to_locator(By.CSS_SELECTOR, "css"), page.locators["css"])
        self.assertIs(driver._to_locator(By.ID, "demo"), page.locators["#demo"])
        self.assertIs(driver._to_locator(By.XPATH, "//div"), page.locators["xpath=//div"])
        self.assertIs(driver._to_locator(By.TAG_NAME, "span"), page.locators["span"])
        with self.assertRaises(ValueError):
            driver._to_locator("bad", "value")

    def test_webdriver_find_helpers_and_set_browser(self) -> None:
        driver = WebDriver()
        first_locator = FakeWaitableLocator()
        locators = FakeLocatorCollection([first_locator, FakeWaitableLocator()])
        page = FakePage()
        page.evaluate = MagicMock()
        driver._to_locator = MagicMock(return_value=locators)
        driver.get_page = MagicMock(return_value=page)
        self.assertIs(driver.find_element(By.CSS_SELECTOR, "x"), first_locator)
        self.assertEqual(len(driver.find_elements(By.CSS_SELECTOR, "x")), 2)

        webdriver_module.PWTimeoutError = RuntimeError
        failing_first = FakeWaitableLocator(wait_error=RuntimeError("wait"))
        locators = FakeLocatorCollection([failing_first])
        driver._to_locator = MagicMock(return_value=locators)
        with self.assertRaises(TimeoutError):
            driver.find_element(By.CSS_SELECTOR, "x", scroll_once=False)

        min_locators = FakeLocatorCollection([FakeWaitableLocator(wait_error=RuntimeError("wait"))])
        driver._to_locator = MagicMock(return_value=min_locators)
        with self.assertRaises(TimeoutError):
            driver.find_elements(By.CSS_SELECTOR, "x", min_count=1)

        driver.browser_name = "chromium"
        driver.set_browser("chromium")
        driver._page = object()
        driver._start = MagicMock()
        driver.quit_driver = MagicMock()
        driver.set_browser("firefox")
        driver.quit_driver.assert_called_once()
        driver._start.assert_called_once()

        driver.find_element = MagicMock(return_value="css")
        driver.find_elements = MagicMock(return_value=["x"])
        self.assertEqual(driver.find_element_css("div"), "css")
        self.assertEqual(driver.find_element_id("demo"), "css")
        self.assertEqual(driver.find_elements_xpath("//a"), ["x"])
        self.assertEqual(driver.find_elements_tag_name("span"), ["x"])

    def test_sources_looper(self) -> None:
        source_accept = MagicMock()
        source_accept.accepts.return_value = True
        source_accept.download.return_value = "path.nbib"
        source_reject = MagicMock()
        source_reject.accepts.return_value = False

        with patch("pyrefman.sources.SourcesLooper.PubMedSource", return_value=source_accept), patch(
            "pyrefman.sources.SourcesLooper.BioRxivSource", return_value=source_reject
        ), patch("pyrefman.sources.SourcesLooper.NCBIGeoSource", return_value=source_reject):
            looper = SourcesLooper(Path.cwd())

        ref = make_inline_reference()
        ref.associate_nbib = MagicMock()
        self.assertTrue(looper.accepts(ref.url))
        looper.fetch_references_from_repos(ref)
        ref.associate_nbib.assert_called_once_with("path.nbib")

        source_accept.download.side_effect = RuntimeError("boom")
        ref.associate_nbib.reset_mock()
        with patch("traceback.print_exc"), patch("builtins.print"):
            looper.fetch_references_from_repos(ref)
        ref.associate_nbib.assert_not_called()

    def test_pubmed_source(self) -> None:
        source = PubMedSource(Path.cwd())
        self.assertTrue(source.accepts("https://pubmed.ncbi.nlm.nih.gov/123/"))
        self.assertTrue(source.accepts("https://pmc.ncbi.nlm.nih.gov/articles/PMC1/"))
        self.assertEqual(source._extract_pmid("https://pubmed.ncbi.nlm.nih.gov/123/"), "123")
        self.assertEqual(source._extract_pmid("https://pmc.ncbi.nlm.nih.gov/articles/PMC1/"), "PMC1")
        self.assertEqual(source._get_base_url("https://pmc.ncbi.nlm.nih.gov/articles/PMC1/"), source.BASE_URL_PMC)

        driver = MagicMock()
        page = FakePage()
        driver.get_page.return_value = page
        driver.find_element.side_effect = [SimpleNamespace(click=lambda: None), RuntimeError("x"), SimpleNamespace(click=lambda: None)]
        with patch("pyrefman.sources.PubMedSource.WebDriver", return_value=driver):
            source._open_citation_ui(is_pmc=True)
            source._open_citation_ui(is_pmc=False)

        driver.find_element.side_effect = RuntimeError("x")
        page.role_clicker = FakeClickTarget(RuntimeError("role"))
        page.text_clicker = FakeClickTarget()
        with patch("pyrefman.sources.PubMedSource.WebDriver", return_value=driver):
            source._open_citation_ui(is_pmc=True)
            source._click_export()

        with patch("pyrefman.sources.PubMedSource.WebDriver", return_value=driver), patch(
            "pyrefman.sources.PubMedSource.expect_download_save_as", return_value=Path("out.nbib")
        ):
            self.assertEqual(source._download_nbib("123", is_pmc=False), Path("out.nbib"))

        with patch.object(source, "_open_citation_ui", side_effect=RuntimeError("boom")), patch(
            "pyrefman.sources.PubMedSource.WebDriver", return_value=driver
        ), patch("builtins.print"):
            self.assertIsNone(source._download_nbib("123", is_pmc=False))

        ref = make_inline_reference(url="https://pubmed.ncbi.nlm.nih.gov/123/")
        with workspace_dir() as tmp_path:
            source = PubMedSource(tmp_path)
            existing = tmp_path / "123.nbib"
            existing.write_text("x", encoding="utf-8")
            self.assertEqual(source.download(ref), existing)

            existing.unlink()
            driver.navigate_to = MagicMock()
            with patch("pyrefman.sources.PubMedSource.WebDriver", return_value=driver), patch.object(
                source, "_download_nbib", return_value=Path("downloaded.nbib")
            ):
                self.assertEqual(source.download(ref), Path("downloaded.nbib"))

        bad_ref = make_inline_reference(url="https://pubmed.ncbi.nlm.nih.gov/")
        with patch("builtins.print"):
            self.assertIsNone(source.download(bad_ref))

    def test_biorxiv_source(self) -> None:
        source = BioRxivSource(Path.cwd())
        self.assertTrue(source.accepts("https://www.biorxiv.org/content/1"))
        self.assertTrue(source._extract_bxid("https://www.biorxiv.org/content/1.abstract").startswith("bxid_"))
        self.assertIsNone(source._extract_bxid("https://www.biorxiv.org/"))

        driver = MagicMock()
        page = FakePage()
        driver.get_page.return_value = page
        driver.find_element.side_effect = [SimpleNamespace(click=lambda: None), RuntimeError("x"), RuntimeError("y"), SimpleNamespace(click=lambda: None)]
        with patch("pyrefman.sources.BioRxivSource.WebDriver", return_value=driver):
            source._open_export_panel()
            source._click_medlars()

        page.role_clicker = FakeClickTarget(RuntimeError("role"))
        page.text_clicker = FakeClickTarget()
        driver.find_element.side_effect = RuntimeError("x")
        with patch("pyrefman.sources.BioRxivSource.WebDriver", return_value=driver):
            source._open_export_panel()
            source._click_medlars()

        ref = make_inline_reference(url="https://www.biorxiv.org/content/1")
        with workspace_dir() as tmp_path:
            source = BioRxivSource(tmp_path)
            target = source._target_path("bxid_demo")
            target.write_text("x", encoding="utf-8")
            with patch.object(source, "_extract_bxid", return_value="bxid_demo"):
                self.assertEqual(source.download(ref), target)

            target.unlink()
            with patch.object(source, "_extract_bxid", return_value="bxid_demo"), patch(
                "pyrefman.sources.BioRxivSource.WebDriver", return_value=driver
            ), patch("pyrefman.sources.BioRxivSource.expect_download_save_as", return_value=Path("bio.nbib")):
                self.assertEqual(source.download(ref), Path("bio.nbib"))

        with patch.object(source, "_extract_bxid", return_value=None), patch("builtins.print"):
            self.assertIsNone(source.download(ref))
        with patch.object(source, "_extract_bxid", return_value="bxid_demo"), patch.object(
            source, "_open_export_panel", side_effect=RuntimeError("boom")
        ), patch("pyrefman.sources.BioRxivSource.WebDriver", return_value=driver), patch("builtins.print"):
            self.assertIsNone(source.download(ref))

    def test_ncbi_geo_source(self) -> None:
        source = NCBIGeoSource(Path.cwd())
        self.assertTrue(source.accepts("https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE1"))
        self.assertEqual(source._extract_accession("https://x?acc=GSE123"), "GSE123")
        self.assertIsNone(source._extract_accession("https://x"))
        self.assertEqual(source._parse_us_date_to_nbib_dp("Mar 5, 2024"), "2024 Mar 05")
        self.assertEqual(source._parse_us_date_to_nbib_dp("March 5, 2024"), "2024 Mar 05")
        self.assertEqual(source._parse_us_date_to_nbib_dp("2024-03-05"), "2024 Mar 05")
        self.assertEqual(source._parse_us_date_to_nbib_dp("Published in 2024"), "2024")
        self.assertIsNone(source._parse_us_date_to_nbib_dp(""))
        self.assertEqual(source._clean_text("  a \n b "), "a b")
        self.assertEqual(source._locator_text(FakeTextLocator(" text ")), "text")
        self.assertEqual(source._locator_text(SimpleNamespace(inner_text=lambda: (_ for _ in ()).throw(RuntimeError()), text_content=lambda: "x")), "x")
        self.assertEqual(source._locator_text(SimpleNamespace(inner_text=lambda: (_ for _ in ()).throw(RuntimeError()), text_content=lambda: (_ for _ in ()).throw(RuntimeError()))), "")

        anchor_one = FakeTextLocator("Author One")
        anchor_two = FakeTextLocator("Author Two")
        self.assertEqual(source._extract_authors_from_cell(FakeTextLocator(anchors=[anchor_one, anchor_two])), ["Author One", "Author Two"])
        self.assertEqual(source._extract_authors_from_cell(FakeTextLocator("A; B, C")), ["A", "B", "C"])

        with workspace_dir() as tmp_path:
            source = NCBIGeoSource(tmp_path)
            existing = tmp_path / "GSE123.nbib"
            existing.write_text("x", encoding="utf-8")
            ref = make_inline_reference(url="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE123")
            self.assertEqual(source.download(ref), existing)

            existing.unlink()
            rows = FakeLocatorCollection(
                [
                    FakeTextLocator(children={"td": FakeLocatorCollection([FakeTextLocator("Title"), FakeTextLocator("Dataset title")])}),
                    FakeTextLocator(children={"td": FakeLocatorCollection([FakeTextLocator("Summary"), FakeTextLocator("Dataset summary")])}),
                    FakeTextLocator(
                        children={
                            "td": FakeLocatorCollection(
                                [FakeTextLocator("Contributor(s)"), FakeTextLocator(anchors=[FakeTextLocator("Doe"), FakeTextLocator("Smith")])]
                            )
                        }
                    ),
                    FakeTextLocator(children={"td": FakeLocatorCollection([FakeTextLocator("Submission date"), FakeTextLocator("Mar 5, 2024")])}),
                    FakeTextLocator(children={"td": FakeLocatorCollection([FakeTextLocator("Last update date"), FakeTextLocator("Apr 1, 2024")])}),
                ]
            )
            strong = SimpleNamespace(locator=lambda selector: rows)
            page = SimpleNamespace(locator=lambda selector: rows)
            driver = MagicMock()
            driver.navigate_to = MagicMock()
            driver.get_page.return_value = page
            driver.find_element.side_effect = [strong]

            with patch("pyrefman.sources.NCBIGeoSource.WebDriver", return_value=driver):
                written = source.download(ref)
            self.assertTrue(written.exists())
            self.assertIn("Dataset title", written.read_text(encoding="utf-8"))

            driver.find_element.side_effect = [RuntimeError("x"), RuntimeError("y")]
            page = SimpleNamespace(locator=lambda selector: rows)
            driver.get_page.return_value = page
            failing_ref = make_inline_reference(url="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE999")
            with patch("pyrefman.sources.NCBIGeoSource.WebDriver", return_value=driver), patch(
                "builtins.open", side_effect=PermissionError("nope")
            ), patch("builtins.print"):
                self.assertIsNone(source.download(failing_ref))

        bad_ref = make_inline_reference(url="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=")
        with patch("builtins.print"):
            self.assertIsNone(source.download(bad_ref))

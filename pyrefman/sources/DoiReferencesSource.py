import re
from pathlib import Path
from typing import Optional

from pyrefman.Utils import (
    bibtex_to_nbib,
    normalize_doi_query,
    sanitize_doi_filename,
)
from pyrefman.WebDriver import WebDriver, By
from pyrefman.data.InlineReference import InlineReference
from pyrefman.sources.ReferencesSource import ReferencesSource


class DoiReferencesSource(ReferencesSource):
    DOI_URL_PREFIX = "https://doi.org/"
    SCHOLAR_URL = "https://scholar.google.com/"
    SEARCH_INPUT_SELECTOR = "input#gs_hdr_tsi"
    RESULTS_CONTAINER_SELECTOR = "div#gs_res_ccl_mid"
    RESULT_CARD_SELECTOR = f"{RESULTS_CONTAINER_SELECTOR} div.gs_scl"
    CITE_BUTTON_SELECTOR = "a.gs_or_cit"
    BIBTEX_LINK_SELECTOR = "a.gs_citi"
    EXPORT_TIMEOUT = 30

    def accepts(self, url: str) -> bool:
        return str(url or "").strip().lower().startswith(self.DOI_URL_PREFIX)

    def _normalize_query(self, url: str) -> str:
        return normalize_doi_query(url)

    def _target_path(self, doi_url: str) -> Path:
        safe_id = sanitize_doi_filename(self._normalize_query(doi_url))
        return self.citations_dir / f"{safe_id}.nbib"

    def _locator_text(self, locator) -> str:
        try:
            text = locator.inner_text()
        except Exception:
            text = locator.text_content() or ""
        return re.sub(r"\s+", " ", text or "").strip()

    def _search_scholar(self, doi_query: str, timeout_s: int = EXPORT_TIMEOUT) -> None:
        driver = WebDriver()
        page = driver.get_page()
        driver.navigate_to(self.SCHOLAR_URL)

        search_input = driver.find_element(
            By.CSS_SELECTOR,
            self.SEARCH_INPUT_SELECTOR,
            timeout=timeout_s,
            state="visible",
        )
        search_input.fill(doi_query)
        search_input.press("Enter")
        driver.find_element(
            By.CSS_SELECTOR,
            self.RESULTS_CONTAINER_SELECTOR,
            timeout=timeout_s,
            state="attached",
        )
        page.wait_for_load_state("domcontentloaded")

    def _find_single_citable_result(self, timeout_s: int = EXPORT_TIMEOUT):
        driver = WebDriver()
        cards = driver.find_elements(
            By.CSS_SELECTOR,
            self.RESULT_CARD_SELECTOR,
            timeout=timeout_s,
            min_count=1,
            state="attached",
        )
        if len(cards) != 1:
            raise RuntimeError(f"Expected exactly one Google Scholar result, found {len(cards)}.")

        card = cards[0]
        if card.locator(self.CITE_BUTTON_SELECTOR).count() == 0:
            raise RuntimeError("Google Scholar result did not expose a cite button.")
        return card

    def _find_bibtex_link(self, timeout_s: int = EXPORT_TIMEOUT):
        driver = WebDriver()
        links = driver.find_elements(
            By.CSS_SELECTOR,
            self.BIBTEX_LINK_SELECTOR,
            timeout=timeout_s,
            min_count=1,
            state="visible",
        )
        for link in links:
            link_text = self._locator_text(link).lower()
            href = (link.get_attribute("href") or "").lower()
            if link_text == "bibtex" or "scholar.bib" in href:
                return link
        raise RuntimeError("Could not find the BibTeX link in the Scholar citation popup.")

    def _read_plain_text_bibtex(self, timeout_s: int = EXPORT_TIMEOUT) -> str:
        page = WebDriver().get_page()
        timeout_ms = int(timeout_s * 1000)

        try:
            pre = page.locator("pre").first
            pre.wait_for(state="visible", timeout=timeout_ms)
            text = self._locator_text(pre)
            if text:
                return text
        except Exception:
            pass

        body = page.locator("body").first
        body.wait_for(state="attached", timeout=timeout_ms)
        text = self._locator_text(body)
        if text:
            return text
        raise RuntimeError("BibTeX page did not contain readable text.")

    def _fetch_nbib_from_scholar(self, doi_query: str, timeout_s: int = EXPORT_TIMEOUT) -> str:
        page = WebDriver().get_page()
        self._search_scholar(doi_query, timeout_s=timeout_s)

        result = self._find_single_citable_result(timeout_s=timeout_s)
        result.locator(self.CITE_BUTTON_SELECTOR).first.click()

        bibtex_link = self._find_bibtex_link(timeout_s=timeout_s)
        bibtex_link.click()
        page.wait_for_load_state("domcontentloaded")

        bibtex_text = self._read_plain_text_bibtex(timeout_s=timeout_s)
        return bibtex_to_nbib(bibtex_text, doi_url=doi_query)

    def download(self, reference: InlineReference) -> Optional[Path]:
        if not self.accepts(reference.url):
            print(f"[SKIP] Invalid DOI url from {reference.url}")
            return None
        doi_query = self._normalize_query(reference.url)

        target = self._target_path(doi_query)
        if target.exists():
            return target

        print(f"[DOWNLOAD] {doi_query}")
        try:
            nbib_text = self._fetch_nbib_from_scholar(doi_query, timeout_s=self.EXPORT_TIMEOUT)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(nbib_text, encoding="utf-8")
            return target
        except Exception as exc:
            print(f"[ERROR] Could not download DOI reference for {doi_query}: {exc}")
            return None

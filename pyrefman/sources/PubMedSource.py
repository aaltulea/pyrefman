import re
from pathlib import Path
from typing import Optional

from pyrefman.data.InlineReference import InlineReference
from pyrefman.sources.ReferencesSource import ReferencesSource
from pyrefman.WebDriver import WebDriver, By, expect_download_save_as


class PubMedSource(ReferencesSource):
    BASE_URL_PUBMED = "https://pubmed.ncbi.nlm.nih.gov/"
    BASE_URL_PMC = "https://pmc.ncbi.nlm.nih.gov/articles/"

    def accepts(self, url: str) -> bool:
        return self.BASE_URL_PUBMED[:-1] in url or self.BASE_URL_PMC[:-1] in url

    def __init__(self, citations_dir):
        super().__init__(citations_dir)

    def _extract_pmid(self, url: str) -> str:
        pmid = url.rstrip("/ ").split("/")[-1].strip()
        if self.BASE_URL_PUBMED[:-1] in url:
            pmid = re.sub(r"\D", "", pmid)
        return pmid

    def _get_base_url(self, url: str) -> str:
        return self.BASE_URL_PMC if self.BASE_URL_PMC[:-1] in url else self.BASE_URL_PUBMED

    def _target_path(self, pmid: str) -> Path:
        return self.citations_dir / f"{pmid}.nbib"

    def _open_citation_ui(self, is_pmc: bool, timeout_s: int = 30) -> None:
        driver = WebDriver()
        page = driver.get_page()
        timeout_ms = int(timeout_s * 1000)

        if is_pmc:
            try:
                driver.find_element(
                    By.CSS_SELECTOR,
                    ".usa-list--actions > li:nth-child(3) > button:nth-child(1)",
                    timeout=timeout_s,
                    state="visible",
                ).click()
                return
            except Exception:
                pass
            # fallbacks
            try:
                page.get_by_role("button", name=re.compile(r"cite|citation", re.I)).click(timeout=timeout_ms)
                return
            except Exception:
                page.get_by_text(re.compile(r"cite|citation", re.I)).click(timeout=timeout_ms)
        else:
            try:
                driver.find_element(
                    By.CSS_SELECTOR,
                    "button.citation-button:nth-child(1)",
                    timeout=timeout_s,
                    state="visible",
                ).click()
                return
            except Exception:
                pass
            # fallbacks
            try:
                page.get_by_role("button", name=re.compile(r"cite", re.I)).click(timeout=timeout_ms)
                return
            except Exception:
                page.get_by_text(re.compile(r"cite", re.I)).click(timeout=timeout_ms)

    def _click_export(self, timeout_s: int = 30) -> None:
        driver = WebDriver()
        page = driver.get_page()
        timeout_ms = int(timeout_s * 1000)

        # primary selector you used before
        try:
            driver.find_element(By.CSS_SELECTOR, ".export-button", timeout=timeout_s, state="visible").click()
            return
        except Exception:
            pass

        # fallbacks
        for rx in (r"download", r"export", r"save"):
            try:
                page.get_by_role("button", name=re.compile(rx, re.I)).click(timeout=timeout_ms)
                return
            except Exception:
                continue
        page.get_by_text(re.compile(r"download|export|save", re.I)).click(timeout=timeout_ms)

    def _download_nbib(self, pmid: str, is_pmc: bool, timeout_s: int = 30) -> Optional[Path]:
        driver = WebDriver()
        page = driver.get_page()
        target = self._target_path(pmid)

        try:
            self._open_citation_ui(is_pmc=is_pmc, timeout_s=timeout_s)
            return expect_download_save_as(
                page=page,
                click_fn=lambda: self._click_export(timeout_s=timeout_s),
                target_path=target,
                timeout_s=timeout_s,
            )
        except Exception as e:
            print(f"[ERROR] Download failed for {pmid} (is_pmc={is_pmc}): {e}")
            return None

    def download(self, reference: InlineReference) -> Optional[Path]:
        pmid = self._extract_pmid(reference.url)
        base_url = self._get_base_url(reference.url)
        is_pmc = base_url == self.BASE_URL_PMC

        if not pmid:
            print(f"[SKIP] Invalid PubMed identifier from {reference.url}")
            return None

        target_file = self._target_path(pmid)
        if target_file.exists():
            return target_file

        url = f"{base_url}{pmid}/"
        print(f"[DOWNLOAD] {url} for {pmid}")
        WebDriver().navigate_to(url)
        return self._download_nbib(pmid, is_pmc=is_pmc, timeout_s=30)

import re
from pathlib import Path
from typing import Optional

from pyrefman.WebDriver import WebDriver, By, expect_download_save_as
from pyrefman.Utils import safe_filename
from pyrefman.data.InlineReference import InlineReference
from pyrefman.sources.ReferencesSource import ReferencesSource


class BioRxivSource(ReferencesSource):
    BASE_URL = "https://www.biorxiv.org/"
    EXPORT_TIMEOUT = 30  # seconds

    def accepts(self, url: str) -> bool:
        return self.BASE_URL[:-1] in url

    def _extract_bxid(self, url: str) -> Optional[str]:
        raw = (
            url.replace(self.BASE_URL, "")
            .replace("content", "")
            .replace(".abstract", "")
            .replace(".full-text", "")
        )
        cleaned = safe_filename(raw)
        return f"bxid_{cleaned}" if cleaned else None

    def _target_path(self, bxid: str) -> Path:
        return self.citations_dir / f"{bxid}.medlars"

    def _open_export_panel(self, timeout_s: int = 30) -> None:
        driver = WebDriver()
        page = driver.get_page()
        timeout_ms = int(timeout_s * 1000)

        try:
            driver.find_element(
                By.CSS_SELECTOR,
                "div.pane-minipanel-dialog-link:nth-child(7) > "
                "div:nth-child(1) > div:nth-child(1) > "
                "div:nth-child(1) > a:nth-child(1) > span:nth-child(2)",
                timeout=timeout_s,
                state="visible",
            ).click()
            return
        except Exception:
            pass

        # fallbacks
        try:
            page.get_by_role("link", name=re.compile(r"cite|citation|tools|download", re.I)).click(timeout=timeout_ms)
            return
        except Exception:
            page.get_by_text(re.compile(r"cite|citation|tools|download", re.I)).click(timeout=timeout_ms)

    def _click_medlars(self, timeout_s: int = 30) -> None:
        driver = WebDriver()
        page = driver.get_page()
        timeout_ms = int(timeout_s * 1000)

        try:
            driver.find_element(By.CSS_SELECTOR, ".medlars > a:nth-child(1)", timeout=timeout_s,
                                state="visible").click()
            return
        except Exception:
            pass

        try:
            page.get_by_role("link", name=re.compile(r"medlars", re.I)).click(timeout=timeout_ms)
            return
        except Exception:
            page.get_by_text(re.compile(r"medlars", re.I)).click(timeout=timeout_ms)

    def download(self, reference: InlineReference) -> Optional[Path]:
        bxid = self._extract_bxid(reference.url)
        if not bxid:
            print(f"[SKIP] {bxid} is not valid from {reference.url}")
            return None

        target = self._target_path(bxid)
        if target.exists():
            return target

        print(f"[DOWNLOAD] {reference.url} for {bxid}")
        WebDriver().navigate_to(reference.url)

        driver = WebDriver()
        page = driver.get_page()

        try:
            self._open_export_panel(timeout_s=self.EXPORT_TIMEOUT)
            return expect_download_save_as(
                page=page,
                click_fn=lambda: self._click_medlars(timeout_s=self.EXPORT_TIMEOUT),
                target_path=target,
                timeout_s=self.EXPORT_TIMEOUT,
            )
        except Exception as e:
            print(f"[ERROR] Timeout / failure downloading {bxid}.medlars: {e}")
            return None

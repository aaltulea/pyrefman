import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from pyrefman.WebDriver import WebDriver, By
from pyrefman.Utils import safe_filename
from pyrefman.data.InlineReference import InlineReference
from pyrefman.sources.ReferencesSource import ReferencesSource


class NCBIGeoSource(ReferencesSource):
    BASE_URL = "https://www.ncbi.nlm.nih.gov/geo/"

    def accepts(self, url: str) -> bool:
        return self.BASE_URL[:-1] in url and "acc=" in url

    def _extract_accession(self, url: str) -> Optional[str]:
        m = re.search(r"(GSE\d+)", url, re.IGNORECASE)
        if m:
            return m.group(1).upper()
        return None

    def _parse_us_date_to_nbib_dp(self, date_str: str) -> Optional[str]:
        date_str = (date_str or "").strip()
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime("%Y %b %d")
            except Exception:
                continue
        y = re.search(r"(\d{4})", date_str)
        if y:
            return y.group(1)
        return None

    def _clean_text(self, s: Optional[str]) -> str:
        if not s:
            return ""
        return re.sub(r"\s+", " ", s).strip()

    def _locator_text(self, loc) -> str:
        """
        Robustly get text from a Playwright Locator. Prefers inner_text, falls back to text_content.
        """
        try:
            return self._clean_text(loc.inner_text())
        except Exception:
            try:
                return self._clean_text(loc.text_content() or "")
            except Exception:
                return ""

    def _extract_authors_from_cell(self, cell_locator) -> List[str]:
        """
        Authors often appear as <a> elements in the GEO table.
        """
        authors: List[str] = []
        try:
            anchors = cell_locator.locator("a")
            n = anchors.count()
            if n:
                for i in range(n):
                    name = self._locator_text(anchors.nth(i))
                    if name:
                        authors.append(name)
                if authors:
                    return authors
        except Exception:
            pass

        # fallback: raw text split by commas/semicolons/newlines
        raw = self._locator_text(cell_locator)
        parts = [p.strip() for p in re.split(r"[,;\n]", raw) if p.strip()]
        return parts

    def download(self, reference: InlineReference) -> Optional[Path]:
        accession = self._extract_accession(reference.url or "")
        if not accession:
            print(f"[SKIP] Could not extract GEO accession from {reference.url}")
            return None

        safe_id = safe_filename(accession)
        target = self.citations_dir / f"{safe_id}.nbib"
        if target.exists():
            return target

        print(f"[DOWNLOAD] loading GEO page {reference.url} for {accession}")
        driver = WebDriver()
        driver.navigate_to(reference.url)
        page = driver.get_page()

        # Try to find <strong class="acc" id="{accession}">
        strong_elem = None
        try:
            strong_elem = driver.find_element(
                By.XPATH,
                f"//strong[contains(@class,'acc') and normalize-space(@id)='{accession}']",
                timeout=30,
                state="attached",
            )
        except Exception:
            # fallback: any element containing the accession text
            try:
                strong_elem = driver.find_element(By.XPATH, f"//*[contains(normalize-space(.),'{accession}')]", timeout=15)
            except Exception:
                strong_elem = None

        # Collect rows likely containing key/value metadata
        rows = None
        if strong_elem is not None:
            try:
                # IMPORTANT: in Playwright, use xpath= prefix inside locator()
                rows = strong_elem.locator("xpath=./ancestor::tr/following-sibling::tr")
            except Exception:
                rows = None

        if rows is None or rows.count() == 0:
            # fallback: grab all table rows from body (GEO pages are small enough)
            rows = page.locator("tr")

        # Parse key/value pairs from rows
        info: Dict[str, Dict[str, Any]] = {}
        row_count = rows.count()

        for i in range(row_count):
            row = rows.nth(i)
            try:
                tds = row.locator("td")
                if tds.count() < 2:
                    continue

                key = self._locator_text(tds.nth(0))
                if not key:
                    continue

                # skip non-key rows / headers
                if key.startswith("Series") or key.lower().startswith("relations"):
                    continue

                value_cell = tds.nth(1)
                value_text = self._locator_text(value_cell)

                key_norm = key.lower().replace(":", "").strip()
                info[key_norm] = {"raw": value_text, "element": value_cell}
            except Exception:
                continue

        # Map fields
        title = ""
        summary = ""
        authors: List[str] = []
        submission_date = None
        last_update_date = None

        # Title
        if "title" in info:
            title = info["title"]["raw"]

        # Summary / Abstract
        for k in ("summary", "abstract"):
            if k in info:
                summary = info[k]["raw"]
                break

        # Contributors / Authors
        for k in ("contributor(s)", "contributors", "contributor"):
            if k in info:
                authors = self._extract_authors_from_cell(info[k]["element"])
                if not authors:
                    authors = [a.strip() for a in (info[k]["raw"] or "").split(",") if a.strip()]
                break

        # Dates
        for k in ("submission date", "submission", "submission date(s)"):
            if k in info:
                submission_date = self._parse_us_date_to_nbib_dp(info[k]["raw"])
                break

        if not submission_date:
            for k in ("status", "last update date"):
                if k in info:
                    date_match = re.search(r"([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})", info[k]["raw"] or "")
                    if date_match:
                        submission_date = self._parse_us_date_to_nbib_dp(date_match.group(1))
                        break

        if "last update date" in info:
            last_update_date = self._parse_us_date_to_nbib_dp(info["last update date"]["raw"])

        # If authors still empty, try contact name, else scan for pubmed-ish author links
        if not authors:
            if "contact name" in info and info["contact name"]["raw"]:
                authors = [info["contact name"]["raw"]]
            else:
                try:
                    anchors = page.locator("xpath=//a[contains(@href,'/pubmed/?term=') or contains(@href,'/pubmed/')]")
                    n = anchors.count()
                    names: List[str] = []
                    for i in range(n):
                        txt = self._locator_text(anchors.nth(i))
                        if txt and re.search(r"[A-Za-z]", txt):
                            names.append(txt)

                    # dedupe preserve order
                    seen = set()
                    dedup = []
                    for n_ in names:
                        if n_ not in seen:
                            seen.add(n_)
                            dedup.append(n_)
                    if dedup:
                        authors = dedup
                except Exception:
                    pass

        # Build NBIB
        nbib_lines: List[str] = []
        nbib_lines.append("PT  - DATASET")
        for au in authors:
            nbib_lines.append(f"AU  - {au}")
        if title:
            nbib_lines.append(f"TI  - {title}")
        nbib_lines.append(f"AID  - {accession}")
        nbib_lines.append(f"PG  - {accession}")
        if submission_date:
            nbib_lines.append(f"DP  - {submission_date}")
        nbib_lines.append("TA  - NCBI GEO")
        nbib_lines.append(f"4099  - {reference.url}")
        nbib_lines.append(f"4100  - {reference.url}")
        if summary:
            ab_clean = (summary or "").replace("\r\n", "\n").strip()
            nbib_lines.append(f"AB  - {ab_clean}")
        if last_update_date:
            nbib_lines.append(f"NOTE  - Last update: {last_update_date}")

        nbib_content = "\n".join(nbib_lines) + "\n"

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(nbib_content)
            return target
        except Exception as e:
            print(f"[ERROR] Could not write nbib for {accession}: {e}")
            return None

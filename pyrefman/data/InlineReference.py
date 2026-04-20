import os.path
import re
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, List
from pyrefman.NBIBParser import NBIBParser
from pyrefman.Utils import extract_markdown_url


@dataclass
class InlineReference:
    inline_text: str
    inline_index: int = field(default=None)
    nbib_path: str = field(default=None)
    parsed_nbib: Dict[str, object] = field(default=None)
    url: str = field(init=False)

    def __post_init__(self):
        self.url = extract_markdown_url(self.inline_text)

    def __str__(self):
        return f"{self.url}"

    def __repr__(self):
        return self.__str__()

    def associate_nbib(self, nbib_path):
        if os.path.exists(nbib_path):
            self.nbib_path = nbib_path
            try:
                self.parsed_nbib = NBIBParser.parse(Path(self.nbib_path))
            except Exception:
                print(f"[ERROR] {self.nbib_path} raised an exception")
                traceback.print_exc()
                raise
        else:
            print(f"[Warning] {self.nbib_path} does not exist or is inaccessible")

    def nbib_entries(self) -> Optional[Dict[str, object]]:
        return self.parsed_nbib

    def get_nbib_field(self, *keys: str) -> Optional[object]:
        nbib_entries = self.nbib_entries()
        if not isinstance(nbib_entries, dict):
            return None
        for k in keys:
            if k in nbib_entries and nbib_entries[k]:
                return nbib_entries[k]
        return None

    def get_nbib_title(self) -> str:
        title = self.get_nbib_field("TI") or self.get_nbib_field("title") or ""
        if isinstance(title, list):
            title = title[0] if title else ""
        title = (title or "").strip()
        if title and not title.endswith("."):
            title = title + "."
        return title

    def get_nbib_volume(self) -> str:
        volume = self.get_nbib_field("VI") or self.get_nbib_field("VOLUME") or ""
        if isinstance(volume, list):
            volume = volume[0] if volume else ""

        return (volume or "").strip()

    def get_nbib_issue(self) -> str:
        issue = self.get_nbib_field("IP") or self.get_nbib_field("ISSUE") or ""
        if isinstance(issue, list):
            issue = issue[0] if issue else ""
        return (issue or "").strip()

    def get_nbib_pages(self) -> str:
        pages = (
                self.get_nbib_field("PG")
                or self.get_nbib_field("PGS")
                or self.get_nbib_field("PAGES")
                or ""
        )
        if isinstance(pages, list):
            pages = pages[0] if pages else ""
        return (pages or "").strip()

    def get_nbib_pmid(self) -> str:
        # prefer TA, fall back to JT or SO parsed
        return (self.get_nbib_field("PMID") or "").strip()

    def get_nbib_journal(self) -> str:
        # prefer TA, fall back to JT or SO parsed
        journal = self.get_nbib_field("TA") or self.get_nbib_field("JT") or ""
        if isinstance(journal, list):
            journal = journal[0] if journal else ""
        journal = (journal or "").strip()
        return journal

    def get_nbib_dp(self) -> str:
        dp = self.get_nbib_field("DP") or ""
        if isinstance(dp, list):
            dp = dp[0] if dp else ""
        dp = (dp or "").strip()
        return dp

    def get_nbib_so(self) -> str:
        so_raw = self.get_nbib_field("SO") or ""
        if isinstance(so_raw, list):
            so_raw = so_raw[0] if so_raw else ""
        so_raw = (so_raw or "").strip()
        return so_raw

    @staticmethod
    def _format_author_from_fau(fau_name: str) -> str:
        # FAU looks like "Last, Given Names"
        parts = [p.strip() for p in fau_name.split(",")]
        last = parts[0]
        given = parts[1] if len(parts) > 1 else ""
        # build initials from given names (take first letter of each part)
        initials = "".join([p[0] for p in given.split() if p])
        return f"{last} {initials}".strip()

    @staticmethod
    def _format_author_from_au(au_name: str) -> str:
        # AU often already like "Last FM" or "Last F M"
        return au_name.strip()

    def get_nbib_authors_list(self) -> List[str]:
        authors_list: List[str] = []
        fau = self.get_nbib_field("FAU")
        au = self.get_nbib_field("AU")

        if fau:
            if isinstance(fau, list):
                authors_list = [
                    self._format_author_from_fau(n)
                    for n in fau
                    if n and n.strip()
                ]
            elif isinstance(fau, str) and fau.strip():
                authors_list = [self._format_author_from_fau(fau)]

        elif au:
            if isinstance(au, list):
                authors_list = [
                    self._format_author_from_au(n)
                    for n in au
                    if n and n.strip()
                ]
            elif isinstance(au, str) and au.strip():
                authors_list = [self._format_author_from_au(au)]

        return authors_list

    def get_linearized_authors(self) -> str:
        authors_str = ""
        authors = self.get_nbib_authors_list()
        if authors:
            if len(authors) > 6:
                authors_str = ", ".join(authors[:6]) + ", et al."
            else:
                authors_str = ", ".join(authors) + "."
        return authors_str

    def get_nbib_doi(self) -> Optional[str]:
        aid = self.get_nbib_field("AID")
        if isinstance(aid, list):
            # find element containing doi
            for a in aid:
                if a and "[doi]" in a.lower():
                    return re.sub(r"\s*\[doi\]\s*$", "", a, flags=re.IGNORECASE).strip()
            # fallback: any string that looks like doi
            for a in aid:
                if a and re.search(r"\d{2}\.\d{4,9}/", a):
                    return a.strip()
        elif isinstance(aid, str) and aid:
            if "[doi]" in aid.lower():
                return re.sub(r"\s*\[doi\]\s*$", "", aid, flags=re.IGNORECASE).strip()
            if re.search(r"\d{2}\.\d{4,9}/", aid):
                return aid.strip()
        # Try SO field
        so = self.get_nbib_field("SO")
        if isinstance(so, list):
            so = so[0] if so else ""
        so = so or ""
        m = re.search(r"(10\.\d{4,9}/\S+)", so)
        if m:
            return m.group(1).strip().rstrip(".")
        # Try any DOI-like key
        doi_field = self.get_nbib_field("DOI")
        if doi_field:
            return str(doi_field).strip()
        return None

    def nbib_summary(self) -> str:
        return f"{self.get_nbib_title()}, {self.get_nbib_doi()}, {self.get_nbib_journal()} {self.get_nbib_volume()} {self.get_nbib_issue()}"

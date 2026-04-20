import re
from typing import Optional, List, Tuple

from pyrefman.data.FormattedReference import FormattedReference
from pyrefman.data.InlineReference import InlineReference
from pyrefman.styles.ReferencesStyle import ReferencesStyle


class APAStyle(ReferencesStyle):
    def describe_style(self) -> str:
        return "Author-date citations with a full reference list in APA style."

    # ------------------------------------------------------------------
    # Sorting
    # ------------------------------------------------------------------
    def sort_formatted_references(self, references: List[FormattedReference]) -> List[FormattedReference]:
        return sorted(
            references,
            key=lambda r: self._reference_sort_key(r.inline_reference)
        )

    def _reference_sort_key(self, inline_reference) -> Tuple[str, str, str]:
        authors = self.get_authors(inline_reference) or []
        first_author = self._author_family_name(authors[0]) if authors else ""
        year = self.get_year(inline_reference) or ""
        title = (self.get_title(inline_reference) or "").lower()
        return (first_author.lower(), year, title)

    # ------------------------------------------------------------------
    # Grouped inline citations
    # Example: (Smith, 2020; Zhao & Lee, 2021)
    # ------------------------------------------------------------------
    def format_grouped_inline_references(self, references: List["FormattedReference"]) -> str:
        if not references:
            return "()"

        unique = {}
        for fr in references:
            key = self._reference_sort_key(fr.inline_reference)
            unique[key] = fr.inline_reference

        ordered = [unique[k] for k in sorted(unique.keys())]
        inner = "; ".join(self._get_parenthetical_citation(ir) for ir in ordered)
        return f"({inner})"

    # ------------------------------------------------------------------
    # Date helpers
    # ------------------------------------------------------------------
    def get_year(self, inline_reference) -> Optional[str]:
        dp = self.get_dp(inline_reference)
        if not dp:
            return None

        match = re.search(r"\b(19|20)\d{2}\b", dp)
        return match.group(0) if match else None

    # ------------------------------------------------------------------
    # Inline citation
    # Example: (Smith et al., 2020)
    # ------------------------------------------------------------------
    def get_inline_reference(self, inline_reference) -> str:
        return f"({self._get_parenthetical_citation(inline_reference)})"

    def _get_parenthetical_citation(self, inline_reference) -> str:
        authors = self.get_authors(inline_reference) or []
        year = self.get_year(inline_reference) or "n.d."

        if not authors:
            title = self.get_title(inline_reference) or "Untitled"
            short_title = self._short_title_for_citation(title)
            return f"{short_title}, {year}"

        if len(authors) == 1:
            author_part = self._author_family_name(authors[0])
        elif len(authors) == 2:
            author_part = f"{self._author_family_name(authors[0])} & {self._author_family_name(authors[1])}"
        else:
            author_part = f"{self._author_family_name(authors[0])} et al."

        return f"{author_part}, {year}"

    # ------------------------------------------------------------------
    # Full reference
    # APA journal article:
    # Author, A. A., & Author, B. B. (2020). Title. Journal, 12(3), 45-56. https://doi.org/...
    # ------------------------------------------------------------------
    def get_full_reference(self, inline_reference) -> str:
        parts = []

        # Authors
        authors = self.get_authors(inline_reference) or []
        if authors:
            parts.append(self._format_apa_authors(authors))
        else:
            parts.append("")

        # Year
        year = self.get_year(inline_reference) or "n.d."
        parts.append(f"({year}).")

        # Title
        title = self.get_title(inline_reference)
        if title:
            parts.append(self._ensure_terminal_punctuation(title, "."))

        # Journal / volume / issue / pages
        journal_block = self._build_journal_block(inline_reference)
        if journal_block:
            parts.append(journal_block)

        # DOI
        doi = self.get_doi(inline_reference)
        if doi:
            parts.append(self._normalize_doi(doi))

        full = " ".join(p.strip() for p in parts if p and p.strip())
        full = re.sub(r"\s+", " ", full).strip()

        # APA does not put a trailing period after DOI/URL
        if re.search(r"https?://doi\.org/\S+$", full):
            return full

        return self._ensure_terminal_punctuation(full, ".")

    def _build_journal_block(self, inline_reference) -> Optional[str]:
        journal = self.get_journal(inline_reference)
        volume = self.get_volume(inline_reference)
        issue = self.get_issue(inline_reference)
        pages = self.get_pages(inline_reference)

        if not journal and not volume and not issue and not pages:
            return None

        block = journal or ""

        if volume:
            if block:
                block += f", {volume}"
            else:
                block += volume

        if issue:
            block += f"({issue})"

        if pages:
            clean_pages = pages.replace("p.", "").strip()
            if block:
                block += f", {clean_pages}"
            else:
                block += clean_pages

        return self._ensure_terminal_punctuation(block, ".")

    # ------------------------------------------------------------------
    # Public formatter
    # ------------------------------------------------------------------
    def format_reference(self, inline_reference: InlineReference) -> FormattedReference:
        full = self.get_full_reference(inline_reference)
        inline_ref = self.get_inline_reference(inline_reference)
        return FormattedReference(_inline=inline_ref, _full=full)

    # ------------------------------------------------------------------
    # Author formatting helpers
    # ------------------------------------------------------------------
    def _format_apa_authors(self, authors: List[str]) -> str:
        formatted = [self._to_apa_author_name(a) for a in authors if a and a.strip()]

        if not formatted:
            return ""

        # APA 7: up to 20 authors listed; for 21+, list first 19, ellipsis, final author
        if len(formatted) > 20:
            formatted = formatted[:19] + ["..."] + [formatted[-1]]

        if len(formatted) == 1:
            return self._ensure_terminal_punctuation(formatted[0], ".")

        if len(formatted) == 2:
            return f"{formatted[0]}, & {formatted[1]}."

        return f"{', '.join(formatted[:-1])}, & {formatted[-1]}."

    def _to_apa_author_name(self, raw_name: str) -> str:
        raw_name = raw_name.strip()
        if not raw_name:
            return ""

        # Already in "Surname, X. X."-ish shape
        if "," in raw_name:
            family, given = [p.strip() for p in raw_name.split(",", 1)]
            initials = self._given_names_to_initials(given)
            return f"{family}, {initials}".strip().rstrip(",")

        tokens = raw_name.split()
        if len(tokens) == 1:
            return tokens[0]

        # Common PubMed-like pattern: "Smith JA"
        if self._looks_like_initials(tokens[-1]):
            family = " ".join(tokens[:-1])
            given = tokens[-1]
            initials = self._given_names_to_initials(given)
            return f"{family}, {initials}".strip().rstrip(",")

        # Less common: "JA Smith"
        if self._looks_like_initials(tokens[0]):
            given = tokens[0]
            family = " ".join(tokens[1:])
            initials = self._given_names_to_initials(given)
            return f"{family}, {initials}".strip().rstrip(",")

        # Fallback: assume "Given Middle Family"
        family = tokens[-1]
        given = " ".join(tokens[:-1])
        initials = self._given_names_to_initials(given)
        return f"{family}, {initials}".strip().rstrip(",")

    def _author_family_name(self, raw_name: str) -> str:
        raw_name = raw_name.strip()
        if not raw_name:
            return ""

        if "," in raw_name:
            return raw_name.split(",", 1)[0].strip()

        tokens = raw_name.split()
        if len(tokens) == 1:
            return tokens[0]

        # PubMed-like: "Smith JA"
        if self._looks_like_initials(tokens[-1]):
            return " ".join(tokens[:-1]).strip()

        # "JA Smith"
        if self._looks_like_initials(tokens[0]):
            return " ".join(tokens[1:]).strip()

        # Fallback: last token as surname
        return tokens[-1].strip()

    def _given_names_to_initials(self, given: str) -> str:
        given = given.strip()
        if not given:
            return ""

        parts = re.split(r"\s+", given)
        initials = []

        for part in parts:
            part = part.strip()
            if "-" in part:
                hyphen_parts = [p for p in part.split("-") if p]
                hyphen_initials = "-".join(self._token_to_initial(p) for p in hyphen_parts)
                if hyphen_initials:
                    initials.append(hyphen_initials)
            else:
                init = self._token_to_initial(part)
                if init:
                    initials.append(init)

        return " ".join(initials)

    def _token_to_initial(self, token: str) -> str:
        clean = re.sub(r"[^A-Za-z]", "", token)
        if not clean:
            return ""

        # e.g. "JA" -> "J. A."
        if len(clean) > 1 and clean.isupper():
            return " ".join(f"{ch}." for ch in clean)

        return f"{clean[0].upper()}."

    def _looks_like_initials(self, token: str) -> bool:
        clean = re.sub(r"[^A-Za-z]", "", token)
        if not clean:
            return False
        return clean.isupper() and len(clean) <= 5

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------
    def _normalize_doi(self, doi: str) -> str:
        doi = doi.strip()

        doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)

        return f"https://doi.org/{doi}"

    def _short_title_for_citation(self, title: str, max_words: int = 4) -> str:
        words = re.findall(r"\w+(?:[-']\w+)*", title)
        short = " ".join(words[:max_words]) if words else title
        return f'"{short}"'

    def _ensure_terminal_punctuation(self, text: str, punct: str = ".") -> str:
        text = text.strip()
        if not text:
            return text
        if text.endswith((".", "!", "?")):
            return text
        return text + punct
        

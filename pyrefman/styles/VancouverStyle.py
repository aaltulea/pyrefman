import re
from typing import Optional, List

from pyrefman.data.FormattedReference import FormattedReference
from pyrefman.data.InlineReference import InlineReference
from pyrefman.styles.ReferencesStyle import ReferencesStyle


class VancouverStyle(ReferencesStyle):
    def describe_style(self) -> str:
        return "Classic numbered citations with a full reference list in Vancouver format."

    def sort_formatted_references(self, references: List[FormattedReference]) -> List[FormattedReference]:
        return sorted(references, key=lambda r: r.inline_reference.inline_index)

    from typing import List

    def format_grouped_inline_references(self, references: List["FormattedReference"]) -> str:
        # Extract, deduplicate, and sort indices
        indices = sorted({fr.inline_reference.inline_index for fr in references})
        if not indices:
            return "[]"

        grouped = []
        start = prev = indices[0]

        for index in indices[1:]:
            if index == prev + 1:
                # Continue the sequence
                prev = index
            else:
                length = prev - start + 1
                if length == 1:
                    grouped.append(f"{start}")
                elif length == 2:
                    # Do not collapse pairs into a range; list individually
                    grouped.append(f"{start}")
                    grouped.append(f"{prev}")
                else:
                    grouped.append(f"{start}-{prev}")
                start = prev = index

        # Append the final sequence
        length = prev - start + 1
        if length == 1:
            grouped.append(f"{start}")
        elif length == 2:
            grouped.append(f"{start}")
            grouped.append(f"{prev}")
        else:
            grouped.append(f"{start}-{prev}")

        return f"[{', '.join(grouped)}]"

    def get_year_month(self, inline_reference) -> Optional[str]:
        dp = self.get_dp(inline_reference)
        if not dp:
            return None
        tokens = dp.split()
        year = tokens[0]
        month = " ".join(tokens[1:]) if len(tokens) > 1 else ""
        return (year + (" " + month if month else "")).strip()

    def get_inline_reference(self, inline_reference) -> str:
        """Return the token that will appear inside the text."""
        return f"[{inline_reference.inline_index}]"

    # ------------------------------------------------------------------
    #  Helper that turns the pieces into the “full” Vancouver string.
    # ------------------------------------------------------------------
    def get_full_reference(self, inline_reference) -> Optional[str]:
        """
        Build the fully‑formatted Vancouver reference (without the
        leading index).  The method is split out so subclasses can
        change punctuation or order without touching `format_reference()`.
        """
        parts = []

        # Authors -------------------------------------------------------
        authors = self.get_authors(inline_reference)
        if authors:
            if len(authors) > 6:
                authors_str = ", ".join(authors[:6]) + ", et al."
            else:
                authors_str = ", ".join(authors) + "."
            parts.append(authors_str)

        # Title ---------------------------------------------------------
        title = self.get_title(inline_reference)  # from parent
        if title:
            parts.append(title)

        # Journal / year / volume / issue / pages ------------------------
        journal = self.get_journal(inline_reference)
        if journal:
            journal_part = journal
            year_month = self.get_year_month(inline_reference)
            if year_month:
                journal_part += f" {year_month};"

            vol = self.get_volume(inline_reference)
            if vol:
                journal_part += vol

            issue = self.get_issue(inline_reference)
            if issue:
                journal_part += f"({issue})"

            pages = self.get_pages(inline_reference)
            if pages:
                clean = pages.replace("p.", "").strip()
                # If we already have volume/issue we put a colon
                if vol or issue:
                    journal_part += f":{clean}"
                else:
                    journal_part += f" {clean}"

            # Ensure period at end
            if not journal_part.endswith("."):
                journal_part += "."
            parts.append(journal_part)

        # DOI ------------------------------------------------------------
        doi = self.get_doi(inline_reference)
        if doi:
            if not doi.lower().startswith("doi:"):
                doi = f"doi: {doi}"
            if not doi.endswith("."):
                doi += "."
            parts.append(doi)

        # If we have no parts but a raw SO fallback --------------------
        if not parts and self.get_so(inline_reference):
            parts.append(self.get_so(inline_reference))

        # Join and return
        full = " ".join(p.strip() for p in parts if p.strip())
        if not full:
            return None

        # Normalize spaces and punctuation
        full = re.sub(r"\s+", " ", full).strip()
        full = full.rstrip(" .") + "."
        return full

    # ------------------------------------------------------------------
    #  The public `format_reference()` method now uses the helper.
    # ------------------------------------------------------------------
    def format_reference(self, inline_reference: InlineReference) -> Optional[FormattedReference]:
        full = self.get_full_reference(inline_reference)
        if not full:
            return None

        reference_index = inline_reference.inline_index
        full_ref = f"{reference_index}. {full}"
        inline_ref = f"[{reference_index}]"
        return FormattedReference(_inline=inline_ref, _full=full_ref)

import re
from typing import Optional, List

from pyrefman.data.FormattedReference import FormattedReference
from pyrefman.data.InlineReference import InlineReference
from pyrefman.styles.ReferencesStyle import ReferencesStyle


class PMIDStyle(ReferencesStyle):
    def describe_style(self) -> str:
        return "Shows inline PMID markers without a reference list; useful for reviewer rebuttals."

    def sort_formatted_references(self, references: List[FormattedReference]) -> List[FormattedReference]:
        return sorted(references, key=lambda r: r.inline_reference.get_nbib_pmid())

    def format_grouped_inline_references(self, references: List["FormattedReference"]) -> str:
        return f"[{' && '.join([f'PMID: {x.inline_reference.get_nbib_pmid()}' for x in references])}]"

    def get_full_reference(self, inline_reference) -> Optional[str]:
        """
        Build the fully‑formatted Vancouver reference (without the
        leading index).  The method is split out so subclasses can
        change punctuation or order without touching `format_reference()`.
        """
        parts = []

        # Title ---------------------------------------------------------
        title = self.get_title(inline_reference)  # from parent
        if title:
            parts.append(title)

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

        reference_index = inline_reference.get_nbib_pmid()
        full_ref = f""
        inline_ref = f"[PMID: {reference_index}]"
        return FormattedReference(_inline=inline_ref, _full=full_ref)

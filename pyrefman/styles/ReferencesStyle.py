from abc import ABC, abstractmethod
from typing import List, Optional


# Abstract base for citation style
# noinspection PyUnresolvedReferences,PyMethodMayBeStatic
class ReferencesStyle(ABC):
    @abstractmethod
    def format_reference(self, inline_reference: "InlineReference") -> Optional["FormattedReference"]:
        raise NotImplementedError

    @abstractmethod
    def sort_formatted_references(self, references: List["FormattedReference"]) -> List["FormattedReference"]:
        raise NotImplementedError

    @abstractmethod
    def format_grouped_inline_references(self, references: List["FormattedReference"]) -> str:
        raise NotImplementedError

    @abstractmethod
    def describe_style(self) -> str:
        raise NotImplementedError

    def get_title(self, inline_reference) -> str:
        return inline_reference.get_nbib_title()

    def get_authors(self, inline_reference) -> List[str]:
        return inline_reference.get_nbib_authors_list()

    def get_journal(self, inline_reference) -> Optional[str]:
        return inline_reference.get_nbib_journal()

    def get_volume(self, inline_reference) -> Optional[str]:
        return inline_reference.get_nbib_volume()

    def get_issue(self, inline_reference) -> Optional[str]:
        return inline_reference.get_nbib_issue()

    def get_pages(self, inline_reference) -> Optional[str]:
        return inline_reference.get_nbib_pages()

    def get_doi(self, inline_reference) -> Optional[str]:
        return inline_reference.get_nbib_doi()

    def get_so(self, inline_reference) -> Optional[str]:
        return inline_reference.get_nbib_so()

    def get_dp(self, inline_reference) -> Optional[str]:
        return inline_reference.get_nbib_dp()

from dataclasses import dataclass
from typing import Optional

from pyrefman.data.InlineReference import InlineReference


@dataclass
class FormattedReference:
    inline_reference: Optional[InlineReference] = None  # now optional
    _inline: Optional[str] = None
    _full: Optional[str] = None

    @property
    def inline(self) -> Optional[str]:
        return self._inline

    @inline.setter
    def inline(self, value: Optional[str]) -> None:
        self._inline = value

    @property
    def full(self) -> Optional[str]:
        return self._full

    @full.setter
    def full(self, value: Optional[str]) -> None:
        self._full = value

    def __str__(self) -> str:
        return f"[{self.inline_reference.inline_index if self.inline_reference else -1}]: {self._inline or ''}\t{self._full or ''}\n"

    def __repr__(self) -> str:
        return self.__str__()

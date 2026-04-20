from __future__ import annotations

import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

from pyrefman.data.FormattedReference import FormattedReference
from pyrefman.data.InlineReference import InlineReference
from tests import TEMP_ROOT


def make_inline_reference(
    index: int = 1,
    url: str = "https://pubmed.ncbi.nlm.nih.gov/12345/",
    title: str = "Example title",
    authors: list[str] | None = None,
    journal: str = "Test Journal",
    dp: str = "2024 Jan",
    volume: str = "10",
    issue: str = "2",
    pages: str = "11-19",
    pmid: str = "12345",
    doi: str = "10.1000/example",
    so: str | None = None,
) -> InlineReference:
    reference = InlineReference(f"[source]({url})")
    reference.inline_index = index
    reference.parsed_nbib = {
        "FAU": authors if authors is not None else ["Doe, Jane A", "Smith, John B"],
        "TI": title,
        "TA": journal,
        "DP": dp,
        "VI": volume,
        "IP": issue,
        "PG": pages,
        "PMID": pmid,
        "AID": [f"{doi} [doi]"],
        "SO": so or f"{journal}. {dp};{volume}({issue}):{pages}. doi: {doi}.",
    }
    return reference


def make_formatted_reference(
    inline_reference: InlineReference | None = None,
    inline: str | None = None,
    full: str | None = None,
) -> FormattedReference:
    return FormattedReference(
        inline_reference=inline_reference,
        _inline=inline if inline is not None else f"[{inline_reference.inline_index if inline_reference else 1}]",
        _full=full if full is not None else "1. Example reference.",
    )


class DummyEvent:
    def __init__(self) -> None:
        self.skipped = False

    def Skip(self) -> None:
        self.skipped = True


class DummyAppearance:
    def __init__(self, dark: bool = False) -> None:
        self._dark = dark

    def IsDark(self) -> bool:
        return self._dark


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@contextmanager
def workspace_dir():
    path = TEMP_ROOT / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class MappingColumnOption:
    key: str
    header: str
    description: str
    getter: Callable[[dict], object]


MAPPING_COLUMN_OPTIONS = [
    MappingColumnOption(
        key="title_and_year",
        header="title and year",
        description="Authors plus publication year.",
        getter=lambda row: row["title_and_year"],
    ),
    MappingColumnOption(
        key="inline_reference",
        header="inline reference",
        description="Formatted inline citation marker.",
        getter=lambda row: row["inline_reference"],
    ),
    MappingColumnOption(
        key="url",
        header="url",
        description="Original source link.",
        getter=lambda row: row["url"],
    ),
    MappingColumnOption(
        key="inline_index",
        header="inline index",
        description="Citation order in the document.",
        getter=lambda row: row["inline_index"],
    ),
    MappingColumnOption(
        key="formatted_reference",
        header="formatted reference",
        description="Full formatted reference text.",
        getter=lambda row: row["formatted_reference"].full if row.get("formatted_reference") else "",
    ),
    MappingColumnOption(
        key="title",
        header="title",
        description="NBIB title when available.",
        getter=lambda row: row["inline_reference_obj"].get_nbib_title() if row.get("inline_reference_obj") else "",
    ),
    MappingColumnOption(
        key="journal",
        header="journal",
        description="Journal name or abbreviation.",
        getter=lambda row: row["inline_reference_obj"].get_nbib_journal() if row.get("inline_reference_obj") else "",
    ),
    MappingColumnOption(
        key="pmid",
        header="pmid",
        description="PubMed identifier when present.",
        getter=lambda row: row["inline_reference_obj"].get_nbib_pmid() if row.get("inline_reference_obj") else "",
    ),
    MappingColumnOption(
        key="doi",
        header="doi",
        description="Digital object identifier when present.",
        getter=lambda row: row["inline_reference_obj"].get_nbib_doi() if row.get("inline_reference_obj") else "",
    ),
]

DEFAULT_MAPPING_KEYS = {"title_and_year", "inline_reference", "url"}

MAPPING_COLUMN_OPTIONS_BY_KEY = {
    option.key: option
    for option in MAPPING_COLUMN_OPTIONS
}


def build_mapping_columns_from_keys(keys: list[str] | None) -> list[tuple[str, Callable[[dict], object]]]:
    if not keys:
        return []

    output: list[tuple[str, Callable[[dict], object]]] = []
    for key in keys:
        option = MAPPING_COLUMN_OPTIONS_BY_KEY.get(key)
        if option is None:
            continue
        output.append((option.header, option.getter))
    return output

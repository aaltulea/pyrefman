from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from pyrefman.Utils import (
    TANDEM_REGEX,
    build_mapping_file_rows,
    find_tandem_reference_groups,
    get_downloads_dir,
    get_output_file_path,
    normalize_google_doc_export_url,
    normalize_user_path,
    read_input_file,
    replace_inline_references_with_formatted_references,
)
from pyrefman.data.InlineReference import InlineReference


DEFAULT_MAPPING_COLUMNS = [
    ("title and year", lambda row: row["title_and_year"]),
    ("inline reference", lambda row: row["inline_reference"]),
    ("url", lambda row: row["url"]),
]


def load_markdown_text(input_source) -> tuple[str, Path | None]:
    formatted_output_file_path = None

    if isinstance(input_source, str) and "https://docs.google.com/document/d/" in input_source:
        url = normalize_google_doc_export_url(input_source)
        html = requests.get(url).text
        soup = BeautifulSoup(html, "html.parser")
        markdown_text_raw = soup.get_text(separator="\n")
        print(url)
        return markdown_text_raw, None

    if isinstance(input_source, (str, Path)):
        input_path = normalize_user_path(input_source)
        if input_path and input_path.exists():
            markdown_text_raw = read_input_file(input_path)
            formatted_output_file_path = get_output_file_path(input_path)
            return markdown_text_raw, formatted_output_file_path

    return str(input_source), formatted_output_file_path


def resolve_output_file(
    output_file,
    formatted_output_file_path: Path | None,
    save_output: bool,
    output_format: str,
) -> Path | None:
    if not save_output:
        return None

    if output_file:
        return normalize_user_path(output_file) or formatted_output_file_path

    if formatted_output_file_path is not None:
        return formatted_output_file_path.with_suffix(".docx" if output_format == "docx" else ".md")

    suffix = ".docx" if output_format == "docx" else ".md"
    return Path(get_downloads_dir()) / f"pyrefman_formatted{suffix}"


def resolve_citations_dir(citations_dir) -> Path:
    if citations_dir is None:
        resolved = Path(get_downloads_dir(), "Citations")
    else:
        resolved = normalize_user_path(citations_dir) or Path(get_downloads_dir(), "Citations")

    os.makedirs(resolved, exist_ok=True)
    return resolved


def partition_urls(urls: Iterable[str], source_looper) -> tuple[list[str], list[str]]:
    accepted_urls: list[str] = []
    rejected_urls: list[str] = []

    for url in urls:
        if source_looper.accepts(url):
            accepted_urls.append(url)
        else:
            rejected_urls.append(url)

    return accepted_urls, rejected_urls


def build_inline_references(accepted_urls: Iterable[str], source_looper) -> list[InlineReference]:
    inline_references = [InlineReference(url) for url in accepted_urls]
    for inline_reference in inline_references:
        source_looper.fetch_references_from_repos(inline_reference)
    return inline_references


def assign_unique_inline_indices(inline_references: Iterable[InlineReference]) -> None:
    seen: dict[str, int] = {}
    next_idx = 1

    for reference in inline_references:
        summary = reference.nbib_summary()
        if summary not in seen:
            seen[summary] = next_idx
            next_idx += 1
        reference.inline_index = seen[summary]


def build_formatted_references(inline_references: Iterable[InlineReference], reference_style) -> list:
    formatted_references = []

    for inline_reference in inline_references:
        if inline_reference.nbib_path and os.path.exists(inline_reference.nbib_path):
            formatted_reference = reference_style.format_reference(inline_reference)
            if formatted_reference is None:
                continue
            formatted_reference.inline_reference = inline_reference
            formatted_references.append(formatted_reference)

    return formatted_references


def resolve_mapping_columns(mapping_columns) -> list[tuple[str, object]]:
    if mapping_columns is None:
        return list(DEFAULT_MAPPING_COLUMNS)
    return list(mapping_columns)


def write_mapping_file(mapping_file, mapping_columns, formatted_references) -> Path:
    mapping_path = normalize_user_path(mapping_file)
    if mapping_path is None:
        raise ValueError("Mapping file path is empty.")

    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    rows_sorted = build_mapping_file_rows(formatted_references)

    with open(mapping_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow([header for header, _ in mapping_columns])
        for row in rows_sorted:
            writer.writerow([value_getter(row) for _, value_getter in mapping_columns])

    return mapping_path


def render_markdown_with_references(markdown_text_raw: str, formatted_references, reference_style) -> str:
    markdown_text_processed = markdown_text_raw

    for formatted_reference in reference_style.sort_formatted_references(formatted_references):
        markdown_text_processed = replace_inline_references_with_formatted_references(
            formatted_reference,
            markdown_text_processed,
        )

    full_reference_lines = [
        formatted_reference.full
        for formatted_reference in reference_style.sort_formatted_references(formatted_references)
        if formatted_reference.full
    ]
    full_reference_lines = list(dict.fromkeys(full_reference_lines))

    tandem_reference_groups = find_tandem_reference_groups(markdown_text_processed, formatted_references)
    for tandem_ref_set in tandem_reference_groups:
        escaped_inlines = [re.escape(formatted_reference.inline) for formatted_reference in tandem_ref_set]
        pattern = TANDEM_REGEX.join(escaped_inlines)
        grouped = reference_style.format_grouped_inline_references(tandem_ref_set)
        markdown_text_processed = re.sub(pattern, grouped, markdown_text_processed)

    if full_reference_lines:
        markdown_text_processed += "\n\n# References\n\n" + "\n".join(full_reference_lines)

    return markdown_text_processed.replace("  ", " ")

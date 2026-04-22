import os
import re
from collections import Counter
from importlib import metadata
from datetime import datetime
from pathlib import Path

from pyrefman.WebDriver import WebDriver
from pyrefman.Utils import grab_markdown_urls, init_reference_style_class, write_output_file, warn_about_missing_citations, build_mapping_file_rows
from pyrefman.processing import (
    assign_unique_inline_indices,
    build_formatted_references,
    build_inline_references,
    load_markdown_text,
    partition_urls,
    render_markdown_with_references,
    resolve_citations_dir,
    resolve_mapping_columns,
    resolve_output_file,
    write_mapping_file,
)
from pyrefman.runtime import can_write_docx
from pyrefman.sources.SourcesLooper import SourcesLooper

YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2}|21\d{2})\b")


class NoUrlsFoundError(ValueError):
    pass


def get_pyrefman_version() -> str:
    for package_name in ("pyrefman", Path(__file__).resolve().parent.name):
        try:
            return metadata.version(package_name)
        except metadata.PackageNotFoundError:
            continue

    package_dir = Path(__file__).resolve().parent
    py_files = list(package_dir.rglob("*.py"))
    if py_files:
        newest_mtime = max(path.stat().st_mtime for path in py_files)
        build_id = datetime.fromtimestamp(newest_mtime).strftime("%Y%m%d%H%M%S")
        return f"0+local.{build_id}"

    return "0+local"


__version__ = get_pyrefman_version()


def _extract_publication_year(inline_reference) -> int | None:
    dp = inline_reference.get_nbib_dp()
    if not dp:
        return None

    match = YEAR_RE.search(dp)
    if not match:
        return None

    return int(match.group(1))


def build_reference_summary(formatted_references) -> dict:
    unique_rows = build_mapping_file_rows(formatted_references) if formatted_references else []
    journal_counts = Counter()
    author_counts = Counter()
    years: list[int] = []

    for row in unique_rows:
        inline_reference = row.get("inline_reference_obj")
        if inline_reference is None:
            continue

        publication_year = _extract_publication_year(inline_reference)
        if publication_year is not None:
            years.append(publication_year)

        journal = inline_reference.get_nbib_journal().strip()
        if journal:
            journal_counts[journal] += 1

        for author in inline_reference.get_nbib_authors_list():
            cleaned_author = str(author or "").strip()
            if cleaned_author:
                author_counts[cleaned_author] += 1

    def top_counts(counter: Counter) -> list[dict]:
        ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0].lower()))
        return [
            {"label": label, "count": count}
            for label, count in ranked
            if count > 1
        ]

    return {
        "total_unique_references": len(unique_rows),
        "oldest_year": min(years) if years else None,
        "newest_year": max(years) if years else None,
        "top_journals": top_counts(journal_counts),
        "top_authors": top_counts(author_counts),
    }


def process_file_citations(input_source,
                           output_file=None,
                           citations_dir=None,
                           mapping_file=None,
                           reference_style="VancouverStyle",
                           mapping_columns=None,
                           save_output=True,
                           output_format="markdown",
                           return_details=False):
    if output_format == "docx" and not can_write_docx():
        raise RuntimeError("Pandoc is not available, so Word export is disabled. Export as Markdown instead.")

    formatted_output_file_path = None
    reference_summary = build_reference_summary([])

    markdown_text_raw, formatted_output_file_path = load_markdown_text(input_source)
    output_file = resolve_output_file(output_file, formatted_output_file_path, save_output, output_format)

    urls = grab_markdown_urls(markdown_text_raw)
    urls_length = len(urls)
    if urls_length == 0:
        raise NoUrlsFoundError("No URLs found in the source file.")

    citations_dir = resolve_citations_dir(citations_dir)

    source_looper = SourcesLooper(citations_dir)
    reference_style = init_reference_style_class(reference_style)

    markdown_text_processed = markdown_text_raw

    try:
        if urls_length > 0:
            print("Found {} URLs".format(urls_length))

            accepted_urls, rejected_urls = partition_urls(urls, source_looper)
            inline_references = build_inline_references(accepted_urls, source_looper)
            assign_unique_inline_indices(inline_references)
            formatted_references = build_formatted_references(inline_references, reference_style)

            # Create deduplicated mapping file if requested
            if mapping_file is not None:
                mapping_columns = resolve_mapping_columns(mapping_columns)
                write_mapping_file(mapping_file, mapping_columns, formatted_references)

            reference_summary = build_reference_summary(formatted_references)
            markdown_text_processed = render_markdown_with_references(
                markdown_text_processed,
                formatted_references,
                reference_style,
            )

            warn_about_missing_citations(markdown_text_processed, rejected_urls, inline_references)
    finally:
        WebDriver().quit_driver()

    if output_file:
        write_output_file(markdown_text_processed, output_file)

    if return_details:
        return {
            "markdown_text": markdown_text_processed,
            "reference_summary": reference_summary,
        }

    return markdown_text_processed

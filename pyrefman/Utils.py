import os
import platform
import re
import string
import subprocess
import locale
from pathlib import Path
from typing import Optional, List

from pyrefman.runtime import (
    MARKDOWN_INPUT_SUFFIXES,
    get_pandoc_path_or_none,
    input_file_requires_pandoc,
)
from pyrefman.styles import ReferencesStyle

_url_re = re.compile(r"https?://[^\s\]\)\>]+", re.IGNORECASE)
_markdown_link_re = re.compile(r"\[[^\]]+]\((https?://[^)\s]+)\)", re.IGNORECASE)
_bracket_url_re = re.compile(r"\[(https?://[^\]\s]+)\]", re.IGNORECASE)
_bare_url_re = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)
TANDEM_REGEX = r"[\s;,]+"
OUTPUT_FORMAT_EXTENSIONS = {
    "markdown": ".md",
    "docx": ".docx",
}


def normalize_google_doc_export_url(url: str) -> str:
    """
    Convert Google Docs URLs like:
      https://docs.google.com/document/d/<id>/edit?tab=t.0
    or
      https://docs.google.com/document/d/<id>
    into:
      https://docs.google.com/document/d/<id>/export?format=md
    """
    m = re.search(r"(https://docs\.google\.com/document/d/[^/]+)", str(url))
    if not m:
        return url
    base = m.group(1)
    return f"{base}/export?format=md"


def strip_wrapping_quotes(value: str) -> str:
    output = str(value).strip()
    if len(output) >= 2 and output[0] == output[-1] and output[0] in ('"', "'"):
        output = output[1:-1].strip()
    return output


def normalize_user_path(value) -> Optional[Path]:
    if value is None:
        return None
    if isinstance(value, Path):
        return value.expanduser()

    cleaned = strip_wrapping_quotes(str(value))
    if not cleaned:
        return None
    return Path(cleaned).expanduser()


def has_markdown_hyperlinks(text: str) -> bool:
    return bool(_markdown_link_re.search(text or ""))


def convert_plain_text_urls_to_markdown(text: str) -> str:
    if not text:
        return text

    placeholders = {}
    placeholder_index = 0

    def placeholder_for(replacement: str) -> str:
        nonlocal placeholder_index
        token = f"__PYREFMAN_URL_{placeholder_index}__"
        placeholder_index += 1
        placeholders[token] = replacement
        return token

    def replace_bracket_url(match: re.Match) -> str:
        url = match.group(1).strip()
        return placeholder_for(f"[{url}]({url})")

    def replace_bare_url(match: re.Match) -> str:
        url = match.group(0)
        trailing = ""

        while url and url[-1] in ".,;:!?)]":
            trailing = url[-1] + trailing
            url = url[:-1]

        return placeholder_for(f"[{url}]({url})") + trailing

    output = _bracket_url_re.sub(replace_bracket_url, text)
    output = _bare_url_re.sub(replace_bare_url, output)

    for token, replacement in placeholders.items():
        output = output.replace(token, replacement)

    return output


def extract_markdown_url(input_str: str) -> Optional[str]:
    # unescape bracket/paren escapes like \[ \] \( \)
    s = re.sub(r"\\([\[\]\(\)])", r"\1", input_str)

    # 1) find markdown links [text](url) (non-greedy)
    for bracket_text, paren_text in re.findall(r"\[([^\]]*?)\]\((.*?)\)", s):
        # prefer URL inside [] if it's a valid URL
        m_br = _url_re.search(bracket_text or "")
        if m_br:
            return m_br.group(0)
        m_pa = _url_re.search(paren_text or "")
        if m_pa:
            return m_pa.group(0)

    # 2) find standalone [url] (not followed by '(' to avoid double-counting)
    for bracket_text in re.findall(r"\[([^\]]+)\](?!\()", s):
        m_br = _url_re.search(bracket_text)
        if m_br:
            return m_br.group(0)

    # 3) find standalone (url)
    for paren_text in re.findall(r"\((.*?)\)", s):
        m_pa = _url_re.search(paren_text or "")
        if m_pa:
            return m_pa.group(0)

    # 4) fallback: any URL anywhere in the string
    m = _url_re.search(s)
    if m:
        return m.group(0)

    return None


def build_mapping_file_rows(formatted_references):
    """
    Build deduplicated mapping rows keyed by nbib identity.
    Returns a list of row-context dicts sorted by inline citation order.
    """
    mapping_rows = {}

    for formatted_reference in formatted_references:
        inline_reference = formatted_reference.inline_reference
        summary = inline_reference.nbib_summary()

        authors = inline_reference.get_linearized_authors() or ""
        year = inline_reference.get_nbib_dp() or ""
        title_and_year = f"{authors} ({year})" if authors and year else (authors or str(year))

        if summary not in mapping_rows:
            mapping_rows[summary] = {
                "title_and_year": title_and_year,
                "inline_reference": formatted_reference.inline,
                "inline_index": getattr(inline_reference, "inline_index", float("inf")),
                "url": inline_reference.url,
                "formatted_reference": formatted_reference,
                "inline_reference_obj": inline_reference,
            }

    return sorted(mapping_rows.values(), key=lambda x: x["inline_index"])


def read_input_file(input_path):
    input_path = input_path if input_path else input("Enter path to input document: ").strip()
    in_file = Path(input_path)
    input_suffix = in_file.suffix.lower()
    if input_suffix in MARKDOWN_INPUT_SUFFIXES:
        return _read_text_file(in_file)
    if input_suffix == ".txt":
        return convert_plain_text_urls_to_markdown(_read_text_file(in_file))
    if input_file_requires_pandoc(in_file) and get_pandoc_path_or_none() is None:
        raise RuntimeError(
            "Pandoc is not available. This file format needs Pandoc for conversion before PyRefman can process it. "
            "Use a Markdown or text file, or repair the local Pandoc download."
        )

    pandoc_args = [str(in_file), "-t", "gfm", "--wrap=none"]
    return run_pandoc(pandoc_args)


def _read_text_file(path: Path) -> str:
    encodings = ["utf-8", "utf-8-sig", locale.getpreferredencoding(False)]
    seen_encodings: set[str] = set()

    for encoding in encodings:
        if not encoding or encoding in seen_encodings:
            continue
        seen_encodings.add(encoding)
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue

    return path.read_text(encoding="utf-8", errors="replace")


def safe_filename(name: str, replacement: str = "_") -> str:
    """
    Converts a string into a safe filename by removing/replacing unsafe characters.

    Args:
        name (str): Original string.
        replacement (str): Character to replace invalid characters with (default "_").

    Returns:
        str: Safe filename.
    """
    # Define valid characters (letters, digits, some punctuation)
    valid_chars = f"-_.() {string.ascii_letters}{string.digits}"
    # Replace invalid characters with the replacement
    safe_name = ''.join(c if c in valid_chars else replacement for c in name)
    # Collapse multiple replacements into one
    safe_name = re.sub(f"{re.escape(replacement)}+", replacement, safe_name)
    # Strip leading/trailing replacements
    safe_name = safe_name.strip(replacement)
    return safe_name


def grab_markdown_urls(text):
    pattern = re.compile(r"\[[^]\[]+?]\([^)(]+?\)|\\\[[^\\\]\[]+?\\\]", flags=re.MULTILINE)
    urls = pattern.findall(text)
    urls = [u for u in urls if "http" in u]
    urls = list(dict.fromkeys(urls))
    return urls


def get_downloads_dir() -> str:
    system = platform.system()

    if system == "Windows":
        downloads = os.path.join(Path.home(), "Downloads")
    elif system == "Darwin":  # macOS
        downloads = os.path.join(Path.home(), "Downloads")
    else:  # Linux and other Unix-like
        downloads = os.path.join(Path.home(), "Downloads")

    return downloads


def init_reference_style_class(style) -> "ReferencesStyle":
    import importlib

    if not isinstance(style, str):
        return style

    module_path = f"pyrefman.styles.{style}"
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError:
        raise ValueError(f"Style module '{module_path}' not found.")
    try:
        cls = getattr(module, style)
    except AttributeError:
        raise ValueError(f"Class '{style}' not found in module '{module_path}'.")
    return cls()


def replace_inline_references_with_formatted_references(formatted_reference: "FormattedReference",
                                                        markdown_text_processed: str) -> str:
    markdown_text_processed = re.sub(
        # possible occurrences: \[[1]\], ([1])
        fr"\\*[\[\(]*{re.escape(formatted_reference.inline_reference.inline_text).strip()}\\*[\]\)]*",
        formatted_reference.inline or f"{formatted_reference.inline_reference.inline_index}",
        markdown_text_processed,
        flags=re.DOTALL
    )

    return markdown_text_processed


def find_tandem_reference_groups(markdown_text_processed, formatted_references) -> List[List["FormattedReference"]]:
    lookup = {}
    inline_values = []
    for fr in formatted_references:
        inline = getattr(fr, "inline", None)
        if inline:
            inline_values.append(inline)
            if inline not in lookup:
                lookup[inline] = fr

    # build alternation pattern, longest-first to avoid partial matches
    escaped = sorted({re.escape(s) for s in inline_values}, key=len, reverse=True)
    if not escaped:
        return []

    pattern = re.compile("|".join(escaped))

    matches = list(pattern.finditer(markdown_text_processed))
    groups: List[List["FormattedReference"]] = []
    i = 0
    while i < len(matches):
        group_matches = [matches[i]]
        j = i + 1
        while j < len(matches):
            prev = group_matches[-1]
            nxt = matches[j]
            separator = markdown_text_processed[prev.end():nxt.start()]
            if separator == "" or re.fullmatch(TANDEM_REGEX, separator):
                group_matches.append(nxt)
                j += 1
            else:
                break

        if len(group_matches) >= 2:
            frs = [lookup[m.group(0)] for m in group_matches if m.group(0) in lookup]
            if len(frs) >= 2:
                groups.append(frs)

        i = j

    return groups


def get_pandoc_path() -> str:
    pandoc_path = get_pandoc_path_or_none()
    if pandoc_path:
        return pandoc_path

    raise FileNotFoundError(
        "Pandoc is required for converting non-Markdown input files or writing .docx output. "
        "PyRefman could not find a working local or system Pandoc executable."
    )


def run_pandoc(args: List[str], input_text: Optional[str] = None) -> str:
    result = subprocess.run(
        [get_pandoc_path(), *args],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Pandoc conversion failed.\n{details}" if details else "Pandoc conversion failed.")
    return result.stdout


def get_output_file_path(input_path: Path, output_format: str = "markdown") -> Path:
    extension = OUTPUT_FORMAT_EXTENSIONS.get(output_format, ".md")
    return input_path.with_name(input_path.stem + "_formatted" + extension)


def write_output_file(markdown_text_processed: str, output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.suffix.lower() == ".docx":
        run_pandoc(
            ["-f", "gfm", "-o", str(output_path), "-"],
            input_text=markdown_text_processed,
        )
    else:
        output_path.write_text(markdown_text_processed, encoding="utf-8")

    print(f"==================================\nOutput: {output_path}\n==================================\n")


def write_markdown_to_file(markdown_text_processed: str, output_path: Path) -> None:
    write_output_file(markdown_text_processed, output_path)


def warn_about_missing_citations(output_md_text, rejected_urls: List[str],
                                 inline_references: list["InlineReference"]) -> None:
    missing_citations = [x.url for x in inline_references if not x.nbib_path]
    missing_citations_count = len(missing_citations)
    if missing_citations_count > 0:
        print(
            f"[WARNING] {missing_citations_count} citation{'s' if missing_citations_count != 1 else ''} {'are' if missing_citations_count != 1 else 'is'} missing:")
        print(missing_citations)

    rejected_urls_count = len(rejected_urls)
    if rejected_urls_count > 0:
        print(
            f"[WARNING] {rejected_urls_count} citation{'s' if rejected_urls_count != 1 else ''} {'are' if rejected_urls_count != 1 else 'is'} not handled:"
        )
        print([extract_markdown_url(x) for x in rejected_urls])

    loose_urls = re.findall(r'https?://[^\s"\'<>\]]+', output_md_text)
    loose_urls_count = len(loose_urls)

    if loose_urls_count > 0:
        print(
            f"[INFO] Found {loose_urls_count} HTTP(S) URL{'s' if loose_urls_count != 1 else ''} {'that are' if loose_urls_count != 1 else 'that is'} loose (not a hyperlink):"
        )
        print([x for x in loose_urls])

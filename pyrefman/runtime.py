from __future__ import annotations

import functools
import os
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLAYWRIGHT_BROWSERS_DIR = PROJECT_ROOT / ".playwright"
LOCAL_PANDOC_ROOT = PROJECT_ROOT / ".tools" / "pandoc"
MARKDOWN_INPUT_SUFFIXES = {".md", ".markdown"}
DIRECT_TEXT_INPUT_SUFFIXES = MARKDOWN_INPUT_SUFFIXES | {".txt"}


def configure_local_runtime_environment() -> None:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(PLAYWRIGHT_BROWSERS_DIR))


configure_local_runtime_environment()


def _pandoc_executable_name() -> str:
    return "pandoc.exe" if os.name == "nt" else "pandoc"


def _is_working_pandoc(path: Path) -> bool:
    if not path.exists() or path.is_dir():
        return False

    try:
        result = subprocess.run(
            [str(path), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False

    return result.returncode == 0


@functools.lru_cache(maxsize=1)
def get_local_pandoc_path() -> str | None:
    if not LOCAL_PANDOC_ROOT.exists():
        return None

    executable_name = _pandoc_executable_name()
    for candidate in sorted(LOCAL_PANDOC_ROOT.rglob(executable_name)):
        if _is_working_pandoc(candidate):
            return str(candidate)

    return None


@functools.lru_cache(maxsize=1)
def get_system_pandoc_path() -> str | None:
    pandoc_path = shutil.which("pandoc")
    if pandoc_path and _is_working_pandoc(Path(pandoc_path)):
        return pandoc_path
    return None


@functools.lru_cache(maxsize=1)
def get_pandoc_path_or_none() -> str | None:
    configured_path = os.environ.get("PANDOC_PATH")
    if configured_path:
        candidate = Path(configured_path).expanduser()
        if _is_working_pandoc(candidate):
            return str(candidate)

    local_pandoc = get_local_pandoc_path()
    if local_pandoc:
        return local_pandoc

    return get_system_pandoc_path()


def is_pandoc_available() -> bool:
    return get_pandoc_path_or_none() is not None


def input_file_requires_pandoc(path: Path | None) -> bool:
    if path is None:
        return False
    return path.suffix.lower() not in DIRECT_TEXT_INPUT_SUFFIXES


def can_write_docx() -> bool:
    return is_pandoc_available()

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from pyrefman import NoUrlsFoundError, process_file_citations
from pyrefman.mapping_columns import build_mapping_columns_from_keys


def _load_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_payload(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")


def _no_urls_message(input_mode: str) -> str:
    base_message = "No URLs found in the source file. Double-check the URLs and try again."
    if input_mode == "google_doc":
        return (
            base_message
            + " Make sure the URL is valid and the document access is set to 'anyone with the link: Viewer'."
        )
    return base_message


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python -m pyrefman.worker <args.json> <result.json>", file=sys.stderr)
        return 2

    args_path = Path(sys.argv[1])
    result_path = Path(sys.argv[2])

    try:
        payload = _load_payload(args_path)
        input_mode = str(payload.pop("_ui_input_mode", "file"))
        mapping_column_keys = payload.pop("mapping_column_keys", None)
        payload["mapping_columns"] = build_mapping_columns_from_keys(mapping_column_keys)

        result = process_file_citations(**payload, return_details=True)
        if isinstance(result, dict):
            preview_text = str(result.get("markdown_text", "") or "")
            reference_summary = result.get("reference_summary") or {}
        else:
            preview_text = result if isinstance(result, str) else ""
            reference_summary = {}

        _write_payload(
            result_path,
            {
                "success": True,
                "preview_text": preview_text,
                "reference_summary": reference_summary,
            },
        )
        return 0
    except NoUrlsFoundError:
        _write_payload(
            result_path,
            {
                "success": False,
                "show_error_dialog": True,
                "skip_completion_dialog": True,
                "error": _no_urls_message(input_mode),
            },
        )
        return 1
    except Exception as exc:
        traceback.print_exc()
        _write_payload(
            result_path,
            {
                "success": False,
                "error": str(exc),
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

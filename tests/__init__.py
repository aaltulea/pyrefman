from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE_PACKAGES = ROOT / ".venv" / "Lib" / "site-packages"
TEMP_ROOT = ROOT / ".tmp-tests"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if SITE_PACKAGES.exists() and str(SITE_PACKAGES) not in sys.path:
    sys.path.append(str(SITE_PACKAGES))

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".playwright"))
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEMP_ROOT)

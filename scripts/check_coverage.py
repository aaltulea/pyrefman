from __future__ import annotations

import sys
import trace
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SITE_PACKAGES = ROOT / ".venv" / "Lib" / "site-packages"
TESTS_DIR = ROOT / "tests"
TRACKED_ROOTS = [ROOT / "pyrefman", ROOT / "scripts"]
EXCLUDED_FILES = {ROOT / "scripts" / "check_coverage.py"}


def configure_path() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if SITE_PACKAGES.exists() and str(SITE_PACKAGES) not in sys.path:
        sys.path.append(str(SITE_PACKAGES))


def tracked_python_files() -> list[Path]:
    tracked: list[Path] = []
    for root in TRACKED_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if path.resolve() in EXCLUDED_FILES:
                continue
            tracked.append(path.resolve())
    return sorted(set(tracked))


def run_tests() -> unittest.result.TestResult:
    loader = unittest.defaultTestLoader
    suite = loader.discover(str(TESTS_DIR), pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=1)
    return runner.run(suite)


def executed_lines(counts: dict, file_path: Path) -> set[int]:
    resolved = str(file_path.resolve())
    return {
        lineno
        for (filename, lineno), count in counts.items()
        if count and str(Path(filename).resolve()) == resolved
    }


def main() -> int:
    configure_path()
    tracer = trace.Trace(count=True, trace=False)
    test_result = tracer.runfunc(run_tests)
    results = tracer.results()
    counts = results.counts

    total_executable = 0
    total_executed = 0
    missing_by_file: dict[Path, list[int]] = {}

    print("\nCoverage Summary")
    for file_path in tracked_python_files():
        executable = {line for line in trace._find_executable_linenos(str(file_path)) if line > 0}
        executed = executed_lines(counts, file_path)
        missing = sorted(executable - executed)
        covered = len(executable) - len(missing)
        percent = 100.0 if not executable else (covered / len(executable)) * 100
        total_executable += len(executable)
        total_executed += covered
        relative = file_path.relative_to(ROOT)
        print(f"{percent:6.2f}% {relative}")
        if missing:
            missing_by_file[file_path] = missing

    overall = 100.0 if total_executable == 0 else (total_executed / total_executable) * 100
    print(f"Overall: {overall:.2f}%")

    if not test_result.wasSuccessful():
        return 1

    if missing_by_file:
        print("\nMissing Lines")
        for file_path, missing in missing_by_file.items():
            relative = file_path.relative_to(ROOT)
            joined = ", ".join(str(line) for line in missing)
            print(f"{relative}: {joined}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

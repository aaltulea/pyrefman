from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError


REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = REPO_ROOT / ".venv"
RUNTIME_DIR = REPO_ROOT / ".runtime"
STATE_FILE = RUNTIME_DIR / "launch-state.json"
PLAYWRIGHT_BROWSERS_DIR = REPO_ROOT / ".playwright"
PANDOC_ROOT = REPO_ROOT / ".tools" / "pandoc"
PANDOC_VERSION = "3.9.0.2"
INTERNET_RETRY_TIMEOUT_S = 5 * 60
INTERNET_RETRY_DELAY_S = 5
INTERNET_ERROR_PATTERNS = (
    "unable to connect to the remote server",
    "could not resolve host",
    "temporary failure in name resolution",
    "name or service not known",
    "no such host is known",
    "network is unreachable",
    "connection refused",
    "connection reset",
    "connection aborted",
    "remote end closed connection",
    "timed out",
    "timeout",
    "read timed out",
    "connect eacces",
    "errno -4092",
    "winerror 10013",
    "failed to download",
    "max retries exceeded",
    "proxyerror",
    "getaddrinfo failed",
    "unable to establish ssl connection",
    "ssl handshake",
    "tls handshake",
)


def main() -> int:
    os.chdir(REPO_ROOT)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(PLAYWRIGHT_BROWSERS_DIR))

    state = load_state()
    state_changed = False

    requirements_hash = file_sha256(REPO_ROOT / "requirements.txt")
    if state.get("requirements_hash") != requirements_hash or not dependencies_look_installed():
        install_requirements()
        state["requirements_hash"] = requirements_hash
        state_changed = True

    playwright_version = package_version("playwright")
    if needs_playwright_install(state, playwright_version):
        install_playwright_browser()
        state["playwright_version"] = playwright_version
        state_changed = True

    pandoc_path = None
    try:
        pandoc_path = ensure_local_pandoc()
        if pandoc_path is not None:
            state["pandoc_version"] = PANDOC_VERSION
            state["pandoc_path"] = pandoc_path
            state_changed = True
    except Exception as exc:
        print(f"[WARNING] Could not download local Pandoc: {exc}")
        print("[WARNING] PyRefman will fall back to a system Pandoc if one is installed.")

    if state_changed:
        save_state(state)

    return launch_app(pandoc_path)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=True), encoding="utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_stream_text(text: str, stream) -> None:
    if not text:
        return

    payload = text if text.endswith(("\n", "\r")) else f"{text}\n"
    try:
        stream.write(payload)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "utf-8"
        encoded = payload.encode(encoding, errors="replace")
        buffer = getattr(stream, "buffer", None)
        if buffer is not None:
            buffer.write(encoded)
        else:
            stream.write(encoded.decode(encoding, errors="replace"))
    stream.flush()


def run_command(args: list[str], env: dict[str, str] | None = None) -> None:
    print(">", " ".join(args))
    result = subprocess.run(
        args,
        check=False,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.stdout:
        write_stream_text(result.stdout, sys.stdout)
    if result.stderr:
        write_stream_text(result.stderr, sys.stderr)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, args, output=result.stdout, stderr=result.stderr)


def internet_retry_deadline() -> float:
    return time.monotonic() + INTERNET_RETRY_TIMEOUT_S


def internet_retry_error_message(step_name: str) -> str:
    return (
        f"{step_name} kept failing due to missing internet access or a firewall block for 5 minutes. "
        "Allow the network prompt or repair connectivity, then run the launcher again."
    )


def is_internet_related_error(exc: BaseException) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code >= 500 or exc.code in {408, 425, 429}

    if isinstance(exc, (TimeoutError, ConnectionError, URLError)):
        return True

    if isinstance(exc, subprocess.CalledProcessError):
        text = "\n".join(filter(None, [exc.output, exc.stderr]))
        return text_looks_like_internet_error(text)

    return text_looks_like_internet_error(str(exc))


def text_looks_like_internet_error(text: str | None) -> bool:
    normalized = str(text or "").lower()
    return any(pattern in normalized for pattern in INTERNET_ERROR_PATTERNS)


def retry_on_internet_failure(step_name: str, action) -> None:
    deadline = internet_retry_deadline()
    attempt = 1

    while True:
        try:
            action()
            return
        except Exception as exc:
            if not is_internet_related_error(exc):
                raise

            if time.monotonic() >= deadline:
                raise RuntimeError(internet_retry_error_message(step_name)) from exc

            remaining = max(0, int(deadline - time.monotonic()))
            print(
                f"[WARNING] {step_name} appears blocked by missing internet access or a firewall rule. "
                f"Retrying in {INTERNET_RETRY_DELAY_S} seconds "
                f"(attempt {attempt}, up to {remaining}s remaining)..."
            )
            time.sleep(INTERNET_RETRY_DELAY_S)
            attempt += 1


def install_requirements() -> None:
    print("Installing Python dependencies into the local virtual environment...")
    try:
        retry_on_internet_failure(
            "Upgrading pip in the local virtual environment",
            lambda: run_command([sys.executable, "-m", "pip", "install", "--upgrade", "pip"]),
        )
        retry_on_internet_failure(
            "Installing Python dependencies into the local virtual environment",
            lambda: run_command([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]),
        )
    except subprocess.CalledProcessError as exc:
        if platform.system() == "Linux":
            raise RuntimeError(
                "Dependency installation failed. On Linux, wxPython may still need a distro-specific wheel "
                "or system GTK development packages."
            ) from exc
        raise


def dependencies_look_installed() -> bool:
    required_distributions = ("beautifulsoup4", "playwright", "requests", "wxPython")
    try:
        for name in required_distributions:
            importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def package_version(name: str) -> str:
    return importlib.metadata.version(name)


def needs_playwright_install(state: dict, playwright_version: str) -> bool:
    if state.get("playwright_version") != playwright_version:
        return True

    return not has_local_playwright_browser()


def has_local_playwright_browser() -> bool:
    if not PLAYWRIGHT_BROWSERS_DIR.exists():
        return False

    for child in PLAYWRIGHT_BROWSERS_DIR.iterdir():
        if child.name.startswith("chromium-"):
            return True
    return False


def install_playwright_browser() -> None:
    print("Installing the local Playwright Chromium browser...")
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_DIR)
    try:
        retry_on_internet_failure(
            "Installing the local Playwright Chromium browser",
            lambda: run_command([sys.executable, "-m", "playwright", "install", "chromium"], env=env),
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "Playwright could not download Chromium into the project-local browser folder. "
            "Check internet access or firewall rules, then run the launcher again."
        ) from exc


def ensure_local_pandoc() -> str | None:
    asset_name = pandoc_asset_name()
    if asset_name is None:
        print("[WARNING] No local Pandoc asset is configured for this platform.")
        return None

    target_dir = PANDOC_ROOT / f"{PANDOC_VERSION}-{asset_name}"
    existing = find_local_pandoc(target_dir)
    if existing is not None:
        return existing

    if target_dir.exists():
        existing = find_local_pandoc(target_dir)
        if existing is not None:
            return existing
        shutil.rmtree(target_dir, ignore_errors=True)

    PANDOC_ROOT.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/jgm/pandoc/releases/download/{PANDOC_VERSION}/{asset_name}"

    print(f"Downloading local Pandoc {PANDOC_VERSION}...")
    with tempfile.TemporaryDirectory(prefix="pyrefman-pandoc-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        archive_path = temp_dir / asset_name
        download_file(url, archive_path)

        extracted_dir = temp_dir / "extracted"
        extracted_dir.mkdir(parents=True, exist_ok=True)
        extract_archive(archive_path, extracted_dir)

        extracted_pandoc = find_local_pandoc(extracted_dir)
        if extracted_pandoc is None:
            raise RuntimeError("Downloaded Pandoc archive did not contain a runnable pandoc executable.")

        shutil.move(str(extracted_dir), str(target_dir))

    return find_local_pandoc(target_dir)


def normalized_machine() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64", "x64"}:
        return "x86_64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    if machine in {"x86", "i386", "i686"}:
        return "x86"
    return machine


def pandoc_asset_name() -> str | None:
    system = platform.system()
    machine = normalized_machine()

    if system == "Windows":
        if machine in {"x86_64", "arm64"}:
            return f"pandoc-{PANDOC_VERSION}-windows-x86_64.zip"
        return None

    if system == "Darwin":
        if machine == "x86_64":
            return f"pandoc-{PANDOC_VERSION}-x86_64-macOS.zip"
        if machine == "arm64":
            return f"pandoc-{PANDOC_VERSION}-arm64-macOS.zip"
        return None

    if system == "Linux":
        if machine == "x86_64":
            return f"pandoc-{PANDOC_VERSION}-linux-amd64.tar.gz"
        if machine == "arm64":
            return f"pandoc-{PANDOC_VERSION}-linux-arm64.tar.gz"
        return None

    return None


def download_file(url: str, destination: Path) -> None:
    def _download() -> None:
        request = urllib.request.Request(url, headers={"User-Agent": "PyRefman launcher"})
        with urllib.request.urlopen(request, timeout=30) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output)

    retry_on_internet_failure("Downloading a local Pandoc archive", _download)


def extract_archive(archive_path: Path, destination: Path) -> None:
    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(destination)
        return

    if archive_path.name.endswith(".tar.gz"):
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(destination)
        return

    raise RuntimeError(f"Unsupported archive format: {archive_path.name}")


def find_local_pandoc(root: Path) -> str | None:
    if not root.exists():
        return None

    executable_name = "pandoc.exe" if os.name == "nt" else "pandoc"
    for candidate in sorted(root.rglob(executable_name)):
        if is_runnable(candidate):
            return str(candidate)
    return None


def is_runnable(path: Path) -> bool:
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


def launch_app(local_pandoc_path: str | None) -> int:
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_DIR)
    if local_pandoc_path:
        env["PANDOC_PATH"] = local_pandoc_path

    pythonw_path = windows_pythonw_path()
    if pythonw_path is not None:
        subprocess.Popen([pythonw_path, "-m", "pyrefman"], cwd=REPO_ROOT, env=env)
        return 0

    return subprocess.call([sys.executable, "-m", "pyrefman"], cwd=REPO_ROOT, env=env)


def windows_pythonw_path() -> str | None:
    if os.name != "nt":
        return None

    candidate = VENV_DIR / "Scripts" / "pythonw.exe"
    if candidate.exists():
        return str(candidate)
    return None


def run_cli(main_func=None, printer=print) -> int:
    main_func = main if main_func is None else main_func

    try:
        return int(main_func())
    except Exception as exc:
        printer(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(run_cli(globals().get("_pyrefman_launch_main_override")))

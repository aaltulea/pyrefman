from __future__ import annotations

import io
import json
import runpy
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock, patch

from pyrefman import runtime
from scripts import launch
from tests.helpers import workspace_dir


class RuntimeAndLaunchTests(unittest.TestCase):
    def tearDown(self) -> None:
        runtime.get_local_pandoc_path.cache_clear()
        runtime.get_system_pandoc_path.cache_clear()
        runtime.get_pandoc_path_or_none.cache_clear()

    def test_runtime_environment_and_pandoc_helpers(self) -> None:
        with patch("pyrefman.runtime.os.name", "nt"):
            self.assertEqual(runtime._pandoc_executable_name(), "pandoc.exe")
        with patch("pyrefman.runtime.os.name", "posix"):
            self.assertEqual(runtime._pandoc_executable_name(), "pandoc")

        with workspace_dir() as tmp_path:
            candidate = tmp_path / "pandoc"
            candidate.write_text("x", encoding="utf-8")
            success = SimpleNamespace(returncode=0)
            failure = SimpleNamespace(returncode=1)
            with patch("subprocess.run", return_value=success):
                self.assertTrue(runtime._is_working_pandoc(candidate))
            with patch("subprocess.run", return_value=failure):
                self.assertFalse(runtime._is_working_pandoc(candidate))
            self.assertFalse(runtime._is_working_pandoc(tmp_path))
            with patch("subprocess.run", side_effect=RuntimeError):
                self.assertFalse(runtime._is_working_pandoc(candidate))

            local_root = tmp_path / ".tools" / "pandoc"
            local_root.mkdir(parents=True)
            local_candidate = local_root / "pandoc"
            local_candidate.write_text("x", encoding="utf-8")
            with patch.object(runtime, "LOCAL_PANDOC_ROOT", local_root), patch.object(
                runtime, "_is_working_pandoc", return_value=True
            ), patch.object(runtime, "_pandoc_executable_name", return_value="pandoc"):
                self.assertEqual(runtime.get_local_pandoc_path(), str(local_candidate))

        with patch("shutil.which", return_value="pandoc"), patch.object(runtime, "_is_working_pandoc", return_value=True):
            self.assertEqual(runtime.get_system_pandoc_path(), "pandoc")
        runtime.get_system_pandoc_path.cache_clear()
        with patch("shutil.which", return_value=None):
            self.assertIsNone(runtime.get_system_pandoc_path())

        with patch.dict("os.environ", {"PANDOC_PATH": "/tmp/pandoc"}, clear=False), patch.object(
            runtime, "_is_working_pandoc", return_value=True
        ):
            self.assertEqual(runtime.get_pandoc_path_or_none(), str(Path("/tmp/pandoc")))

        runtime.get_pandoc_path_or_none.cache_clear()
        with patch.dict("os.environ", {}, clear=True), patch.object(runtime, "get_local_pandoc_path", return_value=None), patch.object(
            runtime, "get_system_pandoc_path", return_value="pandoc"
        ):
            self.assertEqual(runtime.get_pandoc_path_or_none(), "pandoc")
            self.assertTrue(runtime.is_pandoc_available())

        self.assertFalse(runtime.input_file_requires_pandoc(None))
        self.assertFalse(runtime.input_file_requires_pandoc(Path("x.md")))
        self.assertTrue(runtime.input_file_requires_pandoc(Path("x.docx")))

    def test_launch_helpers(self) -> None:
        class AsciiOnlyBufferStream:
            encoding = "ascii"

            def __init__(self) -> None:
                self.buffer = io.BytesIO()

            def write(self, text: str) -> int:
                text.encode(self.encoding)
                return len(text)

            def flush(self) -> None:
                return None

        class AsciiOnlyTextStream:
            encoding = "ascii"

            def __init__(self) -> None:
                self.writes: list[str] = []

            def write(self, text: str) -> int:
                text.encode(self.encoding)
                self.writes.append(text)
                return len(text)

            def flush(self) -> None:
                return None

        with workspace_dir() as tmp_path:
            state_path = tmp_path / "state.json"
            with patch.object(launch, "STATE_FILE", state_path):
                self.assertEqual(launch.load_state(), {})
                launch.save_state({"ok": True})
                self.assertEqual(launch.load_state(), {"ok": True})

            file_path = tmp_path / "data.txt"
            file_path.write_text("abc", encoding="utf-8")
            self.assertEqual(len(launch.file_sha256(file_path)), 64)

        success = SimpleNamespace(stdout="ok\n", stderr="", returncode=0)
        with patch("subprocess.run", return_value=success), patch("sys.stderr", new=io.StringIO()):
            launch.run_command(["echo", "ok"])

        buffer_stream = AsciiOnlyBufferStream()
        launch.write_stream_text("progress ●", buffer_stream)
        self.assertEqual(buffer_stream.buffer.getvalue().decode("ascii"), "progress ?\n")

        text_stream = AsciiOnlyTextStream()
        launch.write_stream_text("", text_stream)
        self.assertEqual(text_stream.writes, [])
        launch.write_stream_text("status ●", text_stream)
        self.assertEqual(text_stream.writes, ["status ?\n"])

        failure = SimpleNamespace(stdout="", stderr="bad", returncode=1)
        with patch("subprocess.run", return_value=failure):
            with self.assertRaises(subprocess.CalledProcessError):
                launch.run_command(["bad"])

        self.assertTrue(launch.text_looks_like_internet_error("timeout on connection"))
        self.assertTrue(launch.text_looks_like_internet_error("socket blocked with WinError 10013"))
        self.assertFalse(
            launch.text_looks_like_internet_error(
                "ERROR: Could not install packages due to an OSError: [Errno 13] Permission denied"
            )
        )
        self.assertFalse(launch.text_looks_like_internet_error("plain error"))
        self.assertTrue(launch.is_internet_related_error(HTTPError("x", 500, "bad", None, None)))
        self.assertTrue(launch.is_internet_related_error(URLError("offline")))
        self.assertTrue(launch.is_internet_related_error(ConnectionError("offline")))
        self.assertTrue(launch.is_internet_related_error(subprocess.CalledProcessError(1, ["x"], output="", stderr="timeout")))
        self.assertFalse(
            launch.is_internet_related_error(
                subprocess.CalledProcessError(
                    1,
                    ["pip"],
                    output="",
                    stderr="ERROR: Could not install packages due to an OSError: [Errno 13] Permission denied",
                )
            )
        )
        self.assertFalse(launch.is_internet_related_error(RuntimeError("other")))

        attempts = {"count": 0}

        def flaky():
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise TimeoutError("timeout")

        monotonic_values = iter([0, 1, 2, 3, 4])
        with patch("scripts.launch.internet_retry_deadline", return_value=10), patch("time.monotonic", side_effect=lambda: next(monotonic_values)), patch(
            "time.sleep"
        ):
            launch.retry_on_internet_failure("step", flaky)
        self.assertEqual(attempts["count"], 2)

        with patch("scripts.launch.internet_retry_deadline", return_value=0), patch("time.monotonic", return_value=1):
            with self.assertRaises(RuntimeError):
                launch.retry_on_internet_failure("step", lambda: (_ for _ in ()).throw(TimeoutError("timeout")))

        permission_attempts = {"count": 0}

        def permission_failure():
            permission_attempts["count"] += 1
            raise OSError(13, "Permission denied")

        with self.assertRaises(OSError):
            launch.retry_on_internet_failure("step", permission_failure)
        self.assertEqual(permission_attempts["count"], 1)

        with patch("scripts.launch.retry_on_internet_failure") as retry:
            launch.install_requirements()
            self.assertEqual(retry.call_count, 2)

        with patch("scripts.launch.importlib.metadata.version", side_effect=["1", "1", "1", "1"]):
            self.assertTrue(launch.dependencies_look_installed())
        with patch("scripts.launch.importlib.metadata.version", side_effect=launch.importlib.metadata.PackageNotFoundError):
            self.assertFalse(launch.dependencies_look_installed())
        with patch("scripts.launch.importlib.metadata.version", return_value="4.14.3"):
            self.assertEqual(launch.package_version("beautifulsoup4"), "4.14.3")

        self.assertTrue(launch.needs_playwright_install({}, "1.0"))
        self.assertTrue(launch.needs_playwright_install({"playwright_version": "0.9"}, "1.0"))
        with patch.object(launch, "has_local_playwright_browser", return_value=True):
            self.assertFalse(launch.needs_playwright_install({"playwright_version": "1.0"}, "1.0"))

        with workspace_dir() as tmp_path:
            with patch.object(launch, "PLAYWRIGHT_BROWSERS_DIR", tmp_path):
                self.assertFalse(launch.has_local_playwright_browser())
                (tmp_path / "chromium-123").mkdir()
                self.assertTrue(launch.has_local_playwright_browser())

        with patch("scripts.launch.retry_on_internet_failure") as retry:
            launch.install_playwright_browser()
            self.assertTrue(retry.called)

        with patch("platform.machine", return_value="AMD64"):
            self.assertEqual(launch.normalized_machine(), "x86_64")
        with patch("platform.machine", return_value="arm64"):
            self.assertEqual(launch.normalized_machine(), "arm64")
        with patch("platform.machine", return_value="x86"):
            self.assertEqual(launch.normalized_machine(), "x86")

        with patch("platform.system", return_value="Windows"), patch.object(launch, "normalized_machine", return_value="x86_64"):
            self.assertIn("windows-x86_64.zip", launch.pandoc_asset_name())
        with patch("platform.system", return_value="Darwin"), patch.object(launch, "normalized_machine", return_value="arm64"):
            self.assertIn("arm64-macOS.zip", launch.pandoc_asset_name())
        with patch("platform.system", return_value="Linux"), patch.object(launch, "normalized_machine", return_value="x86_64"):
            self.assertIn("linux-amd64.tar.gz", launch.pandoc_asset_name())

        with patch("urllib.request.urlopen") as urlopen:
            response = MagicMock()
            response.__enter__.return_value = io.BytesIO(b"abc")
            urlopen.return_value = response
            with workspace_dir() as tmp_path:
                destination = tmp_path / "file.bin"
                launch.download_file("https://example.com/file.bin", destination)
                self.assertEqual(destination.read_bytes(), b"abc")

        with workspace_dir() as tmp_path:
            zip_path = tmp_path / "demo.zip"
            import zipfile

            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("demo.txt", "hello")
            destination = tmp_path / "zip-out"
            launch.extract_archive(zip_path, destination)
            self.assertTrue((destination / "demo.txt").exists())

            import tarfile

            tar_path = tmp_path / "demo.tar.gz"
            inner_file = tmp_path / "inner.txt"
            inner_file.write_text("hello", encoding="utf-8")
            with tarfile.open(tar_path, "w:gz") as archive:
                archive.add(inner_file, arcname="inner.txt")
            tar_destination = tmp_path / "tar-out"
            launch.extract_archive(tar_path, tar_destination)
            self.assertTrue((tar_destination / "inner.txt").exists())

            with self.assertRaises(RuntimeError):
                launch.extract_archive(tmp_path / "bad.txt", tar_destination)

        with workspace_dir() as tmp_path:
            candidate = tmp_path / "pandoc.exe"
            candidate.write_text("x", encoding="utf-8")
            with patch.object(launch, "is_runnable", return_value=True):
                self.assertEqual(launch.find_local_pandoc(tmp_path), str(candidate))
            with patch.object(launch, "is_runnable", return_value=False):
                self.assertIsNone(launch.find_local_pandoc(tmp_path))
            self.assertIsNone(launch.find_local_pandoc(tmp_path / "missing"))

        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0)):
            with workspace_dir() as tmp_path:
                candidate = tmp_path / "pandoc"
                candidate.write_text("x", encoding="utf-8")
                self.assertTrue(launch.is_runnable(candidate))
        with patch("subprocess.run", side_effect=RuntimeError):
            with workspace_dir() as tmp_path:
                candidate = tmp_path / "pandoc"
                candidate.write_text("x", encoding="utf-8")
                self.assertFalse(launch.is_runnable(candidate))

        with patch.object(launch, "windows_pythonw_path", return_value="pythonw"), patch("subprocess.Popen") as popen:
            self.assertEqual(launch.launch_app("pandoc"), 0)
            popen.assert_called_once()
        with patch.object(launch, "windows_pythonw_path", return_value=None), patch("subprocess.call", return_value=7) as call:
            self.assertEqual(launch.launch_app(None), 7)
            call.assert_called_once()

        with patch("scripts.launch.os.name", "nt"), patch.object(Path, "exists", return_value=True):
            self.assertTrue(launch.windows_pythonw_path().endswith("pythonw.exe"))
        with patch("scripts.launch.os.name", "posix"):
            self.assertIsNone(launch.windows_pythonw_path())

        printer = MagicMock()
        self.assertEqual(launch.run_cli(lambda: 5, printer=printer), 5)
        self.assertEqual(launch.run_cli(lambda: (_ for _ in ()).throw(RuntimeError("boom")), printer=printer), 1)
        self.assertTrue(printer.called)

    def test_launch_main_and_runpy_entrypoint(self) -> None:
        with workspace_dir() as tmp_path:
            requirements = tmp_path / "requirements.txt"
            requirements.write_text("requests\n", encoding="utf-8")
            runtime_dir = tmp_path / ".runtime"
            runtime_dir.mkdir()
            playwright_dir = tmp_path / ".playwright"
            playwright_dir.mkdir()
            (playwright_dir / "chromium-123").mkdir()

            state_payload = {
                "requirements_hash": launch.file_sha256(requirements),
                "playwright_version": "1.0",
            }
            state_file = runtime_dir / "launch-state.json"
            state_file.write_text(json.dumps(state_payload), encoding="utf-8")

            with patch.object(launch, "REPO_ROOT", tmp_path), patch.object(launch, "RUNTIME_DIR", runtime_dir), patch.object(
                launch, "STATE_FILE", state_file
            ), patch.object(launch, "PLAYWRIGHT_BROWSERS_DIR", playwright_dir), patch.object(
                launch, "package_version", return_value="1.0"
            ), patch.object(
                launch, "dependencies_look_installed", return_value=True
            ), patch.object(launch, "ensure_local_pandoc", return_value=None), patch.object(
                launch, "launch_app", return_value=0
            ) as launch_app_mock:
                self.assertEqual(launch.main(), 0)
                launch_app_mock.assert_called_once()

        path = Path(launch.__file__)
        with self.assertRaises(SystemExit) as success_exit:
            runpy.run_path(str(path), run_name="__main__", init_globals={"_pyrefman_launch_main_override": lambda: 0})
        self.assertEqual(success_exit.exception.code, 0)

        with self.assertRaises(SystemExit) as error_exit:
            runpy.run_path(
                str(path),
                run_name="__main__",
                init_globals={"_pyrefman_launch_main_override": lambda: (_ for _ in ()).throw(RuntimeError("bad"))},
            )
        self.assertEqual(error_exit.exception.code, 1)

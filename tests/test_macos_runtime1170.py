"""Platform defaults and desktop media discovery; no real projects or installs."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from filmprod.projects import ProjectCatalog, catalog_path, project_identity
from filmprod.render import _exe, _run


class MacCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="film-macos-TEST-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_macos_uses_application_support_and_does_not_create_on_lookup(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "wrong-windows")}, clear=True), \
                patch("filmprod.projects.sys.platform", "darwin"), \
                patch("filmprod.projects.Path.home", return_value=self.root):
            path = catalog_path()
        self.assertEqual(path, self.root / "Library/Application Support/FilmProduction/projects.sqlite3")
        self.assertFalse(path.parent.exists())

    def test_explicit_catalog_wins_on_both_platforms(self):
        expected = self.root / "自定 data/catalog.sqlite3"
        for platform in ("darwin", "win32"):
            with self.subTest(platform=platform), \
                    patch.dict(os.environ, {"FILMPROD_CATALOG_PATH": str(expected)}, clear=True), \
                    patch("filmprod.projects.sys.platform", platform):
                self.assertEqual(catalog_path(), expected)

    def test_relative_override_is_rejected_on_macos(self):
        with patch.dict(os.environ, {"FILMPROD_CATALOG_PATH": "relative/catalog.sqlite3"}, clear=True), \
                patch("filmprod.projects.sys.platform", "darwin"):
            with self.assertRaisesRegex(ValueError, "must be absolute"):
                catalog_path()

    def test_windows_default_and_environment_override_are_preserved(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch("filmprod.projects.sys.platform", "win32"), \
                patch("filmprod.projects.Path.home", return_value=self.root):
            self.assertEqual(catalog_path(), self.root / "AppData/Local/FilmProduction/projects.sqlite3")
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "custom")}, clear=True), \
                patch("filmprod.projects.sys.platform", "win32"):
            self.assertEqual(catalog_path(), self.root / "custom/FilmProduction/projects.sqlite3")

    def test_unicode_space_and_quote_paths_round_trip_without_shell(self):
        data = self.root / "用户's 支持文件 $data" / "catalog.sqlite3"
        project = self.root / "作品's 第一章 $film"
        catalog = ProjectCatalog(data)
        try:
            created = catalog.dispatch("create", {"op_id": "create-mac-path-test", "root": str(project),
                "project_id": "MAC-PATH-TEST", "title": "TEST 中文项目", "test_only": True})
            self.assertEqual(created["project"]["project_id"], "MAC-PATH-TEST")
        finally:
            catalog.close()
        self.assertEqual(project_identity(project)["title"], "TEST 中文项目")
        catalog = ProjectCatalog(data)
        try:
            state = catalog.snapshot()
            self.assertEqual(len(state["projects"]), 1)
            self.assertTrue(state["projects"][0]["available"])
            self.assertEqual(Path(state["projects"][0]["root"]), project.resolve())
        finally:
            catalog.close()


class DesktopMediaDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="film-media-path-TEST-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.arm = self.root / "Apple Silicon bin"
        self.intel = self.root / "Intel bin"
        self.pathbin = self.root / "user's 中文 bin"
        for directory in (self.arm, self.intel, self.pathbin):
            directory.mkdir()
        self.addCleanup(patch.stopall)
        patch("filmprod.render.MACOS_EXECUTABLE_DIRS", (str(self.arm), str(self.intel))).start()

    def executable(self, directory, name):
        path = directory / name
        path.write_bytes(b"TEST executable fixture, never launched")
        path.chmod(0o755)
        return path

    def test_macos_gui_without_homebrew_path_checks_both_standard_locations(self):
        for directory in (self.arm, self.intel):
            for name in ("ffmpeg", "ffprobe"):
                with self.subTest(directory=directory.name, name=name):
                    path = self.executable(directory, name)
                    with patch("filmprod.render.sys.platform", "darwin"), \
                            patch("filmprod.render.shutil.which", return_value=None), \
                            patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
                        before = os.environ["PATH"]
                        self.assertEqual(_exe(name), str(path.resolve()))
                        self.assertEqual(os.environ["PATH"], before)
                    path.unlink()

    def test_path_binary_precedes_homebrew_and_explicit_precedes_path(self):
        fallback = self.executable(self.arm, "ffmpeg")
        on_path = self.executable(self.pathbin, "ffmpeg")
        explicit = self.executable(self.intel, "ffmpeg")
        with patch("filmprod.render.sys.platform", "darwin"), \
                patch("filmprod.render.shutil.which", return_value=str(on_path)) as which:
            self.assertEqual(_exe("ffmpeg"), str(on_path.resolve()))
            which.reset_mock()
            self.assertEqual(_exe("ffmpeg", str(explicit)), str(explicit.resolve()))
            which.assert_not_called()
        self.assertTrue(fallback.is_file())

    def test_invalid_explicit_path_fails_without_fallback(self):
        fallback = self.executable(self.arm, "ffmpeg")
        with patch("filmprod.render.sys.platform", "darwin"), \
                patch("filmprod.render.shutil.which", return_value=str(fallback)) as which:
            with self.assertRaisesRegex(ValueError, "指定的 ffmpeg"):
                _exe("ffmpeg", str(self.root / "missing"))
            which.assert_not_called()

    def test_fallback_requires_executable_permission_and_is_macos_media_only(self):
        path = self.executable(self.arm, "ffmpeg")
        with patch("filmprod.render.sys.platform", "darwin"), \
                patch("filmprod.render.shutil.which", return_value=None), \
                patch("filmprod.render.os.access", return_value=False):
            with self.assertRaisesRegex(ValueError, "未找到可执行"):
                _exe("ffmpeg")
        self.assertTrue(path.is_file())
        for platform, name in (("win32", "ffmpeg"), ("linux", "ffmpeg"), ("darwin", "other-command")):
            self.executable(self.arm, name)
            with self.subTest(platform=platform, name=name), \
                    patch("filmprod.render.sys.platform", platform), \
                    patch("filmprod.render.shutil.which", return_value=None):
                with self.assertRaisesRegex(ValueError, "未找到可执行"):
                    _exe(name)

    @unittest.skipIf(os.name == "nt", "POSIX executable permission behavior")
    def test_posix_nonexecutable_file_is_not_launched(self):
        path = self.executable(self.arm, "ffmpeg")
        path.chmod(0o644)
        with patch("filmprod.render.sys.platform", "darwin"), \
                patch("filmprod.render.shutil.which", return_value=None):
            with self.assertRaises(ValueError):
                _exe("ffmpeg")
            with self.assertRaises(ValueError):
                _exe("ffmpeg", str(path))

    def test_argument_with_unicode_and_shell_metacharacters_is_literal(self):
        value = "中文 path's $(echo BAD) ; $HOME"
        executable = _exe("python", sys.executable)
        raw = _run([executable, "-X", "utf8", "-c", "import sys; print(sys.argv[1])", value])
        self.assertEqual(raw.decode("utf-8").strip(), value)

    def test_missing_preview_watermark_filter_reports_required_build_without_retry(self):
        failed = subprocess.CompletedProcess(["ffmpeg"], 1, b"", b"[AVFilterGraph] No such filter: 'drawtext'")
        with patch("filmprod.render.subprocess.run", return_value=failed) as run:
            with self.assertRaisesRegex(ValueError, "ffmpeg-full"):
                _run(["ffmpeg", "-/filter_complex", "filters.txt"])
            self.assertEqual(run.call_count, 1)

    def test_old_ffmpeg_file_option_failure_is_explicit(self):
        failed = subprocess.CompletedProcess(["ffmpeg"], 1, b"", b"Unrecognized option '/filter_complex'.")
        with patch("filmprod.render.subprocess.run", return_value=failed):
            with self.assertRaisesRegex(ValueError, "更新到支持 -/filter_complex"):
                _run(["ffmpeg", "-/filter_complex", "filters.txt"])


if __name__ == "__main__":
    unittest.main()

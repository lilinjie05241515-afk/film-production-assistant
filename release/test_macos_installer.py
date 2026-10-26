"""Portable installer behavior; all paths, packages and projects are synthetic."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock
import zipfile

spec = importlib.util.spec_from_file_location("installer_synthetic_fixtures", Path(__file__).with_name("test_installer.py"))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
installer = fixtures.installer


class MacInstallerTests(unittest.TestCase):
    setUp = fixtures.InstallerTests.setUp
    tearDown = fixtures.InstallerTests.tearDown
    make_package = fixtures.InstallerTests.make_package
    rehash = fixtures.InstallerTests.rehash

    def test_environment_reports_actual_interpreter_without_claiming_client_verification(self):
        result = installer.environment()
        self.assertEqual(result["sys_platform"], sys.platform)
        self.assertEqual(result["current_platform"], {"win32": "windows", "darwin": "macos"}.get(sys.platform, sys.platform))
        self.assertTrue(Path(result["executable"]).is_absolute())
        self.assertEqual(Path(result["executable"]).resolve(), Path(sys.executable).resolve())
        self.assertEqual(result["supported_platforms"], ["windows", "macos"])
        self.assertTrue(result["environment_checked"])
        self.assertNotIn("platform_tested", result)

    def test_macos_gui_media_fallback_and_path_precedence(self):
        directory = self.root / "TEST Homebrew with space" / "bin"
        directory.mkdir(parents=True)
        media = directory / "ffmpeg"
        media.write_text("synthetic executable", encoding="utf-8")
        media.chmod(0o755)
        with mock.patch.object(installer, "MAC_MEDIA_DIRECTORIES", (str(directory),)), mock.patch.object(installer.shutil, "which", return_value=None):
            self.assertEqual(installer.optional_executable("ffmpeg", "macos"), str(media.resolve()))
            self.assertIsNone(installer.optional_executable("ffprobe", "macos"))
            self.assertIsNone(installer.optional_executable("ffmpeg", "windows"))
        with mock.patch.object(installer, "MAC_MEDIA_DIRECTORIES", (str(directory),)), mock.patch.object(installer.shutil, "which", return_value=sys.executable):
            self.assertEqual(installer.optional_executable("ffmpeg", "macos"), str(Path(sys.executable).resolve()))

    def test_windows_only_archive_can_verify_but_not_install_on_macos(self):
        manifest = installer.read_json(self.package / installer.MANIFEST)
        manifest["runtime"]["platforms"] = ["windows"]
        installer.write_json(self.package / installer.MANIFEST, manifest)
        self.assertTrue(installer.verify_package(self.package)["verified"])
        detected = installer.environment()
        detected.update(current_platform="macos", platform_supported=True)
        with mock.patch.object(installer, "environment", return_value=detected):
            with self.assertRaisesRegex(ValueError, "未声明支持当前系统 macos"):
                installer.install(self.package, self.app, self.data, self.config)
        self.assertFalse((self.app / "releases").exists())
        self.assertFalse(self.data.exists())
        self.assertFalse(self.config.exists())

    def test_unicode_archive_collisions_rejected_before_extraction(self):
        for names in (("caf\u00e9.txt", "cafe\u0301.txt"), ("caf\u00e9", "cafe\u0301/child.txt")):
            with self.subTest(names=names):
                package = self.root / "unicode-collision.zip"
                with zipfile.ZipFile(package, "w") as archive:
                    for name in names:
                        archive.writestr(name, "synthetic")
                with self.assertRaises(ValueError):
                    with installer.package_directory(package):
                        self.fail("colliding archive reached extraction")

    def test_unicode_manifest_alias_rejected(self):
        manifest = installer.read_json(self.package / installer.MANIFEST)
        for name in ("caf\u00e9.txt", "cafe\u0301.txt"):
            manifest["files"].append({"path": name, "sha256": "0" * 64, "size": 0})
        installer.write_json(self.package / installer.MANIFEST, manifest)
        with self.assertRaisesRegex(ValueError, "重复路径"):
            installer.verify_package(self.package)

    def test_decomposed_filesystem_name_matches_single_normalized_manifest_name(self):
        file = self.package / "cafe\u0301.txt"
        file.write_text("synthetic Unicode text", encoding="utf-8")
        self.rehash(self.package)
        manifest = installer.read_json(self.package / installer.MANIFEST)
        for entry in manifest["files"]:
            if entry["path"] in ("caf\u00e9.txt", "cafe\u0301.txt"):
                entry["path"] = "caf\u00e9.txt"
        installer.write_json(self.package / installer.MANIFEST, manifest)
        self.assertTrue(installer.verify_package(self.package)["verified"])

    def test_full_install_with_chinese_spaces_and_shell_metacharacters(self):
        root = self.root / "TEST 中文 空格 & literal"
        app, data, config = root / "application", root / "data", root / "config"
        installed = installer.install(self.package, app, data, config)
        self.assertEqual(installed["status"], "installed")
        mcp = installer.read_json(Path(installed["deployment"]) / "plugin/.mcp.json")["mcpServers"]["film-production"]
        self.assertEqual(mcp["command"], str(Path(sys.executable).resolve()))
        self.assertIn(str(app.resolve() / "deployments/1.6.0/plugin/mcp_server.py"), mcp["args"])
        self.assertEqual(installed["smoke"]["tool_count"], 12)
        plan = installer.host_plan(app)
        self.assertTrue(Path(plan["marketplace_root"]).is_dir())
        self.assertFalse(plan["host_registration_performed"])

    @unittest.skipIf(os.name == "nt", "POSIX bootstrap is executed on macOS CI")
    def test_shell_wrapper_preserves_arguments_from_space_and_unicode_directory(self):
        scripts = self.root / "TEST 解压 目录 & literal" / "release"
        scripts.mkdir(parents=True)
        shutil.copy2(Path(__file__).with_name("bootstrap.sh"), scripts / "bootstrap.sh")
        shutil.copy2(Path(__file__).with_name("installer.py"), scripts / "installer.py")
        package = self.root / "TEST 包 & literal"
        shutil.copytree(self.package, package)
        result = subprocess.run(["/bin/sh", str(scripts / "bootstrap.sh"), "--python", sys.executable,
                                 "verify", "--package", str(package)], capture_output=True, text=True,
                                encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["verified"])

    @unittest.skipIf(os.name == "nt", "POSIX bootstrap is executed on macOS CI")
    def test_shell_wrapper_honors_invalid_explicit_interpreter(self):
        result = subprocess.run(["/bin/sh", str(Path(__file__).with_name("bootstrap.sh")), "--python",
                                 str(self.root / "TEST no python3"), "env"], capture_output=True,
                                text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn("不会改用其他解释器", result.stderr)
        self.assertEqual(result.stdout, "")

    @unittest.skipIf(os.name == "nt", "POSIX bootstrap is executed on macOS CI")
    def test_shell_wrapper_detects_existing_python3_without_override(self):
        # Keep the chosen Python visible without relying on the developer's shell setup.
        directory = self.root / "TEST python3 path"
        directory.mkdir()
        (directory / "python3").symlink_to(Path(sys.executable).resolve())
        env = dict(os.environ, PATH=str(directory) + os.pathsep + os.environ.get("PATH", ""))
        result = subprocess.run(["/bin/sh", str(Path(__file__).with_name("bootstrap.sh")), "env"], env=env,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["executable"], str(Path(sys.executable).resolve()))


if __name__ == "__main__":
    unittest.main(verbosity=2)

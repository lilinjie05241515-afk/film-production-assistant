"""Synthetic release fixtures only. No actual user installations or works."""
import importlib.util
import json
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location("publisher", Path(__file__).with_name("publisher.py"))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="film-publisher-TEST-")
        self.root = Path(self.tmp.name)
        self.payload = self.root / "payload"
        (self.payload / "plugin/.codex-plugin").mkdir(parents=True)
        (self.payload / "plugin/skills/film-production-agent").mkdir(parents=True)
        (self.payload / "plugin/skills/film-production-agent/SKILL.md").write_text("---\nname: film-production-agent\ndescription: synthetic test only\n---\nTEST only\n", encoding="utf-8")
        (self.payload / "install.py").write_text("# TEST only\n", encoding="utf-8")
        self.version("1.6.0")
        self.out = self.root / "archives"

    def tearDown(self):
        self.tmp.cleanup()

    def version(self, version):
        (self.payload / "plugin/.codex-plugin/plugin.json").write_text(json.dumps({"name": p.NAME, "version": version}), encoding="utf-8")

    def build(self, version="1.6.0", channel="stable"):
        self.version(version)
        return Path(p.build(self.payload, self.out, version, channel)["archive_path"])

    def mutated(self, archive, extra=None, replace=None):
        target = self.root / ("bad-" + str(len(list(self.root.glob("bad-*")))) + ".zip")
        files = p.package_files(archive)
        if extra:
            files.update(extra)
        if replace:
            files.update(replace)
        with zipfile.ZipFile(target, "w") as z:
            for name, raw in files.items():
                z.writestr(name, raw)
        return target

    def test_build_verify_and_exact_sha(self):
        archive = self.build()
        result = p.verify(archive)
        self.assertTrue(result["verified"])
        self.assertFalse(result["runtime_changed"])
        self.assertEqual(p.verify(archive, p.sha256(archive.read_bytes()))["version"], "1.6.0")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            p.verify(archive, "0" * 64)

    def test_immutable_build(self):
        archive = self.build()
        before = archive.read_bytes()
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(before, archive.read_bytes())

    def test_tampering_missing_and_extra_rejected(self):
        archive = self.build()
        for package in (self.mutated(archive, extra={"unlisted.txt": b"test"}),
                        self.mutated(archive, replace={"install.py": b"changed"})):
            with self.assertRaises(ValueError):
                p.verify(package)
        files = p.package_files(archive)
        files.pop("install.py")
        target = self.root / "missing.zip"
        with zipfile.ZipFile(target, "w") as z:
            for name, raw in files.items():
                z.writestr(name, raw)
        with self.assertRaises(ValueError):
            p.verify(target)

    def test_unsafe_windows_paths(self):
        for name in ("../escape", "a/../../escape", "/absolute", "C:/absolute", "a\\escape", "a//b", "a/./b", "CON.txt", "a/aux", "a./b", "a/b ", "a:stream", "a\x01.txt", "a<b", "a>b", 'a"b', "a|b", "a?b", "a*b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                p.safe_name(name)

    def test_case_duplicate_and_file_directory_collisions(self):
        for names in (["File.py", "file.py"], ["a", "A/b"], ["a", "a"]):
            with self.assertRaises(ValueError):
                p.validate_names(names)
        archive = self.build()
        with self.assertRaises(ValueError):
            p.verify(self.mutated(archive, extra={"INSTALL.py": b"duplicate"}))

    def test_zip_traversal_and_symlink_rejected(self):
        archive = self.build()
        with self.assertRaises(ValueError):
            p.verify(self.mutated(archive, extra={"../escape": b"escape"}))
        target = self.root / "symlink.zip"
        with zipfile.ZipFile(target, "w") as z:
            entry = zipfile.ZipInfo("link")
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(entry, "outside")
        with self.assertRaises(ValueError):
            p.verify(target)

    def test_hygiene_blocks_personal_paths_data_secrets(self):
        examples = {"manual.md": b"C:/Users/synthetic/private", "config.json": b'{"root":"F:/old-engine"}',
                    ".project/registry.sqlite3": b"TEST", ".env": b"secret=TEST", "secret.txt": b"sk-proj-" + b"A" * 32,
                    "binding.md": b"https://chatgpt.com/c/11111111-2222-3333-4444-555555555555"}
        for name, raw in examples.items():
            with self.subTest(name=name):
                self.assertTrue(p.inspect_payload({name: raw}))
        self.assertFalse(p.inspect_payload({"guide.md": b"${PLUGIN_ROOT}/runtime and %LOCALAPPDATA%"}))

    def test_version_and_manifest_identity(self):
        for version in ("../1.0.0", "01.0.0", "1.0", "1.0.0+other"):
            with self.assertRaises(ValueError):
                p.version_key(version)
        with self.assertRaises(ValueError):
            self.build("1.6.0-rc.1")
        self.version("1.4.1")
        with self.assertRaisesRegex(ValueError, "插件版本"):
            p.build(self.payload, self.out, "1.6.0")
        self.assertLess(p.version_key("1.6.0-rc.2"), p.version_key("1.6.0-rc.10"))
        self.assertLess(p.version_key("1.6.0-rc.10"), p.version_key("1.6.0"))

    @unittest.skipUnless(shutil.which("git"), "Git unavailable")
    def test_publish_check_fetch_local_git_and_no_runtime_change(self):
        archive = self.build()
        repo = self.root / "marketplace"
        result = p.publish(archive, repo)
        self.assertFalse(result["remote_published"])
        self.assertFalse(result["runtime_changed"])
        self.assertEqual(p.git(repo, "remote"), "")
        self.assertEqual(p.git(repo, "status", "--porcelain"), "")
        state = p.check(repo, "1.5.0")
        self.assertTrue(state["update_available"])
        self.assertFalse(p.check(repo, "1.6.0")["update_available"])
        original = p.sha256(archive.read_bytes())
        fetched = p.fetch(repo, self.root / "download")
        self.assertEqual(fetched["archive_sha256"], original)
        self.assertFalse(fetched["runtime_changed"])
        self.assertEqual(p.fetch(repo, self.root / "download")["status"], "already_fetched_verified")
        with self.assertRaises(FileExistsError):
            p.publish(archive, repo)
        newer = self.build("1.6.1")
        p.publish(newer, repo)
        self.assertEqual(p.check(repo)["latest"], "1.6.1")
        self.assertEqual(p.sha256((repo / result["archive"]).read_bytes()), original)
        self.assertEqual(p.fetch(repo, self.root / "older", "1.6.0")["version"], "1.6.0")

    @unittest.skipUnless(shutil.which("git"), "Git unavailable")
    def test_development_separate_and_dirty_repo_rejected(self):
        repo = self.root / "marketplace"
        p.publish(self.build(), repo)
        stable = (repo / ".agents/plugins/marketplace.json").read_bytes()
        p.publish(self.build("1.7.0-rc.1", "development"), repo)
        self.assertEqual((repo / ".agents/plugins/marketplace.json").read_bytes(), stable)
        self.assertEqual(p.check(repo, channel="development")["latest"], "1.7.0-rc.1")
        self.assertEqual(p.check(repo)["latest"], "1.6.0")
        (repo / "unrelated.txt").write_text("do not commit")
        with self.assertRaisesRegex(ValueError, "未提交"):
            p.publish(self.build("1.6.2"), repo)
        self.assertFalse((repo / ".publish.lock").exists())

    @unittest.skipUnless(shutil.which("git"), "Git unavailable")
    def test_index_or_cached_archive_tampering_rejected(self):
        repo = self.root / "marketplace"
        p.publish(self.build(), repo)
        index_path = repo / "channels/stable.json"
        index = p.read_json(index_path)
        index["releases"][0]["archive"] = "../outside.zip"
        p.write_json(index_path, index)
        with self.assertRaises(ValueError):
            p.check(repo)

    def test_no_takeover_of_nonempty_source(self):
        repo = self.root / "existing"
        repo.mkdir()
        (repo / "owned.txt").write_text("existing user file")
        with self.assertRaises(ValueError):
            p.init_repo(repo)
        self.assertEqual((repo / "owned.txt").read_text(), "existing user file")


if __name__ == "__main__":
    unittest.main(verbosity=2)

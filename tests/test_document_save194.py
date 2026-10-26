"""Real derived Markdown files, exclusively within synthetic project directories."""
import hashlib
import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from filmprod import documents
from filmprod.core import Registry, ConflictError


SOURCE = Path(__file__).resolve().parents[1]


class DocumentSaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="film-save194-SYNTHETIC-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "TEST-PROJECT"
        self.body = "\ufeff# TEST 合成标题\r\n\r\n- **粗体**  \r\n|A|B|\n|---|---|\n|1|2|\r\n```py\nprint('测试')\n```\n\r尾行"
        self.aid = "../角色:*稿"
        registry = Registry(self.root)
        try:
            registry.dispatch("project.init", dict(op_id="init", project_id="TEST-SAVE194", title="Synthetic only", test_only=True))
            first = registry.dispatch("artifact.save", dict(op_id="v1", expected_project_id="TEST-SAVE194", artifact_id=self.aid,
                kind="novel", scope="synthetic-chapter", base_version=0, content=self.body, metadata={}, deps=[]))["artifact"]
            registry.dispatch("artifact.save", dict(op_id="v2", expected_project_id="TEST-SAVE194", artifact_id=self.aid,
                kind="novel", scope="synthetic-chapter", base_version=1, content="# TEST 新候选正文", metadata={}, deps=[]))
        finally:
            registry.close()
        self.payload = dict(op_id="save-test-194", expected_project_id="TEST-SAVE194", artifact_id=self.aid,
                            version=1, expected_sha256=first["sha256"])
        self.database = self.root / ".project/registry.sqlite3"
        self.db_before = self.database.read_bytes()
        self.export_dir = self.root / "11-导出/Markdown"
        self.env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
                    "FILMPROD_CATALOG_PATH": str(self.base / "TEST-CATALOG.sqlite3")}

    def save(self, payload=None):
        registry = Registry.open_readonly(self.root)
        try:
            before = registry.db.total_changes
            result = registry.dispatch("document.save", self.payload if payload is None else payload)
            self.assertEqual(registry.db.total_changes, before)
            self.assertEqual(registry.db.execute("PRAGMA query_only").fetchone()[0], 1)
            return result
        finally:
            registry.close()

    def state(self):
        registry = Registry.open_readonly(self.root)
        try:
            state = registry.snapshot()
            state.pop("observed_at")
            return state
        finally:
            registry.close()

    def assert_database_unchanged(self):
        self.assertEqual(self.database.read_bytes(), self.db_before)

    def assert_no_temporary_files(self):
        self.assertFalse(list(self.export_dir.glob(".film-export-*.tmp")))

    def load_server(self):
        spec = importlib.util.spec_from_file_location("mcp_save194", SOURCE / "plugin/mcp_server.py")
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        return server

    def run_cli(self, root=None, payload=None):
        return subprocess.run([sys.executable, "-B", "-X", "utf8", str(SOURCE / "film.py"), "--root", str(root or self.root),
            "dispatch", "document.save", "--file", "-"], input=json.dumps(self.payload if payload is None else payload, ensure_ascii=False),
            text=True, encoding="utf-8", capture_output=True, env=self.env, cwd=SOURCE, timeout=30)

    def run_mcp(self, root=None, payload=None):
        request = {"jsonrpc": "2.0", "id": 194, "method": "tools/call", "params": {"name": "film_dispatch", "arguments": {
            "root": str(root or self.root), "action": "document.save", "payload": self.payload if payload is None else payload}}}
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(SOURCE / "plugin/mcp_server.py")],
            input=json.dumps(request, ensure_ascii=False) + "\n", text=True, encoding="utf-8", capture_output=True,
            env=self.env, cwd=SOURCE, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["result"]

    def test_exact_older_version_writes_utf8_and_returns_verified_receipt_without_registry_changes(self):
        before = self.state()
        receipt = self.save()
        path = Path(receipt["local_path"])
        self.assertTrue(receipt["saved_verified"] and receipt["readback_verified"])
        self.assertEqual(receipt["status"], "created")
        self.assertEqual(receipt["op_id"], self.payload["op_id"])
        self.assertEqual(receipt["project_id"], "TEST-SAVE194")
        self.assertEqual(receipt["project_root"], str(self.root))
        self.assertEqual(receipt["export_dir"], str(self.export_dir))
        self.assertEqual(path.parent, self.export_dir)
        self.assertEqual(path.name, receipt["filename"])
        self.assertEqual(path.suffix, ".md")
        self.assertIn("_v001_", path.name)
        self.assertIn(self.payload["expected_sha256"][:16], path.name)
        self.assertNotIn(":", path.name)
        self.assertEqual(receipt["artifact_ref"], {"artifact_id": self.aid, "version": 1})
        self.assertEqual(path.read_bytes(), self.body.encode("utf-8"))
        self.assertEqual(receipt["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(receipt["size_bytes"], len(self.body.encode("utf-8")))
        self.assertFalse(receipt["registry_changed"])
        self.assertNotIn("content", receipt)
        self.assertNotIn("data_base64", receipt)
        self.assertTrue(self.state()["capabilities"]["document_save"])
        self.assertEqual(self.state(), before)
        self.assert_database_unchanged()
        self.assert_no_temporary_files()

    def test_repeated_requests_reuse_identical_file_without_touching_mtime(self):
        first = self.save()
        path = Path(first["local_path"])
        original_stat = path.stat()
        for payload in (self.payload, dict(self.payload, op_id="another-explicit-click")):
            repeated = self.save(payload)
            self.assertEqual(repeated["status"], "reused")
            self.assertEqual(repeated["local_path"], first["local_path"])
            self.assertEqual(path.stat().st_mtime_ns, original_stat.st_mtime_ns)
        self.assertEqual(len(list(self.export_dir.glob("*.md"))), 1)
        self.assert_database_unchanged()

    def test_invalid_identity_version_hash_and_destination_write_nothing(self):
        cases = [dict(self.payload, expected_project_id="WRONG"), dict(self.payload, expected_sha256="0" * 64),
                 dict(self.payload, expected_sha256="bad"), dict(self.payload, version=True), dict(self.payload, version=999),
                 dict(self.payload, version="1"), dict(self.payload, op_id=""), dict(self.payload, target_path=str(self.base / "escape.md")),
                 dict(self.payload, filename="chosen.md"), dict(self.payload, export_dir=str(self.base))]
        for field in self.payload:
            cases.append({key: value for key, value in self.payload.items() if key != field})
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.save(payload)
            self.assertFalse((self.root / "11-导出").exists())
        self.assert_database_unchanged()

    def test_existing_different_bytes_are_preserved_and_never_report_success(self):
        path = Path(self.save()["local_path"])
        path.write_bytes(b"synthetic user edits that must survive")
        before = path.stat().st_mtime_ns
        with self.assertRaises(ConflictError):
            self.save()
        self.assertEqual(path.read_bytes(), b"synthetic user edits that must survive")
        self.assertEqual(path.stat().st_mtime_ns, before)
        self.assert_database_unchanged()
        self.assert_no_temporary_files()

    def test_parent_or_target_non_file_types_are_rejected_without_replacing_them(self):
        parent = self.root / "11-导出"
        parent.write_bytes(b"synthetic directory blocker")
        with self.assertRaises(ValueError):
            self.save()
        self.assertEqual(parent.read_bytes(), b"synthetic directory blocker")
        parent.unlink()
        path = Path(self.save()["local_path"])
        path.unlink()
        path.mkdir()
        with self.assertRaises(ValueError):
            self.save()
        self.assertTrue(path.is_dir())
        self.assert_database_unchanged()

    def test_existing_hard_link_is_not_accepted_even_when_bytes_match(self):
        path = Path(self.save()["local_path"])
        twin = self.base / "synthetic-hardlink.md"
        os.link(path, twin)
        self.assertEqual(path.stat().st_nlink, 2)
        with self.assertRaises(ValueError):
            self.save()
        self.assertEqual(twin.read_bytes(), self.body.encode("utf-8"))
        self.assertEqual(path.stat().st_nlink, 2)
        self.assert_database_unchanged()

    def test_file_and_directory_symbolic_links_are_refused(self):
        outside = self.base / "synthetic-outside"
        outside.mkdir()
        parent = self.root / "11-导出"
        try:
            parent.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest("Synthetic symlink creation unavailable: " + str(exc))
        try:
            with self.assertRaises(ValueError):
                self.save()
            self.assertFalse(list(outside.iterdir()))
        finally:
            parent.unlink()
        path = Path(self.save()["local_path"])
        path.unlink()
        outside_file = outside / "synthetic-original.md"
        outside_file.write_bytes(self.body.encode("utf-8"))
        path.symlink_to(outside_file)
        with self.assertRaises(ValueError):
            self.save()
        self.assertEqual(outside_file.read_bytes(), self.body.encode("utf-8"))
        self.assert_database_unchanged()

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_windows_junction_at_either_fixed_directory_is_refused_before_descending(self):
        outside = self.base / "synthetic-junction-target"
        outside.mkdir()
        for index, relative in enumerate(("11-导出", "11-导出/Markdown")):
            junction = self.root / relative
            junction.parent.mkdir(parents=True, exist_ok=True)
            # This only creates a link between two owned synthetic directories.
            result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            try:
                self.assertTrue(junction.lstat().st_file_attributes & 0x400)
                with self.assertRaises(ValueError):
                    self.save()
                self.assertFalse(list(outside.iterdir()))
            finally:
                # Remove only the junction itself, never recurse into its target.
                junction.rmdir()
        self.assert_database_unchanged()

    @unittest.skipUnless(os.name == "nt", "Windows concurrent junction regression")
    def test_directory_replaced_with_junction_before_publication_is_detected(self):
        outside = self.base / "synthetic-swapped-target"
        outside.mkdir()
        moved = self.root / "synthetic-moved-export"
        real_publish = documents._publish_no_replace
        def swap_before_publish(temporary, target):
            self.export_dir.rename(moved)
            linked = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(self.export_dir), str(outside)], capture_output=True)
            self.assertEqual(linked.returncode, 0, linked.stderr)
            # An attacker-supplied matching name must not be renamed/removed.
            (outside / temporary.name).write_bytes(b"synthetic outside sentinel")
            return real_publish(temporary, target)
        try:
            with patch.object(documents, "_publish_no_replace", side_effect=swap_before_publish):
                with self.assertRaises(ValueError):
                    self.save()
            outside_files = list(outside.iterdir())
            self.assertEqual(len(outside_files), 1)
            self.assertEqual(outside_files[0].read_bytes(), b"synthetic outside sentinel")
            self.assertFalse(list(outside.glob("*.md")))
        finally:
            if self.export_dir.exists() and self.export_dir.lstat().st_file_attributes & 0x400:
                self.export_dir.rmdir()
            if moved.exists():
                moved.rename(self.export_dir)
        self.assert_database_unchanged()

    def test_fsync_failure_cleans_only_the_new_temp_and_allows_safe_retry(self):
        self.export_dir.mkdir(parents=True)
        retained = self.export_dir / ".film-export-unrelated.tmp"
        retained.write_bytes(b"synthetic unrelated existing temporary")
        with patch.object(documents.os, "fsync", side_effect=PermissionError("synthetic fsync denial")):
            with self.assertRaises(PermissionError):
                self.save()
        self.assertEqual(list(self.export_dir.iterdir()), [retained])
        self.assertEqual(retained.read_bytes(), b"synthetic unrelated existing temporary")
        self.assert_database_unchanged()
        self.assertEqual(self.save()["status"], "created")

    def test_publish_failure_never_falls_back_to_overwriting_or_claims_saved(self):
        with patch.object(documents, "_publish_no_replace", side_effect=PermissionError("synthetic rename denial")):
            with self.assertRaises(PermissionError):
                self.save()
        self.assertFalse(list(self.export_dir.iterdir()))
        self.assert_database_unchanged()

    def test_after_publication_failure_leaves_file_for_exact_request_retry(self):
        real_publish = documents._publish_no_replace
        def publish_then_interrupt(temporary, target):
            real_publish(temporary, target)
            raise OSError("synthetic interruption after publish before receipt")
        with patch.object(documents, "_publish_no_replace", side_effect=publish_then_interrupt):
            with self.assertRaises(OSError):
                self.save()
        files = list(self.export_dir.glob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), self.body.encode("utf-8"))
        receipt = self.save()
        self.assertEqual(receipt["status"], "reused")
        self.assertTrue(receipt["saved_verified"])
        self.assert_no_temporary_files()
        self.assert_database_unchanged()

    def test_final_readback_detects_post_publish_tampering(self):
        real_publish = documents._publish_no_replace
        def publish_then_tamper(temporary, target):
            real_publish(temporary, target)
            target.write_bytes(b"synthetic post-publish tampering")
        with patch.object(documents, "_publish_no_replace", side_effect=publish_then_tamper):
            with self.assertRaises(ConflictError):
                self.save()
        files = list(self.export_dir.glob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), b"synthetic post-publish tampering")
        self.assert_no_temporary_files()
        self.assert_database_unchanged()

    def test_readback_rejects_file_modified_in_place_even_when_bytes_end_up_equal(self):
        path = Path(self.save()["local_path"])
        original_fdopen = os.fdopen
        class ConcurrentEditStream:
            def __init__(self, stream):
                self.stream = stream
                self.changed = False
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return self.stream.__exit__(*exc)
            def fileno(self):
                return self.stream.fileno()
            def read(self, count):
                data = self.stream.read(count)
                if not self.changed:
                    info = path.stat()
                    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
                    self.changed = True
                return data
        with patch.object(documents.os, "fdopen", side_effect=lambda *args: ConcurrentEditStream(original_fdopen(*args))):
            with self.assertRaises(ConflictError):
                self.save()
        self.assertEqual(path.read_bytes(), self.body.encode("utf-8"))
        self.assert_database_unchanged()

    def test_concurrent_exact_exports_publish_one_file_and_both_verify(self):
        barrier = threading.Barrier(2)
        real_publish = documents._publish_no_replace
        def simultaneous_publish(temporary, target):
            barrier.wait(timeout=10)
            return real_publish(temporary, target)
        with patch.object(documents, "_publish_no_replace", side_effect=simultaneous_publish), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda index: self.save(dict(self.payload, op_id=f"concurrent-{index}")), range(2)))
        self.assertEqual(sorted(r["status"] for r in results), ["created", "reused"])
        self.assertEqual(results[0]["local_path"], results[1]["local_path"])
        self.assertTrue(all(r["saved_verified"] for r in results))
        self.assertEqual(len(list(self.export_dir.glob("*.md"))), 1)
        self.assert_no_temporary_files()
        self.assert_database_unchanged()

    def test_competing_different_file_is_preserved_without_overwrite(self):
        def other_writer(temporary, target):
            target.write_bytes(b"synthetic competing writer")
            raise FileExistsError("synthetic target race")
        with patch.object(documents, "_publish_no_replace", side_effect=other_writer):
            with self.assertRaises(ConflictError):
                self.save()
        files = list(self.export_dir.glob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), b"synthetic competing writer")
        self.assert_no_temporary_files()
        self.assert_database_unchanged()

    def test_mcp_and_cli_route_uses_readonly_registry(self):
        import film
        server = self.load_server()
        args = {"root": str(self.root), "action": "document.save", "payload": self.payload}
        with patch.dict(os.environ, self.env), patch.object(Registry, "__init__", side_effect=AssertionError("must not open writable registry")):
            result = server.call_tool("film_dispatch", args, None)["structuredContent"]
            self.assertEqual(Path(result["local_path"]).read_bytes(), self.body.encode("utf-8"))
            output = io.StringIO()
            with patch.object(sys, "argv", ["film.py", "--root", str(self.root), "dispatch", "document.save", "--file", "-"]), \
                 patch.object(sys, "stdin", io.StringIO(json.dumps(self.payload))), redirect_stdout(output):
                self.assertEqual(film.main(), 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "reused")
        self.assert_database_unchanged()

    def test_actual_cli_and_mcp_stdio_write_and_read_back_identical_bytes(self):
        cli = self.run_cli()
        self.assertEqual(cli.returncode, 0, cli.stderr)
        first = json.loads(cli.stdout)
        self.assertEqual(first["status"], "created")
        self.assertEqual(Path(first["local_path"]).read_bytes(), self.body.encode("utf-8"))
        next_body = "# TEST 新候选正文"
        next_payload = dict(self.payload, op_id="mcp-created-194", version=2,
                            expected_sha256=hashlib.sha256(next_body.encode("utf-8")).hexdigest())
        mcp_created = self.run_mcp(payload=next_payload)
        self.assertNotIn("isError", mcp_created)
        created = mcp_created["structuredContent"]
        self.assertEqual(created["status"], "created")
        self.assertEqual(created["artifact_ref"]["version"], 2)
        self.assertEqual(Path(created["local_path"]).read_bytes(), next_body.encode("utf-8"))
        mcp = self.run_mcp()
        self.assertNotIn("isError", mcp)
        repeated = mcp["structuredContent"]
        self.assertEqual(repeated["status"], "reused")
        self.assertEqual(repeated["local_path"], first["local_path"])
        self.assertEqual(Path(repeated["local_path"]).read_bytes(), self.body.encode("utf-8"))
        self.assertFalse((self.base / "TEST-CATALOG.sqlite3").exists())
        self.assert_database_unchanged()

    def test_missing_and_schema1_projects_are_not_created_or_migrated_by_cli_or_mcp(self):
        missing = self.base / "MISSING-SYNTHETIC"
        self.assertNotEqual(self.run_cli(missing).returncode, 0)
        self.assertTrue(self.run_mcp(missing)["isError"])
        self.assertFalse(missing.exists())
        old = self.base / "TEST-SCHEMA1"
        database = old / ".project/registry.sqlite3"
        database.parent.mkdir(parents=True)
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT INTO settings VALUES('schema_version','1')")
            db.execute("INSERT INTO settings VALUES('project',?)", (json.dumps({"project_id": "TEST-SAVE194", "title": "Synthetic schema1"}),))
        db.close()
        before = database.read_bytes()
        paths = sorted(str(p.relative_to(old)) for p in old.rglob("*"))
        cli = self.run_cli(old)
        self.assertNotEqual(cli.returncode, 0)
        self.assertIn("schema 2", cli.stderr)
        mcp = self.run_mcp(old)
        self.assertTrue(mcp["isError"])
        self.assertIn("schema 2", mcp["structuredContent"]["error"]["message"])
        self.assertEqual(database.read_bytes(), before)
        self.assertEqual(sorted(str(p.relative_to(old)) for p in old.rglob("*")), paths)


if __name__ == "__main__":
    unittest.main()

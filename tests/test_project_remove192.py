"""Project deregistration uses isolated TEST data and never removes source files."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from filmprod.core import ConflictError, Registry
from filmprod.projects import ProjectCatalog, project_identity


class ProjectRemoval192Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="film-remove192-TEST-")
        self.base = Path(self.temp.name)
        self.catalog = ProjectCatalog(self.base / "catalog.sqlite3")

    def tearDown(self):
        self.catalog.close()
        self.temp.cleanup()

    def create(self, pid, **context):
        return self.catalog.dispatch("create", {
            "op_id": "create-" + pid, "project_id": pid, "title": "TEST " + pid,
            "test_only": True, "root": str(self.base / pid), **context,
        })["project"]

    def request(self, project, op_id="forget"):
        return {
            "op_id": op_id, "project_id": project["project_id"],
            "expected_root": project["root"],
            "expected_registered_at": project["registered_at"],
        }

    def source_files(self, root):
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob("*") if p.is_file()}

    def add_source_material(self, root):
        registry = Registry(root)
        try:
            for version in (0, 1):
                registry.dispatch("artifact.save", {
                    "op_id": "synthetic-script-" + str(version), "artifact_id": "TEST-SCRIPT",
                    "kind": "script", "scope": "TEST-SCENE", "base_version": version,
                    "content": "TEST ONLY history " + str(version + 1),
                })
        finally:
            registry.close()
        media = root / "test-only-media"
        media.mkdir()
        (media / "sample.mp4").write_bytes(b"SYNTHETIC TEST VIDEO BYTES")
        (media / "source.md").write_text("TEST ONLY original source\n", encoding="utf-8")
        # A normal catalog listing reads identity and may establish empty SQLite
        # WAL sidecars; include that ordinary starting state in the byte baseline.
        project_identity(root)

    def test_forget_only_removes_target_registration_and_its_catalog_bindings(self):
        a = self.create("A", thread_id="chat-A", client_project_id="client-A")
        self.create("B", thread_id="chat-B", client_project_id="client-B")
        self.catalog.dispatch("bind", {"op_id": "extra-chat", "project_id": "A", "thread_id": "chat-A2"})
        root = Path(a["root"])
        self.add_source_material(root)
        before = self.source_files(root)
        old_bindings = self.catalog.snapshot()["bindings"]
        result = self.catalog.dispatch("forget", {**self.request(a), "thread_id": "chat-A"})
        self.assertEqual(result["forgotten"], "A")
        self.assertIs(result["source_files_deleted"], False)
        self.assertEqual([p["project_id"] for p in result["projects"]], ["B"])
        self.assertEqual(result["bindings"], [b for b in old_bindings if b["project_id"] == "B"])
        self.assertIsNone(result["current_thread_project"])
        self.assertIsNone(result["resolved_project"])
        self.assertEqual(self.source_files(root), before)
        self.assertEqual(project_identity(root)["project_id"], "A")

    def test_unavailable_source_can_be_forgotten_without_reading_or_recreating_it(self):
        a = self.create("A", thread_id="chat-A")
        root, moved = Path(a["root"]), self.base / "moved-A"
        self.add_source_material(root)
        self.assertEqual(root.parent, self.base)
        self.assertEqual(moved.parent, self.base)
        root.rename(moved)
        before = self.source_files(moved)
        with patch("filmprod.projects.project_identity", side_effect=AssertionError("source must not be read")), \
             patch("filmprod.projects.Registry", side_effect=AssertionError("source must not be opened")):
            result = self.catalog.dispatch("forget", self.request(a))
        self.assertEqual(result["projects"], [])
        self.assertFalse(root.exists())
        self.assertEqual(self.source_files(moved), before)

    def test_changed_root_rejects_stale_confirmation_before_removing_bindings(self):
        a = self.create("A", thread_id="chat-A")
        root, moved = Path(a["root"]), self.base / "moved-A"
        self.assertEqual(root.parent, self.base)
        self.assertEqual(moved.parent, self.base)
        root.rename(moved)
        latest = self.catalog.dispatch("relink", {"op_id": "move-A", "project_id": "A", "root": str(moved)})["project"]
        with self.assertRaisesRegex(ConflictError, "源文件夹登记已变化"):
            self.catalog.dispatch("forget", self.request(a))
        self.assertFalse(self.catalog.dispatch("outcome", {"op_id": "forget"})["found"])
        self.assertEqual(self.catalog.snapshot({"thread_id": "chat-A"})["resolved_project"]["root"], str(moved))
        self.assertEqual(self.catalog.dispatch("forget", self.request(latest, "forget-current"))["forgotten"], "A")

    def test_invalid_expected_roots_are_rejected_and_lexical_equivalent_root_is_accepted(self):
        a = self.create("A")
        for index, value in enumerate((None, "", "A", 7, [], False)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.catalog.dispatch("forget", {**self.request(a, "bad-" + str(index)), "expected_root": value})
        equivalent = str(self.base / "unused" / ".." / "A")
        with patch("filmprod.projects.project_identity", side_effect=AssertionError("no source lookup")):
            result = self.catalog.dispatch("forget", {**self.request(a), "expected_root": equivalent})
        self.assertEqual(result["forgotten"], "A")

    def test_reregister_preserves_content_and_does_not_restore_old_bindings_or_replay_deletion(self):
        a = self.create("A", thread_id="chat-A", client_project_id="client-A")
        root = Path(a["root"])
        self.add_source_material(root)
        before = self.source_files(root)
        request = self.request(a)
        deleted = self.catalog.dispatch("forget", request)
        restored = self.catalog.dispatch("register", {"op_id": "register-A-again", "root": str(root)})
        self.assertEqual(restored["project"]["project_id"], "A")
        self.assertEqual(restored["project"]["title"], "TEST A")
        self.assertEqual(restored["bindings"], [])
        self.assertEqual(self.source_files(root), before)
        self.assertEqual(self.catalog.dispatch("forget", request), deleted)
        self.assertEqual([p["project_id"] for p in self.catalog.snapshot()["projects"]], ["A"])
        outcome = self.catalog.dispatch("outcome", {"op_id": "forget"})
        self.assertEqual(outcome["operation"]["result"], deleted)
        with self.assertRaises(ConflictError):
            self.catalog.dispatch("forget", {**request, "project_id": "B"})
        self.assertEqual(self.source_files(root), before)

    def test_new_registration_of_same_identity_rejects_old_confirmation(self):
        with patch("filmprod.projects.now", return_value="TEST-first-registration"):
            a = self.create("A", thread_id="chat-A")
        self.catalog.dispatch("forget", self.request(a, "other-window-forget"))
        with patch("filmprod.projects.now", return_value="TEST-second-registration"):
            restored = self.catalog.dispatch("register", {"op_id": "register-A-again", "root": a["root"], "thread_id": "chat-A-new"})["project"]
        with self.assertRaisesRegex(ConflictError, "登记已更新"):
            self.catalog.dispatch("forget", self.request(a, "old-window-forget"))
        self.assertEqual(self.catalog.snapshot({"thread_id": "chat-A-new"})["resolved_project"]["project_id"], "A")
        self.assertFalse(self.catalog.dispatch("outcome", {"op_id": "old-window-forget"})["found"])
        self.assertEqual(self.catalog.dispatch("forget", self.request(restored, "current-window-forget"))["forgotten"], "A")


if __name__ == "__main__":
    unittest.main()

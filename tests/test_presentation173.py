"""Synthetic board management regressions; never open a real work project."""
import json
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from filmprod.core import ConflictError, Registry


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="film-presentation173-TEST-")
        self.root = Path(self.temp.name) / "TEST-PROJECT"
        self.r = Registry(self.root)
        self.call("project.init", project_id="TEST-173", title="synthetic presentation", test_only=True)
        self.first = self.save("DIRECTOR", "director", "Synthetic immutable source\r\n原文。")

    def tearDown(self):
        self.r.close()
        self.temp.cleanup()

    def call(self, action, **payload):
        payload.setdefault("op_id", uuid.uuid4().hex)
        if action != "project.init":
            payload.setdefault("expected_project_id", "TEST-173")
        return self.r.dispatch(action, payload)

    def save(self, aid, kind, content, base=0, deps=None):
        return self.call("artifact.save", artifact_id=aid, kind=kind, scope=aid,
                         content=content, base_version=base, deps=deps or [],
                         metadata={"title": "Original title"})["artifact"]

    def request(self, artifact=None, **overrides):
        item = artifact or self.first
        payload = {"op_id": uuid.uuid4().hex, "expected_project_id": "TEST-173",
                   "artifact_id": item["artifact_id"], "version": item["version"],
                   "expected_sha256": item["sha256"], "base_revision": 0,
                   "display_category": "video_prompt", "title": "旧画面稿（历史参考）", "archived": True}
        payload.update(overrides)
        return payload

    def protected_rows(self):
        tables = ("artifacts", "tasks", "threads", "decisions", "sync", "media",
                  "approved_segments", "master_revisions", "master_bindings", "master_sync")
        return {name: [tuple(row) for row in self.r.db.execute(f"SELECT * FROM {name} ORDER BY rowid")]
                for name in tables}

    def write_state(self):
        return {table: [tuple(row) for row in self.r.db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                for table in ("settings", "events", "operations")}

    def test_management_preserves_content_dependencies_approvals_and_task_locks(self):
        self.call("content.approve", artifact_id="DIRECTOR", version=1, scope="DIRECTOR",
                  evidence="synthetic approval", actor="test", synthetic=True)
        self.save("VIDEO", "video_prompt", "Synthetic video text", deps=[{"artifact_id": "DIRECTOR", "version": 1}])
        self.call("task.create", task_id="TASK", title="Synthetic task", module="video_prompt",
                  scope="episode/test/task", inputs=[{"artifact_id": "DIRECTOR", "version": 1}],
                  must_keep=[], allowed_changes=[], requirements=[])
        before = self.protected_rows()
        project = self.r._project()
        result = self.r.dispatch("presentation.set", self.request())
        self.assertTrue(result["presentation_only"])
        self.assertTrue(result["readback_verified"])
        self.assertEqual(result["entry"]["revision"], 1)
        self.assertEqual(self.protected_rows(), before)
        self.assertEqual(self.r._project(), project)
        snap = self.r.snapshot()
        self.assertEqual(snap["current_content"][0]["category"], "director")
        self.assertEqual(snap["presentation"]["entries"], [result["entry"]])
        self.assertTrue(snap["capabilities"]["presentation_management"])
        self.assertFalse(snap["presentation"]["approval_inferred"])

    def test_idempotency_and_revision_compare_and_swap(self):
        payload = self.request()
        first = self.r.dispatch("presentation.set", payload)
        state = self.write_state()
        self.assertEqual(self.r.dispatch("presentation.set", payload), first)
        self.assertEqual(self.write_state(), state)
        with self.assertRaises(ConflictError):
            self.r.dispatch("presentation.set", dict(payload, title="Different request"))
        with self.assertRaises(ConflictError):
            self.r.dispatch("presentation.set", self.request(title="Stale request"))
        second = self.r.dispatch("presentation.set", self.request(base_revision=1, archived=False,
                                                                  display_category="director", title="Restored"))
        self.assertEqual(second["entry"]["revision"], 2)
        self.assertFalse(second["entry"]["archived"])
        # Replaying a receipt reports its original result; it does not roll back.
        self.assertEqual(self.r.dispatch("presentation.set", payload), first)
        self.assertEqual(self.r.snapshot()["presentation"]["entries"], [second["entry"]])

    def test_exact_version_binding_does_not_follow_new_content(self):
        first = self.r.dispatch("presentation.set", self.request())
        second = self.save("DIRECTOR", "director", "New candidate", base=1)
        snap = self.r.snapshot()
        self.assertEqual(snap["artifacts"][0]["version"], 2)
        self.assertEqual(snap["presentation"]["entries"], [first["entry"]])
        self.assertFalse(any(e["version"] == 2 for e in snap["presentation"]["entries"]))
        self.r.dispatch("presentation.set", self.request(second, archived=False, title="New candidate title"))
        self.assertEqual({(e["version"], e["revision"]) for e in self.r.snapshot()["presentation"]["entries"]},
                         {(1, 1), (2, 1)})
        self.assertEqual(self.r._artifact("DIRECTOR", 1), self.first)

    def test_invalid_target_identity_hash_and_version_leave_no_write(self):
        cases = ({"expected_project_id": "OTHER"}, {"artifact_id": "MISSING"}, {"version": 99},
                 {"version": True}, {"version": 0}, {"expected_sha256": "0" * 64},
                 {"expected_sha256": "not-a-hash"})
        for change in cases:
            with self.subTest(change=change):
                before = self.write_state()
                with self.assertRaises(ValueError):
                    self.r.dispatch("presentation.set", self.request(**change))
                self.assertEqual(self.write_state(), before)
        valid = self.request()
        self.r.dispatch("presentation.set", valid)
        with self.assertRaises(ConflictError):
            self.r.dispatch("presentation.set", dict(valid, expected_project_id="OTHER"))

    def test_required_and_typed_fields_cannot_infer_classification_or_approval(self):
        for key in self.request():
            with self.subTest(missing=key):
                payload = self.request()
                del payload[key]
                before = self.write_state()
                with self.assertRaises(ValueError):
                    self.r.dispatch("presentation.set", payload)
                self.assertEqual(self.write_state(), before)
        for change in ({"archived": 1}, {"base_revision": True}, {"base_revision": -1},
                       {"display_category": "assets"}, {"display_category": "other"},
                       {"display_category": "music"}, {"title": ""}, {"title": "a\nb"},
                       {"title": "a" * 501}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.r.dispatch("presentation.set", self.request(**change))
        record = self.save("RECORD", "project_record", {"state": "test"})
        with self.assertRaises(ValueError):
            self.r.dispatch("presentation.set", self.request(record))
        self.assertFalse(self.r.snapshot()["presentation"]["entries"])
        self.assertFalse(self.r.snapshot()["decisions"])

    def test_asset_and_research_special_pages_cannot_be_moved_or_targeted(self):
        for category in ("asset", "research"):
            with self.subTest(destination=category):
                before = self.write_state()
                protected = self.protected_rows()
                with self.assertRaises(ValueError):
                    self.r.dispatch("presentation.set", self.request(display_category=category))
                self.assertEqual(self.write_state(), before)
                self.assertEqual(self.protected_rows(), protected)
        for kind in ("asset", "prompt", "research", "analysis", "style_constraints"):
            with self.subTest(source_kind=kind):
                artifact = self.save("SPECIAL-" + kind, kind, "Synthetic special page source")
                before = self.write_state()
                protected = self.protected_rows()
                with self.assertRaises(ValueError):
                    self.r.dispatch("presentation.set", self.request(artifact, display_category="director"))
                self.assertEqual(self.write_state(), before)
                self.assertEqual(self.protected_rows(), protected)
        view = self.r.snapshot()["presentation"]
        self.assertFalse(view["entries"])
        self.assertNotIn("asset", view["supported_categories"])
        self.assertNotIn("research", view["supported_categories"])
        self.assertIn("director", view["supported_categories"])
        self.assertIn("video_prompt", view["supported_categories"])

    def test_readonly_old_schema2_view_and_reopen_preserve_settings(self):
        before = self.r.db.total_changes
        self.assertEqual(self.r.snapshot()["presentation"]["entries"], [])
        self.assertEqual(self.r.db.total_changes, before)
        saved = self.r.dispatch("presentation.set", self.request())
        ro = Registry.open_readonly(self.root)
        try:
            self.assertEqual(ro.snapshot()["presentation"]["entries"], [saved["entry"]])
            with self.assertRaises(ValueError):
                ro.dispatch("presentation.set", self.request(base_revision=1))
            self.assertEqual(ro.db.total_changes, 0)
        finally:
            ro.close()
        self.assertEqual(json.loads(self.r.db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]), 2)

    def test_two_connections_one_revision_winner(self):
        def update(index):
            other = Registry(self.root)
            try:
                other.dispatch("presentation.set", self.request(title=f"Writer {index}"))
                return True
            except ConflictError:
                return False
            finally:
                other.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(update, [1, 2])), 1)
        self.assertEqual(self.r.snapshot()["presentation"]["entries"][0]["revision"], 1)


if __name__ == "__main__":
    unittest.main()

"""Board-only organization using explicit test_only projects and synthetic files."""
import json
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from filmprod.board_management190 import ORDER_GROUPS
from filmprod.core import ConflictError, Registry


class BoardManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="film-board190-test_only-")
        self.base = Path(self.temp.name)
        self.root = self.base / "test_only-project"
        self.r = Registry(self.root)
        self.call("project.init", project_id="TEST-190", title="Synthetic board", test_only=True)
        self.script = self.call("artifact.save", artifact_id="SCRIPT", kind="script", scope="synthetic/script",
                                content="Synthetic exact text\r\n第二行", base_version=0, deps=[],
                                metadata={"title": "Synthetic script v1"})["artifact"]
        self.original = self.base / "synthetic-media.bin"
        self.original.write_bytes(b"synthetic local media bytes\x00\r\n")
        self.media = self.call("media.register", media_id="IMAGE", kind="image", path=str(self.original),
                               metadata={"title": "Synthetic image", "asset_type": "prop", "rights_status": "synthetic-only"})

    def tearDown(self):
        self.r.close()
        self.temp.cleanup()

    def call(self, action, **payload):
        payload.setdefault("op_id", uuid.uuid4().hex)
        if action != "project.init":
            payload.setdefault("expected_project_id", "TEST-190")
        return self.r.dispatch(action, payload)

    def order_request(self, group="content_categories", **overrides):
        default_order = ORDER_GROUPS.get(group, ORDER_GROUPS["content_categories"]) if isinstance(group, str) else ORDER_GROUPS["content_categories"]
        payload = {"op_id": uuid.uuid4().hex, "expected_project_id": "TEST-190", "group": group,
                   "order": list(reversed(default_order)), "base_revision": 0}
        payload.update(overrides)
        return payload

    def trash_request(self, target=None, **overrides):
        item = target or self.script
        is_artifact = "artifact_id" in item
        payload = {"op_id": uuid.uuid4().hex, "expected_project_id": "TEST-190",
                   "target_type": "artifact" if is_artifact else "media",
                   "target_id": item["artifact_id"] if is_artifact else item["media_id"],
                   "expected_sha256": item["sha256"], "base_revision": 0, "deleted": True}
        if is_artifact:
            payload["version"] = item["version"]
        payload.update(overrides)
        return payload

    def rows(self, *tables):
        return {name: [tuple(row) for row in self.r.db.execute(f"SELECT * FROM {name} ORDER BY rowid")]
                for name in tables}

    def state(self):
        return self.rows("settings", "artifacts", "media", "events", "operations")

    def reject(self, action, payload, error=ValueError):
        before = self.state()
        with self.assertRaises(error):
            self.r.dispatch(action, payload)
        self.assertEqual(self.state(), before)

    def test_default_views_are_complete_and_readonly(self):
        before = self.state()
        for registry in (self.r, Registry.open_readonly(self.root)):
            try:
                snapshot = registry.snapshot()
                self.assertTrue(snapshot["capabilities"]["board_ordering"])
                self.assertTrue(snapshot["capabilities"]["trash_management"])
                self.assertEqual(snapshot["board_order"]["groups"], {
                    key: {"order": list(order), "revision": 0} for key, order in ORDER_GROUPS.items()})
                self.assertEqual(snapshot["trash"]["entries"], [])
                self.assertFalse(snapshot["trash"]["disk_space_reclaimed"])
            finally:
                if registry is not self.r:
                    registry.close()
        self.assertEqual(self.state(), before)

    def test_all_order_groups_persist_independently_after_reopen(self):
        expected = {}
        for group in ORDER_GROUPS:
            result = self.r.dispatch("board.order.set", self.order_request(group))
            expected[group] = result["entry"]
            self.assertTrue(result["management_only"] and result["readback_verified"])
            self.assertEqual(result["entry"]["revision"], 1)
            self.assertEqual(result["management_change"]["before"]["order"], list(ORDER_GROUPS[group]))
        self.r.close()
        self.r = Registry(self.root)
        self.assertEqual(self.r.snapshot()["board_order"]["groups"], expected)
        second = self.r.dispatch("board.order.set", self.order_request("asset_types", base_revision=1,
                                                                     order=list(ORDER_GROUPS["asset_types"])))
        after = self.r.snapshot()["board_order"]["groups"]
        self.assertEqual(after["asset_types"]["revision"], 2)
        self.assertEqual(after["content_categories"], expected["content_categories"])
        event = self.r.db.execute("SELECT data FROM events WHERE action='board.order.set' ORDER BY event_id DESC LIMIT 1").fetchone()
        self.assertEqual(json.loads(event[0])["result"], second)

    def test_order_rejects_bad_groups_permutations_fields_and_revisions(self):
        variations = [{"group": "unknown"}, {"group": []}, {"order": []}, {"order": "asset"},
                      {"order": [True]}, {"order": [{"id": "asset"}]},
                      {"order": list(ORDER_GROUPS["content_categories"]) + ["all"]},
                      {"order": ["idea"] * len(ORDER_GROUPS["content_categories"])},
                      {"base_revision": True}, {"base_revision": -1}, {"base_revision": 0.0},
                      {"base_revision": "0"}, {"path": str(self.original)}, {"expected_project_id": "OTHER"}]
        for variation in variations:
            with self.subTest(variation=variation):
                self.reject("board.order.set", self.order_request(**variation))
        for missing in ("expected_project_id", "group", "order", "base_revision"):
            payload = self.order_request()
            del payload[missing]
            self.reject("board.order.set", payload)

    def test_order_idempotency_does_not_revert_later_order(self):
        request = self.order_request()
        result = self.r.dispatch("board.order.set", request)
        newer = self.r.dispatch("board.order.set", self.order_request(base_revision=1, order=list(ORDER_GROUPS["content_categories"])))
        before = self.state()
        self.assertEqual(self.r.dispatch("board.order.set", request), result)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.r.snapshot()["board_order"]["groups"]["content_categories"], newer["entry"])
        self.reject("board.order.set", {**request, "order": list(ORDER_GROUPS["content_categories"])}, ConflictError)
        self.reject("board.order.set", self.order_request(), ConflictError)

    def test_two_connections_cannot_overwrite_order(self):
        other = Registry(self.root)
        try:
            requests = [self.order_request(), self.order_request(order=list(ORDER_GROUPS["content_categories"]))]
            def write(registry, payload):
                try:
                    return registry.dispatch("board.order.set", payload)
                except ConflictError as error:
                    return error
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda pair: write(*pair), [(self.r, requests[0]), (other, requests[1])]))
            self.assertEqual(sum(isinstance(x, ConflictError) for x in results), 1)
            self.assertEqual(self.r.snapshot()["board_order"]["groups"]["content_categories"]["revision"], 1)
        finally:
            other.close()

    def test_delete_restore_retains_original_bytes_approvals_tasks_and_content(self):
        self.call("content.approve", artifact_id="SCRIPT", version=1, scope="synthetic/script",
                  evidence="synthetic decision", actor="test", synthetic=True)
        self.call("task.create", task_id="TASK", title="Synthetic dependent task", module="director-agent",
                  scope="synthetic/director", inputs=[{"artifact_id": "SCRIPT", "version": 1}],
                  must_keep=[], allowed_changes=[], requirements=[])
        self.call("artifact.save", artifact_id="DOWNSTREAM", kind="director", scope="synthetic/downstream",
                  content="Synthetic dependent exact text", base_version=0,
                  deps=[{"artifact_id": "SCRIPT", "version": 1}], metadata={})
        tables = ("artifacts", "media", "tasks", "threads", "decisions", "sync", "approved_segments",
                  "master_revisions", "master_bindings", "master_sync")
        protected = self.rows(*tables)
        registered = self.root / self.media["path"]
        original_bytes = self.original.read_bytes()
        for target in (self.script, self.media):
            request = self.trash_request(target)
            result = self.r.dispatch("trash.set", request)
            self.assertTrue(result["entry"]["deleted"])
            self.assertTrue(result["management_only"] and result["original_records_retained"])
            self.assertFalse(result["disk_space_reclaimed"])
            self.assertNotIn("hash_verified", result)
            self.assertEqual(result["entry"]["revision"], 1)
            self.assertIsNotNone(result["entry"]["deleted_at"])
            self.assertEqual(self.rows(*tables), protected)
            restored = self.r.dispatch("trash.set", self.trash_request(target, deleted=False, base_revision=1))
            self.assertFalse(restored["entry"]["deleted"])
            self.assertIsNone(restored["entry"]["deleted_at"])
            self.assertEqual(restored["entry"]["revision"], 2)
            self.assertEqual(self.rows(*tables), protected)
        self.assertEqual(self.original.read_bytes(), original_bytes)
        self.assertEqual(registered.read_bytes(), original_bytes)
        self.assertTrue(all(not item["deleted"] for item in self.r.snapshot()["trash"]["entries"]))

    def test_trash_is_exact_version_and_old_version_is_restorable_after_reopen(self):
        second = self.call("artifact.save", artifact_id="SCRIPT", kind="script", scope="synthetic/script",
                           content="Synthetic v2", base_version=1, deps=[], metadata={"title": "Second title"})["artifact"]
        entry = self.r.dispatch("trash.set", self.trash_request())["entry"]
        self.assertEqual(entry["version"], 1)
        self.assertEqual(entry["title"], "Synthetic script v1")
        self.r.close()
        self.r = Registry(self.root)
        snapshot = self.r.snapshot()
        self.assertEqual(snapshot["trash"]["entries"], [entry])
        self.assertEqual(snapshot["artifacts"][0]["version"], 2)
        self.assertEqual(self.r.dispatch("artifact.get", {"artifact_id": "SCRIPT", "version": 1})["content"], self.script["content"])
        result = self.r.dispatch("trash.set", self.trash_request(deleted=False, base_revision=1))
        self.assertEqual(result["entry"]["version"], 1)
        self.assertEqual(self.r._artifact("SCRIPT", 2), second)

    def test_trash_missing_original_is_still_management_only_without_file_reads(self):
        registered = self.root / self.media["path"]
        registered.unlink()
        with patch.object(Path, "open", side_effect=AssertionError("management must not read or write files")):
            deleted = self.r.dispatch("trash.set", self.trash_request(self.media))
            restored = self.r.dispatch("trash.set", self.trash_request(self.media, deleted=False, base_revision=1))
        self.assertTrue(deleted["entry"]["deleted"])
        self.assertFalse(restored["entry"]["deleted"])
        self.assertFalse(registered.exists())
        self.assertTrue(self.original.exists())

    def test_trash_rejects_bad_identity_hash_fields_bool_revision_and_type(self):
        variants = [{"target_type": "file"}, {"target_type": []}, {"target_id": "missing"},
                    {"expected_sha256": "0" * 64}, {"expected_sha256": "invalid"},
                    {"expected_sha256": self.script["sha256"].upper()}, {"version": 2}, {"version": True},
                    {"version": 0}, {"version": "1"}, {"base_revision": True}, {"base_revision": -1},
                    {"base_revision": 0.0}, {"base_revision": "0"}, {"deleted": "true"}, {"deleted": 1},
                    {"path": str(self.original)}, {"expected_project_id": "OTHER"}]
        for variation in variants:
            with self.subTest(variation=variation):
                self.reject("trash.set", self.trash_request(**variation))
        for missing in ("expected_project_id", "target_type", "target_id", "version", "expected_sha256", "base_revision", "deleted"):
            payload = self.trash_request()
            del payload[missing]
            self.reject("trash.set", payload)
        self.reject("trash.set", self.trash_request(self.media, version=1))
        self.reject("trash.set", self.trash_request(self.media, target_id="missing"))

    def test_trash_idempotent_receipts_never_reapply_old_deletion(self):
        request = self.trash_request()
        deleted = self.r.dispatch("trash.set", request)
        restored = self.r.dispatch("trash.set", self.trash_request(deleted=False, base_revision=1))
        before = self.state()
        self.assertEqual(self.r.dispatch("trash.set", request), deleted)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.r.snapshot()["trash"]["entries"], [restored["entry"]])
        self.reject("trash.set", {**request, "deleted": False}, ConflictError)
        self.reject("trash.set", self.trash_request(base_revision=1), ConflictError)
        self.reject("trash.set", {**request, "expected_project_id": "OTHER"}, ConflictError)

    def test_trash_two_connections_have_one_winner(self):
        other = Registry(self.root)
        try:
            first = self.r.dispatch("trash.set", self.trash_request())
            with self.assertRaises(ConflictError):
                other.dispatch("trash.set", self.trash_request())
            self.assertEqual(other.snapshot()["trash"]["entries"], [first["entry"]])
        finally:
            other.close()

    def test_title_is_snapshot_of_display_name_and_restore_uses_current_label(self):
        self.call("presentation.set", artifact_id="SCRIPT", version=1, expected_sha256=self.script["sha256"],
                  base_revision=0, display_category="script", title="Display at deletion", archived=False)
        deleted = self.r.dispatch("trash.set", self.trash_request())["entry"]
        self.assertEqual(deleted["title"], "Display at deletion")
        self.assertTrue(deleted["title_snapshot"])
        self.call("presentation.set", artifact_id="SCRIPT", version=1, expected_sha256=self.script["sha256"],
                  base_revision=1, display_category="script", title="Later live display", archived=True)
        self.assertEqual(self.r.snapshot()["trash"]["entries"][0]["title"], "Display at deletion")
        restored = self.r.dispatch("trash.set", self.trash_request(deleted=False, base_revision=1))["entry"]
        self.assertEqual(restored["title"], "Later live display")

    def test_management_groups_targets_and_projects_are_independent(self):
        self.r.dispatch("board.order.set", self.order_request())
        self.r.dispatch("trash.set", self.trash_request())
        image = self.r.dispatch("trash.set", self.trash_request(self.media))["entry"]
        self.assertNotIn("version", image)
        other = Registry(self.base / "test_only-other-project")
        try:
            other.dispatch("project.init", {"op_id": "other-init", "project_id": "OTHER", "title": "Synthetic other", "test_only": True})
            snap = other.snapshot()
            self.assertEqual(snap["trash"]["entries"], [])
            self.assertEqual(snap["board_order"]["groups"]["content_categories"]["revision"], 0)
            with self.assertRaises(ConflictError):
                other.dispatch("board.order.set", self.order_request())
        finally:
            other.close()

    def test_readonly_registry_can_inspect_management_but_cannot_change_it(self):
        self.r.dispatch("board.order.set", self.order_request())
        self.r.dispatch("trash.set", self.trash_request())
        before = self.state()
        readonly = Registry.open_readonly(self.root)
        try:
            self.assertEqual(readonly.snapshot()["trash"], self.r.snapshot()["trash"])
            with self.assertRaisesRegex(ValueError, "只读"):
                readonly.dispatch("board.order.set", self.order_request(base_revision=1))
            with self.assertRaisesRegex(ValueError, "只读"):
                readonly.dispatch("trash.set", self.trash_request(deleted=False, base_revision=1))
        finally:
            readonly.close()
        self.assertEqual(self.state(), before)

    def test_order_and_trash_readback_failures_rollback_settings_event_and_operation(self):
        for action, request in (("board.order.set", self.order_request()), ("trash.set", self.trash_request(self.media))):
            with self.subTest(action=action):
                before = self.state()
                with patch("filmprod.board_management190._read_setting", side_effect=[None, {"wrong": "readback"}]):
                    with self.assertRaisesRegex(ConflictError, "读回"):
                        self.r.dispatch(action, request)
                self.assertEqual(self.state(), before)

    def test_audit_keeps_exact_delete_and_restore_receipts(self):
        deleted = self.r.dispatch("trash.set", self.trash_request(self.media))
        restored = self.r.dispatch("trash.set", self.trash_request(self.media, deleted=False, base_revision=1))
        rows = self.r.db.execute("SELECT data FROM events WHERE action='trash.set' ORDER BY event_id").fetchall()
        self.assertEqual([json.loads(row[0])["result"] for row in rows], [deleted, restored])
        self.assertFalse(deleted["management_change"]["before"]["deleted"])
        self.assertTrue(restored["management_change"]["before"]["deleted"])


if __name__ == "__main__":
    unittest.main()

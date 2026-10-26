"""Actual stdio integration for project-local ordering and reversible trash.

Every fixture is an explicit test_only temporary project. Nothing opens a user
project, removes a registered original, or relies on a live client session.
"""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

from filmprod.core import Registry
from test_image_preview180 import png


CONTENT_ORDER = ["idea", "requirements", "outline", "novel", "character_bio",
                 "style", "source_script", "script", "director", "vfx", "asset", "video_prompt"]
PROTECTED_TABLES = ("artifacts", "media", "tasks", "threads", "decisions", "sync",
                    "approved_segments", "master_revisions", "master_bindings", "master_sync")


class BoardManagementStdioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="film-board190-stdio-test_only-")
        self.base = Path(self.temp.name)
        self.root = self.base / "test_only-project"
        self.project_id = "TEST-BOARD-STDIO-190"
        registry = Registry(self.root)
        def write(action, **payload):
            return registry.dispatch(action, {"op_id": uuid.uuid4().hex, **payload})
        write("project.init", project_id=self.project_id, title="Synthetic board only", test_only=True)
        self.v1 = write("artifact.save", artifact_id="SCRIPT", kind="script", scope="synthetic/scene1",
                        content="First synthetic script\r\n原文", base_version=0, deps=[],
                        metadata={"title": "合成正式稿", "workflow_stage": "dynamic_script"})
        write("content.approve", artifact_id="SCRIPT", version=1, scope="synthetic/scene1",
              evidence="synthetic test decision", actor="test", synthetic=True)
        write("task.create", task_id="TASK", title="Synthetic dependent task", module="director-agent",
              scope="synthetic/task", inputs=[{"artifact_id": "SCRIPT", "version": 1}],
              must_keep=[], allowed_changes=[], requirements=[])
        self.v2 = write("artifact.save", artifact_id="SCRIPT", kind="script", scope="synthetic/scene1",
                        content="Second synthetic candidate", base_version=1, deps=[],
                        metadata={"title": "合成候选稿", "workflow_stage": "dynamic_script"})
        self.v1 = registry._artifact("SCRIPT", 1)
        self.v2 = registry._artifact("SCRIPT", 2)
        source = self.base / "original.png"
        self.original_bytes = png(source, 32, 18)
        self.media = write("media.register", media_id="IMAGE", kind="image", path=str(source),
                           metadata={"title": "Synthetic image", "asset_type": "scene", "rights": "synthetic-only"})
        self.protected_before = self.protected(registry)
        self.initial_snapshot = registry.snapshot()
        registry.close()

    def tearDown(self):
        self.temp.cleanup()

    def protected(self, registry):
        return {name: [tuple(row) for row in registry.db.execute(f"SELECT * FROM {name} ORDER BY rowid")]
                for name in PROTECTED_TABLES}

    def invoke(self, calls, root=None):
        messages = [{"jsonrpc": "2.0", "id": i + 1, "method": "tools/call",
                     "params": {"name": name, "arguments": {"root": str(root or self.root), **arguments}}}
                    for i, (name, arguments) in enumerate(calls)]
        env = {**os.environ, "FILMPROD_CATALOG_PATH": str(self.base / "isolated-catalog.sqlite3"),
               "PYTHONDONTWRITEBYTECODE": "1"}
        process = subprocess.run([sys.executable, "-B", "-X", "utf8",
                                  str(Path(__file__).resolve().parents[1] / "plugin/mcp_server.py")],
                                 input="".join(json.dumps(message, ensure_ascii=False) + "\n" for message in messages),
                                 capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
        self.assertEqual(process.returncode, 0, process.stderr)
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual([row["id"] for row in responses], list(range(1, len(calls) + 1)))
        for row in responses:
            self.assertNotIn("error", row)
        return [row["result"] for row in responses]

    def dispatch(self, action, payload):
        return "film_dispatch", {"action": action, "payload": payload}

    def order_payload(self, **changes):
        return {"op_id": uuid.uuid4().hex, "expected_project_id": self.project_id,
                "group": "content_categories", "order": list(reversed(CONTENT_ORDER)),
                "base_revision": 0, **changes}

    def trash_payload(self, target=None, **changes):
        target = target or self.v1
        media = "media_id" in target
        return {"op_id": uuid.uuid4().hex, "expected_project_id": self.project_id,
                "target_type": "media" if media else "artifact",
                "target_id": target["media_id"] if media else target["artifact_id"],
                **({} if media else {"version": target["version"]}),
                "expected_sha256": target["sha256"], "base_revision": 0, "deleted": True, **changes}

    def assert_success(self, result):
        self.assertFalse(result.get("isError"), result)
        return result["structuredContent"]

    def assert_protected(self):
        registry = Registry.open_readonly(self.root)
        try:
            self.assertEqual(self.protected(registry), self.protected_before)
            snapshot = registry.snapshot()
            for key in ("approved_artifacts", "pending_candidates", "current_content", "masters", "workflow", "media", "tasks"):
                self.assertEqual(snapshot[key], self.initial_snapshot[key], key)
        finally:
            registry.close()
        self.assertEqual((self.root / self.media["path"]).read_bytes(), self.original_bytes)
        self.assertEqual(Path(self.media["source_path"]).read_bytes(), self.original_bytes)

    def test_order_persists_between_stdio_processes_and_is_project_scoped(self):
        payload = self.order_payload()
        calls = [self.dispatch("board.order.set", payload), self.dispatch("board.order.set", payload),
                 ("film_snapshot", {})]
        responses = self.invoke(calls)
        first = self.assert_success(responses[0])
        self.assertEqual(first, self.assert_success(responses[1]))
        self.assertEqual(first["entry"]["order"], payload["order"])
        snapshot = self.assert_success(responses[2])
        self.assertEqual(snapshot["board_order"]["groups"]["content_categories"]["revision"], 1)
        self.assertEqual(snapshot["board_order"]["groups"]["asset_types"]["revision"], 0)
        fresh = self.assert_success(self.invoke([("film_snapshot", {})])[0])
        self.assertEqual(fresh["board_order"], snapshot["board_order"])
        self.assertEqual(fresh["events"], snapshot["events"])
        other_root = self.base / "test_only-other-project"
        other = Registry(other_root)
        other.dispatch("project.init", {"op_id": "other-init", "project_id": "OTHER", "title": "Other synthetic", "test_only": True})
        other.close()
        other_snapshot = self.assert_success(self.invoke([("film_snapshot", {})], other_root)[0])
        self.assertEqual(other_snapshot["board_order"]["groups"]["content_categories"]["order"], CONTENT_ORDER)
        self.assertEqual(other_snapshot["board_order"]["groups"]["content_categories"]["revision"], 0)
        self.assert_protected()

    def test_trash_exact_approved_version_and_media_restore_without_content_changes(self):
        old_request = self.trash_payload()
        media_request = self.trash_payload(self.media)
        responses = self.invoke([self.dispatch("trash.set", old_request),
                                 self.dispatch("trash.set", media_request), ("film_snapshot", {})])
        for row in responses[:2]:
            result = self.assert_success(row)
            self.assertTrue(result["management_only"])
            self.assertTrue(result["original_records_retained"])
            self.assertFalse(result["disk_space_reclaimed"])
        snapshot = self.assert_success(responses[2])
        deleted = snapshot["trash"]["entries"]
        self.assertEqual(len(deleted), 2)
        artifact_entry = next(entry for entry in deleted if entry["target_type"] == "artifact")
        self.assertEqual((artifact_entry["target_id"], artifact_entry["version"], artifact_entry["sha256"]),
                         ("SCRIPT", 1, self.v1["sha256"]))
        self.assertTrue(artifact_entry["deleted"])
        self.assertFalse(any(entry.get("version") == 2 for entry in deleted))
        self.assert_protected()
        restore = self.trash_payload(deleted=False, base_revision=1)
        responses = self.invoke([self.dispatch("trash.set", restore), self.dispatch("trash.set", old_request),
                                 ("film_snapshot", {})])
        self.assertFalse(self.assert_success(responses[0])["entry"]["deleted"])
        self.assertEqual(self.assert_success(responses[1]), self.assert_success(self.invoke([self.dispatch("trash.set", old_request)])[0]))
        entry = next(entry for entry in self.assert_success(responses[2])["trash"]["entries"]
                     if entry["target_type"] == "artifact")
        self.assertFalse(entry["deleted"], "Old operation receipt must not re-delete the restored version")
        self.assertEqual(entry["revision"], 2)
        self.assertIsNone(entry["deleted_at"])
        self.assert_protected()

    def test_invalid_management_requests_error_without_writing_or_touching_originals(self):
        order = self.order_payload()
        trash = self.trash_payload()
        invalid_orders = [dict(order, op_id="order-wrong-project", expected_project_id="OTHER"),
                          dict(order, op_id="order-duplicate", order=["idea"] * len(CONTENT_ORDER)),
                          dict(order, op_id="order-extra", path=str(self.base)),
                          dict(order, op_id="order-bool", base_revision=True)]
        invalid_trash = [dict(trash, op_id="trash-sha", expected_sha256="0" * 64),
                         dict(trash, op_id="trash-project", expected_project_id="OTHER"),
                         dict(trash, op_id="trash-version", version=True),
                         dict(trash, op_id="trash-deleted", deleted="true"),
                         dict(trash, op_id="trash-path", path=str(self.base)),
                         self.trash_payload(self.media, op_id="trash-media-version", version=1)]
        responses = self.invoke([self.dispatch("board.order.set", p) for p in invalid_orders] +
                                [self.dispatch("trash.set", p) for p in invalid_trash] + [("film_snapshot", {})])
        for response in responses[:-1]:
            self.assertTrue(response.get("isError"), response)
            self.assertIn(response["structuredContent"]["error"]["type"], {"ValueError", "ConflictError"})
        snapshot = self.assert_success(responses[-1])
        self.assertEqual(snapshot["trash"]["entries"], [])
        self.assertEqual(snapshot["board_order"]["groups"]["content_categories"]["revision"], 0)
        self.assertEqual(snapshot["events"], self.initial_snapshot["events"])
        self.assert_protected()

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires existing local FFmpeg")
    def test_recycled_image_retains_verified_original_and_meta_only_preview(self):
        request = self.trash_payload(self.media)
        responses = self.invoke([self.dispatch("trash.set", request),
                                ("film_media", {"action": "original", "payload": {"media_id": "IMAGE", "expected_project_id": self.project_id}}),
                                ("film_media", {"action": "preview_image", "payload": {"media_id": "IMAGE", "expected_project_id": self.project_id}})])
        self.assert_success(responses[0])
        original = self.assert_success(responses[1])
        self.assertTrue(original["hash_verified"])
        self.assertEqual(original["sha256"], self.media["sha256"])
        preview_result = responses[2]
        preview = self.assert_success(preview_result)
        self.assertNotIn("base64,", json.dumps(preview))
        self.assertNotIn("base64,", json.dumps(preview_result["content"]))
        uri = preview_result["_meta"]["media_preview"]["preview_data_uri"]
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        self.assertTrue(base64.b64decode(uri.split(",", 1)[1]).startswith(b"\x89PNG"))
        self.assert_protected()


if __name__ == "__main__":
    unittest.main(verbosity=2)

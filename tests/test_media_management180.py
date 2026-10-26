"""Synthetic local media management; no real work projects or rendered media."""
import copy
import json
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from filmprod.core import ConflictError, Registry


class MediaManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="film-media180-TEST-")
        self.base = Path(self.temp.name)
        self.root = self.base / "TEST-PROJECT"
        self.r = Registry(self.root)
        self.call("project.init", project_id="TEST-180", title="synthetic media management", test_only=True)
        self.image = self.register("IMG", "image", asset_type="character")
        self.video = self.register("VIDEO", "video", video_category="take")

    def tearDown(self):
        self.r.close()
        self.temp.cleanup()

    def call(self, action, **payload):
        payload.setdefault("op_id", uuid.uuid4().hex)
        if action != "project.init":
            payload.setdefault("expected_project_id", "TEST-180")
        return self.r.dispatch(action, payload)

    def register(self, media_id, kind, **labels):
        source = self.base / ("synthetic-" + media_id + ".bin")
        source.write_bytes(b"synthetic-test-media-original\x00\r\n" + media_id.encode("ascii"))
        return self.call("media.register", media_id=media_id, kind=kind, path=str(source),
                         metadata={"title": "Original synthetic title", "rights_status": "synthetic-only",
                                   "stems": {"dialogue": "unknown"}, "technical_check": {"status": "unverified"},
                                   "unknown_custom": [True, None, {"value": "kept"}], **labels})

    def request(self, media=None, **overrides):
        item = media or self.image
        category = {"asset_type": "prop"} if item["kind"] == "image" else {"video_category": "clip"}
        payload = {"op_id": uuid.uuid4().hex, "expected_project_id": "TEST-180",
                   "media_id": item["media_id"], "expected_sha256": item["sha256"],
                   "base_revision": item.get("classification_revision", 0),
                   "title": "  Synthetic revised title 名称  ", **category}
        payload.update(overrides)
        return payload

    def rows(self, *tables):
        return {name: [tuple(row) for row in self.r.db.execute(f"SELECT * FROM {name} ORDER BY rowid")]
                for name in tables}

    def write_state(self):
        return self.rows("settings", "media", "events", "operations")

    def assert_rejected_without_write(self, request, error=ValueError, action="media.update"):
        before = self.write_state()
        with self.assertRaises(error):
            self.r.dispatch(action, request)
        self.assertEqual(self.write_state(), before)

    def test_rename_and_classification_preserve_originals_and_creative_records(self):
        self.call("artifact.save", artifact_id="SCRIPT", kind="script", scope="synthetic/script",
                  content="Synthetic script\r\n原文。", base_version=0, deps=[], metadata={})
        self.call("content.approve", artifact_id="SCRIPT", version=1, scope="synthetic/script",
                  evidence="synthetic test decision", actor="test", synthetic=True)
        self.call("task.create", task_id="TASK", title="Synthetic task", module="director-agent",
                  scope="synthetic/task", inputs=[{"artifact_id": "SCRIPT", "version": 1}],
                  must_keep=[], allowed_changes=[], requirements=[])
        protected_tables = ("settings", "artifacts", "tasks", "threads", "decisions", "sync",
                            "approved_segments", "master_revisions", "master_bindings", "master_sync")
        protected = self.rows(*protected_tables)
        original_files = {item["media_id"]: ((self.root / item["path"]).read_bytes(),
                                            Path(item["source_path"]).read_bytes())
                          for item in (self.image, self.video)}
        for item, field, value in ((self.image, "asset_type", "scene"), (self.video, "video_category", "final")):
            with self.subTest(kind=item["kind"]):
                request = self.request(item, **{field: value})
                result = self.r.dispatch("media.update", request)
                updated = result["media"]
                self.assertTrue(result["management_only"] and result["readback_verified"])
                self.assertEqual(updated["metadata"]["title"], "Synthetic revised title 名称")
                self.assertEqual(updated["metadata"][field], value)
                self.assertEqual(updated["classification_revision"], 1)
                self.assertEqual({k: v for k, v in updated.items()
                                  if k not in ("metadata", "classification_revision", "classified_at", "management_updated_at")},
                                 {k: v for k, v in item.items() if k not in ("metadata", "classification_revision")})
                self.assertEqual({k: v for k, v in updated["metadata"].items() if k not in ("title", field)},
                                 {k: v for k, v in item["metadata"].items() if k not in ("title", field)})
                self.assertEqual(((self.root / item["path"]).read_bytes(), Path(item["source_path"]).read_bytes()),
                                 original_files[item["media_id"]])
                self.assertEqual(self.rows(*protected_tables), protected)
        self.assertTrue(self.r.snapshot()["capabilities"]["media_management"])

    def test_audit_contains_before_after_and_keeps_legacy_absence(self):
        legacy = copy.deepcopy(self.image)
        del legacy["metadata"]["title"]
        del legacy["metadata"]["asset_type"]
        del legacy["classification_revision"]
        self.r._put("media", "media_id", "IMG", legacy)
        result = self.r.dispatch("media.update", self.request(legacy))
        change = result["management_change"]
        self.assertEqual(change["before"], {"metadata": {}, "classification_revision": 0})
        self.assertEqual(change["after"]["metadata"], {"title": "Synthetic revised title 名称", "asset_type": "prop"})
        self.assertEqual(change["after"]["classification_revision"], 1)
        event = self.r.db.execute("SELECT data FROM events WHERE action='media.update'").fetchone()
        self.assertEqual(json.loads(event[0])["result"]["management_change"], change)

    def test_classify_and_update_share_revision_in_both_directions(self):
        pending_update = self.request()
        classified = self.call("media.classify", media_id="IMG", expected_sha256=self.image["sha256"],
                               asset_type="scene", base_revision=0)
        self.assertEqual(classified["media"]["classification_revision"], 1)
        self.assert_rejected_without_write(pending_update, ConflictError)
        renamed = self.r.dispatch("media.update", self.request(classified["media"], asset_type="scene"))
        self.assertEqual(renamed["media"]["classification_revision"], 2)
        stale_classify = {"op_id": uuid.uuid4().hex, "expected_project_id": "TEST-180", "media_id": "IMG",
                          "expected_sha256": self.image["sha256"], "asset_type": "prop", "base_revision": 1}
        self.assert_rejected_without_write(stale_classify, ConflictError, "media.classify")
        newest = self.call("media.classify", media_id="IMG", expected_sha256=self.image["sha256"],
                           asset_type="other", base_revision=2)
        self.assertEqual(newest["media"]["metadata"]["title"], renamed["media"]["metadata"]["title"])
        self.assertEqual(newest["media"]["classification_revision"], 3)

    def test_idempotent_receipt_does_not_revert_later_edit(self):
        request = self.request()
        first = self.r.dispatch("media.update", request)
        state = self.write_state()
        self.assertEqual(self.r.dispatch("media.update", request), first)
        self.assertEqual(self.write_state(), state)
        self.assert_rejected_without_write(dict(request, title="Different request"), ConflictError)
        second = self.r.dispatch("media.update", self.request(first["media"], title="Second title", asset_type="other"))
        state = self.write_state()
        self.assertEqual(self.r.dispatch("media.update", request), first)
        self.assertEqual(self.write_state(), state)
        self.assertEqual(self.r._get("media", "media_id", "IMG"), second["media"])
        self.assert_rejected_without_write(dict(request, expected_project_id="OTHER"), ConflictError)

    def test_required_fields_and_invalid_types_leave_no_write(self):
        for key in self.request():
            with self.subTest(missing=key):
                request = self.request()
                del request[key]
                self.assert_rejected_without_write(request)
        invalid = ({"base_revision": True}, {"base_revision": False}, {"base_revision": -1},
                   {"base_revision": 0.0}, {"base_revision": "0"}, {"base_revision": None},
                   {"title": ""}, {"title": "  "}, {"title": None}, {"title": 7},
                   {"title": "a\nb"}, {"title": "a\tb"}, {"title": "a" * 501},
                   {"asset_type": "take"}, {"asset_type": []}, {"asset_type": True},
                   {"media_id": True}, {"media_id": "MISSING"}, {"expected_sha256": "bad"},
                   {"expected_sha256": "A" * 64}, {"expected_sha256": 1})
        for change in invalid:
            with self.subTest(change=change):
                self.assert_rejected_without_write(self.request(**change))

    def test_image_and_video_classifications_are_explicit_and_separate(self):
        image, video = self.image, self.video
        for category in ("character", "scene", "prop", "other", "unclassified"):
            image = self.r.dispatch("media.update", self.request(image, asset_type=category))["media"]
            self.assertEqual(image["metadata"]["asset_type"], category)
        for category in ("take", "clip", "final", "unclassified"):
            video = self.r.dispatch("media.update", self.request(video, video_category=category))["media"]
            self.assertEqual(video["metadata"]["video_category"], category)
        for request in (self.request(image, video_category="take"), self.request(video, asset_type="prop"),
                        self.request(video, video_category="scene"), self.request(video, video_category=[]),
                        self.request(video, video_category=True)):
            self.assert_rejected_without_write(request)
        request = self.request(video)
        del request["video_category"]
        self.assert_rejected_without_write(request)

    def test_non_image_video_media_cannot_be_edited(self):
        for kind in ("audio", "project", "other"):
            with self.subTest(kind=kind):
                media = self.register("SYNTHETIC-" + kind, kind)
                self.assert_rejected_without_write(self.request(media))

    def test_payload_cannot_change_original_or_approval_fields(self):
        for key, value in (("kind", "video"), ("path", "replacement.bin"), ("source_path", "elsewhere.bin"),
                           ("sha256", "0" * 64), ("size_bytes", 0), ("metadata", {"title": "override"}),
                           ("rights_status", "approved"), ("stems", {}), ("technical_check", {}),
                           ("status", "approved"), ("adoption", True), ("approved", True),
                           ("artifacts", []), ("execution_lock", {}), ("classification_revision", 99)):
            with self.subTest(field=key):
                self.assert_rejected_without_write(self.request(**{key: value}))

    def test_project_hash_and_revision_conflicts_leave_no_write(self):
        for change in ({"expected_project_id": "OTHER"}, {"expected_sha256": "0" * 64}, {"base_revision": 1}):
            with self.subTest(change=change):
                self.assert_rejected_without_write(self.request(**change), ConflictError)

    def test_original_bytes_missing_and_unsafe_paths_reject(self):
        original = self.root / self.image["path"]
        data = original.read_bytes()
        original.write_bytes(b"synthetic tampered original")
        self.assert_rejected_without_write(self.request(), ConflictError)
        original.unlink()
        self.assert_rejected_without_write(self.request(), ConflictError)
        original.write_bytes(data)
        for relative in ("../synthetic-IMG.bin", str(Path(self.image["source_path"]).resolve()),
                         str(original.resolve()), "missing-original.bin", ""):
            with self.subTest(path=relative):
                altered = dict(self.image, path=relative)
                self.r._put("media", "media_id", "IMG", altered)
                self.assert_rejected_without_write(self.request(), ConflictError)
        self.r._put("media", "media_id", "IMG", self.image)

    def test_corrupt_record_identity_or_revision_cannot_be_overwritten(self):
        for change in ({"media_id": "ANOTHER"}, {"classification_revision": True},
                       {"classification_revision": -1}, {"classification_revision": "0"}):
            with self.subTest(change=change):
                self.r._put("media", "media_id", "IMG", dict(self.image, **change))
                self.assert_rejected_without_write(self.request(), ConflictError)
        self.r._put("media", "media_id", "IMG", self.image)

    def test_failed_readback_rolls_back_media_event_and_operation(self):
        before = self.write_state()
        original_get = self.r._get
        reads = 0

        def altered_readback(table, key, value):
            nonlocal reads
            item = original_get(table, key, value)
            if table == "media":
                reads += 1
                if reads == 2:
                    item["metadata"]["title"] = "synthetic corrupt readback"
            return item

        with patch.object(self.r, "_get", side_effect=altered_readback):
            with self.assertRaises(ConflictError):
                self.r.dispatch("media.update", self.request())
        self.assertEqual(self.write_state(), before)

    def test_two_connections_only_one_shared_revision_can_win(self):
        def update(index):
            registry = Registry(self.root)
            try:
                if index == 0:
                    registry.dispatch("media.update", self.request(title="Synthetic concurrent rename"))
                else:
                    registry.dispatch("media.classify", {"op_id": uuid.uuid4().hex,
                                      "expected_project_id": "TEST-180", "media_id": "IMG",
                                      "expected_sha256": self.image["sha256"], "asset_type": "scene", "base_revision": 0})
                return True
            except ConflictError:
                return False
            finally:
                registry.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(update, [0, 1])), 1)
        self.assertEqual(self.r._get("media", "media_id", "IMG")["classification_revision"], 1)

    def test_readonly_connection_rejects_write_and_reads_saved_management(self):
        saved = self.r.dispatch("media.update", self.request())["media"]
        readonly = Registry.open_readonly(self.root)
        try:
            self.assertEqual(readonly._get("media", "media_id", "IMG"), saved)
            with self.assertRaises(ValueError):
                readonly.dispatch("media.update", self.request(saved))
            self.assertEqual(readonly.db.total_changes, 0)
        finally:
            readonly.close()


if __name__ == "__main__":
    unittest.main()

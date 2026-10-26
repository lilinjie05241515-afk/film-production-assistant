"""Synthetic asset-management and exact Markdown export regressions."""
import base64
import copy
import hashlib
import importlib.util
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from filmprod.core import Registry, ConflictError, canonical


class AssetDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="film-assets-documents172-TEST-")
        self.base = Path(self.temp.name)
        self.root = self.base / "TEST-PROJECT"
        self.r = Registry(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.r.close)
        self.counter = 0
        self.call("project.init", project_id="TEST-172", title="synthetic assets and text", test_only=True)

    def tearDown(self):
        self.r.close()
        self.temp.cleanup()

    def call(self, action, **payload):
        self.counter += 1
        payload.setdefault("op_id", f"test-{self.counter}")
        if action != "project.init":
            payload.setdefault("expected_project_id", "TEST-172")
        return self.r.dispatch(action, payload)

    def save(self, aid, version=0, **values):
        return self.call("artifact.save", artifact_id=aid, kind=values.pop("kind", "asset"),
                         scope=values.pop("scope", aid), base_version=version,
                         content=values.pop("content", "# TEST synthetic\r\n\r\n正文。\n"), deps=[], **values)["artifact"]

    def media(self, mid="IMG", metadata=None):
        source = self.base / f"{mid}.png"
        # Synthetic binary fixture only; not an image-generation result.
        source.write_bytes(b"synthetic-test-original-172\x00\r\n")
        return self.call("media.register", media_id=mid, kind="image", path=str(source),
                         metadata=metadata or {"rights_status": "synthetic-only"})

    def test_exact_asset_version_views_do_not_reclassify_approved_content(self):
        first = self.save("ASSET", metadata={"asset_type": "character"})
        self.call("content.approve", artifact_id="ASSET", version=1, scope="ASSET",
                  evidence="synthetic exact approval", actor="test", synthetic=True)
        second = self.save("ASSET", 1, metadata={"asset_type": "prop"})
        before = self.r.dispatch("artifact.history", {"artifact_id": "ASSET"})
        snap = self.r.snapshot()
        for view in ("approved_artifacts", "current_content"):
            self.assertEqual((snap[view][0]["version"], snap[view][0]["asset_type"]), (1, "character"))
        self.assertEqual((snap["pending_candidates"][0]["version"], snap["pending_candidates"][0]["asset_type"]), (2, "prop"))
        self.assertEqual(snap["asset_summary"]["by_type"]["prop"]["artifacts"], 1)
        self.assertEqual(snap["asset_summary"]["artifact_count"], 1)
        self.assertEqual(self.r.dispatch("artifact.history", {"artifact_id": "ASSET"}), before)
        self.assertNotIn("asset_type", first)
        self.assertNotIn("asset_type", second)

    def test_legacy_labels_are_readonly_unknown_and_prompt_stays_asset(self):
        legacy = self.save("老角色名", kind="prompt")
        self.save("CHARACTER", kind="character")
        # Fixture represents an older producer's uninterpreted metadata.
        old_meta = dict(legacy["metadata"], asset_type="人物待议")
        self.r.db.execute("UPDATE artifacts SET metadata=? WHERE artifact_id=?", (canonical(old_meta), "老角色名"))
        media = self.media()
        old_media = copy.deepcopy(media)
        old_media.pop("classification_revision")
        old_media["metadata"]["asset_type"] = {"old": "unknown"}
        self.r._put("media", "media_id", media["media_id"], old_media)
        before = self.r.db.total_changes
        snap = self.r.snapshot()
        prompt = next(a for a in snap["current_content"] if a["artifact_id"] == "老角色名")
        character = next(a for a in snap["current_content"] if a["artifact_id"] == "CHARACTER")
        self.assertEqual((prompt["category"], prompt["asset_type"]), ("asset", "unclassified"))
        self.assertEqual(prompt["metadata"]["asset_type"], "人物待议")
        self.assertEqual(character["category"], "outline")
        self.assertNotIn("asset_type", character)
        self.assertEqual(snap["media"][0]["asset_type"], "unclassified")
        self.assertEqual(snap["media"][0]["classification_revision"], 0)
        self.assertEqual(self.r._get("media", "media_id", "IMG"), old_media)
        self.assertEqual(self.r.db.total_changes, before)

    def test_explicit_invalid_asset_types_reject_without_side_effects(self):
        events = len(self.r.snapshot()["events"])
        for index, value in enumerate((None, "角色", "", [], True)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.save(f"INVALID-{index}", metadata={"asset_type": value})
        with self.assertRaises(ValueError):
            self.save("BIO", kind="character_bio", metadata={"asset_type": "character"})
        self.assertFalse(self.r.snapshot()["artifacts"])
        self.assertEqual(len(self.r.snapshot()["events"]), events)

    def legacy_asset(self, aid, value, kind="asset"):
        saved = self.save(aid, kind=kind)
        metadata = dict(saved["metadata"], asset_type=value)
        self.r.db.execute("UPDATE artifacts SET metadata=? WHERE artifact_id=? AND version=1",
                          (canonical(metadata), aid))
        return self.r._artifact(aid, 1)

    def test_legacy_unknown_asset_types_survive_body_only_revision(self):
        for index, value in enumerate(("旧分类待议", ["legacy", True], {"z": [1, True], "a": "未知"}, None, True)):
            with self.subTest(value=value):
                aid = f"LEGACY-{index}"
                old = self.legacy_asset(aid, value)
                metadata = copy.deepcopy(old["metadata"])
                if isinstance(value, dict):
                    metadata["asset_type"] = {"a": "未知", "z": [1, True]}
                saved = self.save(aid, 1, content="# synthetic正文修订\r\n只编辑正文。", metadata=metadata)
                self.assertEqual(saved["version"], 2)
                self.assertEqual(canonical(saved["metadata"]["asset_type"]), canonical(value))
                self.assertEqual(self.r._artifact(aid, 1), old)
                view = next(a for a in self.r.snapshot()["pending_candidates"] if a["artifact_id"] == aid)
                self.assertEqual(view["asset_type"], "unclassified")
        self.assertFalse(self.r.snapshot()["decisions"])

    def test_legacy_unknown_asset_type_changes_still_reject_by_stable_json(self):
        cases = (("旧", "另一个非法值"), ([True], [1]), ({"flag": True}, {"flag": 1}), (True, 1), (1, True))
        for index, (old_value, changed_value) in enumerate(cases):
            with self.subTest(old=old_value, changed=changed_value):
                aid = f"CHANGED-{index}"
                old = self.legacy_asset(aid, old_value)
                with self.assertRaises(ValueError):
                    self.save(aid, 1, content="synthetic edit", metadata=dict(old["metadata"], asset_type=changed_value))
                self.assertEqual(self.r._artifact(aid), old)
        valid = self.save("VALID", metadata={"asset_type": "character"})
        with self.assertRaises(ValueError):
            self.save("VALID", 1, metadata=dict(valid["metadata"], asset_type="非法新值"))
        self.assertEqual(self.r._artifact("VALID"), valid)

    def test_legacy_compatibility_does_not_bypass_kind_scope_category_or_media_validation(self):
        asset = self.legacy_asset("ASSET-OLD", {"uninterpreted": True})
        for change in ({"kind": "prompt"}, {"scope": "another-scope"}):
            with self.subTest(change=change), self.assertRaises(ConflictError):
                self.save("ASSET-OLD", 1, metadata=asset["metadata"], **change)
        with self.assertRaises(ValueError):
            self.save("ASSET-OLD", 1, metadata=dict(asset["metadata"], category="other"))
        non_asset = self.legacy_asset("OLD-CHARACTER", "未知", kind="character")
        with self.assertRaises(ValueError):
            self.save("OLD-CHARACTER", 1, kind="character", metadata=non_asset["metadata"])
        for index, value in enumerate(("未知", [], {"flag": True})):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.media(f"NEW-MEDIA-{index}", metadata={"asset_type": value})
        media = self.media("OLD-MEDIA")
        media["metadata"]["asset_type"] = {"old": "unknown"}
        self.r._put("media", "media_id", media["media_id"], media)
        with self.assertRaises(ValueError):
            self.call("media.classify", media_id=media["media_id"], expected_sha256=media["sha256"],
                      asset_type={"old": "unknown"}, base_revision=0)
        self.assertEqual(self.r._get("media", "media_id", media["media_id"]), media)

    def test_task_submit_classification_keeps_execution_protocol(self):
        self.call("task.create", task_id="T", title="synthetic asset", module="assets", scope="T",
                  inputs=[], must_keep=[], allowed_changes=[], requirements=[], artifact_id="A")
        with self.assertRaises(ValueError):
            self.call("task.submit", task_id="T", artifact_id="A", kind="asset", base_version=0,
                      content="TEST", metadata={"asset_type": "bad"})
        self.assertIsNone(self.r._artifact("A"))
        self.assertEqual(self.r._get("tasks", "task_id", "T")["status"], "created")
        with self.assertRaises(ConflictError):
            self.save("A", scope="T", metadata={"asset_type": "prop"})
        saved = self.call("task.submit", task_id="T", artifact_id="A", kind="asset", base_version=0,
                          content="TEST", metadata={"asset_type": "scene"})["artifact"]
        self.assertEqual(saved["metadata"]["asset_type"], "scene")
        self.assertIn("execution_lock", saved["metadata"])
        self.assertEqual(saved["status"], "candidate")
        self.assertFalse(self.r.snapshot()["decisions"])

    def test_old_task_lock_is_not_bypassed_by_asset_metadata(self):
        self.call("task.create", task_id="OLD", title="synthetic old", module="assets", scope="OLD",
                  inputs=[], must_keep=[], allowed_changes=[], requirements=[])
        old = self.r._get("tasks", "task_id", "OLD")
        old.pop("execution_lock")
        self.r._put("tasks", "task_id", "OLD", old)
        with self.assertRaises(ValueError):
            self.call("task.submit", task_id="OLD", artifact_id="OLD-A", kind="asset", base_version=0,
                      content="TEST", metadata={"asset_type": "prop"})
        self.assertIsNone(self.r._artifact("OLD-A"))

    def test_media_classify_preserves_bytes_identity_rights_and_status(self):
        before = self.media()
        original = self.root / before["path"]
        original_bytes = original.read_bytes()
        payload = dict(op_id="classify-stable", expected_project_id="TEST-172", media_id="IMG",
                       expected_sha256=before["sha256"], asset_type="prop", base_revision=0)
        result = self.r.dispatch("media.classify", payload)
        self.assertTrue(result["classification_only"] and result["readback_verified"])
        self.assertEqual(result["media"]["classification_revision"], 1)
        self.assertEqual(result["asset_type"], "prop")
        for key in ("media_id", "path", "source_path", "sha256", "size_bytes", "status", "registered_at", "synthetic"):
            self.assertEqual(result["media"][key], before[key])
        self.assertEqual(result["media"]["metadata"]["rights_status"], before["metadata"]["rights_status"])
        self.assertEqual(original.read_bytes(), original_bytes)
        events = len(self.r.snapshot()["events"])
        self.assertEqual(self.r.dispatch("media.classify", payload), result)
        self.assertEqual(len(self.r.snapshot()["events"]), events)
        with self.assertRaises(ConflictError):
            self.r.dispatch("media.classify", dict(payload, asset_type="scene"))
        with self.assertRaises(ConflictError):
            self.r.dispatch("media.classify", dict(payload, op_id="stale-pane", asset_type="scene"))
        updated = self.r.dispatch("media.classify", dict(payload, op_id="next-revision", base_revision=1, asset_type="scene"))
        self.assertEqual(updated["media"]["classification_revision"], 2)
        self.assertFalse(self.r.snapshot()["decisions"])

    def test_media_classify_rejects_hash_identity_and_byte_changes(self):
        media = self.media()
        base = dict(media_id="IMG", expected_sha256=media["sha256"], asset_type="character", base_revision=0)
        with self.assertRaises(ConflictError):
            self.call("media.classify", **dict(base, expected_sha256="0" * 64))
        with self.assertRaises(ConflictError):
            self.call("media.classify", **base, expected_project_id="WRONG")
        with self.assertRaises(ValueError):
            self.r.dispatch("media.classify", {"op_id": "missing-identity", **base})
        (self.root / media["path"]).write_bytes(b"synthetic tampered fixture")
        with self.assertRaises(ConflictError):
            self.call("media.classify", **base)
        self.assertEqual(self.r._get("media", "media_id", "IMG"), media)

    def test_asset_summary_media_counts_match_registered_images(self):
        self.media(metadata={"asset_type": "scene"})
        for kind in ("audio", "video", "project", "other"):
            source = self.base / f"synthetic-{kind}.bin"
            source.write_bytes(b"synthetic non-image fixture")
            self.call("media.register", media_id=kind, kind=kind, path=str(source),
                      metadata={"asset_type": "prop", "rights_status": "synthetic-only"})
        snap = self.r.snapshot()
        self.assertEqual(len(snap["media"]), 5)
        self.assertTrue(all("asset_type" in m for m in snap["media"]))
        self.assertEqual(snap["asset_summary"]["media_scope"], "registered_images")
        self.assertEqual(snap["asset_summary"]["media_count"], 1)
        self.assertEqual(snap["asset_summary"]["by_type"]["scene"]["media"], 1)
        self.assertEqual(snap["asset_summary"]["by_type"]["prop"]["media"], 0)

    def test_media_classify_concurrent_panels_compare_classification_revision(self):
        media = self.media()
        other = Registry(self.root)
        try:
            common = dict(expected_project_id="TEST-172", media_id="IMG", expected_sha256=media["sha256"], base_revision=0)
            self.r.dispatch("media.classify", dict(common, op_id="panel-one", asset_type="character"))
            with self.assertRaises(ConflictError):
                other.dispatch("media.classify", dict(common, op_id="panel-two", asset_type="prop"))
            self.assertEqual(other._get("media", "media_id", "IMG")["metadata"]["asset_type"], "character")
        finally:
            other.close()

    def test_exact_export_preserves_markdown_mixed_newlines_and_old_version(self):
        body = "# TEST 标题\r\n\r\n- **粗体**  \r\n|A|B|\n|---|---|\n|1|2|\r\n```py\nprint('保留')\n```\n\r尾行"
        saved = self.save("../角色:*稿", kind="novel", content=body)
        self.save("../角色:*稿", 1, kind="novel", content="new candidate")
        before = self.r.db.total_changes
        paths = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
        readonly = Registry.open_readonly(self.root)
        try:
            result = readonly.dispatch("document.export", {"expected_project_id": "TEST-172", "artifact_id": "../角色:*稿", "version": 1})
        finally:
            readonly.close()
        self.assertTrue(result["read_only"])
        self.assertEqual(result["artifact_ref"], {"artifact_id": "../角色:*稿", "version": 1})
        self.assertEqual(result["content"], body)
        self.assertEqual(base64.b64decode(result["data_base64"]), body.encode("utf-8"))
        self.assertEqual(result["sha256"], saved["sha256"])
        self.assertEqual(result["size_bytes"], len(body.encode("utf-8")))
        self.assertEqual(result["mime"], "text/markdown; charset=utf-8")
        self.assertNotIn("/", result["filename"])
        self.assertNotIn(":", result["filename"])
        self.assertEqual(self.r.db.total_changes, before)
        self.assertEqual(sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*")), paths)

    def test_export_rejects_non_exact_identity_structures_and_record_kinds(self):
        self.save("TEXT", kind="novel", content="TEST")
        self.save("OBJECT", kind="research", content={"text": "# Not automatic Markdown"})
        self.call("planning.record", record_id="PLAN", scope="planning", base_version=0,
                  change={"record_kind": "idea", "title": "synthetic", "entries": []})
        self.call("artifact.save", artifact_id="OBS", kind="cloud_observation", scope="observation",
                  base_version=0, content="# synthetic diagnostic", metadata={})
        for aid in ("OBJECT", "PLAN", "OBS"):
            with self.subTest(aid=aid), self.assertRaises(ValueError):
                self.r.dispatch("document.export", dict(expected_project_id="TEST-172", artifact_id=aid, version=1))
        for version in (None, 0, True, "1", 99):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.r.dispatch("document.export", dict(expected_project_id="TEST-172", artifact_id="TEXT", version=version))
        with self.assertRaises(ValueError):
            self.r.dispatch("document.export", dict(artifact_id="TEXT", version=1))
        with self.assertRaises(ConflictError):
            self.r.dispatch("document.export", dict(expected_project_id="WRONG", artifact_id="TEXT", version=1))

    def test_working_draft_export_remains_unapproved_and_raw(self):
        body = "## synthetic 工作稿\r\n> 未通过\r\n"
        self.call("artifact.save", artifact_id="DRAFT", kind="cloud_working_draft", scope="draft",
                  base_version=0, content=body, metadata={"category": "novel"})
        result = self.r.dispatch("document.export", dict(expected_project_id="TEST-172", artifact_id="DRAFT", version=1))
        self.assertEqual(result["content"], body)
        self.assertEqual(result["kind"], "cloud_working_draft")
        self.assertFalse(self.r.snapshot()["masters"])
        self.assertFalse(self.r.snapshot()["decisions"])

    def test_mcp_document_export_uses_readonly_open_and_does_not_initialize(self):
        self.save("TEXT", kind="novel", content="# TEST\r\n原样\n")
        file = Path(__file__).parents[1] / "plugin/mcp_server.py"
        spec = importlib.util.spec_from_file_location("mcp_assets_documents172", file)
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        args = {"root": str(self.root), "action": "document.export", "payload": {"expected_project_id": "TEST-172", "artifact_id": "TEXT", "version": 1}}
        with patch.dict(os.environ, {"FILMPROD_CATALOG_PATH": str(self.base / "synthetic-catalog.sqlite3")}), patch.object(Registry, "__init__", side_effect=AssertionError("must not open writable registry")):
            result = server.call_tool("film_dispatch", args, None)["structuredContent"]
            self.assertEqual(result["content"], "# TEST\r\n原样\n")
            missing = self.base / "NO-PROJECT"
            with self.assertRaises(ValueError):
                server.call_tool("film_dispatch", {**args, "root": str(missing)}, None)
            self.assertFalse(missing.exists())

    def test_cli_document_export_is_readonly_and_schema1_never_migrates(self):
        import film
        self.save("TEXT", kind="novel", content="# TEST\r\n原样\n")
        payload = self.base / "synthetic-export-request.json"
        payload.write_text(json.dumps({"expected_project_id": "TEST-172", "artifact_id": "TEXT", "version": 1}), encoding="utf-8")
        args = ["film.py", "--root", str(self.root), "dispatch", "document.export", "--file", str(payload)]
        output = io.StringIO()
        with patch.object(sys, "argv", args), patch.object(Registry, "__init__", side_effect=AssertionError("CLI must not open writable registry")), redirect_stdout(output):
            self.assertEqual(film.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["content"], "# TEST\r\n原样\n")
        old = self.base / "TEST-SCHEMA1"
        database = old / ".project/registry.sqlite3"
        database.parent.mkdir(parents=True)
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            db.execute("INSERT INTO settings VALUES('schema_version','1')")
        db.close()
        before = database.read_bytes()
        paths = sorted(str(p.relative_to(old)) for p in old.rglob("*"))
        errors = io.StringIO()
        with patch.object(sys, "argv", ["film.py", "--root", str(old), "dispatch", "document.export", "--file", str(payload)]), patch.object(Registry, "__init__", side_effect=AssertionError("schema1 must not migrate")), redirect_stderr(errors):
            self.assertEqual(film.main(), 1)
        self.assertIn("schema 2", errors.getvalue())
        self.assertEqual(database.read_bytes(), before)
        self.assertEqual(sorted(str(p.relative_to(old)) for p in old.rglob("*")), paths)


if __name__ == "__main__":
    unittest.main()

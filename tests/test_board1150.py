"""1.15 management invariants: isolated test_only projects, synthetic facts only."""
import hashlib
import json
import os
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from filmprod.core import ConflictError, Registry
from filmprod.board1150 import DEFAULT_CATEGORIES


class Board1150Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="film-board1150-test_only-")
        self.base = Path(self.temp.name)
        self.r = Registry(self.base / "test_only-project")
        self.call("project.init", project_id="TEST-BOARD1150", title="Synthetic board", test_only=True)
        self.call("project.workflow.set", mode="screenplay", base_revision=0)
        self.v1 = self.save("SCRIPT", "script", "episode/1", "# 第一场\n甲：旧句。\n乙开门。", metadata={"episode": {"id": "E1", "title": "第一集"}, "title": "第一集"})
        self.approve(self.v1)
        self.task = self.call("task.create", task_id="LOCKED", title="Synthetic frozen input", module="director", scope="director/1", inputs=[self.ref(self.v1)], must_keep=[], allowed_changes=[], requirements=[])
        self.v2 = self.save("SCRIPT", "script", "episode/1", "# 第一场\n甲：新句。\n乙开门。", metadata={"episode": {"id": "E1", "title": "第一集"}, "title": "第一集修订"})
        self.prompt = self.save("PROMPT", "prompt", "asset/hero", "参考图提示词全文；没有实际图片", metadata={"asset_type": "character", "asset_id": "HERO"})
        self.original = self.base / "synthetic.bin"
        self.original.write_bytes(b"synthetic original bytes\x00\r\n")
        self.image = self.call("media.register", media_id="IMG", kind="image", path=str(self.original), metadata={"title": "最终已采用只是文件名", "asset_type": "character", "asset_id": "HERO"})
        self.audio = self.call("media.register", media_id="AUD", kind="audio", path=str(self.original), metadata={"title": "合成音频", "audio_category": "sfx"})

    def tearDown(self):
        self.r.close()
        self.temp.cleanup()

    def call(self, action, **payload):
        if action not in {"board.reference", "board.usage", "board.export", "snapshot", "artifact.history", "artifact.get", "task.resume"}:
            payload.setdefault("op_id", uuid.uuid4().hex)
        if action != "project.init":
            payload.setdefault("expected_project_id", "TEST-BOARD1150")
        return self.r.dispatch(action, payload)

    def save(self, aid, kind, scope, body, **payload):
        old = self.r._artifact(aid)
        return self.call("artifact.save", artifact_id=aid, kind=kind, scope=scope, content=body, base_version=old["version"] if old else 0, **payload)["artifact"]

    def ref(self, artifact):
        return {key: artifact[key] for key in ("artifact_id", "version", "sha256")}

    def approve(self, artifact):
        return self.call("content.approve", **self.ref(artifact), scope=artifact["scope"], actor="test", synthetic=True, evidence="synthetic test only")

    def identity(self, target):
        artifact = "artifact_id" in target
        return {"target_type": "artifact" if artifact else "media", "target_id": target["artifact_id"] if artifact else target["media_id"],
                **({"version": target["version"]} if artifact else {}), "expected_sha256": target["sha256"]}

    def manage(self, target, **changes):
        item = self.call("board.reference", **self.identity(target))["item"]
        return {**self.identity(target), "base_revision": item["revision"], "title": item["title"], "category_id": item["category_id"], "tags": item["tags"], "asset_id": item["asset_id"], **changes}

    def trash(self, target, deleted=True, base=0):
        return self.call("trash.set", **self.identity(target), base_revision=base, deleted=deleted)

    def rows(self, tables=None):
        tables = tables or ("settings", "artifacts", "media", "tasks", "threads", "decisions", "events", "operations", "approved_segments", "master_revisions", "master_sync")
        return {table: [tuple(row) for row in self.r.db.execute(f"SELECT * FROM {table} ORDER BY rowid")] for table in tables}

    def protected(self):
        return self.rows(("artifacts", "media", "tasks", "threads", "decisions", "approved_segments", "master_revisions", "master_sync"))

    def test_snapshot_and_query_read_only_without_original_scan(self):
        before = self.rows()
        with patch("filmprod.board1150._media_path", side_effect=AssertionError("snapshot must not scan files")):
            for _ in range(3):
                snapshot = self.r.snapshot()
                self.call("board.reference", **self.identity(self.v1))
                self.call("board.usage", **self.identity(self.image))
        self.assertEqual(before, self.rows())
        self.assertTrue(snapshot["board_library"]["read_only_facts"])
        self.assertFalse(snapshot["capabilities"]["board_business_execution"])

    def test_prompt_document_image_and_audio_are_separate(self):
        board = self.r.snapshot()["board_library"]
        self.assertEqual(board["counts"]["asset_prompt_text"], 1)
        self.assertEqual(board["counts"]["image"], 1)
        self.assertEqual(board["counts"]["audio"], 1)
        prompt = next(item for item in board["items"] if item["target_id"] == "PROMPT")
        self.assertEqual(prompt["media_kind"], "document")
        image = next(item for item in board["items"] if item["target_id"] == "IMG")
        self.assertEqual(image["adoption"]["status"], "not_recorded")
        self.assertEqual(image["review_status"], "not_recorded")
        self.assertEqual(len(board["asset_groups"][0]["items"]), 2)
        self.assertFalse(board["asset_groups"][0]["adoption_inferred"])

    def test_latest_adopted_and_locked_are_distinct_exact_versions(self):
        items = [item for item in self.r.snapshot()["board_library"]["items"] if item["target_id"] == "SCRIPT"]
        one, two = sorted(items, key=lambda item: item["version"])
        self.assertEqual(one["version_roles"], ["latest_adopted", "task_input_locked"])
        self.assertEqual(two["version_roles"], ["latest_working"])
        self.assertEqual(one["locked_by"][0]["task_id"], "LOCKED")
        self.assertEqual(two["adoption"]["status"], "not_recorded")
        self.assertEqual(two["review_status"], "not_recorded")
        self.assertEqual(one["adoption"]["status"], "current_adopted")
        self.assertEqual(one["production_lock_status"], "not_recorded")

    def test_adoption_uses_pointer_not_highest_historical_version_and_reverse_is_rejected(self):
        from filmprod.board1150 import _adoption
        self.approve(self.v2)
        with self.assertRaises(ConflictError):
            self.approve(self.v1)
        decisions = self.r._list("decisions")
        pointer = {"artifact_id": "SCRIPT", "version": 1, "scope": self.v1["scope"], "review_status": "approved"}
        with patch.object(self.r, "_approved_pointer", return_value=pointer):
            result = _adoption(self.r, self.identity(self.v2), self.v2, decisions)
            self.assertEqual(result["latest_adopted_version"], 1)
            self.assertEqual(result["status"], "historical_adopted")
        with patch.object(self.r, "_approved_pointer", return_value={**pointer, "artifact_id": "DIFFERENT"}):
            result = _adoption(self.r, self.identity(self.v2), self.v2, decisions)
            self.assertIsNone(result["latest_adopted_version"])

    def test_rename_category_tags_association_preserve_all_business_rows(self):
        before = self.protected()
        reference = self.call("board.reference", **self.identity(self.v1))["reference"]
        result = self.call("board.item.set", **self.manage(self.v1, title="改显示名称", category_id="other", tags=["按需复用", "一集"], asset_id="HERO"))
        self.call("board.item.set", **self.manage(self.image, title="角色参考图", tags=["人物"], category_id="other"))
        self.call("board.item.set", **self.manage(self.audio, title="环境声", category_id="ambience", tags=["夜间"]))
        self.assertEqual(before, self.protected())
        self.assertTrue(result["management_only"])
        copied = self.call("board.reference", **self.identity(self.v1))
        self.assertEqual(copied["reference"], reference)
        self.assertEqual(copied["item"]["title"], "改显示名称")
        self.assertEqual(copied["usage"]["tasks"][0]["task_id"], "LOCKED")
        self.assertEqual(self.original.read_bytes(), b"synthetic original bytes\x00\r\n")

    def test_old_rename_is_not_inherited_by_new_candidate(self):
        self.call("board.item.set", **self.manage(self.v1, title="只改第一版"))
        self.assertEqual(self.call("board.reference", **self.identity(self.v2))["item"]["title"], "第一集修订")

    def test_categories_add_rename_sort_does_not_reorder_creation(self):
        before = self.protected()
        categories = self.r.snapshot()["board_library"]["categories"]["audio"]["categories"]
        categories = list(reversed(categories)) + [{"id": "voiceover", "label": "旁白"}]
        categories[0]["label"] = "待整理"
        result = self.call("board.categories.set", media_kind="audio", categories=categories, base_revision=0)
        self.assertEqual(result["entry"]["revision"], 1)
        self.call("board.item.set", **self.manage(self.audio, category_id="voiceover"))
        self.assertEqual(self.protected(), before)
        with self.assertRaises(ConflictError):
            self.call("board.categories.set", media_kind="audio", categories=categories, base_revision=0)
        with self.assertRaises(ValueError):
            self.call("board.categories.set", media_kind="audio", categories=[{"id": "voiceover", "label": "旁白"}], base_revision=1)

    def test_legacy_display_order_and_archive_metadata_remain_observable(self):
        from filmprod.board_management190 import ORDER_GROUPS
        order = list(reversed(ORDER_GROUPS["asset_types"]))
        self.call("board.order.set", group="asset_types", order=order, base_revision=0)
        self.call("presentation.set", artifact_id="SCRIPT", version=1, expected_sha256=self.v1["sha256"], base_revision=0,
                  display_category="script", title="旧版归档显示名", archived=True)
        board = self.r.snapshot()["board_library"]
        self.assertEqual([row["id"] for row in board["categories"]["image"]["categories"]], order)
        item = self.call("board.reference", **self.identity(self.v1))["item"]
        self.assertTrue(item["legacy_archived"])
        self.assertFalse(item["deleted"])
        self.assertEqual(item["title"], "旧版归档显示名")
        self.call("board.item.set", **self.manage(self.v1, title="新展示名"))
        self.assertTrue(self.call("board.reference", **self.identity(self.v1))["item"]["legacy_archived"])

    def test_management_rejects_business_fields_wrong_hash_and_stale_revision(self):
        request = self.manage(self.v1)
        for override in ({"approved": True}, {"content": "伪造正文"}, {"version": 2}, {"expected_sha256": "0" * 64}, {"base_revision": True}, {"category_id": "scene"}, {"tags": ["a", "a"]}, {"tags": "tag"}):
            before = self.rows()
            with self.assertRaises(ValueError):
                self.call("board.item.set", **{**request, **override})
            self.assertEqual(before, self.rows())
        self.call("board.item.set", **request)
        with self.assertRaises(ConflictError):
            self.call("board.item.set", **request)

    def test_idempotency_does_not_revert_later_rename(self):
        request = self.manage(self.v1, title="第一次", op_id="FIXED-ITEM")
        first = self.call("board.item.set", **request)
        self.call("board.item.set", **self.manage(self.v1, title="第二次"))
        before = self.rows()
        self.assertEqual(first, self.call("board.item.set", **request))
        self.assertEqual(before, self.rows())
        self.assertEqual(self.call("board.reference", **self.identity(self.v1))["item"]["title"], "第二次")

    def test_two_connections_cannot_overwrite_display_revision(self):
        other = Registry(self.r.root)
        try:
            request = self.manage(self.image)
            self.call("board.item.set", **request)
            with self.assertRaises(ConflictError):
                other.dispatch("board.item.set", {**request, "expected_project_id": "TEST-BOARD1150", "op_id": uuid.uuid4().hex})
        finally:
            other.close()

    def test_changed_original_cannot_be_relabelled_or_exported(self):
        stored = self.r.root / self.image["path"]
        stored.write_bytes(b"tampered")
        before = self.rows()
        with self.assertRaises(ConflictError):
            self.call("board.item.set", **self.manage(self.image, title="mask tampering"))
        with self.assertRaises(ConflictError):
            self.call("board.export", items=[self.identity(self.image)])
        self.assertEqual(before, self.rows())

    def test_batch_organize_is_atomic_and_only_selected(self):
        before = self.protected()
        one = self.manage(self.v1, title="批量一", tags=["选定"])
        two = self.manage(self.audio, title="批量二", tags=["选定"])
        result = self.call("board.items.batch", operation="organize", items=[one, two])
        self.assertEqual(result["selected_count"], 2)
        self.assertEqual(before, self.protected())
        self.assertEqual(self.call("board.reference", **self.identity(self.image))["item"]["revision"], 0)
        before = self.rows()
        with self.assertRaises(ConflictError):
            self.call("board.items.batch", operation="organize", items=[self.manage(self.v1, title="不应保留"), {**self.manage(self.audio), "base_revision": 0}])
        self.assertEqual(before, self.rows())

    def test_batch_rejects_duplicates_and_injected_project(self):
        item = self.manage(self.v1)
        for items in ([item, item], [{**item, "expected_project_id": "OTHER"}]):
            before = self.rows()
            with self.assertRaises(ValueError):
                self.call("board.items.batch", operation="organize", items=items)
            self.assertEqual(before, self.rows())

    def test_trash_restore_retains_adoption_hash_locks_and_originals(self):
        before = self.protected()
        original = (self.r.root / self.image["path"]).read_bytes()
        self.call("board.items.batch", operation="trash", items=[{**self.identity(self.v1), "base_revision": 0, "deleted": True}, {**self.identity(self.image), "base_revision": 0, "deleted": True}])
        board = self.r.snapshot()["board_library"]
        self.assertEqual(board["counts"]["image"], 0)
        self.assertTrue(self.call("board.reference", **self.identity(self.v1))["item"]["deleted"])
        self.trash(self.v1, False, 1)
        self.trash(self.image, False, 1)
        self.assertEqual(before, self.protected())
        self.assertEqual(original, (self.r.root / self.image["path"]).read_bytes())
        self.assertEqual(self.call("board.reference", **self.identity(self.v1))["item"]["adoption"]["status"], "current_adopted")
        self.assertEqual(self.call("board.reference", **self.identity(self.image))["item"]["adoption"]["status"], "not_recorded")

    def test_trash_historical_nonlocked_version_is_recoverable(self):
        self.save("PROMPT", "prompt", "asset/hero", "第二提示词", metadata={"asset_type": "character"})
        self.trash(self.prompt)
        rows = [item for item in self.r.snapshot()["board_library"]["items"] if item["target_id"] == "PROMPT"]
        self.assertTrue(any(item["version"] == 1 and item["deleted"] for item in rows))

    def test_scope_progress_unknown_without_declared_plan(self):
        overview = self.r.snapshot()["board_library"]["overview"]
        self.assertIsNone(overview["completion_percent"])
        self.assertEqual(overview["scope_status"], "not_recorded")
        self.assertEqual(overview["representative_chapters"], [])
        self.assertEqual(overview["current_batches"], [])
        self.assertEqual(overview["episodes"][0]["title"], "第一集")
        self.assertEqual(overview["episodes"][0]["completion_status"], "unknown")

    def test_scope_facts_come_only_from_explicit_metadata_and_keep_candidate_identity(self):
        source = self.save("OUTLINE", "outline", "project/story", "全剧共用大纲", metadata={"production_scope": {"episodes": ["E1", "E2"]}, "representative_chapter": "E1", "batch": {"id": "B1", "current": True, "episodes": ["E1"]}})
        overview = self.r.snapshot()["board_library"]["overview"]
        self.assertEqual(overview["declared_scope"][0]["source"], self.ref(source))
        self.assertEqual(overview["declared_scope"][0]["adoption_status"], "not_recorded")
        self.assertEqual(overview["current_batches"][0]["value"]["id"], "B1")
        self.assertIsNone(overview["completion_percent"])

    def test_empty_scope_values_remain_unknown(self):
        for value in ({}, [], "", {"episodes": []}, {"current": True}, "unknown"):
            self.save("OUTLINE", "outline", "project/story", "空范围不冒充已声明", metadata={"production_scope": value, "representative_chapter": value, "batch": value, "current_batch": True})
            overview = self.r.snapshot()["board_library"]["overview"]
            self.assertEqual(overview["scope_status"], "not_recorded")
            self.assertEqual(overview["representative_chapters"], [])
            self.assertEqual(overview["current_batches"], [])

    def test_current_production_lock_requires_adopted_explicit_batch_task_mapping(self):
        plan = self.save("BATCH", "requirements", "project/batch", "本批范围和输入任务明确登记", metadata={"batch": {"id": "B1", "current": True, "task_ids": ["LOCKED"]}})
        item = self.call("board.reference", **self.identity(self.v1))["item"]
        self.assertEqual(item["production_lock_status"], "not_recorded")
        self.approve(plan)
        item = self.call("board.reference", **self.identity(self.v1))["item"]
        self.assertEqual(item["production_lock_status"], "recorded")
        self.assertIn("production_locked", item["version_roles"])
        self.assertEqual(item["production_locked_by"][0]["batch_sources"], [self.ref(plan)])

    def test_feedback_stays_on_reviewed_version_and_processing_is_not_pass(self):
        self.call("screenwriting.record", base_revision=0, feedback_id="F1", script=self.ref(self.v1), scope=self.v1["scope"], scene_id="S1", anchor="旧句", problem="措辞不明确", expected_effect="更明确", must_keep=["开门"], impact="expression", source={"role": "director", "reference": "synthetic-director-thread"})
        self.call("screenwriting.resolve", base_revision=1, feedback_id="F1", status="addressed", response="已修订候选", revised_script=self.ref(self.v2))
        board = self.r.snapshot()["board_library"]
        feedback = next(entry for entry in board["reviews"]["entries"] if entry["record_type"] == "feedback")
        self.assertEqual(feedback["artifact_ref"], self.ref(self.v1))
        self.assertFalse(feedback["applies_to_latest"])
        self.assertEqual(feedback["new_version_review"], "not_recorded")
        self.assertEqual(feedback["revised_ref"], self.ref(self.v2))
        current = next(item for item in board["items"] if item["target_id"] == "SCRIPT" and item["version"] == 2)
        self.assertEqual(current["review_status"], "not_recorded")
        query = self.call("board.reference", **self.identity(self.v1))
        self.assertEqual(query["item"]["review_status"], "recorded")
        self.assertEqual(query["item"]["review_record_ids"], ["F1"])

    def test_actual_revised_version_review_is_reported_without_inheriting_old_conclusion(self):
        self.call("screenwriting.record", base_revision=0, feedback_id="F1", script=self.ref(self.v1), scope=self.v1["scope"], scene_id="S1", anchor="旧句", problem="措辞", expected_effect="更明确", must_keep=[], impact="expression", source={"role": "director", "reference": "synthetic-director-thread"})
        self.call("screenwriting.resolve", base_revision=1, feedback_id="F1", status="addressed", response="已修订", revised_script=self.ref(self.v2))
        request = {"reference": "synthetic-user-review", "quote": "复核第二版完整正文"}
        self.call("delivery.define", delivery_id="D", base_revision=0, target_artifact_id="SCRIPT", scope=self.v2["scope"], granularity="准确第二版", user_request=request,
                  inputs=[], units=[{"unit_id": "U", "description": "完整正文", "source": {"type": "user_request", **request}}])
        review = self.call("delivery.review", delivery_id="D", revision=1, base_review_revision=0, artifact=self.ref(self.v2), author={"type": "host_agent", "id": "synthetic-writer"},
                           reviewer={"type": "host_subagent", "id": "synthetic-reviewer", "source_reference": "synthetic-review-turn"},
                           coverage=[{"unit_id": "U", "status": "covered", "output": {"location": "完整正文", "quote": self.v2["content"]}, "note": "synthetic verification"}], findings=[])
        board = self.r.snapshot()["board_library"]
        feedback = next(row for row in board["reviews"]["entries"] if row["record_type"] == "feedback")
        self.assertEqual(feedback["new_version_review"], "recorded")
        self.assertEqual(feedback["new_version_review_records"][0]["record_id"], review["review_id"])
        self.assertEqual(feedback["new_version_review_records"][0]["artifact_ref"], self.ref(self.v2))
        item = self.call("board.reference", **self.identity(self.v2))["item"]
        self.assertEqual(item["review_status"], "recorded")
        self.assertEqual(item["adoption"]["status"], "not_recorded")

    def test_usage_is_exact_and_never_inferred_from_names(self):
        dependent = self.save("DIR", "director", "director/other", "有精确依赖", deps=[self.ref(self.v1)])
        old = self.call("board.usage", **self.identity(self.v1))["usage"]
        new = self.call("board.usage", **self.identity(self.v2))["usage"]
        self.assertEqual(old["artifacts"][0]["artifact_id"], dependent["artifact_id"])
        self.assertTrue(old["masters"])
        self.assertEqual(new["artifacts"], [])
        self.assertEqual(new["tasks"], [])
        self.assertEqual(new["external_usage"], "unknown")
        self.assertEqual(self.call("board.usage", **self.identity(self.image))["usage"]["artifacts"], [])

    def test_master_usage_tracks_each_exact_version_after_new_adoption(self):
        self.approve(self.v2)
        old = self.call("board.usage", **self.identity(self.v1))["usage"]["masters"]
        new = self.call("board.usage", **self.identity(self.v2))["usage"]["masters"]
        self.assertEqual(old, [{"category": "script", "version": 1, "relation": "assembled_master"}])
        self.assertEqual(new, [{"category": "script", "version": 2, "relation": "assembled_master"}])

    def test_media_usage_exposes_adopted_exact_artifact_without_approving_media(self):
        artifact = self.save("IMAGE-NOTE", "asset", "asset/image-note", "已登记实际图的说明", metadata={"asset_type": "character", "source_media_id": "IMG"})
        self.approve(artifact)
        result = self.call("board.reference", **self.identity(self.image))
        self.assertEqual(result["item"]["adoption"]["status"], "not_recorded")
        self.assertEqual(result["usage"]["artifacts"][0]["adoption_status"], "current_adopted")
        self.assertTrue(result["usage"]["artifacts"][0]["adoption_record_ids"])
        self.assertFalse(result["usage"]["artifacts"][0]["media_adoption_inferred"])

    def test_import_source_displays_original_selected_path_and_retains_staging_provenance(self):
        imported = self.call("media.register", media_id="ORIGIN", kind="video", path=str(self.original), metadata={"original_source_path": "C:/synthetic-test-only/chosen-original.mp4"})
        item = self.call("board.reference", **self.identity(imported))["item"]
        self.assertEqual(item["source_path"], "C:/synthetic-test-only/chosen-original.mp4")
        self.assertEqual(item["registration_source_path"], imported["source_path"])

    def test_export_selected_exact_text_original_and_manifest_and_readback(self):
        before = self.rows()
        request = {"items": [self.identity(self.v1), self.identity(self.image), self.identity(self.audio)]}
        result = self.call("board.export", **request)
        self.assertTrue(result["saved_verified"])
        path = Path(result["local_path"])
        self.assertTrue(path.is_relative_to(self.r.root / "11-导出" / "资料包"))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), result["sha256"])
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("资料清单.json"))
            self.assertEqual(len(manifest["items"]), 3)
            documents = [name for name in archive.namelist() if name.endswith(".md")]
            self.assertEqual(archive.read(documents[0]).decode("utf-8"), self.v1["content"])
            media = [name for name in archive.namelist() if name.startswith("素材/")]
            self.assertEqual(len(media), 2)
            self.assertTrue(all(archive.read(name) == self.original.read_bytes() for name in media))
        second = self.call("board.export", **request)
        self.assertEqual(second["status"], "reused")
        self.assertEqual(before, self.rows())

    def test_export_recycled_explicit_version_is_allowed_but_no_arbitrary_path(self):
        self.trash(self.v1)
        result = self.call("board.export", items=[self.identity(self.v1)])
        self.assertTrue(result["saved_verified"])
        with self.assertRaises(ValueError):
            self.call("board.export", items=[self.identity(self.v1)], path=str(self.base / "evil.zip"))

    def test_export_existing_different_bytes_never_overwritten(self):
        request = {"items": [self.identity(self.v1)]}
        result = self.call("board.export", **request)
        target = Path(result["local_path"])
        target.write_bytes(b"user edited existing export")
        with self.assertRaises(ConflictError):
            self.call("board.export", **request)
        self.assertEqual(target.read_bytes(), b"user edited existing export")

    def test_export_rejects_hardlink_original(self):
        target = self.r.root / self.image["path"]
        alias = target.with_name("linked-original.bin")
        try:
            os.link(target, alias)
        except OSError:
            self.skipTest("OS does not allow hardlinks in this isolated test")
        with self.assertRaises(ValueError):
            self.call("board.export", items=[self.identity(self.image)])

    def test_media_import_rejects_linked_destination_before_external_write(self):
        import subprocess
        outside = self.base / "test_only-outside"
        outside.mkdir()
        linked = self.r.root / "05-片段" / "视频原件"
        linked.parent.mkdir(exist_ok=True)
        try:
            linked.symlink_to(outside, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                self.skipTest("directory links unavailable")
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(outside)], capture_output=True)
            if result.returncode:
                self.skipTest("directory junction unavailable")
        try:
            before = self.rows()
            with self.assertRaises(ValueError):
                self.call("media.register", media_id="BLOCKED", kind="video", path=str(self.original), metadata={})
            self.assertEqual(list(outside.iterdir()), [])
            self.assertEqual(before, self.rows())
        finally:
            if linked.is_symlink():
                linked.unlink()
            else:
                linked.rmdir()

    def test_media_import_does_not_replace_hardlinked_existing_original(self):
        stored = self.r.root / self.image["path"]
        alias = self.base / "synthetic-linked-original.bin"
        os.link(stored, alias)
        before = self.rows()
        with self.assertRaises(ValueError):
            self.call("media.register", media_id="COPY", kind="image", path=str(self.original), metadata={})
        self.assertEqual(before, self.rows())
        self.assertEqual(alias.read_bytes(), self.original.read_bytes())

    def test_readonly_registry_queries_and_export_work_but_management_rejected(self):
        readonly = Registry.open_readonly(self.r.root)
        try:
            payload = {"expected_project_id": "TEST-BOARD1150", **self.identity(self.v1)}
            self.assertEqual(readonly.dispatch("board.reference", payload)["reference"]["version"], 1)
            self.assertTrue(readonly.dispatch("board.export", {"expected_project_id": "TEST-BOARD1150", "items": [self.identity(self.v1)]})["saved_verified"])
            with self.assertRaises(ValueError):
                readonly.dispatch("board.item.set", {**self.manage(self.v1), "op_id": "READONLY", "expected_project_id": "TEST-BOARD1150"})
        finally:
            readonly.close()

    def test_trash_excluded_from_automatic_style_only_preserves_old_tasks(self):
        style = self.save("STYLE", "style_bible", "project/style", "# 视觉\n灰墙\n# 导演\n固定机位")
        self.approve(style)
        old = self.call("task.create", task_id="OLDSTYLE", title="old style", module="director", scope="director/oldstyle", inputs=[], must_keep=[], allowed_changes=[], requirements=[])
        self.assertIn({"artifact_id": "STYLE", "version": 1}, old["inputs"])
        self.trash(style)
        new = self.call("task.create", task_id="NEWSTYLE", title="new style", module="director", scope="director/newstyle", inputs=[], must_keep=[], allowed_changes=[], requirements=[])
        self.assertEqual(new["inputs"], [])
        self.assertNotIn("style_binding", new)
        saved = self.save("AFTER", "script", "episode/after", "新保存不会自动引用回收风格", use_current_style=True)
        self.assertEqual(saved["deps"], [])
        self.assertEqual(self.r._get("tasks", "task_id", "OLDSTYLE"), old)
        resumed = self.call("task.resume", task_id="OLDSTYLE")
        self.assertEqual(resumed["task"]["inputs"], old["inputs"])
        self.assertEqual(self.r._global_style()[0], {"artifact_id": "STYLE", "version": 1})
        workflow = self.r.snapshot()["workflow"]
        suggestions = [suggestion for key in ("stages", "optional_stages") for stage in workflow[key] for suggestion in stage.get("dependency_suggestions", []) if suggestion.get("stage_key") == "style"]
        self.assertTrue(suggestions)
        self.assertTrue(all(not suggestion["refs"] and suggestion["recycled_refs"] for suggestion in suggestions))


if __name__ == "__main__":
    unittest.main()

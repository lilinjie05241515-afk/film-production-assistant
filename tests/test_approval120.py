"""Schema 2 approval invariants. Every fixture is an isolated synthetic TEST."""
import json
import sqlite3
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from filmprod.core import ConflictError, Registry, content_hash


class Approval120Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="TEST_ONLY_APPROVAL_120_")
        self.root = Path(self.temp.name) / "project"
        self.r = Registry(self.root)
        self.call("project.init", project_id="TEST-APPROVAL-120", title="合成审批测试", test_only=True)

    def tearDown(self):
        self.r.close()
        self.temp.cleanup()

    def call(self, action, **payload):
        payload.setdefault("op_id", uuid.uuid4().hex)
        return self.r.dispatch(action, payload)

    def save(self, aid, content=None, base=0, kind="script", deps=None, order=None, scope=None):
        return self.call("artifact.save", artifact_id=aid, kind=kind, scope=scope or aid, content=content or f"TEST {aid} {base + 1}", base_version=base, deps=deps or [], metadata={} if order is None else {"order": order})

    def approve(self, aid, version=1, **extra):
        artifact = self.r.dispatch("artifact.get", {"artifact_id": aid, "version": version})
        return self.call("content.approve", artifact_id=aid, version=version, scope=artifact["scope"], evidence="合成测试明确批准", actor="test-runner", synthetic=True, **extra)

    def master(self, category="script"):
        return next(m for m in self.r.snapshot()["masters"] if m["category"] == category)

    def test_candidate_never_displaces_approved_or_invalidates_downstream(self):
        self.save("S1"); self.approve("S1")
        self.save("D1", kind="director", deps=[{"artifact_id": "S1", "version": 1}]); self.approve("D1")
        original = self.master()
        result = self.save("S1", "待审修改", base=1)
        self.assertEqual(result["invalidated"], [])
        snap = self.r.snapshot()
        self.assertEqual(self.master(), original)
        self.assertEqual(next(a for a in snap["current_content"] if a["artifact_id"] == "S1")["version"], 1)
        self.assertEqual(next(a for a in snap["pending_candidates"] if a["artifact_id"] == "S1")["version"], 2)
        self.assertEqual(self.r._artifact("D1")["status"], "approved")
        changed = self.approve("S1", 2)
        self.assertEqual(changed["invalidated"], ["D1"])
        self.assertEqual(next(a for a in self.r.snapshot()["approved_artifacts"] if a["artifact_id"] == "D1")["approval_status"], "needs_review")

    def test_partial_master_replacement_preserves_other_segment_bytes_and_history(self):
        for aid, order, text in (("S10", [1, 10], "第十场\n原文\n"), ("S2", [1, 2], "第二场\n原文\n"), ("S1", [1, 1], "第一场\n原文\n")):
            self.save(aid, text, order=order); self.approve(aid)
        before = self.master()
        self.assertEqual([x["artifact_id"] for x in before["segments"]], ["S1", "S2", "S10"])
        self.save("S2", "第二场\n修订\n", base=1, order=[1, 2])
        self.approve("S2", 2, base_master_version=3)
        after = self.master()
        for index in (0, 2):
            self.assertEqual(before["segments"][index], after["segments"][index])
        history = self.r.dispatch("master.history", {"category": "script"})
        self.assertEqual(len(history["versions"]), 4)
        self.assertEqual(history["versions"][2]["content"], before["content"])
        self.assertEqual(after["sha256"], content_hash(after["content"]))

    def test_approve_idempotent_across_operation_ids_and_decision_entrypoint(self):
        self.save("S1")
        first = self.approve("S1", op_id="exact")
        self.assertEqual(first, self.approve("S1", op_id="exact"))
        duplicate = self.approve("S1")
        self.assertTrue(duplicate["already_approved"])
        self.assertEqual(len(self.r.snapshot()["decisions"]), 1)
        self.save("S1", base=1)
        second = self.call("decision.record", artifact_id="S1", version=2, scope="S1", decision="adopt", evidence="合成对话批准", actor="test-runner", synthetic=True)
        self.assertEqual(second["approval"]["master"]["version"], 2)

    def test_wrong_scope_and_master_cas_leave_no_partial_writes(self):
        self.save("S1"); self.approve("S1")
        self.save("S1", base=1)
        with self.assertRaises(ValueError):
            self.call("content.approve", artifact_id="S1", version=2, scope="S1/一句", evidence="test", actor="test-runner", synthetic=True)
        with self.assertRaises(ConflictError):
            self.approve("S1", 2, base_master_version=0)
        self.assertEqual(self.master()["version"], 1)
        self.assertEqual(len(self.r.snapshot()["decisions"]), 1)

    def test_narrow_legacy_adoption_does_not_approve_whole_artifact(self):
        self.save("S1")
        result = self.call("decision.record", artifact_id="S1", version=1, scope="S1/对白", decision="adopt", evidence="合成部分范围", actor="test-runner", synthetic=True)
        self.assertEqual(result["approval_status"], "scope_mapping_required")
        self.assertEqual(self.r.snapshot()["masters"], [])

    def test_restore_is_new_candidate_and_history_is_read_only(self):
        self.save("S1", "旧正文"); self.approve("S1")
        self.save("S1", "新正文", base=1); self.approve("S1", 2)
        before = self.master()
        restored = self.call("artifact.restore", artifact_id="S1", version=1, base_version=2)
        self.assertEqual(restored["artifact"]["version"], 3)
        self.assertEqual(restored["artifact"]["content"], "旧正文")
        self.assertEqual(self.master(), before)
        with self.assertRaises(ConflictError):
            self.approve("S1", 1)
        count = self.r.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self.r.dispatch("master.history", {"category": "script"})
        self.r.dispatch("artifact.history", {"artifact_id": "S1"})
        self.assertEqual(self.r.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], count)
        self.approve("S1", 3)
        self.assertEqual(self.master()["version"], 3)

    def test_approved_task_input_survives_new_candidate(self):
        self.save("S1"); self.approve("S1")
        self.call("task.create", task_id="DRAFT", title="合成导演任务", module="director", scope="S1", inputs=[{"artifact_id": "S1", "version": 1}], must_keep=[], allowed_changes=[], requirements=[])
        self.save("S1", base=1)
        self.assertEqual(self.r.dispatch("task.resume", {"task_id": "DRAFT"})["stale_inputs"], [])
        result = self.call("task.submit", task_id="DRAFT", artifact_id="D1", kind="director", content="合成导演草稿", base_version=0)
        self.assertEqual(result["task"]["status"], "submitted")

    def test_initial_drafts_are_explicit(self):
        self.save("N1", kind="novel")
        snapshot = self.r.snapshot()
        self.assertEqual(snapshot["current_content"][0]["approval_status"], "initial_draft")
        self.assertEqual(snapshot["pending_candidates"][0]["approval_status"], "pending_review")

    def test_sync_failure_does_not_reverse_approval_or_require_reapproval(self):
        self.call("master.bind_page", category="script", page_id="TEST-PAGE", base_revision="r1")
        self.save("S1"); self.approve("S1")
        master = self.master()
        self.assertEqual(master["sync_status"], "pending")
        self.call("sync.intent", sync_id="SYNC1", page_id="TEST-PAGE", base_revision="r1", intended_content=master["content"], master_category="script", master_version=1)
        self.call("sync.observe", sync_id="SYNC1", status="failed", comments="合成宿主失败")
        self.assertEqual(self.master()["sync_status"], "failed")
        self.assertTrue(self.approve("S1")["already_approved"])
        self.assertEqual(len(self.r.snapshot()["decisions"]), 1)
        self.call("sync.intent", sync_id="SYNC2", page_id="TEST-PAGE", base_revision="r1", intended_content=master["content"], master_category="script", master_version=1)
        self.call("sync.observe", sync_id="SYNC2", status="verified", observed_content=master["content"], revision="r2")
        self.assertEqual(self.master()["sync_status"], "verified")
        self.assertEqual(self.r.snapshot()["master_bindings"][0]["base_revision"], "r2")

    def test_sync_conflict_wrong_content_and_unknown_guards(self):
        self.save("S1"); self.approve("S1")
        self.call("master.bind_page", category="script", page_id="TEST-PAGE", base_revision="r1")
        master = self.master()
        with self.assertRaises(ConflictError):
            self.call("sync.intent", sync_id="BAD", page_id="TEST-PAGE", base_revision="r1", intended_content="错误正文", master_category="script", master_version=1)
        self.call("sync.intent", sync_id="SYNC", page_id="TEST-PAGE", base_revision="r1", intended_content=master["content"], master_category="script", master_version=1)
        self.call("sync.observe", sync_id="SYNC", status="unknown")
        with self.assertRaises(ConflictError):
            self.call("sync.intent", sync_id="SECOND", page_id="TEST-PAGE", base_revision="r1", intended_content=master["content"], master_category="script", master_version=1)
        self.call("sync.observe", sync_id="SYNC", status="verified", observed_content="并发编辑正文", revision="r2")
        self.assertEqual(self.master()["sync_status"], "conflict")
        self.assertEqual(self.master()["content"], master["content"])

    def test_schema1_migration_backups_and_never_adopts_old_decisions(self):
        self.save("S1")
        self.call("decision.record", artifact_id="S1", version=1, scope="部分范围", decision="adopt", evidence="合成旧决定", actor="test-runner", synthetic=True)
        self.r.db.execute("UPDATE settings SET value='1' WHERE key='schema_version'")
        for table in ("approved_segments", "master_revisions", "master_bindings", "master_sync"):
            self.r.db.execute(f"DROP TABLE {table}")
        self.r.close(); self.r = Registry(self.root)
        snapshot = self.r.snapshot()
        self.assertEqual(snapshot["schema_version"], 2)
        self.assertEqual(snapshot["masters"], [])
        self.assertEqual(len(snapshot["decisions"]), 1)
        backup = Path(snapshot["migration"]["backup"])
        self.assertTrue(backup.is_file())
        with sqlite3.connect(backup) as db:
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0], "1")
            self.assertEqual(db.execute("SELECT count(*) FROM artifacts").fetchone()[0], 1)
        db.close()
        self.r.close(); self.r = Registry(self.root)
        self.assertEqual(self.r.snapshot()["migration"]["backup"], str(backup))

    def test_schema2_backup_restore_preserves_master_history(self):
        self.save("S1"); self.approve("S1")
        archive = Path(self.temp.name) / "backup.zip"
        self.call("backup.create", destination=str(archive))
        dest = Path(self.temp.name) / "restored"
        self.call("backup.restore", source=str(archive), destination=str(dest))
        other = Registry(dest)
        try:
            self.assertEqual(other.snapshot()["masters"], self.r.snapshot()["masters"])
        finally:
            other.close()

    def test_parallel_master_cas_has_one_winner_without_lost_segments(self):
        self.save("S1"); self.save("S2")
        def approve(aid):
            other = Registry(self.root)
            try:
                other.dispatch("content.approve", {"op_id": aid, "artifact_id": aid, "version": 1, "scope": aid, "evidence": "合成并发点击", "actor": "test-runner", "synthetic": True, "base_master_version": 0})
                return True
            except ConflictError:
                return False
            finally:
                other.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(approve, ["S1", "S2"])), 1)
        self.assertEqual(self.master()["version"], 1)
        self.assertEqual(len(self.master()["segments"]), 1)
        self.assertEqual(len(self.r.snapshot()["pending_candidates"]), 1)

    def test_scoped_categories_and_unrelated_dependencies_stay_separate(self):
        self.save("S1"); self.approve("S1")
        self.save("S2"); self.approve("S2")
        for aid, dep in (("D1", "S1"), ("D2", "S2")):
            self.save(aid, kind="director", deps=[{"artifact_id": dep, "version": 1}], scope=dep)
            self.approve(aid)
        self.save("S1", base=1)
        affected = self.approve("S1", 2)
        self.assertEqual(affected["invalidated"], ["D1"])
        self.assertEqual(self.r._artifact("D2")["status"], "approved")
        self.assertEqual(self.master("director")["version"], 2)
        self.assertEqual(self.master("script")["version"], 3)

    def test_host_authorization_shapes_validate_without_simulating_real_adoption(self):
        self.save("S1")
        payload = {"artifact_id": "S1", "version": 1, "scope": "S1", "actor": "human", "synthetic": False, "evidence": "validator-only"}
        auth = {"source": "panel-click", "actor_identity": "current-host-user-unresolved", "real_user_id": None, "quote": "通过并更新总稿", "artifact_id": "S1", "version": 1, "scope": "S1", "observed_at": "2026-10-24T12:00:00+08:00"}
        self.r._validate_authorization(dict(payload, user_authorization=auth))
        conversation = dict(auth, source="conversation", thread_id="TEST-THREAD", quote="批准 S1 第1版全段")
        self.r._validate_authorization(dict(payload, user_authorization=conversation))
        with self.assertRaises(ValueError):
            self.r._validate_authorization(dict(payload, user_authorization=dict(auth, version=2)))
        with self.assertRaises(ValueError):
            self.call("content.approve", **payload, user_authorization=auth)
        self.assertEqual(self.r.snapshot()["decisions"], [])
        self.assertEqual(self.r.snapshot()["masters"], [])

    def test_older_sync_readback_cannot_mark_new_master_verified(self):
        self.call("master.bind_page", category="script", page_id="TEST-PAGE", base_revision="r1")
        self.save("S1"); self.approve("S1")
        first = self.master()
        self.call("sync.intent", sync_id="SYNC1", page_id="TEST-PAGE", base_revision="r1", intended_content=first["content"], master_category="script", master_version=1)
        self.save("S1", base=1); self.approve("S1", 2)
        self.call("sync.observe", sync_id="SYNC1", status="verified", observed_content=first["content"], revision="r2")
        self.assertEqual(self.master()["sync_status"], "pending")
        self.assertEqual(self.master()["base_revision"], "r2")
        history = self.r.dispatch("master.history", {"category": "script"})
        self.assertEqual(history["versions"][0]["sync_status"], "verified")
        with self.assertRaises(ConflictError):
            self.call("sync.intent", sync_id="OLD", page_id="TEST-PAGE", base_revision="r2", intended_content=first["content"], master_category="script", master_version=1)

    def test_project_thread_keeps_purpose_exact_links_on_status_update(self):
        self.save("R1", kind="research")
        refs = [{"artifact_id": "R1", "version": 1}]
        payload = dict(thread_id="SYNTHETIC-THREAD", title="合成研究登记", scope="research", status="active", purpose="研究光线", artifact_refs=refs, client_project_id="TEST-CLIENT", current_control=True)
        self.call("thread.register", **payload)
        result = self.call("thread.register", thread_id="SYNTHETIC-THREAD", title="合成研究登记", scope="research", status="complete")
        self.assertEqual(result["purpose"], "研究光线")
        self.assertEqual(result["artifact_refs"], refs)
        self.assertTrue(result["current_control"])
        self.assertFalse(result["host_thread_created_by_registry"])
        with self.assertRaises(ValueError):
            self.call("thread.register", **dict(payload, artifact_refs=[{"artifact_id": "R1", "version": 2}]))

    def test_cloud_observations_and_render_evidence_cannot_enter_creative_master(self):
        for kind in ("cloud_working_draft", "pages_observation", "cloud_observation", "render"):
            self.call("artifact.save", artifact_id=kind, kind=kind, scope=kind, content="TEST技术或云观察", base_version=0, metadata={"category": "script"})
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.approve(kind)
        self.call("artifact.save", artifact_id="ASSET", kind="asset", scope="asset/1", content="TEST资产", base_version=0, metadata={"category": "assets"})
        snapshot = self.r.snapshot()
        self.assertEqual([a["artifact_id"] for a in snapshot["current_content"]], ["ASSET"])
        self.assertEqual(snapshot["current_content"][0]["category"], "asset")
        self.assertEqual(len(snapshot["artifacts"]), 5)

    def test_stale_candidate_dependencies_remain_pending_and_cannot_be_laundered(self):
        self.save("S1"); self.approve("S1")
        self.save("D1", kind="director", deps=[{"artifact_id": "S1", "version": 1}])
        self.save("S1", base=1); self.approve("S1", 2)
        self.assertEqual(self.r._artifact("D1")["status"], "candidate")
        candidate = next(a for a in self.r.snapshot()["pending_candidates"] if a["artifact_id"] == "D1")
        self.assertEqual(candidate["input_status"], "stale")
        with self.assertRaises(ConflictError):
            self.call("task.create", task_id="FX", title="过期候选不得转交", module="vfx", scope="FX", inputs=[{"artifact_id": "D1", "version": 1}], must_keep=[], allowed_changes=[], requirements=[])
        with self.assertRaises(ConflictError):
            self.approve("D1")

    def test_cloud_deletion_marker_cannot_be_approved_as_story_body(self):
        self.save("S1", "已通过的真实测试正文"); self.approve("S1")
        before = self.master()
        self.call("artifact.save", artifact_id="S1", kind="script", scope="S1", content="待审核删除诊断占位", base_version=1, metadata={"deleted_in_cloud": True})
        with self.assertRaisesRegex(ValueError, "诊断占位"):
            self.approve("S1", 2)
        self.assertEqual(self.master(), before)
        self.assertEqual(self.r.snapshot()["current_content"][0]["version"], 1)

    def test_expected_project_identity_blocks_writes_and_cached_replay(self):
        result = self.call("artifact.save", op_id="identity-save", expected_project_id="TEST-APPROVAL-120", artifact_id="S1", kind="script", scope="S1", content="TEST", base_version=0)
        with self.assertRaisesRegex(ConflictError, "项目身份"):
            self.call("artifact.save", expected_project_id="OTHER-TEST", artifact_id="S2", kind="script", scope="S2", content="wrong", base_version=0)
        project = self.r._project(); project["project_id"] = "TEST-REPLACEMENT"
        self.r.db.execute("UPDATE settings SET value=? WHERE key='project'", (json.dumps(project),))
        with self.assertRaisesRegex(ConflictError, "项目身份"):
            self.call("artifact.save", op_id="identity-save", expected_project_id="TEST-APPROVAL-120", artifact_id="S1", kind="script", scope="S1", content="TEST", base_version=0)
        self.assertEqual(len(self.r.snapshot()["artifacts"]), 1)
        self.assertEqual(result["artifact"]["content"], "TEST")

    def test_duplicate_creative_scope_id_rejected_without_hiding_candidate(self):
        self.save("S1", scope="chapter/scene"); self.approve("S1")
        with self.assertRaisesRegex(ConflictError, "稳定成果 ID"):
            self.save("S1-OTHER", scope="chapter/scene", kind="screenplay")
        self.save("D1", scope="chapter/scene", kind="director")
        self.assertEqual([a["artifact_id"] for a in self.r.snapshot()["pending_candidates"]], ["D1"])

    def test_sync_rejects_pre_intent_or_backwards_observation_and_revision(self):
        self.call("master.bind_page", category="script", page_id="TEST-PAGE", base_revision=5)
        self.save("S1"); self.approve("S1")
        content = self.master()["content"]
        self.call("sync.intent", sync_id="TIME", page_id="TEST-PAGE", base_revision=5, intended_content=content, master_category="script", master_version=1)
        for extra in ({"observed_at":"2020-01-01T00:00:00+00:00","revision":6}, {"revision":4}):
            with self.assertRaises(ConflictError):
                self.call("sync.observe", sync_id="TIME", status="verified", observed_content=content, **extra)
        self.assertEqual(self.master()["sync_status"], "pending")
        self.assertEqual(self.r.snapshot()["master_bindings"][0]["base_revision"], 5)
        with self.assertRaises(ConflictError):
            self.call("master.bind_page", category="script", page_id="TEST-PAGE", base_revision=4)

    def test_historical_sync_observation_preserves_newer_binding_revision(self):
        self.call("master.bind_page", category="script", page_id="TEST-PAGE", base_revision=5)
        self.save("S1"); self.approve("S1")
        content = self.master()["content"]
        self.call("sync.intent", sync_id="OLD", page_id="TEST-PAGE", base_revision=5, intended_content=content, master_category="script", master_version=1)
        self.call("master.bind_page", category="script", page_id="TEST-PAGE", base_revision=10)
        result = self.call("sync.observe", sync_id="OLD", status="verified", observed_content=content, revision=6)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(self.r.snapshot()["master_bindings"][0]["base_revision"], 10)


if __name__ == "__main__":
    unittest.main()

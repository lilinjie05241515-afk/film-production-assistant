"""Isolated local state tests; all Page observations are synthetic."""
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from filmprod.core import Registry, ConflictError, now
from filmprod.cloud1120 import action_schemas, cloud_update_schema, validate_cloud_payload


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="filmprod-cloud-TEST-")
        self.root = Path(self.temp.name) / "TEST-only"
        self.r = Registry(self.root)
        self.call("project.init", project_id="TEST-CLOUD", title="云稿合成测试", test_only=True)
        self.user = {"source": "conversation", "reference": "TEST-message", "quote": "请整理完整大纲初稿，并建立云端工作稿，以后确认的修改同步到同一份稿。"}

    def tearDown(self):
        self.r.close(); self.temp.cleanup()

    def call(self, action, **payload):
        payload.setdefault("op_id", uuid.uuid4().hex)
        if action != "project.init":
            payload.setdefault("expected_project_id", "TEST-CLOUD")
        return self.r.dispatch(action, payload)

    def read(self, **payload):
        return self.r.dispatch("cloud.read", {"expected_project_id": "TEST-CLOUD", **payload})

    def write(self, action, **payload):
        payload.setdefault("base_revision", self.read()["revision"])
        return self.call(action, **payload)

    def save(self, body="# 大纲\n\n第一幕。\n\n第二幕。", *, aid="outline", scope="project/outline", cloud=True, trigger="full_draft", **extra):
        old = self.r._artifact(aid)
        args = {"artifact_id": aid, "kind": "outline", "scope": scope, "content": body, "base_version": old["version"] if old else 0}
        if cloud:
            args["cloud_update"] = {"trigger": trigger, "user_request": self.user, **extra}
        return self.call("artifact.save", **args)

    def job(self, job_id=None):
        jobs = self.read()["jobs"]
        return next(j for j in jobs if j["job_id"] == job_id) if job_id else jobs[-1]

    def ref(self, artifact):
        return {key: artifact[key] for key in ("artifact_id", "version", "sha256")}

    def page(self, content, page_id="page_TEST_one"):
        return {"source": "host_tool", "tool": "read_page", "observed_at": now(), "page_id": page_id,
                "page_url": "https://example.invalid/" + page_id, "content": content, "whole_page_complete": True, "revision": None}

    def record(self, event, job_id=None, **observation):
        j = self.job(job_id)
        return self.write("cloud.record", job_id=j["job_id"], event=event, observation={"request_id": j["request_id"], **observation})

    def created(self, job_id=None, page_id="page_TEST_one"):
        return self.record("page_created", job_id, source="host_tool", tool="create_page", observed_at=now(), page_id=page_id, page_url="https://example.invalid/" + page_id)

    def synced(self, save=None):
        result = save or self.save()
        j = result["cloud_update"]["job_id"]
        self.record("request_started", j)
        self.created(j)
        self.record("verified", j, **self.page(result["artifact"]["content"]))
        return result

    def logical(self):
        return {t: [tuple(row) for row in self.r.db.execute("SELECT * FROM " + t)] for t in ("settings", "artifacts", "operations", "events", "decisions")}

    def test_read_default_and_readonly_file_unchanged(self):
        self.assertEqual(self.read()["policy"], {"mode": "round_end", "destination": {"kind": "private"}})
        self.assertEqual(self.read()["jobs"], [])
        self.assertFalse(self.read()["host_execution"])
        self.r.close()
        db = self.root / ".project/registry.sqlite3"; before = db.read_bytes()
        self.r = Registry.open_readonly(self.root)
        self.read(); self.r.snapshot()
        self.assertEqual(before, db.read_bytes())

    def test_full_save_queues_same_transaction_without_approval(self):
        saved = self.save()
        self.assertEqual(saved["cloud_update"]["artifact"], self.ref(saved["artifact"]))
        self.assertEqual(saved["cloud_update"]["status"], "prepared")
        self.assertEqual(saved["cloud_update"]["next_action"], "claim")
        self.assertIsNone(self.read()["documents"][0]["page_id"])
        self.assertEqual(self.r.snapshot()["approved_artifacts"], [])
        self.assertEqual(self.r.snapshot()["cloud"], self.read())

    def test_old_saves_discussion_and_local_only_do_not_queue(self):
        self.save(cloud=False)
        self.assertEqual(self.read()["jobs"], [])
        self.assertEqual(self.save(trigger="local_only")["cloud_update"]["status"], "local_only")
        self.write("cloud.configure", mode="local_only", user_request=self.user)
        self.save()
        self.assertEqual(self.read()["jobs"], [])

    def test_invalid_update_rolls_back_saved_artifact(self):
        before = self.logical()
        with self.assertRaises(ValueError):
            self.call("artifact.save", artifact_id="bad", kind="outline", scope="project/outline", content="完整正文", base_version=0, cloud_update={"trigger": "discussion", "user_request": self.user})
        self.assertEqual(before, self.logical())

    def test_prepare_retry_reuses_exact_job_and_creation_key(self):
        saved = self.save(); original = self.job()
        again = self.write("cloud.prepare", artifact=self.ref(saved["artifact"]), trigger="full_draft", user_request=self.user)
        self.assertEqual(original["job_id"], again["job_id"])
        self.assertEqual(original["creation_key"], again["creation_key"])
        self.assertEqual(len(self.read()["jobs"]), 1)

    def test_cached_save_does_not_duplicate(self):
        payload = dict(artifact_id="a", kind="outline", scope="project/outline", content="文本", base_version=0, cloud_update={"trigger":"full_draft","user_request":self.user}, op_id="fixed")
        first = self.call("artifact.save", **payload)
        self.assertEqual(first, self.call("artifact.save", **payload))
        self.assertEqual(len(self.read()["jobs"]), 1)

    def test_claim_once_and_created_is_not_synced(self):
        self.save(); self.record("request_started")
        with self.assertRaises(ConflictError): self.record("request_started")
        self.created()
        self.assertEqual(self.job()["status"], "awaiting_readback")
        self.assertIsNone(self.read()["documents"][0]["last_synced_ref"])

    def test_exact_complete_readback_is_required(self):
        saved = self.save(); self.record("request_started"); self.created()
        partial = self.page("摘要"); partial["whole_page_complete"] = False
        with self.assertRaises(ValueError): self.record("verified", **partial)
        with self.assertRaises(ValueError): self.record("verified", source="host_tool", tool="read_page", observed_at=now(), page_id="page_TEST_one", page_url="https://example.invalid/test", sha256=saved["artifact"]["sha256"], whole_page_complete=True, revision=None)
        self.record("verified", **self.page(saved["artifact"]["content"]))
        self.assertEqual(self.job()["status"], "synced")
        self.assertEqual(self.read()["documents"][0]["last_synced_ref"], self.ref(saved["artifact"]))
        self.assertEqual(self.r.snapshot()["approved_artifacts"], [])

    def test_mismatched_content_preserved_conflict_not_trimmed(self):
        saved = self.save(); self.record("request_started"); self.created()
        changed = saved["artifact"]["content"] + "\n"
        self.record("verified", **self.page(changed))
        self.assertEqual(self.job()["status"], "conflict")
        observation = self.read(observation_id=self.job()["last_observation_id"])["observation"]
        self.assertEqual(observation["content"], changed)

    def test_unknown_creation_cannot_restart_or_fail_away(self):
        self.save(); self.record("request_started"); self.record("unknown", reason="网络中断")
        with self.assertRaises(ConflictError): self.record("request_started")
        with self.assertRaises(ConflictError): self.record("failed", reason="猜测失败", no_write_performed=True)
        self.assertEqual(self.job()["next_action"], "recover_creation")
        self.created()
        self.assertEqual(self.job()["status"], "awaiting_readback")

    def test_newer_save_preserves_inflight_and_uses_same_page_after_recovery(self):
        first = self.save(); old = self.job()["job_id"]
        self.record("request_started", old); self.record("unknown", old, reason="超时")
        newer = self.save("完整修订正文", trigger="confirmed_revision"); new = self.job()["job_id"]
        self.assertEqual(self.job(old)["status"], "unknown")
        self.assertEqual(self.job(new)["next_action"], "resolve_previous")
        with self.assertRaises(ConflictError): self.record("request_started", new)
        self.created(old)
        with self.assertRaises(ConflictError): self.record("preflight", new, **self.page(newer["artifact"]["content"]))
        self.record("verified", old, **self.page(first["artifact"]["content"]))
        self.record("preflight", new, **self.page(first["artifact"]["content"]))
        self.record("request_started", new)
        self.record("verified", new, **self.page(newer["artifact"]["content"]))
        self.assertEqual(self.job(new)["status"], "synced")
        self.assertEqual(self.job(new)["page_id"], "page_TEST_one")
        self.assertEqual(len(self.read()["documents"]), 1)

    def test_unsent_old_job_superseded_and_stale_start_rejected(self):
        self.save(); old = self.job()["job_id"]
        self.save("新版完整正文")
        self.assertEqual(self.job(old)["status"], "superseded")
        with self.assertRaises(ConflictError): self.record("request_started", old)

    def test_stale_artifact_after_local_save_cannot_be_claimed(self):
        self.save(); job = self.job()["job_id"]
        self.save("仅本地新版", cloud=False)
        with self.assertRaises(ConflictError): self.record("request_started", job)

    def test_bound_update_requires_fresh_preflight(self):
        old = self.synced()
        self.save("下一版正文", trigger="confirmed_revision")
        with self.assertRaises(ConflictError): self.record("request_started")
        self.record("preflight", **self.page(old["artifact"]["content"]))
        self.assertEqual(self.job()["next_action"], "claim")
        self.record("request_started")

    def test_manual_cloud_edit_conflicts_and_preserves_source(self):
        self.synced(); self.save("本地修订", trigger="confirmed_revision")
        self.record("preflight", **self.page("用户手动编辑了云稿"))
        self.assertEqual(self.job()["status"], "conflict")
        with self.assertRaises(ConflictError): self.record("request_started")
        observation = self.read(observation_id=self.job()["last_observation_id"])["observation"]
        self.assertEqual(observation["content"], "用户手动编辑了云稿")

    def test_explicit_cloud_source_and_new_preflight_allows_revision(self):
        self.synced(); current = self.r._artifact("outline")
        bound = self.write("cloud.bind", artifact=self.ref(current), user_request=self.user, observation=self.page("用户手动改动"))
        result = self.save("保留手动改动后的完整修订", trigger="confirmed_revision", base_observation_id=bound["observation_id"])
        self.record("preflight", **self.page("用户手动改动"))
        self.record("request_started")
        self.record("verified", **self.page(result["artifact"]["content"]))
        self.assertEqual(self.job()["status"], "synced")

    def test_cloud_changed_again_after_source_observation_conflicts(self):
        self.synced(); current = self.r._artifact("outline")
        bound = self.write("cloud.bind", artifact=self.ref(current), user_request=self.user, observation=self.page("手改1"))
        self.save("融合手改1", base_observation_id=bound["observation_id"], trigger="confirmed_revision")
        self.record("preflight", **self.page("手改2"))
        self.assertEqual(self.job()["status"], "conflict")

    def test_new_read_invalidates_preflight(self):
        original = self.synced(); self.save("修订正文")
        self.record("preflight", **self.page(original["artifact"]["content"]))
        self.write("cloud.bind", artifact=self.ref(self.r._artifact("outline")), user_request=self.user, observation=self.page("又有改动"))
        with self.assertRaises(ConflictError): self.record("request_started")

    def test_existing_page_bind_not_sync_and_cannot_replace_or_share(self):
        a = self.save(cloud=False)["artifact"]
        bound = self.write("cloud.bind", artifact=self.ref(a), user_request=self.user, observation=self.page("现有正文"))
        self.assertIsNone(bound["document"]["last_synced_ref"])
        with self.assertRaises(ConflictError): self.write("cloud.bind", artifact=self.ref(a), user_request=self.user, observation=self.page("其他Page", "page_TEST_other"))
        b = self.save(aid="outline2", scope="other/outline", cloud=False)["artifact"]
        with self.assertRaises(ConflictError): self.write("cloud.bind", artifact=self.ref(b), user_request=self.user, observation=self.page("现有正文"))

    def test_page_of_category_master_is_not_artifact_target(self):
        a = self.save(cloud=False)["artifact"]
        self.call("master.bind_page", category="outline", page_id="page_TEST_one", base_revision="rev")
        with self.assertRaises(ConflictError): self.write("cloud.bind", artifact=self.ref(a), user_request=self.user, observation=self.page("整稿"))

    def test_complete_current_content_can_sync_without_extra_write(self):
        result = self.synced(); current = result["artifact"]["content"]
        newer = self.save(current, trigger="confirmed_revision")
        self.record("preflight", **self.page(current))
        self.assertEqual(self.job()["status"], "synced")
        self.assertEqual(self.read()["documents"][0]["last_synced_ref"], self.ref(newer["artifact"]))

    def test_timestamp_identity_cas_and_request_protection(self):
        self.save(); before = self.logical()
        with self.assertRaises(ConflictError): self.write("cloud.configure", base_revision=0, mode="local_only", user_request=self.user)
        self.assertEqual(before, self.logical())
        with self.assertRaises(ConflictError): self.r.dispatch("cloud.read", {"expected_project_id": "WRONG"})
        with self.assertRaises(ConflictError): self.write("cloud.record", job_id=self.job()["job_id"], event="request_started", observation={"request_id":"wrong"})
        self.record("request_started"); self.created()
        old = self.page("正文"); old["observed_at"]="2020-01-01T00:00:00+00:00"
        with self.assertRaises(ConflictError): self.record("verified", **old)

    def test_schema_invalid_before_project_access(self):
        base = {"op_id":"TEST","expected_project_id":"TEST","base_revision":0,"job_id":"TEST","event":"verified","observation":{"request_id":"TEST", **self.page("正文")}}
        for key, value in (("whole_page_complete",False),("revision",True),("observed_at","2026-10-25")):
            test = json.loads(json.dumps(base)); test["observation"][key]=value
            with self.assertRaises(ValueError): validate_cloud_payload("cloud.record",test)
        self.assertEqual(set(action_schemas()), {"cloud.read","cloud.configure","cloud.bind","cloud.prepare","cloud.record"})
        self.assertIn("local_only", cloud_update_schema()["properties"]["trigger"]["enum"])

    def test_no_body_in_snapshot_or_normal_cloud_read(self):
        secret = "独立合成超长正文不要回显" * 100
        self.synced(self.save(secret))
        self.assertNotIn(secret, json.dumps(self.read(), ensure_ascii=False))
        self.assertNotIn(secret, json.dumps(self.r.snapshot()["cloud"], ensure_ascii=False))

    def test_new_pending_blocks_legacy_sync_and_total_binding(self):
        self.save(); self.record("request_started"); self.created()
        with self.assertRaises(ConflictError):
            self.call("sync.intent", sync_id="legacy", page_id="page_TEST_one", base_revision="known", intended_content="文本")
        with self.assertRaises(ConflictError):
            self.call("master.bind_page", category="outline", page_id="page_TEST_one", base_revision="known")

    def test_legacy_pending_blocks_new_cloud_claim(self):
        original = self.synced(); self.save("下一稿")
        self.record("preflight", **self.page(original["artifact"]["content"]))
        self.call("sync.intent", sync_id="legacy", page_id="page_TEST_one", base_revision="known", intended_content="其他已授权工作稿修改")
        with self.assertRaises(ConflictError): self.record("request_started")

    def test_cloud_update_requires_explicit_project_identity(self):
        before = self.logical()
        with self.assertRaises(ValueError):
            self.r.dispatch("artifact.save", {"op_id":"missing-identity", "artifact_id":"a", "kind":"outline", "scope":"project/outline", "content":"全文", "base_version":0,"cloud_update":{"trigger":"full_draft","user_request":self.user}})
        self.assertEqual(before, self.logical())

    def test_existing_page_bound_after_auto_queue_reuses_target(self):
        saved = self.save(); original = self.job()
        bound = self.write("cloud.bind", artifact=self.ref(saved["artifact"]), user_request=self.user, observation=self.page(saved["artifact"]["content"], "page_TEST_existing"))
        job = self.job()
        self.assertEqual(job["job_id"], original["job_id"])
        self.assertEqual(job["page_id"], "page_TEST_existing")
        self.assertEqual(job["status"], "awaiting_read")
        self.assertEqual(job["next_action"], "preflight")
        self.assertIsNone(job["base_sha256"])
        self.record("preflight", **self.page(saved["artifact"]["content"], "page_TEST_existing"))
        self.assertEqual(self.job()["status"], "synced")
        self.assertEqual(len(self.read()["documents"]), 1)

    def test_bind_different_body_needs_explicit_base_observation(self):
        saved = self.save(); old = self.job()["job_id"]
        bound = self.write("cloud.bind", artifact=self.ref(saved["artifact"]), user_request=self.user, observation=self.page("已读且明确作为底本的云稿", "page_TEST_existing"))
        self.assertIsNone(self.job()["base_sha256"])
        prepared = self.write("cloud.prepare", artifact=self.ref(saved["artifact"]), trigger="confirmed_revision", user_request=self.user, base_observation_id=bound["observation_id"])
        self.assertNotEqual(prepared["job_id"], old)
        self.assertEqual(self.job(old)["status"], "superseded")
        self.assertEqual(prepared["base_observation_id"], bound["observation_id"])
        self.record("preflight", **self.page("已读且明确作为底本的云稿", "page_TEST_existing"))
        self.record("request_started")
        self.assertEqual(self.job()["status"], "requesting")

    def test_integer_revision_regression_and_same_revision_changes_rejected(self):
        saved = self.save(cloud=False)
        observation = self.page("revision二正文"); observation["revision"] = 2
        self.write("cloud.bind", artifact=self.ref(saved["artifact"]), user_request=self.user, observation=observation)
        for revision, content in ((1, "旧正文"), (2, "同版本不同正文")):
            observation = self.page(content); observation["revision"] = revision
            before = self.logical()
            with self.assertRaises(ConflictError): self.write("cloud.bind", artifact=self.ref(saved["artifact"]), user_request=self.user, observation=observation)
            self.assertEqual(before, self.logical())

    def test_null_and_opaque_do_not_erase_known_integer_watermark(self):
        saved = self.save(cloud=False)
        for revision, content in ((3, "三版"), (None, "无修订值的观察"), ("opaque-token", "不透明修订观察")):
            observation = self.page(content); observation["revision"] = revision
            self.write("cloud.bind", artifact=self.ref(saved["artifact"]), user_request=self.user, observation=observation)
        self.assertEqual(self.read()["documents"][0]["known_revision"], 3)
        observation = self.page("二版旧正文"); observation["revision"] = 2
        with self.assertRaises(ConflictError): self.write("cloud.bind", artifact=self.ref(saved["artifact"]), user_request=self.user, observation=observation)
        observation = self.page("不透明token内容变了"); observation["revision"] = "opaque-token"
        with self.assertRaises(ConflictError): self.write("cloud.bind", artifact=self.ref(saved["artifact"]), user_request=self.user, observation=observation)

    def test_preflight_cannot_relabel_old_revision_with_later_time(self):
        saved = self.save(); self.record("request_started"); self.created()
        observation = self.page(saved["artifact"]["content"]); observation["revision"] = 1
        self.record("verified", **observation)
        observation = self.page("用户改成revision2"); observation["revision"] = 2
        self.write("cloud.bind", artifact=self.ref(saved["artifact"]), user_request=self.user, observation=observation)
        self.save("本地下一版正文", trigger="confirmed_revision")
        observation = self.page(saved["artifact"]["content"]); observation["revision"] = 1
        with self.assertRaises(ConflictError): self.record("preflight", **observation)
        with self.assertRaises(ConflictError): self.record("request_started")


if __name__ == "__main__": unittest.main()

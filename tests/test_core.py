import json
import sqlite3
import tempfile
import unittest
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from filmprod.core import Registry, ConflictError, content_hash, now


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="filmprod-test-")
        self.base = Path(self.temp.name)
        self.root = self.base / "project"
        self.r = Registry(self.root)
        self.call("project.init", project_id="TEST", title="原创测试", test_only=True)

    def tearDown(self):
        self.r.close()
        self.temp.cleanup()

    def call(self, action, **p):
        p.setdefault("op_id", uuid.uuid4().hex)
        return self.r.dispatch(action, p)

    def save(self, aid, version=0, deps=None, kind="script", scope=None, **p):
        return self.call("artifact.save", artifact_id=aid, base_version=version,
                         content=p.pop("content", f"{aid}版本{version + 1}"),
                         kind=kind, scope=scope or aid, deps=deps or [], **p)

    def ref(self, aid, v=1):
        return {"artifact_id": aid, "version": v}

    def approve(self, aid, version=1):
        artifact = self.r._artifact(aid, version)
        return self.call("content.approve", artifact_id=aid, version=version, scope=artifact["scope"], evidence="合成测试批准", actor="test-runner", synthetic=True)

    def task(self, tid="T1", inputs=None, **p):
        return self.call("task.create", task_id=tid, title="任务", module=p.pop("module", "director"),
                         scope=p.pop("scope", "S03"), inputs=inputs or [], must_keep=["人物意图"],
                         allowed_changes=["调度"], requirements=["完整动作与对白"], **p)

    def test_cas_dedupe_and_transaction_rollback(self):
        result = self.save("S1", op_id="same")
        self.assertEqual(self.save("S1", op_id="same"), result)
        with self.assertRaises(ConflictError):
            self.save("S1", op_id="same", content="不同请求")
        with self.assertRaises(ConflictError):
            self.save("S1")
        with self.assertRaises(ValueError):
            self.save("bad", deps=[self.ref("missing")])
        self.assertIsNone(self.r._artifact("bad"))
        self.assertEqual(self.r._artifact("S1")["version"], 1)

    def test_parallel_cas_only_one_wins(self):
        self.save("S1")
        def write(index):
            other = Registry(self.root)
            try:
                other.dispatch("artifact.save", dict(op_id=f"writer-{index}", artifact_id="S1", kind="script", scope="S1", content=str(index), base_version=1))
                return True
            except ConflictError:
                return False
            finally:
                other.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(write, [1, 2])), 1)
        self.assertEqual(self.r._artifact("S1")["version"], 2)

    def test_precise_dependencies_and_immutable_history(self):
        for aid in ("S1", "S3"):
            self.save(aid)
            self.approve(aid)
        self.save("D1", deps=[self.ref("S1")], kind="director")
        self.approve("D1")
        self.save("D3", deps=[self.ref("S3")], kind="director")
        self.approve("D3")
        self.save("FX3", deps=[self.ref("D3")], kind="vfx")
        self.approve("FX3")
        self.save("P3", deps=[self.ref("FX3")], kind="prompt")
        self.approve("P3")
        self.save("M3", deps=[self.ref("S3")], kind="cue")
        self.approve("M3")
        self.save("SUB3", deps=[self.ref("S3")], kind="subtitle")
        self.approve("SUB3")
        before = self.r._artifact("S3", 1)
        changed = self.save("S3", 1)
        self.assertEqual(changed["invalidated"], [])
        changed = self.approve("S3", 2)
        self.assertEqual(set(changed["invalidated"]), {"D3", "FX3", "P3", "M3", "SUB3"})
        self.assertEqual(self.r._artifact("D1")["status"], "approved")
        self.assertEqual(self.r._artifact("S3", 1)["content"], before["content"])

    def test_historical_dependency_branch_not_confused_with_latest(self):
        self.save("S1")
        self.approve("S1")
        self.save("S3")
        self.approve("S3")
        self.save("D", deps=[self.ref("S1")], kind="director")
        self.approve("D")
        self.save("P1", deps=[self.ref("D")], kind="prompt")
        self.approve("P1")
        self.save("D", 1, deps=[self.ref("S3")], kind="director")
        self.approve("D", 2)
        self.save("P3", deps=[self.ref("D", 2)], kind="prompt")
        self.approve("P3")
        self.save("S3", 1)
        changed = self.approve("S3", 2)
        self.assertIn("P3", changed["invalidated"])
        self.assertNotIn("P1", changed["invalidated"])
        # Changing S1 must still reach P1 through historical D@1.
        self.save("S1", 1)
        changed = self.approve("S1", 2)
        self.assertIn("P1", changed["invalidated"])
        self.assertNotIn("D", changed["invalidated"])

    def test_resume_complete_draft_read_only_and_stale_submit(self):
        self.save("S3")
        self.task(inputs=[self.ref("S3")])
        draft = '对白：末班车还会来吗？\n动作：抬灯\n声音：门铃'
        self.call("task.checkpoint", task_id="T1", draft=draft, completed=["开场"], decisions=["候选低机位"], unresolved=["镜头长度"], next_step="补结尾")
        count = self.r.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        other = Registry(self.root)
        try:
            package = other.dispatch("task.resume", {"task_id": "T1"})
            self.assertEqual(package["checkpoint"]["draft"], draft)
            self.assertEqual(package["frozen_inputs"][0]["version"], 1)
            self.assertTrue(package["read_only"])
        finally:
            other.close()
        self.assertEqual(self.r.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], count)
        self.save("S3", 1)
        with self.assertRaises(ConflictError):
            self.call("task.submit", task_id="T1", artifact_id="D3", kind="director", content="草稿", base_version=0)
        self.assertIsNone(self.r._artifact("D3"))
        self.assertEqual(self.r._resume("T1")["checkpoint"]["draft"], draft)

    def test_editor_scope_is_module_aware(self):
        self.task()
        with self.assertRaises(ConflictError):
            self.task("T2")
        self.task("FX", module="vfx")
        self.save("S3", scope="S03")  # A director task does not lock the screenplay.
        with self.assertRaises(ConflictError):
            self.save("D3", kind="director", scope="S03")
        result = self.call("task.submit", task_id="T1", artifact_id="D3", kind="director", content="方案", base_version=0)
        self.assertEqual(result["task"]["status"], "submitted")

    def test_external_task_id_cannot_bypass_submit_or_editor_lock(self):
        self.save("S3")
        self.approve("S3")
        self.task(inputs=[self.ref("S3")])
        self.save("S3", 1)
        self.approve("S3", 2)
        with self.assertRaises(ConflictError):
            self.call("task.submit", task_id="T1", artifact_id="D3", kind="director", content="旧输入", base_version=0)
        for payload in ({"task_id": "T1"}, {"task_id": "T1", "trusted_task": {"task_id": "T1"}}, {}):
            with self.subTest(payload=payload), self.assertRaises(ConflictError):
                self.save("D3", kind="director", scope="S03", deps=[], **payload)
        self.assertIsNone(self.r._artifact("D3"))
        self.assertEqual(self.r._resume("T1")["task"]["status"], "needs_review")

    def test_task_submit_enforces_module_and_target_binding(self):
        self.task(artifact_id="D-EXPECTED")
        for aid, kind in (("UNRELATED", "director"), ("D-EXPECTED", "script")):
            with self.subTest(aid=aid, kind=kind), self.assertRaises(ConflictError):
                self.call("task.submit", task_id="T1", artifact_id=aid, kind=kind, content="错误目标", base_version=0)
        result = self.call("task.submit", task_id="T1", artifact_id="D-EXPECTED", kind="director", content="正确目标", base_version=0)
        self.assertEqual(result["task"]["output"]["artifact_id"], "D-EXPECTED")

    def test_checkpoint_and_task_array_fields_reject_type_drift(self):
        for field in ("must_keep", "allowed_changes", "requirements"):
            payload = dict(task_id="BAD", title="错误类型", module="director", scope="S03", inputs=[], must_keep=[], allowed_changes=[], requirements=[])
            payload[field] = '["不能存成JSON字符串"]'
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.call("task.create", **payload)
        self.task()
        valid = dict(task_id="T1", draft="完整草稿", completed=["已完成"], decisions=[{"status": "candidate"}], unresolved=[], next_step="继续")
        for field in ("completed", "decisions", "unresolved", "draft", "next_step"):
            payload = dict(valid)
            payload[field] = '[]' if field not in ("draft", "next_step") else {"not": "text"}
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.call("task.checkpoint", **payload)
        self.assertEqual(self.r._resume("T1")["task"]["checkpoints"], [])
        self.call("task.checkpoint", **valid)

    def test_synthetic_decision_seals_exact_content(self):
        self.save("S3")
        args = dict(artifact_id="S3", version=1, scope="第三场对白", decision="adopt", evidence="开发自测", actor="test-runner")
        decision = self.call("decision.record", **args, synthetic=True)
        self.save("S3", 1)
        self.assertEqual(decision["sealed_content"], "S3版本1")
        self.assertEqual(decision["sealed_sha256"], content_hash("S3版本1"))
        with self.assertRaises(ValueError):
            self.call("decision.record", **dict(args, actor="human"), synthetic=False, user_authorization="伪造通过")
        self.assertEqual(len(self.r.snapshot()["decisions"]), 1)

    def test_unknown_sync_readback_and_conflict_preserve_intent(self):
        self.call("sync.intent", sync_id="X", page_id="P", base_revision="rev1", intended_content="第三场新稿")
        self.call("sync.observe", sync_id="X", status="unknown")
        with self.assertRaises(ConflictError):
            self.call("sync.intent", sync_id="X2", page_id="P", base_revision="rev1", intended_content="重复写入")
        with self.assertRaises(ConflictError):
            self.call("sync.observe", sync_id="X", status="sent")
        observed_at = now()
        data = self.call("sync.observe", sync_id="X", status="verified", observed_content="第三场新稿", revision="rev2", receipt={"tool": "read_page"}, observed_at=observed_at)
        self.assertEqual(data["status"], "verified")
        self.assertEqual(data["last_observed_at"], observed_at)
        self.assertIn("recorded_at", data["observations"][-1])
        self.call("sync.intent", sync_id="Y", page_id="P", base_revision="rev2", intended_content="待写入")
        data = self.call("sync.observe", sync_id="Y", status="verified", observed_content="其他编辑者新稿", revision="rev3")
        self.assertEqual(data["status"], "conflict")
        self.assertEqual(data["intended_content"], "待写入")
        self.assertEqual(data["observed_content"], "其他编辑者新稿")

    def media_fixture(self):
        original = self.base / "TEST_ONLY.bin"
        original.write_bytes(b"TEST_ONLY_MEDIA\x00\x01")
        return self.call("media.register", media_id="V1", kind="video", path=str(original), metadata={"duration_seconds": 5, "test_only": True})

    def timeline_fixture(self):
        self.media_fixture()
        self.save("TC", kind="clip", metadata=dict(source_media_id="V1", in_seconds=0, out_seconds=4))
        self.save("TIMELINE", kind="timeline", deps=[self.ref("TC")], metadata={"clips": [dict(self.ref("TC"), timeline_in_seconds=0)]})

    def test_media_duration_exact_sequence_and_final(self):
        media = self.media_fixture()
        self.assertIsNone(media["metadata"]["stems"])
        self.assertIsNone(media["metadata"]["rights_status"])
        with self.assertRaises(ValueError):
            self.save("bad", kind="clip", metadata=dict(source_media_id="V1", in_seconds=1, out_seconds=6))
        self.save("C", kind="clip", metadata=dict(source_media_id="V1", in_seconds=1, out_seconds=4))
        with self.assertRaises(ValueError):
            self.save("SEQ", kind="sequence", metadata=dict(clips=[dict(self.ref("C"), timeline_in_seconds=0)]))
        self.save("SEQ", kind="sequence", deps=[self.ref("C")], metadata=dict(clips=[dict(self.ref("C"), timeline_in_seconds=0)]))
        self.save("FINAL", kind="final", deps=[self.ref("SEQ"), self.ref("C")], metadata=dict(timeline=self.ref("SEQ"), shots=[self.ref("C")], music=[], dialogue=[], subtitles=[], export_spec={"width": 1920, "height": 1080, "fps": 24}))
        self.assertEqual(self.r._artifact("FINAL")["status"], "candidate")

    def test_final_rejects_research_tracks_and_invalid_export_spec(self):
        self.timeline_fixture()
        self.save("R", kind="research")
        for field in ("shots", "music", "dialogue", "subtitles"):
            metadata = dict(timeline=self.ref("TIMELINE"), shots=[], music=[], dialogue=[], subtitles=[], export_spec=dict(width=640, height=360, fps=24))
            metadata[field] = [self.ref("R")]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.save("BAD", kind="final", deps=[self.ref("TIMELINE"), self.ref("R")], metadata=metadata)
        for spec in ({"fps": -24}, {"width": 640, "height": 360, "fps": -24}, {"width": 0, "height": 360, "fps": 24}, {"width": True, "height": 360, "fps": 24}, {"width": 640, "height": 360, "fps": 0}):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                self.save("BAD", kind="final", deps=[self.ref("TIMELINE")], metadata=dict(timeline=self.ref("TIMELINE"), shots=[], music=[], dialogue=[], subtitles=[], export_spec=spec))
        self.assertIsNone(self.r._artifact("BAD"))

    def test_final_music_requires_actual_audio_or_explicit_plan(self):
        self.timeline_fixture()
        self.save("CUE", kind="cue")
        base = dict(timeline=self.ref("TIMELINE"), shots=[], music=[], dialogue=[], subtitles=[], export_spec=dict(width=640, height=360, fps=24))
        with self.assertRaises(ValueError):
            self.save("BAD", kind="final", deps=[self.ref("TIMELINE"), self.ref("CUE")], metadata=dict(base, music=[self.ref("CUE")]))
        with self.assertRaises(ValueError):
            self.save("BAD", kind="final", deps=[self.ref("TIMELINE"), self.ref("CUE")], metadata=dict(base, planned_music=[self.ref("CUE")]))
        self.save("PLAN", kind="final", deps=[self.ref("TIMELINE"), self.ref("CUE")], metadata=dict(base, planned_music=[self.ref("CUE")], assembly_status="planned", render_status="not_rendered"))
        audio_path = self.base / "TEST_ONLY_AUDIO.bin"
        audio_path.write_bytes(b"TEST_ONLY_AUDIO")
        self.call("media.register", media_id="AUDIO", kind="audio", path=str(audio_path), metadata={})
        self.save("MUSIC", kind="music", metadata={"source_media_id": "AUDIO"})
        self.save("ACTUAL", kind="final", deps=[self.ref("TIMELINE"), self.ref("MUSIC")], metadata=dict(base, music=[self.ref("MUSIC")]))
        self.assertEqual(self.r._artifact("ACTUAL")["metadata"]["music"], [self.ref("MUSIC")])

    def test_timeline_alias_requires_exact_clip_structure(self):
        with self.assertRaises(ValueError):
            self.save("BAD_TIMELINE", kind="timeline", metadata={})
        self.assertIsNone(self.r._artifact("BAD_TIMELINE"))
        self.timeline_fixture()
        # Simulate a historical revision saved by the earlier permissive build.
        self.r.db.execute("UPDATE artifacts SET metadata='{}' WHERE artifact_id='TIMELINE'")
        with self.assertRaises(ValueError):
            self.save("BAD_FINAL", kind="final", deps=[self.ref("TIMELINE")], metadata=dict(timeline=self.ref("TIMELINE"), shots=[], music=[], dialogue=[], subtitles=[], export_spec=dict(width=640, height=360, fps=24)))
        self.assertIsNone(self.r._artifact("BAD_FINAL"))

    def test_duplicate_media_has_one_original(self):
        first = self.media_fixture()
        second = self.call("media.register", media_id="V2", kind="video", path=first["source_path"], metadata={})
        self.assertEqual(first["path"], second["path"])
        self.assertEqual(len(list((self.root / "05-片段/视频原件").iterdir())), 1)

    def test_backup_restore_content_and_media_hashes(self):
        self.save("S3")
        media = self.media_fixture()
        archive = self.base / "backup.zip"
        result = self.call("backup.create", destination=str(archive), op_id="B")
        self.assertEqual(self.call("backup.create", destination=str(archive), op_id="B"), result)
        restored = self.base / "restored"
        result = self.call("backup.restore", source=str(archive), destination=str(restored), op_id="R")
        self.assertTrue(result["verified"])
        clone = Registry(restored)
        try:
            self.assertEqual(clone._artifact("S3")["content"], "S3版本1")
            self.assertEqual((restored / media["path"]).read_bytes(), (self.root / media["path"]).read_bytes())
        finally:
            clone.close()
        with self.assertRaises(ConflictError):
            self.call("backup.restore", source=str(archive), destination=str(restored))

    def test_unsafe_archive_rejected_before_writing(self):
        archive = self.base / "evil.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("../escape", "attack")
        destination = self.base / "must-not-exist"
        with self.assertRaises(ValueError):
            self.call("backup.restore", source=str(archive), destination=str(destination))
        self.assertFalse(destination.exists())
        self.assertFalse((self.base / "escape").exists())

    def test_only_one_current_control_thread(self):
        for thread_id in ("one", "two"):
            self.call("thread.register", thread_id=thread_id, title=thread_id, scope="project", status="active", current_control=True)
        active = [t for t in self.r.snapshot()["threads"] if t["current_control"]]
        self.assertEqual([t["thread_id"] for t in active], ["two"])


if __name__ == "__main__":
    unittest.main()

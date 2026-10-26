"""Isolated feedback protocol tests. Every creative decision is synthetic."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from filmprod.core import Registry, ConflictError
from filmprod.screenwriting1130 import action_schemas


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="film-screenwriter-TEST-")
        self.root = Path(self.temp.name) / "TEST-only"
        self.r = Registry(self.root)
        self.call("project.init", project_id="TEST-WRITER", title="编剧合成测试", test_only=True)
        self.first = self.save("S01 内 厨房 日\n阿禾拿起水杯。\n阿禾：你先坐下。")

    def tearDown(self):
        self.r.close(); self.temp.cleanup()

    def call(self, action, **payload):
        payload.setdefault("op_id", uuid.uuid4().hex)
        if action != "project.init": payload.setdefault("expected_project_id", "TEST-WRITER")
        return self.r.dispatch(action, payload)

    def read(self, **payload):
        return self.r.dispatch("screenwriting.read", {"expected_project_id": "TEST-WRITER", **payload})

    def write(self, action, **payload):
        payload.setdefault("base_revision", self.read()["revision"])
        return self.call(action, **payload)

    def ref(self, item):
        return {key: item[key] for key in ("artifact_id", "version", "sha256")}

    def save(self, body, aid="SCRIPT", scope="episode/1", kind="script"):
        prior = self.r._artifact(aid)
        return self.call("artifact.save", artifact_id=aid, kind=kind, scope=scope, content=body,
                         base_version=prior["version"] if prior else 0,
                         metadata={"workflow_stage": "dynamic_script"} if kind == "script" else {})["artifact"]

    def request(self, **extra):
        return dict(feedback_id="F01", script=self.ref(self.first), scope="episode/1", scene_id="S01",
                    anchor="阿禾拿起水杯。", problem="动作未回应客人的迟疑", expected_effect="让动作体现邀请",
                    must_keep=["客人暂不说出秘密"], impact="expression", source={"role": "director", "reference": "TEST-director-turn"}, **extra)

    def record(self, **extra):
        args = self.request(); args.update(extra)
        return self.write("screenwriting.record", **args)

    def resolve(self, **extra):
        args = dict(feedback_id="F01", status="addressed", response="先递杯，再留出座位。")
        args.update(extra)
        return self.write("screenwriting.resolve", **args)

    def changed(self):
        return self.save("S01 内 厨房 日\n阿禾把水杯递到客人面前，挪开椅上的围裙。\n阿禾：你先坐下。")

    def decision(self):
        return dict(source="conversation", reference="TEST-human-turn", quote="同意按这个改变结局，先出候选。", scope="episode/1",
                    feedback_id="F01", script=self.ref(self.first), actor="human", synthetic=True)

    def logical(self):
        return {table: [tuple(row) for row in self.r.db.execute("SELECT * FROM " + table)] for table in
                ("settings", "artifacts", "tasks", "operations", "events", "decisions", "master_revisions")}

    def test_read_is_nonmutating_and_snapshot_has_no_inferred_route(self):
        self.assertEqual(self.read()["feedbacks"], [])
        self.assertEqual(self.r.snapshot()["workflow"]["mode"], "unset")
        self.r.close(); before = (self.root / ".project/registry.sqlite3").read_bytes()
        self.r = Registry.open_readonly(self.root)
        self.assertEqual(self.r.snapshot()["screenwriting"], self.read())
        self.assertEqual(before, (self.root / ".project/registry.sqlite3").read_bytes())

    def test_record_and_resolve_do_not_write_script_approve_or_sync(self):
        old_artifacts = self.logical()["artifacts"]
        self.record()
        self.assertEqual(old_artifacts, self.logical()["artifacts"])
        revised = self.changed(); before_resolve = self.logical()["artifacts"]
        result = self.resolve(revised_script=self.ref(revised))
        self.assertFalse(result["automatic_approval"])
        self.assertFalse(result["script_edited"])
        self.assertEqual(before_resolve, self.logical()["artifacts"])
        snapshot = self.r.snapshot()
        self.assertEqual(snapshot["approved_artifacts"], [])
        self.assertEqual(snapshot["cloud"]["jobs"], [])
        self.assertEqual(snapshot["tasks"], [])
        self.assertEqual(snapshot["decisions"], [])
        self.assertEqual(result["feedback"]["semantic_review"], "not_assessed")

    def test_identity_checked_even_for_cached_write(self):
        p = dict(self.request(), op_id="same", expected_project_id="TEST-WRITER", base_revision=0)
        self.r.dispatch("screenwriting.record", p)
        with self.assertRaises(ConflictError):
            self.r.dispatch("screenwriting.record", {**p, "expected_project_id": "OTHER"})

    def test_idempotent_replay_returns_original_receipt_and_no_duplicate(self):
        first = self.record(op_id="record-once", base_revision=0)
        self.resolve(status="deferred", response="先保留")
        again = self.record(op_id="record-once", base_revision=0)
        self.assertEqual(first, again)
        self.assertEqual(len(self.read()["feedbacks"]), 1)
        self.assertEqual(self.read()["feedbacks"][0]["status"], "deferred")
        with self.assertRaises(ConflictError):
            self.record(op_id="record-once", base_revision=0, problem="更换请求内容")

    def test_stale_revision_and_duplicate_id_rejected_without_changes(self):
        self.record(); before = self.logical()
        for args in (dict(base_revision=0, feedback_id="F02"), dict(feedback_id="F01")):
            with self.assertRaises(ConflictError): self.record(**args)
        self.assertEqual(before, self.logical())

    def test_wrong_hash_non_script_wrong_scope_and_missing_anchor_rejected(self):
        novel = self.save("阿禾拿起水杯。", aid="N", kind="novel")
        before = self.logical()
        for args in (dict(script={**self.ref(self.first), "sha256": "0"*64}), dict(script=self.ref(novel)),
                     dict(scope="episode/2"), dict(anchor="未出现在原文中的话")):
            with self.assertRaises(ValueError): self.record(**args)
        self.assertEqual(before, self.logical())

    def test_old_source_does_not_gain_new_anchor_or_silently_rebind(self):
        changed = self.changed()
        with self.assertRaises(ConflictError): self.record(anchor="挪开椅上的围裙")
        row = self.record()["feedback"]
        self.assertTrue(row["source_changed"])
        self.assertEqual(row["script"], self.ref(self.first))
        self.assertEqual(row["latest_script"], self.ref(changed))

    def test_body_revision_requires_new_current_same_identity_scope_and_hash(self):
        self.record()
        other = self.save("其他剧本", aid="OTHER", scope="episode/2")
        latest = self.changed()
        invalid = [None, self.ref(self.first), self.ref(other), {**self.ref(latest), "sha256": "0"*64}]
        for reference in invalid:
            with self.assertRaises(ValueError):
                self.resolve(**({"revised_script": reference} if reference else {}))
        next_version = self.save(latest["content"] + "\n客人坐下。")
        with self.assertRaises(ConflictError): self.resolve(revised_script=self.ref(latest))
        self.resolve(revised_script=self.ref(next_version))

    def test_copy_with_identical_text_is_not_completed_body_revision(self):
        self.record(); copy = self.save(self.first["content"])
        with self.assertRaises(ConflictError): self.resolve(revised_script=self.ref(copy))

    def test_major_initially_waits_for_choice_and_requires_exact_user_evidence(self):
        self.record(impact="major")
        self.assertEqual(self.read()["feedbacks"][0]["status"], "needs_user_choice")
        revised = self.changed()
        with self.assertRaises(ValueError): self.resolve(revised_script=self.ref(revised))
        for changed in (dict(synthetic=False), dict(scope="episode/2"), dict(feedback_id="OTHER"), dict(actor="director"),
                        dict(script=self.ref(revised)), dict(quote=" ")):
            with self.assertRaises(ValueError): self.resolve(revised_script=self.ref(revised), user_decision={**self.decision(), **changed})
        result = self.resolve(revised_script=self.ref(revised), user_decision=self.decision())
        self.assertEqual(result["feedback"]["user_decision"], self.decision())
        self.assertEqual(self.r.snapshot()["approved_artifacts"], [])

    def test_staging_can_resolve_without_editing_script_and_deferred_cannot_link_revision(self):
        self.record(impact="staging"); self.resolve(response="只调整镜头切点，保留全部对白。")
        self.assertEqual(len(self.r.dispatch("artifact.history", {"artifact_id": "SCRIPT"})["versions"]), 1)
        newer = self.changed()
        with self.assertRaises(ValueError): self.resolve(status="deferred", revised_script=self.ref(newer))

    def test_history_reopen_and_freshness_are_separate_from_resolution(self):
        self.record(); self.resolve(status="deferred", response="等待新版")
        new = self.changed(); self.resolve(status="partially_addressed", revised_script=self.ref(new))
        self.save(new["content"] + "\n窗外响了一声。")
        self.r.close(); self.r = Registry(self.root)
        row = self.read(feedback_id="F01")["feedbacks"][0]
        self.assertTrue(row["revision_changed"])
        self.assertEqual(row["status"], "partially_addressed")
        self.assertEqual(len(row["history"]), 2)
        with self.assertRaises(ValueError): self.read(artifact_id="OTHER", feedback_id="F01")

    def test_strict_schema_and_unknown_operation_do_not_write(self):
        before = self.logical()
        for args in (dict(base_revision=True), dict(problem=""), dict(must_keep=[None]), dict(impact="automatic"), dict(extra="unexpected")):
            with self.assertRaises(ValueError): self.record(**args)
        with self.assertRaises(ValueError): self.r.dispatch("screenwriting.delete", {})
        self.assertEqual(before, self.logical())

    def test_concurrent_record_uses_compare_and_swap(self):
        other = Registry(self.root)
        def create(index, registry):
            try:
                registry.dispatch("screenwriting.record", {**self.request(), "feedback_id": "F"+str(index),
                    "op_id": "race"+str(index), "expected_project_id": "TEST-WRITER", "base_revision": 0})
                return "saved"
            except ConflictError: return "conflict"
        try:
            with ThreadPoolExecutor(2) as executor:
                results = list(executor.map(lambda args: create(*args), ((1, self.r), (2, other))))
            self.assertCountEqual(results, ["saved", "conflict"])
            self.assertEqual(len(self.read()["feedbacks"]), 1)
        finally: other.close()

    def test_mcp_schema_readonly_help_and_write_roundtrip(self):
        source = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("writer_mcp_test", source / "plugin/mcp_server.py")
        server = importlib.util.module_from_spec(spec); spec.loader.exec_module(server)
        args = {"root": str(self.root), "action": "record", "payload": {**self.request(), "op_id": "mcp", "expected_project_id": "TEST-WRITER", "base_revision": 0}}
        saved = server.call_tool("film_screenwriting", args, None)["structuredContent"]
        self.assertEqual(saved["feedback"]["feedback_id"], "F01")
        with patch.object(Registry, "__init__", side_effect=AssertionError("read opened writable registry")):
            read = server.call_tool("film_screenwriting", {"root": str(self.root), "action": "read", "payload": {"expected_project_id": "TEST-WRITER"}}, None)
            legacy = server.call_tool("film_dispatch", {"root": str(self.root), "action": "screenwriting.read", "payload": {"expected_project_id": "TEST-WRITER"}}, None)
        self.assertEqual(read["structuredContent"]["feedbacks"], legacy["structuredContent"]["feedbacks"])
        help_result = server.call_tool("film_action_help", {"action": "screenwriting.record"}, None)["structuredContent"]
        self.assertEqual(help_result["inputSchema"], action_schemas()["screenwriting.record"])
        with patch.object(server, "checked_project_root", side_effect=AssertionError("invalid request touched project")):
            bad = deepcopy(args); bad["payload"]["base_revision"] = True
            with self.assertRaises(ValueError): server.call_tool("film_screenwriting", bad, None)


if __name__ == "__main__": unittest.main()

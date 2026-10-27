"""Synthetic conversation lifecycle tests; no host, cloud, or real project calls."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import uuid

from filmprod.core import ConflictError, Registry
from filmprod.conversations1170 import action_schemas, conversation_view, validate_conversation_payload


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="film-conversations-TEST-")
        self.r = Registry(Path(self.temp.name) / "synthetic")
        self.r.dispatch("project.init", {"op_id": uuid.uuid4().hex, "project_id": "TEST-CONVERSATIONS",
            "title": "Synthetic conversations", "test_only": True})
        self.call("project.workflow.set", mode="screenplay", base_revision=0)
        self.call("workspace.prepare", base_revision=0)
        for role in ("control", "planning", "script", "art", "director", "assets", "review"):
            self.workspace_observe(role, "request_started")
            self.workspace_observe(role, "host_confirmed", thread_id="TEST-" + role, title=role, origin="created")
            self.workspace_observe(role, "catalog_bound", tool="film_projects", thread_id="TEST-" + role, project_id="TEST-CONVERSATIONS")
            self.workspace_observe(role, "client_project_observed", tool="list_threads", thread_id="TEST-" + role, client_project_id="TEST-CLIENT")
        self.auth = {"quote": "TEST 用户明确授权本项目专题、交接、任务与回报", "reference": "TEST/user-message",
            "actions": ["configure", "prepare", "decide", "accept", "bind_task", "complete", "start", "continue",
                        "create_thread", "send_message_to_thread", "archive"],
            "target": {"project_id": "TEST-CONVERSATIONS", "scopes": ["*"], "thread_ids": ["*"]}, "synthetic": True}

    def tearDown(self):
        self.r.close()
        self.temp.cleanup()

    def call(self, action, **payload):
        payload.setdefault("op_id", uuid.uuid4().hex)
        payload.setdefault("expected_project_id", "TEST-CONVERSATIONS")
        if action.startswith("conversation."):
            payload.setdefault("base_revision", self.read()["revision"])
        return self.r.dispatch(action, payload)

    def read(self):
        return self.r.dispatch("conversation.read", {"expected_project_id": "TEST-CONVERSATIONS"})

    def workspace_observe(self, role, event, **extra):
        view = self.r.dispatch("workspace.read", {"expected_project_id": "TEST-CONVERSATIONS"})
        slot = next(s for s in view["slots"] if s["role"] == role)
        obs = {"request_id": slot["request_id"], **extra}
        if event != "request_started":
            obs = {"source": "host_tool", "observed_at": "2026-10-27T09:00:00+08:00", "tool": "create_thread", **obs}
        return self.call("workspace.record", base_revision=view["revision"], slot_id=slot["slot_id"], event=event, observation=obs)

    def enable(self, authorization=None):
        return self.call("conversation.configure", actor_thread_id="TEST-control", enabled=True, authorization=authorization or self.auth)

    def planning(self, version=0):
        change = {"record_kind": "idea", "title": "TEST 灵感", "state": {"branches": [{"id": "branch-a", "title": "A"}]}}
        if version:
            change = {"append": {"branches": [{"id": "branch-b", "title": "B"}]}}
        saved = self.call("planning.record", record_id="TEST-IDEA", scope="idea/test", base_version=version, change=change)
        return saved["artifact_ref"]

    def idea(self):
        return self.call("conversation.prepare", actor_thread_id="TEST-planning", topic_id="TEST-TOPIC",
            kind="idea", title="TEST 专题", scope="idea/test", planning_ref=self.planning())

    def direct(self):
        return self.call("conversation.prepare", actor_thread_id="TEST-script", topic_id="TEST-EXEC", kind="execution",
            title="TEST 执行", scope="script/test", target_artifact_id="TEST-SCRIPT", target_role="script",
            direct_brief="直接写出完整一场剧本，无需先建灵感记录。", inputs=[])

    def observe(self, request_id, status, **extra):
        request = next(r for r in self.read()["outbox"] if r["request_id"] == request_id)
        tool = {"archive": "set_thread_archived"}.get(request["tool"], request["tool"])
        observation = {"source": "host_tool", "tool": tool, "observed_at": "2026-10-27T09:00:00+08:00",
            "reference": "TEST/receipt", "project_id": "TEST-CONVERSATIONS", "topic_id": request["topic_id"],
            "scope": request["scope"], "request_id": request_id, "attempt": request["attempt"], **extra}
        if status == "host_accepted":
            observation = {"title": "真实TEST标题", "client_project_id": "TEST-CLIENT", "project_root": str(self.r.root), **observation}
        return self.call("conversation.observe", request_id=request_id, status=status, observation=observation)

    def created(self, preparation, thread_id):
        rid = preparation["request"]["request_id"]
        self.call("conversation.claim", request_id=rid)
        self.observe(rid, "host_accepted", thread_id=thread_id)
        return thread_id

    def task(self, task_id="TEST-TASK"):
        return self.call("task.create", task_id=task_id, title="TEST 剧本任务", module="screenplay", scope="script/test",
            thread_id="TEST-execution-child", artifact_id="TEST-SCRIPT", inputs=[], must_keep=[], allowed_changes=["完整候选"], requirements=["完整一场"])

    def submitted(self, task_id="TEST-TASK", base_version=0):
        result = self.call("task.submit", task_id=task_id, artifact_id="TEST-SCRIPT", kind="script", base_version=base_version,
                           content="第一场：室内。甲推开门，说：今天我们从这里开始。", metadata={"category": "script"})
        return result["task"]["output"]

    def test_read_does_not_enable_or_initialize_settings(self):
        before = list(self.r.db.execute("SELECT * FROM settings ORDER BY key"))
        self.assertFalse(self.read()["enabled"])
        self.assertEqual(conversation_view(self.r)["topics"], [])
        self.assertEqual(before, list(self.r.db.execute("SELECT * FROM settings ORDER BY key")))
        self.assertFalse(self.r.db.execute("SELECT 1 FROM settings WHERE key='conversation/v1'").fetchone())

    def test_configure_requires_observed_parent_identity_and_test_evidence(self):
        with self.assertRaises(ConflictError):
            self.call("conversation.configure", actor_thread_id="TEST-planning", enabled=True, authorization=self.auth)
        bad = deepcopy(self.auth)
        bad["synthetic"] = False
        with self.assertRaisesRegex(ValueError, "synthetic"):
            self.enable(bad)
        bad["synthetic"] = True
        bad["target"]["project_id"] = "ANOTHER"
        with self.assertRaises(ValueError):
            self.enable(bad)
        self.assertFalse(self.read()["enabled"])

    def test_one_idea_prepares_one_chat_no_role_expansion(self):
        self.enable()
        slots = self.r.dispatch("workspace.read", {"expected_project_id": "TEST-CONVERSATIONS"})["slots"]
        result = self.idea()
        self.assertEqual(len(result["topics"]), 1)
        self.assertEqual(len(result["pending_host_actions"]), 1)
        self.assertEqual(slots, self.r.dispatch("workspace.read", {"expected_project_id": "TEST-CONVERSATIONS"})["slots"])
        self.assertEqual(len(self.r._list("threads")), 7)
        self.assertFalse(result["dispatch_allowed"])
        self.assertIn("等待", result["request"]["payload"]["instructions"])

    def test_claim_replay_unknown_and_queued_never_dispatch_again(self):
        self.enable()
        request = self.idea()["request"]["request_id"]
        base = self.read()["revision"]
        payload = {"request_id": request, "base_revision": base, "op_id": "claim-once"}
        self.assertTrue(self.call("conversation.claim", **payload)["dispatch_allowed"])
        self.assertFalse(self.call("conversation.claim", **payload)["dispatch_allowed"])
        self.assertFalse(self.call("conversation.claim", request_id=request)["dispatch_allowed"])
        self.observe(request, "queued", client_thread_id="client-only")
        with self.assertRaisesRegex(ValueError, "clientThreadId"):
            self.observe(request, "host_accepted", thread_id="client-only")
        self.observe(request, "unknown", reason="超时待核")
        self.assertFalse(self.call("conversation.claim", request_id=request)["dispatch_allowed"])
        self.observe(request, "host_accepted", thread_id="TEST-topic-child")
        self.assertEqual(self.read()["topics"][0]["thread_id"], "TEST-topic-child")

    def test_failed_retry_requires_no_effect_and_same_request(self):
        self.enable()
        request = self.idea()["request"]["request_id"]
        self.call("conversation.claim", request_id=request)
        self.observe(request, "failed", no_effect=False, proof="unknown", reason="无可靠回执")
        self.assertFalse(self.call("conversation.claim", request_id=request, retry_failed=True)["dispatch_allowed"])
        self.observe(request, "failed", no_effect=True, proof="TEST明确未创建回执", reason="宿主拒绝创建")
        with self.assertRaises(ConflictError):
            self.call("conversation.claim", request_id=request)
        retried = self.call("conversation.claim", request_id=request, retry_failed=True)
        self.assertTrue(retried["dispatch_allowed"])
        self.assertEqual(retried["request"]["request_id"], request)
        self.assertEqual(retried["request"]["attempt"], 2)

    def test_decision_uses_new_exact_planning_version_and_unique_handoff(self):
        self.enable()
        self.created(self.idea(), "TEST-topic-child")
        new_ref = self.planning(version=1)
        result = self.call("conversation.decide", actor_thread_id="TEST-planning", topic_id="TEST-TOPIC", decision="develop",
            reason="用户选择B做剧本", planning_ref=new_ref, branch_id="branch-b", target_role="script")
        self.assertEqual(result["handoff"]["source_ref"]["version"], 2)
        self.assertEqual(result["topic"]["source_history"][0]["version"], 1)
        handoff_id = result["handoff"]["handoff_id"]
        again = self.call("conversation.decide", actor_thread_id="TEST-planning", topic_id="TEST-TOPIC", decision="develop",
            reason="重复读取同交接", planning_ref=new_ref, branch_id="branch-b", target_role="script")
        self.assertEqual(again["handoff"]["handoff_id"], handoff_id)
        self.assertEqual(len(self.read()["handoffs"]), 1)
        self.call("conversation.accept", actor_thread_id="TEST-script", handoff_id=handoff_id, status="ready",
                  brief="已明确写第一场，无需重复问题", inputs=[new_ref])
        self.assertEqual(self.read()["handoffs"][0]["status"], "ready")

    def test_host_delivery_does_not_accept_handoff_or_prove_execution(self):
        self.enable()
        self.created(self.idea(), "TEST-topic-child")
        result = self.call("conversation.decide", actor_thread_id="TEST-planning", topic_id="TEST-TOPIC", decision="develop",
                           reason="明确转作", branch_id="branch-a", target_role="script")
        request = result["request"]["request_id"]
        self.call("conversation.claim", request_id=request)
        self.observe(request, "host_accepted", thread_id="TEST-script")
        self.assertEqual(self.read()["handoffs"][0]["status"], "offered")
        self.assertEqual(self.r._list("tasks"), [])

    def test_route_mismatch_clarifies_and_preserves_route(self):
        self.enable()
        self.idea()
        handoff = self.call("conversation.decide", actor_thread_id="TEST-planning", topic_id="TEST-TOPIC", decision="develop",
                            reason="希望小说形式", branch_id="branch-a", target_role="novel")["handoff"]
        with self.assertRaises(ConflictError):
            self.call("conversation.accept", actor_thread_id="TEST-script", handoff_id=handoff["handoff_id"], status="ready",
                      brief="ready", inputs=[handoff["source_ref"]])
        self.call("conversation.accept", actor_thread_id="TEST-script", handoff_id=handoff["handoff_id"], status="clarifying",
                  questions=["请明确小说分支与既有项目路线如何衔接。"])
        self.assertEqual(self.r._project()["workflow"]["mode"], "screenplay")

    def test_recycle_restore_cancel_unclaimed_archive_but_not_unknown(self):
        self.enable()
        self.created(self.idea(), "TEST-topic-child")
        recycled = self.call("conversation.decide", actor_thread_id="TEST-planning", topic_id="TEST-TOPIC", decision="recycle",
                             reason="暂不继续", archive_chat=True)
        request = recycled["request"]["request_id"]
        self.call("conversation.decide", actor_thread_id="TEST-planning", topic_id="TEST-TOPIC", decision="restore",
                  reason="恢复讨论", archive_chat=True)
        self.assertEqual(next(r for r in self.read()["outbox"] if r["request_id"] == request)["status"], "cancelled")
        self.assertFalse(self.call("conversation.claim", request_id=request)["dispatch_allowed"])
        recycled = self.call("conversation.decide", actor_thread_id="TEST-planning", topic_id="TEST-TOPIC", decision="recycle",
                             reason="再次搁置", archive_chat=True)
        request = recycled["request"]["request_id"]
        self.call("conversation.claim", request_id=request)
        self.observe(request, "unknown", reason="原归档结果待核")
        with self.assertRaises(ConflictError):
            self.call("conversation.decide", actor_thread_id="TEST-planning", topic_id="TEST-TOPIC", decision="restore",
                      reason="需核查", archive_chat=True)
        self.assertEqual(self.read()["topics"][0]["status"], "recycled")

    def test_execution_bind_start_complete_and_same_chat_next_round(self):
        self.enable()
        self.created(self.direct(), "TEST-execution-child")
        with self.assertRaises(ConflictError):
            self.call("conversation.start", actor_thread_id="TEST-script", topic_id="TEST-EXEC")
        self.task()
        self.call("conversation.bind_task", actor_thread_id="TEST-script", topic_id="TEST-EXEC", task_id="TEST-TASK")
        started = self.call("conversation.start", actor_thread_id="TEST-script", topic_id="TEST-EXEC")
        self.assertEqual(started["request"]["payload"]["task_id"], "TEST-TASK")
        self.assertEqual(self.read()["topics"][0]["status"], "task_bound")
        with self.assertRaises(ConflictError):
            self.call("conversation.continue", actor_thread_id="TEST-script", topic_id="TEST-EXEC", brief="新轮", inputs=[])
        output = self.submitted()
        done = self.call("conversation.complete", actor_thread_id="TEST-execution-child", topic_id="TEST-EXEC", task_id="TEST-TASK",
                         output_ref=output, summary="已提交完整候选")
        self.assertFalse(done["notification_sent"])
        self.assertEqual(len(done["requests"]), 2)
        self.assertEqual(self.r._list("decisions"), [])
        previous_task = deepcopy(self.r._get("tasks", "task_id", "TEST-TASK"))
        continued = self.call("conversation.continue", actor_thread_id="TEST-script", topic_id="TEST-EXEC", brief="同聊天第二轮明确修订", inputs=[])
        self.assertFalse(continued["new_chat_created"])
        self.assertEqual(continued["topic"]["round"], 2)
        self.assertEqual(continued["topic"]["task_history"][0]["output_ref"], output)
        self.task("TEST-TASK-2")
        self.call("conversation.bind_task", actor_thread_id="TEST-script", topic_id="TEST-EXEC", task_id="TEST-TASK-2")
        newer_start = self.call("conversation.start", actor_thread_id="TEST-script", topic_id="TEST-EXEC")
        self.assertNotEqual(started["request"]["request_id"], newer_start["request"]["request_id"])
        self.assertEqual(previous_task, self.r._get("tasks", "task_id", "TEST-TASK"))

    def test_guard_blocks_controller_draft_and_task_spoofing(self):
        self.enable()
        self.created(self.direct(), "TEST-execution-child")
        with self.assertRaises(ConflictError):
            self.call("task.create", task_id="BAD", title="BAD", module="screenplay", scope="script/test",
                thread_id="TEST-control", artifact_id="TEST-SCRIPT", inputs=[], must_keep=[], allowed_changes=[], requirements=[])
        with self.assertRaises(ConflictError):
            self.call("task.create", task_id="WRONG-PROFESSION", title="BAD", module="director", scope="script/test",
                thread_id="TEST-execution-child", artifact_id="TEST-SCRIPT", inputs=[], must_keep=[], allowed_changes=[], requirements=[])
        self.assertEqual(self.r._list("tasks"), [])
        self.task()
        self.call("conversation.bind_task", actor_thread_id="TEST-script", topic_id="TEST-EXEC", task_id="TEST-TASK")
        with self.assertRaises(ConflictError):
            self.call("conversation.complete", actor_thread_id="TEST-execution-child", topic_id="TEST-EXEC", task_id="TEST-TASK",
                      output_ref={"artifact_id": "TEST-SCRIPT", "version": 1}, summary="口头声称完成")

    def test_wrong_project_observation_and_actor_rollback(self):
        self.enable()
        prepared = self.idea()
        request = prepared["request"]["request_id"]
        self.call("conversation.claim", request_id=request)
        before = self.read()
        with self.assertRaises(ConflictError):
            self.observe(request, "host_accepted", thread_id="TEST-child", project_id="OTHER-PROJECT")
        self.assertEqual(before, self.read())
        with self.assertRaises(ConflictError):
            self.call("conversation.decide", actor_thread_id="OTHER-THREAD", topic_id="TEST-TOPIC", decision="retain", reason="伪造职责")
        self.assertEqual(before, self.read())

    def test_frozen_planning_source_is_provenance_and_tamper_detected(self):
        self.enable()
        self.created(self.idea(), "TEST-topic-child")
        handoff = self.call("conversation.decide", actor_thread_id="TEST-planning", topic_id="TEST-TOPIC", decision="develop",
                           reason="准确版本分支转作", branch_id="branch-a", target_role="script")["handoff"]
        source = handoff["source_ref"]
        self.call("conversation.accept", actor_thread_id="TEST-script", handoff_id=handoff["handoff_id"], status="ready",
                  brief="按已选分支写剧本", inputs=[source])
        execution = self.call("conversation.prepare", actor_thread_id="TEST-script", topic_id="TEST-FROZEN", kind="execution",
            title="冻结源执行", scope="script/frozen", target_artifact_id="TEST-FROZEN-SCRIPT", handoff_id=handoff["handoff_id"])
        self.created(execution, "TEST-frozen-child")
        self.planning(version=1)
        self.call("task.create", task_id="TEST-FROZEN-TASK", title="冻结源写作", module="screenplay", scope="script/frozen",
            thread_id="TEST-frozen-child", artifact_id="TEST-FROZEN-SCRIPT", inputs=[source], must_keep=[], allowed_changes=[], requirements=[])
        original = deepcopy(self.r._get("tasks", "task_id", "TEST-FROZEN-TASK"))
        self.assertEqual(original["inputs"], [source])
        reference = original["conversation_source_reference"]
        self.assertEqual(reference["branch_id"], "branch-a")
        self.assertEqual(reference["source_ref"]["version"], 1)
        resumed = self.r.dispatch("task.resume", {"task_id": "TEST-FROZEN-TASK"})
        self.assertEqual(resumed["stale_inputs"], [])
        damaged = deepcopy(original)
        damaged["conversation_source_reference"]["branch_id"] = "branch-b"
        self.r._put("tasks", "task_id", "TEST-FROZEN-TASK", damaged)
        self.assertFalse(self.r.dispatch("task.resume", {"task_id": "TEST-FROZEN-TASK"})["execution_compatibility"]["compatible"])
        self.r._put("tasks", "task_id", "TEST-FROZEN-TASK", original)
        result = self.call("task.submit", task_id="TEST-FROZEN-TASK", artifact_id="TEST-FROZEN-SCRIPT", kind="script", base_version=0,
            content="第一场：少年走进院门。故事由已选创意展开。", metadata={"category": "script"})
        artifact = result["artifact"]
        self.assertEqual(artifact["deps"], [])
        self.assertEqual(artifact["metadata"]["conversation_source_reference"], reference)
        with self.assertRaises(ConflictError):
            self.call("artifact.save", artifact_id="TEST-FROZEN-SCRIPT", kind="script", scope="script/frozen", base_version=1,
                content="修订稿", metadata={"category": "script", "conversation_source_reference": {**reference, "branch_id": "fake"}})
        saved = self.call("artifact.save", artifact_id="TEST-FROZEN-SCRIPT", kind="script", scope="script/frozen", base_version=1,
                          content="完整合法修订稿，保留来源。", metadata={"category": "script"})
        self.assertEqual(saved["artifact"]["metadata"]["conversation_source_reference"], reference)

    def test_action_schemas_are_strict_and_independent(self):
        schemas = action_schemas()
        schemas["conversation.read"]["properties"]["x"] = {}
        self.assertNotIn("x", action_schemas()["conversation.read"]["properties"])
        with self.assertRaises(ValueError):
            validate_conversation_payload("conversation.read", {"expected_project_id": "TEST", "unknown": True})
        payload = {"op_id": "TEST", "expected_project_id": "TEST", "base_revision": 0, "actor_thread_id": "TEST",
            "topic_id": "TEST", "kind": "execution", "title": "TEST", "scope": "TEST", "target_artifact_id": "TEST",
            "direct_brief": "TEST", "inputs": [], "target_role": "script", "handoff_id": "BOTH"}
        with self.assertRaises(ValueError):
            validate_conversation_payload("conversation.prepare", payload)


if __name__ == "__main__":
    unittest.main()

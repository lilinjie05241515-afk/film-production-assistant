"""Synthetic 2.1 professional routing, exact completion and independent report tests."""
from copy import deepcopy
from unittest.mock import patch
import json
import unittest

import test_conversations1170 as fixtures
from filmprod.core import ConflictError
from filmprod.conversation_routing2100 import derive_topic_progress


class Conversation2100Tests(unittest.TestCase):
    setUp = fixtures.ConversationTests.setUp
    tearDown = fixtures.ConversationTests.tearDown
    call = fixtures.ConversationTests.call
    read = fixtures.ConversationTests.read
    workspace_observe = fixtures.ConversationTests.workspace_observe
    enable = fixtures.ConversationTests.enable
    planning = fixtures.ConversationTests.planning
    idea = fixtures.ConversationTests.idea
    direct = fixtures.ConversationTests.direct
    observe = fixtures.ConversationTests.observe
    created = fixtures.ConversationTests.created
    task = fixtures.ConversationTests.task
    submitted = fixtures.ConversationTests.submitted

    def extended_auth(self, actions=None, threads=None):
        grant = deepcopy(self.auth)
        grant["actions"] = actions or [*grant["actions"], "route", "route_accept", "report"]
        if threads is not None:
            grant["target"]["thread_ids"] = threads
        return grant

    def route(self, request_id="TEST-ROUTE", **extra):
        return self.call("conversation.route", **{"actor_thread_id": "TEST-director", "request_id": request_id,
            "original_request": "请把这场对白改成更短、更含蓄的版本。", "target_role": "script", "scope": "script/routed",
            "inputs": [], "deliverable": "该场完整修订候选和变更说明", "report_to_thread_id": "TEST-director", **extra})

    def ready_route(self):
        self.route()
        return self.call("conversation.route_accept", actor_thread_id="TEST-script", request_id="TEST-ROUTE",
                         status="ready", brief="按准确原话修订一场，不改变结局", inputs=[])

    def completed_fixture(self, grant=None):
        self.enable(grant or self.extended_auth())
        self.created(self.direct(), "TEST-execution-child")
        self.task()
        self.call("conversation.bind_task", actor_thread_id="TEST-script", topic_id="TEST-EXEC", task_id="TEST-TASK")
        return self.submitted()

    def complete(self, output, **extra):
        return self.call("conversation.complete", **{"actor_thread_id": "TEST-execution-child", "topic_id": "TEST-EXEC",
            "task_id": "TEST-TASK", "output_ref": output, "summary": "准确候选已完整提交", **extra})

    def test_all_current_departments_execute_exact_tasks_and_complete_candidates(self):
        self.enable(self.extended_auth())
        roles = {"planning": ("requirements", "requirements"), "script": ("screenplay", "script"),
            "director": ("director-agent", "director"), "art": ("research", "research"),
            "assets": ("seedance-prompt", "prompt"), "review": ("review", "review")}
        for role, (module, kind) in roles.items():
            with self.subTest(role=role):
                scope, artifact_id, topic_id, task_id = f"TEST/{role}", f"OUT-{role}", f"TOPIC-{role}", f"TASK-{role}"
                prep = self.call("conversation.prepare", actor_thread_id="TEST-" + role, topic_id=topic_id, kind="execution",
                    title="TEST " + role, scope=scope, target_artifact_id=artifact_id, target_role=role, direct_brief="制作准确候选", inputs=[])
                thread_id = self.created(prep, "CHILD-" + role)
                self.call("task.create", task_id=task_id, title="TEST", module=module, scope=scope, thread_id=thread_id,
                    artifact_id=artifact_id, inputs=[], must_keep=[], allowed_changes=["完整候选"], requirements=[])
                self.call("conversation.bind_task", actor_thread_id=thread_id, topic_id=topic_id, task_id=task_id)
                output = self.call("task.submit", task_id=task_id, artifact_id=artifact_id, kind=kind, base_version=0,
                                   content="TEST 完整候选正文")['task']['output']
                done = self.call("conversation.complete", actor_thread_id="TEST-" + role, topic_id=topic_id, task_id=task_id,
                                output_ref=output, summary="已读取准确成果")
                self.assertTrue(done["completion_recorded"])
                self.assertEqual(done["topic"]["status"], "completed")
        self.assertEqual(self.r._list("decisions"), [])
        self.assertEqual(len(self.read()["parents"]), 7)

    def test_novel_department_keeps_its_route_and_lock(self):
        self.call("project.workflow.set", mode="novel_to_screen", base_revision=1)
        workspace = self.r.dispatch("workspace.read", {"expected_project_id": "TEST-CONVERSATIONS"})
        self.call("workspace.prepare", base_revision=workspace["revision"])
        self.workspace_observe("novel", "request_started")
        self.workspace_observe("novel", "host_confirmed", thread_id="TEST-novel", title="novel", origin="created")
        self.workspace_observe("novel", "catalog_bound", tool="film_projects", thread_id="TEST-novel", project_id="TEST-CONVERSATIONS")
        self.workspace_observe("novel", "client_project_observed", tool="list_threads", thread_id="TEST-novel", client_project_id="TEST-CLIENT")
        self.enable(self.extended_auth())
        prep = self.call("conversation.prepare", actor_thread_id="TEST-novel", topic_id="NOVEL", kind="execution", title="TEST novel",
            scope="novel/test", target_artifact_id="NOVEL", target_role="novel", direct_brief="准确小说候选", inputs=[])
        self.created(prep, "TEST-novel-child")
        made = self.call("task.create", task_id="NOVEL", title="TEST", module="story", scope="novel/test", thread_id="TEST-novel-child",
            artifact_id="NOVEL", inputs=[], must_keep=[], allowed_changes=[], requirements=[])
        self.assertEqual(made["execution_lock"]["module_id"], "screenwriter")
        with self.assertRaises(ConflictError):
            self.call("task.create", task_id="WRONG", title="TEST", module="screenplay", scope="novel/test", thread_id="TEST-novel-child",
                artifact_id="NOVEL", inputs=[], must_keep=[], allowed_changes=[], requirements=[])

    def test_controller_wrong_profession_and_scope_cannot_create_tasks(self):
        self.enable()
        prep = self.call("conversation.prepare", actor_thread_id="TEST-art", topic_id="ART", kind="execution", title="TEST art",
            scope="art/test", target_artifact_id="ART", target_role="art", direct_brief="美术研究", inputs=[])
        self.created(prep, "TEST-art-child")
        for thread, module, scope in [("TEST-art", "research", "art/test"), ("TEST-control", "music", "music/test"),
                                      ("TEST-art-child", "screenplay", "art/test"), ("TEST-art-child", "research", "other")]:
            with self.subTest(thread=thread, module=module, scope=scope), self.assertRaises(ConflictError):
                self.call("task.create", task_id="BAD", title="TEST", module=module, scope=scope, thread_id=thread,
                    artifact_id="ART", inputs=[], must_keep=[], allowed_changes=[], requirements=[])

    def test_route_is_exact_local_handoff_not_message_or_approval(self):
        self.enable(self.extended_auth())
        result = self.route()
        self.assertFalse(result["notification_sent"])
        self.assertFalse(result["dispatch_allowed"])
        route = result["route"]
        self.assertEqual(route["source_thread_id"], "TEST-director")
        self.assertEqual(route["receiver_thread_id"], "TEST-script")
        self.assertEqual(route["original_request"], "请把这场对白改成更短、更含蓄的版本。")
        self.assertEqual(self.read()["outbox"], [])
        self.assertTrue(self.route()["reused"])
        with self.assertRaises(ConflictError):
            self.route(deliverable="偷偷改变目标")
        with self.assertRaises(ConflictError):
            self.call("conversation.route_accept", actor_thread_id="TEST-director", request_id="TEST-ROUTE", status="received")
        self.call("conversation.route_accept", actor_thread_id="TEST-script", request_id="TEST-ROUTE", status="clarifying",
                  questions=["本轮准确场次是哪一场？"])
        self.call("conversation.route_accept", actor_thread_id="TEST-script", request_id="TEST-ROUTE", status="ready",
                  brief="已明确准确场次", inputs=[])
        prepared = self.call("conversation.prepare", actor_thread_id="TEST-script", topic_id="ROUTED", kind="execution", title="TEST routed",
            scope="script/routed", route_id="TEST-ROUTE", target_artifact_id="ROUTED")
        self.assertEqual(prepared["topic"]["report_to_thread_id"], "TEST-director")
        with self.assertRaises(ConflictError):
            self.call("conversation.prepare", actor_thread_id="TEST-script", topic_id="DUPLICATE", kind="execution", title="TEST routed",
                scope="script/routed", route_id="TEST-ROUTE", target_artifact_id="ROUTED")
        self.assertEqual(self.r._list("tasks"), [])
        self.assertEqual(self.r._list("decisions"), [])

    def test_missing_department_unknown_thread_and_other_project_do_not_reroute(self):
        self.enable(self.extended_auth())
        for extra in ({"actor_thread_id": "OTHER-THREAD"}, {"report_to_thread_id": "OTHER-THREAD"},
                      {"target_role": "novel"}, {"expected_project_id": "OTHER-PROJECT"}, {"target_role": "director"}):
            before = self.read()
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.route(**extra)
            self.assertEqual(before, self.read())
        self.assertEqual(len(self.r._list("threads")), 7)

    def test_ready_and_prepare_preserve_original_exact_inputs_and_freshness(self):
        self.enable(self.extended_auth())
        ref = self.planning()
        self.route(inputs=[ref])
        with self.assertRaises(ConflictError):
            self.call("conversation.route_accept", actor_thread_id="TEST-script", request_id="TEST-ROUTE", status="ready", brief="TEST", inputs=[])
        self.planning(version=1)
        with self.assertRaises(ConflictError):
            self.call("conversation.route_accept", actor_thread_id="TEST-script", request_id="TEST-ROUTE", status="ready", brief="TEST", inputs=[ref])
        with self.assertRaises(ValueError):
            self.route(request_id="AMBIGUOUS", inputs=[{"artifact_id": "TEST-IDEA"}])
        with self.assertRaises(ConflictError):
            self.route(request_id="STALE", inputs=[ref])
        self.assertEqual(self.read()["routes"][0]["status"], "offered")

    def test_prepared_route_cannot_change_scope_or_discard_later_upstream_change(self):
        self.enable(self.extended_auth())
        ref = self.planning()
        self.route(inputs=[ref])
        self.call("conversation.route_accept", actor_thread_id="TEST-script", request_id="TEST-ROUTE", status="ready", brief="TEST", inputs=[ref])
        with self.assertRaises(ConflictError):
            self.call("conversation.prepare", actor_thread_id="TEST-script", topic_id="ROUTED", kind="execution", title="TEST",
                scope="different", route_id="TEST-ROUTE", target_artifact_id="ROUTED")
        self.planning(version=1)
        with self.assertRaises(ConflictError):
            self.call("conversation.prepare", actor_thread_id="TEST-script", topic_id="ROUTED", kind="execution", title="TEST",
                scope="script/routed", route_id="TEST-ROUTE", target_artifact_id="ROUTED")

    def test_submitted_task_view_is_read_only_not_auto_completion(self):
        output = self.completed_fixture()
        before = self.r.db.execute("SELECT value FROM settings WHERE key='conversation/v1'").fetchone()[0]
        revision = self.read()["revision"]
        view = self.read()["topics"][0]
        self.assertEqual(view["task_status"], "submitted")
        self.assertEqual(view["status"], "task_bound")
        self.assertEqual(view["task_output_ref"], output)
        self.assertTrue(view["needs_completion_record"])
        self.assertFalse(view["completion_recorded"])
        self.assertEqual(view["report_status"], "not_ready")
        self.assertEqual(revision, self.read()["revision"])
        self.assertEqual(before, self.r.db.execute("SELECT value FROM settings WHERE key='conversation/v1'").fetchone()[0])

    def test_complete_without_send_permission_saves_output_and_waiting_reports(self):
        grant = self.extended_auth()
        grant["actions"].remove("send_message_to_thread")
        output = self.completed_fixture(grant)
        done = self.complete(output, actor_thread_id="TEST-script")
        self.assertEqual(done["topic"]["status"], "completed")
        self.assertEqual(done["requests"], [])
        self.assertEqual(done["report_status"], "pending_authorization")
        self.assertEqual(len(done["report_recipients"]), 2)
        self.assertTrue(all(r["request_id"] is None for r in done["report_recipients"]))
        self.assertEqual(self.read()["topics"][0]["task_output_ref"], output)
        self.assertEqual(self.r._list("decisions"), [])

    def test_completion_uses_explicit_narrow_grant_not_stored_broad_send(self):
        output = self.completed_fixture()
        done = self.complete(output, authorization=self.extended_auth(actions=["complete"]))
        self.assertEqual(done["report_status"], "pending_authorization")
        self.assertEqual(done["requests"], [])
        self.assertEqual(self.read()["topics"][0]["status"], "completed")

    def test_report_later_handles_partial_permissions_unknown_and_replay(self):
        output = self.completed_fixture()
        self.complete(output, authorization=self.extended_auth(actions=["complete"]))
        grant = self.extended_auth(actions=["report", "send_message_to_thread"], threads=["TEST-execution-child", "TEST-script"])
        report = self.call("conversation.report", actor_thread_id="TEST-execution-child", topic_id="TEST-EXEC", task_id="TEST-TASK",
            output_ref=output, authorization=grant)
        self.assertEqual(len(report["requests"]), 1)
        request = report["requests"][0]["request_id"]
        claim = {"request_id": request, "op_id": "TEST-ONE-CLAIM", "base_revision": self.read()["revision"]}
        self.assertTrue(self.call("conversation.claim", **claim)["dispatch_allowed"])
        self.assertFalse(self.call("conversation.claim", **claim)["dispatch_allowed"])
        self.observe(request, "unknown", reason="TEST 网络结果未知")
        report = self.call("conversation.report", actor_thread_id="TEST-script", topic_id="TEST-EXEC", task_id="TEST-TASK", output_ref=output)
        self.assertEqual(len(report["requests"]), 2)
        self.assertEqual(report["report_status"], "unknown")
        self.assertFalse(self.call("conversation.claim", request_id=request)["dispatch_allowed"])
        self.assertEqual(len([r for r in self.read()["outbox"] if r["purpose"].startswith("completion-")]), 2)
        self.observe(request, "host_accepted", thread_id="TEST-script")
        other = next(r for r in report["requests"] if r["request_id"] != request)
        self.call("conversation.claim", request_id=other["request_id"])
        self.observe(other["request_id"], "host_accepted", thread_id="TEST-control")
        view = self.read()["topics"][0]
        self.assertEqual(view["report_status"], "host_accepted")
        self.assertTrue(all(not r["business_processed"] for r in view["report_recipients"]))

    def test_completion_and_report_reject_wrong_actor_output_and_unbound_task(self):
        output = self.completed_fixture()
        for extra in ({"actor_thread_id": "TEST-director"}, {"task_id": "ANOTHER"}, {"output_ref": {"artifact_id": "TEST-SCRIPT", "version": 2}}):
            with self.subTest(extra=extra), self.assertRaises(ConflictError):
                self.complete(output, **extra)
        with self.assertRaises(ConflictError):
            self.call("conversation.report", actor_thread_id="TEST-script", topic_id="TEST-EXEC", task_id="TEST-TASK", output_ref=output)
        self.complete(output)
        with self.assertRaises(ConflictError):
            self.call("conversation.report", actor_thread_id="TEST-director", topic_id="TEST-EXEC", task_id="TEST-TASK", output_ref=output)

    def test_pending_report_remains_available_after_next_round(self):
        output = self.completed_fixture()
        self.complete(output, authorization=self.extended_auth(actions=["complete"]))
        self.call("conversation.continue", actor_thread_id="TEST-script", topic_id="TEST-EXEC", brief="明确下一轮", inputs=[])
        reported = self.call("conversation.report", actor_thread_id="TEST-script", topic_id="TEST-EXEC", task_id="TEST-TASK", output_ref=output)
        self.assertEqual(len(reported["requests"]), 2)
        self.assertTrue(all(r["round"] == 1 for r in reported["requests"]))
        topic = self.read()["topics"][0]
        self.assertEqual(topic["status"], "active")
        self.assertEqual(topic["round"], 2)
        self.assertEqual(topic["report_status"], "not_ready")
        self.assertEqual(topic["task_history"][0]["report_status"], "planned")

    def test_old_parent_snapshot_read_does_not_expand_until_explicit_configure(self):
        self.enable()
        state = json.loads(self.r.db.execute("SELECT value FROM settings WHERE key='conversation/v1'").fetchone()[0])
        state["parents"] = {role: p for role, p in state["parents"].items() if role in ("control", "planning", "script")}
        raw = json.dumps(state, ensure_ascii=False)
        self.r.db.execute("UPDATE settings SET value=? WHERE key='conversation/v1'", (raw,))
        self.r.db.commit()
        self.assertEqual(len(self.read()["parents"]), 3)
        self.assertEqual(self.read()["revision"], state["revision"])
        self.assertEqual(raw, self.r.db.execute("SELECT value FROM settings WHERE key='conversation/v1'").fetchone()[0])
        with self.assertRaises(ConflictError):
            self.route(authorization=self.extended_auth(), actor_thread_id="TEST-control", target_role="art")
        self.enable(self.extended_auth())
        self.assertEqual(len(self.read()["parents"]), 7)

    def test_route_operation_replay_and_revision_conflict_keep_one_record(self):
        self.enable(self.extended_auth())
        payload = {"op_id": "TEST-ROUTE-ONCE", "base_revision": self.read()["revision"]}
        self.route(**payload)
        self.route(**payload)
        self.assertEqual(len(self.read()["routes"]), 1)
        with self.assertRaises(ConflictError):
            self.route(request_id="CONCURRENT", base_revision=payload["base_revision"])
        self.assertEqual(len(self.read()["routes"]), 1)

    def test_submitted_old_execution_lock_can_complete_without_new_runtime_execution(self):
        output = self.completed_fixture()
        task_before = deepcopy(self.r._get("tasks", "task_id", "TEST-TASK"))
        with patch("filmprod.modules.require_execution", side_effect=ConflictError("旧任务须用旧运行版本")):
            with self.assertRaises(ConflictError):
                self.call("conversation.start", actor_thread_id="TEST-script", topic_id="TEST-EXEC")
            completed = self.complete(output)
        self.assertTrue(completed["completion_recorded"])
        self.assertEqual(task_before, self.r._get("tasks", "task_id", "TEST-TASK"))

    def test_routed_result_reports_to_owning_department_control_and_original_source(self):
        self.enable(self.extended_auth())
        self.ready_route()
        prep = self.call("conversation.prepare", actor_thread_id="TEST-script", topic_id="ROUTED", kind="execution", title="TEST",
            scope="script/routed", route_id="TEST-ROUTE", target_artifact_id="ROUTED")
        self.created(prep, "TEST-routed-child")
        self.call("task.create", task_id="ROUTED", title="TEST", module="screenplay", scope="script/routed",
            thread_id="TEST-routed-child", artifact_id="ROUTED", inputs=[], must_keep=[], allowed_changes=[], requirements=[])
        self.call("conversation.bind_task", actor_thread_id="TEST-script", topic_id="ROUTED", task_id="ROUTED")
        output = self.call("task.submit", task_id="ROUTED", artifact_id="ROUTED", kind="script", base_version=0, content="TEST完整正文")["task"]["output"]
        done = self.call("conversation.complete", actor_thread_id="TEST-script", topic_id="ROUTED", task_id="ROUTED", output_ref=output, summary="完整候选")
        self.assertEqual({r["target_thread_id"] for r in done["requests"]}, {"TEST-script", "TEST-control", "TEST-director"})

    def test_legacy_start_outbox_is_reused_without_rewriting_unknown_request(self):
        self.enable(self.extended_auth())
        self.created(self.direct(), "TEST-execution-child")
        self.task()
        self.call("conversation.bind_task", actor_thread_id="TEST-script", topic_id="TEST-EXEC", task_id="TEST-TASK")
        started = self.call("conversation.start", actor_thread_id="TEST-script", topic_id="TEST-EXEC")
        request_id = started["request"]["request_id"]
        self.call("conversation.claim", request_id=request_id)
        self.observe(request_id, "unknown", reason="TEST old host request unknown")
        state = json.loads(self.r.db.execute("SELECT value FROM settings WHERE key='conversation/v1'").fetchone()[0])
        request = next(r for r in state["outbox"] if r["request_id"] == request_id)
        for key in ("parent_role", "allowed_task_modules", "route_id", "report_to_thread_id"):
            request["payload"].pop(key, None)
        frozen_request = deepcopy(request)
        self.r.db.execute("UPDATE settings SET value=? WHERE key='conversation/v1'", (json.dumps(state),))
        self.r.db.commit()
        repeated = self.call("conversation.start", actor_thread_id="TEST-script", topic_id="TEST-EXEC")
        self.assertEqual(repeated["request"], frozen_request)
        self.assertFalse(repeated["dispatch_allowed"])
        self.assertFalse(self.call("conversation.claim", request_id=request_id)["dispatch_allowed"])
        self.assertEqual(len([r for r in self.read()["outbox"] if r["purpose"] == "start-1"]), 1)

    def test_registered_professional_aliases_cannot_bypass_topic_guard(self):
        from filmprod.modules import ALIASES
        self.enable(self.extended_auth())
        for module in sorted(set(ALIASES) | set(ALIASES.values())):
            with self.subTest(module=module), self.assertRaises(ConflictError):
                self.call("task.create", task_id="UNBOUND-" + module, title="TEST", module=module, scope="unbound/" + module,
                    thread_id="TEST-unbound", artifact_id="UNBOUND-" + module,
                    inputs=[], must_keep=[], allowed_changes=[], requirements=[])
        self.assertEqual(self.r._list("tasks"), [])

    def test_new_route_continues_same_thread_and_keeps_exact_output_target(self):
        output = self.completed_fixture()
        self.complete(output, authorization=self.extended_auth(actions=["complete"]))
        self.route(scope="script/test", target_artifact_id="TEST-SCRIPT")
        self.call("conversation.route_accept", actor_thread_id="TEST-script", request_id="TEST-ROUTE", status="ready",
                  brief="缩短对白", inputs=[])
        result = self.call("conversation.continue", actor_thread_id="TEST-script", topic_id="TEST-EXEC",
                           brief="本轮缩短对白", inputs=[], route_id="TEST-ROUTE")
        self.assertFalse(result["new_chat_created"])
        self.assertEqual(result["continuation_mode"], "routed")
        self.assertEqual(result["topic"]["thread_id"], "TEST-execution-child")
        self.assertEqual(result["topic"]["target_artifact_id"], "TEST-SCRIPT")
        self.assertEqual(result["topic"]["report_to_thread_id"], "TEST-director")
        route = self.read()["routes"][0]
        self.assertEqual((route["execution_topic_id"], route["execution_round"], route["execution_target_artifact_id"]),
                         ("TEST-EXEC", 2, "TEST-SCRIPT"))
        self.assertEqual(len(self.r._list("threads")), 8)

    def test_route_continuation_rejects_wrong_role_scope_target_and_inputs(self):
        output = self.completed_fixture()
        self.complete(output)
        ref = self.planning()
        cases = [
            ("ROLE", {"target_role": "director", "actor_thread_id": "TEST-art"}, "TEST-director", []),
            ("SCOPE", {"scope": "script/other"}, "TEST-script", []),
            ("TARGET", {"target_artifact_id": "OTHER-SCRIPT"}, "TEST-script", []),
            ("INPUT", {}, "TEST-script", [ref]),
        ]
        for name, changes, receiver, inputs in cases:
            self.route(request_id=name, **{"scope": "script/test", "inputs": inputs, **changes})
            self.call("conversation.route_accept", actor_thread_id=receiver, request_id=name, status="ready", brief="TEST", inputs=inputs)
            before = self.read()
            with self.subTest(case=name), self.assertRaises(ConflictError):
                self.call("conversation.continue", actor_thread_id="TEST-script", topic_id="TEST-EXEC", brief="TEST", inputs=[], route_id=name)
            self.assertEqual(self.read(), before)
        self.route(request_id="NOT-READY", scope="script/test")
        with self.assertRaises(ConflictError):
            self.call("conversation.continue", actor_thread_id="TEST-script", topic_id="TEST-EXEC", brief="TEST", inputs=[], route_id="NOT-READY")

    def test_direct_continuation_does_not_redispatch_old_route(self):
        self.enable(self.extended_auth())
        self.route(scope="script/test")
        self.call("conversation.route_accept", actor_thread_id="TEST-script", request_id="TEST-ROUTE", status="ready", brief="TEST", inputs=[])
        prep = self.call("conversation.prepare", actor_thread_id="TEST-script", topic_id="TEST-EXEC", kind="execution", title="TEST",
            scope="script/test", route_id="TEST-ROUTE", target_artifact_id="TEST-SCRIPT")
        self.created(prep, "TEST-execution-child")
        self.task()
        self.call("conversation.bind_task", actor_thread_id="TEST-script", topic_id="TEST-EXEC", task_id="TEST-TASK")
        self.complete(self.submitted(), authorization=self.extended_auth(actions=["complete"]))
        result = self.call("conversation.continue", actor_thread_id="TEST-script", topic_id="TEST-EXEC", brief="用户直接修订", inputs=[])
        self.assertEqual(result["continuation_mode"], "direct")
        self.assertIsNone(result["route_id"])
        self.assertIsNone(result["report_to_thread_id"])
        self.assertTrue(result["previous_round_reports_preserved"])
        self.assertFalse(result["extra_report_target_inherited"])
        self.assertNotIn("route_id", result["topic"])
        self.assertEqual(result["topic"]["task_history"][0]["route_id"], "TEST-ROUTE")
        self.assertEqual(result["topic"]["task_history"][0]["report_to_thread_id"], "TEST-director")
        self.assertEqual(self.read()["routes"][0]["execution_round"], 1)

    def test_two_routed_rounds_keep_independent_report_targets_and_unknown_request(self):
        self.enable(self.extended_auth())
        self.route(request_id="FIRST", scope="script/test")
        self.call("conversation.route_accept", actor_thread_id="TEST-script", request_id="FIRST", status="ready", brief="TEST first", inputs=[])
        prep = self.call("conversation.prepare", actor_thread_id="TEST-script", topic_id="TEST-EXEC", kind="execution", title="TEST",
            scope="script/test", route_id="FIRST", target_artifact_id="TEST-SCRIPT")
        self.created(prep, "TEST-execution-child")
        self.task()
        self.call("conversation.bind_task", actor_thread_id="TEST-script", topic_id="TEST-EXEC", task_id="TEST-TASK")
        first_output = self.submitted()
        self.complete(first_output, authorization=self.extended_auth(actions=["complete"]))
        self.route(request_id="SECOND", scope="script/test", actor_thread_id="TEST-review", report_to_thread_id="TEST-review")
        self.call("conversation.route_accept", actor_thread_id="TEST-script", request_id="SECOND", status="ready", brief="TEST second", inputs=[])
        self.call("conversation.continue", actor_thread_id="TEST-script", topic_id="TEST-EXEC", brief="TEST second", inputs=[], route_id="SECOND")
        self.task("TEST-TASK-2")
        self.call("conversation.bind_task", actor_thread_id="TEST-script", topic_id="TEST-EXEC", task_id="TEST-TASK-2")
        second_output = self.submitted(task_id="TEST-TASK-2", base_version=1)
        self.complete(second_output, task_id="TEST-TASK-2", authorization=self.extended_auth(actions=["complete"]))
        first = self.call("conversation.report", actor_thread_id="TEST-script", topic_id="TEST-EXEC", task_id="TEST-TASK", output_ref=first_output)
        second = self.call("conversation.report", actor_thread_id="TEST-script", topic_id="TEST-EXEC", task_id="TEST-TASK-2", output_ref=second_output)
        self.assertEqual({r["target_thread_id"] for r in first["requests"]}, {"TEST-script", "TEST-control", "TEST-director"})
        self.assertEqual({r["target_thread_id"] for r in second["requests"]}, {"TEST-script", "TEST-control", "TEST-review"})
        unknown = next(r for r in first["requests"] if r["target_thread_id"] == "TEST-director")
        self.call("conversation.claim", request_id=unknown["request_id"])
        self.observe(unknown["request_id"], "unknown", reason="TEST receipt unknown")
        retried = self.call("conversation.report", actor_thread_id="TEST-script", topic_id="TEST-EXEC", task_id="TEST-TASK", output_ref=first_output)
        self.assertEqual(retried["report_status"], "unknown")
        self.assertFalse(self.call("conversation.claim", request_id=unknown["request_id"])["dispatch_allowed"])
        self.assertEqual(len([r for r in self.read()["outbox"] if r["purpose"].startswith("completion-")]), 6)
        first_route, second_route = self.read()["routes"]
        self.assertEqual((first_route["execution_round"], second_route["execution_round"]), (1, 2))
        self.assertEqual(first_route["execution_topic_id"], second_route["execution_topic_id"])
        # A historical record without the materialized recipients still uses
        # its own frozen source target, never the current round's route.
        topic = self.read()["topics"][0]
        history = deepcopy(topic["task_history"][0])
        history.pop("report_recipients", None)
        history["status"] = "completed"
        from filmprod.conversation_routing2100 import _report_view
        self.assertEqual({r["thread_id"] for r in _report_view(self.read(), topic, history)["report_recipients"]},
                         {"TEST-script", "TEST-control", "TEST-director"})

    def test_route_continuation_keeps_completion_and_unknown_start_guards(self):
        self.enable(self.extended_auth())
        self.created(self.direct(), "TEST-execution-child")
        self.task()
        self.call("conversation.bind_task", actor_thread_id="TEST-script", topic_id="TEST-EXEC", task_id="TEST-TASK")
        started = self.call("conversation.start", actor_thread_id="TEST-script", topic_id="TEST-EXEC")
        self.call("conversation.claim", request_id=started["request"]["request_id"])
        self.observe(started["request"]["request_id"], "unknown", reason="TEST unknown start")
        self.route(scope="script/test")
        self.call("conversation.route_accept", actor_thread_id="TEST-script", request_id="TEST-ROUTE", status="ready", brief="TEST", inputs=[])
        output = self.submitted()
        with self.assertRaises(ConflictError):
            self.call("conversation.continue", actor_thread_id="TEST-script", topic_id="TEST-EXEC", brief="TEST", inputs=[], route_id="TEST-ROUTE")
        self.observe(started["request"]["request_id"], "host_accepted", thread_id="TEST-execution-child")
        with self.assertRaisesRegex(ConflictError, "complete"):
            self.call("conversation.continue", actor_thread_id="TEST-script", topic_id="TEST-EXEC", brief="TEST", inputs=[], route_id="TEST-ROUTE")
        self.complete(output)
        self.call("conversation.continue", actor_thread_id="TEST-script", topic_id="TEST-EXEC", brief="TEST", inputs=[], route_id="TEST-ROUTE")

    def test_pure_projection_does_not_mutate_inputs_or_call_registry(self):
        output = self.completed_fixture()
        state = self.read()
        topic = deepcopy(state["topics"][0])
        task = self.r._get("tasks", "task_id", "TEST-TASK")
        args = (topic, task, state["outbox"], state["parents"])
        before = deepcopy(args)
        result = derive_topic_progress(*args)
        self.assertTrue(result["needs_completion_record"])
        self.assertEqual(result["task_output_ref"], output)
        self.assertEqual(args, before)


if __name__ == "__main__":
    unittest.main()

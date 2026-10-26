"""Isolated synthetic conversation records; no real host tools or project data."""
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from filmprod.core import ConflictError, Registry
from filmprod.workspace1110 import ACTION_SCHEMAS, _slot_id, validate_workspace_payload


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="filmprod-workspace-test-only-")
        self.root = Path(self.temp.name) / "synthetic"
        self.r = Registry(self.root)
        self.call("project.init", project_id="TEST-WORKSPACE", title="合成测试作品", test_only=True)

    def tearDown(self):
        self.r.close()
        self.temp.cleanup()

    def call(self, action, **payload):
        payload.setdefault("op_id", uuid.uuid4().hex)
        if action.startswith("workspace."):
            payload.setdefault("expected_project_id", "TEST-WORKSPACE")
        return self.r.dispatch(action, payload)

    def mode(self, mode):
        project = self.r._project()
        return self.call("project.workflow.set", expected_project_id="TEST-WORKSPACE",
                         base_revision=project.get("workflow", {}).get("revision", 0), mode=mode)

    def read(self):
        return self.r.dispatch("workspace.read", {"expected_project_id": "TEST-WORKSPACE"})

    def prepare(self, mode=None, **extra):
        if mode:
            self.mode(mode)
        return self.call("workspace.prepare", base_revision=self.read()["revision"], **extra)

    def slot(self, role="control", scope="project"):
        return next(s for s in self.read()["slots"] if s["role"] == role and s["scope"] == scope)

    def record(self, event, role="control", scope="project", **extra):
        slot = self.slot(role, scope)
        observation = {"request_id": slot["request_id"], **extra}
        if event not in ("request_started", "unknown"):
            observation = {"source": "host_tool", "tool": "create_thread", "observed_at": "2026-10-25T12:00:00+08:00", **observation}
        return self.call("workspace.record", base_revision=self.read()["revision"], slot_id=slot["slot_id"],
                         event=event, observation=observation)

    def resolve(self, role, scope="project"):
        return self.r.dispatch("workspace.resolve", {"expected_project_id": "TEST-WORKSPACE", "role": role, "scope": scope})

    def created(self, role="control", tid="host-thread-one"):
        self.record("request_started", role)
        self.record("host_confirmed", role, thread_id=tid, title="宿主实际标题", origin="created")
        return self.slot(role)

    def logical(self):
        return {t: [tuple(r) for r in self.r.db.execute("SELECT * FROM " + t)]
                for t in ("settings", "threads", "operations", "events", "tasks", "artifacts", "decisions")}

    def test_selected_route_required_and_no_effects(self):
        before = self.logical()
        with self.assertRaisesRegex(ValueError, "选择创作路线"):
            self.prepare()
        self.assertEqual(before, self.logical())

    def test_all_three_route_role_counts_and_no_host_creation(self):
        for mode, count in (("novel_only", 4), ("screenplay", 7), ("novel_to_screen", 8)):
            view = self.prepare(mode)
            self.assertEqual(len(view["slots"]), count)
            self.assertFalse(view["host_execution"])
            self.assertFalse(view["creation_is_execution"])
            self.assertEqual(self.r._list("threads"), [])
            self.assertEqual(self.r._list("tasks"), [])
            self.assertEqual(self.r._list("decisions"), [])
        self.assertIn("novel", [s["role"] for s in view["slots"]])

    def test_read_resolve_snapshot_are_read_only(self):
        self.prepare("novel_only")
        before = self.logical()
        result = self.r.dispatch("workspace.resolve", {"expected_project_id": "TEST-WORKSPACE", "role": "control"})
        self.assertEqual(result["next_action"], "create")
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(self.r.snapshot()["workspace"], self.read())
        self.assertEqual(before, self.logical())
        self.r.close()
        before_bytes = (self.root / ".project/registry.sqlite3").read_bytes()
        self.r = Registry.open_readonly(self.root)
        self.read()
        self.assertEqual(before_bytes, (self.root / ".project/registry.sqlite3").read_bytes())

    def test_prepare_repeats_reuse_slots_and_operations(self):
        first = self.prepare("screenplay", op_id="prepare-once")
        cached = self.call("workspace.prepare", base_revision=0, op_id="prepare-once")
        self.assertEqual(first, cached)
        again = self.prepare(op_id="prepare-again")
        self.assertEqual(first, again)
        self.assertEqual(len(first["preparations"]), 1)
        self.assertEqual(first["initialization_id"], again["initialization_id"])
        with self.assertRaises(ConflictError):
            self.call("workspace.prepare", base_revision=1, op_id="prepare-once")

    def test_existing_explicit_registry_reused_but_needs_host_check(self):
        self.call("thread.register", thread_id="old-host-thread", title="既有总控", scope="project",
                  status="active", current_control=True)
        self.prepare("novel_only")
        slot = self.slot()
        self.assertEqual(slot["thread_id"], "old-host-thread")
        self.assertEqual(slot["status"], "registered")
        self.assertEqual(slot["next_action"], "verify_existing")
        self.assertIsNone(slot["host_observation"])
        with self.assertRaises(ConflictError):
            self.record("request_started")
        self.record("host_confirmed", thread_id="old-host-thread", title="实际总控", origin="existing", tool="read_thread")
        self.assertEqual(len(self.r._list("threads")), 1)

    def test_legacy_current_control_overrides_purpose_without_double_occupancy(self):
        self.call("thread.register", thread_id="legacy-dual-tag", title="原有聊天", scope="project",
                  status="active", current_control=True, purpose="novel")
        self.prepare("novel_only")
        self.assertEqual(self.slot("control")["thread_id"], "legacy-dual-tag")
        self.assertIsNone(self.slot("novel")["thread_id"])
        self.assertEqual(self.slot("novel")["status"], "planned")
        self.record("host_confirmed", thread_id="legacy-dual-tag", title="真实总控", origin="existing", tool="read_thread")
        self.created("novel", "separate-novel-thread")
        self.assertEqual(self.slot("control")["status"], "host_confirmed")
        self.assertEqual(self.slot("novel")["status"], "host_confirmed")

    def test_explicit_role_overrides_current_control_and_purpose(self):
        thread = self.call("thread.register", thread_id="explicit-role", title="明确角色", scope="project",
                           status="active", current_control=True, purpose="script")
        self.r._put("threads", "thread_id", thread["thread_id"], dict(thread, workspace_role="novel", workspace_scope="chapter/1"))
        self.prepare("novel_to_screen")
        self.prepare(scope="chapter/1")
        assigned = [s for s in self.read()["slots"] if s["thread_id"] == "explicit-role"]
        self.assertEqual([(s["role"], s["scope"]) for s in assigned], [("novel", "chapter/1")])

    def test_exact_slot_tag_overrides_role_current_control_and_purpose(self):
        thread = self.call("thread.register", thread_id="explicit-slot", title="明确槽位", scope="project",
                           status="active", current_control=True, purpose="script")
        self.r._put("threads", "thread_id", thread["thread_id"], dict(thread,
                    workspace_slot_id=_slot_id("TEST-WORKSPACE", "novel", "chapter/1"),
                    workspace_role="script", workspace_scope="project"))
        self.prepare("novel_to_screen")
        self.prepare(scope="chapter/1")
        assigned = [s for s in self.read()["slots"] if s["thread_id"] == "explicit-slot"]
        self.assertEqual([(s["role"], s["scope"]) for s in assigned], [("novel", "chapter/1")])

    def test_scope_selection_retains_project_slots_and_exact_then_fallback_resolution(self):
        self.prepare("novel_only")
        self.prepare(scope="chapter/1")
        view = self.read()
        self.assertEqual(len(view["slots"]), 8)
        self.assertEqual(len([s for s in view["slots"] if s["selected_scope"]]), 4)
        self.assertEqual(view["retired_slots"], [])
        self.assertFalse(view["needs_prepare"])
        before = self.logical()
        for scope, resolved, resolution in (("project", "project", "exact"),
                                            ("chapter/1", "chapter/1", "exact"),
                                            ("chapter/2", "project", "project_fallback")):
            result = self.resolve("novel", scope)
            self.assertEqual(result["requested_scope"], scope)
            self.assertEqual(result["resolved_scope"], resolved)
            self.assertEqual(result["resolution"], resolution)
            self.assertTrue(result["role_active"])
        self.assertEqual(before, self.logical())

    def test_exact_pending_scope_never_escapes_to_project_fallback(self):
        self.prepare("novel_only")
        self.prepare(scope="chapter/1")
        self.prepare(scope="project")
        self.record("request_started", "novel", scope="chapter/1")
        for event, extra in (("queued", {"client_thread_id": "chapter-queue"}), ("unknown", {"reason": "断线"})):
            self.record(event, "novel", scope="chapter/1", **extra)
            result = self.resolve("novel", "chapter/1")
            self.assertEqual(result["resolution"], "exact")
            self.assertEqual(result["resolved_scope"], "chapter/1")
            self.assertEqual(result["next_action"], "check_pending")
            self.assertEqual(result["slot"]["status"], event)

    def test_exact_conflict_scope_never_escapes_to_project_fallback(self):
        self.prepare("novel_only")
        for tid in ("chapter-a", "chapter-b"):
            self.call("thread.register", thread_id=tid, title="章节候选", scope="chapter/1", purpose="novel", status="active")
        self.prepare(scope="chapter/1")
        self.prepare(scope="project")
        result = self.resolve("novel", "chapter/1")
        self.assertEqual(result["resolution"], "exact")
        self.assertEqual(result["next_action"], "resolve_conflict")
        self.assertEqual(result["slot"]["status"], "conflict")

    def test_exact_registry_without_slot_blocks_fallback_without_claiming(self):
        self.prepare("novel_only")
        self.call("thread.register", thread_id="chapter-registered", title="章节专属", scope="chapter/1", purpose="novel", status="active")
        before = self.logical()
        result = self.resolve("novel", "chapter/1")
        self.assertEqual(result["resolution"], "missing")
        self.assertIsNone(result["resolved_scope"])
        self.assertIsNone(result["slot"])
        self.assertTrue(result["project_fallback_blocked"])
        self.assertEqual(result["registry_candidates"], [{"thread_id": "chapter-registered", "title": "章节专属"}])
        self.assertEqual(before, self.logical())
        self.prepare(scope="chapter/1")
        prepared = self.resolve("novel", "chapter/1")
        self.assertEqual(prepared["resolution"], "exact")
        self.assertEqual(prepared["next_action"], "verify_existing")

    def test_other_selected_scope_does_not_block_start_confirm_or_open(self):
        self.prepare("novel_only")
        self.prepare(scope="chapter/1")
        self.created("novel", "project-novel-after-scope-switch")
        self.record("opened", "novel", tool="navigate_to_codex_page", thread_id="project-novel-after-scope-switch")
        self.assertEqual(self.slot("novel")["open_status"], "host_reported_opened")
        self.assertFalse(self.slot("novel")["selected_scope"])
        self.assertTrue(self.slot("novel")["active"])

    def test_retired_role_cannot_resolve_or_start_in_any_scope(self):
        self.prepare("novel_only")
        self.prepare(scope="chapter/1")
        old = self.slot("novel", "chapter/1")
        self.prepare("screenplay")
        result = self.resolve("novel", "chapter/1")
        self.assertEqual(result["resolution"], "missing")
        self.assertFalse(result["role_active"])
        self.assertIsNone(result["slot"])
        with self.assertRaises(ConflictError):
            self.call("workspace.record", base_revision=self.read()["revision"], slot_id=old["slot_id"],
                      event="request_started", observation={"request_id": old["request_id"]})

    def test_exact_legacy_purpose_match_and_ambiguous_match(self):
        for tid in ("a", "b"):
            self.call("thread.register", thread_id=tid, title="同职责", scope="project", purpose="script", status="active")
        self.prepare("screenplay")
        slot = self.slot("script")
        self.assertEqual(slot["status"], "conflict")
        self.assertEqual(slot["next_action"], "resolve_conflict")
        with self.assertRaises(ConflictError):
            self.record("request_started", "script")
        self.record("host_confirmed", "script", thread_id="b", title="选中的真实对话", origin="existing", tool="read_thread")
        self.assertEqual(self.slot("script")["thread_id"], "b")

    def test_repeat_prepare_reconciles_later_registry_without_replacing_unknown(self):
        self.prepare("screenplay")
        self.record("request_started")
        self.record("unknown", reason="待核对")
        self.call("thread.register", thread_id="later-control", title="后来登记总控", scope="project", status="active", current_control=True)
        self.call("thread.register", thread_id="later-script", title="后来登记剧本", scope="project", status="active", purpose="script")
        self.prepare()
        self.assertEqual(self.slot()["status"], "unknown")
        self.assertIsNone(self.slot()["thread_id"])
        self.assertEqual(self.slot("script")["thread_id"], "later-script")
        self.assertEqual(self.slot("script")["status"], "registered")

    def test_creation_claim_precedes_host_confirmation_and_is_exclusive(self):
        self.prepare("novel_only")
        with self.assertRaises(ConflictError):
            self.record("host_confirmed", thread_id="premature", title="未调用", origin="created")
        self.record("request_started")
        with self.assertRaises(ConflictError):
            self.record("request_started")
        self.assertEqual(self.slot()["next_action"], "check_pending")

    def test_queued_unknown_reopen_and_partial_recovery_keep_ids(self):
        self.prepare("screenplay")
        self.record("request_started")
        self.record("queued", client_thread_id="queued-client-id")
        request = self.slot()["request_id"]
        self.record("unknown", reason="transport disconnected")
        self.r.close()
        self.r = Registry(self.root)
        self.prepare()
        self.assertEqual(self.slot()["client_thread_id"], "queued-client-id")
        self.assertEqual(self.slot()["request_id"], request)
        self.assertEqual(self.slot()["next_action"], "check_pending")
        self.assertEqual(self.slot("script")["next_action"], "create")
        with self.assertRaises(ConflictError):
            self.record("request_started")
        with self.assertRaises(ValueError):
            self.record("host_confirmed", thread_id="queued-client-id", title="错误ID", origin="created")
        self.record("host_confirmed", thread_id="real-thread-id", title="真实返回标题", origin="created")
        self.assertEqual(self.slot()["client_thread_id"], "queued-client-id")
        self.assertEqual(self.slot()["status"], "host_confirmed")

    def test_bindings_and_host_open_are_independent_observations(self):
        self.prepare("screenplay")
        self.created()
        self.assertEqual(self.slot()["next_action"], "bind_catalog")
        self.record("catalog_bound", tool="film_projects", thread_id="host-thread-one", project_id="TEST-WORKSPACE")
        self.assertEqual(self.slot()["next_action"], "observe_client_project")
        self.assertEqual(self.slot()["status"], "host_confirmed")
        self.record("client_project_observed", tool="read_thread", thread_id="host-thread-one", client_project_id=None)
        self.assertEqual(self.slot()["status"], "associated_observed")
        self.assertEqual(self.slot()["client_project_status"], "host_reported_projectless")
        self.assertEqual(self.slot()["open_status"], "not_observed")
        self.record("opened", tool="navigate_to_codex_page", thread_id="host-thread-one")
        self.assertEqual(self.slot()["open_status"], "host_reported_opened")
        self.assertFalse(self.read()["observations_are_live"])

    def test_open_failure_keeps_association_and_cannot_restart_creation(self):
        self.prepare("screenplay")
        self.created()
        self.record("open_failed", tool="navigate_to_codex_page", thread_id="host-thread-one", reason="not accessible")
        self.assertEqual(self.slot()["thread_id"], "host-thread-one")
        self.assertEqual(self.slot()["open_status"], "host_reported_failed")
        with self.assertRaises(ConflictError):
            self.record("failed", no_thread_created=True, reason="不能删除已有关系")
        with self.assertRaises(ConflictError):
            self.record("request_started")

    def test_failed_unknown_not_retryable_until_definite_no_creation(self):
        self.prepare("novel_only")
        self.record("request_started")
        self.record("failed", no_thread_created=False, reason="timeout")
        self.assertEqual(self.slot()["status"], "unknown")
        with self.assertRaises(ConflictError):
            self.record("request_started")
        self.record("failed", no_thread_created=True, reason="host explicitly rejected before creation")
        self.assertEqual(self.slot()["next_action"], "create")
        self.record("request_started")

    def test_wrong_identity_revision_request_and_observation_leave_no_writes(self):
        self.prepare("novel_only")
        before = self.logical()
        with self.assertRaises((ValueError, ConflictError)):
            self.call("workspace.prepare", expected_project_id="OTHER", base_revision=1)
        with self.assertRaises(ConflictError):
            self.call("workspace.prepare", base_revision=0)
        with self.assertRaises(ConflictError):
            self.record("request_started", request_id="another-request")
        self.assertEqual(before, self.logical())

    def test_wrong_thread_project_or_late_observation_rejected_atomically(self):
        self.prepare("novel_only")
        self.created()
        before = self.logical()
        for obs in ({"thread_id": "other", "project_id": "TEST-WORKSPACE"},
                    {"thread_id": "host-thread-one", "project_id": "OTHER"},
                    {"thread_id": "host-thread-one", "project_id": "TEST-WORKSPACE", "observed_at": "2026-10-24T12:00:00+08:00"}):
            with self.assertRaises(ConflictError):
                self.record("catalog_bound", tool="film_projects", **obs)
        self.assertEqual(before, self.logical())

    def test_one_real_thread_cannot_fill_two_roles(self):
        self.prepare("novel_only")
        self.created()
        before = self.logical()
        with self.assertRaises(ConflictError):
            self.record("host_confirmed", "planning", thread_id="host-thread-one", title="不能复用给第二职责", origin="existing", tool="read_thread")
        self.assertEqual(before, self.logical())

    def test_route_change_retains_pending_and_reuses_shared_slots(self):
        first = self.prepare("novel_to_screen")
        self.record("request_started", "novel")
        self.record("queued", "novel", client_thread_id="novel-queued")
        next_view = self.prepare("screenplay")
        self.assertEqual(len(next_view["slots"]), 7)
        novel = next(s for s in next_view["retired_slots"] if s["role"] == "novel")
        self.assertEqual(novel["client_thread_id"], "novel-queued")
        self.assertEqual(first["slots"][0]["slot_id"], next_view["slots"][0]["slot_id"])
        restored = self.prepare("novel_to_screen")
        self.assertEqual(next(s for s in restored["slots"] if s["role"] == "novel")["status"], "queued")

    def test_successful_record_retry_uses_original_operation_receipt(self):
        self.prepare("novel_only")
        slot = self.slot()
        payload = {"expected_project_id": "TEST-WORKSPACE", "op_id": "claim-once", "base_revision": self.read()["revision"],
                   "slot_id": slot["slot_id"], "event": "request_started", "observation": {"request_id": slot["request_id"]}}
        original = self.r.dispatch("workspace.record", payload)
        self.record("unknown", reason="synthetic disconnect")
        self.assertEqual(original, self.r.dispatch("workspace.record", payload))
        self.assertEqual(self.slot()["status"], "unknown")

    def test_schemas_reject_unknown_fields_types_and_incomplete_host_claims(self):
        self.assertEqual(set(ACTION_SCHEMAS), {"workspace.read", "workspace.resolve", "workspace.prepare", "workspace.record"})
        base = {"op_id": "synthetic", "expected_project_id": "TEST-WORKSPACE", "base_revision": 0}
        for bad in ({**base, "base_revision": True}, {**base, "mode": "novel_only"}, {**base, "expected_project_id": "   "}):
            with self.assertRaises(ValueError):
                validate_workspace_payload("workspace.prepare", bad)
        with self.assertRaises(ValueError):
            validate_workspace_payload("workspace.read", {})
        host = {"request_id": "request", "source": "host_tool", "tool": "create_thread", "observed_at": "2026-10-25T12:00:00",
                "thread_id": "real-id", "title": "真实标题", "origin": "created"}
        for bad in (host, {**host, "observed_at": "2026-10-25T12:00:00+08:00", "approved": True}):
            with self.assertRaises(ValueError):
                validate_workspace_payload("workspace.record", {**base, "slot_id": "slot", "event": "host_confirmed", "observation": bad})


if __name__ == "__main__":
    unittest.main()

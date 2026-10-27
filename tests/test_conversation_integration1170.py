"""Independent public-interface tests; synthetic local fixtures, no host calls."""
from contextlib import closing
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from filmprod.core import Registry
from filmprod.conversations1170 import action_schemas
from plugin import mcp_server as server
import film as cli


SOURCE = Path(__file__).resolve().parents[1]


class ConversationIntegration1170(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="filmprod-TEST-conversation-integration1170-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "TEST-project"
        self.pid = "TEST-CONVERSATION1170"
        self.control = "TEST-control"
        self.client_project = "TEST-client-project"
        self.counter = 0
        self.env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                    "FILMPROD_CATALOG_PATH": str(self.base / "TEST-catalog.sqlite3")}
        environment = patch.dict(os.environ, self.env)
        environment.start()
        self.addCleanup(environment.stop)
        self.initialize(self.root, self.pid)
        self.db = self.root / ".project/registry.sqlite3"

    def initialize(self, root, pid):
        registry = Registry(root)
        try:
            registry.dispatch("project.init", {"op_id": "TEST-init", "project_id": pid,
                "title": "TEST synthetic conversation project", "test_only": True})
        finally:
            registry.close()

    def op(self):
        self.counter += 1
        return "TEST-operation-" + str(self.counter)

    def args(self, action, **payload):
        return {"root": str(self.root), "action": action,
                "payload": {"expected_project_id": self.pid, **payload}}

    def call(self, name, arguments, error=False, default_root=None):
        result = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}}, default_root)["result"]
        self.assertEqual(bool(result.get("isError")), error, result)
        if not error:
            self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        return result["structuredContent"]

    def read(self):
        return self.call("film_conversations", self.args("read"))

    def dispatch(self, action, **payload):
        return self.call("film_dispatch", self.args(action, **payload))

    def write(self, action, **payload):
        payload.setdefault("op_id", self.op())
        payload.setdefault("base_revision", self.read()["revision"])
        if action not in ("claim", "observe"):
            payload.setdefault("actor_thread_id", self.control)
        return self.call("film_conversations", self.args(action, **payload))

    def dump(self, root=None):
        database = (root or self.root) / ".project/registry.sqlite3"
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            # Registry initialization can reorder identical settings rows via
            # INSERT OR REPLACE; compare logical SQL records, not row order.
            return "\n".join(sorted(connection.iterdump()))

    def rows(self, table):
        self.assertIn(table, ("settings", "tasks", "threads", "artifacts", "decisions", "approved_segments"))
        with closing(sqlite3.connect(self.db.as_uri() + "?mode=ro", uri=True)) as connection:
            return connection.execute("SELECT * FROM " + table + " ORDER BY 1").fetchall()

    def auth(self, actions=None, scopes=None, threads=None):
        return {"quote": "TEST only: manage the explicitly selected project conversation flow",
                "reference": "TEST-user-message", "synthetic": True,
                "actions": actions or ["configure", "prepare", "decide", "accept", "bind_task",
                    "complete", "start", "continue", "create_thread", "send_message_to_thread", "archive"],
                "target": {"project_id": self.pid, "scopes": scopes or ["*"],
                           "thread_ids": threads or ["*"]}}

    def hierarchy(self, mode="novel_to_screen", configure=True, authorization=None):
        self.dispatch("project.workflow.set", op_id=self.op(), base_revision=0, mode=mode)
        workspace = self.call("film_workspace", self.args("prepare", op_id=self.op(), base_revision=0))
        self.parents = {}
        for slot in workspace["slots"]:
            thread_id = "TEST-" + slot["role"]
            self.parents[slot["role"]] = thread_id
            observations = [
                ("request_started", {"request_id": slot["request_id"]}),
                ("host_confirmed", {"thread_id": thread_id, "title": "TEST " + slot["role"], "origin": "created"}),
                ("catalog_bound", {"thread_id": thread_id, "project_id": self.pid}),
                ("client_project_observed", {"thread_id": thread_id, "client_project_id": self.client_project})]
            for event, observation in observations:
                if event != "request_started":
                    observation = {"request_id": slot["request_id"], "source": "host_tool",
                        "tool": "film_projects" if event == "catalog_bound" else "read_thread" if event == "client_project_observed" else "create_thread",
                        "observed_at": "2026-10-27T12:00:00+08:00", **observation}
                self.call("film_workspace", self.args("record", op_id=self.op(), base_revision=workspace["revision"],
                    slot_id=slot["slot_id"], event=event, observation=observation))
                workspace = self.call("film_workspace", self.args("read"))
        if configure:
            self.write("configure", enabled=True, authorization=authorization or self.auth())
        return workspace

    def planning(self, aid="TEST-IDEA-RECORD", scope="idea/TEST"):
        self.dispatch("planning.record", op_id=self.op(), record_id=aid, scope=scope, base_version=0,
            change={"record_kind": "idea", "title": "TEST 雨夜修伞", "entries": [{"kind": "original_input",
                "text": "TEST 女儿在雨夜与母亲修一把旧伞。", "source": {"type": "synthetic_user_message", "reference": "TEST-turn"}}]})
        self.dispatch("planning.record", op_id=self.op(), record_id=aid, scope=scope, base_version=1,
            change={"append": {"branches": [{"id": "TEST-BRANCH", "title": "TEST 家庭短篇", "status": "候选"}]}})
        return {"artifact_id": aid, "version": 2}

    def idea(self, topic_id="TEST-IDEA", scope="idea/TEST", planning_ref=None, **extra):
        reference = planning_ref or self.planning(scope=scope)
        return self.write("prepare", topic_id=topic_id, kind="idea", title="TEST 雨夜修伞讨论", scope=scope,
                          planning_ref=reference, **extra)

    def observe(self, request, status="host_accepted", thread_id=None, **extra):
        current = next(item for item in self.read()["outbox"] if item["request_id"] == request["request_id"])
        observation = {"source": "host_tool", "tool": "set_thread_archived" if current["tool"] == "archive" else current["tool"],
            "observed_at": "2026-10-27T12:01:00+08:00", "reference": "TEST synthetic observation",
            "project_id": self.pid, "topic_id": current["topic_id"], "scope": current["scope"],
            "request_id": current["request_id"], "attempt": current["attempt"]}
        if status == "host_accepted":
            observation.update(thread_id=thread_id or current["target_thread_id"], title="TEST observed chat",
                client_project_id=self.client_project, project_root=str(self.root))
        observation.update(extra)
        return self.write("observe", request_id=current["request_id"], status=status, observation=observation)

    def host_accept(self, request, thread_id=None):
        claimed = self.write("claim", request_id=request["request_id"])
        self.assertTrue(claimed["dispatch_allowed"])
        return self.observe(request, thread_id=thread_id)

    def rejection(self, action, **payload):
        payload.setdefault("op_id", self.op())
        payload.setdefault("base_revision", self.read()["revision"])
        if action not in ("claim", "observe"):
            payload.setdefault("actor_thread_id", self.control)
        before = self.dump()
        result = self.call("film_conversations", self.args(action, **payload), error=True)
        self.assertEqual(self.dump(), before, result)
        return result

    def test_stdio_discovery_and_old_project_read_do_not_enable_or_migrate(self):
        before = self.db.read_bytes()
        requests = [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "film_conversations", "arguments": self.args("read")}}]
        process = subprocess.run([sys.executable, "-B", "-X", "utf8", str(SOURCE / "plugin/mcp_server.py")],
            cwd=SOURCE, env=self.env,
            input="".join(json.dumps(request) + "\n" for request in requests).encode(),
            capture_output=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        definitions = responses[0]["result"]["tools"]
        matches = [tool for tool in definitions if tool["name"] == "film_conversations"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["_meta"]["ui"]["visibility"], ["model"])
        response = responses[1]["result"]
        self.assertFalse(response.get("isError"), response)
        self.assertFalse(response["structuredContent"]["enabled"])
        self.assertEqual(self.db.read_bytes(), before)
        self.assertFalse(any(key == "conversation/v1" for key, _ in self.rows("settings")))

    def test_all_read_entrypoints_are_readonly_and_have_no_catalog_side_effect(self):
        before = self.dump()
        with patch.object(Registry, "__init__", side_effect=AssertionError("Read opened writable Registry")):
            self.read()
            self.dispatch("conversation.read")
            self.call("film_board_manage", self.args("conversation.read"))
            self.call("film_board_manage", self.args("snapshot"))
            self.call("film_context", {"root": str(self.root), "expected_project_id": self.pid, "mode": "summary"})
        self.assertEqual(self.dump(), before)
        self.assertFalse((self.base / "TEST-catalog.sqlite3").exists())

    def test_action_help_exposes_exact_new_schemas_without_project_access(self):
        with patch.object(server, "checked_project_root", side_effect=AssertionError("Help touched a project")), \
             patch.object(Registry, "__init__", side_effect=AssertionError("Help opened writable Registry")), \
             patch.object(Registry, "open_readonly", side_effect=AssertionError("Help opened readonly Registry")):
            for action, schema in action_schemas().items():
                with self.subTest(action=action):
                    result = self.call("film_action_help", {"action": action})
                    self.assertFalse(result["executed"])
                    self.assertTrue(result["read_only"])
                    self.assertEqual(result["inputSchema"], schema)
                    self.assertEqual(result["preferred_tool"], "film_conversations")

    def test_strict_shape_and_conditional_validation_precede_project_lookup(self):
        actor = {"op_id": "TEST-invalid", "base_revision": 0, "actor_thread_id": self.control}
        observation = {"source": "host_tool", "tool": "create_thread", "observed_at": "2026-10-27T12:00:00",
            "reference": "TEST-host-observation", "project_id": self.pid, "topic_id": "TEST-idea",
            "scope": "idea/TEST", "request_id": "TEST-request", "attempt": 1, "reason": "TEST unknown"}
        invalid = [self.args("read", unexpected=True),
            self.args("configure", **{**actor, "base_revision": True}, enabled=True, authorization=self.auth()),
            self.args("configure", **actor, enabled=True, authorization={**self.auth(), "unexpected": True}),
            self.args("prepare", **actor, topic_id="TEST-idea", kind="idea", title="TEST", scope="idea/TEST",
                planning_ref={"artifact_id": "TEST-planning", "version": True}),
            self.args("prepare", **actor, topic_id="TEST-execution", kind="execution", title="TEST", scope="chapter/1",
                planning_ref={"artifact_id": "TEST-planning", "version": 1}),
            self.args("accept", **actor, handoff_id="TEST-handoff", status="ready", brief="TEST", questions=["unanswered"],
                inputs=[{"artifact_id": "TEST-planning", "version": 1}]),
            self.args("accept", **actor, handoff_id="TEST-handoff", status="clarifying", questions=[]),
            self.args("observe", op_id="TEST-observe", base_revision=0, request_id="TEST-request",
                status="unknown", observation=observation),
            self.args("decide", **actor, topic_id="TEST-idea", decision="retain", reason="TEST", archive_chat=True)]
        with patch.object(server, "checked_project_root", side_effect=AssertionError("Invalid input touched a project")):
            for arguments in invalid:
                with self.subTest(arguments=arguments):
                    result = self.call("film_conversations", arguments, error=True)
                    self.assertEqual(result["error"]["type"], "ValueError", result)
                    legacy = {**arguments, "action": "conversation." + arguments["action"]}
                    result = self.call("film_dispatch", legacy, error=True)
                    self.assertEqual(result["error"]["type"], "ValueError", result)

    def test_explicit_root_and_project_identity_are_required(self):
        before = self.dump()
        for tool, action in (("film_conversations", "read"), ("film_dispatch", "conversation.read")):
            with self.subTest(tool=tool):
                self.call(tool, {"action": action, "payload": {"expected_project_id": self.pid}},
                          error=True, default_root=str(self.root))
                self.call(tool, {"root": str(self.root), "action": action, "payload": {}}, error=True)
                wrong = self.args(action); wrong["payload"]["expected_project_id"] = "TEST-OTHER"
                self.call(tool, wrong, error=True)
                missing = self.args(action); missing["root"] = str(self.base / "TEST-missing")
                self.call(tool, missing, error=True)
                relative = self.args(action); relative["root"] = "TEST-relative"
                self.call(tool, relative, error=True)
        self.assertEqual(self.dump(), before)
        self.assertFalse((self.base / "TEST-missing").exists())

    def test_board_rejects_every_new_write_action_before_lookup(self):
        before = self.dump()
        with patch.object(server, "checked_project_root", side_effect=AssertionError("Board write looked up project")):
            for action in action_schemas():
                if action == "conversation.read":
                    continue
                with self.subTest(action=action):
                    value = self.call("film_board_manage", self.args(action, op_id="TEST-forbidden"), error=True)
                    self.assertEqual(value["error"]["type"], "ValueError")
        self.assertEqual(self.dump(), before)

    def test_schema_one_status_query_is_rejected_without_migration(self):
        old_root = self.base / "TEST-schema-one"
        database = old_root / ".project/registry.sqlite3"
        database.parent.mkdir(parents=True)
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            connection.execute("INSERT INTO settings VALUES('schema_version','1')")
            connection.execute("INSERT INTO settings VALUES('project',?)", (json.dumps({
                "project_id": "TEST-OLD", "title": "TEST schema one", "test_only": True}),))
            connection.commit()
        before = database.read_bytes()
        for tool, action in (("film_conversations", "read"), ("film_dispatch", "conversation.read"),
                             ("film_board_manage", "conversation.read")):
            self.call(tool, {"root": str(old_root), "action": action,
                "payload": {"expected_project_id": "TEST-OLD"}}, error=True)
        self.assertEqual(database.read_bytes(), before)
        self.assertEqual(sorted(path.name for path in database.parent.iterdir()), ["registry.sqlite3"])

    def test_cli_invalid_conversation_payload_is_validated_before_writable_open(self):
        invalid = {"expected_project_id": self.pid, "op_id": "TEST-cli-invalid", "base_revision": True,
                   "actor_thread_id": self.control, "enabled": True, "authorization": self.auth()}
        argv = [str(SOURCE / "film.py"), "--root", str(self.root), "dispatch", "conversation.configure", "--file", "-"]
        before = self.dump()
        with patch.object(sys, "argv", argv), patch.object(sys, "stdin", io.StringIO(json.dumps(invalid))), \
             patch.object(sys, "stderr", io.StringIO()), \
             patch.object(Registry, "__init__", side_effect=AssertionError("Invalid CLI payload opened writable Registry")):
            self.assertEqual(cli.main(), 1)
        self.assertEqual(self.dump(), before)

    def test_real_cli_read_preserves_old_project_bytes(self):
        before = self.db.read_bytes()
        process = subprocess.run([sys.executable, "-B", "-X", "utf8", str(SOURCE / "film.py"),
            "--root", str(self.root), "dispatch", "conversation.read", "--file", "-"],
            input=json.dumps({"expected_project_id": self.pid}).encode(), capture_output=True,
            cwd=SOURCE, env=self.env, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertFalse(json.loads(process.stdout)["enabled"])
        self.assertEqual(self.db.read_bytes(), before)

    def test_cli_wrong_identity_is_rejected_before_writable_open(self):
        wrong = {"expected_project_id": "TEST-WRONG-PROJECT", "op_id": "TEST-cli-wrong-id", "base_revision": 0,
                 "actor_thread_id": self.control, "enabled": True, "authorization": self.auth()}
        argv = [str(SOURCE / "film.py"), "--root", str(self.root), "dispatch", "conversation.configure", "--file", "-"]
        before = self.dump()
        with patch.object(sys, "argv", argv), patch.object(sys, "stdin", io.StringIO(json.dumps(wrong))), \
             patch.object(sys, "stderr", io.StringIO()), \
             patch.object(Registry, "__init__", side_effect=AssertionError("Wrong CLI identity opened writable Registry")):
            self.assertEqual(cli.main(), 1)
        self.assertEqual(self.dump(), before)

    def test_configuration_keeps_existing_tasks_route_schema_and_methods(self):
        self.hierarchy(configure=False)
        old = self.dispatch("task.create", op_id=self.op(), task_id="TEST-OLD-DIRECTOR", artifact_id="TEST-DIRECTION",
            title="TEST existing task", module="director", scope="scene/old", thread_id=self.parents["director"],
            inputs=[], must_keep=[], allowed_changes=[], requirements=["TEST full shot design"])
        tasks = self.rows("tasks")
        settings = dict(self.rows("settings"))
        module_files = {path.relative_to(SOURCE / "modules").as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in (SOURCE / "modules").rglob("*") if path.is_file()}
        self.write("configure", enabled=True, authorization=self.auth())
        self.assertEqual(self.rows("tasks"), tasks)
        after = dict(self.rows("settings"))
        for key in ("schema_version", "project", "workspace/v1"):
            self.assertEqual(after[key], settings[key])
        self.assertIn("conversation/v1", after)
        self.assertEqual(module_files, {path.relative_to(SOURCE / "modules").as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in (SOURCE / "modules").rglob("*") if path.is_file()})
        resumed = self.dispatch("task.resume", task_id="TEST-OLD-DIRECTOR")
        self.assertEqual(resumed["task"]["execution_lock"], old["execution_lock"])
        self.assertFalse(self.read()["host_execution"])

    def test_one_idea_is_one_topic_and_claim_replay_never_dispatches_again(self):
        self.hierarchy()
        initial_threads = self.rows("threads")
        prepared = self.idea()
        state = self.read()
        self.assertEqual(len(state["topics"]), 1)
        self.assertEqual(len(state["outbox"]), 1)
        self.assertEqual(self.rows("threads"), initial_threads)
        self.assertEqual(self.rows("tasks"), [])
        request = prepared["request"]
        arguments = self.args("claim", op_id=self.op(), base_revision=state["revision"], request_id=request["request_id"])
        claimed = self.call("film_conversations", arguments)
        self.assertTrue(claimed["dispatch_allowed"])
        repeated = self.call("film_conversations", arguments)
        self.assertFalse(repeated["dispatch_allowed"])
        self.assertTrue(repeated["replayed"])
        legacy_replay = self.call("film_dispatch", {**arguments, "action": "conversation.claim"})
        self.assertFalse(legacy_replay["dispatch_allowed"])
        self.assertTrue(legacy_replay["replayed"])
        self.observe(request, status="unknown", reason="TEST host result lost")
        self.assertFalse(self.call("film_conversations", arguments)["dispatch_allowed"])
        self.assertFalse(self.write("claim", request_id=request["request_id"])["dispatch_allowed"])
        reused = self.idea(planning_ref={"artifact_id": "TEST-IDEA-RECORD", "version": 2})
        self.assertTrue(reused["reused"])
        self.assertEqual(len(self.read()["outbox"]), 1)
        self.assertEqual(self.read()["outbox"][0]["status"], "unknown")
        self.assertEqual(self.rows("threads"), initial_threads)

    def test_queued_reference_is_not_a_real_chat_and_wrong_host_identity_rolls_back(self):
        self.hierarchy()
        prepared = self.idea(); request = prepared["request"]
        self.write("claim", request_id=request["request_id"])
        self.observe(request, status="queued", client_thread_id="TEST-queued-only")
        self.assertIsNone(self.read()["topics"][0]["thread_id"])
        for change in ({"thread_id": "TEST-queued-only"}, {"project_id": "TEST-OTHER"},
                       {"client_project_id": "TEST-other-client"}, {"project_root": str(self.base / "TEST-other-root")}):
            current = next(item for item in self.read()["outbox"] if item["request_id"] == request["request_id"])
            observation = {"source": "host_tool", "tool": "create_thread", "observed_at": "2026-10-27T12:01:00+08:00",
                "reference": "TEST bad receipt", "project_id": self.pid, "topic_id": "TEST-IDEA", "scope": "idea/TEST",
                "request_id": request["request_id"], "attempt": current["attempt"], "thread_id": "TEST-idea-chat",
                "title": "TEST", "client_project_id": self.client_project, "project_root": str(self.root), **change}
            self.rejection("observe", request_id=request["request_id"], status="host_accepted", observation=observation)
        accepted = self.observe(request, thread_id="TEST-idea-chat")
        self.assertEqual(accepted["topic"]["thread_id"], "TEST-idea-chat")
        self.assertFalse(accepted["business_processed"])
        self.assertEqual(self.rows("tasks"), [])

    def test_retain_recycle_restore_preserve_planning_and_separate_host_archival(self):
        self.hierarchy()
        prepared = self.idea(); self.host_accept(prepared["request"], "TEST-idea-chat")
        original = self.rows("artifacts")
        self.write("decide", topic_id="TEST-IDEA", decision="retain", reason="TEST keep for later")
        recycled = self.write("decide", topic_id="TEST-IDEA", decision="recycle", reason="TEST reversible delete", archive_chat=True)
        self.assertEqual(recycled["topic"]["status"], "recycled")
        self.assertNotIn("host_archived_observed", recycled["topic"])
        archive = recycled["request"]
        self.write("claim", request_id=archive["request_id"])
        self.observe(archive, status="unknown", reason="TEST archive reply missing")
        self.rejection("decide", topic_id="TEST-IDEA", decision="restore", reason="TEST restore", archive_chat=True)
        archived = self.observe(archive)
        self.assertTrue(archived["topic"]["host_archived_observed"])
        restored = self.write("decide", topic_id="TEST-IDEA", decision="restore", reason="TEST restore", archive_chat=True)
        self.assertEqual(restored["topic"]["status"], "retained")
        self.assertTrue(restored["topic"]["host_archived_observed"])
        self.assertFalse(restored["request"]["payload"]["archived"])
        unarchived = self.host_accept(restored["request"])
        self.assertFalse(unarchived["topic"]["host_archived_observed"])
        self.assertEqual(self.rows("artifacts"), original)
        self.assertEqual(self.rows("decisions"), [])
        self.assertEqual(self.rows("tasks"), [])
        self.assertEqual(self.read()["topics"][0]["thread_id"], "TEST-idea-chat")

    def test_distinct_projects_cannot_share_authorization_or_outbox_identity(self):
        self.hierarchy()
        prepared = self.idea()
        other_root = self.base / "TEST-independent-project"
        self.initialize(other_root, "TEST-INDEPENDENT")
        other_before = self.dump(other_root); before = self.dump()
        self.call("film_conversations", {"root": str(other_root), "action": "claim", "payload": {
            "op_id": "TEST-wrong-project-claim", "expected_project_id": self.pid, "base_revision": 0,
            "request_id": prepared["request"]["request_id"]}}, error=True)
        wrong_auth = self.auth(); wrong_auth["target"]["project_id"] = "TEST-INDEPENDENT"
        self.rejection("configure", enabled=True, authorization=wrong_auth)
        self.assertEqual(self.dump(), before)
        self.assertEqual(self.dump(other_root), other_before)

    def test_one_time_prepare_authorization_does_not_require_global_expansion(self):
        limited = self.auth(actions=["configure"], scopes=["project"], threads=[self.control])
        self.hierarchy(authorization=limited)
        reference = self.planning()
        prepared = self.idea(planning_ref=reference,
            authorization=self.auth(actions=["prepare", "create_thread"], scopes=["idea/TEST"], threads=[self.parents["planning"]]))
        claimed = self.write("claim", request_id=prepared["request"]["request_id"])
        self.assertTrue(claimed["dispatch_allowed"])
        self.assertEqual(self.read()["authorization"]["actions"], ["configure"])
        self.rejection("decide", topic_id="TEST-IDEA", decision="retain", reason="TEST no decision authorization")

    def test_handoff_clarification_execution_and_completion_use_exact_task_output(self):
        self.hierarchy()
        prepared = self.idea(); source_ref = prepared["topic"]["planning_ref"]
        self.host_accept(prepared["request"], "TEST-idea-chat")
        discussion = self.write("start", actor_thread_id=self.parents["planning"], topic_id="TEST-IDEA")
        self.host_accept(discussion["request"])
        developed = self.write("decide", topic_id="TEST-IDEA", decision="develop", reason="TEST selected novel branch",
            branch_id="TEST-BRANCH", target_role="novel")
        handoff_id = developed["handoff"]["handoff_id"]
        accepted_message = self.host_accept(developed["request"])
        self.assertFalse(accepted_message["business_processed"])
        self.assertEqual(self.read()["handoffs"][0]["status"], "offered")
        self.rejection("prepare", topic_id="TEST-EXEC", kind="execution", title="TEST chapter", scope="chapter/1",
                       handoff_id=handoff_id, target_artifact_id="TEST-NOVEL")
        receiver = self.parents["novel"]
        self.write("accept", handoff_id=handoff_id, actor_thread_id=receiver, status="received")
        clarifying = self.write("accept", handoff_id=handoff_id, actor_thread_id=receiver, status="clarifying",
                               questions=["TEST produce outline or complete prose?"])
        self.assertEqual(clarifying["handoff"]["status"], "clarifying")
        self.assertEqual(self.read()["handoffs"][0]["source_ref"], source_ref)
        self.rejection("accept", handoff_id=handoff_id, actor_thread_id=receiver, status="ready", brief="TEST full prose",
            inputs=[{"artifact_id": source_ref["artifact_id"], "version": 1}])
        ready = self.write("accept", handoff_id=handoff_id, actor_thread_id=receiver, status="ready",
                           brief="TEST write the full first chapter with visible actions", inputs=[source_ref])
        self.assertEqual(ready["handoff"]["status"], "ready")
        execution = self.write("prepare", actor_thread_id=receiver, topic_id="TEST-EXEC", kind="execution",
            title="TEST chapter", scope="chapter/1", handoff_id=handoff_id, target_artifact_id="TEST-NOVEL")
        self.host_accept(execution["request"], "TEST-execution-chat")
        unrelated = self.dispatch("artifact.save", op_id=self.op(), artifact_id="TEST-UNRELATED", kind="novel",
            scope="chapter/other", base_version=0, content="TEST unrelated complete text")
        task = self.dispatch("task.create", op_id=self.op(), task_id="TEST-WRITE", artifact_id="TEST-NOVEL",
            title="TEST full first chapter", module="story", scope="chapter/1", thread_id="TEST-execution-chat",
            inputs=[source_ref], must_keep=["TEST chosen premise"], allowed_changes=["TEST prose detail"], requirements=["TEST full chapter"])
        self.write("bind_task", actor_thread_id="TEST-execution-chat", topic_id="TEST-EXEC", task_id=task["task_id"])
        started = self.write("start", actor_thread_id=receiver, topic_id="TEST-EXEC")
        self.assertEqual(started["request"]["payload"]["task_id"], task["task_id"])
        self.host_accept(started["request"])
        self.rejection("continue", actor_thread_id=receiver, topic_id="TEST-EXEC", brief="TEST improperly start another round",
                       inputs=[source_ref])
        wrong_ref = {"artifact_id": "TEST-UNRELATED", "version": unrelated["artifact"]["version"]}
        self.rejection("complete", actor_thread_id="TEST-execution-chat", topic_id="TEST-EXEC", task_id=task["task_id"],
                       output_ref=wrong_ref, summary="TEST pretending another artifact is finished output")
        saved = self.dispatch("task.checkpoint", op_id=self.op(), task_id=task["task_id"],
            draft="TEST 母亲掐住断伞骨，女儿把铜丝穿过接缝。她们一起撑开伞，雨水落到门外。",
            completed=["TEST full chapter"], decisions=[], unresolved=[], next_step="TEST submit exact checkpoint")
        checkpoint = saved["checkpoint"]
        submitted = self.dispatch("task.submit_checkpoint", op_id=self.op(), task_id=task["task_id"], artifact_id="TEST-NOVEL",
            kind="novel", base_version=0, checkpoint_id=checkpoint["checkpoint_id"],
            expected_draft_sha256=checkpoint["draft_sha256"])
        self.rejection("complete", actor_thread_id="TEST-execution-chat", topic_id="TEST-EXEC", task_id=task["task_id"],
                       output_ref=wrong_ref, summary="TEST wrong submitted output")
        output_ref = {key: submitted["artifact"][key] for key in ("artifact_id", "version")}
        completed = self.write("complete", actor_thread_id="TEST-execution-chat", topic_id="TEST-EXEC", task_id=task["task_id"],
                               output_ref=output_ref, summary="TEST full candidate saved and submitted")
        self.assertEqual(completed["topic"]["output_ref"], output_ref)
        self.assertEqual(completed["topic"]["output_sha256"], submitted["artifact"]["sha256"])
        self.assertFalse(completed["notification_sent"])
        self.assertEqual({request["target_thread_id"] for request in completed["requests"]}, {receiver, self.control})
        self.assertEqual(self.rows("approved_segments"), [])
        self.assertEqual(self.rows("decisions"), [])
        for request in completed["requests"]:
            observed = self.host_accept(request)
            self.assertFalse(observed["business_processed"])
        final = self.read()
        self.assertFalse(final["host_accepted_is_business_processed"])
        self.assertEqual(len(final["topics"]), 2)
        self.assertEqual(len(self.rows("tasks")), 1)
        self.assertEqual(self.dispatch("task.resume", task_id=task["task_id"])["task"]["execution_lock"], task["execution_lock"])
        continued = self.write("continue", actor_thread_id=receiver, topic_id="TEST-EXEC",
                               brief="TEST requested revision of the submitted chapter", inputs=[output_ref])
        self.assertFalse(continued["new_chat_created"])
        self.assertEqual(continued["topic"]["thread_id"], "TEST-execution-chat")
        self.assertEqual(continued["topic"]["round"], 2)
        self.assertIsNone(continued["topic"]["task_id"])
        self.assertEqual(continued["topic"]["task_history"][-1]["task_id"], task["task_id"])
        self.assertEqual(len(self.rows("tasks")), 1)

    def test_selected_planning_version_can_execute_after_independent_discussion_update(self):
        self.hierarchy()
        prepared = self.idea(); source_ref = prepared["topic"]["planning_ref"]
        self.host_accept(prepared["request"], "TEST-idea-chat")
        developed = self.write("decide", topic_id="TEST-IDEA", decision="develop", reason="TEST explicitly select exact v2 branch",
                               branch_id="TEST-BRANCH", target_role="novel")
        self.host_accept(developed["request"])
        self.dispatch("planning.record", op_id=self.op(), record_id=source_ref["artifact_id"], scope="idea/TEST", base_version=2,
            change={"entries": [{"kind": "suggestion", "text": "TEST an independent, unselected v3 discussion"}]})
        handoff_id = developed["handoff"]["handoff_id"]
        receiver = self.parents["novel"]
        self.assertEqual(self.read()["handoffs"][0]["source_ref"], source_ref)
        self.write("accept", handoff_id=handoff_id, actor_thread_id=receiver, status="ready",
                   brief="TEST write exactly the selected v2 premise; later discussion remains separate", inputs=[source_ref])
        execution = self.write("prepare", actor_thread_id=receiver, topic_id="TEST-FROZEN-EXEC", kind="execution",
            title="TEST frozen selected draft", scope="chapter/frozen", handoff_id=handoff_id, target_artifact_id="TEST-FROZEN-NOVEL")
        self.host_accept(execution["request"], "TEST-frozen-execution-chat")
        task = self.dispatch("task.create", op_id=self.op(), task_id="TEST-FROZEN-WRITE", artifact_id="TEST-FROZEN-NOVEL",
            title="TEST use exact chosen discussion", module="story", scope="chapter/frozen", thread_id="TEST-frozen-execution-chat",
            inputs=[source_ref], must_keep=["TEST selected v2 premise"], allowed_changes=[], requirements=["TEST full prose"])
        self.assertIn(source_ref, task["inputs"])
        self.assertNotIn({"artifact_id": source_ref["artifact_id"], "version": 3}, task["inputs"])
        provenance = task["conversation_source_reference"]
        self.assertEqual(provenance["source_ref"]["artifact_id"], source_ref["artifact_id"])
        self.assertEqual(provenance["source_ref"]["version"], 2)
        self.assertEqual(provenance["branch_id"], "TEST-BRANCH")
        original_source = self.dispatch("artifact.get", artifact_id=source_ref["artifact_id"], version=2)
        self.assertEqual(provenance["source_ref"]["sha256"], original_source["sha256"])
        forged = deepcopy(provenance); forged["branch_id"] = "TEST-FORGED-BRANCH"
        before = self.dump()
        self.call("film_dispatch", self.args("artifact.save", op_id=self.op(), artifact_id="TEST-FORGED-SOURCE", kind="novel",
            scope="chapter/forged", base_version=0, content="TEST forged frozen-source metadata",
            metadata={"conversation_source_reference": forged}), error=True)
        self.assertEqual(self.dump(), before)
        self.call("film_dispatch", self.args("task.submit", op_id=self.op(), task_id=task["task_id"],
            artifact_id="TEST-FROZEN-NOVEL", kind="novel", base_version=0, content="TEST malicious source override",
            metadata={"conversation_source_reference": forged}), error=True)
        self.assertEqual(self.dump(), before)
        self.write("bind_task", actor_thread_id="TEST-frozen-execution-chat", topic_id="TEST-FROZEN-EXEC", task_id=task["task_id"])
        started = self.write("start", actor_thread_id=receiver, topic_id="TEST-FROZEN-EXEC")
        self.host_accept(started["request"])
        saved = self.dispatch("task.checkpoint", op_id=self.op(), task_id=task["task_id"],
            draft="TEST 冻结的第二版故事：母亲扶住伞骨，女儿拧紧铜丝，撑开的伞挡住屋檐落水。",
            completed=["TEST exact chosen premise expanded"], decisions=[], unresolved=[], next_step="TEST submit")
        checkpoint = saved["checkpoint"]
        submitted = self.dispatch("task.submit_checkpoint", op_id=self.op(), task_id=task["task_id"],
            artifact_id="TEST-FROZEN-NOVEL", kind="novel", base_version=0,
            checkpoint_id=checkpoint["checkpoint_id"], expected_draft_sha256=checkpoint["draft_sha256"])
        artifact = self.dispatch("artifact.get", artifact_id=submitted["artifact"]["artifact_id"],
                                 version=submitted["artifact"]["version"])
        self.assertNotIn(source_ref, artifact["deps"])
        self.assertEqual(artifact["metadata"]["conversation_source_reference"], provenance)
        self.dispatch("content.approve", op_id=self.op(), artifact_id=artifact["artifact_id"], version=artifact["version"],
            scope=artifact["scope"], evidence="TEST synthetic selected source output acceptance", actor="test", synthetic=True)
        output_ref = {key: artifact[key] for key in ("artifact_id", "version")}
        downstream = self.dispatch("task.create", op_id=self.op(), task_id="TEST-AFTER-FROZEN", artifact_id="TEST-DIRECTION-AFTER",
            title="TEST downstream can use adopted output", module="director", scope="scene/after-frozen",
            thread_id=self.parents["director"], inputs=[output_ref], must_keep=[], allowed_changes=[], requirements=[])
        self.assertEqual(downstream["inputs"], [output_ref])

    def test_ordinary_planning_input_has_no_implicit_frozen_source_exemption(self):
        self.hierarchy()
        source_ref = self.planning()
        execution = self.write("prepare", actor_thread_id=self.parents["novel"], topic_id="TEST-DIRECT-OLD-PLAN", kind="execution",
            title="TEST direct planning input", scope="chapter/direct-old", target_role="novel", target_artifact_id="TEST-DIRECT-OLD",
            direct_brief="TEST direct request with ordinary dependency", inputs=[source_ref])
        self.host_accept(execution["request"], "TEST-direct-old-chat")
        self.dispatch("planning.record", op_id=self.op(), record_id=source_ref["artifact_id"], scope="idea/TEST", base_version=2,
            change={"entries": [{"kind": "suggestion", "text": "TEST ordinary input changed"}]})
        before = self.dump()
        self.call("film_dispatch", self.args("task.create", op_id=self.op(), task_id="TEST-DIRECT-OLD-TASK", artifact_id="TEST-DIRECT-OLD",
            title="TEST must reject stale ordinary input", module="story", scope="chapter/direct-old", thread_id="TEST-direct-old-chat",
            inputs=[source_ref], must_keep=[], allowed_changes=[], requirements=[]), error=True)
        self.assertEqual(self.dump(), before)

    def test_handoff_freezes_only_selected_idea_and_rejects_changed_script_dependency(self):
        self.hierarchy()
        idea = self.idea(); source_ref = idea["topic"]["planning_ref"]
        self.host_accept(idea["request"], "TEST-idea-chat")
        script = self.dispatch("artifact.save", op_id=self.op(), artifact_id="TEST-EXTRA-SCRIPT", kind="script", scope="episode/input",
                              base_version=0, content="TEST exact supplemental script v1")["artifact"]
        script_ref = {key: script[key] for key in ("artifact_id", "version")}
        developed = self.write("decide", topic_id="TEST-IDEA", decision="develop", reason="TEST chosen premise",
                               branch_id="TEST-BRANCH", target_role="novel")
        self.host_accept(developed["request"])
        receiver = self.parents["novel"]
        self.write("accept", actor_thread_id=receiver, handoff_id=developed["handoff"]["handoff_id"], status="ready",
                   brief="TEST use chosen idea and current script", inputs=[source_ref, script_ref])
        execution = self.write("prepare", actor_thread_id=receiver, topic_id="TEST-WITH-SCRIPT", kind="execution", title="TEST source mix",
            scope="chapter/mixed", handoff_id=developed["handoff"]["handoff_id"], target_artifact_id="TEST-MIXED-NOVEL")
        self.host_accept(execution["request"], "TEST-mixed-chat")
        self.dispatch("artifact.save", op_id=self.op(), artifact_id=script_ref["artifact_id"], kind="script", scope="episode/input",
                      base_version=1, content="TEST changed supplemental script v2")
        before = self.dump()
        self.call("film_dispatch", self.args("task.create", op_id=self.op(), task_id="TEST-MIXED-TASK", artifact_id="TEST-MIXED-NOVEL",
            title="TEST script freshness must remain enforced", module="story", scope="chapter/mixed", thread_id="TEST-mixed-chat",
            inputs=[source_ref, script_ref], must_keep=[], allowed_changes=[], requirements=[]), error=True)
        self.assertEqual(self.dump(), before)

    def test_direct_writer_request_needs_no_fake_idea_and_rejects_controller_task(self):
        self.hierarchy(mode="screenplay")
        payload = {"op_id": self.op(), "task_id": "TEST-WRONG-CONTROLLER-TASK", "artifact_id": "TEST-SCRIPT", "title": "TEST",
            "module": "script", "scope": "episode/1", "thread_id": self.parents["script"], "inputs": [],
            "must_keep": [], "allowed_changes": [], "requirements": ["TEST full script"]}
        before = self.dump()
        self.call("film_dispatch", self.args("task.create", **payload), error=True)
        self.assertEqual(self.dump(), before)
        direct = self.write("prepare", actor_thread_id=self.parents["script"], topic_id="TEST-DIRECT", kind="execution",
            title="TEST direct script", scope="episode/1", target_role="script", target_artifact_id="TEST-SCRIPT",
            direct_brief="TEST directly write first episode from the clear user request", inputs=[])
        self.assertEqual(len(self.read()["topics"]), 1)
        self.assertEqual(self.read()["topics"][0]["kind"], "execution")
        self.assertEqual(self.read()["handoffs"], [])
        self.assertEqual(self.rows("artifacts"), [])
        self.assertEqual(self.rows("tasks"), [])
        self.assertEqual(direct["request"]["tool"], "create_thread")

    def test_execution_topic_rejects_wrong_professional_task_module(self):
        self.hierarchy(mode="novel_only")
        execution = self.write("prepare", actor_thread_id=self.parents["novel"], topic_id="TEST-NOVEL-EXEC", kind="execution",
            title="TEST novel prose", scope="chapter/1", target_role="novel", target_artifact_id="TEST-NOVEL",
            direct_brief="TEST full novel chapter", inputs=[])
        self.host_accept(execution["request"], "TEST-novel-execution")
        before = self.dump()
        self.call("film_dispatch", self.args("task.create", op_id=self.op(), task_id="TEST-WRONG-METHOD", artifact_id="TEST-NOVEL",
            title="TEST wrong director task", module="director", scope="chapter/1", thread_id="TEST-novel-execution",
            inputs=[], must_keep=[], allowed_changes=[], requirements=["TEST director plan"]), error=True)
        self.assertEqual(self.dump(), before)
        self.assertEqual(self.rows("tasks"), [])

        # Corrupt only this isolated TEST fixture to represent a legacy/imported
        # task that predates the new create guard. Binding must still reject it.
        legacy = self.dispatch("task.create", op_id=self.op(), task_id="TEST-LEGACY-DIRECTOR", artifact_id="TEST-LEGACY-DIRECTION",
            title="TEST legacy director", module="director", scope="scene/legacy", thread_id="TEST-legacy-director-chat",
            inputs=[], must_keep=[], allowed_changes=[], requirements=["TEST director plan"])
        forged = deepcopy(legacy)
        forged.update(task_id="TEST-FORGED-OLD", artifact_id="TEST-NOVEL", scope="chapter/1", thread_id="TEST-novel-execution")
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute("INSERT INTO tasks(task_id,data) VALUES(?,?)", (forged["task_id"], json.dumps(forged)))
            connection.commit()
        rejected = self.rejection("bind_task", actor_thread_id="TEST-novel-execution", topic_id="TEST-NOVEL-EXEC",
                                  task_id=forged["task_id"])
        self.assertEqual(rejected["error"]["type"], "ConflictError")

    def test_unknown_message_and_failed_create_require_evidence_before_retry(self):
        self.hierarchy()
        prepared = self.idea(); request = prepared["request"]
        self.write("claim", request_id=request["request_id"])
        self.observe(request, status="failed", reason="TEST transport error", no_effect=False, proof="TEST no definitive evidence")
        self.assertEqual(self.read()["outbox"][0]["status"], "unknown")
        denied = self.write("claim", request_id=request["request_id"], retry_failed=True)
        self.assertFalse(denied["dispatch_allowed"])
        self.observe(request, status="failed", reason="TEST host verified no chat", no_effect=True, proof="TEST original request lookup returned no effect")
        self.rejection("claim", request_id=request["request_id"])
        retry = self.write("claim", request_id=request["request_id"], retry_failed=True)
        self.assertTrue(retry["dispatch_allowed"])
        self.assertEqual(retry["request"]["request_id"], request["request_id"])
        self.assertEqual(retry["request"]["attempt"], 2)
        self.observe(request, thread_id="TEST-idea-chat")
        developed = self.write("decide", topic_id="TEST-IDEA", decision="develop", reason="TEST exact branch",
                               branch_id="TEST-BRANCH", target_role="novel")
        message = developed["request"]
        self.write("claim", request_id=message["request_id"])
        self.observe(message, status="unknown", reason="TEST send response lost")
        retry_message = self.write("claim", request_id=message["request_id"], retry_failed=True)
        self.assertFalse(retry_message["dispatch_allowed"])
        self.assertEqual(self.read()["handoffs"][0]["status"], "offered")


if __name__ == "__main__":
    unittest.main()

"""Typed creative tools against isolated TEST registries and real stdio calls."""
import hashlib
import importlib.util
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
from filmprod.action_schemas import ACTION_SCHEMAS, action_help, validate


SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mcp_efficiency1100", SOURCE / "plugin/mcp_server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def occurrences(value, expected):
    if isinstance(value, dict):
        return sum(occurrences(item, expected) for item in value.values())
    if isinstance(value, list):
        return sum(occurrences(item, expected) for item in value)
    return int(value == expected)


class EfficiencyMCPTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="film-efficiency1100-TEST-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root = self.base / "TEST-PROJECT"
        self.identity = "TEST-EFFICIENCY-1100"
        self.env = {**os.environ, "FILMPROD_CATALOG_PATH": str(self.base / "TEST-catalog.sqlite3"), "PYTHONDONTWRITEBYTECODE": "1"}
        registry = Registry(self.root)
        try:
            registry.dispatch("project.init", dict(op_id="TEST-init", project_id=self.identity, title="TEST only", test_only=True))
        finally:
            registry.close()
        self.database = self.root / ".project/registry.sqlite3"
        self.body = "\ufeff# TEST 完整正文\r\n" + "**不重复回传的原文** 🎬\r\n" * 600

    def call(self, name, payload, error=False):
        with patch.dict(os.environ, self.env):
            result = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": payload}}, None)["result"]
        self.assertEqual(bool(result.get("isError")), error, result)
        if error:
            return result
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        return result["structuredContent"]

    def args(self, **kwargs):
        return dict(root=str(self.root), expected_project_id=self.identity, **kwargs)

    def records(self):
        connection = sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True)
        try:
            return list(connection.iterdump())
        finally:
            connection.close()

    def create(self):
        return self.call("film_task_create", self.args(op_id="TEST-create", task_id="TEST-TASK", title="TEST writing", module="story", artifact_id="TEST-TEXT", scope="chapter/1", inputs=[], must_keep=["TEST source"], allowed_changes=["TEST prose"], requirements=["Complete chapter"]))

    def draft(self, **kwargs):
        values = dict(op_id="TEST-draft", task_id="TEST-TASK", draft=self.body, completed=["Written"], decisions=[], unresolved=[], next_step="Review")
        values.update(kwargs)
        return self.call("film_draft_save", self.args(**values))

    def submit_args(self, checkpoint):
        return self.args(op_id="TEST-submit", task_id="TEST-TASK", artifact_id="TEST-TEXT", kind="novel", base_version=0,
                         checkpoint_id=checkpoint["checkpoint"]["checkpoint_id"], expected_draft_sha256=checkpoint["checkpoint"]["draft_sha256"], metadata={"title": "TEST output"})

    def stdio(self, requests):
        process = subprocess.run([sys.executable, "-B", "-X", "utf8", str(SOURCE / "plugin/mcp_server.py")],
            cwd=SOURCE, env=self.env, input="".join(json.dumps(request, ensure_ascii=False) + "\n" for request in requests),
            capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        return [json.loads(line) for line in process.stdout.splitlines() if line.strip()]

    def test_real_stdio_discovers_six_typed_tools_and_static_help(self):
        before = self.database.read_bytes()
        result = self.stdio([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                             {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "film_action_help", "arguments": {"action": "task.submit_checkpoint"}}}])
        definitions = {tool["name"]: tool for tool in result[0]["result"]["tools"]}
        for name in ("film_context", "film_action_help", "film_task_create", "film_draft_save", "film_draft_submit", "film_artifact_save_file"):
            self.assertIn(name, definitions)
            self.assertFalse(definitions[name]["inputSchema"]["additionalProperties"])
        self.assertTrue(definitions["film_context"]["annotations"]["readOnlyHint"])
        help_result = result[1]["result"]["structuredContent"]
        self.assertFalse(help_result["executed"])
        self.assertNotIn("content", help_result["inputSchema"]["properties"])
        self.assertEqual(self.database.read_bytes(), before)
        self.assertFalse(Path(self.env["FILMPROD_CATALOG_PATH"]).exists())

    def test_each_help_example_matches_shared_contract_without_opening_registry(self):
        with patch.object(Registry, "__init__", side_effect=AssertionError("Help must not open a registry")):
            for action in ACTION_SCHEMAS:
                help_result = self.call("film_action_help", {"action": action})
                validate(help_result["example_payload"], help_result["inputSchema"])
                self.assertTrue(help_result["example_only"])
        definition = next(t for t in server.TOOLS if t["name"] == "film_task_create")
        properties = {k: v for k, v in definition["inputSchema"]["properties"].items() if k != "root"}
        self.assertEqual(properties, action_help("task.create")["inputSchema"]["properties"])
        modified = action_help("task.create")
        modified["inputSchema"]["properties"].clear()
        self.assertIn("task_id", action_help("task.create")["inputSchema"]["properties"])

    def test_schema_errors_are_rejected_before_any_project_lookup(self):
        draft = self.args(op_id="TEST-invalid", task_id="TEST-TASK", completed=[], decisions=[], unresolved=[], next_step="", draft="")
        invalid = [("film_draft_save", dict(draft, source_path="draft.md", expected_file_sha256="0" * 64)),
                   ("film_draft_save", {k: v for k, v in draft.items() if k != "draft"}),
                   ("film_draft_save", dict(draft, completed="not an array")),
                   ("film_draft_save", dict(draft, decisions=[42])),
                   ("film_draft_save", dict(draft, extra=True)),
                   ("film_context", self.args(mode="artifact", artifact_id="TEST", version=True)),
                   ("film_context", self.args(mode="summary", task_id="TEST")),
                   ("film_context", self.args(mode="resume")),
                   ("film_context", self.args(mode="artifact", artifact_id="TEST", version=0)),
                   ("film_action_help", {"action": "unknown"}),
                   ("film_action_help", {"action": "task.create", "root": str(self.root)})]
        with patch.object(server, "checked_project_root", side_effect=AssertionError("Invalid schema reached project lookup")):
            for name, arguments in invalid:
                error = self.call(name, arguments, error=True)
                self.assertEqual(error["structuredContent"]["error"]["type"], "ValueError", error)

    def test_create_checkpoint_submit_preserves_full_body_without_echo(self):
        created = self.create()
        self.assertTrue(created["compact"])
        checkpoint = self.draft()
        self.assertTrue(checkpoint["compact"])
        self.assertEqual(occurrences(checkpoint, self.body), 0)
        self.assertLess(len(json.dumps(checkpoint)), len(self.body) // 4)
        submit_args = self.submit_args(checkpoint)
        saved = self.call("film_draft_submit", submit_args)
        self.assertEqual(saved["artifact_ref"], {"artifact_id": "TEST-TEXT", "version": 1})
        self.assertEqual(saved["approval_status"], "pending_review")
        self.assertEqual(saved["sha256"], hashlib.sha256(self.body.encode("utf-8")).hexdigest())
        self.assertEqual(occurrences(saved, self.body), 0)
        self.assertEqual(self.call("film_draft_submit", submit_args), saved)
        exact = self.call("film_context", self.args(mode="artifact", artifact_id="TEST-TEXT", version=1))
        self.assertEqual(exact["artifact"]["content"], self.body)
        self.assertEqual(occurrences(exact, self.body), 1)
        self.assertFalse(exact["is_current_approved"])

    def test_file_checkpoint_retry_is_independent_of_later_source_edits(self):
        self.create()
        path = self.root / "TEST-draft.md"
        path.write_bytes(self.body.encode("utf-8"))
        arguments = self.args(op_id="TEST-file-draft", task_id="TEST-TASK", source_path=path.name,
            expected_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), completed=[], decisions=[], unresolved=[], next_step="Submit")
        checkpoint = self.call("film_draft_save", arguments)
        self.assertEqual(checkpoint["source"]["sha256"], arguments["expected_file_sha256"])
        path.write_text("TEST changed after acknowledged checkpoint", encoding="utf-8")
        self.assertEqual(self.call("film_draft_save", arguments), checkpoint)
        saved = self.call("film_draft_submit", self.submit_args(checkpoint))
        exact = self.call("film_context", self.args(mode="artifact", **saved["artifact_ref"]))
        self.assertEqual(exact["artifact"]["content"], self.body)

    def test_fixed_invalid_values_fail_before_lookup_and_structured_constraints_survive(self):
        file_args = self.args(op_id="TEST-bad-kind", artifact_id="TEST-TEXT", kind="render", scope="chapter/1", base_version=0,
                             source_path="draft.md", expected_file_sha256="0" * 64)
        draft_args = self.args(op_id="TEST-empty", task_id="TEST-TASK", draft="TEST body", completed=[], decisions=[], unresolved=[], next_step="Submit")
        with patch.object(server, "checked_project_root", side_effect=AssertionError("Invalid fixed value reached project lookup")):
            for name, arguments in [("film_artifact_save_file", file_args), ("film_draft_save", dict(draft_args, draft="")), ("film_draft_save", dict(draft_args, next_step=""))]:
                error = self.call(name, arguments, error=True)
                self.assertEqual(error["structuredContent"]["error"]["type"], "ValueError")
        from filmprod.core import TEXT_FILE_KINDS
        self.assertEqual(set(action_help("artifact.save_file")["inputSchema"]["properties"]["kind"]["enum"]), TEXT_FILE_KINDS)
        self.create()
        saved = self.draft(decisions=[{"fact": "TEST explicit decision"}], completed=[{"unit": "TEST chapter"}])
        self.assertEqual(saved["checkpoint"]["decisions"], [{"fact": "TEST explicit decision"}])
        self.assertEqual(saved["checkpoint"]["completed"], [{"unit": "TEST chapter"}])

    def test_actual_stdio_file_candidate_matches_bytes_and_legacy_read_contract(self):
        path = self.root / "TEST-text.md"
        path.write_bytes(self.body.encode("utf-8"))
        arguments = self.args(op_id="TEST-file-save", artifact_id="TEST-FILE", kind="novel", scope="chapter/file", base_version=0,
                              source_path=path.name, expected_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), deps=[], metadata={"title": "TEST File"})
        requests = [{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "film_artifact_save_file", "arguments": arguments}},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "film_context", "arguments": self.args(mode="artifact", artifact_id="TEST-FILE", version=1)}},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "film_dispatch", "arguments": {"root": str(self.root), "action": "artifact.get", "payload": {"artifact_id": "TEST-FILE", "version": 1}}}}]
        results = self.stdio(requests)
        self.assertTrue(all(not item["result"].get("isError") for item in results), results)
        compact, exact, legacy = [item["result"]["structuredContent"] for item in results]
        self.assertEqual(occurrences(compact, self.body), 0)
        self.assertEqual(exact["artifact"]["content"].encode("utf-8"), path.read_bytes())
        self.assertEqual(legacy, exact["artifact"])
        self.assertEqual(compact["source"]["path"], path.name)

    def test_summary_omits_bodies_and_resume_includes_only_latest_draft_once(self):
        self.create()
        self.draft(op_id="TEST-draft-old", draft="TEST previous checkpoint")
        self.draft()
        before = self.database.read_bytes()
        with patch.object(Registry, "__init__", side_effect=AssertionError("Context must be read-only")):
            summary = self.call("film_context", self.args(mode="summary"))
            resume = self.call("film_context", self.args(mode="resume", task_id="TEST-TASK"))
        self.assertFalse(summary["bodies_included"])
        self.assertEqual(occurrences(summary, self.body), 0)
        self.assertEqual(occurrences(resume, self.body), 1)
        self.assertEqual(occurrences(resume, "TEST previous checkpoint"), 0)
        self.assertNotIn("checkpoints", resume["task"])
        self.assertEqual(resume["task"]["must_keep"], ["TEST source"])
        self.assertEqual(self.database.read_bytes(), before)

    def test_incorrect_identity_hash_version_and_mutually_exclusive_fields_preserve_records(self):
        self.create()
        checkpoint = self.draft()
        arguments = self.submit_args(checkpoint)
        before = self.records()
        for changes in ({"expected_project_id": "TEST-WRONG"}, {"expected_draft_sha256": "0" * 64},
                        {"base_version": True}, {"base_version": 7}, {"checkpoint_id": "TEST-WRONG"}, {"content": self.body}):
            self.call("film_draft_submit", dict(arguments, **changes), error=True)
            self.assertEqual(self.records(), before)

    def test_wrong_reference_types_cannot_start_a_task(self):
        fields = self.args(op_id="TEST-invalid-create", task_id="TEST-TASK", title="TEST", module="story", scope="chapter/1", inputs=[], must_keep=[], allowed_changes=[], requirements=[])
        before = self.database.read_bytes()
        for refs in ([{"artifact_id": "TEST", "version": True}], [{"artifact_id": "TEST", "version": 1, "content": "injected"}], "not refs"):
            self.call("film_task_create", dict(fields, inputs=refs), error=True)
            self.assertEqual(self.database.read_bytes(), before)

    def test_missing_and_schema1_context_never_initializes_or_migrates(self):
        missing = self.base / "TEST-MISSING"
        self.call("film_context", dict(self.args(mode="summary"), root=str(missing)), error=True)
        self.assertFalse(missing.exists())
        old = self.base / "TEST-SCHEMA1"
        database = old / ".project/registry.sqlite3"
        database.parent.mkdir(parents=True)
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT INTO settings VALUES('schema_version','1')")
            db.execute("INSERT INTO settings VALUES('project',?)", (json.dumps({"project_id": self.identity, "title": "TEST old"}),))
        db.close()
        before = database.read_bytes()
        self.call("film_context", dict(self.args(mode="summary"), root=str(old)), error=True)
        self.assertEqual(database.read_bytes(), before)
        self.assertEqual([p.name for p in database.parent.iterdir()], ["registry.sqlite3"])

    def test_legacy_dispatch_checkpoints_keep_full_response_for_existing_clients(self):
        self.create()
        payload = dict(op_id="TEST-legacy-draft", expected_project_id=self.identity, task_id="TEST-TASK", draft=self.body, completed=[], decisions=[], unresolved=[], next_step="Submit")
        legacy = self.call("film_dispatch", {"root": str(self.root), "action": "task.checkpoint", "payload": payload})
        self.assertEqual(legacy["checkpoint"]["draft"], self.body)
        self.assertNotIn("compact", legacy)
        summary = self.call("film_dispatch", {"root": str(self.root), "action": "context.read", "payload": {"expected_project_id": self.identity, "mode": "summary"}})
        self.assertTrue(summary["read_only"])


if __name__ == "__main__":
    unittest.main()

"""Read-only brainstorm interface. All data and decisions are synthetic TEST."""
import hashlib
import json
import re
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from filmprod.brainstorm import interface, prepare
from filmprod.core import ConflictError, Registry


def check_schema(value, schema):
    """Validate the JSON Schema keyword subset used by this exported contract."""
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            try:
                check_schema(value, option)
                return
            except AssertionError:
                pass
        raise AssertionError("no anyOf branch matched")
    if "const" in schema:
        assert type(value) is type(schema["const"]) and value == schema["const"]
    if "enum" in schema:
        assert value in schema["enum"]
    types = schema.get("type")
    if types:
        types = [types] if isinstance(types, str) else types
        matches = {"null": value is None, "object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str), "integer": type(value) is int, "boolean": type(value) is bool}
        assert any(matches.get(kind, False) for kind in types), (value, types)
    if isinstance(value, dict):
        assert set(schema.get("required", [])) <= set(value)
        if schema.get("additionalProperties") is False:
            assert set(value) <= set(schema.get("properties", {}))
        for key, child in schema.get("properties", {}).items():
            if key in value:
                check_schema(value[key], child)
    if isinstance(value, list):
        assert len(value) >= schema.get("minItems", 0)
        for item in value:
            check_schema(item, schema.get("items", {}))
    if isinstance(value, str):
        assert len(value) >= schema.get("minLength", 0)
        if "pattern" in schema:
            assert re.search(schema["pattern"], value)
    if type(value) is int and "minimum" in schema:
        assert value >= schema["minimum"]


class Brainstorm140Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="TEST_ONLY_BRAINSTORM_140_")
        self.root = Path(self.tmp.name) / "project"
        self.r = Registry(self.root)
        self.call("project.init", project_id="TEST-BRAINSTORM-140", title="脑暴接口合成测试", test_only=True)

    def tearDown(self):
        if self.r is not None:
            self.r.close()
        self.tmp.cleanup()

    def call(self, action, **payload):
        return self.r.dispatch(action, {"op_id": uuid.uuid4().hex, **payload})

    def request(self, **payload):
        return {"expected_project_id": "TEST-BRAINSTORM-140", "topic": "合成创作议题", **payload}

    def ref(self, aid, version=1):
        return {"artifact_id": aid, "version": version}

    def save(self, aid="N", base=0, kind="novel", scope=None, deps=None):
        return self.call("artifact.save", artifact_id=aid, base_version=base, kind=kind, scope=scope or aid, content=f"TEST 正文 {aid} @{base + 1}", deps=deps or [])

    def approve(self, aid="N", version=1):
        a = self.r._artifact(aid, version)
        return self.call("content.approve", artifact_id=aid, version=version, scope=a["scope"], evidence="合成明确批准", actor="test-runner", synthetic=True)

    def state(self):
        return "\n".join(self.r.db.iterdump())

    def test_static_interface_exports_actual_schemas_without_generation(self):
        contract = interface()
        self.assertEqual(contract["skill_name"], "film-brainstorm-interface")
        self.assertEqual(contract["status"], "interface_only")
        self.assertEqual(contract["provider_status"], "not_connected")
        self.assertFalse(contract["can_generate"])
        self.assertTrue(all(value is False for value in contract["effects"].values()))
        check_schema(self.request(), contract["input_schema"])
        before = self.state()
        result = self.r.dispatch("brainstorm.interface")
        self.assertEqual(result, contract)
        self.assertEqual(self.state(), before)
        contract["input_schema"]["required"].append("corrupted")
        self.assertNotIn("corrupted", interface()["input_schema"]["required"])

    def test_prepare_unknown_inputs_and_output_schema_leave_database_unchanged(self):
        self.save("UNSELECTED")
        before, changes = self.state(), self.r.db.total_changes
        result = self.r.dispatch("brainstorm.prepare", self.request())
        check_schema(result, interface()["output_schema"])
        self.assertEqual(result["contexts"], [])
        self.assertEqual(result["context_refs"], [])
        for key in ("scope", "must_keep", "constraints", "base_ref", "approved_style", "candidate_output"):
            self.assertIsNone(result[key])
        self.assertEqual(set(result["unknown_inputs"]), {"scope", "must_keep", "constraints", "base_ref", "context_refs", "global_style"})
        self.assertFalse(result["generation_performed"])
        self.assertEqual(self.state(), before)
        self.assertEqual(self.r.db.total_changes, changes)

    def test_wrong_project_and_invalid_payload_never_write(self):
        before = self.state()
        with self.assertRaises(ConflictError):
            self.r.dispatch("brainstorm.prepare", self.request(expected_project_id="OTHER"))
        for request in ({"topic": "no identity"}, self.request(topic=" "), self.request(allow_candidate_context=1), self.request(must_keep="invented"), self.request(generate=True)):
            with self.assertRaises(ValueError):
                self.r.dispatch("brainstorm.prepare", request)
        self.assertEqual(self.state(), before)

    def test_candidates_require_explicit_selection_and_keep_candidate_label(self):
        self.save()
        request = self.request(context_refs=[self.ref("N")])
        before = self.state()
        with self.assertRaises(ValueError):
            self.r.dispatch("brainstorm.prepare", request)
        result = self.r.dispatch("brainstorm.prepare", dict(request, allow_candidate_context=True))
        check_schema(result, interface()["output_schema"])
        self.assertEqual(result["contexts"][0]["context_status"], "candidate")
        self.assertTrue(result["contexts"][0]["is_candidate"])
        self.assertIsNone(result["base_ref"])
        self.assertEqual(result["contexts"][0]["content"], "TEST 正文 N @1")
        self.assertEqual(self.state(), before)

    def test_exact_historical_version_never_swaps_to_latest_or_guesses_base(self):
        self.save(); self.approve()
        self.save(base=1); self.approve(version=2)
        payload = self.request(context_refs=[self.ref("N"), self.ref("N", 2)], base_ref=self.ref("N"), scope="N/开头", must_keep=[], constraints=["保持合成测试边界"])
        result = prepare(self.root, payload)
        self.assertEqual([a["version"] for a in result["contexts"]], [1, 2])
        self.assertEqual(result["contexts"][0]["context_status"], "historical_approved")
        self.assertEqual(result["base_ref"], self.ref("N"))
        self.assertEqual(result["contexts"][0]["content"], "TEST 正文 N @1")
        self.save(base=2)
        again = prepare(self.root, payload)
        self.assertEqual(result["contexts"], again["contexts"])
        self.assertEqual(again["base_ref"], self.ref("N"))
        with self.assertRaises(ValueError):
            prepare(self.root, self.request(context_refs=[self.ref("N")], base_ref=self.ref("N", 2)))
        with self.assertRaises(ValueError):
            prepare(self.root, self.request(context_refs=[{"artifact_id": "N"}]))
        with self.assertRaises(ValueError):
            prepare(self.root, self.request(context_refs=[self.ref("N", 99)]))

    def test_approved_style_is_exact_and_pending_style_is_not_promoted(self):
        self.save(); self.approve()
        self.save("STYLE", kind="style_bible", scope="project/style", deps=[self.ref("N")]); self.approve("STYLE")
        self.save("STYLE", base=1, kind="style_bible", scope="project/style", deps=[self.ref("N")])
        result = prepare(self.root, self.request())
        self.assertEqual(result["approved_style"]["version"], 1)
        self.assertEqual(result["global_style"]["pending_refs"], [self.ref("STYLE", 2)])
        self.assertEqual(result["context_refs"], [])
        check_schema(result, interface()["output_schema"])
        self.save(base=1); self.approve(version=2)
        result = prepare(self.root, self.request())
        self.assertEqual(result["global_style"]["status"], "needs_review")
        self.assertIsNone(result["approved_style"])
        self.assertIn("global_style", result["unknown_inputs"])

    def test_readonly_entrypoint_never_initializes_or_migrates(self):
        missing = Path(self.tmp.name) / "DO_NOT_CREATE"
        with self.assertRaises(ValueError):
            prepare(missing, self.request())
        self.assertFalse(missing.exists())
        legacy = Path(self.tmp.name) / "LEGACY_TEST" / ".project"
        legacy.mkdir(parents=True)
        db = sqlite3.connect(legacy / "registry.sqlite3")
        try:
            db.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            db.execute("INSERT INTO settings VALUES('schema_version','1')")
            db.commit()
        finally:
            db.close()
        old_hash = hashlib.sha256((legacy / "registry.sqlite3").read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            prepare(legacy.parent, self.request())
        self.assertFalse((legacy / "migrations").exists())
        self.assertEqual(hashlib.sha256((legacy / "registry.sqlite3").read_bytes()).hexdigest(), old_hash)
        self.assertEqual([p.name for p in legacy.iterdir()], ["registry.sqlite3"])

    def test_style_with_stale_candidate_source_is_not_presented_as_usable(self):
        self.save("RESEARCH", kind="research")
        self.save("STYLE", kind="style_bible", scope="project/style", deps=[self.ref("RESEARCH")]); self.approve("STYLE")
        self.save("RESEARCH", base=1, kind="research")
        before = self.state()
        result = prepare(self.root, self.request())
        self.assertEqual(result["global_style"]["approved_ref"], self.ref("STYLE"))
        self.assertEqual(result["global_style"]["status"], "needs_review")
        self.assertIsNone(result["approved_style"])
        self.assertEqual(self.state(), before)

    def test_readonly_connection_rejects_writes_and_keeps_closed_database_bytes(self):
        self.r.close(); self.r = None
        db_file = self.root / ".project" / "registry.sqlite3"
        before = hashlib.sha256(db_file.read_bytes()).hexdigest()
        reader = Registry.open_readonly(self.root)
        try:
            self.assertEqual(reader.db.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(ValueError):
                reader.dispatch("project.workflow.set", dict(self.request(), op_id="not-a-write", base_revision=0, mode="novel_only"))
            with self.assertRaises(sqlite3.OperationalError):
                reader.db.execute("DELETE FROM settings")
            result = reader.dispatch("brainstorm.prepare", self.request())
            check_schema(result, interface()["output_schema"])
            self.assertEqual(reader.db.total_changes, 0)
        finally:
            reader.close()
        self.assertEqual(hashlib.sha256(db_file.read_bytes()).hexdigest(), before)

    def test_future_output_contract_allows_one_or_more_unadopted_candidates(self):
        schema = interface()["candidate_output_schema"]
        direction = {"direction_id": "A", "title": "合成schema样例", "proposal": "仅测试schema，不是实际脑暴产出", "source_refs": [], "benefits": [], "risks": [], "assumptions": [], "unknowns": []}
        sample = {"status": "candidate", "directions": [direction, dict(direction, direction_id="B")], "tradeoffs": [], "open_questions": [], "selection_status": "awaiting_user_choice", "automatically_adopted": False}
        check_schema(sample, schema)
        check_schema(dict(sample, directions=[direction]), schema)
        with self.assertRaises(AssertionError):
            check_schema(dict(sample, status="approved"), schema)
        with self.assertRaises(AssertionError):
            check_schema(dict(sample, automatically_adopted=True), schema)
        with self.assertRaises(AssertionError):
            check_schema(dict(sample, directions=[]), schema)


if __name__ == "__main__":
    unittest.main()

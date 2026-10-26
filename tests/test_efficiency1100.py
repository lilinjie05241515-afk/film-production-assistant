"""Synthetic authoring equivalence, exact references, and bounded response tests."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from filmprod.core import Registry, ConflictError
from filmprod.efficient import compact_result, read_context


def sha(body):
    return hashlib.sha256(body).hexdigest()


class EfficientAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="film-efficient-TEST-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "TEST-PROJECT"
        self.reg = Registry(self.root)
        self.addCleanup(self.reg.close)
        self.pid = "TEST-EFFICIENT-1100"
        self.n = 0
        self.call("project.init", project_id=self.pid, title="TEST authoring", test_only=True)
        self.body = "\ufeff# TEST exact source\r\n\r\n**中文** 🎬\n\r末行"
        self.path = self.root / "drafts/中文源文.md"
        self.path.parent.mkdir()
        self.path.write_bytes(self.body.encode("utf-8"))

    def call(self, action, **payload):
        self.n += 1
        payload.setdefault("op_id", "TEST-OP-" + str(self.n))
        if action != "project.init":
            payload.setdefault("expected_project_id", self.pid)
        return self.reg.dispatch(action, payload)

    def source(self):
        return dict(source_path=self.path.relative_to(self.root).as_posix(), expected_file_sha256=sha(self.path.read_bytes()))

    def create(self, task="TASK", aid="OUT", inputs=None):
        return self.call("task.create", task_id=task, title="TEST creation", module="story", artifact_id=aid,
                         scope="novel/" + aid, inputs=inputs or [], must_keep=["TEST preserve"],
                         allowed_changes=["TEST dialogue"], requirements=["TEST complete text"])

    def checkpoint(self, task="TASK", **changes):
        p = dict(task_id=task, draft=self.body, completed=["TEST complete"], decisions=[], unresolved=[], next_step="TEST review")
        p.update(changes)
        return self.call("task.checkpoint", **p)

    def checkpoint_file(self, task="TASK", **changes):
        p = dict(task_id=task, **self.source(), completed=["TEST complete"], decisions=[], unresolved=[], next_step="TEST review")
        p.update(changes)
        return self.call("task.checkpoint_file", **p)

    def submit(self, cp, task="TASK", aid="OUT", **changes):
        p = dict(task_id=task, checkpoint_id=cp["checkpoint"]["checkpoint_id"],
                 expected_draft_sha256=cp["checkpoint"]["draft_sha256"], artifact_id=aid, kind="novel", base_version=0)
        p.update(changes)
        return self.call("task.submit_checkpoint", **p)

    def save_file(self, aid="FILE", **changes):
        p = dict(artifact_id=aid, kind="novel", scope="novel/" + aid, base_version=0, deps=[], metadata={}, **self.source())
        p.update(changes)
        return self.call("artifact.save_file", **p)

    def persisted_counts(self):
        return {table: self.reg.db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                for table in ("artifacts", "tasks", "operations", "events", "approved_segments")}

    def context(self, **payload):
        with_registry = Registry.open_readonly(self.root)
        try:
            before = with_registry.db.total_changes
            result = read_context(with_registry, {"expected_project_id": self.pid, **payload})
            self.assertEqual(with_registry.db.total_changes, before)
            self.assertEqual(with_registry.db.execute("PRAGMA query_only").fetchone()[0], 1)
            return result
        finally:
            with_registry.close()

    def test_file_candidate_exact_utf8_preserves_source_metadata_and_never_approves(self):
        original = self.path.read_bytes()
        metadata = {"title": "TEST file", "source_file": "TEST user provenance", "source": {"url": "TEST original"}}
        result = self.save_file(metadata=metadata)
        artifact = self.reg._artifact("FILE", 1)
        self.assertEqual(artifact["content"].encode("utf-8"), original)
        self.assertEqual(artifact["metadata"], metadata)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(result["source"], {"path": "drafts/中文源文.md", "sha256": sha(original), "size_bytes": len(original)})
        self.assertEqual(result["artifact_ref"], {"artifact_id": "FILE", "version": 1})
        self.assertEqual(result["approval_status"], "pending_review")
        self.assertNotIn("content", result["artifact"])
        self.assertEqual(self.reg.snapshot()["approved_artifacts"], [])

    def test_file_checkpoint_and_reference_submit_have_exact_legacy_content(self):
        task = self.create()
        cp = self.checkpoint_file()
        source = dict(cp["source"])
        self.assertNotIn("draft", cp["checkpoint"])
        self.assertEqual(cp["checkpoint"]["draft_sha256"], sha(self.path.read_bytes()))
        self.path.write_bytes(b"TEST later edits must not replace persisted checkpoint")
        result = self.submit(cp, metadata={"source_file": "TEST metadata remains"})
        artifact = self.reg._artifact("OUT", 1)
        self.assertEqual(artifact["content"], self.body)
        self.assertEqual(artifact["metadata"]["execution_lock"], task["execution_lock"])
        self.assertEqual(result["source"], source)
        self.assertEqual(result["submitted_checkpoint"]["checkpoint_id"], cp["checkpoint"]["checkpoint_id"])
        self.assertEqual(result["task"]["status"], "submitted")
        self.assertNotIn("checkpoints", result["task"])
        self.assertEqual(self.reg.snapshot()["approved_artifacts"], [])

    def test_successful_file_retry_reuses_original_after_source_changed_or_removed(self):
        request = dict(op_id="TEST-IDEMPOTENT", expected_project_id=self.pid, artifact_id="FILE", kind="novel",
                       scope="novel/FILE", base_version=0, metadata={}, deps=[], **self.source())
        first = self.reg.dispatch("artifact.save_file", request)
        before = self.persisted_counts()
        self.path.write_bytes(b"TEST changed")
        with patch("filmprod.efficient._read_source", side_effect=AssertionError("cache must precede file read")):
            self.assertEqual(self.reg.dispatch("artifact.save_file", request), first)
        self.path.unlink()
        self.assertEqual(self.reg.dispatch("artifact.save_file", request), first)
        self.assertEqual(self.persisted_counts(), before)
        with self.assertRaisesRegex(ConflictError, "op_id"):
            self.reg.dispatch("artifact.save_file", dict(request, expected_file_sha256="0" * 64))

    def test_checkpoint_file_retry_and_submit_retry_remain_idempotent(self):
        self.create()
        cp = self.checkpoint_file(op_id="TEST-CP-FIXED")
        p = dict(op_id="TEST-CP-FIXED", expected_project_id=self.pid, task_id="TASK", **self.source(),
                 completed=["TEST complete"], decisions=[], unresolved=[], next_step="TEST review")
        submitted = self.submit(cp, op_id="TEST-SUBMIT-FIXED")
        self.path.unlink()
        self.assertEqual(self.reg.dispatch("task.checkpoint_file", p), cp)
        self.assertEqual(self.submit(cp, op_id="TEST-SUBMIT-FIXED"), submitted)
        self.assertEqual(len(self.reg._get("tasks", "task_id", "TASK")["checkpoints"]), 1)
        self.assertEqual(len(self.reg.dispatch("artifact.history", {"artifact_id": "OUT"})["versions"]), 1)

    def test_wrong_project_hash_encoding_or_unsupported_kind_do_not_write(self):
        before = self.persisted_counts()
        for changes in ({"expected_project_id": "TEST-WRONG"}, {"expected_file_sha256": "0" * 64},
                        {"expected_file_sha256": "invalid"}, {"kind": "planning_record"}, {"kind": "render"},
                        {"content": "TEST override"}, {"source_path": ".project/registry.sqlite3"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.save_file(**changes)
            self.assertEqual(self.persisted_counts(), before)
        self.path.write_bytes(b"\xff\xfeTEST")
        with self.assertRaises(UnicodeDecodeError):
            self.save_file()
        self.assertEqual(self.persisted_counts(), before)

    def test_file_path_escape_drive_ads_and_directory_are_refused(self):
        before = self.persisted_counts()
        for value in (str(self.path), "../outside.md", "drafts/../drafts/中文源文.md", "C:relative.md", "drafts/中文源文.md:stream",
                      "drafts//中文源文.md", "drafts/./中文源文.md", ".PROJECT/a", "drafts", "\\server\\share\\a.md"):
            with self.subTest(path=value), self.assertRaises((ValueError, OSError)):
                self.save_file(source_path=value)
        self.assertEqual(self.persisted_counts(), before)

    def test_hardlink_sources_are_rejected(self):
        linked = self.root / "drafts/hard.md"
        os.link(self.path, linked)
        before = self.persisted_counts()
        with self.assertRaisesRegex(ValueError, "独立普通"):
            self.save_file(source_path="drafts/hard.md")
        self.assertEqual(self.persisted_counts(), before)

    @unittest.skipUnless(os.name == "nt", "Windows junction only")
    def test_windows_junction_is_rejected_without_reading_outside_project(self):
        external = self.base / "TEST-OUTSIDE"
        external.mkdir()
        (external / "a.md").write_bytes(self.path.read_bytes())
        link = self.root / "drafts/junction"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(external)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            with self.assertRaisesRegex(ValueError, "重解析点"):
                self.save_file(source_path="drafts/junction/a.md")
        finally:
            link.rmdir()  # Removes this explicit test junction, never its target.
        self.assertTrue((external / "a.md").exists())

    def test_permission_or_read_race_rolls_back_registry(self):
        before = self.persisted_counts()
        with patch("filmprod.efficient.os.open", side_effect=PermissionError("TEST denied")), self.assertRaises(PermissionError):
            self.save_file()
        self.assertEqual(self.persisted_counts(), before)
        from filmprod import efficient
        original = efficient._plain
        calls = 0
        def changed(path, directory):
            nonlocal calls
            result = original(path, directory)
            if not directory:
                calls += 1
                if calls == 2:
                    os.utime(path, ns=(result.st_atime_ns, result.st_mtime_ns + 10000000))
                    return original(path, directory)
            return result
        with patch("filmprod.efficient._plain", side_effect=changed), self.assertRaisesRegex(ConflictError, "读取后"):
            self.save_file()
        self.assertEqual(self.persisted_counts(), before)

    def test_missing_project_identity_is_rejected_before_file_read(self):
        with patch("filmprod.efficient._read_source", side_effect=AssertionError("identity must be required first")):
            with self.assertRaisesRegex(ValueError, "expected_project_id"):
                self.reg.dispatch("artifact.save_file", {"op_id": "TEST-NO-ID", **self.source()})

    def test_file_save_retains_base_version_dependencies_and_exclusive_editor_guards(self):
        first = self.save_file()
        with self.assertRaisesRegex(ConflictError, "基础版本"):
            self.save_file()
        with self.assertRaisesRegex(ValueError, "依赖版本"):
            self.save_file(aid="BAD-DEP", deps=[{"artifact_id": "MISSING", "version": 1}])
        self.create(aid="OUT")
        with self.assertRaisesRegex(ConflictError, "任务"):
            self.save_file(aid="OUT")
        self.assertEqual(self.reg._artifact("FILE", 1)["sha256"], first["sha256"])

    def test_submit_rejects_wrong_or_old_checkpoint_hash_target_and_body_override(self):
        self.create()
        older = self.checkpoint()
        newer = self.checkpoint(draft="TEST new persisted draft")
        before = self.persisted_counts()
        for cp, changes in ((older, {}), (newer, {"checkpoint_id": "TEST-OTHER"}), (newer, {"expected_draft_sha256": "0" * 64}),
                            (newer, {"artifact_id": "OTHER"}), (newer, {"content": "TEST override"}), (newer, {"base_version": 1})):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.submit(cp, **changes)
            self.assertEqual(self.persisted_counts(), before)
        result = self.submit(newer)
        self.assertEqual(result["sha256"], sha(b"TEST new persisted draft"))

    def test_submit_preserves_frozen_upstream_freshness(self):
        self.call("artifact.save", artifact_id="UP", kind="outline", scope="outline/UP", base_version=0, content="TEST upstream one", deps=[], metadata={})
        self.create(inputs=[{"artifact_id": "UP", "version": 1}])
        cp = self.checkpoint()
        self.call("artifact.save", artifact_id="UP", kind="outline", scope="outline/UP", base_version=1, content="TEST upstream two", deps=[], metadata={})
        before = self.persisted_counts()
        with self.assertRaises(ConflictError):
            self.submit(cp)
        self.assertEqual(self.persisted_counts(), before)

    def test_old_execution_lock_remains_readable_but_cannot_checkpoint_or_submit(self):
        self.create()
        cp = self.checkpoint()
        old = self.reg._get("tasks", "task_id", "TASK")
        old["execution_lock"]["system_version"] = "0.0.0-TEST-OLD"
        self.reg._put("tasks", "task_id", "TASK", old)
        resumed = self.context(mode="resume", task_id="TASK")
        self.assertFalse(resumed["execution_compatibility"]["compatible"])
        self.assertEqual(resumed["checkpoint"]["draft"], self.body)
        self.assertEqual(resumed["task"]["execution_lock"], old["execution_lock"])
        before = self.persisted_counts()
        with self.assertRaisesRegex(ValueError, "冻结"):
            self.checkpoint_file()
        with self.assertRaisesRegex(ValueError, "冻结"):
            self.submit(cp)
        self.assertEqual(self.persisted_counts(), before)

    def test_legacy_result_shapes_and_compact_projection_are_independent(self):
        task = self.create()
        task_original = copy.deepcopy(task)
        compact = compact_result("task.create", task)
        self.assertNotIn("checkpoints", compact)
        self.assertEqual(task, task_original)
        self.assertIn("checkpoints", task)
        cp = self.checkpoint()
        cp_original = copy.deepcopy(cp)
        short = compact_result("task.checkpoint", cp)
        self.assertNotIn("draft", short["checkpoint"])
        short["checkpoint"]["completed"].append("TEST mutate returned projection")
        self.assertEqual(cp, cp_original)
        self.assertEqual(cp["checkpoint"]["draft"], self.body)
        original = self.call("task.submit", task_id="TASK", artifact_id="OUT", kind="novel", content=self.body, base_version=0)
        self.assertIn("content", original["artifact"])
        self.assertIn("checkpoints", original["task"])

    def test_read_context_preserves_status_exact_refs_and_only_latest_draft_once(self):
        first = self.save_file()
        self.call("content.approve", artifact_id="FILE", version=1, scope="novel/FILE", actor="TEST", synthetic=True, evidence="TEST synthetic approval")
        self.path.write_bytes(b"TEST new candidate")
        self.save_file(base_version=1)
        self.create(inputs=[first["artifact_ref"]])
        self.checkpoint(draft="TEST old draft")
        self.checkpoint()
        before = (self.root / ".project/registry.sqlite3").read_bytes()
        summary = self.context()
        self.assertEqual(summary["approved_artifacts"][0]["version"], 1)
        self.assertEqual(summary["pending_candidates"][0]["version"], 2)
        self.assertEqual(summary["tasks"][0]["inputs"], [{"artifact_id": "FILE", "version": 1}])
        self.assertNotIn(self.body, json.dumps(summary, ensure_ascii=False))
        self.assertFalse(summary["bodies_included"])
        resumed = self.context(mode="resume", task_id="TASK")
        self.assertNotIn("checkpoints", resumed["task"])
        self.assertEqual(resumed["checkpoint"]["draft"], self.body)
        self.assertEqual(resumed["task"]["must_keep"], ["TEST preserve"])
        self.assertNotIn("content", resumed["frozen_inputs"][0])
        exact = self.context(mode="artifact", artifact_id="FILE", version=1)
        self.assertEqual(exact["artifact"]["content"], self.body)
        self.assertTrue(exact["is_current_approved"])
        self.assertEqual((self.root / ".project/registry.sqlite3").read_bytes(), before)

    def test_context_rejects_identity_implicit_latest_extra_fields_and_mutation(self):
        self.save_file()
        for p in ({"mode": "summary", "expected_project_id": "OTHER"}, {"mode": "artifact", "artifact_id": "FILE"},
                  {"mode": "artifact", "artifact_id": "FILE", "version": True}, {"mode": "artifact", "artifact_id": "FILE", "version": 99},
                  {"mode": "summary", "content": "TEST"}, {"mode": "all"}):
            with self.subTest(p=p), self.assertRaises(ValueError):
                self.context(**p)

    def test_long_document_response_reduction_is_measured_without_losing_exact_body(self):
        long_body = "TEST-UNIQUE-LONG-BODY\n" + "长文本与完整原稿\r\n" * 12000
        self.path.write_bytes(long_body.encode("utf-8"))
        self.save_file()
        self.create()
        old_cp = self.checkpoint(draft=long_body)
        short_cp = compact_result("task.checkpoint", old_cp)
        old = self.reg.snapshot()
        summary = self.context()
        old_bytes = len(json.dumps(old, ensure_ascii=False).encode())
        new_bytes = len(json.dumps(summary, ensure_ascii=False).encode())
        self.assertLess(new_bytes, old_bytes * 0.1)
        self.assertLess(len(json.dumps(short_cp, ensure_ascii=False).encode()), len(long_body.encode()) * 0.01)
        resumed = self.context(mode="resume", task_id="TASK")
        self.assertEqual(json.dumps(resumed, ensure_ascii=False).count("TEST-UNIQUE-LONG-BODY"), 1)
        exact = self.context(mode="artifact", artifact_id="FILE", version=1)
        self.assertEqual(exact["artifact"]["content"], long_body)


if __name__ == "__main__":
    unittest.main()

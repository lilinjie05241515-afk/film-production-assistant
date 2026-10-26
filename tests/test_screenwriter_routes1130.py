"""Unified methods, task edit scopes and direct screenplay route behavior."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from filmprod.core import Registry, ConflictError, output_kinds
from filmprod.modules import catalog, resolve, execution_lock


class ScreenwriterRoutes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="film-writer-routes-TEST-")
        self.root = Path(self.temp.name) / "TEST-only"
        self.r = Registry(self.root)
        self.call("project.init", project_id="TEST-ROUTES", title="TEST", test_only=True)

    def tearDown(self):
        self.r.close(); self.temp.cleanup()

    def call(self, action, **payload):
        payload.setdefault("op_id", uuid.uuid4().hex)
        if action != "project.init": payload.setdefault("expected_project_id", "TEST-ROUTES")
        return self.r.dispatch(action, payload)

    def task(self, module, tid="T", scope="episode/1"):
        return self.call("task.create", task_id=tid, title="TEST", module=module, scope=scope,
                         inputs=[], must_keep=[], allowed_changes=["表达调整"], requirements=[])

    def test_eight_active_modules_and_legacy_names_resolve_self_contained_screenwriter(self):
        ids = {row["id"] for row in catalog()["modules"]}
        self.assertEqual(len(ids), 8)
        self.assertIn("film-art-director", ids)
        self.assertIn("screenwriter", ids)
        self.assertNotIn("novel-master", ids)
        self.assertNotIn("novel-to-screenplay", ids)
        for alias in ("screenwriter", "novel-master", "novel-to-screenplay", "story", "novel", "outline", "character_bio", "adaptation", "original-screenplay"):
            result = resolve(alias)
            self.assertEqual(result["module"]["id"], "screenwriter")
            self.assertFalse(result["generation_performed"])
            self.assertEqual(execution_lock(alias)["module_id"], "screenwriter")
        for alias in ("script", "source_script", "dynamic_script", "screenplay"):
            self.assertEqual(resolve(alias, "screenplay")["screenwriting_mode"], "original")
            self.assertEqual(resolve(alias, "novel_to_screen")["screenwriting_mode"], "adaptation")

    def test_default_recommendation_does_not_mutate_existing_unset_or_novel_route(self):
        initial = self.r.snapshot()
        self.assertEqual(initial["workflow"]["recommended_mode"], "screenplay")
        self.assertEqual(initial["workflow"]["mode"], "unset")
        self.assertNotIn("workflow", initial["project"])
        self.call("project.workflow.set", mode="novel_only", base_revision=0)
        self.r.close(); self.r = Registry(self.root)
        self.assertEqual(self.r.snapshot()["workflow"]["mode"], "novel_only")

    def test_direct_script_has_no_compulsory_novel_or_source_draft(self):
        self.call("project.workflow.set", mode="screenplay", base_revision=0)
        flow = self.r.snapshot()["workflow"]
        self.assertEqual(flow["stages"][0]["key"], "dynamic_script")
        self.assertEqual(flow["stages"][0]["dependency_suggestions"], [])
        self.assertIn("source_script", {row["key"] for row in flow["optional_stages"]})
        self.task("screenwriter")
        saved = self.call("task.submit", task_id="T", artifact_id="SCRIPT", kind="script", content="S01 内 厨房 日\n甲：请坐。",
                          base_version=0, metadata={"workflow_stage": "dynamic_script"})["artifact"]
        self.assertEqual(saved["metadata"]["execution_lock"]["module_id"], "screenwriter")
        self.assertEqual(self.r.snapshot()["approved_artifacts"], [])

    def test_unified_and_legacy_tasks_share_the_same_editor_scope(self):
        self.task("screenwriter")
        for module in ("story", "novel-master", "screenplay", "novel-to-screenplay", "adaptation"):
            with self.assertRaises(ConflictError): self.task(module, tid=module)
        self.task("director", tid="D")
        self.assertIn("novel", output_kinds("screenwriter"))
        self.assertIn("script", output_kinds("screenwriter"))
        self.assertNotIn("director", output_kinds("screenwriter"))

    def test_old_lock_stays_readable_but_cannot_be_written_with_new_methods(self):
        task = self.task("story")
        task["execution_lock"]["system_version"] = "1.12.0"
        task["execution_lock"]["module_id"] = "novel-master"
        self.r.db.execute("UPDATE tasks SET data=? WHERE task_id='T'", (json.dumps(task),))
        old = self.r.db.execute("SELECT data FROM tasks WHERE task_id='T'").fetchone()[0]
        self.assertFalse(self.r.dispatch("task.resume", {"task_id": "T"})["execution_compatibility"]["compatible"])
        with self.assertRaises(ValueError):
            self.call("task.checkpoint", task_id="T", draft="不能改旧任务", completed=[], decisions=[], unresolved=[], next_step="等待")
        self.assertEqual(old, self.r.db.execute("SELECT data FROM tasks WHERE task_id='T'").fetchone()[0])


if __name__ == "__main__": unittest.main()

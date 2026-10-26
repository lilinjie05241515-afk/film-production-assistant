"""Explicit workflow and style provenance; every fixture is isolated synthetic TEST."""
import json
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from filmprod.core import ConflictError, Registry


class Workflow130Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="TEST_ONLY_WORKFLOW_130_")
        self.root = Path(self.tmp.name) / "project"
        self.r = Registry(self.root)
        self.call("project.init", project_id="TEST-WORKFLOW-130", title="合成流程测试", test_only=True)

    def tearDown(self):
        self.r.close()
        self.tmp.cleanup()

    def call(self, action, **payload):
        payload.setdefault("op_id", uuid.uuid4().hex)
        return self.r.dispatch(action, payload)

    def save(self, aid, kind="novel", scope=None, base=0, deps=None, metadata=None, **extra):
        return self.call("artifact.save", artifact_id=aid, kind=kind, scope=scope or aid, base_version=base, deps=deps or [], metadata=metadata or {}, content=f"合成 {aid} v{base + 1}", **extra)["artifact"]

    def approve(self, aid, version=1):
        a = self.r._artifact(aid, version)
        return self.call("content.approve", artifact_id=aid, version=version, scope=a["scope"], evidence="合成测试批准", actor="test-runner", synthetic=True)

    def choose(self, mode="novel_to_screen", revision=0, **extra):
        return self.call("project.workflow.set", expected_project_id="TEST-WORKFLOW-130", base_revision=revision, mode=mode, **extra)

    def task(self, tid="TASK", module="director", inputs=None, scope=None):
        return self.call("task.create", task_id=tid, module=module, title="合成任务", scope=scope or tid, inputs=inputs or [], must_keep=[], allowed_changes=[], requirements=[])

    def ref(self, aid, version=1):
        return {"artifact_id": aid, "version": version}

    def stage(self, key):
        flow = self.r.snapshot()["workflow"]
        return next(s for s in flow["stages"] + flow["optional_stages"] if s["key"] == key)

    def style(self, base=0):
        return self.save("STYLE", kind="style_bible", scope="project/style", base=base)

    def test_unset_route_not_inferred_from_approved_artifacts_or_snapshot(self):
        for aid, kind in (("N", "novel"), ("O", "outline"), ("C", "character"), ("S", "script")):
            self.save(aid, kind); self.approve(aid)
        before = self.r.db.total_changes
        view = self.r.snapshot()
        self.assertEqual(view["workflow"]["mode"], "unset")
        self.assertEqual(view["workflow"]["revision"], 0)
        self.assertEqual(view["workflow"]["stages"], [])
        self.assertNotIn("workflow", view["project"])
        self.assertEqual({a["artifact_id"] for a in view["workflow"]["unclassified"]}, {"S", "C"})
        self.assertEqual(self.r.db.total_changes, before)

    def test_workflow_cas_identity_idempotency_and_reopen(self):
        result = self.choose(op_id="route", outline_order="before_novel")
        self.assertEqual(result, self.choose(op_id="route", outline_order="before_novel"))
        with self.assertRaises(ConflictError):
            self.choose(mode="screenplay")
        with self.assertRaises(ValueError):
            self.call("project.workflow.set", base_revision=1, mode="screenplay")
        with self.assertRaises(ConflictError):
            self.call("project.workflow.set", expected_project_id="OTHER", base_revision=1, mode="screenplay")
        with self.assertRaises(ConflictError):
            self.choose(revision=True)
        self.r.close(); self.r = Registry(self.root)
        self.assertEqual(self.r.snapshot()["workflow"]["outline_order"], "before_novel")
        self.assertEqual(self.r.snapshot()["artifacts"], [])
        self.assertEqual(self.r.snapshot()["decisions"], [])
        other = Registry(self.root)
        try:
            def edit(registry, mode):
                try:
                    return registry.dispatch("project.workflow.set", {"op_id": uuid.uuid4().hex, "expected_project_id": "TEST-WORKFLOW-130", "base_revision": 1, "mode": mode})
                except ConflictError:
                    return "conflict"
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda item: edit(*item), [(self.r, "screenplay"), (other, "novel_only")]))
            self.assertEqual(sum(x == "conflict" for x in results), 1)
            self.assertEqual(self.r.snapshot()["workflow"]["revision"], 2)
        finally:
            other.close()

    def test_routes_and_optional_stages_are_explicit(self):
        self.choose(outline_order="before_novel")
        flow = self.r.snapshot()["workflow"]
        self.assertEqual([s["key"] for s in flow["stages"]][:3], ["outline", "novel", "style"])
        self.assertFalse(self.stage("outline")["optional"])
        self.choose(revision=1, outline_order="after_novel")
        self.assertEqual([s["key"] for s in self.r.snapshot()["workflow"]["stages"]][:3], ["novel", "style", "outline"])
        self.choose("novel_only", 2)
        self.assertEqual([s["key"] for s in self.r.snapshot()["workflow"]["stages"]], ["novel"])
        self.assertTrue(self.stage("style")["optional"])
        self.choose("screenplay", 3)
        self.assertEqual([s["key"] for s in self.r.snapshot()["workflow"]["stages"]][:4], ["dynamic_script", "director", "vfx", "asset"])
        self.assertTrue(self.stage("source_script")["optional"])
        self.assertTrue(self.stage("outline")["optional"])

    def test_screenplay_dependencies_do_not_invent_novel_or_optional_outline_gaps(self):
        self.choose("screenplay")
        asset_inputs = {s["stage_key"]: s for s in self.stage("asset")["dependency_suggestions"]}
        self.assertNotIn("source_script", asset_inputs)
        self.save("OPTIONAL-SOURCE", "source_script")
        asset_inputs = {s["stage_key"]: s for s in self.stage("asset")["dependency_suggestions"]}
        self.assertTrue(asset_inputs["source_script"]["optional"])
        self.assertNotIn("novel", asset_inputs)
        self.assertNotIn("outline", asset_inputs)
        bio_inputs = {s["stage_key"] for s in self.stage("character_bio")["dependency_suggestions"]}
        self.assertNotIn("outline", bio_inputs)
        self.save("OPTIONAL-OUTLINE", "outline")
        self.save("CROSS-ROUTE-NOVEL"); self.approve("CROSS-ROUTE-NOVEL")
        asset_inputs = {s["stage_key"]: s for s in self.stage("asset")["dependency_suggestions"]}
        self.assertTrue(asset_inputs["novel"]["optional"])
        self.assertEqual(asset_inputs["novel"]["refs"], [self.ref("CROSS-ROUTE-NOVEL")])
        self.assertEqual(asset_inputs["outline"]["status"], "candidate")
        self.assertEqual(asset_inputs["outline"]["refs"], [])
        self.assertEqual(asset_inputs["outline"]["candidate_refs"], [self.ref("OPTIONAL-OUTLINE")])
        self.assertTrue(next(s for s in self.stage("character_bio")["dependency_suggestions"] if s["stage_key"] == "outline")["optional"])

    def test_novel_only_optional_helpers_appear_only_when_content_exists(self):
        self.choose("novel_only")
        self.assertEqual(self.stage("novel")["dependency_suggestions"], [])
        self.save("BIO", "character_bio")
        suggestions = self.stage("novel")["dependency_suggestions"]
        self.assertEqual([s["stage_key"] for s in suggestions], ["character_bio"])
        self.assertEqual(suggestions[0]["status"], "candidate")
        self.assertTrue(suggestions[0]["optional"])
        self.assertEqual(suggestions[0]["refs"], [])
        self.approve("BIO")
        self.assertEqual(self.stage("novel")["dependency_suggestions"][0]["refs"], [self.ref("BIO")])

    def test_character_bio_outputs_do_not_reclassify_legacy_character(self):
        self.save("LEGACY", "character", scope="person/A"); self.approve("LEGACY")
        old_master = self.r.dispatch("master.history", {"category": "outline"})
        for index, module in enumerate(("story", "novel-master", "screenplay", "novel-to-screenplay")):
            task = self.task("T" + str(index), module=module)
            result = self.call("task.submit", task_id=task["task_id"], artifact_id="BIO" + str(index), kind="character_bio", content="明确人物小传", base_version=0)
            self.approve(result["artifact"]["artifact_id"])
        self.assertEqual(self.r.dispatch("master.history", {"category": "outline"}), old_master)
        self.assertEqual(len(self.r._master("character_bio")["segments"]), 4)
        self.assertEqual(next(a for a in self.r.snapshot()["approved_artifacts"] if a["artifact_id"] == "LEGACY")["category"], "outline")

    def test_legacy_character_does_not_claim_outline_or_biography_stage(self):
        self.choose()
        self.save("LEGACY", "character"); self.approve("LEGACY")
        self.assertEqual(self.stage("outline")["status"], "empty")
        self.assertEqual(self.stage("character_bio")["status"], "empty")
        item = self.r.snapshot()["workflow"]["unclassified"][0]
        self.assertEqual(item["reason"], "legacy_character_stage_not_declared")
        self.assertEqual(item["category"], "outline")
        self.assertEqual(self.r._master("outline")["segments"][0]["artifact_id"], "LEGACY")

    def test_source_and_dynamic_script_masters_are_separate_at_same_scope(self):
        self.choose("screenplay")
        self.save("BASE", "source_script", "S01"); self.approve("BASE")
        self.save("DYNAMIC", "script", "S01", deps=[self.ref("BASE")], metadata={"workflow_stage": "dynamic_script"}); self.approve("DYNAMIC")
        self.save("OLD", "script", "S02"); self.approve("OLD")
        self.assertEqual([s["artifact_id"] for s in self.r._master("source_script")["segments"]], ["BASE"])
        self.assertNotIn("BASE", [s["artifact_id"] for s in self.r._master("script")["segments"]])
        self.assertEqual(self.stage("source_script")["approved_refs"], [self.ref("BASE")])
        self.assertEqual(self.stage("dynamic_script")["approved_refs"], [self.ref("DYNAMIC")])
        self.assertEqual(self.r.snapshot()["workflow"]["unclassified"][0]["artifact_id"], "OLD")
        with self.assertRaises(ValueError):
            self.save("BAD", "script", metadata={"workflow_stage": "source_script"})

    def test_mixed_segments_and_pending_revisions_never_claim_stage_completion(self):
        self.choose()
        self.save("N1"); self.approve("N1")
        self.save("N2")
        stage = self.stage("novel")
        self.assertEqual(stage["status"], "mixed")
        self.assertEqual(stage["counts"], {"segments": 2, "approved": 1, "needs_review": 0, "pending_candidates": 1, "initial_drafts": 1})
        self.approve("N2")
        self.assertEqual(self.stage("novel")["status"], "approved")
        self.assertEqual(self.stage("novel")["completion_status"], "unknown")
        self.save("N1", base=1)
        self.assertEqual(self.stage("novel")["status"], "mixed")
        self.assertEqual(self.stage("novel")["counts"]["initial_drafts"], 0)
        novel_suggestion = next(s for s in self.stage("outline")["dependency_suggestions"] if s["stage_key"] == "novel")
        self.assertEqual(novel_suggestion["refs"], [self.ref("N1"), self.ref("N2")])

    def test_research_is_not_global_style_and_style_requires_fixed_scope(self):
        self.save("RESEARCH", "style_constraints"); self.approve("RESEARCH")
        self.assertEqual(self.r.snapshot()["global_style"]["status"], "missing")
        for bad in ({"kind": "style_bible", "scope": "S01"}, {"kind": "research", "metadata": {"category": "style"}}):
            with self.assertRaises(ValueError):
                self.save("BAD", **bad)
        self.style()
        self.assertEqual(self.r.snapshot()["global_style"]["status"], "candidate")
        self.approve("STYLE")
        self.assertEqual(self.r.snapshot()["global_style"]["approved_ref"], self.ref("STYLE"))
        self.assertEqual(self.r.snapshot()["global_style"]["semantic_compliance"], "not_assessed")

    def test_downstream_modules_freeze_approved_style_and_pending_does_not_displace(self):
        self.style(); self.approve("STYLE"); self.style(base=1)
        for index, module in enumerate(("screenplay", "novel-to-screenplay", "director", "director-agent", "vfx", "vfx-agent", "assets", "seedance-prompt")):
            task = self.task("T" + str(index), module=module)
            self.assertEqual(task["inputs"], [self.ref("STYLE")])
            self.assertEqual(task["style_context"]["status"], "bound")
            self.assertEqual(task["style_context"]["semantic_compliance"], "not_assessed")
            self.assertEqual(task["missing_context"], [])
        self.assertEqual(self.r.snapshot()["global_style"]["pending_refs"], [self.ref("STYLE", 2)])
        with self.assertRaises(ConflictError):
            self.task("EXPLICIT-CANDIDATE", inputs=[self.ref("STYLE", 2)])

    def test_approved_style_change_only_invalidates_exact_declared_consumers(self):
        self.choose()
        self.style(); self.approve("STYLE")
        self.save("N"); self.approve("N")
        task = self.task(module="director")
        result = self.call("task.submit", task_id=task["task_id"], artifact_id="D", kind="director", content="合成导演稿", base_version=0)
        self.approve("D")
        self.assertEqual(result["artifact"]["deps"], [self.ref("STYLE")])
        self.assertEqual(result["artifact"]["metadata"]["style_context"]["status"], "bound")
        self.style(base=1)
        self.assertEqual(self.stage("director")["status"], "approved")
        result = self.approve("STYLE", 2)
        self.assertEqual(result["invalidated"], ["D"])
        self.assertEqual(self.stage("director")["status"], "needs_review")
        suggestion = next(s for s in self.stage("vfx")["dependency_suggestions"] if s["stage_key"] == "director")
        self.assertEqual(suggestion["refs"], [])
        self.assertEqual(suggestion["status"], "needs_review")
        self.assertEqual(self.r._artifact("N")["status"], "approved")
        with self.assertRaises(ConflictError):
            self.task("EXPLICIT-OLD", inputs=[self.ref("STYLE")])

    def test_missing_style_allows_draft_and_never_backfills_history(self):
        task = self.task()
        self.assertEqual(task["inputs"], [])
        self.assertEqual(task["missing_context"], ["global_style"])
        old = self.save("OLD", "script")
        self.assertEqual(old["metadata"]["style_context"]["status"], "missing")
        self.style(); self.approve("STYLE")
        self.assertEqual(self.r._artifact("OLD"), old)
        old_view = next(a for a in self.r.snapshot()["current_content"] if a["artifact_id"] == "OLD")
        self.assertEqual(old_view["style_context"]["status"], "missing_reference")
        self.assertEqual(old_view["deps"], [])
        self.assertEqual(old_view["metadata"]["style_context"]["status"], "missing")
        submitted = self.call("task.submit", task_id=task["task_id"], artifact_id="D", kind="director", content="旧任务新候选", base_version=0)
        self.assertEqual(submitted["artifact"]["deps"], [])
        self.assertEqual(submitted["artifact"]["metadata"]["style_context"]["status"], "missing_reference")
        manual = self.save("MANUAL", "vfx", deps=[self.ref("STYLE")], metadata={"style_context": {"semantic_compliance": "approved"}})
        self.assertEqual(manual["metadata"]["style_context"]["semantic_compliance"], "not_assessed")

    def test_style_approval_invalidates_declared_production_chain_and_open_tasks(self):
        self.choose()
        self.style(); self.approve("STYLE")
        self.save("LEGACY-D", "director"); self.approve("LEGACY-D")
        original_legacy = self.r._artifact("LEGACY-D")
        previous = None
        for aid, module, kind in (("SCRIPT", "screenplay", "script"), ("DIR", "director", "director"), ("VFX", "vfx", "vfx"), ("ASSET", "assets", "asset")):
            task = self.task("BUILD-" + aid, module, [self.ref(previous)] if previous else [], scope="scene/" + aid)
            metadata = {"workflow_stage": "dynamic_script"} if kind == "script" else {}
            self.call("task.submit", task_id=task["task_id"], artifact_id=aid, kind=kind, content="合成生产候选", base_version=0, metadata=metadata)
            self.approve(aid)
            self.task("OPEN-" + aid, module, [self.ref(aid)])
            previous = aid
        self.style(base=1)
        self.assertTrue(all(self.r._artifact(aid)["status"] == "approved" for aid in ("SCRIPT", "DIR", "VFX", "ASSET")))
        result = self.approve("STYLE", 2)
        self.assertEqual(set(result["invalidated"]), {"SCRIPT", "DIR", "VFX", "ASSET"})
        snap = self.r.snapshot()
        self.assertTrue(all(t["status"] == "needs_review" for t in snap["tasks"] if t["task_id"].startswith("OPEN-")))
        for key in ("dynamic_script", "director", "vfx", "asset"):
            self.assertEqual(self.stage(key)["status"], "needs_review")
        self.assertEqual(self.r._artifact("LEGACY-D"), original_legacy)
        self.assertEqual(original_legacy["deps"], [])
        self.assertEqual(original_legacy["metadata"]["style_context"]["status"], "missing_reference")

    def test_needs_review_style_does_not_block_new_draft_or_fabricate_dependency(self):
        self.save("N"); self.approve("N")
        self.save("STYLE", "style_bible", "project/style", deps=[self.ref("N")]); self.approve("STYLE")
        self.save("N", base=1); self.approve("N", 2)
        task = self.task()
        self.assertEqual(task["inputs"], [])
        self.assertEqual(task["style_context"]["status"], "needs_review")
        self.assertEqual(task["missing_context"], ["global_style"])
        self.assertEqual(self.r.snapshot()["global_style"]["status"], "needs_review")

    def test_master_metadata_is_exact_revision_read_view_and_does_not_mutate_rows(self):
        self.save("N", metadata={"chapter": {"id": "1", "title": "旧章名"}, "order": 1}); self.approve("N")
        before = self.r.db.execute("SELECT data FROM master_revisions").fetchone()[0]
        self.save("N", base=1, metadata={"chapter": "新章名", "order": 1})
        historical = self.r.dispatch("master.history", {"category": "novel"})["versions"][0]
        self.assertEqual(historical["segments"][0]["metadata"]["chapter"]["title"], "旧章名")
        self.assertEqual(self.r.db.execute("SELECT data FROM master_revisions").fetchone()[0], before)
        self.assertNotIn("metadata", json.loads(before)["segments"][0])


if __name__ == "__main__":
    unittest.main()

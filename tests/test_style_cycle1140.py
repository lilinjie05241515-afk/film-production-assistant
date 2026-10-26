"""Exact task/reference and art-rebase recovery; isolated TEST data only."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from filmprod.core import Registry, ConflictError, content_hash
from filmprod.efficient import compact_result


class StyleCycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="film-cycle1140-TEST-")
        self.r=Registry(Path(self.temp.name)/"TEST-only")
        self.call("project.init",project_id="TEST-CYCLE",title="TEST",test_only=True)
        self.call("project.workflow.set",mode="screenplay",base_revision=0)
        self.script=self.save("SCRIPT","script","episode/1","S01 门口\n甲：请进。")
        self.approve(self.script)
        self.style=self.save("STYLE","style_bible","project/style","# 完整基准\n视觉：灰白墙。\n导演：固定机位。\n表演：克制。\n声音：风声。\n世界：不能穿墙。",[self.ref(self.script)])
        self.approve(self.style)

    def tearDown(self):
        self.r.close();self.temp.cleanup()

    def call(self,action,**p):
        p.setdefault("op_id",uuid.uuid4().hex)
        if action!="project.init":p.setdefault("expected_project_id","TEST-CYCLE")
        return self.r.dispatch(action,p)

    def ref(self,a):return {k:a[k] for k in ("artifact_id","version","sha256")}

    def save(self,aid,kind,scope,content,deps=None,**p):
        old=self.r._artifact(aid)
        return self.call("artifact.save",artifact_id=aid,kind=kind,scope=scope,content=content,base_version=old["version"] if old else 0,deps=deps or [],**p)["artifact"]

    def approve(self,a):return self.call("content.approve",artifact_id=a["artifact_id"],version=a["version"],scope=a["scope"],actor="test",evidence="TEST synthetic",synthetic=True)

    def task(self,known=True,inputs=None,tid="WRITER",**extra):
        p=dict(task_id=tid,title="TEST writer",module="screenwriter",scope="episode/1",inputs=inputs or [],must_keep=["完整基准"],allowed_changes=["局部动作"],requirements=[])
        if known:p["artifact_id"]="SCRIPT"
        p.update(extra)
        return self.call("task.create",**p)

    def submit(self,tid="WRITER",body="S01 门口\n甲侧身让开。\n甲：请进。",**extra):
        return self.call("task.submit",task_id=tid,artifact_id="SCRIPT",kind="script",content=body,base_version=self.r._artifact("SCRIPT")["version"],**extra)

    def new_script(self,known=True):
        self.task(known=known)
        a=self.submit()["artifact"];self.approve(a);return a

    def rebase(self,script,working=None,source=None,quote="灰白墙",replacement="浅灰旧墙",**extra):
        source=source or self.style;working=working or source
        read=self.r.dispatch("art.read",{"expected_project_id":"TEST-CYCLE"})
        edits=[] if quote is None else [{"start":source["content"].index(quote),"end":source["content"].index(quote)+len(quote),"quote":quote,"replacement":replacement}]
        previous=[self.ref(self.r._artifact(d["artifact_id"],d["version"])) for d in source["deps"]]
        inputs=[self.ref(script) if d["artifact_id"]==script["artifact_id"] else d for d in previous]
        p=dict(base_revision=read["revision"],selection_id=read["active_selection_id"],source_ref=self.ref(source),working_ref=self.ref(working),baseline=read["current_style"],base_version=working["version"],edits=edits,scope_judgment="within_baseline",reason="TEST 核对新剧本后调整墙面措辞",user_request={"source":"conversation","reference":"TEST-user","quote":"按最新剧本核对完整基准，先保存候选"},synthetic=True,rebase={"previous_inputs":previous,"inputs":inputs})
        p.update(extra)
        return self.call("art.revise",**p)

    def test_actual_task_script_art_rebase_approval_director_success(self):
        task=self.task();self.assertEqual(task["inputs"],[])
        self.assertEqual(task["style_binding"]["mode"],"frozen_reference")
        self.assertEqual(task["style_binding"]["dependency_path"], [self.ref(self.style),self.ref(self.script)])
        script=self.submit()["artifact"]
        self.assertEqual(script["deps"],[])
        self.assertEqual(script["metadata"]["style_reference"]["content"],self.style["content"])
        self.approve(script)
        self.assertEqual(self.r._artifact("STYLE",1)["status"],"needs_review")
        style=self.rebase(script)["artifact"]
        self.assertEqual(style["status"],"candidate")
        self.assertEqual(style["deps"],[{"artifact_id":"SCRIPT","version":2}])
        self.assertEqual(self.r._artifact("STYLE",1)["deps"],[{"artifact_id":"SCRIPT","version":1}])
        self.assertIn("导演：固定机位。",style["content"])
        self.assertEqual(self.r.snapshot()["art"]["current_style"],self.ref(self.style))
        self.approve(style)
        director=self.call("task.create",task_id="DIRECTOR",title="TEST director",module="director",scope="scene/1",artifact_id="DIRECTOR",inputs=[self.ref(script)],must_keep=[],allowed_changes=[],requirements=[])
        self.assertIn({"artifact_id":"STYLE","version":2},director["inputs"])
        self.assertFalse(self.r._dependency_stale(self.ref(style)))

    def test_unknown_target_checkpoint_submit_preserves_frozen_original_inputs(self):
        task=self.task(known=False)
        self.assertEqual(task["inputs"],[{"artifact_id":"STYLE","version":1}])
        checkpoint=self.call("task.checkpoint",task_id="WRITER",draft="S01 门口\n甲让开。",completed=[],decisions=[],unresolved=[],next_step="TEST submit")["checkpoint"]
        self.assertEqual(checkpoint["style_binding"]["content"],self.style["content"])
        result=self.call("task.submit_checkpoint",task_id="WRITER",artifact_id="SCRIPT",kind="script",base_version=1,checkpoint_id=checkpoint["checkpoint_id"],expected_draft_sha256=checkpoint["draft_sha256"])
        self.assertEqual(result["artifact"]["deps"],[])
        saved=self.r._get("tasks","task_id","WRITER")
        self.assertEqual(saved["inputs"],task["inputs"])
        self.assertEqual(saved["style_execution_lock"],task["style_execution_lock"])
        self.assertEqual(saved["submitted_style_reference"]["mode"],"frozen_reference")

    def test_compact_reference_has_identity_without_full_prose_and_resume_has_full(self):
        task=self.task();compact=compact_result("task.create",task)
        self.assertEqual(compact["style_binding"]["artifact"],self.ref(self.style))
        self.assertEqual(compact["style_context"]["status"],"frozen_reference")
        self.assertNotIn(self.style["content"],json.dumps(compact,ensure_ascii=False))
        resume=self.r.dispatch("context.read",{"expected_project_id":"TEST-CYCLE","mode":"resume","task_id":"WRITER"})
        self.assertEqual(resume["frozen_style_reference"]["content"],self.style["content"])

    def test_explicit_cycle_is_rejected_at_create_and_late_submit(self):
        with self.assertRaises(ConflictError):self.task(inputs=[self.ref(self.style)])
        task=self.task(known=False,inputs=[self.ref(self.style)])
        self.assertNotIn("style_binding",task)
        with self.assertRaises(ConflictError):self.submit()
        self.assertEqual(self.r._artifact("SCRIPT")["version"],1)

    def test_direct_save_explicit_cycle_is_rejected(self):
        with self.assertRaises(ConflictError):self.save("SCRIPT","script","episode/1","新稿",[self.ref(self.style)],use_current_style=True)

    def test_ordinary_edit_automatic_policy_freezes_style_and_preserves_history(self):
        a=self.save("SCRIPT","script","episode/1","S01 新动作。",use_current_style=True)
        self.assertEqual(a["deps"],[])
        self.assertEqual(a["metadata"]["style_reference"]["content"],self.style["content"])
        b=self.save("SCRIPT","script","episode/1","S01 再修改。",use_current_style=True)
        prior=b["metadata"]["style_reference"]["previous_reference"]
        self.assertEqual(prior["prior_output_ref"],self.ref(a))
        self.assertNotIn("content",prior);self.assertNotIn("previous_reference",prior)
        c=self.save("SCRIPT","script","episode/1","S01 沿用准确来源。")
        self.assertEqual(c["metadata"]["style_reference"],b["metadata"]["style_reference"])

    def test_plain_edit_cannot_forge_or_drop_frozen_reference(self):
        self.task();a=self.submit()["artifact"]
        with self.assertRaises(ConflictError):self.save("SCRIPT","script","episode/1","伪造引用",metadata={"style_reference":{}})
        b=self.save("SCRIPT","script","episode/1","完整手改文本")
        self.assertEqual(b["metadata"]["style_reference"],a["metadata"]["style_reference"])

    def test_new_task_without_binding_cannot_drop_previous_reference(self):
        self.task();a=self.submit()["artifact"]
        # Explicit same style would cycle; a non-style legacy writer module
        # must at least retain and validate the previous frozen reference.
        self.task(tid="LEGACY",module="script")
        b=self.submit(tid="LEGACY")["artifact"]
        self.assertEqual(b["metadata"]["style_reference"],a["metadata"]["style_reference"])

    def test_style_change_blocks_checkpoint_and_submit(self):
        self.task()
        newer=self.save("STYLE","style_bible","project/style",self.style["content"]+"\n新增风格条款。",[self.ref(self.script)])
        self.approve(newer)
        with self.assertRaises(ConflictError):self.call("task.checkpoint",task_id="WRITER",draft="新稿",completed=[],decisions=[],unresolved=[],next_step="TEST")
        with self.assertRaises(ConflictError):self.submit()
        self.assertFalse(self.r._resume("WRITER")["execution_compatibility"]["compatible"])

    def test_style_reference_lock_and_full_text_cannot_be_changed(self):
        self.task();task=self.r._get("tasks","task_id","WRITER")
        task["style_binding"]["content"]="伪造风格"
        self.r._put("tasks","task_id","WRITER",task)
        with self.assertRaises(ConflictError):self.submit()

    def test_old_execution_lock_still_rejects_reference_task(self):
        self.task();task=self.r._get("tasks","task_id","WRITER")
        task["execution_lock"]["system_version"]="1.12.0"
        self.r._put("tasks","task_id","WRITER",task)
        with self.assertRaises(ValueError):self.submit()

    def test_rebase_can_retain_full_text_without_auto_approval(self):
        script=self.new_script();result=self.rebase(script,quote=None)
        self.assertEqual(result["artifact"]["content"],self.style["content"])
        self.assertEqual(self.r._artifact("STYLE",1)["status"],"needs_review")
        self.assertEqual(result["art_integration"]["rebase"]["previous_inputs"],[self.ref(self.script)])
        self.approve(result["artifact"])

    def test_cloud_working_changes_are_preserved_before_dependency_rebase(self):
        script=self.new_script()
        body=self.style["content"].replace("灰白墙","浅灰旧墙")
        working=self.save("STYLE","style_bible","project/style",body,self.style["deps"])
        result=self.rebase(script,working=working)["artifact"]
        self.assertEqual(result["content"],body);self.assertEqual(result["version"],3)
        self.assertEqual(self.r._artifact("STYLE",2)["content"],body)
        self.approve(result)

    def test_unexplained_cloud_edit_blocks_rebase(self):
        script=self.new_script();working=self.save("STYLE","style_bible","project/style",self.style["content"]+"\n未解释声音修改。",self.style["deps"])
        with self.assertRaises(ConflictError):self.rebase(script,working=working)

    def test_rebase_requires_complete_unchanged_source_identity_set(self):
        script=self.new_script()
        for rebase in ({"previous_inputs":[],"inputs":[self.ref(script)]},
                       {"previous_inputs":[self.ref(self.script)],"inputs":[self.ref(script),self.ref(script)]},
                       {"previous_inputs":[self.ref(script)],"inputs":[self.ref(script)]},
                       {"previous_inputs":[self.ref(self.script)],"inputs":[self.ref(self.script)]}):
            with self.assertRaises(ValueError):self.rebase(script,rebase=rebase)

    def test_rebase_only_current_approved_script_not_candidate(self):
        self.task();script=self.submit()["artifact"]
        with self.assertRaises(ConflictError):self.rebase(script)

    def test_rebase_candidate_approval_rechecks_new_script(self):
        script=self.new_script();candidate=self.rebase(script)["artifact"]
        # Simulate a genuine independent new script candidate, explicitly
        # preserving its historical reference; a new current style is still
        # under review, so normal edit cannot pretend it is fresh.
        newer=self.save("OTHER","script","episode/2","独立片段")
        self.approve(newer)
        self.assertEqual(self.r._artifact("STYLE",1)["status"],"needs_review")
        self.approve(candidate)
        next_script=self.save("SCRIPT","script","episode/1","下一轮剧本。",use_current_style=True)
        self.approve(next_script)
        self.assertEqual(self.r._artifact("STYLE",2)["status"],"needs_review")
        self.assertFalse(self.r._dependency_stale(self.ref(next_script)))

    def test_rebase_task_uses_new_inputs_and_legacy_lock_rejected(self):
        script=self.new_script()
        task=self.call("task.create",task_id="ART",title="TEST rebase",module="art_director",scope="project/style",artifact_id="STYLE",inputs=[self.ref(script)],must_keep=[],allowed_changes=[],requirements=[])
        task["execution_lock"]["system_version"]="1.12.0";self.r._put("tasks","task_id","ART",task)
        with self.assertRaises(ValueError):self.rebase(script,task_id="ART")

    def test_frozen_style_cannot_hide_an_unrelated_stale_source(self):
        external=self.save("EXT","research","source/ext","原外部来源")
        self.style=self.save("STYLE","style_bible","project/style",self.style["content"],[self.ref(self.script),self.ref(external)])
        self.approve(self.style)
        self.save("EXT","research","source/ext","新的未批准来源")
        self.assertEqual(self.r._artifact("STYLE")["status"],"approved")
        with self.assertRaises(ConflictError):self.task()
        with self.assertRaises(ConflictError):self.save("SCRIPT","script","episode/1","新稿",use_current_style=True)

    def test_rebase_rejects_unrelated_stale_dependency_even_when_listed(self):
        external=self.save("EXT","research","source/ext","旧声音依据");self.approve(external)
        self.style=self.save("STYLE","style_bible","project/style",self.style["content"],[self.ref(self.script),self.ref(external)]);self.approve(self.style)
        script=self.new_script()
        newer=self.save("EXT","research","source/ext","新声音依据");self.approve(newer)
        with self.assertRaises(ConflictError):self.rebase(script)
        with self.assertRaises(ConflictError):self.rebase(script,rebase={"previous_inputs":[self.ref(self.script),self.ref(external)],"inputs":[self.ref(script),self.ref(newer)]})

    def test_candidate_approval_rejects_script_change_after_rebase(self):
        # A legacy direct save has no new policy flag and preserves its empty
        # deps. This also exercises concurrency with an older client.
        script=self.save("SCRIPT","script","episode/1","SCRIPT2 explicit legacy save");self.approve(script)
        candidate=self.rebase(script)["artifact"]
        newer=self.save("SCRIPT","script","episode/1","SCRIPT3 concurrent save");self.approve(newer)
        with self.assertRaises(ConflictError):self.approve(candidate)

    def test_frozen_reference_restore_cannot_drop_or_forge_origin(self):
        self.task();a=self.submit()["artifact"]
        restored=self.call("artifact.restore",artifact_id="SCRIPT",version=1,base_version=2)["artifact"]
        self.assertEqual(restored["metadata"]["style_reference"],a["metadata"]["style_reference"])
        self.assertEqual(restored["metadata"]["restored_from_version"],1)

    def test_rebase_task_with_exact_new_inputs_submits_candidate(self):
        script=self.new_script()
        self.call("task.create",task_id="ART",title="TEST rebase",module="art_director",scope="project/style",artifact_id="STYLE",inputs=[self.ref(script)],must_keep=[],allowed_changes=[],requirements=[])
        result=self.rebase(script,task_id="ART")
        self.assertEqual(result["task"]["status"],"submitted")
        self.assertEqual(result["artifact"]["deps"],[{"artifact_id":"SCRIPT","version":2}])
        self.approve(result["artifact"])

    def test_restore_history_after_reference_advance_keeps_both_exact_origins(self):
        self.task();script2=self.submit()["artifact"];self.approve(script2)
        style2=self.rebase(script2)["artifact"];self.approve(style2)
        self.task(tid="NEXT")
        script3=self.submit(tid="NEXT",body="S01 新稿动作。") ["artifact"]
        restored=self.call("artifact.restore",artifact_id="SCRIPT",version=2,base_version=3)["artifact"]
        self.assertEqual(restored["content"],script2["content"])
        self.assertEqual(restored["status"],"candidate")
        self.assertEqual(restored["metadata"]["style_reference"],script3["metadata"]["style_reference"])
        self.assertEqual(restored["metadata"]["restored_style_reference"]["artifact"],self.ref(self.style))
        self.assertEqual(restored["metadata"]["restored_style_reference"]["prior_output_ref"],self.ref(script2))
        self.assertEqual(self.r._artifact("SCRIPT",2)["metadata"],script2["metadata"])
        with self.assertRaises(ConflictError):self.save("SCRIPT","script","episode/1","伪造旧引用",metadata={"style_reference":script2["metadata"]["style_reference"]})

    def test_missing_binding_with_remaining_execution_lock_rejected(self):
        self.task();task=self.r._get("tasks","task_id","WRITER")
        task.pop("style_binding");self.r._put("tasks","task_id","WRITER",task)
        with self.assertRaises(ConflictError):self.submit()
        self.assertEqual(self.r._artifact("SCRIPT")["version"],1)

    def test_missing_binding_and_lock_with_frozen_context_rejected(self):
        self.task();task=self.r._get("tasks","task_id","WRITER")
        task.pop("style_binding");task.pop("style_execution_lock")
        self.r._put("tasks","task_id","WRITER",task)
        with self.assertRaises(ConflictError):self.submit()
        self.assertFalse(self.r._resume("WRITER")["execution_compatibility"]["compatible"])

    def test_checkpoint_binding_evidence_rejects_missing_current_fields(self):
        self.task(known=False)
        checkpoint=self.call("task.checkpoint",task_id="WRITER",draft="S01 原完整检查点。",completed=[],decisions=[],unresolved=[],next_step="TEST")
        task=self.r._get("tasks","task_id","WRITER")
        task.pop("style_binding");task.pop("style_execution_lock")
        self.r._put("tasks","task_id","WRITER",task)
        with self.assertRaises(ConflictError):self.call("task.submit_checkpoint",task_id="WRITER",artifact_id="SCRIPT",kind="script",base_version=1,checkpoint_id=checkpoint["checkpoint"]["checkpoint_id"],expected_draft_sha256=checkpoint["checkpoint"]["draft_sha256"])

    def test_explicit_style_without_automatic_binding_remains_compatible(self):
        task=self.call("task.create",task_id="D",title="TEST explicit",module="director",scope="scene/1",artifact_id="D",inputs=[self.ref(self.style)],must_keep=[],allowed_changes=[],requirements=[])
        self.assertNotIn("style_binding",task)
        self.call("task.checkpoint",task_id="D",draft="固定镜头。",completed=[],decisions=[],unresolved=[],next_step="TEST")
        result=self.call("task.submit",task_id="D",artifact_id="D",kind="director",content="固定镜头。",base_version=0)
        self.assertEqual(result["task"]["status"],"submitted")

    def test_task_created_without_any_style_remains_compatible(self):
        other=Registry(Path(self.temp.name)/"TEST-no-style")
        try:
            other.dispatch("project.init",dict(op_id="init",project_id="TEST-NONE",title="TEST",test_only=True))
            task=other.dispatch("task.create",dict(op_id="task",task_id="D",title="TEST",module="director",scope="scene/1",inputs=[],must_keep=[],allowed_changes=[],requirements=[]))
            self.assertNotIn("style_binding",task)
            result=other.dispatch("task.submit",dict(op_id="submit",task_id="D",artifact_id="D",kind="director",content="未定风格的完整候选。",base_version=0))
            self.assertEqual(result["task"]["status"],"submitted")
        finally:other.close()

    def test_rebase_preserves_fresh_unapproved_research_without_approving_it(self):
        external=self.save("EXT","research","source/ext","仍是准确当前研究候选。")
        self.style=self.save("STYLE","style_bible","project/style",self.style["content"],[self.ref(self.script),self.ref(external)]);self.approve(self.style)
        script=self.new_script();candidate=self.rebase(script)["artifact"]
        self.assertIn({"artifact_id":"EXT","version":1},candidate["deps"])
        self.approve(candidate)
        self.assertEqual(self.r._artifact("EXT")["status"],"candidate")
        self.assertIsNone(self.r._approved_pointer(external))

    def test_rebase_rejects_unapproved_research_that_changed_after_baseline(self):
        external=self.save("EXT","research","source/ext","研究候选v1。")
        self.style=self.save("STYLE","style_bible","project/style",self.style["content"],[self.ref(self.script),self.ref(external)]);self.approve(self.style)
        script=self.new_script()
        self.save("EXT","research","source/ext","研究候选v2。")
        with self.assertRaises(ConflictError):self.rebase(script)


if __name__=="__main__":unittest.main()

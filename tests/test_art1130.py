"""Art-direction integration tests: isolated TEST data, no creative adoption."""
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from filmprod.core import Registry, ConflictError, content_hash, output_kinds
from filmprod.art1130 import validate_art_payload


class ArtTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="filmprod-art-TEST-")
        self.root = Path(self.temp.name) / "TEST-project"
        self.r = Registry(self.root)
        self.call("project.init", project_id="TEST-ART", title="美术合成验证", test_only=True)
        self.user = {"source":"conversation","reference":"TEST-user-message","quote":"选择备选，保留声音、表演与世界规则。"}
        self.scene = self.save("scene", "script", "scene/01", "同一雨夜门口场景，两人见面。")
        self.approve(self.scene)
        self.main = self.save("main", "research", "art/main", "主选：暖金色墙面，磨损木器，人物保持既有外貌。", [self.ref(self.scene)])
        self.alt = self.save("alternate", "research", "art/alternate", "备选：冷青色墙面，湿润石面，人物保持既有外貌。", [self.ref(self.scene)])

    def tearDown(self):
        self.r.close(); self.temp.cleanup()

    def call(self, action, **payload):
        payload.setdefault("op_id", uuid.uuid4().hex)
        if action != "project.init": payload.setdefault("expected_project_id", "TEST-ART")
        return self.r.dispatch(action, payload)

    def ref(self, a):
        return {k:a[k] for k in ("artifact_id","version","sha256")}

    def save(self, aid, kind, scope, content, deps=None, metadata=None):
        old = self.r._artifact(aid)
        return self.call("artifact.save", artifact_id=aid, kind=kind, scope=scope, content=content,
                         base_version=old["version"] if old else 0, deps=deps or [], metadata=metadata or {})["artifact"]

    def approve(self, a):
        return self.call("content.approve", artifact_id=a["artifact_id"], version=a["version"], scope=a["scope"],
                         evidence="TEST synthetic approval", actor="test", synthetic=True)

    def read(self, **payload):
        return self.r.dispatch("art.read", {"expected_project_id":"TEST-ART", **payload})

    def write(self, action, **payload):
        payload.setdefault("base_revision", self.read()["revision"])
        return self.call(action, **payload)

    def prepare(self, working=None, baseline=None, comparison_id="comparison", **extra):
        payload = dict(comparison_id=comparison_id,title="同场景主备比较", target_artifact_id="style",
                       baseline=self.ref(baseline) if baseline else None, working_ref=self.ref(working) if working else None,
                       main=self.ref(self.main),alternate=self.ref(self.alt),context=[self.ref(self.scene)],visual_ranges=[])
        if working and "visual_ranges" not in extra:
            q = "旧视觉：灰白墙。"
            start = working["content"].index(q)
            payload["visual_ranges"]=[{"start":start,"end":start+len(q),"quote":q}]
        elif not working:
            payload["nonvisual_sections"]={"direction":"导演约束待确认。","performance":"表演克制。","sound":"保留雨声。","world_rules":"没有穿墙能力。"}
        payload.update(extra)
        return self.write("art.prepare", **payload)

    def select(self, choice="alternate", comparison_id="comparison", **extra):
        return self.write("art.select", comparison_id=comparison_id, choice=choice, user_request=self.user, synthetic=True, **extra)["selection"]

    def integrate(self, selection, base_version=0, **extra):
        return self.write("art.integrate", selection_id=selection["selection_id"], base_version=base_version, **extra)

    def style(self):
        return self.save("style","style_bible","project/style", "# 全剧基准\n旧视觉：灰白墙。\n导演：固定机位。\n表演：停顿后开口。\n声音：雨声不中断。\n世界：不能穿墙。", [self.ref(self.scene)])

    def revise(self, source, quote=None, replacement=None, working=None, **extra):
        working=working or source
        edits=[] if quote is None else [{"start":source["content"].index(quote),"end":source["content"].index(quote)+len(quote),"quote":quote,"replacement":replacement}]
        payload=dict(selection_id=self.read()["active_selection_id"],source_ref=self.ref(source),working_ref=self.ref(working),
                     baseline=self.read()["current_style"],base_version=working["version"],edits=edits,
                     scope_judgment="within_baseline",reason="TEST 基准内局部措辞校正",user_request=self.user,synthetic=True)
        payload.update(extra)
        return self.write("art.revise",**payload)

    def selected_style(self):
        self.prepare();a=self.integrate(self.select())["artifact"];self.approve(a);return a

    def logical(self):
        return {t:[tuple(r) for r in self.r.db.execute("SELECT * FROM " + t)] for t in ("settings","artifacts","approved_segments","decisions","tasks","operations","events")}

    def test_initial_alternate_is_complete_candidate_not_approval(self):
        self.prepare(); selection=self.select(); result=self.integrate(selection)
        a=result["artifact"]
        self.assertEqual(a["kind"],"style_bible"); self.assertEqual(a["scope"],"project/style")
        self.assertIn(self.alt["content"],a["content"]); self.assertNotIn(self.main["content"],a["content"])
        for phrase in ("导演约束待确认。","表演克制。","保留雨声。","没有穿墙能力。"):
            self.assertIn(phrase,a["content"])
        self.assertIsNone(self.read()["current_style"])
        self.assertEqual(a["status"],"candidate")
        self.approve(a)
        self.assertEqual(self.read()["current_style"],self.ref(a))
        self.assertEqual(self.r._artifact("main")["status"],"candidate")

    def test_current_working_nonvisual_manual_edits_preserved(self):
        baseline=self.style(); self.approve(baseline)
        working=self.save("style","style_bible","project/style",baseline["content"]+"\n云端手改声音：加远处犬吠。",baseline["deps"])
        self.prepare(working,baseline); selection=self.select(); result=self.integrate(selection,2)
        self.assertEqual(result["artifact"]["artifact_id"],"style")
        self.assertEqual(result["artifact"]["content"],working["content"].replace("旧视觉：灰白墙。",self.alt["content"]))
        self.assertEqual(self.read()["current_style"],self.ref(baseline))
        self.approve(result["artifact"])
        self.assertEqual(self.read()["current_style"],self.ref(result["artifact"]))

    def test_old_approved_version_not_used_as_current_working(self):
        baseline=self.style(); self.approve(baseline)
        self.save("style","style_bible","project/style",baseline["content"]+"\n未批准手改。",baseline["deps"])
        with self.assertRaises(ConflictError): self.prepare(baseline,baseline)

    def test_selection_does_not_approve_or_invalidate_downstream(self):
        baseline=self.style(); self.approve(baseline)
        d=self.save("director","director","scene/01","镜头建议",[self.ref(baseline)]);self.approve(d)
        self.prepare(baseline,baseline);self.select()
        self.assertEqual(self.r._artifact("director")["status"],"approved")
        self.assertEqual(self.read()["current_style"],self.ref(baseline))

    def test_new_complete_approval_marks_both_full_version_dependents(self):
        baseline=self.style();self.approve(baseline)
        for aid,scope in (("director-a","scene/A"),("director-b","scene/B")):
            a=self.save(aid,"director",scope,"完整分镜建议",[self.ref(baseline)]);self.approve(a)
        self.prepare(baseline,baseline);out=self.integrate(self.select(),1)
        self.assertEqual(self.r._artifact("director-a")["status"],"approved")
        approved=self.approve(out["artifact"])
        self.assertEqual(set(approved["invalidated"]),{"director-a","director-b"})
        self.assertEqual(self.r._artifact("director-a")["status"],"needs_review")
        self.assertEqual(self.r._artifact("director-b")["status"],"needs_review")

    def test_raw_visual_only_cannot_be_approved_as_managed_style(self):
        baseline=self.style();self.approve(baseline)
        self.prepare(baseline,baseline);self.select()
        visual=self.save("style","style_bible","project/style",self.alt["content"],[self.ref(self.scene)])
        with self.assertRaises(ConflictError):self.approve(visual)
        self.assertEqual(self.read()["current_style"],self.ref(baseline))

    def test_switch_selection_rejects_old_choice_and_keeps_proposals(self):
        self.prepare();first=self.select("main");second=self.select("alternate")
        with self.assertRaises(ConflictError):self.integrate(first)
        result=self.integrate(second)
        self.assertIn(self.alt["content"],result["artifact"]["content"])
        self.assertEqual(self.r._artifact("main")["content"],self.main["content"])
        self.assertEqual(len(self.read()["selections"]),2)

    def test_fusion_requires_an_independent_complete_proposal(self):
        self.prepare()
        with self.assertRaises(ValueError):self.select("fusion",fusion=self.ref(self.main))
        fusion=self.save("fusion","research","art/fusion","融合：冷青主调，保留暖色灯火。",[self.ref(self.scene),self.ref(self.main),self.ref(self.alt)])
        out=self.integrate(self.select("fusion",fusion=self.ref(fusion)))
        self.assertIn(fusion["content"],out["artifact"]["content"])
        self.assertNotIn(self.main["content"],out["artifact"]["content"])
        self.assertNotIn(self.alt["content"],out["artifact"]["content"])

    def test_approve_changed_baseline_or_changed_working_rejected(self):
        baseline=self.style();self.approve(baseline);self.prepare(baseline,baseline);choice=self.select()
        self.save("style","style_bible","project/style",baseline["content"]+"\n新工作修改。",baseline["deps"])
        with self.assertRaises(ConflictError):self.integrate(choice,1)

    def test_wrong_identity_or_cas_does_not_write(self):
        self.prepare();before=self.logical()
        with self.assertRaises(ConflictError):self.write("art.select",comparison_id="comparison",choice="main",user_request=self.user,synthetic=True,base_revision=0)
        with self.assertRaises(ConflictError):self.r.dispatch("art.read",{"expected_project_id":"WRONG"})
        self.assertEqual(before,self.logical())

    def test_ranges_unicode_slice_nonoverlap_and_full_replace_rejected(self):
        style=self.style();self.approve(style)
        for ranges in ([{"start":0,"end":2,"quote":"错误"}],
                       [{"start":0,"end":len(style["content"]),"quote":style["content"]}]):
            with self.assertRaises(ValueError):self.prepare(style,style,visual_ranges=ranges)
        with self.assertRaises(ValueError):validate_art_payload("art.prepare",{"op_id":"x","expected_project_id":"p","base_revision":0,"comparison_id":"x","title":"x","target_artifact_id":"style","baseline":self.ref(style),"working_ref":self.ref(style),"main":self.ref(self.main),"alternate":self.ref(self.alt),"context":[self.ref(self.scene)],"visual_ranges":[{"start":1,"end":3,"quote":"ab"},{"start":2,"end":4,"quote":"cd"}]})

    def test_unknown_fields_and_content_without_id_rejected(self):
        with self.assertRaises(ValueError):validate_art_payload("art.read",{"expected_project_id":"TEST","include_content":True})
        with self.assertRaises(ValueError):validate_art_payload("art.select",{"op_id":"x","expected_project_id":"TEST","base_revision":0,"comparison_id":"x","choice":"main","user_request":self.user,"synthetic":True,"approve":True})

    def test_main_alt_need_same_exact_context_and_distinct_body(self):
        wrong=self.save("wrong","research","art/wrong","不同方案",[])
        with self.assertRaises(ConflictError):self.prepare(alternate=self.ref(wrong))
        copied=self.save("copied","research","art/copied",self.main["content"],[self.ref(self.scene)])
        with self.assertRaises(ValueError):self.prepare(alternate=self.ref(copied))

    def test_stable_style_identity_rejects_new_target(self):
        baseline=self.style();self.approve(baseline)
        with self.assertRaises(ConflictError):self.prepare(baseline,baseline,target_artifact_id="style-new")

    def test_read_summary_has_no_prose_and_readonly_preserves_bytes(self):
        self.prepare();self.select()
        before=self.logical();view=self.read()
        self.assertNotIn(self.main["content"],json.dumps(view,ensure_ascii=False))
        detailed=self.read(comparison_id="comparison",include_content=True)
        self.assertEqual(detailed["proposals"]["main"]["content"],self.main["content"])
        self.assertIn(self.alt["content"],detailed["integration_preview"])
        self.assertEqual(before,self.logical())
        self.r.close();db=self.root/".project/registry.sqlite3";raw=db.read_bytes();self.r=Registry.open_readonly(self.root)
        self.read();self.r.snapshot();self.assertEqual(raw,db.read_bytes())

    def test_idempotent_integrate_returns_same_version(self):
        self.prepare();s=self.select();payload={"selection_id":s["selection_id"],"base_version":0,"base_revision":self.read()["revision"],"op_id":"integrate-once"}
        a=self.write("art.integrate",**payload);b=self.write("art.integrate",**payload)
        self.assertEqual(a,b);self.assertEqual(self.r._artifact("style")["version"],1)

    def test_existing_cloud_page_and_unknown_request_unchanged(self):
        baseline=self.style();self.approve(baseline)
        self.call("master.bind_page",category="style",page_id="page_TEST_keep",base_revision="rev1")
        self.call("sync.intent",sync_id="sync-old",page_id="page_TEST_keep",base_revision="rev1",intended_content="旧云稿")
        self.call("sync.observe",sync_id="sync-old",status="unknown",receipt="TEST timeout")
        before=self.r._list("sync")
        self.prepare(baseline,baseline);self.integrate(self.select(),1)
        self.assertEqual(self.r._binding("style")["page_id"],"page_TEST_keep")
        self.assertEqual(self.r._list("sync"),before)

    def test_activity_task_lock_cannot_be_bypassed(self):
        self.prepare();choice=self.select()
        self.call("task.create",task_id="task",title="TEST style task",module="research",scope="project/style",artifact_id="style",inputs=[self.ref(self.scene)],must_keep=[],allowed_changes=[],requirements=[])
        with self.assertRaises(ConflictError):self.integrate(choice)
        result=self.integrate(choice,task_id="task")
        self.assertEqual(result["task"]["status"],"submitted")

    def test_old_task_execution_lock_rejected(self):
        self.prepare();choice=self.select()
        self.call("task.create",task_id="task",title="TEST style task",module="research",scope="project/style",artifact_id="style",inputs=[self.ref(self.scene)],must_keep=[],allowed_changes=[],requirements=[])
        task=self.r._get("tasks","task_id","task");task["execution_lock"]["system_version"]="0.0.0-old";self.r._put("tasks","task_id","task",task);self.r.db.commit()
        with self.assertRaises(ValueError):self.integrate(choice,task_id="task")
        self.assertIsNone(self.r._artifact("style"))

    def test_new_unapproved_proposal_version_does_not_displace_approved_style(self):
        self.prepare();out=self.integrate(self.select());self.approve(out["artifact"])
        self.save("alternate","research","art/alternate","另一未批准备选草稿。",[self.ref(self.scene)])
        self.assertEqual(self.read()["current_style"],self.ref(out["artifact"]))
        self.assertFalse(self.r._dependency_stale(self.ref(out["artifact"])))

    def test_working_dependency_set_is_preserved(self):
        source=self.save("sound-source","research","sound/reference","明确声音来源")
        self.approve(source)
        baseline=self.style();self.approve(baseline)
        working=self.save("style","style_bible","project/style",baseline["content"], [self.ref(self.scene),self.ref(source)])
        self.prepare(working,baseline);out=self.integrate(self.select(),2)
        self.assertIn({"artifact_id":"sound-source","version":1},out["artifact"]["deps"])

    def test_art_director_output_alias(self):
        self.assertEqual(output_kinds("art_director"),{"research","style_bible"})
        self.assertEqual(output_kinds("film-art-director"),{"research","style_bible"})

    def test_multiple_visual_ranges_preserve_unicode_and_nonvisual_text(self):
        body="🙂导演保持。视觉甲。\n声音保留雨声。视觉乙。\n世界禁止穿墙。"
        a=self.save("style","style_bible","project/style",body,[self.ref(self.scene)]);self.approve(a)
        ranges=[{"start":body.index(q),"end":body.index(q)+len(q),"quote":q} for q in ("视觉甲。","视觉乙。")]
        self.prepare(a,a,visual_ranges=ranges)
        out=self.integrate(self.select(),1)
        self.assertEqual(out["artifact"]["content"],body.replace("视觉甲。",self.alt["content"]).replace("视觉乙。",""))

    def test_changed_context_is_stale_before_integrate(self):
        self.prepare();choice=self.select()
        newer=self.save("scene","script","scene/01","同场景已改为晴天。")
        self.approve(newer)
        with self.assertRaises(ConflictError):self.integrate(choice)

    def test_task_may_not_inject_unselected_direction_as_dependency(self):
        self.prepare();choice=self.select()
        self.call("task.create",task_id="task",title="TEST wrong inputs",module="research",scope="project/style",artifact_id="style",inputs=[self.ref(self.scene),self.ref(self.main)],must_keep=[],allowed_changes=[],requirements=[])
        with self.assertRaises(ConflictError):self.integrate(choice,task_id="task")

    def test_test_project_cannot_claim_real_selection(self):
        self.prepare()
        with self.assertRaises(ValueError):self.write("art.select",comparison_id="comparison",choice="main",user_request=self.user,synthetic=False)

    def test_within_baseline_revision_needs_no_new_selection_and_is_candidate(self):
        source=self.selected_style();sid=self.read()["active_selection_id"]
        result=self.revise(source,"湿润石面","微湿石面");a=result["artifact"]
        self.assertEqual(a["content"],source["content"].replace("湿润石面","微湿石面"))
        self.assertEqual(a["status"],"candidate");self.assertEqual(self.read()["active_selection_id"],sid)
        self.assertEqual(self.read()["current_style"],self.ref(source))
        self.assertEqual(result["art_integration"]["semantic_compliance"],"host_judgment_not_program_proof")
        self.approve(a);self.assertEqual(self.read()["current_style"],self.ref(a))

    def test_revision_chain_uses_latest_full_source(self):
        source=self.selected_style();a=self.revise(source,"湿润石面","微湿石面")["artifact"];self.approve(a)
        with self.assertRaises(ConflictError):self.revise(source,working=a)
        b=self.revise(a,"微湿石面","潮湿石面")["artifact"];self.approve(b)
        self.assertEqual(self.read()["revision_source"],self.ref(b))
        self.assertEqual(len(self.read()["selections"]),1)

    def test_cloud_imported_full_working_revision_preserves_original(self):
        source=self.selected_style();body=source["content"].replace("保留雨声。","保留雨声与远处犬吠。")
        working=self.save("style","style_bible","project/style",body,source["deps"])
        with self.assertRaises(ConflictError):self.approve(working)
        out=self.revise(source,"保留雨声。","保留雨声与远处犬吠。",working=working)["artifact"]
        self.assertEqual(out["content"],body);self.assertEqual(out["version"],3)
        self.assertEqual(self.r._artifact("style",1)["content"],source["content"])
        self.assertEqual(self.r._artifact("style",2)["content"],body)
        self.approve(out)

    def test_cloud_unexplained_changes_cannot_be_overwritten(self):
        source=self.selected_style();body=source["content"].replace("保留雨声。","额外云端改写声音。")
        working=self.save("style","style_bible","project/style",body,source["deps"])
        before=self.logical()
        with self.assertRaises(ConflictError):self.revise(source,"湿润石面","微湿石面",working=working)
        self.assertEqual(before,self.logical())

    def test_revision_source_cannot_be_arbitrary_visual_only_candidate(self):
        source=self.selected_style()
        visual=self.save("style","style_bible","project/style",self.main["content"],source["deps"])
        with self.assertRaises(ConflictError):self.revise(visual,"暖金色","浅金色")
        with self.assertRaises(ConflictError):self.revise(source,"湿润石面","浅金色",working=visual)

    def test_revision_guards_exact_quotes_all_replacement_and_stale_baseline(self):
        source=self.selected_style()
        with self.assertRaises(ConflictError):self.revise(source,edits=[{"start":0,"end":2,"quote":"错误","replacement":"对"}])
        with self.assertRaises(ValueError):self.revise(source,edits=[{"start":0,"end":len(source["content"]),"quote":source["content"],"replacement":"新全文"}])
        with self.assertRaises(ConflictError):self.revise(source,baseline=None)
        with self.assertRaises(ValueError):self.revise(source,scope_judgment="new_direction")
        with self.assertRaises(ValueError):self.revise(source,synthetic=False)

    def test_revision_empty_edits_allows_exact_reconciliation(self):
        source=self.selected_style();result=self.revise(source)
        self.assertEqual(result["artifact"]["content"],source["content"])
        self.assertEqual(result["art_integration"]["edits"],[])
        self.approve(result["artifact"])

    def test_revision_task_scope_and_execution_locks_preserved(self):
        source=self.selected_style()
        self.call("task.create",task_id="task",title="TEST local revise",module="research",scope="project/style",artifact_id="style",inputs=source["deps"],must_keep=[],allowed_changes=[],requirements=[])
        with self.assertRaises(ConflictError):self.revise(source,"湿润石面","微湿石面")
        task=self.r._get("tasks","task_id","task");task["execution_lock"]["system_version"]="0.0.0-old";self.r._put("tasks","task_id","task",task);self.r.db.commit()
        with self.assertRaises(ValueError):self.revise(source,"湿润石面","微湿石面",task_id="task")
        self.assertEqual(self.r._artifact("style")["version"],1)

    def test_revision_task_submission_is_supported(self):
        source=self.selected_style()
        self.call("task.create",task_id="task",title="TEST local revise",module="research",scope="project/style",artifact_id="style",inputs=source["deps"],must_keep=[],allowed_changes=[],requirements=[])
        out=self.revise(source,"湿润石面","微湿石面",task_id="task")
        self.assertEqual(out["task"]["status"],"submitted")

    def test_legacy_approved_baseline_revision_needs_no_comparison(self):
        source=self.style();self.approve(source)
        self.assertEqual(self.read()["revision_source_kind"],"legacy_approved")
        result=self.revise(source,"灰白墙","灰白旧墙");a=result["artifact"]
        self.assertTrue(result["art_integration"]["legacy_baseline_inherited"])
        self.assertIsNone(result["art_integration"]["selection_id"])
        self.assertIsNone(result["art_integration"]["comparison_id"])
        self.assertEqual(self.read()["current_style"],self.ref(source));self.assertEqual(self.read()["selections"],[])
        self.approve(a)
        b=self.revise(a,"灰白旧墙","灰白墙面")["artifact"];self.approve(b)
        self.assertEqual(self.read()["revision_source"],self.ref(b));self.assertEqual(self.read()["comparisons"],[])

    def test_legacy_cloud_working_can_be_exactly_inherited(self):
        source=self.style();self.approve(source)
        body=source["content"].replace("雨声不中断","雨声保持连续")
        working=self.save("style","style_bible","project/style",body,source["deps"])
        out=self.revise(source,"雨声不中断","雨声保持连续",working=working)["artifact"]
        self.assertEqual(out["content"],body);self.approve(out)

    def test_legacy_revision_cannot_start_from_unapproved_or_bypass_selection(self):
        source=self.style()
        with self.assertRaises(ConflictError):self.revise(source,"灰白墙","灰墙")
        self.approve(source);self.prepare(source,source);self.select()
        with self.assertRaises(ConflictError):self.revise(source,"灰白墙","灰墙",selection_id=None)

    def test_legacy_managed_revision_blocks_raw_full_overwrite_approval(self):
        source=self.style();self.approve(source)
        self.revise(source,"灰白墙","灰白旧墙")
        bad=self.save("style","style_bible","project/style",self.main["content"],source["deps"])
        with self.assertRaises(ConflictError):self.approve(bad)

    def test_revision_summary_omits_exact_quote_and_replacement(self):
        source=self.selected_style();self.revise(source,"湿润石面","秘密测试替换词")
        self.assertNotIn("秘密测试替换词",json.dumps(self.read(),ensure_ascii=False))
        full=self.read(comparison_id="comparison",include_content=True)
        self.assertEqual(full["integrations"][-1]["edits"][0]["replacement"],"秘密测试替换词")


if __name__ == "__main__":unittest.main()

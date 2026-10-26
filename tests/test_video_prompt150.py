"""AI video prompt boundaries using only isolated synthetic TEST projects."""
import tempfile
import unittest
import uuid
from pathlib import Path

from filmprod.core import ConflictError, Registry
from filmprod.export import export_project
from filmprod.pages_bridge import import_observation


class VideoPrompt150Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="TEST_ONLY_VIDEO_PROMPT_150_")
        self.root = Path(self.tmp.name) / "project"
        self.r = Registry(self.root)
        self.call("project.init", project_id="TEST-VIDEO-PROMPT-150", title="合成视频提示词测试", test_only=True)

    def tearDown(self):
        self.r.close()
        self.tmp.cleanup()

    def call(self, action, **payload):
        payload.setdefault("op_id", uuid.uuid4().hex)
        return self.r.dispatch(action, payload)

    @staticmethod
    def ref(aid, version=1):
        return {"artifact_id": aid, "version": version}

    def save(self, aid, kind="video_prompt", scope="episode/1/scene/1/shot/1", base=0, deps=None, metadata=None, content=None):
        return self.call("artifact.save", artifact_id=aid, kind=kind, scope=scope, base_version=base,
                         deps=deps or [], metadata=metadata or {}, content=content if content is not None else f"TEST {aid} 第{base + 1}版正文")["artifact"]

    def approve(self, aid, version=1):
        a = self.r.dispatch("artifact.get", self.ref(aid, version))
        return self.call("content.approve", **self.ref(aid, version), scope=a["scope"], evidence="synthetic TEST only", actor="test-runner", synthetic=True)

    def style(self, base=0):
        return self.save("STYLE", "style_bible", "project/style", base=base)

    def task(self, tid, module="video_prompt", inputs=None, scope=None):
        return self.call("task.create", task_id=tid, title="TEST 提示词任务", module=module, scope=scope or tid,
                         inputs=inputs or [], must_keep=[], allowed_changes=[], requirements=[])

    def choose(self, mode, revision=0):
        return self.call("project.workflow.set", expected_project_id="TEST-VIDEO-PROMPT-150", base_revision=revision, mode=mode)

    def stage(self):
        return next(x for x in self.r.snapshot()["workflow"]["stages"] if x["key"] == "video_prompt")

    def test_asset_and_video_same_scope_have_separate_history_and_approval(self):
        self.save("ASSET", "asset"); self.approve("ASSET")
        self.save("VIDEO", content="TEST 视频纯正文"); self.approve("VIDEO")
        asset_history = self.r.dispatch("master.history", {"category": "asset"})
        self.save("VIDEO", base=1, content="TEST 视频候选第二版")
        snap = self.r.snapshot()
        self.assertEqual({a["artifact_id"]: a["version"] for a in snap["current_content"]}, {"ASSET": 1, "VIDEO": 1})
        self.assertEqual([a["artifact_id"] for a in snap["pending_candidates"]], ["VIDEO"])
        self.approve("VIDEO", 2)
        self.assertEqual(self.r.dispatch("master.history", {"category": "asset"}), asset_history)
        history = self.r.dispatch("master.history", {"category": "video_prompt"})["versions"]
        self.assertEqual([v["version"] for v in history], [1, 2])
        self.assertEqual([s["artifact_id"] for s in history[-1]["segments"]], ["VIDEO"])
        restored = self.call("artifact.restore", artifact_id="VIDEO", version=1, base_version=2)["artifact"]
        self.assertEqual((restored["version"], restored["content"]), (3, "TEST 视频纯正文"))
        self.assertEqual(self.r.dispatch("master.history", {"category": "video_prompt"})["versions"], history)

    def test_legacy_prompt_stays_asset_and_category_relabel_is_rejected(self):
        self.save("LEGACY", "prompt"); self.approve("LEGACY")
        old = self.r.dispatch("artifact.history", {"artifact_id": "LEGACY"})
        self.save("VIDEO")
        with self.assertRaises(ValueError):
            self.save("BAD-OLD", "prompt", scope="another", metadata={"category": "video_prompt"})
        with self.assertRaises(ValueError):
            self.save("BAD-NEW", scope="another", metadata={"category": "asset"})
        self.assertEqual(self.r.dispatch("artifact.history", {"artifact_id": "LEGACY"}), old)
        item = next(a for a in self.r.snapshot()["current_content"] if a["artifact_id"] == "LEGACY")
        self.assertEqual(item["category"], "asset")
        self.assertEqual(self.r.dispatch("master.history", {"category": "video_prompt"})["versions"], [])

    def test_routes_and_asset_suggestions_distinguish_exact_statuses(self):
        for revision, mode in enumerate(("novel_to_screen", "screenplay", "novel_only")):
            self.choose(mode, revision)
            flow = self.r.snapshot()["workflow"]
            keys = [s["key"] for s in flow["stages"]]
            if mode == "novel_only":
                self.assertNotIn("video_prompt", keys + [s["key"] for s in flow["optional_stages"]])
            else:
                self.assertEqual(keys[-2:], ["asset", "video_prompt"])
                self.assertNotIn("asset", [d["stage_key"] for d in self.stage()["dependency_suggestions"]])
        self.choose("screenplay", 3)
        self.save("ASSET", "asset")
        asset = next(d for d in self.stage()["dependency_suggestions"] if d["stage_key"] == "asset")
        self.assertTrue(asset["optional"])
        self.assertEqual((asset["status"], asset["refs"], asset["candidate_refs"]), ("candidate", [], [self.ref("ASSET")]))
        self.approve("ASSET")
        self.save("ASSET", "asset", base=1)
        asset = next(d for d in self.stage()["dependency_suggestions"] if d["stage_key"] == "asset")
        self.assertEqual(asset["refs"], [self.ref("ASSET")])
        self.assertEqual(asset["candidate_refs"], [self.ref("ASSET", 2)])
        self.assertEqual({d["stage_key"] for d in self.stage()["dependency_suggestions"]},
                         {"dynamic_script", "director", "vfx", "character_bio", "style", "asset"})
        task = self.task("NO-ASSET-REFERENCE")
        self.assertEqual(task["inputs"], [])
        self.assertEqual(task["missing_context"], ["global_style"])

    def test_task_resume_and_submit_freeze_style_for_both_modules(self):
        self.style(); self.approve("STYLE"); self.style(base=1)
        for module in ("video_prompt", "seedance-prompt"):
            task = self.task(module, module)
            self.assertEqual(task["inputs"], [self.ref("STYLE")])
            self.call("task.checkpoint", task_id=module, draft="TEST 未完成视频提示词", completed=["动作"], decisions=[], unresolved=["目标平台未知"], next_step="补充镜头")
            resumed = self.r.dispatch("task.resume", {"task_id": module})
            self.assertEqual(resumed["checkpoint"]["draft"], "TEST 未完成视频提示词")
            self.assertEqual(resumed["frozen_inputs"][0]["version"], 1)
            body = "TEST 镜头从门外推进。\n人物转身，衣摆随动作落下。\n"
            metadata = {"workflow_stage": "video_prompt", "target_platform": None, "target_model": None,
                        "generation_unit": "shot", "episode": "第一集", "scene": "第一场", "shot": "镜头1"}
            result = self.call("task.submit", task_id=module, artifact_id=module, kind="video_prompt", content=body, base_version=0, metadata=metadata)
            self.assertEqual(result["artifact"]["content"], body)
            self.assertEqual(result["artifact"]["deps"], [self.ref("STYLE")])
            self.assertIsNone(result["artifact"]["metadata"]["target_model"])
            self.assertEqual(result["artifact"]["metadata"]["style_context"]["semantic_compliance"], "not_assessed")
        capabilities = self.r.snapshot()["capabilities"]["module_output_kinds"]
        self.assertEqual(capabilities["video_prompt"], ["video_prompt"])
        self.assertIn("video_prompt", capabilities["seedance-prompt"])
        with self.assertRaises(ConflictError):
            self.task("WRONG-STYLE", inputs=[self.ref("STYLE", 2)])

    def test_approved_style_and_declared_asset_changes_require_review_only_after_approval(self):
        self.choose("screenplay")
        self.style(); self.approve("STYLE")
        self.save("ASSET", "asset", deps=[self.ref("STYLE")]); self.approve("ASSET")
        self.task("BUILD", inputs=[self.ref("ASSET")])
        self.call("task.submit", task_id="BUILD", artifact_id="VIDEO", kind="video_prompt", content="TEST 视频", base_version=0)
        self.approve("VIDEO")
        self.task("OPEN", inputs=[self.ref("VIDEO")])
        self.style(base=1); self.save("ASSET", "asset", base=1, deps=[self.ref("STYLE")])
        self.assertEqual(self.stage()["status"], "approved")
        self.assertEqual(self.r.dispatch("task.resume", {"task_id": "OPEN"})["stale_inputs"], [])
        self.approve("ASSET", 2)
        self.assertEqual(self.stage()["status"], "needs_review")
        self.assertEqual(self.r.dispatch("task.resume", {"task_id": "OPEN"})["task"]["status"], "needs_review")
        self.assertEqual(self.r.dispatch("artifact.get", self.ref("VIDEO"))["deps"], [self.ref("ASSET"), self.ref("STYLE")])
        self.task("STYLE-ONLY")
        self.call("task.submit", task_id="STYLE-ONLY", artifact_id="VIDEO2", kind="video_prompt", content="TEST 仅绑定风格", base_version=0)
        self.approve("VIDEO2")
        self.approve("STYLE", 2)
        self.assertEqual(self.r.dispatch("artifact.get", self.ref("VIDEO2"))["status"], "needs_review")
        suggestions = {d["stage_key"]: d for d in self.stage()["dependency_suggestions"]}
        self.assertEqual(suggestions["asset"]["refs"], [])
        self.assertEqual(suggestions["asset"]["review_refs"], [self.ref("ASSET", 2)])
        self.assertEqual(suggestions["style"]["refs"], [self.ref("STYLE", 2)])

    def test_video_metadata_and_body_are_separate_and_unknown_not_filled(self):
        item = self.save("VIDEO", content="TEST 纯视频提示词")
        self.assertEqual(item["content"], "TEST 纯视频提示词")
        self.assertNotIn("target_model", item["metadata"])
        self.assertEqual(item["metadata"]["style_context"]["status"], "missing")
        with self.assertRaises(ValueError):
            self.save("BAD-BODY", scope="bad", content={"prompt": "结构不是纯正文"})
        with self.assertRaises(ValueError):
            self.save("BAD-MODEL", scope="bad", metadata={"target_model": ["猜测模型"]})
        with self.assertRaises(ValueError):
            self.save("BAD-STAGE", scope="bad", metadata={"workflow_stage": "asset"})
        with self.assertRaises(ConflictError):
            self.save("DUPLICATE", content="重复分类范围")

    def test_pages_video_working_draft_never_becomes_an_approved_prompt(self):
        self.save("VIDEO", content="TEST 正式分段"); self.approve("VIDEO")
        before = self.r.dispatch("master.history", {"category": "video_prompt"})
        observation = {"category": "video_prompt", "view": "full", "observed_at": "2026-10-24T12:00:00+00:00",
                       "content": {"page_id": "TEST-VIDEO-PAGE", "through_sequence": 1,
                                   "blocks": [{"id": "block-1", "hash": "test-hash", "kind": "markdown", "markdown": "TEST 云端视频工作稿"}]}}
        imported = import_observation(self.r, observation, "test-cloud")
        item = imported["result"]["artifact"]
        self.assertEqual(item["kind"], "cloud_working_draft")
        self.assertEqual(item["metadata"]["category"], "video_prompt")
        self.assertFalse(imported["approval_changed"])
        self.assertEqual(self.r.dispatch("master.history", {"category": "video_prompt"}), before)
        self.assertFalse(any(a["artifact_id"] == item["artifact_id"] for a in self.r.snapshot()["pending_candidates"]))
        with self.assertRaises(ValueError):
            self.approve(item["artifact_id"])
        exported = export_project(self.r)
        self.assertEqual([x["artifact_id"] for x in exported["video_prompt_texts"]], ["VIDEO"])

    def test_pure_text_exports_exact_revisions_with_status_only_in_index(self):
        body = "TEST 镜头主体向前两步。\r\n镜头后退，光影连续。\n"
        self.style(); self.approve("STYLE")
        self.save("ASSET", "asset", content="TEST 资产提示词")
        self.save("VIDEO", content=body, deps=[self.ref("STYLE")], metadata={"target_platform": "TEST 平台", "shot": {"id": "1", "title": "镜头一"}})
        self.approve("VIDEO")
        self.save("VIDEO", base=1, content="TEST 第二版", deps=[self.ref("STYLE")]); self.approve("VIDEO", 2)
        self.save("VIDEO", base=2, content="TEST 待审第三版", deps=[self.ref("STYLE")])
        self.save("OTHER", scope="shot/2", content="TEST 未确认生成单元")
        result = export_project(self.r)
        exports = {(e["artifact_id"], e["version"]): e for e in result["video_prompt_texts"]}
        self.assertEqual(len(exports), 4)
        self.assertEqual(Path(exports[("VIDEO", 1)]["path"]).read_bytes(), body.encode("utf-8"))
        self.assertEqual(exports[("VIDEO", 1)]["status"], "historical_approved")
        self.assertEqual(exports[("VIDEO", 2)]["status"], "current_approved")
        self.assertEqual(exports[("VIDEO", 3)]["status"], "candidate")
        self.assertEqual(exports[("OTHER", 1)]["status"], "candidate")
        entry = Path(result["entry"]).read_text(encoding="utf-8")
        self.assertIn("AI 视频提示词", entry)
        self.assertIn("历史已通过 · 非当前版", entry)
        self.assertIn("当前已通过", entry)
        self.assertIn("待审核候选", entry)
        self.assertEqual(list((self.root/"已通过总稿").rglob("*.txt")), [])
        self.assertTrue(list((self.root/"已通过总稿").rglob("*.md")))
        export_project(self.r)
        target = Path(exports[("VIDEO", 2)]["path"])
        target.write_text("TEST 外部修改", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "纯提示词副本已被外部修改"):
            export_project(self.r)
        self.assertEqual(target.read_text(encoding="utf-8"), "TEST 外部修改")


if __name__ == "__main__":
    unittest.main()

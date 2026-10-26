"""Isolated merge boundaries: screenwriter feedback and art remain independent."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

from filmprod.core import Registry
from filmprod.modules import resolve
from filmprod.workflow_tools1110 import action_schemas, READ_ACTIONS


class MergeBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="film-merge1140-TEST-")
        self.root = Path(self.temp.name) / "TEST-only"
        self.r = Registry(self.root)
        self.call("project.init", project_id="TEST-MERGED", title="TEST merged", test_only=True)

    def tearDown(self):
        self.r.close()
        self.temp.cleanup()

    def call(self, action, **payload):
        payload.setdefault("op_id", uuid.uuid4().hex)
        if action != "project.init":
            payload.setdefault("expected_project_id", "TEST-MERGED")
        return self.r.dispatch(action, payload)

    def ref(self, artifact):
        return {k: artifact[k] for k in ("artifact_id", "version", "sha256")}

    def save(self, aid, kind, scope, content, deps=None):
        prior = self.r._artifact(aid)
        return self.call("artifact.save", artifact_id=aid, kind=kind, scope=scope, content=content,
                         base_version=prior["version"] if prior else 0, deps=deps or []) ["artifact"]

    def approve(self, a):
        return self.call("content.approve", artifact_id=a["artifact_id"], version=a["version"], scope=a["scope"],
                         evidence="TEST synthetic adoption", actor="test", synthetic=True)

    def test_both_action_families_and_readonly_identity_survive(self):
        schemas = action_schemas()
        self.assertEqual({a for a in schemas if a.startswith("art.")},
                         {"art.read", "art.prepare", "art.select", "art.integrate", "art.revise"})
        self.assertEqual({a for a in schemas if a.startswith("screenwriting.")},
                         {"screenwriting.read", "screenwriting.record", "screenwriting.resolve"})
        self.assertIn("screenwriting.read", READ_ACTIONS)
        self.assertIn("art.read", READ_ACTIONS)
        state = self.r.snapshot()
        self.assertTrue({"art", "screenwriting", "cloud", "workspace", "delivery"} <= state.keys())
        self.assertIn("screenwriter", state["capabilities"]["module_output_kinds"])
        self.assertIn("art_director", state["capabilities"]["module_output_kinds"])
        self.assertEqual(state["workflow"]["mode"], "unset")

    def test_unified_writer_does_not_replace_art_or_research_routes(self):
        self.assertEqual(resolve("style")["module"]["id"], "film-art-director")
        self.assertEqual(resolve("style")["task_module"], "art_director")
        self.assertEqual(resolve("research")["module"]["id"], "film-analysis")
        for role, mode in (("novel", "novel"), ("adaptation", "adaptation"), ("original-screenplay", "original")):
            result = resolve(role)
            self.assertEqual(result["module"]["id"], "screenwriter")
            self.assertEqual(result["screenwriting_mode"], mode)

    def test_full_route_keeps_eight_stable_role_slots(self):
        self.call("project.workflow.set", mode="novel_to_screen", base_revision=0)
        result = self.call("workspace.prepare", base_revision=0)
        self.assertEqual(len(result["slots"]), 8)
        roles = {slot["role"] for slot in result["slots"]}
        self.assertEqual(roles, {"control", "planning", "novel", "script", "art", "director", "assets", "review"})
        again = self.call("workspace.prepare", base_revision=result["revision"])
        self.assertEqual([s["slot_id"] for s in result["slots"]], [s["slot_id"] for s in again["slots"]])

    def test_cli_feedback_and_art_reads_open_readonly(self):
        self.r.close()
        raw = (self.root / ".project/registry.sqlite3").read_bytes()
        source = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("film_cli_merge_test", source / "film.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        for action in ("screenwriting.read", "art.read"):
            output = io.StringIO()
            with patch.object(sys, "argv", ["film.py", "--root", str(self.root), "dispatch", action, "--file", "-"]), \
                 patch.object(sys, "stdin", io.StringIO(json.dumps({"expected_project_id": "TEST-MERGED"}))), \
                 patch.object(Registry, "__init__", side_effect=AssertionError("read opened writable registry")), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(), 0)
            self.assertEqual(json.loads(output.getvalue())["project_id"], "TEST-MERGED")
        self.assertEqual(raw, (self.root / ".project/registry.sqlite3").read_bytes())
        self.r = Registry(self.root)

    def test_script_feedback_candidate_does_not_change_adopted_art_then_approval_marks_review(self):
        script = self.save("script", "script", "scene/01", "S01 门口\n甲：请进。")
        self.approve(script)
        main = self.save("main", "research", "art/main", "视觉主选：暖灰木门。", [self.ref(script)])
        alt = self.save("alt", "research", "art/alt", "视觉备选：冷青石门。", [self.ref(script)])
        self.call("art.prepare", base_revision=0, comparison_id="COMPARE", title="TEST 两套视觉", target_artifact_id="style",
                  baseline=None, working_ref=None, main=self.ref(main), alternate=self.ref(alt), context=[self.ref(script)],
                  visual_ranges=[], nonvisual_sections={"direction":"固定镜头。", "performance":"自然对话。", "sound":"保留风声。", "world_rules":"不能穿墙。"})
        selected = self.call("art.select", base_revision=1, comparison_id="COMPARE", choice="alternate", synthetic=True,
                             user_request={"source":"conversation", "reference":"TEST-selection", "quote":"选择备选，先保存完整候选。"})
        style = self.call("art.integrate", base_revision=2, selection_id=selected["selection"]["selection_id"], base_version=0)["artifact"]
        self.approve(style)
        self.call("screenwriting.record", base_revision=0, feedback_id="F1", script=self.ref(script), scope="scene/01", scene_id="S01",
                  anchor="甲：请进。", problem="邀请动作不清楚。", expected_effect="明确让出门口。", must_keep=["人物关系不变"],
                  impact="expression", source={"role":"director", "reference":"TEST-feedback"})
        revised = self.save("script", "script", "scene/01", "S01 门口\n甲侧身让开门口。\n甲：请进。")
        self.call("screenwriting.resolve", base_revision=1, feedback_id="F1", status="addressed", response="明确让位动作。", revised_script=self.ref(revised))
        state = self.r.snapshot()
        self.assertEqual(state["art"]["current_style"], self.ref(style))
        self.assertEqual(state["art"]["current_style_status"], "approved")
        self.assertEqual(state["cloud"]["jobs"], [])
        self.approve(revised)
        updated = self.r.snapshot()
        self.assertEqual(updated["art"]["current_style"], self.ref(style))
        self.assertEqual(updated["art"]["current_style_status"], "needs_review")
        self.assertEqual(self.r._artifact("style")["version"], 1)


if __name__ == "__main__":
    unittest.main()

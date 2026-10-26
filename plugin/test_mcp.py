"""Real subprocess MCP protocol tests against an isolated original test project."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

class MCPTest(unittest.TestCase):
    def test_video_prompt150_real_stdio_preserves_text_metadata_and_independent_master(self):
        with tempfile.TemporaryDirectory(prefix="film-mcp-video150-TEST-") as temp:
            root = str(Path(temp) / "TEST_PROJECT")
            requests, labels = [], {}
            def call(label, name, **arguments):
                labels[label] = len(requests)
                requests.append({"jsonrpc":"2.0", "id":len(requests)+1, "method":"tools/call",
                                 "params":{"name":name,"arguments":{"root":root,**arguments}}})
            def dispatch(label, action, **payload):
                identity={} if action=="project.init" else {"expected_project_id":"TEST-VIDEO150"}
                call(label,"film_dispatch",action=action,payload={"op_id":label,**identity,**payload})
            dispatch("init","project.init",project_id="TEST-VIDEO150",title="TEST video prompt protocol",test_only=True)
            dispatch("route","project.workflow.set",base_revision=0,mode="screenplay")
            for aid,kind,scope,content in (("STYLE","style_bible","project/style","TEST 已确认暖灰质感"),("SCRIPT","script","S01","灯亮。阿禾说：回家吧。"),("LEGACY","prompt","S01/G01","TEST 资产旧提示词")):
                dispatch("save-"+aid,"artifact.save",artifact_id=aid,kind=kind,scope=scope,content=content,base_version=0,deps=[],metadata={"workflow_stage":"dynamic_script"} if kind=="script" else {})
                dispatch("approve-"+aid,"content.approve",artifact_id=aid,version=1,scope=scope,evidence="synthetic MCP regression",actor="test",synthetic=True)
            dispatch("task","task.create",task_id="VIDEO-TASK",title="TEST complete video prompt",module="video_prompt",scope="S01/G01",inputs=[{"artifact_id":"SCRIPT","version":1}],must_keep=["保留原对白"],allowed_changes=["补足非关键拍法"],requirements=["纯三段式完整正文"])
            call("resume","film_resume",task_id="VIDEO-TASK")
            body="【风格总控】\n暖灰自然光，克制表演。\n\n【场景与角色锚定】\n阿禾站在屋门旁，手放门把。\n\n【分镜】\n镜1｜中景固定，灯亮，阿禾看向屋内说：\"回家吧。\"\n镜2｜切近景固定，阿禾松开门把，留出通路。"
            metadata={"workflow_stage":"video_prompt","target_platform":None,"target_model":None,"generation_unit":"G01","shot":None,"episode":"E01","scene":"S01"}
            dispatch("submit","task.submit",task_id="VIDEO-TASK",artifact_id="VIDEO",kind="video_prompt",content=body,base_version=0,metadata=metadata)
            call("candidate","film_snapshot")
            dispatch("approve-video","content.approve",artifact_id="VIDEO",version=1,scope="S01/G01",evidence="synthetic MCP regression",actor="test",synthetic=True)
            call("approved","film_snapshot")
            call("history","film_history",artifact_id="VIDEO")
            dispatch("novel-route","project.workflow.set",base_revision=1,mode="novel_only")
            call("novel-only","film_snapshot")
            process=subprocess.run([sys.executable,"-X","utf8",str(Path(__file__).with_name("mcp_server.py"))],input="\n".join(json.dumps(r,ensure_ascii=False) for r in requests)+"\n",capture_output=True,encoding="utf-8",timeout=25,env={**os.environ,"FILMPROD_CATALOG_PATH":str(Path(temp)/"catalog.sqlite3"),"PYTHONDONTWRITEBYTECODE":"1"})
            self.assertEqual(process.returncode,0,process.stderr)
            responses=[json.loads(line) for line in process.stdout.splitlines()]
            self.assertEqual(len(responses),len(requests))
            for row in responses:
                self.assertFalse(row.get("error") or row.get("result",{}).get("isError"),row)
            def result(label):return responses[labels[label]]["result"]["structuredContent"]
            self.assertIn({"artifact_id":"STYLE","version":1},result("resume")["task"]["inputs"])
            before=result("candidate")
            self.assertNotIn("video_prompt",{m["category"] for m in before["masters"]})
            self.assertEqual(before["workflow"]["stages"][-1]["key"],"video_prompt")
            after=result("approved")
            self.assertTrue({"asset","video_prompt"}<={m["category"] for m in after["masters"]})
            video=next(a for a in after["approved_artifacts"] if a["artifact_id"]=="VIDEO")
            legacy=next(a for a in after["approved_artifacts"] if a["artifact_id"]=="LEGACY")
            self.assertEqual(video["category"],"video_prompt")
            self.assertEqual(legacy["category"],"asset")
            self.assertEqual(video["content"],body)
            self.assertEqual(result("history")["versions"][0]["content"],body)
            for key,value in metadata.items():self.assertEqual(video["metadata"][key],value)
            self.assertIn("video_prompt",after["capabilities"]["module_output_kinds"]["seedance-prompt"])
            self.assertNotIn("video_prompt",{row["key"] for row in result("novel-only")["workflow"]["stages"]})

    def test_video_prompt_pages_observation_is_preserved_without_approval(self):
        import importlib.util
        from unittest.mock import patch
        spec=importlib.util.spec_from_file_location("film_mcp_video_pages150",Path(__file__).with_name("mcp_server.py"))
        server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)
        with tempfile.TemporaryDirectory(prefix="film-mcp-video-pages150-TEST-") as temp,patch.dict(os.environ,{"FILMPROD_CATALOG_PATH":str(Path(temp)/"catalog.sqlite3")}):
            root=str(Path(temp)/"TEST_PROJECT")
            def call(name,**args):return server.call_tool(name,{"root":root,**args},None)["structuredContent"]
            call("film_dispatch",action="project.init",payload={"op_id":"init","project_id":"TEST-VIDEO-PAGES","title":"TEST video pages","test_only":True})
            body="【风格总控】\nTEST 文字版\n【场景与角色锚定】\n门前\n【分镜】\n镜1｜固定中景。"
            observation={"category":"video_prompt","view":"full","observed_at":"2026-10-24T01:00:00+08:00","selection":{"whole_page_complete":True},"metadata":{"current_sequence":7},"content":{"page_id":"test-video-page","through_sequence":7,"blocks":[{"id":"video-block","kind":"markdown","hash":"synthetic-only","markdown":body}]}}
            imported=call("film_pages_import",observation=observation,op_prefix="observe-video")
            self.assertEqual(imported["category"],"video_prompt")
            self.assertFalse(imported["approval_changed"])
            snapshot=call("film_snapshot")
            draft=next(a for a in snapshot["artifacts"] if a["kind"]=="cloud_working_draft")
            self.assertEqual(draft["content"],body)
            self.assertEqual(draft["metadata"]["cloud_revision"],7)
            self.assertEqual(draft["metadata"]["category"],"video_prompt")
            self.assertFalse(snapshot["masters"])
            self.assertFalse(call("film_pages_import",observation=observation,op_prefix="observe-video")["changed"])
            with self.assertRaises(ValueError):
                call("film_pages_import",observation={**observation,"truncated":True},op_prefix="partial-video")

    def test_brainstorm_static_schema_is_readonly_and_does_not_touch_a_project(self):
        import importlib.util
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location("film_mcp_brainstorm_static140", Path(__file__).with_name("mcp_server.py"))
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        definition = next(t for t in server.TOOLS if t["name"] == "film_brainstorm")
        self.assertTrue(definition["annotations"]["readOnlyHint"])
        self.assertFalse(definition["annotations"]["destructiveHint"])
        self.assertEqual(len(server.TOOLS), 25)
        with tempfile.TemporaryDirectory(prefix="film-brainstorm-static-TEST-") as temp:
            absent = Path(temp)/"DO_NOT_CREATE"
            with patch("filmprod.core.Registry", side_effect=AssertionError("static interface must not open Registry")):
                result = server.call_tool("film_brainstorm", {"action":"interface"}, str(absent))["structuredContent"]
                alias = server.call_tool("film_dispatch", {"root":str(absent),"action":"brainstorm.interface","payload":{}}, None)["structuredContent"]
            self.assertEqual(result, alias)
            self.assertEqual(result["skill_name"], "film-brainstorm-interface")
            self.assertEqual(result["provider_status"], "not_connected")
            self.assertFalse(result["can_generate"])
            self.assertIn("base_ref", result["input_schema"]["properties"])
            self.assertFalse(absent.exists())
            with self.assertRaises(ValueError):
                server.call_tool("film_brainstorm", {"action":"generate"}, None)

    def test_brainstorm_prepare_exact_context_and_identity_do_not_write(self):
        import hashlib
        import importlib.util
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location("film_mcp_brainstorm_prepare140", Path(__file__).with_name("mcp_server.py"))
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        with tempfile.TemporaryDirectory(prefix="film-brainstorm-prepare-TEST-") as temp, patch.dict(os.environ,{"FILMPROD_CATALOG_PATH":str(Path(temp)/"catalog.sqlite3")}):
            root=Path(temp)/"PROJECT"
            server.call_tool("film_projects",{"action":"create","payload":{"op_id":"create","project_id":"TEST-BRAINSTORM","title":"TEST only","root":str(root),"test_only":True}},None)
            server.call_tool("film_dispatch",{"root":str(root),"action":"artifact.save","payload":{"op_id":"save","artifact_id":"N","kind":"novel","scope":"chapter/1","content":"TEST 正文","base_version":0,"deps":[]}},None)
            database=root/".project/registry.sqlite3"
            before=hashlib.sha256(database.read_bytes()).hexdigest()
            request={"expected_project_id":"TEST-BRAINSTORM","topic":"TEST 问题","context_refs":[{"artifact_id":"N","version":1}]}
            with self.assertRaises(ValueError):
                server.call_tool("film_brainstorm",{"root":str(root),"action":"prepare","payload":request},None)
            selected={**request,"base_ref":{"artifact_id":"N","version":1},"allow_candidate_context":True}
            result=server.call_tool("film_brainstorm",{"root":str(root),"action":"prepare","payload":selected},None)["structuredContent"]
            alias=server.call_tool("film_dispatch",{"root":str(root),"action":"brainstorm.prepare","payload":selected},None)["structuredContent"]
            self.assertEqual(result,alias)
            self.assertEqual(result["contexts"][0]["content"],"TEST 正文")
            self.assertEqual(result["contexts"][0]["context_status"],"candidate")
            self.assertIsNone(result["candidate_output"])
            self.assertFalse(result["generation_performed"])
            self.assertEqual(before,hashlib.sha256(database.read_bytes()).hexdigest())
            with patch("filmprod.brainstorm.prepare",side_effect=AssertionError("identity guard must run first")):
                for payload in ({"topic":"TEST"},{**selected,"expected_project_id":"OTHER"}):
                    with self.assertRaises(ValueError):
                        server.call_tool("film_brainstorm",{"root":str(root),"action":"prepare","payload":payload},None)
            import sqlite3
            catalog=sqlite3.connect(Path(temp)/"catalog.sqlite3")
            try:
                catalog.execute("UPDATE projects SET project_id='OTHER' WHERE project_id='TEST-BRAINSTORM'")
                catalog.commit()
            finally:
                catalog.close()
            with patch("filmprod.brainstorm.prepare",side_effect=AssertionError("catalog guard must run first")),self.assertRaisesRegex(ValueError,"registered root"):
                server.call_tool("film_brainstorm",{"root":str(root),"action":"prepare","payload":selected},None)

    def test_brainstorm_compatibility_action_cannot_migrate_schema1(self):
        import hashlib
        import importlib.util
        import sqlite3
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location("film_mcp_brainstorm_legacy140", Path(__file__).with_name("mcp_server.py"))
        server=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        with tempfile.TemporaryDirectory(prefix="film-brainstorm-legacy-TEST-") as temp,patch.dict(os.environ,{"FILMPROD_CATALOG_PATH":str(Path(temp)/"NO_CATALOG.sqlite3")}):
            root=Path(temp)/"LEGACY";project=root/".project";project.mkdir(parents=True)
            database=project/"registry.sqlite3"
            db=sqlite3.connect(database)
            try:
                db.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
                db.execute("INSERT INTO settings VALUES('schema_version','1')")
                db.execute("INSERT INTO settings VALUES('project',?)",(json.dumps({"project_id":"LEGACY","title":"TEST legacy","test_only":True}),))
                db.commit()
            finally:
                db.close()
            before=hashlib.sha256(database.read_bytes()).hexdigest()
            for name,action in (("film_brainstorm","prepare"),("film_dispatch","brainstorm.prepare")):
                with self.assertRaises(ValueError):
                    server.call_tool(name,{"root":str(root),"action":action,"payload":{"expected_project_id":"LEGACY","topic":"TEST"}},None)
            self.assertEqual(before,hashlib.sha256(database.read_bytes()).hexdigest())
            self.assertEqual([p.name for p in project.iterdir()],["registry.sqlite3"])
            self.assertFalse((Path(temp)/"NO_CATALOG.sqlite3").exists())

    def test_workflow_routes_separate_masters_and_confirmed_style_survive_mcp(self):
        import importlib.util
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location("film_mcp_workflow130_test", Path(__file__).with_name("mcp_server.py"))
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        with tempfile.TemporaryDirectory(prefix="film-mcp-workflow130-TEST-") as temp, patch.dict(os.environ, {"FILMPROD_CATALOG_PATH":str(Path(temp)/"catalog.sqlite3")}):
            root = str(Path(temp)/"project")
            def call(name, **args):
                return server.call_tool(name, {"root": root, **args}, None)["structuredContent"]
            def dispatch(action, payload):
                return call("film_dispatch", action=action, payload=payload)
            dispatch("project.init", {"op_id":"init130", "project_id":"MCP-WORKFLOW-TEST", "title":"Workflow protocol TEST", "test_only":True})
            initial=call("film_snapshot")
            self.assertEqual(initial["workflow"]["mode"], "unset")
            self.assertEqual(initial["global_style"]["status"], "missing")
            route={"op_id":"route130", "expected_project_id":"MCP-WORKFLOW-TEST", "base_revision":0, "mode":"screenplay", "outline_order":"after_novel"}
            first=dispatch("project.workflow.set",route)
            self.assertEqual(dispatch("project.workflow.set",route),first)
            self.assertEqual(call("film_snapshot")["workflow"]["mode"],"screenplay")
            from filmprod.core import ConflictError
            with self.assertRaises(ConflictError):
                dispatch("project.workflow.set",{**route,"op_id":"stale130","mode":"novel_only"})
            rows=[("SOURCE","source_script","S01",{}),("DYNAMIC","script","S01",{"workflow_stage":"dynamic_script"}),("BIO","character_bio","人物/阿禾",{}),("STYLE","style_bible","project/style",{})]
            for artifact_id,kind,scope,metadata in rows:
                dispatch("artifact.save",{"op_id":"save-"+artifact_id,"artifact_id":artifact_id,"kind":kind,"scope":scope,"content":"TEST 完整候选 "+artifact_id,"base_version":0,"deps":[],"metadata":metadata})
                dispatch("content.approve",{"op_id":"approve-"+artifact_id,"artifact_id":artifact_id,"version":1,"scope":scope,"evidence":"synthetic protocol check","actor":"test","synthetic":True})
            snapshot=call("film_snapshot")
            categories={row["category"] for row in snapshot["masters"]}
            self.assertTrue({"source_script","script","character_bio","style"}<=categories)
            self.assertEqual(snapshot["global_style"]["approved_ref"],{"artifact_id":"STYLE","version":1})
            self.assertEqual(snapshot["workflow"]["global_style"],snapshot["global_style"])
            dispatch("task.create",{"op_id":"director-task","task_id":"DIRECT","title":"TEST style-bound director","module":"director","scope":"S01","inputs":[{"artifact_id":"DYNAMIC","version":1}],"must_keep":[],"allowed_changes":[],"requirements":[]})
            resumed=call("film_resume",task_id="DIRECT")
            self.assertIn({"artifact_id":"STYLE","version":1},resumed["task"]["inputs"])
            self.assertEqual(call("film_health")["version"],"1.15.0")

    def test_expected_identity_and_catalog_identity_are_checked_before_registry_open(self):
        import importlib.util
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location("film_mcp_identity_test", Path(__file__).with_name("mcp_server.py"))
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        with tempfile.TemporaryDirectory(prefix="film-mcp-identity-TEST-") as temp, patch.dict(os.environ,{"FILMPROD_CATALOG_PATH":str(Path(temp)/"catalog.sqlite3")}):
            root=Path(temp)/"A"
            server.call_tool("film_projects",{"action":"create","payload":{"op_id":"A","project_id":"A","title":"TEST A","root":str(root),"test_only":True}},None)
            request={"root":str(root),"action":"artifact.save","payload":{"op_id":"bad","expected_project_id":"B"}}
            with patch("filmprod.core.Registry",side_effect=AssertionError("must not open/migrate registry")),self.assertRaisesRegex(ValueError,"identity changed"):
                server.call_tool("film_dispatch",request,None)
            import sqlite3
            with sqlite3.connect(root/".project/registry.sqlite3") as connection:
                row=json.loads(connection.execute("SELECT value FROM settings WHERE key='project'").fetchone()[0]);row["project_id"]="REPLACED"
                connection.execute("UPDATE settings SET value=? WHERE key='project'",(json.dumps(row),))
            connection.close()
            for tool_name,args in (("film_dispatch",{"action":"artifact.save","payload":{"op_id":"old-wrapper"}}),("film_media",{"action":"import","payload":{"op_id":"old-wrapper"}}),("film_render",{"payload":{"op_id":"old-wrapper","preview":True}})):
                with patch("filmprod.core.Registry",side_effect=AssertionError("must not open/migrate registry")),self.assertRaisesRegex(ValueError,"registered root"):
                    server.call_tool(tool_name,{"root":str(root),**args},None)

    def test_catalog_bound_board_and_private_media_preview(self):
        import importlib.util
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location("film_mcp_catalog_test", Path(__file__).with_name("mcp_server.py"))
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        with tempfile.TemporaryDirectory(prefix="film-mcp-catalog-TEST-") as temp, patch.dict(os.environ, {"FILMPROD_CATALOG_PATH":str(Path(temp)/"catalog.sqlite3")}):
            def call(name, **args):
                return server.call_tool(name,args,None)
            empty=call("film_board",thread_id="TEST-chat-A")["structuredContent"]
            self.assertTrue(empty["empty_state"])
            self.assertIsNone(empty["project_root"])
            for project_id in ("A","B"):
                call("film_projects",action="create",payload={"op_id":"create-"+project_id,"project_id":project_id,"title":"TEST "+project_id,"root":str(Path(temp)/project_id),"test_only":True,"thread_id":"TEST-chat-"+project_id})
            board=call("film_board",thread_id="TEST-chat-A")["structuredContent"]
            self.assertEqual(board["project"]["project_id"],"A")
            self.assertEqual(board["host_context"]["thread_id"],"TEST-chat-A")
            browsed=call("film_board",root=str(Path(temp)/"B"),thread_id="TEST-chat-A")["structuredContent"]
            self.assertEqual(browsed["project"]["project_id"],"B")
            self.assertEqual(browsed["catalog"]["current_thread_project"]["project_id"],"A")
            self.assertEqual(call("film_board",thread_id="TEST-chat-A")["structuredContent"]["project"]["project_id"],"A")
            private={"media_id":"VIDEO","thumbnail_data_uri":"data:image/jpeg;base64,TEST","preview_data_uri":"data:video/mp4;base64,TEST","preview_inline_available":True,"original_transmitted":False}
            with patch("filmprod.media120.media_action",return_value=private):
                response=call("film_media",root=str(Path(temp)/"A"),action="preview",payload={"media_id":"VIDEO"})
            self.assertNotIn("data:image",json.dumps(response["content"]))
            self.assertNotIn("preview_data_uri",response["structuredContent"])
            self.assertEqual(response["_meta"]["media_preview"],private)

    def test_protocol_and_registry(self):
        with tempfile.TemporaryDirectory(prefix="film-mcp-") as temp:
            requests = []
            def req(method, params=None):
                requests.append({"jsonrpc": "2.0", "id": len(requests)+1, "method": method, "params": params or {}})
            def call(name, args):
                req("tools/call", {"name": name, "arguments": args})
            root = str(Path(temp) / "原创测试")
            req("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
            req("tools/list")
            req("resources/read", {"uri": "ui://film-production-agent/board"})
            call("film_dispatch", {"root": root, "action": "project.init", "payload": {"op_id": "init", "project_id": "MCP-TEST", "title": "原创协议测试", "test_only": True}})
            payload = {"op_id": "save-one", "artifact_id": "S01", "kind": "script", "scope": "S01", "content": "灯亮了。", "base_version": 0, "deps": [], "metadata": {}}
            call("film_dispatch", {"root": root, "action": "artifact.save", "payload": payload})
            call("film_dispatch", {"root": root, "action": "artifact.save", "payload": payload})
            call("film_dispatch", {"root": root, "action": "artifact.save", "payload": {**payload, "op_id": "stale-save", "content": "旧底本不能覆盖"}})
            call("film_snapshot", {"root": root})
            call("film_dispatch", {"root": root, "action": "task.create", "payload": {"op_id": "task", "task_id": "T01", "title": "接续测试", "module": "director", "scope": "S01", "inputs": [{"artifact_id": "S01", "version": 1}], "must_keep": ["灯亮"], "allowed_changes": ["拍法"], "requirements": ["交付方案"]}})
            call("film_dispatch", {"root": root, "action": "task.checkpoint", "payload": {"op_id": "check", "task_id": "T01", "draft": "完整草稿：窗外雨声，桌上灯亮。", "completed": ["空间"], "decisions": [], "unresolved": [], "next_step": "声音核查"}})
            call("film_resume", {"root": root, "task_id": "T01"})
            call("film_snapshot", {"root": str(Path(temp)/"absent")})
            process = subprocess.run([sys.executable, "-X", "utf8", str(Path(__file__).with_name("mcp_server.py"))],
                input="\n".join(json.dumps(r, ensure_ascii=False) for r in requests)+"\n", capture_output=True, encoding="utf-8", timeout=20)
            self.assertEqual(process.returncode, 0, process.stderr)
            result = [json.loads(x) for x in process.stdout.splitlines()]
            self.assertEqual(len(result), len(requests))
            self.assertEqual(result[0]["result"]["serverInfo"]["version"], "1.15.0")
            self.assertEqual(len(result[1]["result"]["tools"]), 25)
            self.assertIn("ui/initialize", result[2]["result"]["contents"][0]["text"])
            for i in [3,4,5,7,8,9,10]:
                self.assertFalse(result[i].get("error") or result[i].get("result", {}).get("isError"), result[i])
            self.assertEqual(result[4]["result"], result[5]["result"])
            self.assertTrue(result[6]["result"]["isError"])
            self.assertEqual(len(result[7]["result"]["structuredContent"]["artifacts"]), 1)
            self.assertIn("完整草稿", json.dumps(result[10], ensure_ascii=False))
            self.assertTrue(result[11]["result"]["isError"])
            self.assertFalse((Path(temp)/"absent").exists())

    def test_history_export_and_host_observation(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("film_mcp_test", Path(__file__).with_name("mcp_server.py"))
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        with tempfile.TemporaryDirectory(prefix="film-mcp-new-") as temp:
            root = str(Path(temp) / "原创协议测试")
            def call(name, **args):
                return server.call_tool(name, {"root": root, **args}, None)["structuredContent"]
            health=call("film_health")
            self.assertFalse(health["project_registered"])
            self.assertFalse(Path(root).exists())
            call("film_dispatch", action="project.init", payload={"op_id":"init","project_id":"TEST","title":"原创协议测试","test_only":True})
            observation={"view":"full","observed_at":"2026-10-24T00:00:00+08:00","metadata":{"current_sequence":1,"url":"https://chatgpt.com/space/test_fixture"},
                         "content":{"page_id":"test_fixture","blocks":[{"kind":"markdown","id":"scene","hash":"synthetic","markdown":"# 第一场 S01 夜\n灯亮。"}]}}
            imported=call("film_pages_import",observation=observation,op_prefix="host-observe-1")
            self.assertEqual(imported["changed_scenes"],["S01"])
            second=call("film_pages_import",observation=observation,op_prefix="host-observe-1")
            self.assertEqual(second["changed_scenes"],[])
            history=call("film_history",artifact_id="SCRIPT-S01")
            self.assertEqual(len(history["versions"]),1)
            self.assertEqual(history["versions"][0]["content"],"# 第一场 S01 夜\n灯亮。")
            exported=call("film_export")
            self.assertTrue(Path(exported["entry"]).is_file())
            with self.assertRaises(ValueError):
                call("film_pages_import",observation={**observation,"view":"excerpts"},op_prefix="partial")
            with self.assertRaises(ValueError):
                call("film_pages_import",observation={**observation,"truncated":True},op_prefix="truncated")
            with self.assertRaises(ValueError):
                call("film_history",artifact_id={"wrong":"type"})
            with self.assertRaisesRegex(ValueError, "explicitly set preview"):
                call("film_render", payload={"artifact_id":"FINAL", "version":1, "op_id":"missing-mode"})
            self.assertFalse(call("film_health")["http_listener"])

    def test_render_errors_expose_explicit_operation_outcome(self):
        import importlib.util
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location("film_mcp_outcome_test", Path(__file__).with_name("mcp_server.py"))
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        from filmprod.core import Registry
        with tempfile.TemporaryDirectory(prefix="film-mcp-outcome-") as temp:
            registry = Registry(temp)
            registry.dispatch("project.init", {"op_id": "init", "project_id": "TEST", "title": "Outcome test only", "test_only": True})
            registry.close()
            request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "film_render", "arguments": {"root": temp, "payload": {"artifact_id": "MISSING", "version": 1, "op_id": "preflight", "preview": True}}}}
            rejected = server.handle(request, None)["result"]
            self.assertTrue(rejected["isError"])
            self.assertIn(rejected["structuredContent"]["error"]["operation_outcome"], ("no_write", "failed_before_commit"))
            error = OSError("Simulated lost return")
            error.operation_outcome = "resumable"
            with patch("filmprod.render.render_final", side_effect=error):
                result = server.handle(request, None)["result"]
            self.assertEqual(result["structuredContent"]["error"]["operation_outcome"], "resumable")
            with patch("filmprod.render.render_final", side_effect=RuntimeError("Unclassified boundary")):
                result = server.handle(request, None)["result"]
            self.assertEqual(result["structuredContent"]["error"]["operation_outcome"], "unknown")

if __name__ == "__main__":
    unittest.main(verbosity=2)

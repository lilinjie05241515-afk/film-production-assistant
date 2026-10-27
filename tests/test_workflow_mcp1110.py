"""Typed real-stdio integration; all projects and host observations are synthetic."""
import importlib.util
from contextlib import closing
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

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mcp_workflow1110", SOURCE/"plugin/mcp_server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

class WorkflowMCPTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="filmprod-TEST-workflow-mcp1110-")
        self.addCleanup(temp.cleanup)
        self.base=Path(temp.name);self.root=self.base/"TEST-project";self.pid="TEST-WORKFLOW1110"
        self.env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1","FILMPROD_CATALOG_PATH":str(self.base/"TEST-catalog.sqlite3")}
        r=Registry(self.root)
        r.dispatch("project.init",{"op_id":"init","project_id":self.pid,"title":"TEST only","test_only":True})
        r.dispatch("project.workflow.set",{"op_id":"route","expected_project_id":self.pid,"base_revision":0,"mode":"novel_to_screen"})
        r.close()
        self.db=self.root/".project/registry.sqlite3"
    def payload(self,**fields):
        return {"expected_project_id":self.pid,**fields}
    def args(self,action,**fields):
        return {"root":str(self.root),"action":action,"payload":self.payload(**fields)}
    def call(self,name,args,error=False):
        with patch.dict(os.environ,self.env):
            value=server.handle({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":name,"arguments":args}},None)["result"]
        self.assertEqual(bool(value.get("isError")),error,value)
        if not error:self.assertEqual(json.loads(value["content"][0]["text"]),value["structuredContent"])
        return value["structuredContent"]
    def stdio(self,requests):
        p=subprocess.run([sys.executable,"-B","-X","utf8",str(SOURCE/"plugin/mcp_server.py")],cwd=SOURCE,env=self.env,
            input="".join(json.dumps(x,ensure_ascii=False)+"\n" for x in requests).encode("utf-8"),capture_output=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        return [json.loads(line) for line in p.stdout.splitlines()]
    def definition(self):
        return self.args("define",op_id="define",delivery_id="TEST-DELIVERY",base_revision=0,target_artifact_id="TEST-DRAFT",scope="chapter/1",
            granularity="Keep the visible action and reaction",user_request={"reference":"TEST-user-turn","quote":"Write the full door opening and retreat."},inputs=[],
            units=[{"unit_id":"OPEN","description":"Opening and retreat","source":{"type":"user_request","reference":"TEST-user-turn","quote":"door opening and retreat"}}])
    def test_real_stdio_lists_24_tools_and_persists_eight_slots_without_host_creation(self):
        requests=[{"jsonrpc":"2.0","id":1,"method":"tools/list"},
            {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"film_workspace","arguments":self.args("prepare",op_id="prepare",base_revision=0)}},
            {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"film_workspace","arguments":self.args("read")}},
            {"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"film_delivery","arguments":self.args("read")}}]
        results=self.stdio(requests)
        self.assertEqual(len(results[0]["result"]["tools"]),26)
        for result in results[1:]:self.assertFalse(result["result"].get("isError"),result)
        ws=results[2]["result"]["structuredContent"]
        self.assertEqual(len(ws["slots"]),8);self.assertFalse(ws["host_execution"])
        self.assertTrue(all(not slot["thread_id"] for slot in ws["slots"]))
        with closing(sqlite3.connect(self.db)) as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM threads").fetchone()[0],0)
        self.assertEqual(results[3]["result"]["structuredContent"]["items"],[])
    def test_read_tools_and_legacy_read_actions_use_readonly_registry(self):
        before=self.db.read_bytes()
        with patch.object(Registry,"__init__",side_effect=AssertionError("Read must never open writable Registry")):
            self.call("film_workspace",self.args("read"))
            self.call("film_workspace",self.args("resolve",role="control"))
            self.call("film_delivery",self.args("read"))
            for action in ("workspace.read","delivery.read"):
                self.call("film_dispatch",{"root":str(self.root),"action":action,"payload":self.payload()})
        self.assertEqual(self.db.read_bytes(),before)
    def test_fixed_schema_errors_reject_before_project_lookup(self):
        define=self.definition();empty={**define,"payload":{**define["payload"],"units":[]}}
        invalid=[("film_workspace",self.args("prepare",op_id="x",base_revision=True)),
            ("film_workspace",self.args("read",op_id="extra")),
            ("film_workspace",self.args("resolve",role="invented")),
            ("film_workspace",self.args("record",op_id="r",base_revision=0,slot_id="TEST",event="queued",
                observation={"request_id":"TEST","source":"host_tool","tool":"create_thread","observed_at":"2026-10-25T12:00:00",
                    "client_thread_id":"CLIENT"})),
            ("film_delivery",empty),
            ("film_delivery",{**define,"payload":{**define["payload"],"base_revision":False}})]
        with patch.object(server,"checked_project_root",side_effect=AssertionError("Invalid schema touched project")):
            for name,args in invalid:
                result=self.call(name,args,error=True)
                self.assertEqual(result["error"]["type"],"ValueError",result)
    def test_unknown_workspace_state_survives_reopen_and_same_operation_retry(self):
        ws=self.call("film_workspace",self.args("prepare",op_id="prepare",base_revision=0));slot=ws["slots"][0]
        claim=self.args("record",op_id="claim",base_revision=ws["revision"],slot_id=slot["slot_id"],event="request_started",observation={"request_id":slot["request_id"]})
        claimed=self.call("film_workspace",claim)
        unknown=self.call("film_workspace",self.args("record",op_id="unknown",base_revision=claimed["revision"],slot_id=slot["slot_id"],event="unknown",observation={"request_id":slot["request_id"],"reason":"TEST lost host response"}))
        self.assertEqual(self.call("film_workspace",claim),claimed)
        reopened=self.call("film_workspace",self.args("read"))
        self.assertEqual(reopened["revision"],unknown["revision"])
        self.assertEqual(reopened["slots"][0]["status"],"unknown")
        self.assertEqual(reopened["slots"][0]["next_action"],"check_pending")
    def test_conditional_delivery_fields_reject_before_lookup(self):
        define=self.definition()
        request={"actor":"user","reference":"TEST-user-turn","quote":"Write the full door opening and retreat."}
        review=self.args("review",op_id="review",delivery_id="TEST-DELIVERY",revision=1,base_review_revision=0,
            artifact={"artifact_id":"TEST-DRAFT","version":1,"sha256":"0"*64},author={"type":"host_agent","id":"TEST-writer"},
            reviewer={"type":"host_subagent","id":"TEST-reviewer","source_reference":"TEST-only"},coverage=[],findings=[])
        finding={"finding_id":"TEST-GAP","severity":"major","status":"resolved","location":"TEST line","quote":"TEST body","detail":"TEST issue"}
        cases=[{**define,"payload":{**define["payload"],"mode":"summary"}},
            {**define,"payload":{**define["payload"],"mode":"full","summary_request":request}},
            {**review,"payload":{**review["payload"],"coverage":[{"unit_id":"OPEN","status":"covered","note":"TEST"}]}},
            {**review,"payload":{**review["payload"],"coverage":[{"unit_id":"OPEN","status":"needs_revision","note":"TEST"}]}},
            {**review,"payload":{**review["payload"],"findings":[finding]}},
            {**review,"payload":{**review["payload"],"findings":[{**finding,"status":"open","resolution":{"location":"TEST line","quote":"TEST body","explanation":"TEST"}}]}}]
        with patch.object(server,"checked_project_root",side_effect=AssertionError("Invalid combination reached project lookup")):
            for args in cases:
                result=self.call("film_delivery",args,error=True)
                self.assertEqual(result["error"]["type"],"ValueError",result)
    def test_delivery_exact_saved_text_ready_then_revision_stales_review(self):
        body="TEST: 甲推开门，乙后退一步。"
        saved=self.call("film_dispatch",{"root":str(self.root),"action":"artifact.save","payload":self.payload(op_id="draft",artifact_id="TEST-DRAFT",kind="novel",scope="chapter/1",content=body,base_version=0)})["artifact"]
        ref={k:saved[k] for k in ("artifact_id","version","sha256")}
        defined=self.call("film_delivery",self.definition());self.assertEqual(defined["mode"],"full")
        review=self.call("film_delivery",self.args("review",op_id="review",delivery_id="TEST-DELIVERY",revision=1,base_review_revision=0,artifact=ref,
            author={"type":"host_agent","id":"TEST-writer"},reviewer={"type":"host_subagent","id":"TEST-reviewer","source_reference":"synthetic-review-only"},
            coverage=[{"unit_id":"OPEN","status":"covered","output":{"location":"TEST first line","quote":"甲推开门，乙后退一步。"},"note":"TEST observed sequence"}],findings=[]))
        completed=self.call("film_delivery",self.args("complete",op_id="complete",delivery_id="TEST-DELIVERY",revision=1,review_id=review["review_id"],artifact=ref,base_completion_revision=0))
        self.assertTrue(completed["ready_for_delivery"]);self.assertFalse(completed["quality_guaranteed"]);self.assertFalse(completed["approval_changed"])
        self.call("film_dispatch",{"root":str(self.root),"action":"artifact.save","payload":self.payload(op_id="draft2",artifact_id="TEST-DRAFT",kind="novel",scope="chapter/1",content="TEST: 他们交谈后离开。",base_version=1)})
        current=self.call("film_delivery",self.args("read",delivery_id="TEST-DELIVERY"))
        self.assertFalse(current["ready_for_delivery"]);self.assertTrue(current["stale_reasons"])
        with closing(sqlite3.connect(self.db)) as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM approved_segments").fetchone()[0],0)
    def test_wrong_identity_and_missing_project_reads_do_not_write(self):
        before=self.db.read_bytes()
        for name in ("film_workspace","film_delivery"):
            args=self.args("read");args["payload"]["expected_project_id"]="WRONG"
            self.call(name,args,error=True)
            args=self.args("read");args["root"]=str(self.base/"TEST-missing")
            self.call(name,args,error=True)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertFalse((self.base/"TEST-missing").exists())

if __name__=="__main__":unittest.main()

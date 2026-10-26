"""1.13 art-workspace migration and scope tests, synthetic local state only."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid
from filmprod.core import Registry, ConflictError
from filmprod import workspace1110 as ws

OLD_ROUTES={"novel_only":("control","planning","novel","review"),
"screenplay":("control","planning","script","director","assets","review"),
"novel_to_screen":("control","planning","novel","script","director","assets","review")}

class ArtWorkspaceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix="TEST-art-workspace1130-")
  self.root=Path(self.tmp.name)/"project";self.r=Registry(self.root)
  self.call("project.init",project_id="TEST-ART-WS",title="合成美术工作区",test_only=True)
 def tearDown(self):
  self.r.close();self.tmp.cleanup()
 def call(self,action,**p):
  p.setdefault("op_id",uuid.uuid4().hex)
  if action.startswith("workspace."):p.setdefault("expected_project_id","TEST-ART-WS")
  return self.r.dispatch(action,p)
 def mode(self,mode):
  self.call("project.workflow.set",expected_project_id="TEST-ART-WS",mode=mode,base_revision=self.r._project().get("workflow",{}).get("revision",0))
 def read(self):return self.r.dispatch("workspace.read",{"expected_project_id":"TEST-ART-WS"})
 def prepare(self,**p):return self.call("workspace.prepare",base_revision=self.read()["revision"],**p)
 def resolve(self,scope="project"):
  return self.r.dispatch("workspace.resolve",{"expected_project_id":"TEST-ART-WS","role":"art","scope":scope})
 def legacy(self):
  self.mode("novel_to_screen")
  self.call("thread.register",thread_id="TEST-old-control",title="旧总控自定义标题",scope="project",status="active",current_control=True)
  with patch.object(ws,"ROUTE_ROLES",OLD_ROUTES):return self.prepare()
 def test_legacy_increment_adds_one_role_preserving_ids_and_history(self):
  old=self.legacy();frozen={x["slot_id"]:x for x in old["slots"]}
  missing=self.read();self.assertTrue(missing["needs_prepare"])
  new=self.prepare();self.assertEqual(len(new["slots"]),8)
  self.assertEqual([x["role"] for x in new["slots"] if x["slot_id"] not in frozen],["art"])
  for slot in new["slots"]:
   if slot["slot_id"] in frozen:self.assertEqual(slot,frozen[slot["slot_id"]])
  again=self.prepare();self.assertEqual(new,again)
  self.assertEqual(len(self.r._list("threads")),1)
  self.assertEqual(self.r._list("tasks"),[])
 def test_legacy_explicit_controller_fallback_is_readonly_not_new_art_binding(self):
  self.legacy();before=self.r.db.total_changes
  result=self.resolve("scene/3")
  self.assertEqual(result["resolution"],"legacy_control_fallback")
  self.assertEqual(result["requested_role"],"art")
  self.assertEqual(result["resolved_role"],"control")
  self.assertTrue(result["art_setup_needed"])
  self.assertEqual(result["slot"]["thread_id"],"TEST-old-control")
  self.assertFalse(result["execution_authorized"]);self.assertEqual(self.r.db.total_changes,before)
 def test_pending_art_never_escapes_to_legacy_controller(self):
  self.legacy();self.prepare()
  slot=self.resolve()["slot"]
  self.call("workspace.record",base_revision=self.read()["revision"],slot_id=slot["slot_id"],event="request_started",observation={"request_id":slot["request_id"]})
  self.call("workspace.record",base_revision=self.read()["revision"],slot_id=slot["slot_id"],event="unknown",observation={"request_id":slot["request_id"],"reason":"TEST disconnected"})
  result=self.resolve("scene/3")
  self.assertEqual(result["resolution"],"project_fallback")
  self.assertEqual(result["resolved_role"],"art")
  self.assertEqual(result["next_action"],"check_pending")
  self.assertEqual(result["slot"]["request_id"],slot["request_id"])
 def test_registered_art_blocks_fallback_without_claiming(self):
  self.legacy()
  self.call("thread.register",thread_id="TEST-art",title="只是登记的美术",scope="project",purpose="art",status="active")
  result=self.resolve("scene/3")
  self.assertIsNone(result["slot"]);self.assertTrue(result["project_fallback_blocked"])
  self.assertEqual(result["registry_candidates"],[{"thread_id":"TEST-art","title":"只是登记的美术"}])
 def test_pure_novel_art_is_opt_in_and_reversible_without_deleting(self):
  self.mode("novel_only");base=self.prepare();self.assertEqual(len(base["slots"]),4)
  added=self.prepare(include_art=True);self.assertEqual(len(added["slots"]),5)
  art=self.resolve()["slot"];self.assertEqual(art["role"],"art")
  self.assertEqual(self.prepare(),added)
  retired=self.prepare(include_art=False);self.assertEqual(len(retired["slots"]),4)
  self.assertEqual(retired["retired_slots"][0]["slot_id"],art["slot_id"])
  self.assertIsNone(self.resolve()["slot"])
  restored=self.prepare(include_art=True)
  self.assertEqual(next(x for x in restored["slots"] if x["role"]=="art")["slot_id"],art["slot_id"])
 def test_optional_art_exact_registry_blocks_control_without_enabling_role(self):
  self.mode("novel_only")
  self.call("thread.register",thread_id="TEST-control",title="既有总控",scope="project",status="active",current_control=True)
  self.prepare()
  self.call("thread.register",thread_id="TEST-scene-art",title="既有场景美术",scope="scene/01",purpose="art",status="active")
  before=self.r.db.total_changes;result=self.resolve("scene/01")
  self.assertFalse(result["role_active"]);self.assertIsNone(result["slot"])
  self.assertTrue(result["project_fallback_blocked"])
  self.assertEqual(result["registry_candidates"],[{"thread_id":"TEST-scene-art","title":"既有场景美术"}])
  self.assertEqual(self.r.db.total_changes,before);self.assertEqual(len(self.read()["slots"]),4)
 def test_exact_scoped_art_wins_and_other_scope_stays_unclaimed(self):
  self.mode("screenplay");self.prepare();self.prepare(scope="scene/1")
  exact=self.resolve("scene/1");other=self.resolve("scene/2")
  self.assertEqual(exact["resolution"],"exact")
  self.assertEqual(exact["resolved_scope"],"scene/1")
  self.assertEqual(other["resolution"],"project_fallback")
  self.assertEqual(other["resolved_scope"],"project")
 def test_invalid_opt_in_type_and_stale_revision_do_not_change_slots(self):
  self.mode("novel_only");base=self.prepare();logical=self.read()
  with self.assertRaises(ValueError):self.prepare(include_art=1)
  with self.assertRaises(ConflictError):self.call("workspace.prepare",base_revision=0,include_art=True)
  self.assertEqual(self.read(),logical)
 def test_readonly_connection_preserves_database_bytes(self):
  self.legacy();self.r.close()
  database=self.root/".project/registry.sqlite3";before=database.read_bytes()
  self.r=Registry.open_readonly(self.root);self.resolve();self.read()
  self.assertEqual(database.read_bytes(),before)

if __name__=="__main__":unittest.main()


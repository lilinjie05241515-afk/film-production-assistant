"""Catalog, isolation and local video tests; all projects are disposable TEST data."""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from filmprod.core import ConflictError, Registry
from filmprod.projects import ProjectCatalog, project_identity
from filmprod.media120 import import_video, preview_video


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="film-catalog-TEST-")
        self.root = Path(self.temp.name)
        self.catalog_path = self.root / "catalog.sqlite3"
        self.catalog = ProjectCatalog(self.catalog_path)

    def tearDown(self):
        self.catalog.close()
        self.temp.cleanup()

    def create(self, project_id, **extra):
        payload = dict(op_id="create-"+project_id, root=str(self.root/project_id), project_id=project_id, title="TEST "+project_id, test_only=True, **extra)
        return self.catalog.dispatch("create", payload)

    def test_catalog_persists_and_chat_binding_takes_priority(self):
        self.create("A", thread_id="chat-A", client_project_id="client-A")
        self.create("B", thread_id="chat-B", client_project_id="client-B")
        state = self.catalog.dispatch("resolve", {"thread_id":"chat-A", "client_project_id":"client-B"})
        self.assertEqual(state["resolved_project"]["project_id"], "A")
        self.assertEqual(state["resolution"], "thread_binding")
        self.assertIsNone(self.catalog.dispatch("resolve", {"thread_id":"new-chat"})["resolved_project"])
        self.catalog.close()
        self.catalog = ProjectCatalog(self.catalog_path)
        self.assertEqual(len(self.catalog.snapshot()["projects"]), 2)
        self.assertEqual(self.catalog.snapshot({"thread_id":"chat-B"})["resolved_project"]["project_id"], "B")

    def test_existing_identity_resume_and_operation_replay(self):
        self.create("A")
        request = {"op_id":"register-A", "root":str(self.root/"A")}
        result = self.catalog.dispatch("register", request)
        self.assertEqual(self.catalog.dispatch("register", request), result)
        self.assertTrue(self.catalog.dispatch("outcome", {"op_id":"register-A"})["found"])
        with self.assertRaises(ConflictError):
            self.catalog.dispatch("register", {**request, "thread_id":"another"})
        resumed = self.catalog.dispatch("create", {"op_id":"resume-existing", "root":str(self.root/"A"), "project_id":"A", "title":"unused rename", "test_only":True})
        self.assertTrue(resumed["resumed_existing"])
        self.assertEqual(resumed["project"]["title"], "TEST A")
        with self.assertRaises(ConflictError):
            self.catalog.dispatch("create", {"op_id":"duplicate", "root":str(self.root/"duplicate"), "project_id":"A", "title":"TEST A", "test_only":True})
        self.assertFalse((self.root/"duplicate").exists())

    def test_registering_another_project_preserves_bound_chat_without_partial_rejection(self):
        self.create("A",thread_id="chat")
        result=self.create("B",thread_id="chat")
        self.assertEqual(result["project"]["project_id"],"B")
        self.assertEqual(result["resolved_project"]["project_id"],"A")
        self.assertEqual(len(result["projects"]),2)
        bad=self.root/"invalid"
        with self.assertRaises(ValueError):
            self.catalog.dispatch("create",{"op_id":"invalid-create","root":str(bad),"project_id":"INVALID","title":"TEST","test_only":"yes","thread_id":{}})
        self.assertFalse(bad.exists())

    def test_relink_verifies_identity_and_updates_existing_bindings(self):
        self.create("A", thread_id="chat-A")
        self.create("B")
        moved = self.root/"moved-A"
        shutil.move(str(self.root/"A"), str(moved))
        self.assertFalse(self.catalog.snapshot({"thread_id":"chat-A"})["resolved_project"]["available"])
        with self.assertRaises(ConflictError):
            self.catalog.dispatch("relink", {"op_id":"wrong", "project_id":"A", "root":str(self.root/"B")})
        result = self.catalog.dispatch("relink", {"op_id":"move", "project_id":"A", "root":str(moved), "thread_id":"chat-A"})
        self.assertEqual(Path(result["resolved_project"]["root"]), moved)
        self.assertTrue(result["resolved_project"]["available"])

    def test_bind_requires_explicit_replacement_and_forget_keeps_source(self):
        self.create("A", thread_id="chat")
        self.create("B")
        request = {"op_id":"rebind", "project_id":"B", "thread_id":"chat"}
        with self.assertRaises(ConflictError):
            self.catalog.dispatch("bind", request)
        self.catalog.dispatch("bind", {**request,"replace":True})
        self.assertEqual(self.catalog.snapshot({"thread_id":"chat"})["resolved_project"]["project_id"],"B")
        self.catalog.dispatch("forget", {"op_id":"forget-A", "project_id":"A"})
        self.assertEqual(project_identity(self.root/"A")["project_id"],"A")
        self.assertEqual(len(self.catalog.snapshot()["projects"]),1)

    def test_no_scanning_or_implicit_initialization(self):
        unrelated = self.root/"unrelated"
        unrelated.mkdir()
        (unrelated/"source.txt").write_text("unrelated",encoding="utf-8")
        self.assertEqual(self.catalog.snapshot()["projects"],[])
        with self.assertRaises(ValueError):
            self.catalog.dispatch("register", {"op_id":"absent", "root":str(unrelated)})
        with self.assertRaises(ValueError):
            self.catalog.dispatch("create", {"op_id":"nonempty", "root":str(unrelated), "project_id":"A", "title":"TEST", "test_only":True})
        self.assertFalse((unrelated/".project").exists())


class NativeMediaTest(unittest.TestCase):
    def test_pending_import_recovers_after_restore_without_retargeting_committed_payload(self):
        for interrupted_after_commit in (False, True):
            with self.subTest(interrupted_after_commit=interrupted_after_commit), tempfile.TemporaryDirectory(prefix="film-import-restore-TEST-") as temp:
                base=Path(temp); original=base/"original"; registry=Registry(original)
                registry.dispatch("project.init",{"op_id":"init","project_id":"TEST-MEDIA-RESTORE","title":"TEST restored import","test_only":True})
                source=base/"synthetic.mp4"; source.write_bytes(b"SYNTHETIC-VIDEO-ONLY")
                payload={"op_id":"import","media_id":"M1","path":str(source),"kind":"clip","expected_project_id":"TEST-MEDIA-RESTORE"}
                dispatch=registry.dispatch
                def interrupted(action,p):
                    if action=="media.register":
                        if interrupted_after_commit:
                            dispatch(action,p)
                        raise OSError("synthetic lost result")
                    return dispatch(action,p)
                with patch("filmprod.media120.probe",return_value={"streams":[{"codec_type":"video"}],"format":{"duration":"1"}}),patch.object(registry,"dispatch",interrupted):
                    with self.assertRaises(OSError):
                        import_video(registry,payload)
                prepared_before=json.loads(registry.db.execute("SELECT prepared FROM media_import_jobs").fetchone()[0])
                archive=base/"backup.zip"; restored=base/"restored"
                registry.dispatch("backup.create",{"op_id":"backup","destination":str(archive)})
                registry.dispatch("backup.restore",{"op_id":"restore","source":str(archive),"destination":str(restored)})
                registry.close(); original.rename(base/"moved-original")
                registry=Registry(restored)
                try:
                    with patch("filmprod.media120._thumbnail",side_effect=ValueError("synthetic preview omitted")):
                        result=import_video(registry,payload)
                    self.assertTrue(Path(result["local_path"]).is_relative_to(restored))
                    self.assertTrue(Path(result["local_path"]).is_file())
                    self.assertEqual(result["metadata"]["original_source_path"],str(source))
                    after=json.loads(registry.db.execute("SELECT prepared FROM media_import_jobs").fetchone()[0])
                    if interrupted_after_commit:
                        self.assertEqual(after,prepared_before)
                    else:
                        self.assertNotEqual(after["path"],prepared_before["path"])
                        self.assertTrue(Path(after["path"]).is_relative_to(restored))
                    self.assertEqual(len(registry.snapshot()["media"]),1)
                    self.assertEqual(import_video(registry,payload)["local_path"],result["local_path"])
                finally:
                    registry.close()

    def test_completed_import_cache_resolves_current_root_after_move(self):
        with tempfile.TemporaryDirectory(prefix="film-import-move-TEST-") as temp:
            base=Path(temp); original=base/"original"; registry=Registry(original)
            registry.dispatch("project.init",{"op_id":"init","project_id":"TEST-MEDIA-MOVE","title":"TEST moved import","test_only":True})
            source=base/"synthetic.mp4"; source.write_bytes(b"SYNTHETIC-VIDEO-ONLY")
            payload={"op_id":"import","media_id":"M1","path":str(source),"kind":"clip"}
            with patch("filmprod.media120.probe",return_value={"streams":[{"codec_type":"video"}],"format":{"duration":"1"}}),patch("filmprod.media120._thumbnail",side_effect=ValueError("synthetic preview omitted")):
                before=import_video(registry,payload)
            registry.close(); moved=base/"moved"; original.rename(moved)
            registry=Registry(moved)
            try:
                after=import_video(registry,payload)
                self.assertNotEqual(before["local_path"],after["local_path"])
                self.assertTrue(Path(after["local_path"]).is_relative_to(moved))
                self.assertEqual(after["sha256"],before["sha256"])
            finally:
                registry.close()

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires local FFmpeg")
    def test_video_import_preview_idempotency_and_project_isolation(self):
        with tempfile.TemporaryDirectory(prefix="film-media-TEST-") as temp:
            root=Path(temp)
            source=root/"synthetic.mp4"
            subprocess.run([shutil.which("ffmpeg"),"-hide_banner","-loglevel","error","-f","lavfi","-i","color=c=blue:s=320x180:d=0.4","-c:v","libx264","-pix_fmt","yuv420p","-y",str(source)],check=True,capture_output=True)
            registry=Registry(root/"A")
            registry.dispatch("project.init",{"op_id":"init","project_id":"TEST-MEDIA-A","title":"TEST MEDIA","test_only":True})
            second=Registry(root/"B")
            second.dispatch("project.init",{"op_id":"init","project_id":"TEST-MEDIA-B","title":"TEST MEDIA B","test_only":True})
            try:
                request={"op_id":"import-one","media_id":"VIDEO-1","path":str(source),"kind":"clip","metadata":{"title":"合成测试视频","scene":"S01","synthetic":True}}
                imported=import_video(registry,request)
                self.assertEqual(import_video(registry,request),imported)
                self.assertTrue(Path(imported["local_path"]).is_relative_to(registry.root))
                self.assertEqual(imported["metadata"]["video_category"],"clip")
                self.assertGreater(imported["metadata"]["duration_seconds"],0)
                preview=preview_video(registry,{"media_id":"VIDEO-1"})
                self.assertTrue(preview["preview_inline_available"])
                self.assertTrue(preview["thumbnail_data_uri"].startswith("data:image/jpeg;base64,"))
                self.assertTrue(preview["preview_data_uri"].startswith("data:video/mp4;base64,"))
                self.assertFalse(preview["original_transmitted"])
                thumbnail_only=preview_video(registry,{"media_id":"VIDEO-1","thumbnail_only":True})
                self.assertIsNone(thumbnail_only["preview_data_uri"])
                self.assertEqual(imported["metadata"]["original_source_path"],str(source.resolve()))
                self.assertEqual(list((registry.internal/"import-staging").iterdir()),[])
                self.assertEqual(second.snapshot()["media"],[])
                with self.assertRaises(ConflictError):
                    import_video(registry,{**request,"kind":"final"})
                with self.assertRaises(ValueError):
                    preview_video(second,{"media_id":"VIDEO-1"})
            finally:
                registry.close()
                second.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

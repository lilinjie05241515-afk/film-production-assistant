"""Actual management boundary and audio tests; independent synthetic fixtures only."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

from filmprod.core import Registry
from filmprod.board_gateway1150 import ALL_ACTIONS, call_board, catalog_read
from plugin.mcp_server import call_tool, checked_project_root, TOOLS, handle


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="board1150-test_only-")
        self.base = Path(self.temp.name)
        self.root = self.base / "TEST-project"
        self.env = patch.dict(os.environ, {"FILMPROD_CATALOG_PATH": str(self.base / "TEST-catalog.sqlite3")})
        self.env.start()
        registry = Registry(self.root)
        registry.dispatch("project.init", {"op_id": "init", "project_id": "TEST-BOARD", "title": "Synthetic", "test_only": True})
        registry.dispatch("artifact.save", {"op_id": "save", "artifact_id": "SCRIPT", "kind": "script", "scope": "episode/1", "base_version": 0,
            "content": "# 合成正文\n完整台词。", "deps": [], "metadata": {"workflow_stage": "dynamic_script", "title": "合成文本"}})
        registry.close()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def board(self, action, **payload):
        return call_tool("film_board_manage", {"root": str(self.root), "action": action,
            "payload": {"expected_project_id": "TEST-BOARD", **payload}}, None)

    def dump(self):
        registry = Registry.open_readonly(self.root)
        try:
            return "\n".join(registry.db.iterdump())
        finally:
            registry.close()

    def test_query_is_no_write_and_missing_catalog_not_created(self):
        before = self.dump()
        for _ in range(3):
            snap = self.board("snapshot")["structuredContent"]
            self.assertEqual(snap["project"]["project_id"], "TEST-BOARD")
            self.board("artifact.history", artifact_id="SCRIPT")
            self.board("artifact.get", artifact_id="SCRIPT", version=1)
        self.assertEqual(before, self.dump())
        self.assertFalse((self.base / "TEST-catalog.sqlite3").exists())
        self.assertEqual(catalog_read()["projects"], [])

    def test_business_actions_rejected_before_root_or_registry_open(self):
        forbidden = ["task.create", "task.checkpoint", "task.submit", "task.cancel", "artifact.save", "artifact.restore",
            "content.approve", "decision.record", "project.init", "project.workflow.set", "cue.save", "render", "film_render",
            "workspace.prepare", "workspace.record", "cloud.configure", "cloud.prepare", "art.select", "screenwriting.resolve",
            "thread.register", "sync.observe", "projects.create", "board.anything", "board.task.create", "send_message"]
        before = self.dump()
        for action in forbidden:
            with self.subTest(action=action), patch("filmprod.core.Registry.open_readonly", side_effect=AssertionError("opened")):
                with self.assertRaisesRegex(ValueError, "不允许"):
                    call_board({"root": str(self.base / "MUST-NOT-EXIST"), "action": action, "payload": {"op_id": "evil"}}, None, checked_project_root)
        self.assertEqual(before, self.dump())
        self.assertFalse((self.base / "MUST-NOT-EXIST").exists())

    def test_all_old_tools_are_model_only_and_only_gateway_app_visible(self):
        self.assertEqual([t["name"] for t in TOOLS if "app" in t.get("_meta", {}).get("ui", {}).get("visibility", [])], ["film_board_manage"])
        self.assertTrue({"film_art", "film_screenwriting", "film_draft_submit", "film_render"}.issubset({t["name"] for t in TOOLS}))
        for tool in TOOLS:
            self.assertEqual(tool["_meta"]["ui"]["visibility"], ["app"] if tool["name"] == "film_board_manage" else ["model"])

    def test_work_chat_still_saves_and_approves_accurate_synthetic_version(self):
        result = call_tool("film_dispatch", {"root": str(self.root), "action": "artifact.save", "payload": {
            "op_id": "v2", "artifact_id": "SCRIPT", "kind": "script", "scope": "episode/1", "base_version": 1,
            "content": "完整新候选", "deps": [], "metadata": {"workflow_stage": "dynamic_script"}}}, None)
        self.assertEqual(result["structuredContent"]["artifact"]["version"], 2)
        call_tool("film_dispatch", {"root": str(self.root), "action": "content.approve", "payload": {
            "op_id": "approve", "artifact_id": "SCRIPT", "version": 1, "scope": "episode/1",
            "evidence": "synthetic only", "actor": "test", "synthetic": True}}, None)
        snap = self.board("snapshot")["structuredContent"]
        self.assertEqual(snap["approved_artifacts"][0]["version"], 1)
        self.assertEqual(snap["artifacts"][0]["version"], 2)

    def test_original_tools_query_uses_readonly_connection(self):
        before = self.dump()
        for name, extra in (("film_board", {}), ("film_snapshot", {}), ("film_history", {"artifact_id": "SCRIPT"})):
            call_tool(name, {"root": str(self.root), **extra}, None)
        self.assertEqual(before, self.dump())

    def test_identity_and_import_business_metadata_rejected(self):
        with self.assertRaisesRegex(ValueError, "身份"):
            call_tool("film_board_manage", {"root": str(self.root), "action": "artifact.history", "payload": {"artifact_id": "SCRIPT"}}, None)
        with self.assertRaisesRegex(ValueError, "identity"):
            self.board("snapshot", expected_project_id="OTHER")
        with self.assertRaisesRegex(ValueError, "审核"):
            self.board("media.import_audio", op_id="bad", media_id="bad", path="missing.wav", metadata={"status": "approved"})

    def test_compact_context_suggestions_exclude_recycled_version(self):
        registry = Registry(self.root)
        registry.dispatch("project.workflow.set", {"op_id":"route", "expected_project_id":"TEST-BOARD", "mode":"screenplay", "base_revision":0})
        registry.dispatch("content.approve", {"op_id":"adopt", "artifact_id":"SCRIPT", "version":1,
            "scope":"episode/1", "evidence":"synthetic", "actor":"test", "synthetic":True})
        artifact=registry._artifact("SCRIPT",1)
        registry.dispatch("trash.set", {"op_id":"trash", "expected_project_id":"TEST-BOARD", "target_type":"artifact",
            "target_id":"SCRIPT", "version":1, "expected_sha256":artifact["sha256"], "base_revision":0, "deleted":True})
        registry.close()
        result = call_tool("film_context", {"root":str(self.root), "expected_project_id":"TEST-BOARD", "mode":"summary"}, None)["structuredContent"]
        suggestions = [entry for stage in result["workflow"].get("stages",[]) for entry in stage.get("dependency_suggestions",[])]
        self.assertTrue(any(entry.get("recycled_refs") for entry in suggestions))
        self.assertFalse(any(ref.get("artifact_id")=="SCRIPT" for entry in suggestions for ref in entry.get("refs",[])))
        self.assertTrue(any(a["artifact_id"]=="SCRIPT" for a in result["approved_artifacts"]))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "local image import requires FFmpeg")
    def test_committed_image_error_preserves_unknown_outcome_and_original_operation(self):
        from test_image_preview180 import png
        source = self.base / "synthetic.png"
        png(source, 64, 32)
        payload = {"op_id":"IMAGE-UNKNOWN", "media_id":"IMAGE", "path":str(source),
                   "expected_project_id":"TEST-BOARD", "metadata":{"title":"Synthetic"}}
        request = {"jsonrpc":"2.0", "id":1, "method":"tools/call", "params":{
            "name":"film_board_manage", "arguments":{"root":str(self.root), "action":"media.import_image", "payload":payload}}}
        with patch("filmprod.image_preview180.verified_original", side_effect=ValueError("injected after commit")):
            response = handle(request, None)["result"]
        self.assertTrue(response["isError"])
        self.assertEqual(response["structuredContent"]["error"]["operation_outcome"], "unknown")
        registry = Registry.open_readonly(self.root)
        try:
            self.assertEqual(len(registry._list("media")), 1)
        finally:
            registry.close()
        recovered = handle(request, None)["result"]
        self.assertFalse(recovered.get("isError"), recovered)
        self.assertEqual(recovered["structuredContent"]["media_id"], "IMAGE")
        self.assertEqual(len(self.board("snapshot")["structuredContent"]["media"]), 1)

    def test_each_media_gateway_import_serializes_uncertain_outcomes(self):
        for action in ("media.import", "media.import_image", "media.import_audio"):
            for outcome in ("unknown", "resumable", "no_write", "failed_before_commit"):
                with self.subTest(action=action, outcome=outcome):
                    error = ValueError("injected transport-boundary result")
                    error.operation_outcome = outcome
                    request = {"jsonrpc":"2.0", "id":1, "method":"tools/call", "params":{
                        "name":"film_board_manage", "arguments":{"action":action}}}
                    with patch("plugin.mcp_server.call_tool", side_effect=error):
                        result = handle(request, None)["result"]
                    self.assertEqual(result["structuredContent"]["error"]["operation_outcome"], outcome)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "real import rejection requires local FFmpeg")
    def test_invalid_files_are_precommit_rejections_for_all_three_media_types(self):
        for action, suffix in (("media.import_image", ".png"), ("media.import", ".mp4"), ("media.import_audio", ".wav")):
            with self.subTest(action=action):
                source = self.base / ("invalid-synthetic" + suffix)
                source.write_bytes(b"synthetic invalid media, no original to register")
                payload = {"op_id":"INVALID"+suffix, "media_id":"INVALID"+suffix,
                    "path":str(source), "expected_project_id":"TEST-BOARD", "metadata":{}}
                if action == "media.import":
                    payload["kind"] = "take"
                request = {"jsonrpc":"2.0", "id":1, "method":"tools/call", "params":{
                    "name":"film_board_manage", "arguments":{"root":str(self.root), "action":action, "payload":payload}}}
                result = handle(request, None)["result"]
                self.assertTrue(result["isError"])
                self.assertEqual(result["structuredContent"]["error"]["operation_outcome"], "failed_before_commit")
                self.assertEqual(self.board("snapshot")["structuredContent"]["media"], [])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe") and shutil.which("node"), "preview contract requires local FFmpeg and Node")
    def test_real_video_preview_passes_actual_ui_contract_and_rejects_linked_cache(self):
        source = self.base / "synthetic-video.mp4"
        subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
            "-i", "color=c=gray:s=64x32:r=12:d=1", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True)
        original_bytes = source.read_bytes()
        with patch("filmprod.media120.probe", side_effect=RuntimeError("injected before video metadata read")):
            with self.assertRaises(RuntimeError):
                self.board("media.import", op_id="VIDEO", media_id="VIDEO", path=str(source), kind="take", metadata={})
        # The retry must use the already frozen/staged original, never new bytes
        # that appeared at the user's source path after an uncertain operation.
        source.write_bytes(b"changed source after interruption")
        imported = self.board("media.import", op_id="VIDEO", media_id="VIDEO", path=str(source), kind="take", metadata={})["structuredContent"]
        self.assertEqual(imported["sha256"], hashlib.sha256(original_bytes).hexdigest())
        before = self.dump()
        preview = self.board("media.preview", media_id="VIDEO")
        self.assertEqual(self.dump(), before)
        data = preview["_meta"]["media_preview"]
        self.assertTrue(data["preview_data_uri"].startswith("data:video/mp4;base64,"))
        self.assertNotIn("preview_data_uri", preview["structuredContent"])
        html = Path(__file__).resolve().parents[1] / "plugin/ui/board.html"
        program = "const fs=require('fs'),vm=require('vm');const c={module:{exports:{}}};vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8').split('<script>')[1].split('</script>')[0],c);const p=JSON.parse(fs.readFileSync(0,'utf8'));c.module.exports.verifyPreview(p,{target_id:'VIDEO',kind:'video',sha256:p.sha256},'TEST-BOARD');console.log('actual UI preview contract passed');"
        verified = subprocess.run([shutil.which("node"), "-e", program, str(html)], input=json.dumps(data), text=True, capture_output=True, encoding="utf-8")
        self.assertEqual(verified.returncode, 0, verified.stderr)
        derivative = self.root / ".project/previews" / (imported["sha256"] + ".preview.mp4")
        external = self.base / "synthetic-external-cache.mp4"
        external.write_bytes(derivative.read_bytes())
        derivative.unlink()
        os.link(external, derivative)
        with self.assertRaises(ValueError):
            self.board("media.preview", media_id="VIDEO")
        self.assertEqual(self.dump(), before)
        Path(imported["local_path"]).write_bytes(b"corrupted registered original")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.board("media.import", op_id="VIDEO", media_id="VIDEO", path=str(source), kind="take", metadata={})

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "local audio preview requires FFmpeg")
    def test_audio_import_preview_idempotency_hash_and_no_adoption(self):
        source = self.base / "synthetic-test-tone.wav"
        with wave.open(str(source), "wb") as writer:
            writer.setparams((1, 2, 16000, 16000, "NONE", "not compressed"))
            writer.writeframes(b"\x00\x00" * 16000)
        original = source.read_bytes()
        payload = {"op_id": "audio-import", "media_id": "AUDIO", "path": str(source), "metadata": {"title": "合成静音", "audio_category": "ambience"}}
        imported = self.board("media.import_audio", **payload)["structuredContent"]
        repeated = self.board("media.import_audio", **payload)["structuredContent"]
        self.assertEqual(imported, repeated)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(imported["sha256"], hashlib.sha256(original).hexdigest())
        before = self.dump()
        preview = self.board("media.preview_audio", media_id="AUDIO")
        self.assertTrue(preview["_meta"]["media_preview"]["preview_data_uri"].startswith("data:audio/mpeg;base64,"))
        self.assertNotIn("preview_data_uri", preview["structuredContent"])
        self.assertNotIn("base64", preview["content"][0]["text"])
        self.assertEqual(before, self.dump())
        snap = self.board("snapshot")["structuredContent"]
        self.assertEqual(snap["media"][0]["status"], "registered")
        self.assertEqual(snap["decisions"], [])
        self.assertFalse(imported["music_generated"])
        with self.assertRaisesRegex(ValueError, "op_id"):
            self.board("media.import_audio", **{**payload, "metadata": {"title": "changed"}})
        Path(imported["local_path"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.board("media.preview_audio", media_id="AUDIO")


if __name__ == "__main__":
    unittest.main()

import array
import hashlib
import json
import math
import shutil
import subprocess
import tempfile
import unittest
import uuid
import wave
from pathlib import Path
from unittest.mock import patch

from filmprod.core import Registry, ConflictError
from filmprod.render import render_final, probe, _job_lock, render_operation_outcome


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "actual FFmpeg/ffprobe are required")
class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(__file__).resolve().parents[1] / "work" / "render-tests"
        cls.work.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="TEST_ONLY_", dir=cls.work)
        cls.base = Path(cls.temp.name)
        cls.red, cls.blue, cls.tone = cls.base / "TEST_RED.mp4", cls.base / "TEST_BLUE.mp4", cls.base / "TEST_TONE.wav"
        for path, color in ((cls.red, "red"), (cls.blue, "blue")):
            subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-n", "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=24:d=1.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
        samples = array.array("h", (int(8000 * math.sin(2 * math.pi * 440 * i / 48000)) for i in range(48000)))
        with wave.open(str(cls.tone), "wb") as stream:
            stream.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
            stream.writeframes(samples.tobytes())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.project_temp = tempfile.TemporaryDirectory(prefix="PROJECT_", dir=self.base)
        self.root = Path(self.project_temp.name)
        self.r = Registry(self.root)
        self.call("project.init", project_id="RENDER-TEST", title="原创技术色块测试", test_only=True)

    def tearDown(self):
        self.r.close()
        self.project_temp.cleanup()

    def call(self, action, **p):
        return self.r.dispatch(action, dict(op_id=uuid.uuid4().hex, **p))

    @staticmethod
    def ref(aid):
        return {"artifact_id": aid, "version": 1}

    def save(self, aid, kind, metadata=None, deps=None, base=0):
        return self.call("artifact.save", artifact_id=aid, kind=kind, scope="TEST/" + aid, content=f"TEST_ONLY {aid} v{base+1}", base_version=base, metadata=metadata or {}, deps=deps or [])

    def approve(self, aid, version=1):
        artifact = self.r._artifact(aid, version)
        return self.call("content.approve", artifact_id=aid, version=version, scope=artifact["scope"], evidence="合成技术测试批准", actor="test-runner", synthetic=True)

    def fixture(self, audio=True, subtitles=True, gap=False, planned=False, rights=False):
        rights_data = {"rights_status": "owned", "rights_evidence": "Original generated technical fixture"} if rights else {"rights_status": None}
        for aid, path, kind in (("RED", self.red, "video"), ("BLUE", self.blue, "video"), ("TONE", self.tone, "audio")):
            self.call("media.register", media_id=aid, kind=kind, path=str(path), metadata=dict(rights_data, test_only=True))
        for aid, media in (("CLIP1", "RED"), ("CLIP2", "BLUE")):
            self.save(aid, "clip", {"source_media_id": media, "in_seconds": 0.25, "out_seconds": 1.25})
        clips = [self.ref("CLIP1"), self.ref("CLIP2")]
        self.save("SEQUENCE", "sequence", {"clips": [dict(clips[0], timeline_in_seconds=0), dict(clips[1], timeline_in_seconds=1.2 if gap else 1)]}, clips)
        meta = {"timeline": self.ref("SEQUENCE"), "shots": clips, "music": [], "dialogue": [], "subtitles": [], "export_spec": {"width": 320, "height": 180, "fps": 24, "format": "mp4"}}
        deps = [self.ref("SEQUENCE"), *clips]
        if audio:
            self.save("MUSIC", "music", {"source_media_id": "TONE", "in_seconds": 0, "out_seconds": 1, "timeline_in_seconds": 0.5, "gain": 0.5})
            meta["music"] = [self.ref("MUSIC")]
            deps.append(self.ref("MUSIC"))
        if subtitles:
            self.save("SUBTITLE", "subtitle", dict(rights_data, cues=[{"start_seconds": 0.25, "end_seconds": 0.8, "text": "第一段 RED"}, {"start_seconds": 1.2, "end_seconds": 1.8, "text": "第二段 BLUE"}]))
            meta["subtitles"] = [self.ref("SUBTITLE")]
            deps.append(self.ref("SUBTITLE"))
        if planned:
            self.save("CUE", "cue")
            meta.update(planned_music=[self.ref("CUE")], assembly_status="planned", render_status="not_rendered")
            deps.append(self.ref("CUE"))
        self.save("FINAL", "final", meta, deps)

    def render(self, **payload):
        return render_final(self.r, dict(artifact_id="FINAL", version=1, op_id=payload.pop("op_id", uuid.uuid4().hex), preview=payload.pop("preview", True), **payload))

    def test_actual_two_cut_audio_subtitle_render(self):
        self.fixture()
        result = self.render(op_id="actual-video")
        path = Path(result["path"])
        self.assertTrue(path.is_file())
        self.assertTrue(result["verification"]["fully_decoded"])
        self.assertTrue(result["verification"]["subtitle_text_readback"])
        self.assertTrue(result["preview"])
        self.assertEqual(result["adoption"], "not_recorded")
        info = probe(path)
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"]), (320, 180))
        self.assertAlmostEqual(float(video["duration"]), 2, places=2)
        self.assertEqual(video["avg_frame_rate"], "24/1")
        # Read a center pixel away from the preview watermark, on either side
        # of the cut. This verifies content order, not just a container header.
        for time, channel in ((0.5, 0), (1.5, 2)):
            pixels = subprocess.check_output([shutil.which("ffmpeg"), "-v", "error", "-ss", str(time), "-i", str(path), "-frames:v", "1", "-vf", "crop=2:2:160:130", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
            self.assertGreater(pixels[channel], 170)
            self.assertLess(pixels[2 if channel == 0 else 0], 60)
        pcm = subprocess.check_output([shutil.which("ffmpeg"), "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "48000", "-f", "s16le", "-"])
        values = array.array("h"); values.frombytes(pcm)
        def rms(start, end):
            values_slice = values[int(start*48000):int(end*48000)]
            return math.sqrt(sum(v*v for v in values_slice) / len(values_slice))
        self.assertLess(rms(0.1, 0.3), 30)
        self.assertGreater(rms(0.7, 0.9), 500)
        self.assertLess(rms(1.7, 1.9), 30)
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual([s["in_seconds"] for s in manifest["segments"]], [0.25, 0.25])
        self.assertFalse((Path(result["manifest_path"]).parent / "output.mp4").exists())
        count = len(self.r.snapshot()["media"])
        replay = self.render(op_id="actual-video")
        for key in ("render_id", "path", "sha256", "verification", "issues"):
            self.assertEqual(replay[key], result[key])
        self.assertEqual(len(self.r.snapshot()["media"]), count)
        with self.assertRaises(ConflictError):
            self.render(op_id="actual-video", preview=False)

    def test_missing_or_corrupt_source_refused_even_in_preview(self):
        self.fixture()
        media = next(m for m in self.r.snapshot()["media"] if m["media_id"] == "RED")
        (self.root / media["path"]).write_bytes(b"corrupt")
        with self.assertRaises(ValueError):
            self.render()
        self.assertFalse(any(a["kind"] == "render" for a in self.r.snapshot()["artifacts"]))

    def test_formal_test_or_unknown_rights_refused(self):
        self.fixture()
        with self.assertRaises(ValueError):
            self.render(preview=False)
        # Isolate the rights gate from the test-only gate without claiming a
        # real project or person: this exists only in a temporary fixture DB.
        project = self.r._project(); project["test_only"] = False
        self.r.db.execute("UPDATE settings SET value=? WHERE key='project'", (json.dumps(project),))
        with self.assertRaises(ConflictError):
            self.render(preview=False)

    def test_stale_dependencies_formal_refused_preview_retains_issue(self):
        self.fixture(audio=False, subtitles=False, rights=True)
        clip = self.r._artifact("CLIP1")
        self.save("CLIP1", "clip", clip["metadata"], [], base=1)
        project = self.r._project(); project["test_only"] = False
        self.r.db.execute("UPDATE settings SET value=? WHERE key='project'", (json.dumps(project),))
        with self.assertRaises(ConflictError):
            self.render(preview=False)
        result = self.render()
        self.assertEqual(result["registry_status"], "candidate")
        self.assertTrue(any(i["code"] == "old_version" for i in result["issues"]))

    def test_timeline_gap_refused_not_silently_concatenated(self):
        self.fixture(gap=True)
        with self.assertRaisesRegex(ValueError, "间隙或重叠"):
            self.render()

    def test_planned_music_never_becomes_actual_audio(self):
        self.fixture(audio=False, subtitles=False, planned=True)
        result = self.render()
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["audio_tracks"], [])
        self.assertTrue(any(i["code"] == "unfulfilled_plan" for i in result["issues"]))

    def test_lost_artifact_receipt_recovers_without_duplicate_video(self):
        self.fixture(audio=False, subtitles=False)
        original = self.r.dispatch
        tripped = False
        def interrupted(action, payload):
            nonlocal tripped
            result = original(action, payload)
            if action == "artifact.save" and payload.get("kind") == "render" and not tripped:
                tripped = True
                raise OSError("Simulated lost return after successful registry commit")
            return result
        with patch.object(self.r, "dispatch", interrupted), self.assertRaises(OSError):
            self.render(op_id="lost-receipt")
        result = self.render(op_id="lost-receipt")
        self.assertTrue(Path(result["path"]).exists())
        renders = [a for a in self.r.snapshot()["artifacts"] if a["kind"] == "render"]
        self.assertEqual(len(renders), 1)
        self.assertEqual(renders[0]["version"], 1)

    def test_completed_result_refreshes_readiness_after_upstream_change(self):
        self.fixture(audio=False, subtitles=False, rights=True)
        first = self.render(op_id="result-refresh")
        self.assertEqual(first["current_readiness"], "ready_for_review")
        clip = self.r._artifact("CLIP1")
        self.save("CLIP1", "clip", clip["metadata"], [], base=1)
        replay = self.render(op_id="result-refresh")
        self.assertEqual(replay["sha256"], first["sha256"])
        self.assertEqual(replay["status"], "historical_render_needs_review")
        self.assertEqual(replay["current_registry_status"], "candidate")
        self.assertEqual(replay["current_readiness"], "needs_review")
        self.assertTrue(any(i["code"] == "old_version" for i in replay["current_issues"]))
        self.assertEqual(replay["historical_issues"], [])

    def test_pending_candidate_preserves_approved_render_until_upstream_approval(self):
        self.fixture(audio=False, subtitles=False, rights=True)
        for aid in ("CLIP1", "CLIP2", "SEQUENCE", "FINAL"):
            self.approve(aid)
        first = self.render(op_id="approval-aware-render")
        clip = self.r._artifact("CLIP1")
        self.save("CLIP1", "clip", clip["metadata"], [], base=1)
        pending = self.render(op_id="approval-aware-render")
        self.assertEqual(pending["current_registry_status"], "candidate")
        self.assertEqual(pending["current_readiness"], "ready_for_review")
        self.assertEqual(pending["current_issues"], [])
        self.approve("CLIP1", 2)
        changed = self.render(op_id="approval-aware-render")
        self.assertEqual(changed["current_registry_status"], "candidate")
        self.assertEqual(changed["current_readiness"], "needs_review")
        self.assertEqual(changed["sha256"], first["sha256"])

    def test_lost_receipt_with_intervening_edit_replays_entire_request(self):
        self.fixture(audio=False, subtitles=False, rights=True)
        original = self.r.dispatch
        sent_requests = []
        def interrupted(action, payload):
            result = original(action, payload)
            if action == "artifact.save" and payload.get("kind") == "render":
                sent_requests.append(json.loads(json.dumps(payload)))
                raise OSError("Lost receipt after commit")
            return result
        with patch.object(self.r, "dispatch", interrupted), self.assertRaises(OSError):
            self.render(op_id="lost-then-edited")
        clip = self.r._artifact("CLIP1")
        self.save("CLIP1", "clip", clip["metadata"], [], base=1)
        def observe_replay(action, payload):
            if action == "artifact.save" and payload.get("kind") == "render":
                sent_requests.append(json.loads(json.dumps(payload)))
            return original(action, payload)
        with patch.object(self.r, "dispatch", observe_replay):
            recovered = self.render(op_id="lost-then-edited")
        self.assertEqual(sent_requests[0], sent_requests[1])
        self.assertEqual(recovered["current_registry_status"], "candidate")
        self.assertEqual(recovered["current_readiness"], "needs_review")
        self.assertTrue(recovered["current_issues"])
        self.assertEqual(len([a for a in self.r.snapshot()["artifacts"] if a["kind"] == "render"]), 1)

    def test_cli_refuses_unregistered_or_relative_roots_without_creation(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "render_final.py"
        import sys
        missing = self.root / "MISSING"
        for root in (str(missing), "relative-missing"):
            proc = subprocess.run([sys.executable, "-X", "utf8", str(script), "--root", root, "--final", "F", "--version", "1", "--op-id", "test", "--preview"], cwd=self.root, capture_output=True)
            self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(missing.exists())
        self.assertFalse((self.root / "relative-missing").exists())

    def test_source_video_audio_is_actually_retained(self):
        audio_video = self.root / "TEST_SOURCE_WITH_AUDIO.mp4"
        subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-n", "-i", str(self.red), "-stream_loop", "-1", "-i", str(self.tone), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-t", "1.5", str(audio_video)], check=True)
        self.call("media.register", media_id="AV", kind="video", path=str(audio_video), metadata={"test_only": True})
        self.save("C", "clip", {"source_media_id": "AV", "in_seconds": 0.25, "out_seconds": 1.25})
        self.save("SEQ", "sequence", {"clips": [dict(self.ref("C"), timeline_in_seconds=0)]}, [self.ref("C")])
        self.save("FINAL", "final", {"timeline": self.ref("SEQ"), "shots": [self.ref("C")], "music": [], "dialogue": [], "subtitles": [], "export_spec": {"width": 320, "height": 180, "fps": 24}}, [self.ref("SEQ"), self.ref("C")])
        result = self.render()
        pcm = subprocess.check_output([shutil.which("ffmpeg"), "-v", "error", "-i", result["path"], "-vn", "-ac", "1", "-ar", "48000", "-f", "s16le", "-"])
        values = array.array("h"); values.frombytes(pcm)
        self.assertGreater(math.sqrt(sum(v*v for v in values) / len(values)), 500)

    def test_completed_render_resolves_registered_copy_after_restore(self):
        self.fixture(audio=False, subtitles=False)
        result = self.render(op_id="restore-render")
        archive = self.base / (uuid.uuid4().hex + ".zip")
        restored_path = self.base / ("RESTORED_" + uuid.uuid4().hex)
        self.call("backup.create", destination=str(archive))
        self.call("backup.restore", source=str(archive), destination=str(restored_path))
        restored = Registry(restored_path)
        try:
            recovered = render_final(restored, dict(artifact_id="FINAL", version=1, op_id="restore-render", preview=True))
            self.assertTrue(Path(recovered["path"]).is_relative_to(restored_path))
            self.assertEqual(recovered["sha256"], result["sha256"])
            self.assertTrue(Path(recovered["manifest_path"]).is_file())
        finally:
            restored.close()

    def test_registered_media_recovery_after_restore_replays_original_request(self):
        self.fixture(audio=False, subtitles=False)
        import filmprod.render as renderer
        original_write = renderer._write
        tripped = False
        def interrupted_write(path, value):
            nonlocal tripped
            original_write(path, value)
            if Path(path).name == "state.json" and value.get("phase") == "registered" and not tripped:
                tripped = True
                raise OSError("Interrupted after media commit and durable registered state")
        with patch.object(renderer, "_write", interrupted_write), self.assertRaises(OSError) as caught:
            self.render(op_id="registered-restore")
        self.assertEqual(caught.exception.operation_outcome, "resumable")
        archive = self.base / (uuid.uuid4().hex + ".zip")
        destination = self.base / ("RESTORED_" + uuid.uuid4().hex)
        self.call("backup.create", destination=str(archive))
        self.call("backup.restore", source=str(archive), destination=str(destination))
        clone = Registry(destination)
        try:
            recovered = render_final(clone, {"artifact_id": "FINAL", "version": 1, "op_id": "registered-restore", "preview": True})
            self.assertTrue(Path(recovered["path"]).is_relative_to(destination))
            self.assertTrue(Path(recovered["path"]).is_file())
            job = Path(recovered["manifest_path"]).parent
            state = json.loads((job / "state.json").read_text(encoding="utf-8"))
            self.assertTrue(Path(state["pending_media_request"]["path"]).is_relative_to(self.root))
            self.assertEqual(len([m for m in clone.snapshot()["media"] if m["media_id"].startswith("RENDER-MEDIA-")]), 1)
        finally:
            clone.close()

    def test_uncommitted_media_intent_relocates_only_after_proving_no_commit(self):
        self.fixture(audio=False, subtitles=False)
        original = self.r.dispatch
        def stop_before_media(action, payload):
            if action == "media.register" and payload["media_id"].startswith("RENDER-MEDIA-"):
                raise OSError("Stopped before first media send")
            return original(action, payload)
        with patch.object(self.r, "dispatch", stop_before_media), self.assertRaises(OSError):
            self.render(op_id="unsent-media-restore")
        archive = self.base / (uuid.uuid4().hex + ".zip")
        destination = self.base / ("RESTORED_" + uuid.uuid4().hex)
        self.call("backup.create", destination=str(archive))
        self.call("backup.restore", source=str(archive), destination=str(destination))
        clone = Registry(destination)
        try:
            recovered = render_final(clone, {"artifact_id": "FINAL", "version": 1, "op_id": "unsent-media-restore", "preview": True})
            state = json.loads((Path(recovered["manifest_path"]).parent / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(len(state["media_request_relocations"]), 1)
            self.assertTrue(Path(state["pending_media_request"]["path"]).is_relative_to(destination))
            self.assertTrue(Path(recovered["path"]).is_file())
        finally:
            clone.close()

    def test_error_outcome_preflight_and_existing_operation_are_distinguished(self):
        self.fixture(audio=False, subtitles=False)
        with self.assertRaises(ValueError) as caught:
            self.render(op_id="formal-precheck", preview=False)
        self.assertEqual(caught.exception.operation_outcome, "failed_before_commit")
        self.assertFalse(any(m["media_id"].startswith("RENDER-MEDIA-") for m in self.r.snapshot()["media"]))
        with patch("filmprod.render._exe", side_effect=ValueError("ffmpeg absent")), self.assertRaises(ValueError) as caught:
            self.render(op_id="not-started")
        self.assertEqual(caught.exception.operation_outcome, "no_write")
        self.render(op_id="already-completed")
        with patch("filmprod.render._exe", side_effect=ValueError("ffmpeg absent")), self.assertRaises(ValueError) as caught:
            self.render(op_id="already-completed")
        self.assertEqual(caught.exception.operation_outcome, "resumable")

    def test_outcome_is_unknown_while_job_lock_cannot_be_acquired(self):
        op_id = "other-process-running"
        key = hashlib.sha256(op_id.encode()).hexdigest()[:24]
        job = self.r.internal / "render-jobs" / key
        job.mkdir(parents=True)
        with _job_lock(job / "operation.lock"):
            self.assertEqual(render_operation_outcome(self.r, {"op_id": op_id}), "unknown")

    def test_interrupted_encoding_without_output_is_still_unknown(self):
        op_id = "orphan-encoder-may-still-run"
        key = hashlib.sha256(op_id.encode()).hexdigest()[:24]
        job = self.r.internal / "render-jobs" / key
        job.mkdir(parents=True)
        (job / "state.json").write_text(json.dumps({"phase": "encoding"}), encoding="utf-8")
        self.assertFalse((job / "output.mp4").exists())
        self.assertEqual(render_operation_outcome(self.r, {"op_id": op_id}), "unknown")

    def test_unknown_orphan_encoding_does_not_launch_second_ffmpeg(self):
        self.fixture(audio=False, subtitles=False)
        import filmprod.render as renderer
        original_write = renderer._write
        class SimulatedParentExit(BaseException):
            pass
        def abruptly_exit(path, value):
            original_write(path, value)
            if Path(path).name == "state.json" and value.get("phase") == "encoding":
                raise SimulatedParentExit()
        with patch.object(renderer, "_write", abruptly_exit), self.assertRaises(SimulatedParentExit):
            self.render(op_id="unknown-encoder")
        with patch.object(renderer, "_run") as execute, self.assertRaises(ConflictError) as caught:
            self.render(op_id="unknown-encoder")
        self.assertEqual(caught.exception.operation_outcome, "unknown")
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()

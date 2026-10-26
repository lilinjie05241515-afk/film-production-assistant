"""Local synthetic images only. No real works or external media are accessed."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib

from filmprod.core import ConflictError, Registry
from filmprod.image_preview180 import import_image, preview_image, validate_image, _dimensions, _image_derivative, THUMBNAIL_BYTES
from filmprod.media120 import media_action, verified_original


def png(path, width=1280, height=720, color=(42, 100, 180, 125)):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    data += chunk(b"IDAT", zlib.compress((b"\0" + bytes(color) * width) * height)) + chunk(b"IEND", b"")
    path.write_bytes(data)
    return data


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires existing local FFmpeg")
class ImagePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="film-image180-test_only-")
        self.base = Path(self.temp.name)
        self.source = self.base / "synthetic.png"
        self.bytes = png(self.source)
        self.registry = Registry(self.base / "test_only-project")
        self.registry.dispatch("project.init", {"op_id": "init", "project_id": "TEST-IMAGE", "title": "Synthetic only", "test_only": True})
        self.request = {"op_id": "import", "media_id": "IMAGE-1", "path": str(self.source), "expected_project_id": "TEST-IMAGE", "metadata": {"title": "合成测试图片", "asset_type": "scene"}}

    def tearDown(self):
        self.registry.close()
        self.temp.cleanup()

    def test_original_bytes_alpha_resize_cache_rebuild_and_no_registry_writes(self):
        imported = import_image(self.registry, self.request)
        self.assertEqual(imported["preview_status"], "ready", imported)
        self.assertTrue(imported["path"].startswith("03-资产/图片原件/"))
        self.assertEqual(Path(imported["local_path"]).read_bytes(), self.bytes)
        self.assertEqual(self.source.read_bytes(), self.bytes)
        before = self.registry.snapshot()
        ro = Registry.open_readonly(self.registry.root)
        try:
            result = preview_image(ro, {"media_id": "IMAGE-1", "expected_project_id": "TEST-IMAGE"})
            self.assertTrue(result["cache_only"])
            self.assertFalse(result["read_only"])
            self.assertEqual(result["kind"], "image")
            for key, dimensions in (("thumbnail_data_uri", (480, 270)), ("preview_data_uri", (960, 540))):
                data = base64.b64decode(result[key].split(",", 1)[1])
                self.assertEqual(_dimensions(data)[1:], dimensions)
                self.assertEqual(data[25], 6)  # PNG RGBA retains transparency.
            files = list((ro.internal / "previews/images").glob("*.png"))
            self.assertEqual(len(files), 2)
            hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
            for path in files:
                path.unlink()
            rebuilt = preview_image(ro, {"media_id": "IMAGE-1"})
            self.assertEqual(rebuilt["preview_data_uri"], result["preview_data_uri"])
            for path in files:
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), hashes[path.name])
            files[0].write_bytes(b"corrupted cache")
            preview_image(ro, {"media_id": "IMAGE-1"})
            self.assertEqual(hashlib.sha256(files[0].read_bytes()).hexdigest(), hashes[files[0].name])
            thumb = preview_image(ro, {"media_id": "IMAGE-1", "thumbnail_only": True})
            self.assertIsNone(thumb["preview_data_uri"])
        finally:
            ro.close()
        after = self.registry.snapshot()
        for key in ("media", "events", "artifacts", "decisions", "masters"):
            self.assertEqual(before[key], after[key])
        self.assertEqual(Path(imported["local_path"]).read_bytes(), self.bytes)

    def test_no_upscale_small_image_and_common_jpeg_webp(self):
        png(self.source, 33, 21)
        imported = import_image(self.registry, self.request)
        result = preview_image(self.registry, {"media_id": "IMAGE-1"})
        self.assertEqual(_dimensions(base64.b64decode(result["preview_data_uri"].split(",", 1)[1]))[1:], (33, 21))
        for suffix in (".jpg", ".webp"):
            target = self.base / ("synthetic" + suffix)
            subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", str(self.source), "-frames:v", "1", "-y", str(target)], check=True, capture_output=True)
            result = import_image(self.registry, {**self.request, "op_id": "import-" + suffix[1:], "media_id": "IMAGE-" + suffix[1:], "path": str(target)})
            self.assertEqual(result["preview_status"], "ready", result)
            self.assertEqual(Path(result["local_path"]).read_bytes(), target.read_bytes())

    def test_replay_keeps_frozen_original_and_rejects_changed_parameters(self):
        first = import_image(self.registry, self.request)
        png(self.source, color=(200, 30, 10, 255))
        self.assertEqual(import_image(self.registry, self.request), first)
        with self.assertRaises(ConflictError):
            import_image(self.registry, {**self.request, "metadata": {"title": "another"}})
        self.assertEqual(len(self.registry.snapshot()["media"]), 1)

    def test_title_validation_matches_management_and_does_not_write_invalid_imports(self):
        for title in (" ", "bad\nname", "bad\x7fname", "x" * 501):
            with self.assertRaises(ValueError):
                import_image(self.registry, {**self.request, "metadata": {"title": title}})
        self.assertEqual(self.registry.snapshot()["media"], [])
        result = import_image(self.registry, {**self.request, "metadata": {"title": " " + "名" * 498 + " "}})
        self.assertEqual(result["metadata"]["title"], "名" * 498)

    def test_freeze_before_copy_failure_blocks_replacement_bytes(self):
        with patch("filmprod.image_preview180.shutil.copyfile", side_effect=OSError("synthetic interruption")):
            with self.assertRaises(OSError) as failed:
                import_image(self.registry, self.request)
        self.assertEqual(failed.exception.operation_outcome, "failed_before_commit")
        png(self.source, color=(200, 30, 10, 255))
        with self.assertRaisesRegex(ConflictError, "冻结"):
            import_image(self.registry, self.request)
        self.assertEqual(self.registry.snapshot()["media"], [])

    def test_interruption_after_staging_and_commit_replay_exact_original(self):
        real_dispatch = self.registry.dispatch
        for committed in (False, True):
            request = {**self.request, "op_id": "recover-" + str(committed), "media_id": "RECOVER-" + str(committed)}
            def interrupt(action, payload):
                if action == "media.register":
                    if committed:
                        real_dispatch(action, payload)
                    raise OSError("synthetic interruption")
                return real_dispatch(action, payload)
            with patch.object(self.registry, "dispatch", interrupt):
                with self.assertRaises(OSError):
                    import_image(self.registry, request)
            png(self.source, color=(200, 30, 10, 255))
            result = import_image(self.registry, request)
            # This operation must use its own staged bytes, never changed source.
            self.assertEqual(result["sha256"], result["metadata"]["probe_source_sha256"])
            self.assertEqual(import_image(self.registry, request), result)

    def test_invalid_images_oversize_and_wrong_extension_rejected_before_decode(self):
        self.source.write_bytes(b"not an image")
        with self.assertRaises(ValueError):
            import_image(self.registry, self.request)
        self.assertEqual(self.registry.snapshot()["media"], [])
        self.source.write_bytes(self.bytes[:-15])
        with self.assertRaises(ValueError):
            validate_image(self.source)
        # A huge declared size is rejected before running any subprocess.
        oversized = bytearray(self.bytes)
        oversized[16:24] = struct.pack(">II", 20000, 20000)
        self.source.write_bytes(oversized)
        with patch("filmprod.image_preview180.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "尺寸"):
                validate_image(self.source)
            run.assert_not_called()
        self.source.write_bytes(self.bytes)
        wrong = self.base / "synthetic.jpg"
        wrong.write_bytes(self.bytes)
        with self.assertRaisesRegex(ValueError, "扩展名"):
            validate_image(wrong)

    def test_hash_boundary_wrong_project_and_arbitrary_path_refused(self):
        item = import_image(self.registry, self.request)
        valid = media_action(self.registry, "original", {"media_id": "IMAGE-1", "expected_project_id": "TEST-IMAGE"})
        self.assertTrue(valid["hash_verified"])
        with self.assertRaises(ConflictError):
            media_action(self.registry, "original", {"media_id": "IMAGE-1", "expected_project_id": "OTHER"})
        with self.assertRaises(ValueError):
            media_action(self.registry, "original", {"media_id": "IMAGE-1", "path": str(self.source)})
        with self.assertRaises(ValueError):
            preview_image(self.registry, {"media_id": "IMAGE-1", "path": str(self.source)})
        record = self.registry._get("media", "media_id", "IMAGE-1")
        for path in (str(self.source), "../synthetic.png"):
            self.registry._put("media", "media_id", "IMAGE-1", {**record, "path": path})
            with self.assertRaises(ValueError):
                verified_original(self.registry, {"media_id": "IMAGE-1"})
        self.registry._put("media", "media_id", "IMAGE-1", record)
        Path(item["local_path"]).write_bytes(b"tampered original")
        with self.assertRaises(ConflictError):
            verified_original(self.registry, {"media_id": "IMAGE-1"})
        with self.assertRaises(ConflictError):
            preview_image(self.registry, {"media_id": "IMAGE-1"})

    def test_preview_failure_reports_original_saved_and_is_rebuildable(self):
        with patch("filmprod.image_preview180._image_derivative", side_effect=ValueError("synthetic cache failure")):
            result = import_image(self.registry, self.request)
        self.assertTrue(result["original_saved"])
        self.assertEqual(result["preview_status"], "unavailable")
        self.assertIn("synthetic cache failure", result["warning"])
        self.assertTrue(preview_image(self.registry, {"media_id": "IMAGE-1"})["preview_inline_available"])

    def test_postcommit_original_change_is_unknown_not_partial_success(self):
        def corrupt_original(registry, media, source, edge, limit):
            source.write_bytes(b"synthetic original changed during preview")
            raise ConflictError("synthetic original hash changed")
        with patch("filmprod.image_preview180._image_derivative", corrupt_original):
            with self.assertRaises(ConflictError) as failure:
                import_image(self.registry, self.request)
        self.assertEqual(failure.exception.operation_outcome, "unknown")
        self.assertEqual(len(self.registry.snapshot()["media"]), 1)
        self.assertIsNone(self.registry.db.execute("SELECT result FROM image_import_jobs WHERE op_id='import'").fetchone()[0])

    def test_concurrent_cache_generation_has_single_writer_and_clean_atomic_result(self):
        item = import_image(self.registry, self.request)
        for path in (self.registry.internal / "previews/images").glob("*"):
            path.unlink()
        media = self.registry._get("media", "media_id", "IMAGE-1")
        started, finish = threading.Event(), threading.Event()
        actual_run = subprocess.run
        def slow_run(*args, **kwargs):
            started.set()
            finish.wait(10)
            return actual_run(*args, **kwargs)
        with ThreadPoolExecutor(max_workers=2) as pool, patch("filmprod.image_preview180.subprocess.run", slow_run):
            first = pool.submit(_image_derivative, self.registry, media, Path(item["local_path"]), 480, THUMBNAIL_BYTES)
            self.assertTrue(started.wait(10))
            try:
                with self.assertRaises(ConflictError):
                    _image_derivative(self.registry, media, Path(item["local_path"]), 480, THUMBNAIL_BYTES)
            finally:
                finish.set()
            target = first.result(timeout=30)
        self.assertTrue(target.is_file())
        self.assertEqual(len(list(target.parent.glob("*"))), 2)
        self.assertEqual(_dimensions(target.read_bytes())[1:], (480, 270))


if __name__ == "__main__":
    unittest.main(verbosity=2)

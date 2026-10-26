"""Actual stdio protocol checks against isolated test_only synthetic media."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from filmprod.core import Registry
from filmprod.image_preview180 import _dimensions
from test_image_preview180 import png


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires existing local FFmpeg")
class MediaStdioTests(unittest.TestCase):
    def test_metadata_only_binary_and_verified_image_video_originals(self):
        with tempfile.TemporaryDirectory(prefix="film-media-stdio180-test_only-") as temp:
            base = Path(temp).resolve()
            source = base / "synthetic.png"
            original_bytes = png(source)
            video = base / "synthetic.mp4"
            subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=13", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(video)], check=True, capture_output=True)
            root = base / "test_only-project"
            registry = Registry(root)
            registry.dispatch("project.init", {"op_id": "init", "project_id": "TEST-STDIO-IMAGE", "title": "Synthetic only", "test_only": True})
            registry.close()
            def request(action, payload):
                return ("film_media", {"action": action, "payload": {"expected_project_id": "TEST-STDIO-IMAGE", **payload}})
            calls = [request("import_image", {"op_id": "import-image", "media_id": "I", "path": str(source), "metadata": {"title": "合成透明图片", "asset_type": "prop"}}),
                     request("preview_image", {"media_id": "I"}), request("original", {"media_id": "I"}),
                     request("preview_image", {"media_id": "I", "thumbnail_only": True}),
                     request("import", {"op_id": "import-video", "media_id": "V", "path": str(video), "kind": "take"}),
                     request("preview", {"media_id": "V"}), request("original", {"media_id": "V"}),
                     request("original", {"media_id": "I", "path": str(source)}),
                     request("preview_image", {"media_id": "I", "expected_project_id": "OTHER"}),
                     ("film_snapshot", {})]
            messages = [{"jsonrpc": "2.0", "id": i + 1, "method": "tools/call", "params": {"name": name, "arguments": {"root": str(root), **args}}} for i, (name, args) in enumerate(calls)]
            env = {**os.environ, "FILMPROD_CATALOG_PATH": str(base / "isolated-catalog.sqlite3"), "PYTHONDONTWRITEBYTECODE": "1"}
            process = subprocess.run([sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve().parents[1] / "plugin/mcp_server.py")],
                input="".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages), capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
            self.assertEqual(process.returncode, 0, process.stderr)
            rows = [json.loads(line)["result"] for line in process.stdout.splitlines()]
            self.assertEqual(len(rows), len(calls))
            for row in rows[:7]:
                self.assertFalse(row.get("isError"), row)
                self.assertNotIn("base64,", json.dumps(row["content"]))
                self.assertNotIn("base64,", json.dumps(row["structuredContent"]))
            self.assertTrue(rows[7]["isError"])
            self.assertTrue(rows[8]["isError"])
            image = rows[1]["_meta"]["media_preview"]
            self.assertEqual(image["kind"], "image")
            self.assertEqual(image["sha256"], rows[0]["structuredContent"]["sha256"])
            self.assertEqual(_dimensions(base64.b64decode(image["preview_data_uri"].split(",", 1)[1]))[1:], (960, 540))
            self.assertEqual(image["write_scope"], "preview_cache")
            self.assertFalse(image["read_only"])
            self.assertNotIn("preview_data_uri", rows[1]["structuredContent"])
            self.assertIsNone(rows[3]["_meta"]["media_preview"]["preview_data_uri"])
            for index, kind in ((2, "image"), (6, "video")):
                original = rows[index]["structuredContent"]
                self.assertEqual(original["kind"], kind)
                self.assertTrue(original["hash_verified"])
                self.assertEqual(original["project_id"], "TEST-STDIO-IMAGE")
                self.assertTrue(Path(original["local_path"]).is_relative_to(root))
                self.assertNotIn("_meta", rows[index])
            self.assertEqual(Path(rows[2]["structuredContent"]["local_path"]).read_bytes(), original_bytes)
            preview = rows[5]["_meta"]["media_preview"]
            self.assertEqual(preview["preview_kind"], "low_resolution_first_12_seconds")
            self.assertTrue(preview["preview_data_uri"].startswith("data:video/mp4;base64,"))
            derivative = base / "synthetic-video-preview.mp4"
            derivative.write_bytes(base64.b64decode(preview["preview_data_uri"].split(",", 1)[1]))
            duration = subprocess.check_output([shutil.which("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(derivative)], text=True)
            self.assertLessEqual(float(duration), 12.05)
            snapshot = rows[9]["structuredContent"]
            self.assertEqual(len(snapshot["media"]), 2)
            self.assertEqual(len(snapshot["events"]), 3)  # init and two registrations only
            self.assertEqual(snapshot["decisions"], [])
            self.assertEqual(snapshot["artifacts"], [])

    def test_import_error_reports_outcome_without_claiming_success(self):
        with tempfile.TemporaryDirectory(prefix="film-media-error180-test_only-") as temp:
            base = Path(temp).resolve()
            root = base / "test_only-project"
            registry = Registry(root)
            registry.dispatch("project.init", {"op_id": "init", "project_id": "TEST-ERROR", "title": "Synthetic only", "test_only": True})
            registry.close()
            source = base / "corrupt.png"
            source.write_bytes(b"synthetic invalid image")
            message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "film_media", "arguments": {"root": str(root), "action": "import_image", "payload": {"op_id": "bad-image", "media_id": "BAD", "path": str(source), "expected_project_id": "TEST-ERROR"}}}}
            env = {**os.environ, "FILMPROD_CATALOG_PATH": str(base / "catalog.sqlite3"), "PYTHONDONTWRITEBYTECODE": "1"}
            process = subprocess.run([sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve().parents[1] / "plugin/mcp_server.py")], input=json.dumps(message) + "\n", capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
            result = json.loads(process.stdout)["result"]
            self.assertTrue(result["isError"])
            self.assertEqual(result["structuredContent"]["error"]["operation_outcome"], "failed_before_commit")
            registry = Registry.open_readonly(root)
            try:
                self.assertEqual(registry.snapshot()["media"], [])
            finally:
                registry.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""HTTP boundary and real-registry workflow tests; no production data is loaded."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import DashboardServer
from filmprod.core import Registry


class DashboardHTTPTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "work").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="http-test-", dir=ROOT / "work")
        self.root = Path(self.temp.name) / "ORIGINAL_TEST"
        reg = Registry(self.root)
        reg.dispatch("project.init", {"op_id": "init", "project_id": "HTTP_TEST", "title": "原创 HTTP 测试", "test_only": True})
        reg.close()
        self.other_root = Path(self.temp.name) / "SECOND_ORIGINAL_TEST"
        reg = Registry(self.other_root)
        reg.dispatch("project.init", {"op_id": "init", "project_id": "SECOND_TEST", "title": "第二个原创 HTTP 测试", "test_only": True})
        reg.close()
        self.server = DashboardServer(("127.0.0.1", 0), [self.root, self.other_root])
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.port = self.server.server_port
        self.host = f"127.0.0.1:{self.port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=3)
        self.temp.cleanup()

    def request(self, path, body=None, headers=None, method=None):
        request_headers = {"Host": self.host}
        if body is not None:
            request_headers.update({"Content-Type": "application/json", "Origin": "http://" + self.host})
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_headers.update(headers or {})
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method or ("POST" if body is not None else "GET"), path, body, request_headers)
            response = conn.getresponse()
            content = response.read()
            data = json.loads(content) if response.getheader("Content-Type", "").startswith("application/json") else content.decode()
            return response.status, data, dict(response.getheaders())
        finally:
            conn.close()

    def dispatch(self, action, payload):
        return self.request("/api/dispatch", {"action": action, "payload": payload})

    def test_snapshot_and_static_assets(self):
        status, data, _ = self.request("/api/snapshot")
        self.assertEqual(status, 200)
        self.assertTrue(data["project"]["test_only"])
        self.assertFalse(data["capabilities"]["music_creation"])
        for path in ("/", "/app.js", "/styles.css"):
            status, body, headers = self.request(path)
            self.assertEqual(status, 200)
            self.assertGreater(len(body), 50)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_host_origin_and_path_boundaries(self):
        for headers in ({"Host": "attacker.example"}, {"Origin": "https://attacker.example"}, {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.request("/api/snapshot", headers=headers)[0], 403)
        navigation = {"Sec-Fetch-Site":"cross-site", "Sec-Fetch-Mode":"navigate", "Sec-Fetch-Dest":"document"}
        self.assertEqual(self.request("/", headers=navigation)[0], 200)
        self.assertEqual(self.request("/api/snapshot", headers=navigation)[0], 403)
        self.assertEqual(self.request("/", headers={**navigation, "Origin":"https://attacker.example"})[0], 403)
        self.assertEqual(self.request("/api/dispatch", method="POST")[0], 403)
        self.assertEqual(self.request("/../AGENTS.md")[0], 404)
        self.assertEqual(self.request("/api/snapshot?project=C:/Users/SYNTHETIC_TEST")[0], 400)
        self.assertEqual(self.dispatch("backup.restore", {"op_id": "bad", "source": "x", "destination": "y"})[0], 403)
        self.assertEqual(self.dispatch("media.register", {"op_id": "read", "path": "C:/private"})[0], 403)
        self.assertEqual(self.dispatch("decision.record", {"op_id": "adopt"})[0], 403)
        self.assertEqual(self.request("/api/dispatch", {"action":"task.resume","payload":{}}, {"Content-Type":"text/plain"})[0], 415)

    def test_legacy_business_mutations_rejected_and_exact_read_retained(self):
        reg = Registry(self.root)
        reg.dispatch("artifact.save", {"op_id":"seed", "artifact_id":"SC03", "kind":"screenplay", "scope":"scene/3", "content":"完整合成正文", "base_version":0, "deps":[], "metadata":{}})
        before = list(reg.db.iterdump())
        reg.close()
        for action in ("artifact.save", "artifact.restore", "task.create", "task.checkpoint", "task.submit", "thread.register", "cue.save", "content.approve", "project.workflow.set"):
            self.assertEqual(self.dispatch(action, {"op_id":"forbidden"})[0], 403, action)
        status, original, _ = self.dispatch("artifact.get", {"artifact_id":"SC03", "version":1})
        self.assertEqual(status, 200)
        self.assertEqual(original["content"], "完整合成正文")
        reg = Registry.open_readonly(self.root)
        self.assertEqual(before, list(reg.db.iterdump()))
        reg.close()

    def test_registered_project_switching(self):
        status, payload, _ = self.request("/api/projects")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["projects"]), 2)
        key = payload["projects"][0]["key"]
        self.assertEqual(self.request("/api/snapshot?project=" + key)[1]["project"]["project_id"], "HTTP_TEST")
        other = payload["projects"][1]["key"]
        self.assertEqual(self.request("/api/snapshot?project=" + other)[1]["project"]["project_id"], "SECOND_TEST")
        create = {"action":"task.create", "payload":{"op_id":"other-task", "task_id":"OTHER-TASK", "title":"第二项目任务", "module":"review", "scope":"other/review", "inputs":[], "must_keep":["原文"], "allowed_changes":[], "requirements":["审查"]}}
        self.assertEqual(self.request("/api/dispatch?project=" + other, create)[0], 403)
        self.assertEqual(len(self.request("/api/snapshot?project=" + key)[1]["tasks"]), 0)
        self.assertEqual(len(self.request("/api/snapshot?project=" + other)[1]["tasks"]), 0)
        self.assertEqual(self.request("/api/snapshot?project=" + key + "&project=other")[0], 400)


if __name__ == "__main__":
    unittest.main()

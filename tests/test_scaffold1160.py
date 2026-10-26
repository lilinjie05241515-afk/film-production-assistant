"""Synthetic TEST fixtures only; no real project reads or host mutations."""
import importlib.util
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "skills/film-production-agent/scripts/scaffold_project.py"
spec = importlib.util.spec_from_file_location("scaffold", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ID = "TEST-FILM-WORKSPACE"


class ScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="film-scaffold-TEST-")
        self.root = Path(self.tmp.name) / "project"
        (self.root / ".project").mkdir(parents=True)
        self.db_path = self.root / ".project/registry.sqlite3"
        self.workspace = {"revision": 7, "prepared": True, "initialization_id": "TEST-init", "slots": [
            {"slot_id": "TEST-control", "project_id": ID, "role": "control", "scope": "project",
             "title": "TEST 总控", "thread_id": "TEST-real-thread", "client_thread_id": None,
             "status": "associated_observed", "catalog_binding_status": "host_reported_bound",
             "client_project_id": None, "client_project_status": "host_reported_projectless",
             "host_observation": {"thread_id": "TEST-real-thread", "observed_at": "2026-10-27T00:00:00+08:00"},
             "observations": []},
            {"slot_id": "TEST-script", "project_id": ID, "role": "script", "scope": "project",
             "title": "TEST 编剧", "thread_id": None, "client_thread_id": "TEST-queued-client",
             "status": "queued", "host_observation": None, "observations": []},
        ]}
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)")
            db.executemany("INSERT INTO settings VALUES(?,?)", [
                ("schema_version", "2"), ("project", json.dumps({"project_id": ID, "title": "TEST 合成作品", "test_only": True, "workflow": {"mode": "screenplay"}})),
                ("workspace/v1", json.dumps(self.workspace)),
            ])
            db.commit()

    def tearDown(self):
        self.tmp.cleanup()

    def run_scaffold(self, expected=ID):
        return module.scaffold(str(self.root), expected)

    def index(self):
        return json.loads((self.root / module.INDEX / "对话索引.json").read_text("utf-8"))

    def test_idempotence_and_registry_unchanged(self):
        db_before = self.db_path.read_bytes()
        first = self.run_scaffold()
        self.assertTrue(first["changed_files"])
        second = self.run_scaffold()
        self.assertEqual([], second["changed_files"])
        self.assertEqual([], second["created_directories"])
        self.assertEqual(db_before, self.db_path.read_bytes())
        self.assertFalse((self.root / "01-故事与剧本/小说").exists())

    def test_wrong_identity_no_output(self):
        with self.assertRaisesRegex(ValueError, "身份不符"):
            self.run_scaffold("TEST-other")
        self.assertEqual([".project"], [p.name for p in self.root.iterdir()])

    def test_relocated_bundle_finds_its_own_rules_and_creates_no_install_path_reference(self):
        skill = Path(self.tmp.name) / "relocated-plugin/skills/film-production-agent"
        relocated = skill / "scripts/scaffold_project.py"
        relocated.parent.mkdir(parents=True)
        rules = skill / "references/project-bootstrap.md"
        rules.parent.mkdir()
        shutil.copy2(SCRIPT, relocated)
        shutil.copy2(module.RULES, rules)
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(relocated),
                                 "--root", str(self.root), "--expected-project-id", ID],
                                cwd=self.tmp.name, capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertFalse(receipt["registry_written"])
        self.assertFalse(receipt["host_chats_created"])
        agents = (self.root / "AGENTS.md").read_text("utf-8")
        self.assertNotIn(str(SCRIPT.parent), agents)
        self.assertNotIn(str(skill), agents)
        self.assertIn("references/project-bootstrap.md", agents)

    def test_incomplete_bundle_refuses_before_writing_project(self):
        relocated = Path(self.tmp.name) / "incomplete-plugin/scripts/scaffold_project.py"
        relocated.parent.mkdir(parents=True)
        shutil.copy2(SCRIPT, relocated)
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(relocated),
                                 "--root", str(self.root), "--expected-project-id", ID],
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(1, result.returncode)
        self.assertIn("缺少包内", result.stderr)
        self.assertEqual([".project"], [p.name for p in self.root.iterdir()])

    def test_unknown_schema_no_output(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute("UPDATE settings SET value='99' WHERE key='schema_version'")
            db.commit()
        with self.assertRaisesRegex(ValueError, "schema_version"):
            self.run_scaffold()
        self.assertEqual([".project"], [p.name for p in self.root.iterdir()])

    def test_preserve_user_agents_bytes_and_append(self):
        original = b"\xef\xbb\xbf# My rules\r\nKeep my CRLF.\r\n"
        agents = self.root / "AGENTS.md"
        agents.write_bytes(original)
        self.run_scaffold()
        self.assertTrue(agents.read_bytes().startswith(original))
        agents.write_bytes(agents.read_bytes() + b"\r\nNew user rule.\r\n")
        self.run_scaffold()
        self.assertTrue(agents.read_bytes().endswith(b"\r\nNew user rule.\r\n"))

    def test_queued_has_no_chat_link_and_null_client_is_retained(self):
        self.run_scaffold()
        slots = self.index()["slots"]
        self.assertEqual(None, slots[1]["chat_url"])
        self.assertEqual(None, slots[1]["thread_id"])
        self.assertEqual("TEST-queued-client", slots[1]["client_thread_id"])
        self.assertEqual(None, slots[0]["client_project_id"])
        self.assertEqual("host_reported_projectless", slots[0]["client_project_status"])

    def test_unknown_has_no_chat_link(self):
        self.workspace["slots"][1].update(status="unknown", client_thread_id=None)
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute("UPDATE settings SET value=? WHERE key='workspace/v1'", (json.dumps(self.workspace),))
            db.commit()
        self.run_scaffold()
        self.assertIsNone(self.index()["slots"][1]["chat_url"])

    def test_unknown_reason_survives_without_observed_time_and_success_clears_current(self):
        slot = self.workspace["slots"][1]
        slot.update(status="unknown", observations=[{"event": "unknown", "recorded_at": "2026-10-27T01:00:00+08:00",
                    "observation": {"reason": "创建返回中断，尚未取得真实聊天 ID；核查原请求，禁止重建"}}])
        def save():
            with closing(sqlite3.connect(self.db_path)) as db:
                db.execute("UPDATE settings SET value=? WHERE key='workspace/v1'", (json.dumps(self.workspace),))
                db.commit()
        save()
        self.run_scaffold()
        self.assertEqual("unknown", self.index()["slots"][1]["pending_reason"]["event"])
        self.assertIn("禁止重建", (self.root / module.INDEX / "对话索引.md").read_text("utf-8"))
        slot.update(status="associated_observed", thread_id="TEST-recovered", client_thread_id=None,
                    host_observation={"thread_id": "TEST-recovered", "observed_at": "2026-10-27T02:00:00+08:00"})
        slot["observations"].append({"event": "host_confirmed", "observation": slot["host_observation"]})
        self.workspace["revision"] += 1
        save()
        self.run_scaffold()
        self.assertIsNone(self.index()["slots"][1]["pending_reason"])
        self.assertIn("禁止重建", self.index()["slots"][1]["observations"][0]["reason"])
        self.assertNotIn("禁止重建", (self.root / module.INDEX / "对话索引.md").read_text("utf-8"))

    def test_index_manual_edits_are_not_overwritten(self):
        self.run_scaffold()
        index = self.root / module.INDEX / "对话索引.md"
        content = index.read_bytes() + "\n用户手改保留。".encode()
        index.write_bytes(content)
        with self.assertRaisesRegex(ValueError, "外部修改"):
            self.run_scaffold()
        self.assertEqual(content, index.read_bytes())

    def test_managed_block_edit_is_not_overwritten(self):
        self.run_scaffold()
        agents = self.root / "AGENTS.md"
        content = agents.read_bytes().replace("项目 ID".encode(), "手改项目 ID".encode())
        agents.write_bytes(content)
        with self.assertRaisesRegex(ValueError, "管理区已有外部修改"):
            self.run_scaffold()
        self.assertEqual(content, agents.read_bytes())

    def test_file_at_directory_preflight_creates_nothing(self):
        (self.root / "07-成片").write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "不是目录"):
            self.run_scaffold()
        self.assertFalse((self.root / "00-设定与依据").exists())

    def test_link_destination_rejected(self):
        target = Path(self.tmp.name) / "outside"
        target.mkdir()
        link = self.root / "03-资产"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            # Windows directory junction does not need symlink privilege.
            quote = lambda path: "'" + str(path).replace("'", "''") + "'"
            result = subprocess.run(["powershell", "-NoProfile", "-Command",
                f"New-Item -ItemType Junction -Path {quote(link)} -Target {quote(target)} -ErrorAction Stop | Out-Null"], capture_output=True)
            if result.returncode:
                self.skipTest("Host cannot create a synthetic link/junction")
        try:
            with self.assertRaisesRegex(ValueError, "链接或重解析"):
                self.run_scaffold()
            self.assertEqual([], list(target.iterdir()))
            self.assertFalse((self.root / "00-设定与依据").exists())
        finally:
            # Unlink only the synthetic link; never recurse into its target.
            try:
                link.unlink()
            except OSError:
                link.rmdir()


if __name__ == "__main__":
    unittest.main()

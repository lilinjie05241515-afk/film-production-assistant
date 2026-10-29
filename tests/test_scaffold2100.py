"""Synthetic-only navigation: submission, completion and reports stay distinct."""
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "scaffold2100", SOURCE / "skills/film-production-agent/scripts/scaffold_project.py")
scaffold = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scaffold)


class ScaffoldProgress2100Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="film-scaffold2100-TEST-")
        self.root = Path(self.temporary.name)
        (self.root / ".project").mkdir()
        self.database = self.root / ".project/registry.sqlite3"
        self.output = {"artifact_id": "TEST-DIRECTOR-OUTPUT", "version": 1}
        self.topic = {"topic_id": "TEST-TOPIC", "kind": "execution", "title": "TEST 导演执行",
                      "scope": "TEST-director", "parent_role": "director", "parent_thread_id": "TEST-DIRECTOR",
                      "thread_id": "TEST-EXECUTOR", "task_id": "TEST-TASK", "status": "task_bound", "round": 1,
                      "brief": "PRIVATE-TEST-PROMPT"}
        self.state = {"revision": 8, "enabled": True, "parents": {
            "control": {"thread_id": "TEST-CONTROL", "title": "TEST 总控"},
            "director": {"thread_id": "TEST-DIRECTOR", "title": "TEST 导演总控"}},
            "topics": [self.topic], "handoffs": [], "outbox": [],
            "authorization": {"quote": "PRIVATE-TEST-AUTHORIZATION"}}
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)")
            db.execute("CREATE TABLE tasks(task_id TEXT PRIMARY KEY,data TEXT NOT NULL)")
            db.executemany("INSERT INTO settings VALUES (?,?)", [(key, json.dumps(value, ensure_ascii=False)) for key, value in {
                "schema_version": 2, "project": {"project_id": "TEST-2100", "title": "TEST 合成项目",
                                                  "test_only": True, "workflow": {"mode": "screenplay"}},
                "workspace/v1": {"revision": 1, "slots": []}, "conversation/v1": self.state}.items()])
            db.execute("INSERT INTO tasks VALUES (?,?)", ("TEST-TASK", json.dumps({
                "task_id": "TEST-TASK", "status": "submitted", "output": self.output,
                "requirements": "PRIVATE-TEST-TASK-REQUIREMENTS"})))
            db.commit()

    def tearDown(self):
        self.temporary.cleanup()

    def save_state(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("UPDATE settings SET value=? WHERE key='conversation/v1'", (json.dumps(self.state),))
            db.commit()

    def run_index(self):
        original = self.database.read_bytes()
        scaffold.scaffold(str(self.root), "TEST-2100")
        self.assertEqual(original, self.database.read_bytes())
        directory = self.root / scaffold.INDEX
        text = (directory / "对话索引.json").read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE-", text)
        return json.loads(text)["conversations"]["topics"][0], (directory / "对话索引.md").read_text(encoding="utf-8")

    def mark_completed(self):
        self.topic.update(status="completed", completed_at="2026-10-30T00:00:00+08:00", output_ref=self.output)
        self.save_state()

    def test_submitted_task_is_visible_without_rewriting_topic_status(self):
        topic, markdown = self.run_index()
        self.assertEqual("task_bound", topic["status"])
        self.assertEqual("submitted", topic["task_status"])
        self.assertEqual(self.output, topic["task_output_ref"])
        self.assertTrue(topic["needs_completion_record"])
        self.assertFalse(topic["completion_recorded"])
        self.assertEqual("not_ready", topic["report_status"])
        self.assertIn("已提交候选", markdown)
        self.assertIn("待补完成登记", markdown)

    def test_recorded_completion_does_not_imply_authorized_or_sent_report(self):
        self.mark_completed()
        topic, markdown = self.run_index()
        self.assertTrue(topic["completion_recorded"])
        self.assertFalse(topic["needs_completion_record"])
        self.assertEqual("pending_authorization", topic["report_status"])
        self.assertEqual({"TEST-DIRECTOR", "TEST-CONTROL"}, {r["thread_id"] for r in topic["report_recipients"]})
        self.assertIn("回报待处理：需授权", markdown)

    def test_host_acceptance_stays_separate_from_business_reading(self):
        self.mark_completed()
        self.state["outbox"] = [{"request_id": "TEST-REPORT-" + recipient, "topic_id": "TEST-TOPIC",
            "tool": "send_message_to_thread", "purpose": "completion-1-TEST-TASK", "status": "host_accepted",
            "target_thread_id": recipient} for recipient in ("TEST-DIRECTOR", "TEST-CONTROL")]
        self.save_state()
        topic, markdown = self.run_index()
        self.assertEqual("host_accepted", topic["report_status"])
        self.assertTrue(all(r["business_processed"] is False for r in topic["report_recipients"]))
        self.assertIn("宿主已受理，业务读取待核", markdown)

    def test_missing_task_remains_unknown_and_repeat_is_stable(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("DELETE FROM tasks")
            db.commit()
        topic, _ = self.run_index()
        self.assertIsNone(topic["task_status"])
        self.assertIsNone(topic["task_output_ref"])
        self.assertFalse(topic["completion_recorded"])
        self.assertFalse(topic["needs_completion_record"])
        first = (self.root / scaffold.INDEX / "对话索引.json").read_bytes()
        self.run_index()
        self.assertEqual(first, (self.root / scaffold.INDEX / "对话索引.json").read_bytes())
        rules = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("当前登记职责优先", rules)


if __name__ == "__main__":
    unittest.main()

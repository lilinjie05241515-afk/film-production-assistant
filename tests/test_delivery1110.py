"""Synthetic evidence tests; no test claims creative quality or real approval."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from filmprod.core import Registry, ConflictError, content_hash
from filmprod.delivery1110 import action_schemas, delivery_summary


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="filmprod-TEST-delivery1110-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "TEST-project"
        self.r = Registry(self.root)
        self.addCleanup(self.r.close)
        self.call("project.init", project_id="TEST-DELIVERY", title="TEST 合成完整成稿证据", test_only=True)
        self.source_text = "甲推开门。\n乙后退一步。\n甲停手，问：你受伤了吗？\n乙点头，将药盒递过去。"
        self.source = self.save("SOURCE", self.source_text, kind="novel", scope="chapter/1")
        self.target = self.save("DRAFT", self.source_text)
        self.request = {"reference": "synthetic:user:turn-1", "quote": "完整改编这一场，保留开门、后退、停手问话及递药盒的过程。"}

    def call(self, action, **payload):
        if action != "project.init":
            payload.setdefault("expected_project_id", "TEST-DELIVERY")
        if not action.endswith(".read"):
            payload.setdefault("op_id", uuid.uuid4().hex)
        return self.r.dispatch(action, payload)

    def save(self, aid, body, version=0, kind="script", scope="episode/1"):
        return self.call("artifact.save", artifact_id=aid, base_version=version, content=body, kind=kind, scope=scope)["artifact"]

    def ref(self, artifact):
        return {key: artifact[key] for key in ("artifact_id", "version", "sha256")}

    def definition(self):
        return {"delivery_id": "DELIVERY", "base_revision": 0, "target_artifact_id": "DRAFT", "scope": "episode/1",
                "granularity": "本场逐次动作、回应与问话过程；不增加无关场次", "user_request": deepcopy(self.request),
                "inputs": [self.ref(self.source)], "units": [
                    {"unit_id": "U" + str(index), "description": line, "source": {"type": "artifact", **self.ref(self.source), "location": "原文第" + str(index) + "行", "quote": line}}
                    for index, line in enumerate(self.source_text.splitlines(), 1)]}

    def define(self, **changes):
        payload = self.definition()
        payload.update(changes)
        return self.call("delivery.define", **payload)

    def review_payload(self, artifact=None):
        artifact = artifact or self.target
        return {"delivery_id": "DELIVERY", "revision": 1, "base_review_revision": 0, "artifact": self.ref(artifact),
                "author": {"type": "host_agent", "id": "TEST-writer"},
                "reviewer": {"type": "host_subagent", "id": "TEST-independent-reviewer", "source_reference": "synthetic:spawn:test-reviewer"},
                "coverage": [{"unit_id": "U" + str(index), "status": "covered", "output": {"location": "成稿第" + str(index) + "行", "quote": line}, "note": "合成复核：本单元在正文中有对应过程"}
                             for index, line in enumerate(self.source_text.splitlines(), 1)], "findings": []}

    def review(self, **changes):
        payload = self.review_payload()
        payload.update(changes)
        return self.call("delivery.review", **payload)

    def complete(self, review, **changes):
        payload = {"delivery_id": "DELIVERY", "revision": review["revision"], "review_id": review["review_id"],
                   "artifact": review["artifact"], "base_completion_revision": review["completion_revision"]}
        payload.update(changes)
        return self.call("delivery.complete", **payload)

    def read(self):
        return self.call("delivery.read", delivery_id="DELIVERY")

    def test_full_flow_is_evidence_completion_not_approval(self):
        definition = self.define()
        self.assertEqual(definition["mode"], "full")
        self.assertEqual(definition["status"], "incomplete")
        review = self.review()
        self.assertEqual(review["status"], "reviewed")
        self.assertFalse(review["ready_for_delivery"])
        result = self.complete(review)
        self.assertTrue(result["ready_for_delivery"])
        self.assertFalse(result["quality_guaranteed"])
        self.assertFalse(result["approval_changed"])
        self.assertEqual(result["latest_review"]["independence_evidence"], "host_reported_unverified")
        self.assertEqual(self.r._artifact("DRAFT")["status"], "candidate")
        self.assertEqual(self.r.db.execute("SELECT COUNT(*) FROM approved_segments").fetchone()[0], 0)
        summaries = self.call("delivery.read")
        self.assertTrue(summaries["items"][0]["ready_for_delivery"])
        self.assertNotIn("quote", json.dumps(summaries, ensure_ascii=False))
        self.assertNotIn("contract", summaries["items"][0])

    def test_compressed_candidate_with_missing_process_cannot_complete(self):
        self.target = self.save("DRAFT", "甲乙在门口交谈，甲拿到药盒。", version=1)
        self.define()
        coverage = [{"unit_id": "U1", "status": "needs_revision", "output": {"location": "概括句", "quote": self.target["content"]},
                     "note": "只概括交谈，未展开开门、后退与停手问话"},
                    {"unit_id": "U4", "status": "missing", "note": "正文没有乙点头和递药盒的可见过程"}]
        review = self.review(artifact=self.ref(self.target), coverage=coverage)
        self.assertEqual(review["status"], "incomplete")
        self.assertEqual(review["missing_units"], ["U2", "U3", "U4"])
        with self.assertRaises(ConflictError):
            self.complete(review)
        self.assertEqual(self.r._artifact("DRAFT")["content"], self.target["content"])
        self.assertFalse(self.read()["ready_for_delivery"])

    def test_quote_presence_is_verified_and_self_certification_rejected(self):
        self.define()
        payload = self.review_payload()
        payload["coverage"][0]["output"]["quote"] = "成稿不存在的精细过程"
        with self.assertRaises(ValueError):
            self.call("delivery.review", **payload)
        payload = self.review_payload()
        payload["reviewer"]["id"] = payload["author"]["id"]
        with self.assertRaises(ValueError):
            self.call("delivery.review", **payload)
        payload = self.review_payload()
        payload["reviewer"]["independent"] = True
        with self.assertRaises(ValueError):
            self.call("delivery.review", **payload)
        self.assertEqual(self.read()["review_revision"], 0)

    def test_summary_requires_frozen_user_quote_and_request_units_are_bound(self):
        with self.assertRaises(ValueError):
            self.define(mode="summary")
        with self.assertRaises(ValueError):
            self.define(mode="summary", summary_request={"actor": "user", "reference": self.request["reference"], "quote": "只写摘要"})
        request = {"reference": "synthetic:user:summary", "quote": "这次只要摘要，保留主要事件。"}
        payload = self.definition()
        payload.update(mode="summary", user_request=request, summary_request={"actor": "user", **request}, inputs=[],
                       units=[{"unit_id": "U1", "description": "主要事件概述", "source": {"type": "user_request", "reference": request["reference"], "quote": "保留主要事件"}}])
        result = self.call("delivery.define", **payload)
        self.assertEqual(result["mode"], "summary")
        self.assertEqual(result["contract"]["request_authenticity"], "host_reported_unverified")
        payload["base_revision"] = 1
        payload["units"][0]["source"]["quote"] = "用户没说的话"
        with self.assertRaises(ValueError):
            self.call("delivery.define", **payload)

    def test_hash_project_and_target_identity_rejected(self):
        payload = self.definition()
        payload["inputs"][0]["sha256"] = "0" * 64
        with self.assertRaises(ConflictError):
            self.call("delivery.define", **payload)
        self.define()
        with self.assertRaises(ConflictError):
            self.call("delivery.read", expected_project_id="WRONG", delivery_id="DELIVERY")
        with self.assertRaises(ConflictError):
            self.review(expected_project_id="WRONG")
        payload = self.review_payload()
        payload["artifact"]["sha256"] = "0" * 64
        with self.assertRaises(ConflictError):
            self.call("delivery.review", **payload)
        payload["artifact"] = self.ref(self.source)
        with self.assertRaises(ConflictError):
            self.call("delivery.review", **payload)
        self.assertEqual(self.read()["review_revision"], 0)

    def test_new_body_invalidates_prior_completion_and_keeps_history(self):
        self.define()
        review = self.review()
        self.complete(review)
        self.target = self.save("DRAFT", self.source_text + "\n门外又响起脚步。", version=1)
        result = self.read()
        self.assertFalse(result["ready_for_delivery"])
        self.assertEqual(result["review_state"], "stale")
        self.assertIn("artifact_updated", result["stale_reasons"])
        self.assertEqual(result["history"]["review_ids"], [review["review_id"]])
        with self.assertRaises(ConflictError):
            self.complete(review, base_completion_revision=1)
        revised = self.review(artifact=self.ref(self.target), base_review_revision=1)
        self.assertTrue(self.complete(revised)["ready_for_delivery"])

    def test_definition_and_input_updates_expire_review(self):
        self.define()
        review = self.review()
        self.complete(review)
        self.define(base_revision=1, granularity="本场完整过程，加核物件交接")
        self.assertIn("contract_updated", self.read()["stale_reasons"])
        self.assertEqual(self.read()["history"]["definition_revisions"], [1, 2])
        refreshed = self.review(revision=2, base_review_revision=1)
        self.complete(refreshed)
        self.source = self.save("SOURCE", self.source_text + "\n新底本的额外行。", version=1, kind="novel", scope="chapter/1")
        result = self.read()
        self.assertFalse(result["ready_for_delivery"])
        self.assertIn("input_updated:SOURCE", result["stale_reasons"])
        with self.assertRaises(ConflictError):
            self.complete(refreshed, base_completion_revision=2)

    def test_open_blocker_is_carried_until_explicit_resolution(self):
        self.define()
        finding = {"finding_id": "F1", "severity": "blocking", "status": "open", "location": "第2行", "quote": "乙后退一步。", "detail": "合成待返修事项"}
        first = self.review(findings=[finding])
        self.assertEqual(first["status"], "needs_revision")
        with self.assertRaises(ConflictError):
            self.complete(first)
        second = self.review(base_review_revision=1, findings=[])
        self.assertEqual(second["blocking_findings"], ["F1"])
        with self.assertRaises(ConflictError):
            self.complete(second)
        weaker = dict(finding, severity="minor")
        with self.assertRaises(ValueError):
            self.review(base_review_revision=2, findings=[weaker])
        resolved = dict(finding, status="resolved", resolution={"location": "第2行", "quote": "乙后退一步。", "explanation": "合成重新核查：明确已核实此项并给出对应证据"})
        third = self.review(base_review_revision=2, findings=[resolved])
        self.assertEqual(third["blocking_findings"], [])
        self.assertTrue(self.complete(third)["ready_for_delivery"])

    def test_definition_review_completion_cas_and_operation_idempotency(self):
        definition = self.define(op_id="DEFINE-ONCE")
        self.assertEqual(definition, self.define(op_id="DEFINE-ONCE"))
        with self.assertRaises(ConflictError):
            self.define()
        review = self.review(op_id="REVIEW-ONCE")
        self.assertEqual(review, self.review(op_id="REVIEW-ONCE"))
        with self.assertRaises(ConflictError):
            self.review()
        completed = self.complete(review, op_id="COMPLETE-ONCE")
        self.assertEqual(completed, self.complete(review, op_id="COMPLETE-ONCE"))
        with self.assertRaises(ConflictError):
            self.complete(review)
        with self.assertRaises(ConflictError):
            self.define(op_id="DEFINE-ONCE", granularity="不同请求")
        self.save("DRAFT", self.source_text + "\n新候选", version=1)
        # Exact replay is the original receipt, not a claim of current freshness.
        self.assertEqual(completed, self.complete(review, op_id="COMPLETE-ONCE"))
        self.assertFalse(self.read()["ready_for_delivery"])

    def test_local_sentence_revision_can_freeze_original_target(self):
        request = {"reference": "synthetic:user:local", "quote": "只把第一句开门动作写清楚，其他句子保留。"}
        result = self.define(user_request=request, inputs=[self.ref(self.target)], granularity="只核第一句局部动作及其承接",
                             units=[{"unit_id": "U1", "description": "第一句开门动作", "source": {"type": "artifact", **self.ref(self.target), "location": "原稿第1句", "quote": "甲推开门。"}}])
        self.assertEqual(len(result["contract"]["units"]), 1)
        self.target = self.save("DRAFT", self.source_text.replace("甲推开门。", "甲掌心抵住门板，推开门。"), version=1)
        review = self.review(artifact=self.ref(self.target), coverage=[{"unit_id": "U1", "status": "covered", "output": {"location": "第1句", "quote": "甲掌心抵住门板，推开门。"}, "note": "只核当前授权局部范围"}])
        self.assertEqual(review["status"], "reviewed")
        self.assertTrue(self.complete(review)["ready_for_delivery"])

    def test_read_only_reopen_and_schema_contracts(self):
        self.define()
        read_only = Registry.open_readonly(self.root)
        try:
            result = read_only.dispatch("delivery.read", {"expected_project_id": "TEST-DELIVERY"})
            self.assertEqual(result["items"][0]["delivery_id"], "DELIVERY")
            with self.assertRaises(ValueError):
                read_only.dispatch("delivery.define", {**self.definition(), "op_id": "READONLY", "expected_project_id": "TEST-DELIVERY"})
        finally:
            read_only.close()
        self.assertEqual(delivery_summary(self.r)["items"][0]["mode"], "full")
        schemas = action_schemas()
        self.assertEqual(set(schemas), {"delivery.read", "delivery.define", "delivery.review", "delivery.complete"})
        for schema in schemas.values():
            self.assertFalse(schema["additionalProperties"])
            self.assertIn("expected_project_id", schema["required"])
        schemas["delivery.read"]["properties"].clear()
        self.assertIn("expected_project_id", action_schemas()["delivery.read"]["properties"])


if __name__ == "__main__":
    unittest.main()

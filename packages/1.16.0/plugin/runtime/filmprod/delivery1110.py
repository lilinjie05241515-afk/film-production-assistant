"""Version-bound delivery evidence, not creative-quality or approval automation.

Registry.dispatch owns write transactions, project identity, operation caching and
events. Definitions, reviews and completions are immutable append-only records in
settings. Freshness is derived on read; no approved artifact is ever changed.
"""
from copy import deepcopy
import json
import re

from .core import ConflictError, canonical, content_hash, identifier, now, required


PREFIX = "delivery1110:"
WRITE_ACTIONS = {"delivery.define", "delivery.review", "delivery.complete"}
LIMITATION = "Recorded source and reviewer identities are host-reported, not authenticated by this registry; quotations prove text presence, not semantic coverage or creative quality."


def _object(value, allowed, required_fields=(), name="payload"):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(name + " 含未知字段或不是对象")
    required(value, *required_fields)
    return value


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + " 必须为非空文本")
    return value


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(name + " 必须为不小于 " + str(minimum) + " 的整数")
    return value


def _array(value, name, nonempty=False):
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(name + " 必须为" + ("非空" if nonempty else "") + "数组")
    return value


def _identity(registry, payload, fields, required_fields=()):
    _object(payload, {"expected_project_id", "delivery_id", "op_id"} | set(fields), ("expected_project_id", *required_fields))
    identifier(payload["expected_project_id"], "expected_project_id")
    registry.check_project_identity(payload["expected_project_id"])
    if "delivery_id" in payload:
        identifier(payload["delivery_id"], "delivery_id")


def _load(registry, delivery_id):
    row = registry.db.execute("SELECT value FROM settings WHERE key=?", (PREFIX + delivery_id,)).fetchone()
    return json.loads(row[0]) if row else None


def _store(registry, state):
    registry.db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (PREFIX + state["delivery_id"], canonical(state)))


def _exact_artifact(registry, value):
    _object(value, {"artifact_id", "version", "sha256"}, ("artifact_id", "version", "sha256"), "artifact reference")
    identifier(value["artifact_id"], "artifact_id")
    _integer(value["version"], "version", 1)
    if not isinstance(value["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", value["sha256"]):
        raise ValueError("sha256 必须为实际正文的 SHA-256")
    artifact = registry._artifact(value["artifact_id"], value["version"])
    if not artifact:
        raise ValueError("准确成果版本不存在")
    if artifact["sha256"] != value["sha256"] or content_hash(artifact["content"]) != value["sha256"]:
        raise ConflictError("准确成果正文摘要不符")
    return artifact


def _ref(artifact):
    return {key: artifact[key] for key in ("artifact_id", "version", "sha256")}


def _quote(body, evidence, name):
    _object(evidence, {"location", "quote"}, ("location", "quote"), name)
    _text(evidence["location"], name + ".location")
    quote = _text(evidence["quote"], name + ".quote")
    if not isinstance(body, str) or quote not in body:
        raise ValueError(name + " 引文不在准确正文中；不可使用概要或编造引文")
    start = body.index(quote)
    return dict(evidence, verified_first_span={"start": start, "end": start + len(quote)}, occurrence_count=body.count(quote))


def _source(registry, source, user_request, inputs):
    if not isinstance(source, dict):
        raise ValueError("unit.source 必须保留准确来源")
    if source.get("type") == "user_request":
        _object(source, {"type", "reference", "quote"}, ("reference", "quote"), "unit.source")
        if source["reference"] != user_request["reference"] or _text(source["quote"], "source.quote") not in user_request["quote"]:
            raise ValueError("单元原话必须来自冻结 user_request 的同一 reference 和原文")
        return deepcopy(source)
    if source.get("type") != "artifact":
        raise ValueError("unit.source.type 必须为 artifact 或 user_request")
    _object(source, {"type", "artifact_id", "version", "sha256", "location", "quote"}, ("artifact_id", "version", "sha256", "location", "quote"), "unit.source")
    reference = {key: source[key] for key in ("artifact_id", "version", "sha256")}
    if reference not in inputs:
        raise ValueError("单元来源必须属于本契约冻结的 inputs")
    artifact = _exact_artifact(registry, reference)
    evidence = _quote(artifact["content"], {key: source[key] for key in ("location", "quote")}, "source")
    return dict(source, verified_first_span=evidence["verified_first_span"], occurrence_count=evidence["occurrence_count"])


def _stale(registry, contract, artifact=None, *, defining=False):
    reasons = []
    for reference in contract["inputs"]:
        bound = registry._artifact(reference["artifact_id"], reference["version"])
        latest = registry._artifact(reference["artifact_id"])
        if not bound or bound["sha256"] != reference["sha256"] or content_hash(bound["content"]) != reference["sha256"]:
            reasons.append("input_integrity:" + reference["artifact_id"])
        elif reference["artifact_id"] == contract["target_artifact_id"] and not defining:
            # A local revision may freeze this target's original text. Its new
            # output does not replace that baseline; a later output still makes
            # the review stale via the artifact check below.
            if artifact and artifact["version"] < reference["version"]:
                reasons.append("output_predates_baseline")
        elif not latest or latest["version"] != reference["version"] or registry._dependency_stale(reference):
            reasons.append("input_updated:" + reference["artifact_id"])
    if artifact:
        latest = registry._artifact(artifact["artifact_id"])
        if not latest or latest["version"] != artifact["version"] or latest["sha256"] != artifact["sha256"]:
            reasons.append("artifact_updated")
        elif registry._dependency_stale(artifact):
            reasons.append("artifact_inputs_updated")
    return reasons


def _evaluate(registry, state):
    contract = state["definition_revisions"][-1]
    review = state["reviews"][-1] if state["reviews"] else None
    completion = state["completions"][-1] if state["completions"] else None
    current_artifact = registry._artifact(contract["target_artifact_id"])
    artifact = review["artifact"] if review else (_ref(current_artifact) if current_artifact else None)
    stale = _stale(registry, contract, artifact)
    if review and review["revision"] != contract["revision"]:
        stale.append("contract_updated")
    if review:
        bound = registry._artifact(review["artifact"]["artifact_id"], review["artifact"]["version"])
        if not bound or content_hash(bound["content"]) != review["artifact"]["sha256"]:
            stale.append("review_artifact_integrity")
    expected = {unit["unit_id"] for unit in contract["units"]}
    coverage = {row["unit_id"]: row for row in review["coverage"]} if review else {}
    missing = sorted(unit for unit in expected if unit not in coverage or coverage[unit]["status"] == "missing")
    revision_units = sorted(unit for unit in expected if unit in coverage and coverage[unit]["status"] == "needs_revision")
    blockers = [finding["finding_id"] for finding in review["findings"] if finding["status"] == "open" and finding["severity"] in {"blocking", "major"}] if review else []
    status = "incomplete" if not review or stale or missing else ("needs_revision" if blockers or revision_units else "reviewed")
    ready = bool(status == "reviewed" and completion and completion["review_id"] == review["review_id"] and completion["revision"] == contract["revision"])
    return {"delivery_id": state["delivery_id"], "target_artifact_id": contract["target_artifact_id"], "scope": contract["scope"],
            "mode": contract["mode"], "granularity": contract["granularity"], "revision": contract["revision"],
            "review_revision": len(state["reviews"]), "completion_revision": len(state["completions"]),
            "status": status, "review_state": "missing" if not review else ("stale" if stale else "current"),
            "completion_state": "ready" if ready else ("stale" if completion else "not_completed"), "ready_for_delivery": ready,
            "artifact": artifact, "review_id": review["review_id"] if review else None,
            "missing_units": missing, "revision_units": revision_units, "blocking_findings": blockers, "stale_reasons": stale,
            "quality_guaranteed": False, "approval_changed": False}


def delivery_summary(registry):
    """Compact live view for snapshot/UI. Caller owns the read lock/transaction."""
    states = [json.loads(row[0]) for row in registry.db.execute("SELECT value FROM settings WHERE key LIKE ? ORDER BY key", (PREFIX + "%",))]
    return {"schema_version": 1, "items": [_evaluate(registry, state) for state in states], "evidence_limitation": LIMITATION}


def _view(registry, state):
    return dict(_evaluate(registry, state), contract=deepcopy(state["definition_revisions"][-1]),
                latest_review=deepcopy(state["reviews"][-1]) if state["reviews"] else None,
                latest_completion=deepcopy(state["completions"][-1]) if state["completions"] else None,
                history={"definition_revisions": [item["revision"] for item in state["definition_revisions"]],
                         "review_ids": [item["review_id"] for item in state["reviews"]],
                         "completion_ids": [item["completion_id"] for item in state["completions"]]},
                evidence_limitation=LIMITATION, observed_at=now())


def read_delivery(registry, payload):
    _identity(registry, payload, set())
    if "op_id" in payload:
        raise ValueError("delivery.read 不接受写入操作号")
    with registry.lock:
        registry.db.execute("BEGIN")
        try:
            registry.check_project_identity(payload["expected_project_id"])
            if "delivery_id" not in payload:
                result = delivery_summary(registry)
            else:
                state = _load(registry, payload["delivery_id"])
                if not state:
                    raise ValueError("交付契约不存在")
                result = _view(registry, state)
            result.update(read_only=True, project_id=payload["expected_project_id"])
            registry.db.execute("COMMIT")
            return result
        except Exception:
            registry.db.execute("ROLLBACK")
            raise


def _receipt(registry, state):
    return dict(_view(registry, state), project_id=registry._project()["project_id"],
                receipt_semantics="operation_time_snapshot; use delivery.read for current freshness")


def define_delivery(registry, payload):
    fields = {"base_revision", "target_artifact_id", "scope", "granularity", "mode", "user_request", "summary_request", "inputs", "units"}
    _identity(registry, payload, fields, ("delivery_id", "op_id", "base_revision", "target_artifact_id", "scope", "granularity", "user_request", "inputs", "units"))
    _integer(payload["base_revision"], "base_revision")
    identifier(payload["target_artifact_id"], "target_artifact_id")
    for field in ("scope", "granularity"):
        _text(payload[field], field)
    request = payload["user_request"]
    _object(request, {"reference", "quote"}, ("reference", "quote"), "user_request")
    for field in ("reference", "quote"):
        _text(request[field], "user_request." + field)
    mode = payload.get("mode", "full")
    if mode not in {"full", "summary"}:
        raise ValueError("mode 必须为 full 或 summary")
    if mode == "summary":
        authorization = payload.get("summary_request")
        _object(authorization, {"actor", "reference", "quote"}, ("actor", "reference", "quote"), "summary_request")
        if authorization["actor"] != "user" or authorization["reference"] != request["reference"] or _text(authorization["quote"], "summary_request.quote") not in request["quote"]:
            raise ValueError("摘要交付必须保留同一冻结用户请求中的摘要要求原话；宿主须提供真人来源")
    elif "summary_request" in payload:
        raise ValueError("full 不接受 summary_request")
    state = _load(registry, payload["delivery_id"])
    if (len(state["definition_revisions"]) if state else 0) != payload["base_revision"]:
        raise ConflictError("交付契约基础版本冲突")
    if state and state["definition_revisions"][-1]["target_artifact_id"] != payload["target_artifact_id"]:
        raise ConflictError("同一交付契约不能改绑另一成果")
    target = registry._artifact(payload["target_artifact_id"])
    if target and target["scope"] != payload["scope"]:
        raise ConflictError("交付范围必须匹配目标成果 scope；局部范围写入 granularity 和 units")
    inputs, seen = [], set()
    for reference in _array(payload["inputs"], "inputs"):
        _exact_artifact(registry, reference)
        if reference["artifact_id"] in seen:
            raise ValueError("inputs 不能重复引用同一成果")
        seen.add(reference["artifact_id"])
        inputs.append(deepcopy(reference))
    units, seen = [], set()
    for unit in _array(payload["units"], "units", True):
        _object(unit, {"unit_id", "description", "source"}, ("unit_id", "description", "source"), "unit")
        identifier(unit["unit_id"], "unit_id")
        if unit["unit_id"] in seen:
            raise ValueError("unit_id 重复")
        seen.add(unit["unit_id"])
        units.append(dict(unit, description=_text(unit["description"], "unit.description"), source=_source(registry, unit["source"], request, inputs)))
    contract = {key: deepcopy(payload[key]) for key in ("target_artifact_id", "scope", "granularity", "user_request")}
    contract.update(revision=payload["base_revision"] + 1, mode=mode, inputs=inputs, units=units, defined_at=now(), definition_id=payload["op_id"], request_authenticity="host_reported_unverified")
    if mode == "summary":
        contract["summary_request"] = deepcopy(payload["summary_request"])
    if _stale(registry, contract, defining=True):
        raise ConflictError("来源已有更新或需复核，须重新冻结准确输入")
    state = state or {"schema_version": 1, "delivery_id": payload["delivery_id"], "definition_revisions": [], "reviews": [], "completions": []}
    state["definition_revisions"].append(contract)
    _store(registry, state)
    return _receipt(registry, state)


def review_delivery(registry, payload):
    fields = {"revision", "base_review_revision", "artifact", "author", "reviewer", "coverage", "findings"}
    _identity(registry, payload, fields, ("delivery_id", "op_id", *fields))
    state = _load(registry, payload["delivery_id"])
    if not state:
        raise ValueError("交付契约不存在")
    contract = state["definition_revisions"][-1]
    if _integer(payload["revision"], "revision", 1) != contract["revision"] or _integer(payload["base_review_revision"], "base_review_revision") != len(state["reviews"]):
        raise ConflictError("交付契约或审查基础版本冲突")
    artifact = _exact_artifact(registry, payload["artifact"])
    if artifact["artifact_id"] != contract["target_artifact_id"] or artifact["scope"] != contract["scope"]:
        raise ConflictError("审查目标与冻结交付契约不符")
    if not isinstance(artifact["content"], str):
        raise ValueError("完整成稿审查需要实际文本正文")
    if _stale(registry, contract, payload["artifact"]):
        raise ConflictError("准确正文或来源已有更新；当前审查不能绑定旧稿")
    author, reviewer = payload["author"], payload["reviewer"]
    _object(author, {"type", "id"}, ("type", "id"), "author")
    _object(reviewer, {"type", "id", "source_reference"}, ("type", "id", "source_reference"), "reviewer")
    if author["type"] not in {"host_agent", "host_subagent", "human"} or reviewer["type"] not in {"host_subagent", "human"}:
        raise ValueError("评审须记录宿主独立子代理或人工来源；无独立上下文不能伪装独立审查")
    identifier(author["id"], "author.id")
    identifier(reviewer["id"], "reviewer.id")
    _text(reviewer["source_reference"], "reviewer.source_reference")
    if author["id"] == reviewer["id"]:
        raise ValueError("同一作者不能作为其独立审稿人")
    units = {unit["unit_id"]: unit for unit in contract["units"]}
    coverage, seen = [], set()
    for item in _array(payload["coverage"], "coverage"):
        _object(item, {"unit_id", "status", "output", "note"}, ("unit_id", "status", "note"), "coverage")
        if item["unit_id"] not in units or item["unit_id"] in seen:
            raise ValueError("覆盖单元未知或重复")
        seen.add(item["unit_id"])
        if item["status"] not in {"covered", "missing", "needs_revision"}:
            raise ValueError("coverage.status 无效")
        _text(item["note"], "coverage.note")
        saved = dict(item, source=deepcopy(units[item["unit_id"]]["source"]))
        if item["status"] in {"covered", "needs_revision"} or "output" in item:
            saved["output"] = _quote(artifact["content"], item.get("output"), "coverage.output")
        coverage.append(saved)
    findings, seen = [], set()
    previous_open = {item["finding_id"]: item for item in (state["reviews"][-1]["findings"] if state["reviews"] else [])
                     if item["status"] == "open" and item["severity"] in {"blocking", "major"}}
    for item in _array(payload["findings"], "findings"):
        _object(item, {"finding_id", "severity", "status", "location", "quote", "detail", "resolution"}, ("finding_id", "severity", "status", "location", "quote", "detail"), "finding")
        identifier(item["finding_id"], "finding_id")
        if item["finding_id"] in seen or item["severity"] not in {"blocking", "major", "minor"} or item["status"] not in {"open", "resolved"}:
            raise ValueError("finding 编号重复或状态无效")
        seen.add(item["finding_id"])
        if item["finding_id"] in previous_open and item["severity"] != previous_open[item["finding_id"]]["severity"]:
            raise ValueError("未闭合阻断项不能降低严重度以绕过返修；按原 finding_id 提供解决证据")
        _text(item["detail"], "finding.detail")
        saved = dict(item, evidence=_quote(artifact["content"], {key: item[key] for key in ("location", "quote")}, "finding"))
        if item["status"] == "resolved":
            resolution = item.get("resolution")
            _object(resolution, {"location", "quote", "explanation"}, ("location", "quote", "explanation"), "finding.resolution")
            _text(resolution["explanation"], "resolution.explanation")
            saved["resolution"] = dict(resolution, evidence=_quote(artifact["content"], {key: resolution[key] for key in ("location", "quote")}, "resolution"))
        elif "resolution" in item:
            raise ValueError("open finding 不能附已解决记录")
        findings.append(saved)
    for finding_id, previous in previous_open.items():
        if finding_id not in seen:
            carried = deepcopy(previous)
            carried.setdefault("carried_from_review_id", state["reviews"][-1]["review_id"])
            carried.setdefault("evidence_artifact", deepcopy(state["reviews"][-1]["artifact"]))
            findings.append(carried)
    review = {"review_id": payload["op_id"], "review_revision": len(state["reviews"]) + 1, "revision": contract["revision"],
              "artifact": _ref(artifact), "author": deepcopy(author), "reviewer": deepcopy(reviewer), "coverage": coverage,
              "findings": findings, "reviewed_at": now(), "independence_evidence": "host_reported_unverified", "semantic_quality_verified_by_program": False}
    state["reviews"].append(review)
    _store(registry, state)
    return _receipt(registry, state)


def complete_delivery(registry, payload):
    fields = {"revision", "review_id", "artifact", "base_completion_revision"}
    _identity(registry, payload, fields, ("delivery_id", "op_id", *fields))
    state = _load(registry, payload["delivery_id"])
    if not state:
        raise ValueError("交付契约不存在")
    contract = state["definition_revisions"][-1]
    if _integer(payload["revision"], "revision", 1) != contract["revision"] or _integer(payload["base_completion_revision"], "base_completion_revision") != len(state["completions"]):
        raise ConflictError("交付契约或完成记录基础版本冲突")
    _exact_artifact(registry, payload["artifact"])
    review = state["reviews"][-1] if state["reviews"] else None
    if not review or review["review_id"] != payload["review_id"] or review["artifact"] != payload["artifact"]:
        raise ConflictError("只能完成最新审查绑定的准确成果版本")
    assessment = _evaluate(registry, state)
    if assessment["status"] != "reviewed":
        raise ConflictError("完整交付证据未闭合或已过期: " + canonical({key: assessment[key] for key in ("status", "missing_units", "revision_units", "blocking_findings", "stale_reasons")}))
    state["completions"].append({"completion_id": payload["op_id"], "completion_revision": len(state["completions"]) + 1,
                                 "revision": contract["revision"], "review_id": review["review_id"], "artifact": deepcopy(payload["artifact"]), "completed_at": now()})
    _store(registry, state)
    return _receipt(registry, state)


def action_schemas():
    """Fresh JSON schemas shared by MCP/CLI contracts; root is a tool envelope."""
    string = {"type": "string", "minLength": 1}
    number = {"type": "integer", "minimum": 0}
    positive = {"type": "integer", "minimum": 1}
    def obj(properties, mandatory=None):
        return {"type": "object", "properties": properties, "required": list(properties) if mandatory is None else mandatory, "additionalProperties": False}
    def array(item):
        return {"type": "array", "items": item}
    ref = obj({"artifact_id": string, "version": positive, "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}})
    quote = obj({"location": string, "quote": string})
    request = obj({"reference": string, "quote": string})
    source = {"oneOf": [obj({"type": {"const": "artifact"}, **ref["properties"], **quote["properties"]}), obj({"type": {"const": "user_request"}, **request["properties"]})]}
    base = {"expected_project_id": string, "delivery_id": string, "op_id": string}
    define = {**base, "base_revision": number, "target_artifact_id": string, "scope": string, "granularity": string,
              "mode": {"type": "string", "enum": ["full", "summary"], "default": "full"}, "user_request": request,
              "summary_request": obj({"actor": {"const": "user"}, **request["properties"]}), "inputs": array(ref),
              "units": {**array(obj({"unit_id": string, "description": string, "source": source})), "minItems": 1}}
    coverage = obj({"unit_id": string, "status": {"enum": ["covered", "missing", "needs_revision"]}, "output": quote, "note": string}, ["unit_id", "status", "note"])
    coverage["oneOf"] = [{"properties": {"status": {"enum": ["covered", "needs_revision"]}}, "required": ["output"]},
                         {"properties": {"status": {"const": "missing"}}}]
    finding = obj({"finding_id": string, "severity": {"enum": ["blocking", "major", "minor"]}, "status": {"enum": ["open", "resolved"]},
                   **quote["properties"], "detail": string, "resolution": obj({**quote["properties"], "explanation": string})}, ["finding_id", "severity", "status", "location", "quote", "detail"])
    finding["oneOf"] = [{"properties": {"status": {"const": "resolved"}}, "required": ["resolution"]},
                        {"properties": {"status": {"const": "open"}}, "not": {"required": ["resolution"]}}]
    schemas = {"delivery.read": obj({"expected_project_id": string, "delivery_id": string}, ["expected_project_id"]),
               "delivery.define": obj(define, [key for key in define if key not in {"mode", "summary_request"}]),
               "delivery.review": obj({**base, "revision": positive, "base_review_revision": number, "artifact": ref,
                                       "author": obj({"type": {"enum": ["host_agent", "host_subagent", "human"]}, "id": string}),
                                       "reviewer": obj({"type": {"enum": ["host_subagent", "human"]}, "id": string, "source_reference": string}),
                                       "coverage": array(coverage), "findings": array(finding)}),
               "delivery.complete": obj({**base, "revision": positive, "review_id": string, "artifact": ref, "base_completion_revision": number})}
    schemas["delivery.define"]["oneOf"] = [
        {"properties": {"mode": {"const": "summary"}}, "required": ["mode", "summary_request"]},
        {"properties": {"mode": {"const": "full"}}, "not": {"required": ["summary_request"]}}]
    return deepcopy(schemas)

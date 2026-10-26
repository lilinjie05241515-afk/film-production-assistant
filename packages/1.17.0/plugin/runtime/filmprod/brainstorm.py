"""Callable, read-only handoff contract for a future brainstorming provider.

No generation provider, task creation, approval or external side effect lives here.
"""
from copy import deepcopy
import json


SKILL_NAME = "film-brainstorm-interface"
INTERFACE_VERSION = "1.0"
REF_SCHEMA = {
    "type": "object", "required": ["artifact_id", "version"], "additionalProperties": False,
    "properties": {"artifact_id": {"type": "string", "minLength": 1}, "version": {"type": "integer", "minimum": 1}},
}
NULLABLE_ITEMS = {"type": ["array", "null"], "items": {"type": ["string", "object"]}, "default": None}
INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
    "required": ["expected_project_id", "topic"],
    "properties": {
        "expected_project_id": {"type": "string", "minLength": 1},
        "topic": {"type": "string", "minLength": 1},
        "scope": {"type": ["string", "null"], "minLength": 1, "default": None},
        "must_keep": NULLABLE_ITEMS, "constraints": NULLABLE_ITEMS,
        "context_refs": {"type": "array", "items": REF_SCHEMA, "default": []},
        "base_ref": {"anyOf": [REF_SCHEMA, {"type": "null"}], "default": None},
        "allow_candidate_context": {"type": "boolean", "default": False},
    },
}
CANDIDATE_OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
    "required": ["status", "directions", "tradeoffs", "open_questions", "selection_status", "automatically_adopted"],
    "properties": {
        "status": {"const": "candidate"},
        "directions": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["direction_id", "title", "proposal", "source_refs", "benefits", "risks", "assumptions", "unknowns"],
            "properties": {
                "direction_id": {"type": "string", "minLength": 1}, "title": {"type": "string", "minLength": 1}, "proposal": {"type": "string", "minLength": 1},
                "source_refs": {"type": "array", "items": REF_SCHEMA},
                **{key: {"type": "array", "items": {"type": "string"}} for key in ("benefits", "risks", "assumptions", "unknowns")},
            },
        }},
        "tradeoffs": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["direction_ids", "dimension", "comparison"],
            "properties": {"direction_ids": {"type": "array", "minItems": 2, "items": {"type": "string"}}, "dimension": {"type": "string"}, "comparison": {"type": "string"}},
        }},
        "open_questions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["question_id", "question", "related_direction_ids"],
            "properties": {"question_id": {"type": "string"}, "question": {"type": "string"}, "related_direction_ids": {"type": "array", "items": {"type": "string"}}},
        }},
        "selection_status": {"const": "awaiting_user_choice"}, "automatically_adopted": {"const": False},
    },
}
CONTEXT_SCHEMA = {
    "type": "object", "required": ["artifact_id", "version", "kind", "category", "scope", "content", "sha256", "metadata", "deps", "context_status", "is_candidate", "current_approved_ref", "input_status"],
    "properties": {
        "artifact_id": REF_SCHEMA["properties"]["artifact_id"], "version": REF_SCHEMA["properties"]["version"],
        "kind": {"type": "string"}, "category": {"type": "string"}, "scope": {"type": "string"}, "content": {},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}, "metadata": {"type": "object"}, "deps": {"type": "array", "items": REF_SCHEMA},
        "context_status": {"enum": ["approved", "candidate", "historical_approved", "needs_review"]}, "is_candidate": {"type": "boolean"},
        "current_approved_ref": {"anyOf": [REF_SCHEMA, {"type": "null"}]}, "input_status": {"enum": ["current", "stale"]},
    },
}
OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
    "required": ["skill_name", "interface_version", "status", "provider_status", "can_generate", "read_only", "generation_performed", "project_id", "project_root", "topic", "scope", "must_keep", "constraints", "base_ref", "context_refs", "contexts", "global_style", "approved_style", "unknown_inputs", "candidate_output", "candidate_output_schema"],
    "properties": {
        "skill_name": {"const": SKILL_NAME}, "interface_version": {"const": INTERFACE_VERSION},
        "status": {"const": "interface_only"}, "provider_status": {"const": "not_connected"}, "can_generate": {"const": False}, "read_only": {"const": True}, "generation_performed": {"const": False},
        "project_id": {"type": "string"}, "project_root": {"type": "string"}, "topic": {"type": "string"},
        "scope": INPUT_SCHEMA["properties"]["scope"], "must_keep": NULLABLE_ITEMS, "constraints": NULLABLE_ITEMS,
        "base_ref": INPUT_SCHEMA["properties"]["base_ref"], "context_refs": INPUT_SCHEMA["properties"]["context_refs"],
        "contexts": {"type": "array", "items": CONTEXT_SCHEMA},
        "global_style": {"type": "object", "required": ["status", "approved_ref", "pending_refs", "scope", "semantic_compliance"]},
        "approved_style": {"anyOf": [CONTEXT_SCHEMA, {"type": "null"}]},
        "unknown_inputs": {"type": "array", "items": {"type": "string"}},
        "candidate_output": {"type": "null"}, "candidate_output_schema": {"type": "object"},
    },
}


def interface():
    return deepcopy({
        "skill_name": SKILL_NAME, "interface_version": INTERFACE_VERSION,
        "status": "interface_only", "provider_status": "not_connected", "can_generate": False, "read_only": True,
        "actions": ["brainstorm.interface", "brainstorm.prepare"],
        "input_schema": INPUT_SCHEMA, "output_schema": OUTPUT_SCHEMA, "candidate_output_schema": CANDIDATE_OUTPUT_SCHEMA,
        "effects": {"generation": False, "create_task": False, "save_artifact": False, "record_decision": False, "write_event": False, "external_request": False},
    })


def _validate(payload):
    extra = set(payload) - set(INPUT_SCHEMA["properties"])
    if extra:
        raise ValueError("brainstorm.prepare 不接受字段: " + ", ".join(sorted(extra)))
    for key in ("expected_project_id", "topic"):
        if not isinstance(payload.get(key), str) or not payload[key].strip():
            raise ValueError(f"brainstorm.prepare 需要明确 {key}")
    if payload.get("scope") is not None and (not isinstance(payload["scope"], str) or not payload["scope"].strip()):
        raise ValueError("scope 必须为明确非空字符串或 null（未知）")
    for key in ("must_keep", "constraints"):
        value = payload.get(key)
        if value is not None and (not isinstance(value, list) or any(not isinstance(item, (str, dict)) for item in value)):
            raise ValueError(f"{key} 必须为字符串/对象数组或 null（未知）")
    if not isinstance(payload.get("context_refs", []), list):
        raise ValueError("context_refs 必须为显式精确版本数组")
    if type(payload.get("allow_candidate_context", False)) is not bool:
        raise ValueError("allow_candidate_context 必须为布尔值")
    json.dumps(payload, ensure_ascii=False, allow_nan=False)


def _context(registry, ref):
    from .core import content_category
    artifact = registry._artifact(ref["artifact_id"], ref["version"])
    pointer = registry._approved_pointer(artifact)
    exact_pointer = pointer and pointer["artifact_id"] == artifact["artifact_id"] and pointer["version"] == artifact["version"]
    if exact_pointer:
        status = "needs_review" if pointer["review_status"] == "needs_review" else "approved"
    elif artifact["status"] == "approved":
        status = "historical_approved"
    elif artifact["status"] == "needs_review":
        status = "needs_review"
    else:
        status = "candidate"
    return dict(artifact, category=content_category(artifact), context_status=status, is_candidate=status == "candidate", current_approved_ref={"artifact_id": pointer["artifact_id"], "version": pointer["version"]} if pointer else None, input_status="stale" if registry._dependency_stale(ref) else "current")


def prepare_with_registry(registry, payload):
    """Called within a consistent read transaction by Registry.dispatch."""
    from .workflow import global_style
    _validate(payload)
    registry.check_project_identity(payload["expected_project_id"])
    refs = []
    for selected in payload.get("context_refs", []):
        if not isinstance(selected, dict) or set(selected) != {"artifact_id", "version"}:
            raise ValueError("context_refs 每项必须只有 artifact_id 和准确 version")
        if not isinstance(selected["artifact_id"], str) or not selected["artifact_id"].strip():
            raise ValueError("context_refs.artifact_id 必须为明确字符串 ID")
        ref = registry._ref(selected)
        if ref not in refs:
            refs.append(ref)
    base_ref = payload.get("base_ref")
    if base_ref is not None:
        if not isinstance(base_ref, dict) or set(base_ref) != {"artifact_id", "version"}:
            raise ValueError("base_ref 必须为精确 artifact_id/version 或 null")
        if not isinstance(base_ref["artifact_id"], str) or not base_ref["artifact_id"].strip():
            raise ValueError("base_ref.artifact_id 必须为明确字符串 ID")
        base_ref = registry._ref(base_ref)
        if base_ref not in refs:
            raise ValueError("base_ref 必须由用户明确列入 context_refs；不会猜选底本")
    contexts = [_context(registry, ref) for ref in refs]
    if any(item["is_candidate"] for item in contexts) and not payload.get("allow_candidate_context", False):
        raise ValueError("所选上下文含待审核候选；明确 allow_candidate_context=true 才能用于交接，并保留候选标签")
    approved, pending, _ = registry._content_views()
    style = global_style(approved, pending)
    approved_style = _context(registry, style["approved_ref"]) if style["status"] == "approved" else None
    if approved_style is not None and approved_style["input_status"] == "stale":
        style.update(status="needs_review", review_reason="dependency_stale")
        approved_style = None
    unknown = [key for key in ("scope", "must_keep", "constraints") if payload.get(key) is None]
    if not refs:
        unknown.append("context_refs")
    if base_ref is None:
        unknown.append("base_ref")
    if approved_style is None:
        unknown.append("global_style")
    return deepcopy({
        "skill_name": SKILL_NAME, "interface_version": INTERFACE_VERSION,
        "status": "interface_only", "provider_status": "not_connected", "can_generate": False, "read_only": True, "generation_performed": False,
        "project_id": registry._project()["project_id"], "project_root": str(registry.root), "topic": payload["topic"],
        "scope": payload.get("scope"), "must_keep": payload.get("must_keep"), "constraints": payload.get("constraints"),
        "base_ref": base_ref, "context_refs": refs, "contexts": contexts,
        "global_style": style, "approved_style": approved_style, "unknown_inputs": unknown,
        "candidate_output": None, "candidate_output_schema": CANDIDATE_OUTPUT_SCHEMA,
    })


def prepare(root, payload):
    """Public host entry point: opens existing data read-only, never migrates it."""
    from .core import Registry
    registry = Registry.open_readonly(root)
    try:
        return registry.dispatch("brainstorm.prepare", payload)
    finally:
        registry.close()

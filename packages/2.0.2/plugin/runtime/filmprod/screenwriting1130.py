"""Version-bound script feedback. No script edits, approval or host calls.

Registry owns the transaction and operation cache. Records describe reported
editorial decisions; they do not authenticate people or assess dramatic quality.
"""
from copy import deepcopy
import json

from .cloud1120 import ID, REF, REV, TEXT, obj

KEY = "screenwriting1130/v1"
READ_ACTIONS = {"screenwriting.read"}
IMPACTS = ("staging", "expression", "structure", "major")
STATUSES = ("addressed", "partially_addressed", "deferred", "declined", "needs_user_choice")
SOURCE = obj({"role": {"enum": ["director", "user", "review"]}, "reference": ID})
USER = obj({"source": {"enum": ["conversation", "panel"]}, "reference": ID, "quote": TEXT,
            "scope": ID, "feedback_id": ID, "script": REF, "actor": {"const": "human"},
            "synthetic": {"type": "boolean"}})
WRITE = {"op_id": ID, "expected_project_id": ID, "base_revision": REV}
SCHEMAS = {
    "screenwriting.read": obj({"expected_project_id": ID, "artifact_id": ID, "feedback_id": ID}, ["expected_project_id"]),
    "screenwriting.record": obj({**WRITE, "feedback_id": ID, "script": REF, "scope": ID,
        "scene_id": ID, "anchor": TEXT, "problem": TEXT, "expected_effect": TEXT,
        "must_keep": {"type": "array", "items": TEXT}, "impact": {"enum": list(IMPACTS)},
        "source": SOURCE, "suggestion": TEXT}, [*WRITE, "feedback_id", "script", "scope", "scene_id", "anchor", "problem", "expected_effect", "must_keep", "impact", "source"]),
    "screenwriting.resolve": obj({**WRITE, "feedback_id": ID, "status": {"enum": list(STATUSES)},
        "response": TEXT, "revised_script": REF, "user_decision": USER},
        [*WRITE, "feedback_id", "status", "response"]),
}


def action_schemas():
    return deepcopy(SCHEMAS)


def validate_screenwriting_payload(action, payload):
    from .action_schemas import validate
    if action not in SCHEMAS:
        raise ValueError("未知编剧改稿意见操作")
    validate(payload, SCHEMAS[action], "payload")


def _load(registry):
    row = registry.db.execute("SELECT value FROM settings WHERE key=?", (KEY,)).fetchone()
    return json.loads(row[0]) if row else {"revision": 0, "feedbacks": []}


def _save(registry, state):
    from .core import canonical
    state["revision"] += 1
    registry.db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (KEY, canonical(state)))


def _check(registry, payload, state):
    from .core import ConflictError
    registry.check_project_identity(payload["expected_project_id"])
    if payload["base_revision"] != state["revision"]:
        raise ConflictError("改稿意见已发生变化，请先读取最新状态")


def _ref(artifact):
    return {key: artifact[key] for key in ("artifact_id", "version", "sha256")}


def _script(registry, reference):
    from .core import ConflictError, content_category, content_hash
    artifact = registry._artifact(reference["artifact_id"], reference["version"])
    if not artifact or artifact["sha256"] != reference["sha256"] or content_hash(artifact["content"]) != reference["sha256"]:
        raise ConflictError("意见必须引用本项目准确存在的剧本版本和摘要")
    if artifact["kind"] not in {"script", "screenplay", "source_script"} or content_category(artifact) not in {"script", "source_script"} or not isinstance(artifact["content"], str):
        raise ValueError("改稿意见仅适用于完整文本剧本；其他成果不能冒充剧本")
    return artifact


def _feedback_view(registry, feedback):
    result = deepcopy(feedback)
    latest = registry._artifact(feedback["script"]["artifact_id"])
    result["latest_script"] = _ref(latest) if latest else None
    result["source_changed"] = result["latest_script"] != feedback["script"]
    result["revision_changed"] = bool(feedback.get("revised_script") and feedback["revised_script"] != result["latest_script"])
    result["semantic_review"] = "not_assessed"
    result["scene_assignment"] = "host_reported; exact anchor existence verified, scene semantics not assessed"
    return result


def _view(registry, state):
    return {"project_id": registry._project()["project_id"], "revision": state["revision"],
            "feedbacks": [_feedback_view(registry, row) for row in state["feedbacks"]],
            "automatic_approval": False, "script_edited": False, "host_execution": False,
            "decision_evidence": "host_reported; not authenticated identity",
            "receipt_semantics": "operation_time_snapshot; read again for current versions"}


def screenwriting_summary(registry):
    return _view(registry, _load(registry))


def read_screenwriting(registry, payload):
    validate_screenwriting_payload("screenwriting.read", payload)
    registry.check_project_identity(payload["expected_project_id"])
    with registry.lock:
        registry.db.execute("BEGIN")
        try:
            result = screenwriting_summary(registry)
            for field, getter in (("artifact_id", lambda row: row["script"]["artifact_id"]), ("feedback_id", lambda row: row["feedback_id"])):
                if field in payload:
                    result["feedbacks"] = [row for row in result["feedbacks"] if getter(row) == payload[field]]
            if "feedback_id" in payload and not result["feedbacks"]:
                raise ValueError("指定改稿意见不存在或与成果不匹配")
            registry.db.execute("COMMIT")
            return result
        except Exception:
            registry.db.execute("ROLLBACK")
            raise


def record_screenwriting(registry, payload):
    from .core import ConflictError, now
    validate_screenwriting_payload("screenwriting.record", payload)
    state = _load(registry); _check(registry, payload, state)
    if any(row["feedback_id"] == payload["feedback_id"] for row in state["feedbacks"]):
        raise ConflictError("意见 ID 已存在；不可覆盖来源，请处理原意见或建立新的独立意见")
    script = _script(registry, payload["script"])
    if script["scope"] != payload["scope"]:
        raise ConflictError("意见范围与准确剧本范围不符")
    if payload["anchor"] not in script["content"]:
        raise ConflictError("原文定位不在引用的剧本版本中，请先读取准确正文")
    # Older source references are useful evidence. They are explicitly flagged
    # source_changed, never relabeled as latest or allowed to overwrite it.
    row = {key: deepcopy(payload[key]) for key in ("feedback_id", "script", "scope", "scene_id", "anchor", "problem", "expected_effect", "must_keep", "impact", "source")}
    row.update(suggestion=payload.get("suggestion"), created_at=now(),
               status="needs_user_choice" if row["impact"] == "major" else "open",
               response=None, revised_script=None, user_decision=None, history=[])
    state["feedbacks"].append(row); _save(registry, state)
    return {**_view(registry, state), "feedback": _feedback_view(registry, row), "saved": True}


def resolve_screenwriting(registry, payload):
    from .core import ConflictError, now
    validate_screenwriting_payload("screenwriting.resolve", payload)
    state = _load(registry); _check(registry, payload, state)
    row = next((item for item in state["feedbacks"] if item["feedback_id"] == payload["feedback_id"]), None)
    if not row:
        raise ValueError("改稿意见不存在")
    source = _script(registry, row["script"])
    resolved = payload["status"] in {"addressed", "partially_addressed"}
    if resolved and row["impact"] != "staging" and "revised_script" not in payload:
        raise ValueError("正文改稿必须先保存完整修订候选，再关联其准确版本")
    if not resolved and "revised_script" in payload:
        raise ValueError("未处理意见不能挂接已完成修订；请准确选择处理状态")
    if "revised_script" in payload:
        revised = _script(registry, payload["revised_script"])
        if revised["artifact_id"] != source["artifact_id"] or revised["scope"] != source["scope"] or revised["version"] <= source["version"]:
            raise ConflictError("修订必须是原剧本同一成果和范围的更高版本")
        if _ref(registry._artifact(revised["artifact_id"])) != payload["revised_script"]:
            raise ConflictError("修订成果已有更新版本，请先核对最新剧本和意见")
        if revised["sha256"] == source["sha256"]:
            raise ConflictError("正文未改变，不能将复制版本记为完成正文修订")
    decision = payload.get("user_decision")
    if resolved and row["impact"] == "major" and decision is None:
        raise ValueError("重大剧情变化需要真实用户选择原话及准确范围，不以导演建议代替")
    if decision is not None:
        if decision["feedback_id"] != row["feedback_id"] or decision["scope"] != row["scope"] or decision["script"] != row["script"]:
            raise ConflictError("用户选择必须准确对应本条意见的原剧本版本和范围")
        if decision["synthetic"] != bool(registry._project().get("test_only")):
            raise ValueError("测试项目使用 synthetic=true；真实作品不得以合成选择作为真人决定")
    update = {"status": payload["status"], "response": payload["response"],
              "revised_script": deepcopy(payload.get("revised_script")), "user_decision": deepcopy(decision),
              "resolved_at": now(), "op_id": payload["op_id"]}
    row["history"].append(deepcopy(update)); row.update(update)
    _save(registry, state)
    return {**_view(registry, state), "feedback": _feedback_view(registry, row), "saved": True}

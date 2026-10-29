"""Project conversation lifecycle and durable host outbox; never calls host tools.

All host observations and actor identities are caller reported, not authenticated.
Core owns identity, transactions, operation replay, and audit. No schema migration.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json

SETTINGS_KEY = "conversation/v1"
# Explicit duties, not semantic classification of user prose. Host/core routes
# remain finite and do not claim a bundled professional method exists.
ROLE_MODULES = {
    "planning": {"idea", "idea-explorer", "requirements", "requirements-planner"},
    "script": {"screenwriter", "outline", "character_bio", "screenplay", "script", "source_script",
               "dynamic_script", "original-screenplay", "adaptation", "novel-to-screenplay"},
    "novel": {"screenwriter", "outline", "character_bio", "story", "novel", "novel-master"},
    "director": {"director", "director-agent", "vfx", "vfx-agent"},
    "art": {"art", "style", "art_director", "film-art-director", "research", "film-analysis"},
    "assets": {"asset", "asset_prompt", "assets", "seedance-prompt", "video_prompt"},
    "review": {"review", "editing", "delivery"},
}
ROLES = list(ROLE_MODULES)
ID = {"type": "string", "minLength": 1, "pattern": r"^(?!\s*$)[^\x00-\x1f]{1,240}$"}
TEXT = {"type": "string", "minLength": 1}
BOOL = {"type": "boolean"}
REV = {"type": "integer", "minimum": 0}


def obj(properties, required=None, **extra):
    return {"type": "object", "properties": properties,
            "required": list(properties if required is None else required),
            "additionalProperties": False, **extra}


def array(items, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum}


REF = obj({"artifact_id": ID, "version": {"type": "integer", "minimum": 1}})
AUTH = obj({"quote": TEXT, "reference": TEXT, "actions": array({"enum": [
    "configure", "prepare", "decide", "accept", "bind_task", "complete", "start", "continue",
    "create_thread", "send_message_to_thread", "archive", "route", "route_accept", "report"]}, 1),
    "target": obj({"project_id": ID, "scopes": array(ID, 1), "thread_ids": array(ID, 1)}),
    "synthetic": BOOL})
WRITE = {"op_id": ID, "expected_project_id": ID, "base_revision": REV}
ACTOR = {"actor_thread_id": ID, "authorization": AUTH}
BASE = {**WRITE, **ACTOR}
REQUIRED = (*WRITE, "actor_thread_id")
OBS_BASE = {"source": {"const": "host_tool"}, "tool": {"enum": [
    "create_thread", "send_message_to_thread", "set_thread_archived", "list_threads",
    "read_thread", "wait_threads", "get_worktree_creation_status"]},
    "observed_at": TEXT, "reference": TEXT, "project_id": ID,
    "topic_id": ID, "scope": ID, "request_id": ID, "attempt": {"type": "integer", "minimum": 1}}
OBS = {
    "queued": obj({**OBS_BASE, "client_thread_id": ID}),
    "unknown": obj({**OBS_BASE, "reason": TEXT}),
    "host_accepted": obj({**OBS_BASE, "thread_id": ID, "title": TEXT,
                          "client_project_id": ID, "project_root": TEXT}),
    "failed": obj({**OBS_BASE, "reason": TEXT, "no_effect": BOOL, "proof": TEXT}),
}
ACTION_SCHEMAS = {
    "conversation.read": obj({"expected_project_id": ID}),
    "conversation.configure": obj({**BASE, "enabled": BOOL}, (*REQUIRED, "enabled", "authorization")),
    "conversation.prepare": obj({**BASE, "topic_id": ID, "kind": {"enum": ["idea", "execution"]},
        "title": TEXT, "scope": ID, "planning_ref": REF, "handoff_id": ID, "route_id": ID, "target_artifact_id": ID,
        "direct_brief": TEXT, "inputs": array(REF), "target_role": {"enum": ROLES}},
        (*REQUIRED, "topic_id", "kind", "title", "scope"), oneOf=[
            {"properties": {"kind": {"const": "idea"}}, "required": ["planning_ref"],
             "not": {"anyOf": [{"required": [key]} for key in ("handoff_id", "route_id", "target_artifact_id", "direct_brief", "inputs", "target_role")]}},
            {"properties": {"kind": {"const": "execution"}}, "required": ["handoff_id", "target_artifact_id"],
             "not": {"anyOf": [{"required": [key]} for key in ("planning_ref", "route_id", "direct_brief", "inputs", "target_role")]}},
            {"properties": {"kind": {"const": "execution"}}, "required": ["route_id", "target_artifact_id"],
             "not": {"anyOf": [{"required": [key]} for key in ("planning_ref", "handoff_id", "direct_brief", "inputs", "target_role")]}},
            {"properties": {"kind": {"const": "execution"}}, "required": ["direct_brief", "inputs", "target_role", "target_artifact_id"],
             "not": {"anyOf": [{"required": ["planning_ref"]}, {"required": ["handoff_id"]}, {"required": ["route_id"]}]}}]),
    "conversation.decide": obj({**BASE, "topic_id": ID,
        "decision": {"enum": ["retain", "recycle", "restore", "develop"]}, "reason": TEXT,
        "branch_id": ID, "target_role": {"enum": ["script", "novel"]}, "archive_chat": BOOL, "planning_ref": REF},
        (*REQUIRED, "topic_id", "decision", "reason"), oneOf=[
            {"properties": {"decision": {"const": "develop"}}, "required": ["branch_id", "target_role"],
             "not": {"required": ["archive_chat"]}},
            {"properties": {"decision": {"enum": ["retain", "recycle", "restore"]}},
             "not": {"anyOf": [{"required": ["branch_id"]}, {"required": ["target_role"]}]}}]),
    "conversation.accept": obj({**BASE, "handoff_id": ID,
        "status": {"enum": ["received", "clarifying", "ready", "declined"]},
        "brief": TEXT, "questions": array(TEXT), "inputs": array(REF, 1)},
        (*REQUIRED, "handoff_id", "status")),
    "conversation.bind_task": obj({**BASE, "topic_id": ID, "task_id": ID},
        (*REQUIRED, "topic_id", "task_id")),
    "conversation.complete": obj({**BASE, "topic_id": ID, "task_id": ID,
        "output_ref": REF, "summary": TEXT}, (*REQUIRED, "topic_id", "task_id", "output_ref", "summary")),
    "conversation.route": obj({**BASE, "request_id": ID, "original_request": TEXT,
        "target_role": {"enum": ROLES}, "scope": ID, "inputs": array(REF), "deliverable": TEXT,
        "report_to_thread_id": ID, "target_artifact_id": ID}, (*REQUIRED, "request_id", "original_request", "target_role", "scope",
                                      "inputs", "deliverable", "report_to_thread_id")),
    "conversation.route_accept": obj({**BASE, "request_id": ID,
        "status": {"enum": ["received", "clarifying", "ready", "declined"]},
        "brief": TEXT, "questions": array(TEXT), "inputs": array(REF)}, (*REQUIRED, "request_id", "status")),
    "conversation.report": obj({**BASE, "topic_id": ID, "task_id": ID, "output_ref": REF},
        (*REQUIRED, "topic_id", "task_id", "output_ref")),
    "conversation.start": obj({**BASE, "topic_id": ID}, (*REQUIRED, "topic_id")),
    "conversation.continue": obj({**BASE, "topic_id": ID, "brief": TEXT, "inputs": array(REF),
        "planning_ref": REF, "route_id": ID}, (*REQUIRED, "topic_id", "brief", "inputs"),
        description="接续原真实聊天。route_id明确接收新转交；省略则为直接接续，本轮不继承旧转交的额外回报目标，旧轮仍可按准确task/output补report。"),
    "conversation.claim": obj({**WRITE, "request_id": ID, "retry_failed": BOOL}, (*WRITE, "request_id")),
    "conversation.observe": obj({**WRITE, "request_id": ID, "status": {"enum": list(OBS)},
        "observation": {"type": "object"}}, (*WRITE, "request_id", "status", "observation"),
        oneOf=[{"properties": {"status": {"const": status}, "observation": schema}} for status, schema in OBS.items()]),
}


def action_schemas():
    return deepcopy(ACTION_SCHEMAS)


def validate_conversation_payload(action, payload):
    """Strict shape validation is safe before opening any project."""
    from .action_schemas import validate
    if action not in ACTION_SCHEMAS:
        raise ValueError("不支持的会话管理操作")
    validate(payload, ACTION_SCHEMAS[action], "payload")
    observation = payload.get("observation")
    if observation:
        try:
            stamp = datetime.fromisoformat(observation["observed_at"].replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("observed_at 必须为带时区的 ISO 8601 时间") from exc
        if stamp.utcoffset() is None:
            raise ValueError("observed_at 必须带时区")
        if observation["request_id"] != payload["request_id"]:
            raise ValueError("观察的 request_id 不一致")
    if action in ("conversation.accept", "conversation.route_accept"):
        if payload["status"] == "ready" and (not payload.get("brief") or "inputs" not in payload or (action == "conversation.accept" and not payload["inputs"]) or payload.get("questions")):
            raise ValueError("ready 必须有完整 brief、准确 inputs 且无未决 questions")
        if payload["status"] == "clarifying" and not payload.get("questions"):
            raise ValueError("clarifying 必须记录真正待澄清的 questions")
        if payload["status"] == "declined" and not payload.get("brief"):
            raise ValueError("declined 必须用 brief 记录原因")
    if action == "conversation.route" and any(not payload[key].strip() for key in ("original_request", "deliverable")):
        raise ValueError("转交必须保留非空原话与明确交付要求")
    if action == "conversation.decide" and payload.get("archive_chat") and payload["decision"] not in ("recycle", "restore"):
        raise ValueError("archive_chat 只能作为 recycle/restore 的独立宿主待办")
    return payload


def _load(registry):
    row = registry.db.execute("SELECT value FROM settings WHERE key=?", (SETTINGS_KEY,)).fetchone()
    if row:
        return json.loads(row[0])
    return {"revision": 0, "enabled": False, "parents": {}, "authorization": None,
            "authorization_history": [], "topics": [], "handoffs": [], "outbox": [], "history": []}


def _id(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:32]


def _find(items, field, value):
    matches = [item for item in items if item[field] == value]
    if len(matches) != 1:
        raise ValueError(f"准确{field}不存在或重复: {value}")
    return matches[0]


def _view(registry, state, full=False):
    project = registry._project()
    result = deepcopy(state) if full else {
        "revision": state["revision"], "enabled": state["enabled"], "parents": deepcopy(state["parents"]),
        "topics": [{k: t[k] for k in ("topic_id", "kind", "title", "scope", "status", "parent_role",
            "parent_thread_id", "thread_id", "task_id", "target_artifact_id", "planning_ref", "handoff_id", "output_ref", "round") if k in t}
            for t in state["topics"]],
        "handoffs": [{k: h[k] for k in ("handoff_id", "source_topic_id", "source_ref", "branch_id", "target_role",
            "receiver_role", "receiver_thread_id", "status", "execution_topic_id") if k in h} for h in state["handoffs"]]}
    pending = []
    for request in state["outbox"]:
        if request["status"] in ("host_accepted", "cancelled"):
            continue
        item = deepcopy(request) if full else {k: request.get(k) for k in (
            "request_id", "topic_id", "tool", "status", "attempt", "target_thread_id", "purpose", "round")}
        item["next_action"] = ("claim" if request["status"] == "planned" and state["enabled"] else
                               "retry_with_no_effect_evidence" if request["status"] == "failed" else "check_original_request")
        item["dispatch_allowed"] = False
        pending.append(item)
    from .conversation_routing2100 import add_business_views
    add_business_views(registry, state, result, full=full)
    result.update(project_id=project["project_id"], pending_host_actions=pending,
                  host_execution=False, evidence_level="caller_reported", observations_are_live=False,
                  host_accepted_is_business_processed=False, read_only=True)
    # Each query is a view of stored observations; it performs no initialization.
    return result


def conversation_view(registry):
    return _view(registry, _load(registry))


def read_conversations(registry, payload):
    validate_conversation_payload("conversation.read", payload)
    registry.check_project_identity(payload["expected_project_id"])
    return _view(registry, _load(registry), full=True)


def _save(registry, state, payload, action, **extra):
    from .core import now
    state["revision"] += 1
    state["history"].append({"action": action, "op_id": payload["op_id"], "actor_thread_id": payload.get("actor_thread_id"),
                             "at": now(), "revision": state["revision"]})
    registry.db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                        (SETTINGS_KEY, json.dumps(state, ensure_ascii=False)))
    result = _view(registry, state)
    result.update(saved=True, read_only=False, **deepcopy(extra))
    return result


def _parents(registry):
    from .workspace1110 import workspace_view
    from .core import ConflictError
    workspace = workspace_view(registry)
    result = {}
    for slot in workspace["slots"]:
        if slot["role"] not in ("control", *ROLES) or slot["scope"] != "project":
            continue
        if not (slot["status"] == "associated_observed" and slot.get("thread_id") and slot.get("host_observation")
                and slot.get("catalog_binding_status") == "host_reported_bound" and slot.get("client_project_id")):
            continue
        if slot["role"] in result:
            raise ConflictError("项目级管理职责存在重复关联")
        result[slot["role"]] = {"thread_id": slot["thread_id"], "title": slot["title"],
            "client_project_id": slot["client_project_id"], "slot_id": slot["slot_id"], "scope": "project"}
    mode = workspace["workflow_mode"]
    needed = {"control", "planning", "novel" if mode == "novel_only" else "script"}
    if mode == "novel_to_screen":
        needed.add("novel")
    if mode == "unset" or not needed.issubset(result):
        raise ConflictError("请先核验本路线准确项目级总控、灵感及编剧真实对话关联")
    if len({p["client_project_id"] for p in result.values()}) != 1 or len({p["thread_id"] for p in result.values()}) != len(result):
        raise ConflictError("管理对话必须分别属于同一个准确客户端项目")
    return result


def _parent(registry, state, role):
    from .core import ConflictError
    current = _parents(registry)
    parent = state["parents"].get(role)
    if not parent or current.get(role) != parent:
        raise ConflictError("管理入口不存在或准确关联已改变；先核验并 configure，不能静默改绑")
    return parent


def _actor(payload, *thread_ids):
    from .core import ConflictError
    if payload["actor_thread_id"] not in {value for value in thread_ids if value}:
        raise ConflictError("当前报告的 actor_thread_id 不属于本步骤的准确职责")


def _authorize(registry, state, payload, action, scope, thread_id):
    grant = deepcopy(payload.get("authorization") or state.get("authorization"))
    if not grant:
        raise ValueError("缺少当前操作的实际用户授权记录")
    from .action_schemas import validate
    validate(grant, AUTH, "authorization")
    if not grant["quote"].strip() or not grant["reference"].strip():
        raise ValueError("授权必须保留非空用户原话及来源")
    if grant["target"]["project_id"] != registry._project()["project_id"]:
        raise ValueError("授权不属于当前项目")
    if registry._project().get("test_only") and not grant["synthetic"]:
        raise ValueError("TEST项目授权必须 synthetic=true")
    if not registry._project().get("test_only") and grant["synthetic"]:
        raise ValueError("模拟授权不能用于真实项目")
    target = grant["target"]
    if action not in grant["actions"] or not ({scope, "*"} & set(target["scopes"])):
        raise ValueError("用户授权未覆盖当前动作与范围")
    if thread_id and not ({thread_id, "*"} & set(target["thread_ids"])):
        raise ValueError("用户授权未覆盖准确目标对话")
    return grant


def _refs(registry, refs):
    normalized = registry._deps(refs)
    if len({_id(r) for r in normalized}) != len(normalized):
        raise ValueError("准确输入不能重复")
    from .board1150 import is_trashed_ref
    if any(is_trashed_ref(registry, ref) for ref in normalized):
        raise ValueError("新工作不能选择回收站中的输入")
    return normalized


def _planning(registry, ref, scope=None):
    artifact = registry._artifact(ref["artifact_id"], ref["version"])
    if not artifact or artifact["kind"] != "planning_record" or artifact["content"]["record_kind"] != "idea":
        raise ValueError("灵感专题必须关联准确 idea planning_record 版本")
    if scope is not None and artifact["scope"] != scope:
        raise ValueError("灵感记录与专题范围不符")
    _refs(registry, [ref])
    return artifact


def _compatible(registry, role):
    mode = (registry._project().get("workflow") or {}).get("mode")
    if role == "script":
        return mode in {"screenplay", "novel_to_screen"}
    if role == "novel":
        return mode in {"novel_only", "novel_to_screen"}
    return role in ROLE_MODULES and mode in {"screenplay", "novel_to_screen", "novel_only"}


def _request(registry, state, payload, topic, tool, purpose, target_thread_id, body, **fields):
    from .core import now, ConflictError
    request_id = "host-" + _id(registry._project()["project_id"], topic["topic_id"], purpose, target_thread_id)
    existing = next((r for r in state["outbox"] if r["request_id"] == request_id), None)
    if existing:
        if existing["payload"] != body or existing["tool"] != tool:
            raise ConflictError("固定宿主请求的内容不能改变")
        return existing
    authorization = _authorize(registry, state, payload, tool, topic["scope"], target_thread_id or topic["parent_thread_id"])
    request = {"request_id": request_id, "topic_id": topic["topic_id"], "scope": topic["scope"], "tool": tool,
        "purpose": purpose, "target_thread_id": target_thread_id, "payload": deepcopy(body),
        "authorization": authorization, "status": "planned", "attempt": 0, "client_thread_id": None,
        "observations": [], "created_at": now(), "round": topic.get("round", 1), **fields}
    state["outbox"].append(request)
    return request


def _prepare(registry, state, payload):
    from .core import ConflictError, now
    existing = next((t for t in state["topics"] if t["topic_id"] == payload["topic_id"]), None)
    fingerprint = {key: payload[key] for key in ("topic_id", "kind", "title", "scope", "planning_ref", "handoff_id",
        "target_artifact_id", "direct_brief", "inputs", "target_role", "route_id") if key in payload}
    if existing:
        if existing["preparation"] != fingerprint:
            raise ConflictError("同 topic_id 已有准确范围和输入；不能重建或静默改绑")
        _actor(payload, existing["parent_thread_id"], state["parents"]["control"]["thread_id"])
        return {"topic": existing, "reused": True}
    handoff = None
    route = None
    if payload["kind"] == "idea":
        _planning(registry, payload["planning_ref"], payload["scope"])
        role, inputs, brief = "planning", [payload["planning_ref"]], "围绕准确记录开展专题讨论，保留原话、分支与决定；不自动写剧本。"
    elif payload.get("handoff_id"):
        handoff = _find(state["handoffs"], "handoff_id", payload["handoff_id"])
        if handoff["status"] != "ready" or handoff.get("execution_topic_id"):
            raise ConflictError("执行专题须使用 ready 且未派发的交接")
        source = _find(state["topics"], "topic_id", handoff["source_topic_id"])
        if source["status"] == "recycled":
            raise ConflictError("灵感已回收；先明确恢复，再开始新的下游工作")
        role, inputs, brief = handoff["target_role"], _refs(registry, handoff["inputs"]), handoff["brief"]
    elif payload.get("route_id"):
        from .conversation_routing2100 import execution_route
        route = execution_route(registry, state, payload)
        role, inputs, brief = route["target_role"], deepcopy(route["inputs"]), route["brief"]
    else:
        role, inputs, brief = payload["target_role"], _refs(registry, payload["inputs"]), payload["direct_brief"]
    if payload["kind"] == "execution" and handoff is None:
        registry._fresh(inputs)
    if payload["kind"] == "execution" and not _compatible(registry, role):
        raise ConflictError("请求与既有创作路线不匹配；先澄清，不自动修改路线")
    parent = _parent(registry, state, role)
    _actor(payload, parent["thread_id"], state["parents"]["control"]["thread_id"])
    _authorize(registry, state, payload, "prepare", payload["scope"], parent["thread_id"])
    for topic in state["topics"]:
        if topic["kind"] == payload["kind"] and topic["status"] not in ("completed", "recycled"):
            if topic["scope"] == payload["scope"] or (payload.get("target_artifact_id") and topic.get("target_artifact_id") == payload["target_artifact_id"]):
                raise ConflictError("该范围或成果已有专题，不另建并发编辑者")
        if payload["kind"] == "idea" and topic.get("planning_ref", {}).get("artifact_id") == payload["planning_ref"]["artifact_id"]:
            raise ConflictError("同一灵感记录已有专题；请接续或恢复原专题")
    if payload["kind"] == "execution":
        for task in registry._list("tasks"):
            if task["status"] in ("created", "in_progress", "needs_review") and (
                    task["scope"] == payload["scope"] or task.get("artifact_id") == payload["target_artifact_id"]):
                raise ConflictError("范围内已有未结束任务；不能新建专题绕过执行锁")
    topic = {"topic_id": payload["topic_id"], "kind": payload["kind"], "title": payload["title"], "scope": payload["scope"],
        "parent_role": role, "parent_thread_id": parent["thread_id"], "client_project_id": parent["client_project_id"],
        "thread_id": None, "task_id": None, "status": "prepared", "preparation": fingerprint,
        "inputs": deepcopy(inputs), "brief": brief, "decisions": [], "created_at": now(), "source_history": [],
        "round": 1, "task_history": []}
    if payload["kind"] == "idea":
        topic["planning_ref"] = deepcopy(payload["planning_ref"])
    else:
        topic["target_artifact_id"] = payload["target_artifact_id"]
        topic["handoff_id"] = payload.get("handoff_id")
    if handoff:
        handoff["execution_topic_id"] = topic["topic_id"]
    if route:
        topic["route_id"] = route["request_id"]
        topic["report_to_thread_id"] = route["report_to_thread_id"]
        route.update(execution_topic_id=topic["topic_id"], execution_round=topic["round"],
                     execution_target_artifact_id=topic["target_artifact_id"])
    state["topics"].append(topic)
    request = _request(registry, state, payload, topic, "create_thread", "create", None,
        {"project_id": registry._project()["project_id"], "project_root": str(registry.root),
         "client_project_id": parent["client_project_id"], "title": topic["title"], "topic_id": topic["topic_id"],
         "scope": topic["scope"], "kind": topic["kind"], "parent_thread_id": parent["thread_id"],
         "parent_role": role, "allowed_task_modules": sorted(ROLE_MODULES[role]),
         "route_id": topic.get("route_id"), "report_to_thread_id": topic.get("report_to_thread_id"),
         "instructions": "只核对本专题身份并报告就绪，等待父入口记录真实关联和显式start任务；不立即创作、不创建其他聊天。",
         "brief": brief, "inputs": deepcopy(inputs), "target_artifact_id": topic.get("target_artifact_id"),
         "project_control_thread_id": state["parents"]["control"]["thread_id"],
         "no_recursive_workspace_creation": True, "no_automatic_approval": True})
    return {"topic": topic, "request": request, "dispatch_allowed": False}


def _decide(registry, state, payload):
    from .core import ConflictError, now
    topic = _find(state["topics"], "topic_id", payload["topic_id"])
    if topic["kind"] != "idea":
        raise ValueError("保留、回收、恢复与转作决定仅用于灵感专题")
    _parent(registry, state, "planning")
    _actor(payload, topic["parent_thread_id"], topic["thread_id"], state["parents"]["control"]["thread_id"])
    authorization = _authorize(registry, state, payload, "decide", topic["scope"], topic["parent_thread_id"])
    if payload.get("planning_ref"):
        ref = payload["planning_ref"]
        if ref["artifact_id"] != topic["planning_ref"]["artifact_id"] or ref["version"] < topic["planning_ref"]["version"]:
            raise ConflictError("决定只能接续同一灵感记录的准确当前或新版本")
        _planning(registry, ref, topic["scope"])
        if ref != topic["planning_ref"]:
            topic["source_history"].append(deepcopy(topic["planning_ref"]))
            topic["planning_ref"] = deepcopy(ref)
    decision = payload["decision"]
    if topic["status"] == "recycled" and decision not in ("restore", "recycle"):
        raise ConflictError("已回收的灵感必须先恢复")
    result = {"topic": topic}
    if decision == "develop":
        source = _planning(registry, topic["planning_ref"], topic["scope"])
        if not any(b["id"] == payload["branch_id"] for b in source["content"]["state"]["branches"]):
            raise ValueError("所选分支不属于准确灵感版本")
        handoff_id = "handoff-" + _id(registry._project()["project_id"], topic["topic_id"])
        existing = next((h for h in state["handoffs"] if h["handoff_id"] == handoff_id), None)
        if existing:
            if (existing["source_ref"], existing["branch_id"], existing["target_role"]) != (topic["planning_ref"], payload["branch_id"], payload["target_role"]):
                raise ConflictError("专题已有唯一冻结交接；不能覆盖已转作的分支或版本")
            return {"topic": topic, "handoff": existing, "reused": True}
        role = payload["target_role"]
        receiver = role if role in state["parents"] else ("novel" if "novel" in state["parents"] else "script")
        parent = _parent(registry, state, receiver)
        handoff = {"handoff_id": handoff_id, "source_topic_id": topic["topic_id"], "source_ref": deepcopy(topic["planning_ref"]),
            "branch_id": payload["branch_id"], "target_role": role, "receiver_role": receiver,
            "receiver_thread_id": parent["thread_id"], "status": "offered", "execution_topic_id": None,
            "reason": payload["reason"], "created_at": now(), "history": [], "route_compatible": _compatible(registry, role)}
        state["handoffs"].append(handoff)
        topic.update(status="developed", handoff_id=handoff_id)
        request = _request(registry, state, payload, topic, "send_message_to_thread", "handoff", parent["thread_id"],
            {"handoff_id": handoff_id, "project_id": registry._project()["project_id"], "source_topic_id": topic["topic_id"],
             "source_ref": handoff["source_ref"], "branch_id": handoff["branch_id"], "target_role": role,
             "instruction": "读取准确灵感分支及既有需求；只澄清真实缺项，记录 received/clarifying/ready/declined。路线不符时只澄清，不改路线。",
             "reason": payload["reason"]}, handoff_id=handoff_id)
        result.update(handoff=handoff, request=request)
    elif decision == "retain":
        if topic["status"] != "developed":
            topic["status"] = "retained"
    elif decision == "recycle":
        if topic["status"] != "recycled":
            topic["before_recycle_status"] = topic["status"]
            topic["status"] = "recycled"
            topic["recycle_generation"] = topic.get("recycle_generation", 0) + 1
    elif decision == "restore":
        if topic["status"] != "recycled":
            raise ConflictError("只有已回收灵感可以恢复")
        topic["status"] = topic.get("before_recycle_status", "retained")
        # Cancelling an unclaimed request is a local action, never proof that an
        # in-flight host action was undone. Preserve the request and audit trail.
        for request in state["outbox"]:
            if request["topic_id"] == topic["topic_id"] and request["tool"] == "archive" and request["status"] == "planned":
                request.update(status="cancelled", cancelled_by=payload["op_id"], cancellation_reason="restore_before_dispatch")
    if payload.get("archive_chat"):
        if not topic.get("thread_id"):
            raise ConflictError("没有真实专题聊天，不能准备归档或恢复聊天")
        pending = [r for r in state["outbox"] if r["topic_id"] == topic["topic_id"] and r["tool"] == "archive"
                   and r["status"] in ("in_flight", "queued", "unknown")]
        if pending:
            raise ConflictError("原归档请求未决；先核查，不发送相反或重复操作")
        if decision == "recycle" or topic.get("host_archived_observed"):
            request = _request(registry, state, payload, topic, "archive", f"{decision}-{topic.get('recycle_generation', 0)}",
                topic["thread_id"], {"thread_id": topic["thread_id"], "archived": decision == "recycle"})
            result["request"] = request
    topic["decisions"].append({"decision": decision, "reason": payload["reason"], "planning_ref": deepcopy(topic["planning_ref"]),
                               "authorization": authorization, "at": now()})
    return result


def _accept(registry, state, payload):
    from .core import ConflictError, now
    handoff = _find(state["handoffs"], "handoff_id", payload["handoff_id"])
    topic = _find(state["topics"], "topic_id", handoff["source_topic_id"])
    parent = _parent(registry, state, handoff["receiver_role"])
    if parent["thread_id"] != handoff["receiver_thread_id"]:
        raise ConflictError("交接接收者已变更，不能静默改绑")
    _actor(payload, parent["thread_id"])
    authorization = _authorize(registry, state, payload, "accept", topic["scope"], parent["thread_id"])
    if handoff.get("execution_topic_id") or handoff["status"] == "declined":
        raise ConflictError("已派发或拒绝的交接不能覆盖接收状态")
    if topic["status"] == "recycled":
        raise ConflictError("源灵感已回收；不得继续推进新的下游")
    if not _compatible(registry, handoff["target_role"]) and payload["status"] not in ("clarifying", "declined"):
        raise ConflictError("既有路线不匹配；当前只能澄清或拒绝，不能改路线或标记ready")
    if payload["status"] == "ready":
        if handoff["target_role"] != handoff["receiver_role"]:
            raise ConflictError("需重新核验正确编剧接收入口，不能将错误路线接收者作为执行管理者")
        inputs = _refs(registry, payload["inputs"])
        if handoff["source_ref"] not in inputs:
            raise ValueError("ready输入必须保留交接冻结的准确灵感版本")
        handoff["inputs"] = inputs
    handoff.update(status=payload["status"], brief=payload.get("brief"), questions=payload.get("questions", []))
    handoff["history"].append({"status": payload["status"], "brief": payload.get("brief"),
        "questions": payload.get("questions", []), "inputs": payload.get("inputs"), "authorization": authorization, "at": now()})
    return {"handoff": handoff}


def _module_matches(role, module):
    return module in ROLE_MODULES.get(role, set())


def _task_matches(registry, topic, task, completed=False):
    from .core import ConflictError
    from .modules import require_execution
    if not _module_matches(topic["parent_role"], task.get("module")):
        raise ConflictError("任务模块不属于本专题的准确专业职责")
    task_frozen_source_ref(registry, task)
    if task.get("thread_id") != topic.get("thread_id") or not topic.get("thread_id") or task["scope"] != topic["scope"]:
        raise ConflictError("任务真实聊天或范围与执行专题不一致")
    if task.get("artifact_id") != topic["target_artifact_id"]:
        raise ConflictError("任务目标成果与执行专题不一致")
    if not all(ref in task["inputs"] for ref in topic["inputs"]):
        raise ConflictError("任务不能遗漏或替换专题的准确冻结输入")
    if completed:
        frozen = task.get("execution_lock")
        if not frozen:
            raise ConflictError("已提交任务缺少冻结执行锁")
    else:
        require_execution(task)
    if topic.get("task_lock") and topic["task_lock"] != task.get("execution_lock"):
        raise ConflictError("原任务冻结执行锁发生变化")


def _bind(registry, state, payload):
    from .core import ConflictError
    topic = _find(state["topics"], "topic_id", payload["topic_id"])
    if topic["kind"] != "execution" or not topic["thread_id"] or topic["status"] == "completed":
        raise ConflictError("须先取得执行专题真实聊天，且不能重新绑定已完成专题")
    _parent(registry, state, topic["parent_role"])
    _actor(payload, topic["thread_id"], topic["parent_thread_id"])
    _authorize(registry, state, payload, "bind_task", topic["scope"], topic["thread_id"])
    if topic.get("task_id") and topic["task_id"] != payload["task_id"]:
        raise ConflictError("执行专题已绑定其他任务；不得绕过旧任务")
    task = registry._get("tasks", "task_id", payload["task_id"])
    if task["status"] not in ("created", "in_progress", "needs_review"):
        raise ConflictError("只绑定尚未关闭的真实创作任务")
    _task_matches(registry, topic, task)
    if any(t.get("task_id") == task["task_id"] and t["topic_id"] != topic["topic_id"] for t in state["topics"]):
        raise ConflictError("真实任务已绑定其他专题")
    topic.update(task_id=task["task_id"], task_lock=deepcopy(task["execution_lock"]), status="task_bound")
    return {"topic": topic}


def _complete(registry, state, payload):
    from .core import ConflictError, now
    topic = _find(state["topics"], "topic_id", payload["topic_id"])
    if topic["kind"] != "execution" or topic.get("task_id") != payload["task_id"]:
        raise ConflictError("完成结果必须属于已绑定执行任务")
    _parent(registry, state, topic["parent_role"])
    _actor(payload, topic["thread_id"], topic["parent_thread_id"])
    _authorize(registry, state, payload, "complete", topic["scope"], topic["thread_id"])
    task = registry._get("tasks", "task_id", payload["task_id"])
    _task_matches(registry, topic, task, completed=True)
    if task["status"] != "submitted" or task.get("output") != payload["output_ref"]:
        raise ConflictError("完成需要真实提交任务的准确 output_ref，文本汇报不能替代")
    artifact = registry._artifact(payload["output_ref"]["artifact_id"], payload["output_ref"]["version"])
    if not artifact or artifact["scope"] != topic["scope"] or artifact["metadata"].get("execution_lock") != task["execution_lock"]:
        raise ConflictError("提交成果与任务范围或冻结执行锁不符")
    from .core import output_kinds
    allowed = output_kinds(task["module"])
    if topic["parent_role"] in ("script", "novel"):
        role_kinds = ({"script", "screenplay", "source_script"} if topic["parent_role"] == "script" else {"novel", "story"}) | {"outline", "character", "character_bio"}
        allowed &= role_kinds
    if artifact["kind"] not in allowed:
        raise ConflictError("真实提交成果类型不属于本专题专业任务")
    if topic["status"] == "completed":
        if topic["output_ref"] != payload["output_ref"] or topic["completion_summary"] != payload["summary"]:
            raise ConflictError("完成回执已冻结；不能覆盖为其他成果或摘要")
        return {"topic": topic, "reused": True}
    topic.update(status="completed", output_ref=deepcopy(payload["output_ref"]), output_sha256=artifact["sha256"],
                 completion_summary=payload["summary"], completed_at=now())
    from .conversation_routing2100 import queue_completion_reports
    return queue_completion_reports(registry, state, payload, topic)


def _start(registry, state, payload):
    from .core import ConflictError
    topic = _find(state["topics"], "topic_id", payload["topic_id"])
    _parent(registry, state, topic["parent_role"])
    _actor(payload, topic["parent_thread_id"], state["parents"]["control"]["thread_id"])
    _authorize(registry, state, payload, "start", topic["scope"], topic["thread_id"])
    if not topic["thread_id"] or topic["status"] in ("recycled", "completed"):
        raise ConflictError("start需要准确真实且未关闭的专题对话")
    if topic.get("host_archived_observed") or any(r["topic_id"] == topic["topic_id"] and r["tool"] == "archive"
            and r["status"] in ("in_flight", "queued", "unknown") for r in state["outbox"]):
        raise ConflictError("专题归档状态未恢复或仍未知；先核查原归档并明确恢复")
    if topic["kind"] == "execution":
        if not topic.get("task_id"):
            raise ConflictError("执行专题先创建并bind实际任务，再start")
        task = registry._get("tasks", "task_id", topic["task_id"])
        _task_matches(registry, topic, task)
        if task["status"] not in ("created", "in_progress", "needs_review"):
            raise ConflictError("已关闭任务不能重新启动")
    body = {"project_id": registry._project()["project_id"], "topic_id": topic["topic_id"], "round": topic["round"],
         "task_id": topic.get("task_id"), "scope": topic["scope"], "brief": topic["brief"], "inputs": deepcopy(topic["inputs"]),
         "target_artifact_id": topic.get("target_artifact_id"), "parent_thread_id": topic["parent_thread_id"],
         "parent_role": topic["parent_role"], "allowed_task_modules": sorted(ROLE_MODULES[topic["parent_role"]]),
         "route_id": topic.get("route_id"), "report_to_thread_id": topic.get("report_to_thread_id"),
         "instruction": "读取准确输入及当前任务检查点，执行本轮已授权范围。保留完整成果；完成记录不等于批准，回报须按待办单独发送。"}
    purpose = f"start-{topic['round']}"
    prior = next((r for r in state["outbox"] if r["topic_id"] == topic["topic_id"] and r["purpose"] == purpose
                  and r["target_thread_id"] == topic["thread_id"]), None)
    if prior:
        # 1170 outbox bodies predate role metadata. Reuse their immutable body;
        # never rewrite an accepted/unknown request or issue a replacement.
        additions = {"parent_role", "allowed_task_modules", "route_id", "report_to_thread_id"}
        comparable = {k: value for k, value in body.items() if k not in additions or k in prior["payload"]}
        if prior["payload"] != comparable:
            raise ConflictError("原启动请求内容已冻结，不能替换任务或输入")
        body = prior["payload"]
    request = _request(registry, state, payload, topic, "send_message_to_thread", purpose, topic["thread_id"], body)
    return {"topic": topic, "request": request, "dispatch_allowed": False, "business_processed": False}


def _continue(registry, state, payload):
    from .core import ConflictError, now
    topic = _find(state["topics"], "topic_id", payload["topic_id"])
    _parent(registry, state, topic["parent_role"])
    _actor(payload, topic["parent_thread_id"], state["parents"]["control"]["thread_id"])
    _authorize(registry, state, payload, "continue", topic["scope"], topic["thread_id"])
    if not topic["thread_id"] or topic["status"] == "recycled":
        raise ConflictError("接续需要准确真实聊天；已回收专题须先明确恢复")
    if any(r["topic_id"] == topic["topic_id"] and r["purpose"].startswith("start-")
           and r["status"] in ("in_flight", "queued", "unknown") for r in state["outbox"]):
        raise ConflictError("原启动请求结果未决；先核查原宿主观察，再接续新轮")
    inputs = _refs(registry, payload["inputs"])
    route = None
    if topic["kind"] == "execution":
        if payload.get("planning_ref"):
            raise ValueError("执行接续使用准确inputs，不改写灵感专题身份")
        if not topic.get("task_id"):
            raise ConflictError("本轮尚未绑定任务，不能用接续跳过本轮")
        task = registry._get("tasks", "task_id", topic["task_id"])
        _task_matches(registry, topic, task, completed=True)
        if task["status"] == "submitted" and topic["status"] != "completed":
            raise ConflictError("先complete准确提交成果并保留回报待办，再接续下一轮")
        if task["status"] not in ("submitted", "cancelled"):
            raise ConflictError("上轮任务尚未结束，不能新任务绕过原执行锁")
        for other in state["topics"]:
            if other["topic_id"] != topic["topic_id"] and other["kind"] == "execution" and other["status"] not in ("completed", "recycled"):
                if other["scope"] == topic["scope"] or other.get("target_artifact_id") == topic["target_artifact_id"]:
                    raise ConflictError("同范围或成果已有其他执行专题，不能通过接续创建第二编辑者")
        for other_task in registry._list("tasks"):
            if other_task["task_id"] != task["task_id"] and other_task["status"] in ("created", "in_progress", "needs_review") and (
                    other_task["scope"] == topic["scope"] or other_task.get("artifact_id") == topic["target_artifact_id"]):
                raise ConflictError("范围内仍有未结束任务，不能通过接续绕过旧执行锁")
        if payload.get("route_id"):
            from .conversation_routing2100 import execution_route
            route = execution_route(registry, state, {**payload, "scope": topic["scope"],
                "target_artifact_id": topic["target_artifact_id"]})
            if route["target_role"] != topic["parent_role"] or route["receiver_thread_id"] != topic["parent_thread_id"]:
                raise ConflictError("新转交的目标职责与原执行专题不符，不能改绑专业入口")
            if sorted(inputs, key=lambda r: (r["artifact_id"], r["version"])) != sorted(route["inputs"], key=lambda r: (r["artifact_id"], r["version"])):
                raise ConflictError("接续输入必须与新转交ready的准确输入完全一致")
    else:
        if payload.get("route_id"):
            raise ValueError("跨职责实作转交只能接续执行专题，不能转入灵感讨论")
        if not payload.get("planning_ref"):
            raise ValueError("灵感接续必须给出同一记录准确planning_ref")
        ref = payload["planning_ref"]
        if ref["artifact_id"] != topic["planning_ref"]["artifact_id"] or ref["version"] < topic["planning_ref"]["version"]:
            raise ConflictError("灵感接续不可改记录身份或回退到旧版本")
        _planning(registry, ref, topic["scope"])
        if inputs != [ref]:
            raise ValueError("灵感接续inputs必须为该准确planning_ref")
        topic["source_history"].append(deepcopy(topic["planning_ref"]))
        topic["planning_ref"] = deepcopy(ref)
    topic["task_history"].append({k: deepcopy(topic[k]) for k in ("round", "task_id", "task_lock", "inputs", "brief",
        "output_ref", "output_sha256", "completion_summary", "completed_at", "report_recipients",
        "route_id", "report_to_thread_id", "target_artifact_id") if k in topic})
    for request in state["outbox"]:
        if request["topic_id"] == topic["topic_id"] and request["purpose"].startswith("start-") and request["status"] == "planned":
            request.update(status="cancelled", cancelled_by=payload["op_id"], cancellation_reason="round_closed_before_dispatch")
    topic.update(round=topic["round"] + 1, inputs=inputs, brief=payload["brief"], task_id=None,
                 status="active", continued_at=now())
    for key in ("task_lock", "output_ref", "output_sha256", "completion_summary", "completed_at", "report_recipients"):
        topic.pop(key, None)
    for key in ("route_id", "report_to_thread_id"):
        topic.pop(key, None)
    if route:
        topic.update(route_id=route["request_id"], report_to_thread_id=route["report_to_thread_id"])
        route.update(execution_topic_id=topic["topic_id"], execution_round=topic["round"],
                     execution_target_artifact_id=topic["target_artifact_id"])
    return {"topic": topic, "new_chat_created": False,
            "continuation_mode": "routed" if route else "direct",
            "route_id": topic.get("route_id"), "report_to_thread_id": topic.get("report_to_thread_id"),
            "previous_round_reports_preserved": True,
            "extra_report_target_inherited": False}


def _claim(registry, state, payload):
    from .core import ConflictError, now
    request = _find(state["outbox"], "request_id", payload["request_id"])
    topic = _find(state["topics"], "topic_id", request["topic_id"])
    # An explicit one-time grant belongs to this exact durable request. Merely
    # configuring the mode does not broaden it; disabling the mode stops claims.
    _authorize(registry, state, {"authorization": request["authorization"]}, request["tool"], request["scope"],
               request["target_thread_id"] or topic["parent_thread_id"])
    _parent(registry, state, topic["parent_role"])
    for role, parent in state["parents"].items():
        if parent["thread_id"] == request["target_thread_id"]:
            _parent(registry, state, role)
    if request["status"] == "failed":
        if not payload.get("retry_failed") or not request.get("failure_no_effect"):
            raise ConflictError("只有准确未发生证明及显式 retry_failed 才能重试原请求")
    elif request["status"] != "planned":
        return {"request": request, "dispatch_allowed": False, "next_action": "check_original_request"}
    if topic["status"] == "recycled" and (request["tool"] == "create_thread" or request["purpose"] == "handoff" or request["purpose"].startswith("start-")):
        raise ConflictError("已回收专题不能启动新的讨论、聊天创建或下游交接")
    if request["purpose"].startswith("start-") and request["round"] != topic["round"]:
        raise ConflictError("旧轮启动请求不能唤醒新轮；核查原请求，不重复执行")
    request.update(status="in_flight", attempt=request["attempt"] + 1, claimed_at=now(), claim_op_id=payload["op_id"])
    return {"request": request, "dispatch_allowed": True, "delivery_is_not_business_processing": True}


def _observe(registry, state, payload):
    from .core import ConflictError
    from pathlib import Path
    request = _find(state["outbox"], "request_id", payload["request_id"])
    topic = _find(state["topics"], "topic_id", request["topic_id"])
    obs, status = payload["observation"], payload["status"]
    if request["status"] not in ("in_flight", "queued", "unknown", "host_accepted"):
        raise ConflictError("未领取或已明确失败的请求不能登记宿主执行观察")
    if any(obs[k] != v for k, v in {"project_id": registry._project()["project_id"], "topic_id": topic["topic_id"],
            "scope": topic["scope"], "request_id": request["request_id"], "attempt": request["attempt"]}.items()):
        raise ConflictError("宿主观察的项目、专题、范围、请求或尝试编号不一致")
    allowed = {"create_thread": {"create_thread", "list_threads", "read_thread", "get_worktree_creation_status"},
               "send_message_to_thread": {"send_message_to_thread", "read_thread", "wait_threads"},
               "archive": {"set_thread_archived", "list_threads", "read_thread"}}
    if obs["tool"] not in allowed[request["tool"]]:
        raise ValueError("宿主观察工具与待办动作不符")
    if request["status"] == "host_accepted":
        if status != "host_accepted" or request.get("accepted_observation") != obs:
            raise ConflictError("已确认接受的宿主结果不能被降级或替换")
        return {"request": request, "reused": True, "dispatch_allowed": False}
    if status == "queued":
        if request["tool"] != "create_thread":
            raise ValueError("clientThreadId仅适用于聊天创建排队")
        if request.get("client_thread_id") and request["client_thread_id"] != obs["client_thread_id"]:
            raise ConflictError("原排队引用不能替换")
        request.update(status="queued", client_thread_id=obs["client_thread_id"])
    elif status == "host_accepted":
        if obs["thread_id"] == request.get("client_thread_id"):
            raise ValueError("clientThreadId不能作为真实threadId")
        if obs["client_project_id"] != topic["client_project_id"] or Path(obs["project_root"]).resolve() != registry.root.resolve():
            raise ConflictError("宿主真实对话的客户端项目或作品目录不符")
        if request["tool"] == "create_thread":
            if topic.get("thread_id") and topic["thread_id"] != obs["thread_id"]:
                raise ConflictError("专题已经关联其他真实聊天")
            if any(t["thread_id"] == obs["thread_id"] for t in state["topics"] if t["topic_id"] != topic["topic_id"]) or any(
                    p["thread_id"] == obs["thread_id"] for p in state["parents"].values()):
                raise ConflictError("真实聊天已作为其他专题或管理入口，不得重复认领")
            previous = next((t for t in registry._list("threads") if t["thread_id"] == obs["thread_id"]), None)
            if previous and (previous.get("conversation_topic_id") != topic["topic_id"]):
                raise ConflictError("真实聊天已有其他登记；不能通过标题或创建观察重新认领")
            data = registry._thread({"thread_id": obs["thread_id"], "title": obs["title"], "scope": topic["scope"],
                "status": "active", "purpose": "conversation:" + topic["kind"], "artifact_refs": topic["inputs"],
                "client_project_id": topic["client_project_id"]})
            data.update(conversation_topic_id=topic["topic_id"], parent_thread_id=topic["parent_thread_id"],
                        host_observation=deepcopy(obs), host_evidence_level="caller_reported")
            registry._put("threads", "thread_id", obs["thread_id"], data)
            topic["thread_id"] = obs["thread_id"]
            if topic["status"] == "prepared":
                topic["status"] = "active"
        elif obs["thread_id"] != request["target_thread_id"]:
            raise ConflictError("宿主消息或归档观察不属于准确目标聊天")
        elif request["tool"] == "archive":
            topic["host_archived_observed"] = request["payload"]["archived"]
        request.update(status="host_accepted", accepted_observation=deepcopy(obs))
    elif status == "failed":
        request.update(status="failed" if obs["no_effect"] else "unknown", failure_no_effect=obs["no_effect"])
    else:
        request["status"] = "unknown"
    request["observations"].append({"status": status, "observation": deepcopy(obs), "op_id": payload["op_id"]})
    return {"request": request, "topic": topic, "dispatch_allowed": False, "business_processed": False}


def mutate_conversations(registry, action, payload):
    """Run only inside core's transaction; returns observations, never host effects."""
    from .core import ConflictError
    validate_conversation_payload(action, payload)
    if action == "conversation.read":
        raise ValueError("read 必须走只读入口")
    registry.check_project_identity(payload["expected_project_id"])
    state = _load(registry)
    if payload["base_revision"] != state["revision"]:
        raise ConflictError(f"会话修订冲突: expected={payload['base_revision']}, current={state['revision']}")
    if action == "conversation.configure":
        parents = _parents(registry)
        _actor(payload, parents["control"]["thread_id"])
        authorization = _authorize(registry, state, payload, "configure", "project", parents["control"]["thread_id"])
        if state["parents"] and any(parents.get(role) != prior for role, prior in state["parents"].items()):
            raise ConflictError("已启用管理入口不可自动改绑；保留原历史并先处理明确迁移")
        state.update(enabled=payload["enabled"], parents=parents, authorization=authorization)
        state["authorization_history"].append(deepcopy(authorization))
        extra = {"configured": True}
    else:
        if not state["enabled"] and action != "conversation.observe":
            raise ConflictError("尚未启用分层会话模式；先按明确授权 configure")
        from .conversation_routing2100 import route_request, accept_route, report_completion
        handlers = {"conversation.route": route_request, "conversation.route_accept": accept_route,
                    "conversation.report": report_completion, "conversation.prepare": _prepare, "conversation.decide": _decide, "conversation.accept": _accept,
                    "conversation.bind_task": _bind, "conversation.complete": _complete,
                    "conversation.start": _start, "conversation.continue": _continue,
                    "conversation.claim": _claim, "conversation.observe": _observe}
        extra = handlers[action](registry, state, payload)
    return _save(registry, state, payload, action, **extra)


def guard_task_create(registry, payload):
    """Enabled hierarchy routes new professional tasks to an exact execution chat."""
    from .core import ConflictError
    state = _load(registry)
    module = payload.get("module")
    if not state["enabled"]:
        return
    by_thread = [t for t in state["topics"] if t["kind"] == "execution" and t.get("thread_id")
                 and t["thread_id"] == payload.get("thread_id")]
    if by_thread and any(not _module_matches(t["parent_role"], module) for t in by_thread):
        raise ConflictError("该真实聊天已属于准确专业执行专题，不能建立其他模块任务占用范围")
    if any(parent["thread_id"] == payload.get("thread_id") for parent in state["parents"].values()):
        raise ConflictError("分层模式管理入口不承担具体制作；须复用准确执行专题")
    if not any(_module_matches(role, module) for role in ROLES):
        return
    matches = [t for t in state["topics"] if t["kind"] == "execution" and t.get("thread_id")
               and t["thread_id"] == payload.get("thread_id") and t["scope"] == payload.get("scope")
               and t.get("target_artifact_id") == payload.get("artifact_id")]
    if len(matches) != 1:
        raise ConflictError("分层模式下专业任务必须在准确已创建的执行专题中建立")
    topic = matches[0]
    if not _module_matches(topic["parent_role"], module):
        raise ConflictError("任务模块与专题专业职责不符")
    _parent(registry, state, topic["parent_role"])
    if topic["status"] not in ("active", "prepared") or topic.get("task_id"):
        raise ConflictError("专题已有任务或已关闭，不能新建任务绕过旧执行锁")
    if sorted(payload.get("inputs", []), key=lambda r: (r["artifact_id"], r["version"])) != sorted(topic["inputs"], key=lambda r: (r["artifact_id"], r["version"])):
        raise ConflictError("专业任务输入必须与执行专题冻结的准确输入一致")
    if not _compatible(registry, topic["parent_role"]):
        raise ConflictError("执行专题与当前路线不符；先澄清，不修改旧任务")


def _source_binding(reference, task):
    from .core import content_hash
    fields = {k: deepcopy(task.get(k)) for k in ("task_id", "module", "scope", "thread_id", "artifact_id", "inputs", "execution_lock")}
    return content_hash({"reference": {k: v for k, v in reference.items() if k != "binding_sha256"}, "task": fields})


def frozen_source_for_task(registry, task):
    """Only the selected branch of an enabled, ready handoff is a frozen source.

    Ordinary planning inputs and direct briefs receive no freshness exemption.
    The result is persisted on the task and thereafter checked independently of
    the mutable conversation round, configuration, or latest planning version.
    """
    from .core import ConflictError
    state = _load(registry)
    if not state["enabled"]:
        return None
    matches = [t for t in state["topics"] if t["kind"] == "execution" and t.get("handoff_id")
        and t.get("thread_id") == task.get("thread_id") and t["scope"] == task["scope"]
        and t.get("target_artifact_id") == task.get("artifact_id")]
    if not matches:
        return None
    if len(matches) != 1:
        raise ConflictError("冻结创意来源的专题身份不唯一")
    topic = matches[0]
    handoff = _find(state["handoffs"], "handoff_id", topic["handoff_id"])
    if handoff["status"] != "ready" or handoff.get("execution_topic_id") != topic["topic_id"] or handoff["target_role"] != topic["parent_role"]:
        raise ConflictError("冻结来源必须来自准确已接收交接与执行专题")
    source_ref = handoff["source_ref"]
    if source_ref not in task["inputs"]:
        # Later explicit revisions can inherit provenance from their previous
        # output without pretending they directly read this planning snapshot.
        return None
    if source_ref not in topic["inputs"]:
        raise ConflictError("冻结来源未纳入本轮专题准确输入")
    source = _planning(registry, source_ref)
    if not any(b["id"] == handoff["branch_id"] for b in source["content"]["state"]["branches"]):
        raise ConflictError("冻结来源分支不属于准确记录")
    reference = {"schema_version": 1, "mode": "frozen_planning_source", "project_id": registry._project()["project_id"],
        "topic_id": topic["topic_id"], "round": topic["round"], "handoff_id": handoff["handoff_id"],
        "source_topic_id": handoff["source_topic_id"], "source_ref": {**source_ref, "sha256": source["sha256"]},
        "source_scope": source["scope"], "branch_id": handoff["branch_id"], "task_id": task["task_id"],
        "thread_id": task["thread_id"], "target_artifact_id": task["artifact_id"], "scope": task["scope"]}
    reference["binding_sha256"] = _source_binding(reference, task)
    return reference


def check_frozen_source(registry, reference, *, task=None, artifact_id=None, scope=None):
    """Validate persisted source against its original task and immutable record."""
    from .core import ConflictError, content_hash
    keys = {"schema_version", "mode", "project_id", "topic_id", "round", "handoff_id", "source_topic_id", "source_ref",
            "source_scope", "branch_id", "task_id", "thread_id", "target_artifact_id", "scope", "binding_sha256"}
    if not isinstance(reference, dict) or set(reference) != keys or reference["schema_version"] != 1 or reference["mode"] != "frozen_planning_source":
        raise ConflictError("冻结创意来源结构不完整")
    ref = reference["source_ref"]
    if not isinstance(ref, dict) or set(ref) != {"artifact_id", "version", "sha256"}:
        raise ConflictError("冻结创意来源必须有准确版本和摘要")
    original = task or registry._get("tasks", "task_id", reference["task_id"])
    if original.get("conversation_source_reference") != reference or original.get("conversation_source_binding_sha256") != reference["binding_sha256"]:
        raise ConflictError("冻结创意来源与原任务记录不一致")
    if reference["binding_sha256"] != _source_binding(reference, original):
        raise ConflictError("冻结创意来源或任务输入绑定已被修改")
    if reference["project_id"] != registry._project()["project_id"] or reference["task_id"] != original["task_id"]:
        raise ConflictError("冻结创意来源项目或任务身份不符")
    if (artifact_id is not None and reference["target_artifact_id"] != artifact_id) or (scope is not None and reference["scope"] != scope):
        raise ConflictError("冻结创意来源只能由同一成果和范围继承")
    source = registry._artifact(ref["artifact_id"], ref["version"])
    if not source or source["kind"] != "planning_record" or source["content"]["record_kind"] != "idea" or source["scope"] != reference["source_scope"]:
        raise ConflictError("冻结创意来源原始记录身份不符")
    if source["sha256"] != ref["sha256"] or content_hash(source["content"]) != ref["sha256"]:
        raise ConflictError("冻结创意来源准确正文摘要不符")
    if not any(b["id"] == reference["branch_id"] for b in source["content"]["state"]["branches"]):
        raise ConflictError("冻结创意来源原分支缺失")
    exact = {k: ref[k] for k in ("artifact_id", "version")}
    if exact not in original["inputs"]:
        raise ConflictError("原任务未冻结该准确创意输入")
    return exact


def task_frozen_source_ref(registry, task):
    """Check stored markers even after the conversation moves to another round."""
    from .core import ConflictError
    reference = task.get("conversation_source_reference")
    if reference is None:
        if "conversation_source_binding_sha256" in task:
            raise ConflictError("任务冻结创意来源缺失但绑定摘要仍存在")
        return None
    return check_frozen_source(registry, reference, task=task)

"""Recoverable conversation workspace records; never invokes host chat tools.

The caller reports observed host results. These records are not authenticated host
receipts, current host state, creative execution, or approval of any content.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import uuid


SETTINGS_KEY = "workspace/v1"
ROLES = {
    "control": "项目总控", "planning": "灵感与需求", "novel": "小说创作",
    "script": "编剧与修订", "art": "美术总监", "director": "导演与特效", "assets": "资产与视频提示词",
    "review": "审核与交付",
}
ROUTE_ROLES = {
    "novel_only": ("control", "planning", "novel", "review"),
    "screenplay": ("control", "planning", "script", "art", "director", "assets", "review"),
    "novel_to_screen": tuple(ROLES),
}
TEXT = {"type": "string", "minLength": 1}
ID = {"type": "string", "minLength": 1, "pattern": r"^(?!\s*$)[^\x00-\x1f]{1,240}$"}
REVISION = {"type": "integer", "minimum": 0}
TIME = {"type": "string", "minLength": 1, "description": "ISO 8601 observation timestamp with timezone."}


def _object(props, required=None, **extra):
    return {"type": "object", "properties": props, "required": list(props if required is None else required),
            "additionalProperties": False, **extra}


def _host(tools, extra):
    return _object({"request_id": ID, "source": {"const": "host_tool"},
                    "tool": {"type": "string", "enum": tools}, "observed_at": TIME, **extra})


OBSERVATION_SCHEMAS = {
    "request_started": _object({"request_id": ID}),
    "unknown": _object({"request_id": ID, "reason": TEXT}),
    "queued": _host(["create_thread", "get_worktree_creation_status"], {"client_thread_id": ID}),
    "host_confirmed": _host(["create_thread", "list_threads", "read_thread", "get_worktree_creation_status"],
                            {"thread_id": ID, "title": TEXT, "origin": {"enum": ["created", "existing"]}}),
    "catalog_bound": _host(["film_projects"], {"thread_id": ID, "project_id": ID}),
    "client_project_observed": _host(["list_threads", "read_thread", "move_thread_to_project"],
                                     {"thread_id": ID, "client_project_id": {"type": ["string", "null"], "minLength": 1}}),
    "opened": _host(["navigate_to_codex_page"], {"thread_id": ID}),
    "open_failed": _host(["navigate_to_codex_page"], {"thread_id": ID, "reason": TEXT}),
    "failed": _host(["create_thread", "get_worktree_creation_status", "list_threads", "read_thread"],
                    {"reason": TEXT, "no_thread_created": {"type": "boolean"}}),
}
_WRITE = {"op_id": ID, "expected_project_id": ID, "base_revision": REVISION}
ACTION_SCHEMAS = {
    "workspace.read": _object({"expected_project_id": ID}),
    "workspace.resolve": _object({"expected_project_id": ID, "role": {"enum": list(ROLES)}, "scope": ID},
                                  ("expected_project_id", "role")),
    "workspace.prepare": _object({**_WRITE, "scope": ID, "include_art": {"type": "boolean"}}, tuple(_WRITE)),
    "workspace.record": _object({**_WRITE, "slot_id": ID,
                                 "event": {"type": "string", "enum": list(OBSERVATION_SCHEMAS)},
                                 "observation": {"type": "object"}},
                                oneOf=[{"properties": {"event": {"const": event}, "observation": schema}}
                                       for event, schema in OBSERVATION_SCHEMAS.items()]),
}


def action_schemas():
    """Independent schema copy for tool discovery and pre-project validation."""
    return deepcopy(ACTION_SCHEMAS)


def validate_workspace_payload(action, payload):
    """Safe before opening a project; exported for MCP schema/runtime alignment."""
    from .action_schemas import validate
    if action not in ACTION_SCHEMAS:
        raise ValueError("不支持的对话工作区操作")
    validate(payload, ACTION_SCHEMAS[action], "payload")
    observation = payload.get("observation", {})
    if "observed_at" in observation:
        _timestamp(observation["observed_at"])
    if "title" in observation and (not observation["title"].strip() or len(observation["title"]) > 500):
        raise ValueError("host title 必须为1至500字的非空标题")
    if "thread_id" in observation and observation.get("client_thread_id") == observation["thread_id"]:
        raise ValueError("clientThreadId 不能作为真实 threadId")
    return payload


def _timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("observed_at 必须是带时区的 ISO 8601 时间") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("observed_at 必须带时区")
    return result


def _load(registry):
    row = registry.db.execute("SELECT value FROM settings WHERE key=?", (SETTINGS_KEY,)).fetchone()
    if row:
        return json.loads(row[0])
    return {"revision": 0, "prepared": False, "initialization_id": None, "workflow_mode": "unset",
            "scope": "project", "slots": [], "preparations": []}


def _mode(registry):
    return ((registry._project() or {}).get("workflow") or {}).get("mode", "unset")


def _roles(mode, state):
    roles = ROUTE_ROLES.get(mode, ())
    if mode == "novel_only" and state.get("include_art", False):
        roles = tuple(r for r in roles if r != "review") + ("art", "review")
    return roles


def _slot_id(project_id, role, scope):
    value = json.dumps([project_id, role, scope], ensure_ascii=False, separators=(",", ":"))
    return "slot-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _next(slot):
    if slot["status"] == "conflict":
        return "resolve_conflict"
    if slot["thread_id"]:
        if not slot.get("host_observation"):
            return "verify_existing"
        if slot["catalog_binding_status"] != "host_reported_bound":
            return "bind_catalog"
        if slot["client_project_status"] == "unknown":
            return "observe_client_project"
        return "open_existing"
    if slot["status"] in ("requesting", "queued", "unknown"):
        return "check_pending"
    return "create"


def _view(registry, state):
    project = registry._project() or {}
    mode = _mode(registry)
    roles = _roles(mode, state)
    slots, retired = [], []
    for stored in state["slots"]:
        slot = deepcopy(stored)
        slot["next_action"] = _next(slot)
        # Scope selects the group currently shown/prepared; it does not retire
        # other valid work in the same route.
        slot["active"] = slot["role"] in roles
        slot["selected_scope"] = slot["scope"] == state["scope"]
        (slots if slot["active"] else retired).append(slot)
    slots.sort(key=lambda s: (not s["selected_scope"], s["scope"], roles.index(s["role"])))
    selected_slots = [s for s in slots if s["selected_scope"]]
    return {"project_id": project.get("project_id"), "revision": state["revision"],
            "workflow_mode": mode, "prepared_workflow_mode": state["workflow_mode"],
            "prepared": state["prepared"], "needs_prepare": state["workflow_mode"] != mode or len(selected_slots) != len(roles),
            "scope": state["scope"], "initialization_id": state["initialization_id"],
            "include_art": state.get("include_art", False),
            "slots": slots, "retired_slots": retired, "preparations": deepcopy(state["preparations"]),
            "required_roles": [{"role": r, "label": ROLES[r]} for r in roles],
            "host_execution": False, "creation_is_execution": False, "evidence_level": "caller_reported_observations",
            "observations_are_live": False, "all_associations_observed": bool(slots) and len(selected_slots) == len(roles)
            and all(s["status"] == "associated_observed" for s in slots)}


def workspace_view(registry):
    """Called inside the snapshot read transaction; performs no writes."""
    return _view(registry, _load(registry))


def read_workspace(registry, payload, *, resolve=False):
    action = "workspace.resolve" if resolve else "workspace.read"
    validate_workspace_payload(action, payload)
    registry.check_project_identity(payload["expected_project_id"])
    view = workspace_view(registry)
    if not resolve:
        return view
    scope = payload.get("scope", "project")
    role = payload["role"]
    role_active = role in [r["role"] for r in view["required_roles"]]
    slot = next((s for s in view["slots"] if s["role"] == role and s["scope"] == scope), None)
    resolution = "exact" if slot else "missing"
    candidates = []
    if (role_active or role == "art") and not slot:
        # An exact registry entry without a prepared slot is still a reason not
        # to escape to a general chat. Return candidates for explicit preparation
        # and host verification, without claiming the conversation here.
        candidates = _candidates(registry, role, scope, _slot_id(view["project_id"], role, scope))
        if not candidates and scope != "project":
            slot = next((s for s in view["slots"] if s["role"] == role and s["scope"] == "project"), None)
            if slot:
                resolution = "project_fallback"
    # Older workspaces may have no art slot yet. Only an existing project
    # controller can be offered explicitly; never escape a pending art request.
    if role == "art" and not slot and not candidates:
        general_candidates = _candidates(registry, role, "project", _slot_id(view["project_id"], role, "project"))
        if general_candidates:
            candidates = general_candidates
        elif not any(s["role"] == "art" and s["scope"] in (scope, "project") for s in view["slots"] + view["retired_slots"]):
            controller = next((s for s in view["slots"] if s["role"] == "control" and s["scope"] == "project" and s.get("thread_id")), None)
            if controller:
                slot, resolution = controller, "legacy_control_fallback"
    return {"project_id": view["project_id"], "workspace_revision": view["revision"], "slot": slot,
            "next_action": slot["next_action"] if slot else "prepare", "host_execution": False,
            "execution_authorized": False, "requested_scope": scope,
            "resolved_scope": slot["scope"] if slot else None, "resolution": resolution,
            "role_active": role_active,
            "requested_role": role, "resolved_role": slot["role"] if slot else None,
            "art_setup_needed": role == "art" and (not slot or slot["role"] != "art"),
            "registry_candidates": [{"thread_id": t["thread_id"], "title": t["title"]} for t in candidates],
            "project_fallback_blocked": bool(candidates)}


def _write_state(registry, state):
    from .core import canonical, ConflictError
    registry.db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (SETTINGS_KEY, canonical(state)))
    if _load(registry) != state:
        raise ConflictError("对话工作区读回不一致")
    return _view(registry, state)


def _mutable(registry, action, payload):
    from .core import ConflictError
    validate_workspace_payload(action, payload)
    registry.check_project_identity(payload["expected_project_id"])
    state = _load(registry)
    if payload["base_revision"] != state["revision"]:
        raise ConflictError(f"对话工作区修订冲突: expected={payload['base_revision']}, current={state['revision']}")
    return state


def _candidates(registry, role, scope, slot_id):
    # One registry row has exactly one ownership rule, in precedence order.
    # Never fill two roles from current_control plus a legacy purpose label.
    matches = []
    for thread in registry._list("threads"):
        if thread.get("workspace_slot_id"):
            matched = thread["workspace_slot_id"] == slot_id
        elif thread.get("workspace_role"):
            matched = thread["workspace_role"] == role and thread.get("workspace_scope", thread.get("scope")) == scope
        elif thread.get("current_control"):
            matched = role == "control" and scope == "project"
        else:
            matched = thread.get("purpose") == role and thread.get("scope") == scope
        if matched:
            matches.append(thread)
    return matches


def prepare_workspace(registry, payload):
    from .core import now
    state = _mutable(registry, "workspace.prepare", payload)
    mode, scope = _mode(registry), payload.get("scope", "project")
    if mode not in ROUTE_ROLES:
        raise ValueError("请先明确选择创作路线，再准备主要阶段对话")
    project = registry._project()
    changed = not state["prepared"] or state["workflow_mode"] != mode or state["scope"] != scope
    if "include_art" in payload and payload["include_art"] != state.get("include_art", False):
        state["include_art"] = payload["include_art"]
        changed = True
    for role in _roles(mode, state):
        slot_id = _slot_id(project["project_id"], role, scope)
        existing = next((s for s in state["slots"] if s["slot_id"] == slot_id), None)
        if existing:
            # Another authorized workflow may register the real conversation
            # after preparation. Reconcile only unclaimed slots; an uncertain
            # creation must never silently adopt an unrelated registry row.
            if existing["status"] in ("planned", "failed") and not existing["thread_id"]:
                matches = _candidates(registry, role, scope, slot_id)
                if matches:
                    thread = matches[0] if len(matches) == 1 else None
                    existing.update(status="registered" if thread else "conflict",
                                    thread_id=thread["thread_id"] if thread else None,
                                    registry_status="registered" if thread else "not_registered",
                                    reuse_candidates=[{"thread_id": t["thread_id"], "title": t["title"]} for t in matches],
                                    updated_at=now())
                    if thread:
                        existing["title"] = thread["title"]
                    changed = True
            continue
        matches = _candidates(registry, role, scope, slot_id)
        thread = matches[0] if len(matches) == 1 else None
        state["slots"].append({"slot_id": slot_id, "project_id": project["project_id"], "role": role,
                               "label": ROLES[role], "scope": scope, "title": thread["title"] if thread else project["title"] + "｜" + ROLES[role],
                               "status": "conflict" if len(matches) > 1 else "registered" if thread else "planned",
                               "thread_id": thread["thread_id"] if thread else None, "client_thread_id": None,
                               "request_id": "create-" + slot_id, "registry_status": "registered" if thread else "not_registered",
                               "catalog_binding_status": "unknown", "client_project_status": "unknown", "client_project_id": None,
                               "open_status": "not_observed", "host_observation": None, "observations": [],
                               "reuse_candidates": [{"thread_id": t["thread_id"], "title": t["title"]} for t in matches],
                               "updated_at": now()})
        changed = True
    if changed:
        state.update(prepared=True, workflow_mode=mode, scope=scope, revision=state["revision"] + 1)
        state["initialization_id"] = state["initialization_id"] or "workspace-" + uuid.uuid4().hex
        state["preparations"].append({"op_id": payload["op_id"], "workflow_mode": mode, "scope": scope, "prepared_at": now()})
        return _write_state(registry, state)
    return _view(registry, state)


def record_workspace(registry, payload):
    from .core import ConflictError, now
    state = _mutable(registry, "workspace.record", payload)
    slot = next((s for s in state["slots"] if s["slot_id"] == payload["slot_id"]), None)
    if not slot:
        raise ValueError("对话职责槽位不存在，请先准备工作区")
    event, obs = payload["event"], deepcopy(payload["observation"])
    if obs["request_id"] != slot["request_id"]:
        raise ConflictError("观察不属于该槽位的原始请求")
    if "observed_at" in obs:
        previous = [o["observation"]["observed_at"] for o in slot["observations"] if "observed_at" in o["observation"]]
        if previous and _timestamp(obs["observed_at"]) < max(map(_timestamp, previous)):
            raise ConflictError("迟到观察不能覆盖更新的宿主观察")
    active = slot["role"] in _roles(_mode(registry), state)
    if event == "request_started":
        if not active or slot["status"] not in ("planned", "failed") or slot["thread_id"]:
            raise ConflictError("该槽位不可新建；已有或未知请求必须先核对")
        slot.update(status="requesting", client_thread_id=None)
    elif event == "unknown":
        if slot["thread_id"] or slot["status"] not in ("requesting", "queued", "unknown"):
            raise ConflictError("只有未决创建请求可以记录结果未知")
        slot["status"] = "unknown"
    elif event == "queued":
        if slot["thread_id"] or slot["status"] not in ("requesting", "queued", "unknown"):
            raise ConflictError("排队观察必须属于尚未完成的创建请求")
        if slot["client_thread_id"] and slot["client_thread_id"] != obs["client_thread_id"]:
            raise ConflictError("同一请求的排队标识不一致，请核对，不能换号")
        slot.update(status="queued", client_thread_id=obs["client_thread_id"])
    elif event == "host_confirmed":
        allowed = ("requesting", "queued", "unknown", "host_confirmed", "associated_observed") if obs["origin"] == "created" else ("planned", "registered", "conflict", "host_confirmed", "associated_observed")
        if slot["status"] not in allowed:
            raise ConflictError("宿主创建或复用观察与当前请求状态不符")
        thread_id = obs["thread_id"]
        if slot["client_thread_id"] == thread_id:
            raise ValueError("clientThreadId 不是真实 threadId")
        if slot["thread_id"] and slot["thread_id"] != thread_id:
            raise ConflictError("槽位已经关联其他真实对话；不得静默替换")
        if any(s["slot_id"] != slot["slot_id"] and s["thread_id"] == thread_id for s in state["slots"]):
            raise ConflictError("真实对话已被另一个职责槽位使用")
        previous = next((t for t in registry._list("threads") if t["thread_id"] == thread_id), {})
        data = registry._thread({"thread_id": thread_id, "title": obs["title"], "scope": previous.get("scope", slot["scope"]),
                                 "purpose": previous.get("purpose") or slot["role"], "status": "active", "current_control": slot["role"] == "control"})
        data.update(workspace_slot_id=slot["slot_id"], workspace_role=slot["role"], workspace_scope=slot["scope"],
                    host_observation=deepcopy(obs), host_evidence_level="caller_reported")
        registry._put("threads", "thread_id", thread_id, data)
        slot.update(thread_id=thread_id, title=obs["title"], status="host_confirmed", registry_status="registered",
                    host_observation=deepcopy(obs), reuse_candidates=[])
    elif event == "failed":
        if slot["thread_id"] or slot["status"] not in ("requesting", "queued", "unknown", "failed"):
            raise ConflictError("创建失败不能清除已存在的对话")
        slot["status"] = "failed" if obs["no_thread_created"] else "unknown"
    else:
        if not slot["thread_id"] or not slot["host_observation"] or obs["thread_id"] != slot["thread_id"]:
            raise ConflictError("请先核对同一个真实对话，不能使用排队ID或其他对话")
        if event == "catalog_bound":
            if obs["project_id"] != payload["expected_project_id"]:
                raise ConflictError("宿主报告的本地项目绑定与目标作品不一致")
            slot["catalog_binding_status"] = "host_reported_bound"
        elif event == "client_project_observed":
            slot.update(client_project_id=obs["client_project_id"], client_project_status="host_reported_project" if obs["client_project_id"] else "host_reported_projectless")
        elif event == "opened":
            slot["open_status"] = "host_reported_opened"
        elif event == "open_failed":
            slot["open_status"] = "host_reported_failed"
    if slot["host_observation"] and slot["catalog_binding_status"] == "host_reported_bound" and slot["client_project_status"] != "unknown":
        slot["status"] = "associated_observed"
    slot["observations"].append({"event": event, "observation": obs, "op_id": payload["op_id"], "recorded_at": now()})
    slot["updated_at"] = now()
    state["revision"] += 1
    return _write_state(registry, state)

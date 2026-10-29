"""2.1 conversation routing and independent completion/report views.

No host calls, semantic intent inference, project migration or content approval.
Actor identities and human authorization evidence are caller reported, matching
1170. Core retains operation replay and optimistic transaction boundaries.
"""
from copy import deepcopy


def _known_thread(registry, state, thread_id):
    from .conversations1170 import _parent
    from .core import ConflictError
    parents = [(role, value) for role, value in state["parents"].items() if value["thread_id"] == thread_id]
    topics = [topic for topic in state["topics"] if topic.get("thread_id") == thread_id]
    if len(parents) + len(topics) != 1:
        raise ConflictError("来源或回报对话不是当前项目唯一已核验的真实职责入口")
    if parents:
        role, parent = parents[0]
        _parent(registry, state, role)
        return {"thread_id": thread_id, "role": role, "parent_thread_id": parent["thread_id"], "topic_id": None}
    topic = topics[0]
    parent = _parent(registry, state, topic["parent_role"])
    if topic["parent_thread_id"] != parent["thread_id"]:
        raise ConflictError("来源专题所属部门已改变，不能静默改绑")
    return {"thread_id": thread_id, "role": topic["parent_role"], "parent_thread_id": parent["thread_id"],
            "topic_id": topic["topic_id"]}


def route_request(registry, state, payload):
    from .conversations1170 import _parent, _authorize, _refs, _compatible
    from .core import ConflictError, now
    source = _known_thread(registry, state, payload["actor_thread_id"])
    parent = _parent(registry, state, payload["target_role"])
    _known_thread(registry, state, payload["report_to_thread_id"])
    if source["role"] == payload["target_role"]:
        raise ConflictError("同一职责使用已有专题或直接prepare；不生成自我转交")
    grant = _authorize(registry, state, payload, "route", payload["scope"], parent["thread_id"])
    identity = {key: deepcopy(payload[key]) for key in ("request_id", "original_request", "target_role", "scope",
        "inputs", "deliverable", "report_to_thread_id", "actor_thread_id", "target_artifact_id") if key in payload}
    prior = next((r for r in state.get("routes", []) if r["request_id"] == payload["request_id"]), None)
    if prior:
        if prior["request_identity"] != identity:
            raise ConflictError("同request_id转交内容已冻结；不能换接收人、原话或输入")
        return {"route": prior, "reused": True, "notification_sent": False, "dispatch_allowed": False}
    inputs = _refs(registry, payload["inputs"])
    registry._fresh(inputs)
    if not _compatible(registry, payload["target_role"]):
        raise ConflictError("目标职责与项目既有创作路线不符，须由总控协调")
    route = {"request_id": payload["request_id"], "project_id": registry._project()["project_id"],
        "original_request": payload["original_request"], "source_thread_id": source["thread_id"],
        "source_role": source["role"], "source_topic_id": source["topic_id"],
        "source_parent_thread_id": source["parent_thread_id"], "target_role": payload["target_role"],
        "receiver_thread_id": parent["thread_id"], "client_project_id": parent["client_project_id"],
        "scope": payload["scope"], "original_inputs": deepcopy(inputs), "inputs": inputs,
        "deliverable": payload["deliverable"], "report_to_thread_id": payload["report_to_thread_id"],
        "status": "offered", "execution_topic_id": None, "request_identity": identity,
        "authorization": grant, "history": [], "created_at": now(), "notification_sent": False}
    if "target_artifact_id" in payload:
        route["target_artifact_id"] = payload["target_artifact_id"]
    state.setdefault("routes", []).append(route)
    return {"route": route, "notification_sent": False, "dispatch_allowed": False,
            "next_action": "receive_in_exact_existing_department"}


def accept_route(registry, state, payload):
    from .conversations1170 import _find, _parent, _actor, _authorize, _refs, _compatible
    from .core import ConflictError, now
    route = _find(state.get("routes", []), "request_id", payload["request_id"])
    parent = _parent(registry, state, route["target_role"])
    if parent["thread_id"] != route["receiver_thread_id"]:
        raise ConflictError("转交的准确接收部门已变更，不能静默改绑")
    _actor(payload, parent["thread_id"])
    grant = _authorize(registry, state, payload, "route_accept", route["scope"], parent["thread_id"])
    if route.get("execution_topic_id") or route["status"] == "declined":
        raise ConflictError("已派发或拒绝的转交不能改写接收状态")
    if payload["status"] == "ready":
        if not _compatible(registry, route["target_role"]):
            raise ConflictError("目标职责与当前路线不符，不能标记ready")
        inputs = _refs(registry, payload["inputs"])
        if not all(ref in inputs for ref in route["original_inputs"]):
            raise ConflictError("接收必须保留原转交的准确输入；变更版本须另行明确转交")
        registry._fresh(inputs)
        route["inputs"] = inputs
    elif "inputs" in payload:
        raise ValueError("仅ready可冻结接收输入，其他状态只记录问题和原因")
    route.update(status=payload["status"], brief=payload.get("brief"), questions=deepcopy(payload.get("questions", [])))
    route["history"].append({"status": payload["status"], "brief": payload.get("brief"),
        "questions": deepcopy(payload.get("questions", [])), "inputs": deepcopy(payload.get("inputs")),
        "actor_thread_id": payload["actor_thread_id"], "authorization": grant, "at": now()})
    return {"route": route, "notification_sent": False}


def execution_route(registry, state, payload):
    from .conversations1170 import _find, _parent, _refs
    from .core import ConflictError
    route = _find(state.get("routes", []), "request_id", payload["route_id"])
    parent = _parent(registry, state, route["target_role"])
    if parent["thread_id"] != route["receiver_thread_id"] or route["scope"] != payload["scope"]:
        raise ConflictError("执行专题范围或接收部门与准确转交不符")
    if route["status"] != "ready" or route.get("execution_topic_id"):
        raise ConflictError("执行专题须使用ready且未派发的准确转交")
    if route.get("target_artifact_id") and route["target_artifact_id"] != payload["target_artifact_id"]:
        raise ConflictError("新转交的准确成果目标与执行专题不符，不能静默替换")
    registry._fresh(_refs(registry, route["inputs"]))
    return route


def _recipients(state, topic, record):
    existing = record.get("report_recipients")
    if existing is not None:
        return deepcopy(existing)
    recipients = dict.fromkeys((topic["parent_thread_id"], state["parents"]["control"]["thread_id"],
                               record.get("report_to_thread_id")))
    return [{"thread_id": thread_id, "request_id": None, "status": "pending_authorization"}
            for thread_id in recipients if thread_id]


def _report_view(state, topic, record):
    if not record.get("output_ref") or not record.get("completed_at"):
        return {"report_status": "not_ready", "report_recipients": []}
    recipients = _recipients(state, topic, record)
    purpose = f"completion-{record['round']}-{record['task_id']}"
    for recipient in recipients:
        request = next((r for r in state["outbox"] if r["topic_id"] == topic["topic_id"]
            and r["purpose"] == purpose and r["target_thread_id"] == recipient["thread_id"]), None)
        if request:
            recipient.update(request_id=request["request_id"], status=request["status"])
            recipient.pop("reason", None)
        # A request may be accepted by the host; recipient reading or reviewing
        # the creative result still requires a separate, actual observation.
        recipient["business_processed"] = False
    statuses = {r["status"] for r in recipients}
    status = ("host_accepted" if statuses == {"host_accepted"} else
              next((s for s in ("unknown", "in_flight", "queued", "failed", "pending_authorization", "planned", "cancelled")
                    if s in statuses), "pending_authorization"))
    return {"report_status": status, "report_recipients": recipients}


def derive_topic_progress(topic, task, outbox, parents):
    """Pure, shared read projection for the API and project-file index.

    task is a stored tasks.data dictionary or None, not a host observation.
    Neither returned candidate references nor completion receipts approve content.
    """
    recorded = topic.get("status") == "completed" and bool(topic.get("completed_at"))
    return {"task_status": task["status"] if task else None,
        "task_output_ref": deepcopy(task.get("output")) if task else None,
        "completion_recorded": recorded,
        "needs_completion_record": bool(task and task["status"] == "submitted" and not recorded),
        **_report_view({"outbox": outbox, "parents": parents}, topic, topic)}


def add_business_views(registry, state, result, *, full):
    """Enrich copies only: reading old or submitted tasks never migrates them."""
    tasks = {task["task_id"]: task for task in registry._list("tasks")}
    originals = {topic["topic_id"]: topic for topic in state["topics"]}
    for item in result["topics"]:
        topic = originals[item["topic_id"]]
        task = tasks.get(topic.get("task_id"))
        item.update(derive_topic_progress(topic, task, state["outbox"], state["parents"]))
        if full:
            for history in item.get("task_history", []):
                history.update(_report_view(state, topic, history))
    from .conversations1170 import ROLE_MODULES
    result["role_modules"] = {role: sorted(modules) for role, modules in ROLE_MODULES.items()}
    result["routes"] = deepcopy(state.get("routes", [])) if full else [
        {key: deepcopy(route.get(key)) for key in ("request_id", "source_thread_id", "source_role", "target_role",
             "receiver_thread_id", "scope", "report_to_thread_id", "status", "execution_topic_id", "execution_round",
             "target_artifact_id", "execution_target_artifact_id", "notification_sent")}
        for route in state.get("routes", [])]


def queue_completion_reports(registry, state, payload, topic, record=None):
    from .conversations1170 import _authorize, _request
    record = record if record is not None else topic
    recipients = _recipients(state, topic, record)
    requests = []
    context = {**topic, "round": record["round"]}
    for recipient in recipients:
        purpose = f"completion-{record['round']}-{record['task_id']}"
        existing = next((r for r in state["outbox"] if r["topic_id"] == topic["topic_id"] and
            r["purpose"] == purpose and r["target_thread_id"] == recipient["thread_id"]), None)
        if existing:
            requests.append(existing)
            recipient.update(request_id=existing["request_id"], status=existing["status"])
            continue
        try:
            _authorize(registry, state, payload, "send_message_to_thread", topic["scope"], recipient["thread_id"])
        except ValueError as exc:
            recipient.update(status="pending_authorization", request_id=None, reason=str(exc))
            continue
        _known_thread(registry, state, recipient["thread_id"])
        request = _request(registry, state, payload, context, "send_message_to_thread", purpose, recipient["thread_id"],
            {"project_id": registry._project()["project_id"], "topic_id": topic["topic_id"], "task_id": record["task_id"],
             "output_ref": deepcopy(record["output_ref"]), "sha256": record["output_sha256"], "summary": record["completion_summary"],
             "notice": "任务已提交完整候选；不是用户采用或发布。请按准确引用读取结果。"})
        requests.append(request)
        recipient.update(request_id=request["request_id"], status=request["status"])
        recipient.pop("reason", None)
    record["report_recipients"] = recipients
    return {"topic": topic, "requests": requests, "notification_sent": False, "completion_recorded": True,
            **_report_view(state, topic, record)}


def report_completion(registry, state, payload):
    from .conversations1170 import _find, _parent, _actor, _authorize, _task_matches
    from .core import ConflictError
    topic = _find(state["topics"], "topic_id", payload["topic_id"])
    _parent(registry, state, topic["parent_role"])
    _actor(payload, topic["thread_id"], topic["parent_thread_id"])
    _authorize(registry, state, payload, "report", topic["scope"], topic["thread_id"])
    records = [record for record in [topic, *topic.get("task_history", [])]
               if record.get("task_id") == payload["task_id"] and record.get("completed_at")]
    if len(records) != 1 or records[0].get("output_ref") != payload["output_ref"]:
        raise ConflictError("回报必须引用准确已登记完成的任务与成果，不能替代complete")
    record = records[0]
    task = registry._get("tasks", "task_id", payload["task_id"])
    _task_matches(registry, {**topic, **record}, task, completed=True)
    artifact = registry._artifact(payload["output_ref"]["artifact_id"], payload["output_ref"]["version"])
    if task["status"] != "submitted" or task.get("output") != payload["output_ref"] or not artifact or artifact["sha256"] != record["output_sha256"]:
        raise ConflictError("准确提交成果与完成登记不一致")
    return queue_completion_reports(registry, state, payload, topic, record)

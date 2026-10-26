"""Round-end cloud work-draft outbox. Host observations are not authentication.

No network call, Page edit, approval or background work occurs in this module.
All writes run inside Registry.dispatch's transaction and operation cache.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import uuid

KEY = "cloud1120/v1"
READ_ACTIONS = {"cloud.read"}
WRITE_ACTIONS = {"cloud.configure", "cloud.bind", "cloud.prepare", "cloud.record"}
TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}
ID = {"type": "string", "minLength": 1, "pattern": r"^(?!\s*$)[^\x00-\x1f]{1,240}$"}
HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
REV = {"type": "integer", "minimum": 0}
REF = {"type": "object", "properties": {"artifact_id": ID, "version": {"type": "integer", "minimum": 1}, "sha256": HASH}, "required": ["artifact_id", "version", "sha256"], "additionalProperties": False}


def obj(fields, required=None, **extra):
    return {"type": "object", "properties": fields, "required": list(fields) if required is None else list(required), "additionalProperties": False, **extra}


USER = obj({"source": {"enum": ["conversation", "panel"]}, "reference": ID, "quote": TEXT})
DEST = obj({"kind": {"enum": ["private", "space", "page"]}, "id": ID}, ["kind"], oneOf=[
    {"properties": {"kind": {"const": "private"}}, "not": {"required": ["id"]}},
    {"properties": {"kind": {"enum": ["space", "page"]}}, "required": ["id"]}])
UPDATE = obj({"trigger": {"enum": ["full_draft", "confirmed_revision", "local_only"]}, "user_request": USER, "base_observation_id": ID}, ["trigger", "user_request"])
PAGE = obj({"source": {"const": "host_tool"}, "tool": {"const": "read_page"}, "observed_at": TEXT,
            "page_id": ID, "page_url": {"type": "string", "pattern": "^https://"}, "content": {"type": "string"},
            "whole_page_complete": {"const": True}, "revision": {"type": ["string", "integer", "null"]}},
           ["source", "tool", "observed_at", "page_id", "page_url", "content", "whole_page_complete", "revision"])
EVENTS = {
    "request_started": obj({"request_id": ID}),
    "page_created": obj({"request_id": ID, "source": {"const": "host_tool"}, "tool": {"enum": ["create_page", "read_page"]}, "observed_at": TEXT, "page_id": ID, "page_url": {"type": "string", "pattern": "^https://"}}),
    "preflight": obj({"request_id": ID, **PAGE["properties"]}),
    "verified": obj({"request_id": ID, **PAGE["properties"]}),
    "unknown": obj({"request_id": ID, "reason": TEXT}),
    "failed": obj({"request_id": ID, "reason": TEXT, "no_write_performed": {"const": True}}),
    "conflict": obj({"request_id": ID, "reason": TEXT}),
}
WRITE = {"op_id": ID, "expected_project_id": ID, "base_revision": REV}
SCHEMAS = {
    "cloud.read": obj({"expected_project_id": ID, "artifact_id": ID, "observation_id": ID}, ["expected_project_id"]),
    "cloud.configure": obj({**WRITE, "mode": {"enum": ["round_end", "local_only"]}, "user_request": USER, "destination": DEST}, [*WRITE, "mode", "user_request"]),
    "cloud.bind": obj({**WRITE, "artifact": REF, "user_request": USER, "observation": PAGE}),
    "cloud.prepare": obj({**WRITE, "artifact": REF, **UPDATE["properties"]}, [*WRITE, "artifact", "trigger", "user_request"]),
    "cloud.record": obj({**WRITE, "job_id": ID, "event": {"enum": list(EVENTS)}, "observation": {"type": "object"}},
                        oneOf=[{"properties": {"event": {"const": event}, "observation": schema}} for event, schema in EVENTS.items()]),
}


def action_schemas():
    return deepcopy(SCHEMAS)


def cloud_update_schema():
    return deepcopy(UPDATE)


def _time(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError()
        return result
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("云端 observed_at 必须为带时区的 ISO 8601 时间") from exc


def validate_cloud_payload(action, payload):
    from .action_schemas import validate
    if action not in SCHEMAS:
        raise ValueError("未知云端工作稿操作")
    validate(payload, SCHEMAS[action], "payload")
    observation = payload.get("observation", {})
    if "observed_at" in observation:
        _time(observation["observed_at"])
    if type(observation.get("revision")) is bool:
        raise ValueError("revision 不能使用布尔值")
    return payload


def _load(registry):
    row = registry.db.execute("SELECT value FROM settings WHERE key=?", (KEY,)).fetchone()
    return json.loads(row[0]) if row else {"revision": 0, "policy": {"mode": "round_end", "destination": {"kind": "private"}}, "documents": [], "jobs": [], "observations": []}


def _save(registry, state):
    from .core import canonical
    state["revision"] += 1
    registry.db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (KEY, canonical(state)))


def _check(registry, payload, state):
    from .core import ConflictError
    registry.check_project_identity(payload["expected_project_id"])
    if payload["base_revision"] != state["revision"]:
        raise ConflictError("云稿记录基础版本变化，请先读取最新状态")


def _ref(artifact):
    return {key: artifact[key] for key in ("artifact_id", "version", "sha256")}


def _artifact(registry, reference):
    from .core import ConflictError, content_category, content_hash
    artifact = registry._artifact(reference["artifact_id"], reference["version"])
    if not artifact or artifact["sha256"] != reference["sha256"] or content_hash(artifact["content"]) != reference["sha256"]:
        raise ConflictError("云稿来源必须为真实准确成果版本和正文摘要")
    if registry._artifact(artifact["artifact_id"])["version"] != artifact["version"]:
        raise ConflictError("旧成果版本不能准备新的云稿写入")
    if not isinstance(artifact["content"], str) or not artifact["content"].strip() or content_category(artifact) not in {"outline", "novel", "character_bio", "style", "source_script", "script", "director", "vfx", "asset", "video_prompt", "research"}:
        raise ValueError("仅完整创作文本成果可准备云端工作稿；讨论记录或云观察不适用")
    return artifact


def _document(registry, state, artifact):
    from .core import canonical, content_category
    found = next((d for d in state["documents"] if d["artifact_id"] == artifact["artifact_id"] and d["scope"] == artifact["scope"]), None)
    if found:
        return found
    identity = [registry._project()["project_id"], artifact["artifact_id"], artifact["scope"]]
    doc = {"document_id": "cloud-" + hashlib.sha256(canonical(identity).encode("utf-8")).hexdigest()[:32],
           "artifact_id": artifact["artifact_id"], "scope": artifact["scope"], "category": content_category(artifact),
           "page_id": None, "page_url": None, "last_synced_ref": None, "last_synced_sha256": None,
           "last_observation_id": None, "last_observed_at": None,
           "known_revision": None, "known_revision_sha256": None}
    state["documents"].append(doc)
    return doc


def _next(state, job):
    if job["status"] in {"synced", "superseded"}:
        return "done"
    if state["policy"]["mode"] == "local_only":
        return "local_only"
    if job["status"] in {"unknown", "requesting", "awaiting_readback"}:
        return "readback_existing" if job.get("page_id") else "recover_creation"
    if job["status"] == "conflict":
        return "reconcile_cloud_changes"
    if job["status"] == "failed":
        return "prepare_retry"
    unresolved = [j for j in state["jobs"] if j["document_id"] == job["document_id"] and j["job_id"] != job["job_id"] and j["status"] in {"requesting", "awaiting_readback", "unknown"}]
    if unresolved:
        return "resolve_previous"
    return "preflight" if job.get("page_id") and not job.get("preflight") else "claim"


def _job_view(state, job):
    result = deepcopy(job)
    result["next_action"] = _next(state, job)
    # Every body belongs to the immutable artifact or explicit observation read.
    result.pop("history", None)
    return result


def _view(registry, state):
    return {"project_id": registry._project()["project_id"], "revision": state["revision"],
            "policy": deepcopy(state["policy"]), "documents": deepcopy(state["documents"]),
            "jobs": [_job_view(state, j) for j in state["jobs"]], "host_execution": False,
            "background_sync": False, "evidence_level": "host_reported_observations", "observations_are_live": False}


def cloud_summary(registry):
    return _view(registry, _load(registry))


def guard_legacy_page_write(registry, page_id, *, binding=False):
    """Keep legacy total-draft and new per-artifact writers from overlapping."""
    from .core import ConflictError
    state = _load(registry)
    if binding and any(d["page_id"] == page_id for d in state["documents"]):
        raise ConflictError("该 Page 已用于准确成果工作稿，不能另作分类总稿覆盖目标")
    if any(j["page_id"] == page_id and j["status"] in {"requesting", "awaiting_readback", "unknown"} for j in state["jobs"]):
        raise ConflictError("该 Page 存在未完成的工作稿写入；先读回原请求")


def read_cloud(registry, payload):
    validate_cloud_payload("cloud.read", payload)
    registry.check_project_identity(payload["expected_project_id"])
    with registry.lock:
        state = _load(registry)
        result = _view(registry, state)
        if "artifact_id" in payload:
            result["documents"] = [d for d in result["documents"] if d["artifact_id"] == payload["artifact_id"]]
            result["jobs"] = [j for j in result["jobs"] if j["artifact"]["artifact_id"] == payload["artifact_id"]]
        if "observation_id" in payload:
            observation = next((o for o in state["observations"] if o["observation_id"] == payload["observation_id"]), None)
            if not observation:
                raise ValueError("云稿观察不存在")
            if "artifact_id" in payload and not any(d["document_id"] == observation["document_id"] for d in result["documents"]):
                raise ValueError("云稿观察与成果范围不匹配")
            result["observation"] = deepcopy(observation)
        return result


def configure_cloud(registry, payload):
    validate_cloud_payload("cloud.configure", payload)
    state = _load(registry); _check(registry, payload, state)
    state["policy"].update(mode=payload["mode"], user_request=deepcopy(payload["user_request"]))
    if "destination" in payload:
        state["policy"]["destination"] = deepcopy(payload["destination"])
    _save(registry, state)
    return _view(registry, state)


def _observe(state, doc, observation, job=None):
    from .core import ConflictError, content_hash
    timestamp = _time(observation["observed_at"])
    if doc["last_observed_at"] and timestamp < _time(doc["last_observed_at"]):
        raise ConflictError("不能使用早于最后观察的云稿")
    if job and timestamp < _time(job["created_at"]):
        raise ConflictError("云稿观察早于本次同步请求")
    actual_hash = content_hash(observation["content"])
    revision = observation["revision"]
    known_revision = doc.get("known_revision")
    if type(revision) is int and type(known_revision) is int and revision < known_revision:
        raise ConflictError("云端修订早于该 Page 已知版本，不能用新的观察时间包装旧正文")
    if revision is not None:
        for previous in state["observations"]:
            if previous["document_id"] == doc["document_id"] and type(previous["revision"]) is type(revision) and previous["revision"] == revision and previous["sha256"] != actual_hash:
                raise ConflictError("同一已知云端修订出现不同完整正文，须重新核对实际 Page")
    # Only actual integer revisions have a known ordering. Null and opaque
    # tokens do not erase that watermark or acquire an invented ordering.
    if type(revision) is int:
        doc.update(known_revision=revision, known_revision_sha256=actual_hash)
    data = {**deepcopy(observation), "observation_id": "observation-" + uuid.uuid4().hex,
            "document_id": doc["document_id"], "sha256": actual_hash}
    data.pop("request_id", None)
    state["observations"].append(data)
    doc.update(last_observation_id=data["observation_id"], last_observed_at=observation["observed_at"])
    return data


def _unique_page(registry, state, doc, page_id):
    from .core import ConflictError
    if doc["page_id"] and doc["page_id"] != page_id:
        raise ConflictError("既有工作稿 Page 不可由普通操作替换")
    if any(d["document_id"] != doc["document_id"] and d["page_id"] == page_id for d in state["documents"]):
        raise ConflictError("同一 Page 已关联另一准确成果，不能把单章写入其他文档")
    if any(b.get("page_id") == page_id for b in registry._list("master_bindings")):
        raise ConflictError("该 Page 已用于分类总稿；不能将单成果工作稿作为整稿覆盖")


def bind_cloud(registry, payload):
    validate_cloud_payload("cloud.bind", payload)
    state = _load(registry); _check(registry, payload, state)
    artifact = _artifact(registry, payload["artifact"])
    doc = _document(registry, state, artifact)
    observation = payload["observation"]
    _unique_page(registry, state, doc, observation["page_id"])
    if any(j["document_id"] == doc["document_id"] and j["status"] in {"requesting", "awaiting_readback", "unknown"} for j in state["jobs"]):
        from .core import ConflictError
        raise ConflictError("先核查未决云稿请求，不能通过绑定绕过恢复")
    doc.update(page_id=observation["page_id"], page_url=observation["page_url"])
    observed = _observe(state, doc, observation)
    doc["binding_user_request"] = deepcopy(payload["user_request"])
    for waiting in state["jobs"]:
        if waiting["document_id"] == doc["document_id"] and waiting["status"] in {"prepared", "awaiting_read", "conflict"}:
            # Binding is target identity, not permission to overwrite its body.
            # Keep the original baseline unless prepare explicitly names this
            # source observation; preflight will detect unconfirmed contents.
            waiting.update(page_id=doc["page_id"], page_url=doc["page_url"], status="awaiting_read", preflight=None)
    _save(registry, state)
    return {"project_id": registry._project()["project_id"], "revision": state["revision"], "document": deepcopy(doc),
            "observation_id": observed["observation_id"], "sha256": observed["sha256"], "host_execution": False}


def _prepare(registry, state, artifact, update):
    from .core import ConflictError, now
    if update["trigger"] == "local_only" or state["policy"]["mode"] == "local_only":
        return {"status": "local_only", "skip_reason": "local_only", "artifact": _ref(artifact), "host_execution": False}
    doc = _document(registry, state, artifact)
    same = next((j for j in state["jobs"] if j["document_id"] == doc["document_id"] and j["artifact"] == _ref(artifact) and j["status"] not in {"failed", "superseded"}
                 and not (j["status"] in {"prepared", "awaiting_read", "conflict"} and update.get("base_observation_id") and update["base_observation_id"] != j.get("base_observation_id"))), None)
    if same:
        return _job_view(state, same)
    base = doc["last_synced_sha256"]
    if update.get("base_observation_id"):
        observation = next((o for o in state["observations"] if o["observation_id"] == update["base_observation_id"]), None)
        if not observation or observation["document_id"] != doc["document_id"] or observation["page_id"] != doc["page_id"]:
            raise ConflictError("修订来源观察不属于该准确工作稿")
        if observation["observation_id"] != doc["last_observation_id"]:
            raise ConflictError("修订必须使用该工作稿最后完整观察作为来源")
        base = observation["sha256"]
    # A merely saved later draft can supersede only work that never started.
    for older in state["jobs"]:
        if older["document_id"] == doc["document_id"] and older["status"] in {"prepared", "awaiting_read", "conflict"}:
            older["status"] = "superseded"
            older.setdefault("history", []).append({"event": "superseded_before_send", "by_artifact": _ref(artifact), "at": now()})
    job = {"job_id": "job-" + uuid.uuid4().hex, "request_id": "request-" + uuid.uuid4().hex,
           "creation_key": str(uuid.uuid4()), "document_id": doc["document_id"], "artifact": _ref(artifact),
           "scope": artifact["scope"], "category": doc["category"], "trigger": update["trigger"],
           "user_request": deepcopy(update["user_request"]), "base_observation_id": update.get("base_observation_id"),
           "title": str(artifact.get("metadata", {}).get("title") or artifact["artifact_id"]),
           "destination": deepcopy(state["policy"]["destination"]), "page_id": doc["page_id"], "page_url": doc["page_url"],
           "base_sha256": base, "status": "awaiting_read" if doc["page_id"] else "prepared",
           "created_at": now(), "preflight": None, "history": []}
    state["jobs"].append(job)
    return _job_view(state, job)


def prepare_cloud(registry, payload):
    validate_cloud_payload("cloud.prepare", payload)
    state = _load(registry); _check(registry, payload, state)
    artifact = _artifact(registry, payload["artifact"])
    result = _prepare(registry, state, artifact, payload)
    _save(registry, state)
    result.update(project_id=registry._project()["project_id"], revision=state["revision"], host_execution=False)
    return result


def prepare_saved_cloud(registry, artifact, update):
    """Called only after saving the complete artifact inside the same transaction."""
    from .action_schemas import validate
    validate(update, UPDATE, "cloud_update")
    artifact = _artifact(registry, _ref(artifact))
    state = _load(registry)
    result = _prepare(registry, state, artifact, update)
    _save(registry, state)
    result.update(project_id=registry._project()["project_id"], revision=state["revision"], host_execution=False)
    return result


def record_cloud(registry, payload):
    from .core import ConflictError, now
    validate_cloud_payload("cloud.record", payload)
    state = _load(registry); _check(registry, payload, state)
    job = next((j for j in state["jobs"] if j["job_id"] == payload["job_id"]), None)
    if not job:
        raise ValueError("云稿请求不存在")
    obs = payload["observation"]; event = payload["event"]
    if obs["request_id"] != job["request_id"]:
        raise ConflictError("云稿 request_id 不符")
    if job["status"] in {"synced", "superseded", "failed"}:
        raise ConflictError("云稿请求已结束；读取当前状态后准备新版本或重试")
    doc = next(d for d in state["documents"] if d["document_id"] == job["document_id"])
    if event == "request_started":
        _artifact(registry, job["artifact"])
        if state["policy"]["mode"] != "round_end":
            raise ConflictError("当前策略仅本地保存，不执行云稿写入")
        if job["status"] not in {"prepared", "awaiting_read"} or _next(state, job) != "claim":
            raise ConflictError("不能重复发送、跳过最新读回或绕过未决云稿请求")
        if job["page_id"] and job["preflight"]["observation_id"] != doc["last_observation_id"]:
            raise ConflictError("发送前观察已不是最新，请重新读取当前云稿")
        if job["page_id"]:
            _unique_page(registry, state, doc, job["page_id"])
            if any(s["page_id"] == job["page_id"] and s["status"] in {"intent", "sent", "unknown"} for s in registry._list("sync")):
                raise ConflictError("该 Page 存在旧同步未决意图，先核查原同步")
        # A preceding create may have settled after this job was queued.
        if doc["page_id"] != job["page_id"]:
            job.update(page_id=doc["page_id"], page_url=doc["page_url"], base_sha256=doc["last_synced_sha256"], preflight=None, status="awaiting_read")
            raise ConflictError("前次创建已确认，请先读取现有 Page 后再处理本轮")
        job["status"] = "requesting"
        job["started_at"] = now()
    elif event == "page_created":
        if job["status"] not in {"requesting", "unknown"} or job["page_id"]:
            raise ConflictError("只有未绑定且已领取/未知创建请求可以登记创建结果")
        if _time(obs["observed_at"]) < _time(job["created_at"]):
            raise ConflictError("创建观察早于本次请求")
        _unique_page(registry, state, doc, obs["page_id"])
        doc.update(page_id=obs["page_id"], page_url=obs["page_url"])
        job.update(page_id=obs["page_id"], page_url=obs["page_url"], status="awaiting_readback")
        # New queued revisions must update this same Page, never create another.
        for waiting in state["jobs"]:
            if waiting["document_id"] == doc["document_id"] and waiting["status"] in {"prepared", "awaiting_read"}:
                waiting.update(page_id=doc["page_id"], page_url=doc["page_url"], status="awaiting_read", preflight=None)
    elif event in {"preflight", "verified"}:
        if not job["page_id"] or obs["page_id"] != job["page_id"]:
            raise ConflictError("观察不属于本次准确 Page")
        if any(j["document_id"] == doc["document_id"] and j["job_id"] != job["job_id"] and j["status"] in {"requesting", "awaiting_readback", "unknown"} for j in state["jobs"]):
            raise ConflictError("同一工作稿的前次写入尚未核查，不能提前确认另一轮同步")
        if event == "preflight" and job["status"] not in {"prepared", "awaiting_read", "conflict"}:
            raise ConflictError("未决写入只能读回核查，不能重做发送前检查")
        if event == "verified" and job["status"] not in {"requesting", "awaiting_readback", "unknown", "awaiting_read"}:
            raise ConflictError("没有可核对的云稿发送或完整当前观察")
        observation = _observe(state, doc, obs, job)
        if event == "preflight":
            # Baseline follows a completed preceding job only if this job did
            # not explicitly freeze a different cloud source observation.
            if not job.get("base_observation_id") and doc["last_synced_sha256"]:
                job["base_sha256"] = doc["last_synced_sha256"]
            if observation["sha256"] == job["artifact"]["sha256"]:
                job["status"] = "synced"
                doc.update(last_synced_ref=deepcopy(job["artifact"]), last_synced_sha256=observation["sha256"])
            elif not job["base_sha256"] or observation["sha256"] != job["base_sha256"]:
                job["status"] = "conflict"
                job["conflict_reason"] = "cloud_changed_or_unconfirmed_baseline"
            else:
                job["preflight"] = {"observation_id": observation["observation_id"], "sha256": observation["sha256"], "observed_at": observation["observed_at"], "revision": obs["revision"]}
                job["status"] = "awaiting_read"
        elif observation["sha256"] != job["artifact"]["sha256"]:
            job.update(status="conflict", conflict_reason="readback_does_not_match_exact_artifact")
        else:
            job["status"] = "synced"
            doc.update(last_synced_ref=deepcopy(job["artifact"]), last_synced_sha256=observation["sha256"])
        job["last_observation_id"] = observation["observation_id"]
    elif event == "unknown":
        if job["status"] not in {"requesting", "awaiting_readback", "unknown"}:
            raise ConflictError("尚未发送的请求不能标记发送结果未知")
        job.update(status="unknown", reason=obs["reason"])
    elif event == "failed":
        if job["status"] in {"unknown", "awaiting_readback"}:
            raise ConflictError("未知结果不能仅凭失败声明清除；须完整读回核查")
        job.update(status="failed", reason=obs["reason"])
    elif event == "conflict":
        if job["status"] in {"requesting", "unknown", "awaiting_readback"}:
            raise ConflictError("已发送或未知请求须以完整读回确定差异")
        job.update(status="conflict", reason=obs["reason"])
    job["history"].append({"event": event, "observation": {k: v for k, v in obs.items() if k != "content"}, "recorded_at": now()})
    _save(registry, state)
    return {"project_id": registry._project()["project_id"], "revision": state["revision"], "document": deepcopy(doc),
            "job": _job_view(state, job), "host_execution": False}

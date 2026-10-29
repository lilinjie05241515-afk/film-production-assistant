"""Exact art-direction alternatives and a single complete style integration.

Comparison/selection do not approve. Protected working-draft text is preserved
byte-for-byte; whether chosen ranges are visual is a host semantic judgment.
"""
from copy import deepcopy
import json
import uuid

KEY = "art1130/v1"
READ_ACTIONS = {"art.read"}
WRITE_ACTIONS = {"art.prepare", "art.select", "art.integrate", "art.revise"}
TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}
ID = {"type": "string", "minLength": 1, "pattern": r"^(?!\s*$)[^\x00-\x1f]{1,240}$"}
REV = {"type": "integer", "minimum": 0}
HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}


def obj(fields, required=None, **extra):
    return {"type": "object", "properties": fields, "required": list(fields) if required is None else list(required), "additionalProperties": False, **extra}


REF = obj({"artifact_id": ID, "version": {"type": "integer", "minimum": 1}, "sha256": HASH})
OPTIONAL_REF = {"oneOf": [REF, {"type": "null"}]}
USER = obj({"source": {"enum": ["conversation", "panel"]}, "reference": ID, "quote": TEXT})
RANGE = obj({"start": REV, "end": {"type": "integer", "minimum": 1}, "quote": TEXT})
EDIT = obj({**RANGE["properties"], "replacement": {"type": "string"}})
REBASE = obj({"previous_inputs": {"type": "array", "items": REF, "minItems": 1},
              "inputs": {"type": "array", "items": REF, "minItems": 1}})
NONVISUAL = obj({key: TEXT for key in ("direction", "performance", "sound", "world_rules")})
WRITE = {"op_id": ID, "expected_project_id": ID, "base_revision": REV}
SCHEMAS = {
    "art.read": obj({"expected_project_id": ID, "comparison_id": ID, "include_content": {"type": "boolean"}}, ["expected_project_id"],
                    oneOf=[{"properties": {"include_content": {"const": True}}, "required": ["comparison_id", "include_content"]},
                           {"properties": {"include_content": {"const": False}}}]),
    "art.prepare": obj({**WRITE, "comparison_id": ID, "title": TEXT, "target_artifact_id": ID,
                        "baseline": OPTIONAL_REF, "working_ref": OPTIONAL_REF, "main": REF, "alternate": REF,
                        "context": {"type": "array", "items": REF, "minItems": 1},
                        "visual_ranges": {"type": "array", "items": RANGE}, "nonvisual_sections": NONVISUAL},
                       [*WRITE, "comparison_id", "title", "target_artifact_id", "baseline", "working_ref", "main", "alternate", "context", "visual_ranges"],
                       oneOf=[{"properties": {"working_ref": {"type": "null"}, "visual_ranges": {"maxItems": 0}}, "required": ["nonvisual_sections"]},
                              {"properties": {"working_ref": REF, "visual_ranges": {"minItems": 1}}, "not": {"required": ["nonvisual_sections"]}}]),
    "art.select": obj({**WRITE, "comparison_id": ID, "choice": {"enum": ["main", "alternate", "fusion"]}, "fusion": REF,
                       "user_request": USER, "synthetic": {"type": "boolean"}}, [*WRITE, "comparison_id", "choice", "user_request", "synthetic"],
                      oneOf=[{"properties": {"choice": {"const": "fusion"}}, "required": ["fusion"]},
                             {"properties": {"choice": {"enum": ["main", "alternate"]}}, "not": {"required": ["fusion"]}}]),
    "art.integrate": obj({**WRITE, "selection_id": ID, "base_version": REV, "task_id": ID, "cloud_update": {"type": "object"}},
                         [*WRITE, "selection_id", "base_version"]),
    "art.revise": obj({**WRITE, "selection_id": {"oneOf": [ID, {"type": "null"}]}, "source_ref": REF, "working_ref": REF, "baseline": OPTIONAL_REF,
                       "base_version": REV, "edits": {"type": "array", "items": EDIT}, "scope_judgment": {"const": "within_baseline"},
                       "reason": TEXT, "user_request": USER, "synthetic": {"type": "boolean"}, "task_id": ID, "cloud_update": {"type": "object"}, "rebase": REBASE},
                      [*WRITE, "selection_id", "source_ref", "working_ref", "baseline", "base_version", "edits", "scope_judgment", "reason", "user_request", "synthetic"]),
}


def action_schemas():
    from .cloud1120 import cloud_update_schema
    result = deepcopy(SCHEMAS)
    result["art.integrate"]["properties"]["cloud_update"] = cloud_update_schema()
    result["art.revise"]["properties"]["cloud_update"] = cloud_update_schema()
    return result


def validate_art_payload(action, payload):
    from .action_schemas import validate
    if action not in SCHEMAS:
        raise ValueError("不支持的美术基准操作")
    validate(payload, action_schemas()[action], "payload")
    ranges = payload.get("visual_ranges", payload.get("edits", []))
    end = 0
    for item in ranges:
        if item["start"] < end or item["end"] <= item["start"] or item["end"] - item["start"] != len(item["quote"]):
            raise ValueError("视觉范围须按顺序、非重叠并与准确quote长度一致")
        end = item["end"]
    return payload


def _load(registry):
    row = registry.db.execute("SELECT value FROM settings WHERE key=?", (KEY,)).fetchone()
    return json.loads(row[0]) if row else {"revision": 0, "comparisons": [], "selections": [], "integrations": [], "active_selection_id": None}


def _store(registry, state):
    from .core import canonical
    state["revision"] += 1
    registry.db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (KEY, canonical(state)))


def _check(registry, state, payload):
    from .core import ConflictError
    registry.check_project_identity(payload["expected_project_id"])
    if state["revision"] != payload["base_revision"]:
        raise ConflictError("美术方案基础版本变化，请读取最新状态")


def _ref(artifact):
    return {key: artifact[key] for key in ("artifact_id", "version", "sha256")}


def _exact(registry, ref):
    from .core import ConflictError, content_hash
    artifact = registry._artifact(ref["artifact_id"], ref["version"])
    if not artifact or artifact["sha256"] != ref["sha256"] or content_hash(artifact["content"]) != ref["sha256"]:
        raise ConflictError("美术来源须为真实准确版本及正文摘要")
    if not isinstance(artifact["content"], str) or not artifact["content"].strip():
        raise ValueError("美术方案与完整基准必须为非空正文")
    return artifact


def _approved(registry):
    ref, status = registry._global_style()
    return (_ref(registry._artifact(ref["artifact_id"], ref["version"])) if ref else None), status


def _comparison(state, comparison_id):
    value = next((c for c in state["comparisons"] if c["comparison_id"] == comparison_id), None)
    if value is None:
        raise ValueError("美术方案对比不存在")
    return value


def _stale(registry, comparison, *, check_working=True):
    reasons = []
    approved, status = _approved(registry)
    if comparison["baseline"] != approved:
        reasons.append("approved_baseline_changed")
    if approved and status == "needs_review":
        reasons.append("approved_baseline_needs_review")
    current = registry._artifact(comparison["target_artifact_id"])
    if check_working and comparison["working_ref"] != (_ref(current) if current else None):
        reasons.append("working_draft_changed")
    for reference in comparison["context"]:
        if registry._dependency_stale(reference):
            reasons.append("context_changed:" + reference["artifact_id"])
    if comparison["working_ref"]:
        for reference in _exact(registry, comparison["working_ref"])["deps"]:
            if registry._dependency_stale(reference):
                reasons.append("working_dependency_changed:" + reference["artifact_id"])
    return reasons


def _require_current(registry, comparison, *, check_working=True):
    from .core import ConflictError
    reasons = _stale(registry, comparison, check_working=check_working)
    if reasons:
        raise ConflictError("美术方案底本已变化：" + ",".join(reasons))


def _proposal(registry, ref, context):
    from .core import ConflictError
    proposal = _exact(registry, ref)
    if proposal["kind"] != "research":
        raise ValueError("主选、备选及融合方案须独立保存为research候选，不直接占用正式style_bible身份")
    if any({"artifact_id": r["artifact_id"], "version": r["version"]} not in proposal["deps"] for r in context):
        raise ConflictError("两套方案必须绑定同一组准确剧本情境context")
    return proposal


def _compose(registry, comparison, selected):
    visual = _exact(registry, selected)["content"]
    if comparison["working_ref"] is None:
        nonvisual = comparison["nonvisual_sections"]
        labels = {"direction": "导演与摄影", "performance": "表演", "sound": "声音", "world_rules": "世界规则"}
        return "# 全剧风格基准\n\n## 视觉基准\n\n" + visual + "\n\n" + "\n\n".join("## " + label + "\n\n" + nonvisual[key] for key, label in labels.items())
    body = _exact(registry, comparison["working_ref"])["content"]
    chunks = []; cursor = 0
    for index, region in enumerate(comparison["visual_ranges"]):
        chunks.append(body[cursor:region["start"]])
        if index == 0:
            chunks.append(visual)
        cursor = region["end"]
    chunks.append(body[cursor:])
    return "".join(chunks)


def _inputs(registry, comparison):
    from .core import ConflictError
    sources = [] if comparison["working_ref"] is None else _exact(registry, comparison["working_ref"])["deps"]
    result = []
    for reference in [*sources, *comparison["context"]]:
        item = {"artifact_id": reference["artifact_id"], "version": reference["version"]}
        existing = next((r for r in result if r["artifact_id"] == item["artifact_id"]), None)
        if existing and existing != item:
            raise ConflictError("原工作稿与新方案情境引用同一来源的不同版本，先核对受保护条款")
        if existing is None:
            result.append(item)
    return result


def _edited(source, edits):
    from .core import ConflictError
    chunks = []; cursor = 0
    for item in edits:
        if source[item["start"]:item["end"]] != item["quote"]:
            raise ConflictError("局部修订quote不等于完整来源的准确切片")
        chunks.extend((source[cursor:item["start"]], item["replacement"]))
        cursor = item["end"]
    if edits and sum(e["end"] - e["start"] for e in edits) >= len(source):
        raise ValueError("基准内局部修订不能作为全稿替换入口；改变方向请准备新方案")
    chunks.append(source[cursor:])
    return "".join(chunks)


def _integration_summary(integration):
    result = deepcopy(integration)
    if "edits" in result:
        result["edits"] = [{"start": e["start"], "end": e["end"]} for e in result["edits"]]
    return result


def art_summary(registry):
    state = _load(registry)
    approved, status = _approved(registry)
    comparisons = []
    for stored in state["comparisons"]:
        c = deepcopy(stored)
        c["visual_ranges"] = [{"start": r["start"], "end": r["end"]} for r in c["visual_ranges"]]
        c.pop("nonvisual_sections", None)
        c["stale_reasons"] = _stale(registry, stored)
        c["required_inputs"] = _inputs(registry, stored)
        comparisons.append(c)
    active = next((s for s in state["selections"] if s["selection_id"] == state["active_selection_id"]), None)
    chain = [i for i in state["integrations"] if i["selection_id"] == state["active_selection_id"]]
    revision_source = chain[-1]["artifact"] if chain else (approved if not state["selections"] else None)
    return {"project_id": registry._project()["project_id"], "revision": state["revision"], "comparisons": comparisons,
            "selections": deepcopy(state["selections"]), "integrations": [_integration_summary(i) for i in state["integrations"]],
            "active_selection_id": state["active_selection_id"], "active_selection": deepcopy(active),
            "revision_source": deepcopy(revision_source),
            "revision_source_kind": "managed_chain" if chain else ("legacy_approved" if revision_source else None),
            "current_style": approved, "current_style_status": status, "selection_is_approval": False,
            "semantic_compliance": "not_assessed", "host_execution": False, "bodies_included": False}


def _read_art(registry, payload):
    validate_art_payload("art.read", payload)
    registry.check_project_identity(payload["expected_project_id"])
    with registry.lock:
        state = _load(registry)
        view = art_summary(registry)
        if "comparison_id" in payload:
            comparison = _comparison(state, payload["comparison_id"])
            view["comparisons"] = [c for c in view["comparisons"] if c["comparison_id"] == comparison["comparison_id"]]
            view["selections"] = [s for s in view["selections"] if s["comparison_id"] == comparison["comparison_id"]]
            view["integrations"] = [i for i in view["integrations"] if i["comparison_id"] == comparison["comparison_id"]]
            if payload.get("include_content"):
                view["integrations"] = deepcopy([i for i in state["integrations"] if i["comparison_id"] == comparison["comparison_id"]])
                view["comparison"] = deepcopy(comparison)
                view["proposals"] = {role: _exact(registry, comparison[role]) for role in ("main", "alternate")}
                view["working_draft"] = _exact(registry, comparison["working_ref"]) if comparison["working_ref"] else None
                active = view["active_selection"]
                if active and active["comparison_id"] == comparison["comparison_id"]:
                    view["selected_proposal"] = _exact(registry, active["selected"])
                    view["integration_preview"] = _compose(registry, comparison, active["selected"])
                view["bodies_included"] = True
        return view


def read_art(registry, payload):
    validate_art_payload("art.read", payload)
    with registry.lock:
        registry.db.execute("BEGIN")
        try:
            result = _read_art(registry, payload)
            registry.db.execute("COMMIT")
            return result
        except Exception:
            registry.db.execute("ROLLBACK")
            raise


def prepare_art(registry, payload):
    from .core import ConflictError, now
    validate_art_payload("art.prepare", payload)
    state = _load(registry); _check(registry, state, payload)
    if any(c["comparison_id"] == payload["comparison_id"] for c in state["comparisons"]):
        raise ConflictError("对比记录不可覆盖；修订方案请保存新准确版本并建立新的对比记录")
    if payload["main"]["artifact_id"] == payload["alternate"]["artifact_id"] or payload["main"]["sha256"] == payload["alternate"]["sha256"]:
        raise ValueError("主选和备选必须有独立身份和不同完整正文")
    if len({r["artifact_id"] for r in payload["context"]}) != len(payload["context"]):
        raise ValueError("同一情境输入不得包含重复成果或多个版本")
    if not any(_exact(registry, r)["kind"] in {"script", "source_script", "screenplay", "novel", "outline", "story"} for r in payload["context"]):
        raise ValueError("方案对比需要一份明确的小说、剧本或大纲情境")
    if any(r["artifact_id"] == payload["target_artifact_id"] for r in payload["context"]):
        raise ValueError("被修订的全剧基准通过baseline/working_ref冻结，不作为自身动态依赖")
    registry._fresh(payload["context"])
    _proposal(registry, payload["main"], payload["context"])
    _proposal(registry, payload["alternate"], payload["context"])
    style_items = [a for a in registry._latest() if a["kind"] == "style_bible" and a["scope"] == "project/style"]
    if style_items and any(a["artifact_id"] != payload["target_artifact_id"] for a in style_items):
        raise ConflictError("全剧风格已有稳定身份，不能新建竞争性正式基准")
    if state["comparisons"] and any(c["target_artifact_id"] != payload["target_artifact_id"] for c in state["comparisons"]):
        raise ConflictError("美术基准目标身份已固定，不因改方向重建成果或云页")
    if payload["working_ref"]:
        working = _exact(registry, payload["working_ref"])
        if working["artifact_id"] != payload["target_artifact_id"] or working["kind"] != "style_bible" or working["scope"] != "project/style":
            raise ConflictError("working_ref 必须为目标全剧基准的完整工作稿")
        for region in payload["visual_ranges"]:
            if working["content"][region["start"]:region["end"]] != region["quote"]:
                raise ConflictError("视觉范围quote不等于完整工作稿的准确切片")
        protected_size = len(working["content"]) - sum(r["end"] - r["start"] for r in payload["visual_ranges"])
        if protected_size <= 0:
            raise ValueError("已有全剧基准不可整篇当纯视觉区域替换；需保留其他专业条款")
    if payload["baseline"]:
        baseline = _exact(registry, payload["baseline"])
        if baseline["artifact_id"] != payload["target_artifact_id"] or baseline["kind"] != "style_bible":
            raise ConflictError("采用基准与目标稳定身份不一致")
    comparison = {k: deepcopy(payload[k]) for k in ("comparison_id", "title", "target_artifact_id", "baseline", "working_ref", "main", "alternate", "context", "visual_ranges")}
    if "nonvisual_sections" in payload:
        comparison["nonvisual_sections"] = deepcopy(payload["nonvisual_sections"])
    comparison.update(created_at=now(), visual_range_classification="host_judgment_not_semantic_proof")
    _require_current(registry, comparison)
    _inputs(registry, comparison)
    state["comparisons"].append(comparison); _store(registry, state)
    return art_summary(registry)


def select_art(registry, payload):
    from .core import ConflictError, now
    validate_art_payload("art.select", payload)
    state = _load(registry); _check(registry, state, payload)
    comparison = _comparison(state, payload["comparison_id"])
    _require_current(registry, comparison)
    if registry._project()["test_only"] and not payload["synthetic"]:
        raise ValueError("TEST项目只能使用synthetic选择，不能冒充用户决定")
    selected = payload.get("fusion") if payload["choice"] == "fusion" else comparison[payload["choice"]]
    proposal = _proposal(registry, selected, comparison["context"])
    if payload["choice"] == "fusion":
        if selected["artifact_id"] in {comparison["main"]["artifact_id"], comparison["alternate"]["artifact_id"]}:
            raise ValueError("融合必须先形成独立完整方案，不直接同时选择主备两份")
        if any({"artifact_id": comparison[role]["artifact_id"], "version": comparison[role]["version"]} not in proposal["deps"] for role in ("main", "alternate")):
            raise ConflictError("融合方案须保留主备双方的准确来源版本")
    selection = {"selection_id": "art-selection-" + uuid.uuid4().hex, "comparison_id": comparison["comparison_id"],
                 "choice": payload["choice"], "selected": deepcopy(selected), "user_request": deepcopy(payload["user_request"]),
                 "synthetic": payload["synthetic"], "selected_at": now(), "approval_status": "selection_only"}
    state["selections"].append(selection); state["active_selection_id"] = selection["selection_id"]
    _store(registry, state)
    return {"project_id": registry._project()["project_id"], "revision": state["revision"], "selection": deepcopy(selection), "selection_is_approval": False}


def integrate_art(registry, payload):
    from .core import ConflictError, content_hash, now
    validate_art_payload("art.integrate", payload)
    state = _load(registry); _check(registry, state, payload)
    selection = next((s for s in state["selections"] if s["selection_id"] == payload["selection_id"]), None)
    if not selection or state["active_selection_id"] != selection["selection_id"]:
        raise ConflictError("只能接续当前明确选中的一套方案")
    comparison = _comparison(state, selection["comparison_id"])
    _require_current(registry, comparison)
    working = comparison["working_ref"]
    if payload["base_version"] != (working["version"] if working else 0):
        raise ConflictError("完整基准工作稿基础版本不符")
    content = _compose(registry, comparison, selection["selected"])
    provenance = {"selection_id": selection["selection_id"], "comparison_id": comparison["comparison_id"],
                  "selected_proposal": deepcopy(selection["selected"]), "baseline": deepcopy(comparison["baseline"]),
                  "working_ref": deepcopy(working), "protected_text_preserved": True,
                  "visual_range_classification": "host_judgment_not_semantic_proof"}
    metadata = deepcopy(_exact(registry, working)["metadata"]) if working else {"title": "全剧风格基准"}
    metadata["art1130"] = provenance
    # Proposals are frozen provenance, not mutable downstream prerequisites.
    # Context references remain full-version dependencies of the style bible.
    deps = _inputs(registry, comparison)
    save = {"op_id": payload["op_id"], "expected_project_id": payload["expected_project_id"],
            "artifact_id": comparison["target_artifact_id"], "kind": "style_bible", "scope": "project/style",
            "content": content, "base_version": payload["base_version"], "metadata": metadata, "deps": deps}
    if "cloud_update" in payload:
        save["cloud_update"] = deepcopy(payload["cloud_update"])
    if payload.get("task_id"):
        task = registry._get("tasks", "task_id", payload["task_id"])
        if task["scope"] != "project/style" or (task.get("artifact_id") and task["artifact_id"] != comparison["target_artifact_id"]):
            raise ConflictError("任务必须属于准确全剧基准范围和稳定成果身份")
        if len(task["inputs"]) != len(deps) or any(dep not in task["inputs"] for dep in deps):
            raise ConflictError("美术任务inputs须等于required_inputs；方案选择另以准确记录冻结，不能混入未选方案或基准自身旧版")
        save["task_id"] = payload["task_id"]
        result = registry._submit(save)
    else:
        result = registry._save(save)
    integration = {"integration_id": "art-integration-" + uuid.uuid4().hex, "selection_id": selection["selection_id"],
                   "kind": "integration",
                   "comparison_id": comparison["comparison_id"], "artifact": _ref(result["artifact"]),
                   "baseline": deepcopy(comparison["baseline"]), "working_ref": deepcopy(working),
                   "selected_proposal": deepcopy(selection["selected"]), "created_at": now(), "approval_status": "candidate"}
    state["integrations"].append(integration); _store(registry, state)
    result.update(art_integration=deepcopy(integration), art_revision=state["revision"], selection_is_approval=False)
    return result


def revise_art(registry, payload):
    from .core import ConflictError, now
    validate_art_payload("art.revise", payload)
    state = _load(registry); _check(registry, state, payload)
    if payload["selection_id"] != state["active_selection_id"]:
        raise ConflictError("局部修订须接续当前选择，不重新猜定视觉方向")
    baseline, status = _approved(registry)
    if payload["baseline"] != baseline or (baseline and status == "needs_review" and "rebase" not in payload):
        raise ConflictError("当前采用基准变化或待复核，先核对基准")
    chain = [i for i in state["integrations"] if i["selection_id"] == payload["selection_id"]]
    if payload["selection_id"] is None and state["selections"]:
        raise ConflictError("已有美术选择，不得以旧基准继承绕过当前方向")
    inherited = not chain and payload["selection_id"] is None and not state["selections"] and baseline == payload["source_ref"]
    if inherited:
        parent = {"comparison_id": None, "selected_proposal": None}
    elif chain and chain[-1]["artifact"] == payload["source_ref"]:
        parent = chain[-1]
    else:
        raise ConflictError("source_ref 须为当前选择最近的完整integrate/revise版本；首次旧项目仅可继承准确已采用基准")
    source = _exact(registry, payload["source_ref"])
    working = _exact(registry, payload["working_ref"])
    latest = registry._artifact(source["artifact_id"])
    if source["kind"] != "style_bible" or source["scope"] != "project/style" or working["artifact_id"] != source["artifact_id"] or _ref(latest) != payload["working_ref"] or payload["base_version"] != working["version"]:
        raise ConflictError("局部修订须使用稳定全剧基准的最新完整工作稿")
    if registry._project()["test_only"] and not payload["synthetic"]:
        raise ValueError("TEST项目不能冒充真人局部修订授权")
    content = _edited(source["content"], payload["edits"])
    if payload["working_ref"] != payload["source_ref"] and working["content"] != content:
        raise ConflictError("云端回灌工作稿与完整来源及明确编辑计划不一致，不覆盖未解释的修改")
    if working["deps"] != source["deps"]:
        raise ConflictError("局部回灌已改变来源依赖，请先核对完整基准与受保护条款")
    deps = _rebase_inputs(registry, source, baseline, status, payload["rebase"]) if "rebase" in payload else deepcopy(source["deps"])
    registry._fresh(deps)
    metadata = deepcopy(working["metadata"])
    metadata["art1130"] = {"selection_id": payload["selection_id"], "comparison_id": parent["comparison_id"],
                           "selected_proposal": deepcopy(parent["selected_proposal"]), "source_ref": deepcopy(payload["source_ref"]),
                           "baseline": deepcopy(baseline), "working_ref": deepcopy(payload["working_ref"]),
                           "legacy_baseline_inherited": inherited,
                           "scope_judgment": "within_baseline", "semantic_compliance": "host_judgment_not_program_proof"}
    if "rebase" in payload:
        metadata["art1130"]["rebase"] = deepcopy(payload["rebase"])
    save = {"op_id": payload["op_id"], "expected_project_id": payload["expected_project_id"], "artifact_id": source["artifact_id"],
            "kind": "style_bible", "scope": "project/style", "content": content, "base_version": payload["base_version"],
            "metadata": metadata, "deps": deps}
    if "cloud_update" in payload: save["cloud_update"] = deepcopy(payload["cloud_update"])
    if payload.get("task_id"):
        task = registry._get("tasks", "task_id", payload["task_id"])
        if task["scope"] != "project/style" or (task.get("artifact_id") and task["artifact_id"] != source["artifact_id"]) or len(task["inputs"]) != len(save["deps"]) or any(dep not in task["inputs"] for dep in save["deps"]):
            raise ConflictError("局部修订任务须锁定准确全剧基准及其完整来源依赖")
        save["task_id"] = payload["task_id"]
        result = registry._submit(save)
    else:
        result = registry._save(save)
    revision = {"integration_id": "art-revision-" + uuid.uuid4().hex, "kind": "revision", "selection_id": payload["selection_id"],
                "comparison_id": parent["comparison_id"], "artifact": _ref(result["artifact"]), "source_ref": deepcopy(payload["source_ref"]),
                "baseline": deepcopy(baseline), "working_ref": deepcopy(payload["working_ref"]), "selected_proposal": deepcopy(parent["selected_proposal"]),
                "edits": deepcopy(payload["edits"]), "reason": payload["reason"], "user_request": deepcopy(payload["user_request"]),
                "scope_judgment": "within_baseline", "semantic_compliance": "host_judgment_not_program_proof", "synthetic": payload["synthetic"],
                "legacy_baseline_inherited": inherited,
                "created_at": now(), "approval_status": "candidate"}
    if "rebase" in payload:
        revision["rebase"] = deepcopy(payload["rebase"])
    state["integrations"].append(revision); _store(registry, state)
    result.update(art_integration=_integration_summary(revision), art_revision=state["revision"], selection_is_approval=False)
    return result


def _rebase_inputs(registry, source, baseline, status, rebase):
    """Advance only exact script sources; never waive external stale inputs."""
    from .core import ConflictError
    original = [_ref(_exact(registry, {**dep, "sha256": registry._artifact(dep["artifact_id"], dep["version"])["sha256"]})) for dep in source["deps"]]
    if not baseline or len(rebase["previous_inputs"]) != len(original) or len({r["artifact_id"] for r in rebase["previous_inputs"]}) != len(original) or any(r not in original for r in rebase["previous_inputs"]):
        raise ConflictError("rebase须完整冻结source原deps及当前真实采用基准")
    if len(rebase["inputs"]) != len(original) or len({r["artifact_id"] for r in rebase["inputs"]}) != len(original) or {r["artifact_id"] for r in rebase["inputs"]} != {r["artifact_id"] for r in original}:
        raise ConflictError("rebase只能逐条更新原来源版本，不能增删真实依赖")
    advanced = {}
    for ref in rebase["inputs"]:
        new = _exact(registry, ref)
        prior = next(r for r in original if r["artifact_id"] == ref["artifact_id"])
        if ref != prior:
            if new["kind"] not in {"script", "screenplay", "source_script"} or new["version"] <= prior["version"]:
                raise ConflictError("此受控rebase只接续更新剧本；其他专业来源变化须独立核对，不能豁免")
            pointer = registry._approved_pointer(new)
            if not pointer or pointer["artifact_id"] != ref["artifact_id"] or pointer["version"] != ref["version"] or pointer["review_status"] != "approved":
                raise ConflictError("rebase推进的新剧本必须为当前已采用且无需复核的准确版本")
            advanced[ref["artifact_id"]] = ref["version"]
    if not advanced:
        raise ConflictError("rebase必须明确接续至少一份更新且已采用的剧本")
    if status == "needs_review":
        adopted = _exact(registry, baseline)
        reason = (registry._approved_pointer(adopted) or {}).get("review_reason", {})
        if advanced.get(reason.get("upstream")) != reason.get("version"):
            raise ConflictError("基准需复核原因不是本次列明的准确剧本更新，不能通过rebase跳过")
    registry._fresh(rebase["inputs"])
    registry._reject_dependency_cycle(rebase["inputs"], source["artifact_id"])
    return [{"artifact_id": r["artifact_id"], "version": r["version"]} for r in rebase["inputs"]]


def guard_style_approval(registry, artifact):
    """A managed style target cannot approve a visual-only or altered candidate."""
    from .core import ConflictError, content_hash
    if artifact["kind"] != "style_bible":
        return
    state = _load(registry)
    if not any(c["target_artifact_id"] == artifact["artifact_id"] for c in state["comparisons"]) and not any(i["artifact"]["artifact_id"] == artifact["artifact_id"] for i in state["integrations"]):
        return
    integration = next((i for i in state["integrations"] if i["artifact"] == _ref(artifact)), None)
    if not integration or integration["selection_id"] != state["active_selection_id"]:
        raise ConflictError("此全剧基准须先按当前所选方案形成完整集成候选，选择本身不等于批准")
    if integration.get("kind") == "revision":
        baseline, status = _approved(registry)
        if baseline != integration["baseline"] or (baseline and status == "needs_review" and "rebase" not in integration):
            raise ConflictError("局部修订所依据的采用基准已变化")
        if "rebase" in integration:
            deps = _rebase_inputs(registry, _exact(registry, integration["source_ref"]), baseline, status, integration["rebase"])
            if artifact["deps"] != deps:
                raise ConflictError("rebase候选真实依赖与完整核对清单不一致")
    else:
        comparison = _comparison(state, integration["comparison_id"])
        _require_current(registry, comparison, check_working=False)
    latest = registry._artifact(artifact["artifact_id"])
    if latest["version"] != artifact["version"]:
        raise ConflictError("当前工作稿已有更新，不直接采用旧集成版本")
    expected = (_edited(_exact(registry, integration["source_ref"])["content"], integration["edits"])
                if integration.get("kind") == "revision" else _compose(registry, comparison, integration["selected_proposal"]))
    if content_hash(expected) != artifact["sha256"] or artifact["content"] != expected:
        raise ConflictError("完整基准与所选方案及受保护原文不一致")

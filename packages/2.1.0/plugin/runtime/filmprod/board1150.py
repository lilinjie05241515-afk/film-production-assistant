"""Read-only production facts and project-local, reversible library organization.

Display metadata never edits creative records, approval pointers or locked inputs.
The Registry owns transactions and the operation journal. Exports use a read-only
Registry and write only an explicitly selected, verified derived package.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
import zipfile
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote

ITEM_PREFIX = "board1150/item/"
CATEGORY_PREFIX = "board1150/categories/"
READ_ACTIONS = {"board.reference", "board.usage", "board.export"}
WRITE_ACTIONS = {"board.item.set", "board.categories.set", "board.items.batch"}
DEFAULT_CATEGORIES = {
    "document": [("idea", "灵感"), ("requirements", "需求"), ("outline", "故事大纲"),
                 ("character_bio", "人物小传"), ("novel", "小说"), ("source_script", "底稿"),
                 ("script", "剧本"), ("director", "导演方案"), ("style", "风格圣经"),
                 ("vfx", "特效方案"), ("research", "研究"), ("asset", "资产提示词"),
                 ("video_prompt", "视频提示词"), ("music", "声音文稿"), ("editing", "制作记录"),
                 ("other", "其他资料")],
    "image": [("character", "人物"), ("scene", "场景"), ("prop", "道具"), ("other", "其他"), ("unclassified", "未分类")],
    "video": [("take", "生成素材"), ("clip", "镜头与片段"), ("final", "成片"), ("unclassified", "未分类")],
    "audio": [("music", "音乐"), ("dialogue", "对白"), ("sfx", "音效"), ("ambience", "环境声"), ("other", "其他"), ("unclassified", "未分类")],
}
NOTICE = "业务记录只读；未记录保持未知。整理名称、分类、标签及资产关联不改变采用、审核或制作锁定。"


def _fields(payload, allowed, required_fields):
    from .core import required
    if not isinstance(payload, dict) or set(payload) - set(allowed):
        raise ValueError("资料管理参数含未知字段；不得通过管理字段改变业务状态")
    required(payload, *required_fields)


def _text(value, name, limit=500, empty=False):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value) or (not empty and not value.strip()):
        raise ValueError(f"{name} 必须为{'可空' if empty else '非空'}单行文字，最多 {limit} 字符")
    return value.strip()


def _revision(value):
    if type(value) is not int or value < 0:
        raise ValueError("base_revision 必须为非负整数")
    return value


def _read(registry, key):
    row = registry.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def _write(registry, key, value):
    from .core import ConflictError, canonical
    registry.db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, canonical(value)))
    if _read(registry, key) != value:
        raise ConflictError("资料管理写入后读回不一致")


def _identity(target_type, target_id, version=None):
    from .core import identifier
    if target_type not in {"artifact", "media"}:
        raise ValueError("target_type 必须为 artifact 或 media")
    identifier(target_id, "target_id")
    result = {"target_type": target_type, "target_id": target_id}
    if target_type == "artifact":
        if type(version) is not int or version < 1:
            raise ValueError("文稿必须指定准确正整数版本")
        result["version"] = version
    elif version is not None:
        raise ValueError("媒体身份不接受文稿版本")
    return result


def _key(identity):
    from .core import canonical
    return ITEM_PREFIX + canonical(identity)


def _trash(registry, identity):
    from .board_management190 import TRASH_PREFIX
    from .core import canonical
    return _read(registry, TRASH_PREFIX + canonical(identity)) or {"deleted": False, "revision": 0}


def is_trashed_ref(registry, reference):
    """Only automatic new selections call this; historical references stay valid."""
    if not reference:
        return False
    identity = _identity("artifact", reference["artifact_id"], reference["version"])
    return bool(_trash(registry, identity).get("deleted"))


def _target(registry, payload, *, verify_original=False):
    from .core import ConflictError, content_hash, required
    required(payload, "expected_project_id", "target_type", "target_id", "expected_sha256")
    registry.check_project_identity(payload["expected_project_id"])
    identity = _identity(payload["target_type"], payload["target_id"], payload.get("version"))
    sha = payload["expected_sha256"]
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("expected_sha256 必须为准确的 SHA-256")
    if identity["target_type"] == "artifact":
        target = registry._artifact(identity["target_id"], identity["version"])
        if not target:
            raise ValueError("所选文稿准确版本不存在")
        if content_hash(target["content"]) != target["sha256"]:
            raise ConflictError("文稿内容摘要与登记不符")
    else:
        target = registry._get("media", "media_id", identity["target_id"])
        if target.get("kind") not in {"image", "video", "audio"}:
            raise ValueError("素材库只管理已登记的图片、视频与音频")
        if verify_original:
            _media_path(registry, target, verify_hash=True)
    if target["sha256"] != sha:
        raise ConflictError("所选准确资料摘要与登记不符")
    return identity, target


def categories_view(registry):
    from .board_management190 import ORDER_PREFIX
    result = {}
    groups = {"document": "content_categories", "image": "asset_types", "video": "video_categories"}
    for kind, definitions in DEFAULT_CATEGORIES.items():
        saved = _read(registry, CATEGORY_PREFIX + kind)
        if saved:
            result[kind] = saved
            continue
        categories = [{"id": ident, "label": label} for ident, label in definitions]
        legacy = _read(registry, ORDER_PREFIX + groups[kind]) if kind in groups else None
        if legacy:
            order = {ident: index for index, ident in enumerate(legacy.get("order", []))}
            categories.sort(key=lambda row: order.get(row["id"], len(order)))
        result[kind] = {"revision": 0, "categories": categories,
                        **({"legacy_order_revision": legacy["revision"]} if legacy else {})}
    return result


def set_categories(registry, payload):
    from .core import ConflictError, now
    fields = {"op_id", "expected_project_id", "media_kind", "categories", "base_revision"}
    _fields(payload, fields, fields)
    registry.check_project_identity(payload["expected_project_id"])
    kind = payload["media_kind"]
    if not isinstance(kind, str) or kind not in DEFAULT_CATEGORIES:
        raise ValueError("media_kind 必须为 document/image/video/audio")
    previous = categories_view(registry)[kind]
    if _revision(payload["base_revision"]) != previous["revision"]:
        raise ConflictError("分类管理已变化，请刷新后重试")
    rows = payload["categories"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
        raise ValueError("分类必须为 1 至 200 项数组")
    cleaned = []
    for row in rows:
        _fields(row, {"id", "label"}, {"id", "label"})
        ident = _text(row["id"], "分类 ID", 100)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", ident):
            raise ValueError("分类 ID 使用字母数字及 ._-，显示名称可以使用中文")
        cleaned.append({"id": ident, "label": _text(row["label"], "分类名称", 100)})
    ids = [row["id"] for row in cleaned]
    if len(set(ids)) != len(ids) or not {row["id"] for row in previous["categories"]}.issubset(ids):
        raise ValueError("分类 ID 不可重复或移除；可修改名称、排序或新增，避免断开已有分类")
    entry = {"revision": previous["revision"] + 1, "categories": cleaned, "updated_at": now()}
    _write(registry, CATEGORY_PREFIX + kind, entry)
    return {"media_kind": kind, "entry": entry, "management_only": True, "readback_verified": True,
            "management_change": {"before": previous, "after": entry}}


def _legacy(registry, identity, target):
    from .core import canonical, content_category
    metadata = target.get("metadata", {})
    if identity["target_type"] == "artifact":
        from .presentation import SETTINGS_PREFIX
        presentation = _read(registry, SETTINGS_PREFIX + canonical([identity["target_id"], identity["version"]])) or {}
        if presentation.get("sha256") != target["sha256"]:
            presentation = {}
        category = presentation.get("display_category") or content_category(target)
        title = presentation.get("title") or metadata.get("title") or identity["target_id"]
        kind = "document"
        archived = bool(presentation.get("archived"))
    else:
        kind = target["kind"]
        field = {"image": "asset_type", "video": "video_category", "audio": "audio_category"}[kind]
        category = metadata.get(field, "unclassified")
        title = metadata.get("title") or identity["target_id"]
        archived = False
    if not isinstance(category, str) or category not in {row["id"] for row in categories_view(registry)[kind]["categories"]}:
        category = "other" if kind == "document" else "unclassified"
    asset_id = metadata.get("asset_id")
    if not isinstance(asset_id, str) or not asset_id.strip():
        asset_id = None
    return {"title": str(title), "category_id": category, "tags": [], "asset_id": asset_id,
            "media_kind": kind, "revision": 0, "archived": archived}


def set_item(registry, payload):
    from .core import ConflictError, now
    fields = {"op_id", "expected_project_id", "target_type", "target_id", "version", "expected_sha256", "base_revision", "title", "category_id", "tags", "asset_id"}
    _fields(payload, fields, fields - {"version", "asset_id"})
    identity, target = _target(registry, payload, verify_original=True)
    previous = _read(registry, _key(identity)) or _legacy(registry, identity, target)
    if _revision(payload["base_revision"]) != previous["revision"]:
        raise ConflictError("资料展示信息已变化，请刷新后重试")
    kind = "document" if identity["target_type"] == "artifact" else target["kind"]
    category = _text(payload["category_id"], "分类 ID", 100)
    if category not in {row["id"] for row in categories_view(registry)[kind]["categories"]}:
        raise ValueError("所选分类不属于这类资料；正文与媒体分类不能混用")
    tags = payload["tags"]
    if not isinstance(tags, list) or len(tags) > 50:
        raise ValueError("标签必须为不超过 50 项的文字数组")
    tags = [_text(tag, "标签", 100) for tag in tags]
    if len(set(tags)) != len(tags):
        raise ValueError("标签不可重复")
    asset_id = payload.get("asset_id", previous.get("asset_id"))
    if asset_id is not None:
        asset_id = _text(asset_id, "稳定资产身份", 240, empty=True) or None
    entry = {**identity, "sha256": target["sha256"], "media_kind": kind,
             "title": _text(payload["title"], "显示名称"), "category_id": category, "tags": tags,
             "asset_id": asset_id, "revision": previous["revision"] + 1, "updated_at": now()}
    _write(registry, _key(identity), entry)
    return {"entry": entry, "management_only": True, "readback_verified": True,
            "management_change": {"before": previous, "after": entry}, "notice": NOTICE}


def batch_items(registry, payload):
    from .board_management190 import set_trash
    fields = {"op_id", "expected_project_id", "operation", "items"}
    _fields(payload, fields, fields)
    registry.check_project_identity(payload["expected_project_id"])
    operation, items = payload["operation"], payload["items"]
    if operation not in {"organize", "trash"} or not isinstance(items, list) or not 1 <= len(items) <= 200:
        raise ValueError("批量操作为 organize/trash，必须明确选择 1 至 200 项")
    results, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or "op_id" in item or "expected_project_id" in item:
            raise ValueError("批量条目不能覆盖操作身份或项目身份")
        identity = _identity(item.get("target_type"), item.get("target_id"), item.get("version"))
        key = _key(identity)
        if key in seen:
            raise ValueError("批量选择不得重复准确资料")
        seen.add(key)
        request = {**item, "op_id": payload["op_id"], "expected_project_id": payload["expected_project_id"]}
        results.append(set_item(registry, request) if operation == "organize" else set_trash(registry, request))
    return {"items": results, "selected_count": len(items), "management_only": True,
            "atomic": True, "readback_verified": True, "notice": NOTICE}


def _artifact_ref(target):
    return {key: target[key] for key in ("artifact_id", "version", "sha256")}


def _all_artifacts(registry):
    return [registry._artifact(row[0], row[1]) for row in registry.db.execute("SELECT artifact_id,version FROM artifacts ORDER BY artifact_id,version")]


def _matches(reference, target):
    return isinstance(reference, dict) and reference.get("artifact_id") == target.get("artifact_id") and reference.get("version") == target.get("version") and (not reference.get("sha256") or reference["sha256"] == target["sha256"])


def usage_view(registry, identity, target, *, all_artifacts=None, tasks=None):
    """Only explicit registry edges are evidence; never infer links from names."""
    artifacts = all_artifacts if all_artifacts is not None else _all_artifacts(registry)
    tasks = registry._list("tasks") if tasks is None else tasks
    dependents, locked, masters = [], [], []
    if identity["target_type"] == "artifact":
        for artifact in artifacts:
            if any(_matches(ref, target) for ref in artifact.get("deps", [])):
                dependents.append({**_artifact_ref(artifact), "scope": artifact["scope"], "relation": "exact_dependency"})
            binding = artifact.get("metadata", {}).get("style_reference", {})
            if _matches(binding.get("artifact"), target):
                dependents.append({**_artifact_ref(artifact), "scope": artifact["scope"], "relation": "frozen_style_reference"})
        for task in tasks:
            if any(_matches(ref, target) for ref in task.get("inputs", [])) or _matches(task.get("style_binding", {}).get("artifact"), target):
                locked.append({"task_id": task["task_id"], "scope": task["scope"], "status": task["status"],
                               "thread_id": task.get("thread_id"), "relation": "frozen_task_input"})
        for row in registry.db.execute("SELECT data FROM master_revisions ORDER BY category,version"):
            master = json.loads(row[0])
            if any(_matches(ref, target) for ref in master.get("segments", [])):
                masters.append({"category": master["category"], "version": master["version"], "relation": "assembled_master"})
    else:
        for artifact in artifacts:
            if artifact.get("metadata", {}).get("source_media_id") == identity["target_id"]:
                adoption = _adoption(registry, _identity("artifact", artifact["artifact_id"], artifact["version"]), artifact, registry._list("decisions"))
                review_ids = _exact_review_ids(registry, artifact)
                dependents.append({**_artifact_ref(artifact), "scope": artifact["scope"], "relation": "registered_source_media",
                                   "adoption_status": adoption["status"], "adoption_record_ids": [record["decision_id"] for record in adoption["records"]],
                                   "review_status": "needs_review" if artifact.get("status") == "needs_review" else "recorded" if review_ids else "not_recorded",
                                   "review_record_ids": review_ids, "media_adoption_inferred": False})
    return {"artifacts": dependents, "tasks": locked, "masters": masters,
            "external_usage": "unknown", "evidence": "explicit_registry_edges_only"}


def _adoption(registry, identity, target, decisions):
    if identity["target_type"] != "artifact":
        return {"status": "not_recorded", "records": [], "latest_adopted_version": None}
    records = [{key: deepcopy(value) for key, value in decision.items() if key != "sealed_content"}
               for decision in decisions if _matches(decision, target) and decision.get("sealed_sha256") in {None, target["sha256"]} and decision.get("decision") == "adopt"]
    pointer = registry._approved_pointer(target)
    current = bool(pointer and pointer["artifact_id"] == target["artifact_id"] and pointer["version"] == target["version"])
    full_records = [record for record in records if record.get("scope") == target["scope"] and record.get("updates_master") is True]
    return {"status": "current_adopted" if current else "historical_adopted" if full_records else "scope_adopted" if records else "not_recorded", "records": records,
            "latest_adopted_version": pointer["version"] if pointer and pointer["artifact_id"] == target["artifact_id"] else None,
            "current_pointer": {key: pointer[key] for key in ("artifact_id", "version", "scope", "review_status") if key in pointer} if pointer else None}


def _exact_review_ids(registry, target):
    from .screenwriting1130 import KEY
    from .delivery1110 import PREFIX
    identifiers = []
    feedbacks = (_read(registry, KEY) or {}).get("feedbacks", [])
    identifiers.extend(row["feedback_id"] for row in feedbacks if _matches(row.get("script"), target))
    for row in registry.db.execute("SELECT value FROM settings WHERE substr(key,1,?)=?", (len(PREFIX), PREFIX)):
        state = json.loads(row[0])
        identifiers.extend(review["review_id"] for review in state.get("reviews", []) if _matches(review.get("artifact"), target))
    return identifiers


def _batch_task_sources(registry):
    """Only an adopted, explicit current batch-to-task mapping proves this link."""
    sources = {}
    for row in registry.db.execute("SELECT data FROM approved_segments"):
        pointer = json.loads(row[0])
        artifact = registry._artifact(pointer["artifact_id"], pointer["version"])
        if not artifact or pointer.get("review_status") != "approved":
            continue
        metadata = artifact.get("metadata", {})
        batch = metadata.get("batch")
        if not isinstance(batch, dict) or not (batch.get("current") is True or metadata.get("current_batch") is True):
            continue
        task_ids = batch.get("task_ids")
        if not isinstance(task_ids, list) or any(not isinstance(task_id, str) or not task_id.strip() for task_id in task_ids):
            continue
        for task_id in task_ids:
            sources.setdefault(task_id, []).append(_artifact_ref(artifact))
    return sources


def _item_view(registry, identity, target, *, decisions=None, tasks=None):
    decisions = registry._list("decisions") if decisions is None else decisions
    tasks = registry._list("tasks") if tasks is None else tasks
    metadata = target.get("metadata", {})
    legacy = _legacy(registry, identity, target)
    entry = _read(registry, _key(identity)) or legacy
    if entry.get("sha256") not in {None, target["sha256"]}:
        entry = _legacy(registry, identity, target)
    trash = _trash(registry, identity)
    adoption = _adoption(registry, identity, target, decisions)
    locked = []
    production_locked = []
    latest = None
    roles = []
    if identity["target_type"] == "artifact":
        latest = registry._artifact(identity["target_id"])["version"]
        for task in tasks:
            if any(_matches(ref, target) for ref in task.get("inputs", [])) or _matches(task.get("style_binding", {}).get("artifact"), target):
                locked.append({"task_id": task["task_id"], "scope": task["scope"], "status": task["status"], "thread_id": task.get("thread_id"), "module": task.get("module")})
        batch_sources = _batch_task_sources(registry)
        production_locked = [{**task, "batch_sources": batch_sources[task["task_id"]]} for task in locked
                             if task["task_id"] in batch_sources and task["status"] != "cancelled"]
        if identity["version"] == latest:
            roles.append("latest_working")
        if identity["version"] == adoption["latest_adopted_version"]:
            roles.append("latest_adopted")
        if locked:
            roles.append("task_input_locked")
        if production_locked:
            roles.append("production_locked")
    reasons = []
    if target.get("status") == "needs_review":
        reasons.append("registered_needs_review")
    if identity["target_type"] == "artifact":
        for ref in target.get("deps", []):
            if registry._dependency_stale(ref):
                reasons.append("upstream_changed:" + ref["artifact_id"] + "@" + str(ref["version"]))
    pointer = adoption.get("current_pointer")
    if pointer and pointer.get("artifact_id") == identity["target_id"] and pointer.get("version") == identity.get("version") and pointer.get("review_status") == "needs_review":
        reasons.append("adopted_version_needs_review")
    review_ids = _exact_review_ids(registry, target) if identity["target_type"] == "artifact" else []
    return {**identity, **{key: deepcopy(entry.get(key)) for key in ("title", "category_id", "tags", "asset_id", "revision")},
            "sha256": target["sha256"], "kind": target["kind"], "media_kind": "document" if identity["target_type"] == "artifact" else target["kind"],
            "scope": target.get("scope") or metadata.get("scope"), "created_at": target.get("created_at") or target.get("registered_at"),
            "path": target.get("path"), "source_path": metadata.get("original_source_path") or target.get("source_path"),
            "registration_source_path": target.get("source_path"), "size_bytes": target.get("size_bytes"),
            "source_note": metadata.get("source_note"),
            "deleted": bool(trash.get("deleted")), "trash_revision": trash.get("revision", 0),
            "legacy_archived": legacy["archived"],
            "version_roles": roles, "latest_working_version": latest, "latest_adopted_version": adoption["latest_adopted_version"],
            "locked_by": locked, "production_locked_by": production_locked,
            "production_lock_status": "recorded" if production_locked else "not_recorded",
            "adoption": adoption, "review_status": "needs_review" if reasons else "recorded" if review_ids else "not_recorded",
            "review_record_ids": review_ids,
            "needs_review_reasons": reasons, "structure": {key: deepcopy(metadata[key]) for key in ("chapter", "episode", "scene") if key in metadata},
            "registered_source": {key: deepcopy(metadata[key]) for key in ("source", "source_reference", "thread_id", "page_id", "page_url", "reference_role") if key in metadata},
            "management_association_only": True}


def _review_entries(registry, snapshot, items):
    entries = []
    for decision in snapshot.get("decisions", []):
        target = registry._artifact(decision["artifact_id"], decision["version"])
        if not target:
            continue
        latest = registry._artifact(decision["artifact_id"])
        entries.append({"record_type": "adoption" if decision.get("decision") == "adopt" else "decision", "record_id": decision["decision_id"],
                        "artifact_ref": _artifact_ref(target), "scope": decision.get("scope"), "status": decision.get("decision"),
                        "source": deepcopy(decision.get("user_authorization")) or {"reference": decision.get("evidence"), "actor": decision.get("actor"), "synthetic": decision.get("synthetic")},
                        "observed_at": decision.get("created_at"), "details": {key: deepcopy(value) for key, value in decision.items() if key != "sealed_content"},
                        "latest_version": latest["version"], "applies_to_latest": latest["version"] == target["version"]})
    for feedback in snapshot.get("screenwriting", {}).get("feedbacks", []):
        ref = feedback["script"]
        latest = registry._artifact(ref["artifact_id"])
        entries.append({"record_type": "feedback", "record_id": feedback["feedback_id"], "artifact_ref": deepcopy(ref),
                        "scope": feedback["scope"], "status": feedback["status"], "source": deepcopy(feedback["source"]),
                        "observed_at": feedback.get("resolved_at") or feedback["created_at"], "details": deepcopy(feedback),
                        "latest_version": latest["version"], "applies_to_latest": ref["version"] == latest["version"],
                        "revised_ref": deepcopy(feedback.get("revised_script")), "new_version_review": "not_recorded"})
    from .delivery1110 import PREFIX
    for row in registry.db.execute("SELECT value FROM settings WHERE substr(key,1,?)=? ORDER BY key", (len(PREFIX), PREFIX)):
        state = json.loads(row[0])
        for review in state.get("reviews", []):
            ref = review["artifact"]
            target = registry._artifact(ref["artifact_id"], ref["version"])
            latest = registry._artifact(ref["artifact_id"])
            summary = next((item for item in snapshot.get("delivery", {}).get("items", []) if item["delivery_id"] == state["delivery_id"]), {})
            is_latest_review = bool(state["reviews"] and review["review_id"] == state["reviews"][-1]["review_id"])
            entries.append({"record_type": "professional_review", "record_id": review["review_id"], "artifact_ref": deepcopy(ref),
                            "scope": target["scope"] if target else None, "status": summary.get("status", "recorded") if is_latest_review else "historical_record",
                            "source": deepcopy(review.get("reviewer")), "observed_at": review.get("reviewed_at"), "details": deepcopy(review),
                            "latest_version": latest["version"] if latest else None, "applies_to_latest": bool(latest and latest["version"] == ref["version"]),
                            "stale_reasons": summary.get("stale_reasons", []) if is_latest_review else [], "approval_inferred": False})
    for item in items:
        if item["target_type"] == "artifact" and item["needs_review_reasons"]:
            entries.append({"record_type": "needs_review", "record_id": item["target_id"] + "@" + str(item["version"]),
                            "artifact_ref": {"artifact_id": item["target_id"], "version": item["version"], "sha256": item["sha256"]},
                            "scope": item["scope"], "status": "needs_review", "source": {"reference": "registry_exact_dependencies"},
                            "observed_at": snapshot.get("observed_at"), "details": {"reasons": item["needs_review_reasons"]},
                            "latest_version": item["latest_working_version"], "applies_to_latest": item["version"] == item["latest_working_version"]})
    for item in items:
        exact = [entry for entry in entries if entry["artifact_ref"]["artifact_id"] == item["target_id"] and entry["artifact_ref"]["version"] == item.get("version")]
        if item["review_status"] == "not_recorded" and any(entry["record_type"] in {"feedback", "professional_review"} for entry in exact):
            item["review_status"] = "recorded"
    for entry in entries:
        if entry["record_type"] == "feedback" and entry.get("revised_ref"):
            revision = entry["revised_ref"]
            reviews = [record for record in entries if record["record_type"] == "professional_review" and record["artifact_ref"] == revision]
            entry["new_version_review"] = "recorded" if reviews else "not_recorded"
            entry["new_version_review_records"] = [{"record_id": record["record_id"], "status": record["status"],
                                                    "artifact_ref": deepcopy(record["artifact_ref"]), "source": deepcopy(record["source"]),
                                                    "stale_reasons": record.get("stale_reasons", [])} for record in reviews]
    return {"entries": entries, "notice": "意见已处理不等于新版复核通过；旧版本结论不会套用于新版。没有记录时显示未记录。"}


def filter_new_input_suggestions(registry, workflow):
    """Keep adopted stage facts, but do not recommend recycled new inputs."""
    for key in ("stages", "optional_stages", "preproduction_stages"):
        for stage in workflow.get(key, []):
            for suggestion in stage.get("dependency_suggestions", []):
                recycled = [ref for ref in suggestion.get("refs", []) if is_trashed_ref(registry, ref)]
                if not recycled:
                    continue
                suggestion["refs"] = [ref for ref in suggestion["refs"] if not is_trashed_ref(registry, ref)]
                suggestion["recycled_refs"] = recycled
                if not suggestion["refs"] and suggestion.get("status") == "available":
                    suggestion["status"] = "recycled"
                suggestion["note"] += " 已回收版本不作为新工作的默认建议输入；历史采用和冻结输入保留。"


def _overview(registry, snapshot, items):
    baseline, representative, batches, scope_rows, episodes = [], [], [], [], {}
    from .core import content_category
    for item in items:
        if item["target_type"] != "artifact" or item["deleted"]:
            continue
        target = registry._artifact(item["target_id"], item["version"])
        metadata = target.get("metadata", {})
        if content_category(target) in {"outline", "character_bio", "style"} and (target["scope"] == "project" or target["scope"].startswith("project/")):
            baseline.append(deepcopy(item))
        source = _artifact_ref(target)
        evidence = {"source": source, "adoption_status": item["adoption"]["status"]}
        if "latest_working" in item["version_roles"] or "latest_adopted" in item["version_roles"]:
            if _meaningful_scope(metadata.get("production_scope")):
                scope_rows.append({"value": deepcopy(metadata["production_scope"]), **evidence})
            if _meaningful_scope(metadata.get("representative_chapter")):
                representative.append({"value": deepcopy(metadata["representative_chapter"]), **evidence})
            batch = metadata.get("batch")
            if _meaningful_scope(batch) and (metadata.get("current_batch") is True or isinstance(batch, dict) and batch.get("current") is True):
                batches.append({"value": deepcopy(batch), **evidence})
        for field in ("episode", "chapter"):
            value = metadata.get(field)
            if isinstance(value, str) and value.strip():
                ident, title = value.strip(), value.strip()
            elif isinstance(value, dict) and isinstance(value.get("id") or value.get("title"), str):
                ident = value.get("id") or value["title"]
                title = value.get("title") or ident
            else:
                continue
            key = field + ":" + ident
            group = episodes.setdefault(key, {"id": ident, "title": title, "source_field": field, "items": [], "completion_status": "unknown"})
            group["items"].append(deepcopy(item))
            break
    next_steps = []
    for task in snapshot.get("tasks", []):
        if task.get("checkpoints"):
            checkpoint = task["checkpoints"][-1]
            if checkpoint.get("next_step"):
                next_steps.append({"task_id": task["task_id"], "scope": task["scope"], "text": checkpoint["next_step"], "source": "checkpoint", "task_status": task["status"]})
    return {"global_baseline": baseline, "representative_chapters": representative, "current_batches": batches,
            "declared_scope": scope_rows, "episodes": list(episodes.values()), "next_steps": next_steps,
            "scope_status": "declared" if scope_rows else "not_recorded", "completion_percent": None,
            "notice": "仅展示明确登记的范围和版本。章节从 metadata.episode/chapter 读取；范围、代表章节及当前批次无登记则未知。文件数不代表全剧完成。"}


def _meaningful_scope(value):
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().lower() not in {"unknown", "not_recorded", "未知", "未记录", "未声明"}
    if type(value) in (int, float):
        return value > 0
    if isinstance(value, list):
        return any(_meaningful_scope(item) for item in value)
    if isinstance(value, dict):
        return any(_meaningful_scope(item) for key, item in value.items() if key not in {"current", "status"})
    return False


def library_view(registry, snapshot):
    from .core import NON_APPROVABLE_KINDS
    artifacts, decisions, tasks = snapshot.get("artifacts", []), snapshot.get("decisions", []), snapshot.get("tasks", [])
    selected = {(item["artifact_id"], item["version"]): item for item in artifacts if item["kind"] not in NON_APPROVABLE_KINDS}
    for item in snapshot.get("approved_artifacts", []):
        if item["kind"] not in NON_APPROVABLE_KINDS:
            selected[(item["artifact_id"], item["version"])] = item
    for task in tasks:
        refs = list(task.get("inputs", []))
        if task.get("style_binding", {}).get("artifact"):
            refs.append(task["style_binding"]["artifact"])
        for ref in refs:
            item = registry._artifact(ref["artifact_id"], ref["version"])
            if item and item["kind"] not in NON_APPROVABLE_KINDS:
                selected[(item["artifact_id"], item["version"])] = item
    # Trashed older versions remain visible and recoverable even when they are
    # neither latest, adopted nor part of a task.
    for entry in snapshot.get("trash", {}).get("entries", []):
        if entry.get("deleted") and entry["target_type"] == "artifact":
            item = registry._artifact(entry["target_id"], entry["version"])
            if item:
                selected[(item["artifact_id"], item["version"])] = item
    items = [_item_view(registry, _identity("artifact", item["artifact_id"], item["version"]), item, decisions=decisions, tasks=tasks)
             for item in selected.values()]
    items.extend(_item_view(registry, _identity("media", media["media_id"]), media, decisions=decisions, tasks=tasks)
                 for media in snapshot.get("media", []) if media["kind"] in {"image", "video", "audio"})
    reviews = _review_entries(registry, snapshot, items)
    counts = {kind: sum(item["media_kind"] == kind and not item["deleted"] for item in items) for kind in DEFAULT_CATEGORIES}
    counts["asset_prompt_text"] = sum(item["target_type"] == "artifact" and item["kind"] in {"asset", "prompt"} and not item["deleted"] for item in items)
    groups = {}
    for item in items:
        if item.get("asset_id"):
            groups.setdefault(item["asset_id"], []).append({key: item[key] for key in ("target_type", "target_id", "version", "sha256") if key in item})
    return {"schema_version": 1, "categories": categories_view(registry), "items": items, "counts": counts,
            "asset_groups": [{"asset_id": ident, "items": refs, "association": "explicit_registry", "adoption_inferred": False} for ident, refs in groups.items()],
            "reviews": reviews, "overview": _overview(registry, snapshot, items), "read_only_facts": True, "notice": NOTICE}


def reference(registry, payload):
    allowed = {"expected_project_id", "target_type", "target_id", "version", "expected_sha256"}
    _fields(payload, allowed, allowed - {"version"})
    identity, target = _target(registry, payload)
    item = _item_view(registry, identity, target)
    project_id = registry._project()["project_id"]
    exact = {"schema": "film-reference/v1", "project_id": project_id, **identity, "sha256": target["sha256"], "scope": item["scope"]}
    uri = "filmref:v1/" + quote(project_id, safe="") + "/" + identity["target_type"] + "/" + quote(identity["target_id"], safe="")
    if identity["target_type"] == "artifact":
        uri += "@" + str(identity["version"])
    uri += "/" + target["sha256"]
    exact["uri"] = uri
    text = json.dumps({**exact, "adoption_status": item["adoption"]["status"], "version_roles": item["version_roles"],
                       "locked_by": item["locked_by"], "production_locked_by": item["production_locked_by"],
                       "production_lock_status": item["production_lock_status"]}, ensure_ascii=False, indent=2)
    return {"reference": exact, "reference_text": text, "item": item, "usage": usage_view(registry, identity, target), "read_only": True, "copy_sends_message": False}


def _media_path(registry, media, verify_hash=False):
    from .core import ConflictError
    from .documents import _plain_path
    relative = media.get("path")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ConflictError("原件路径不是项目内相对路径")
    root = registry.root.resolve(strict=True)
    path = root / relative
    if not path.resolve(strict=True).is_relative_to(root):
        raise ConflictError("原件路径越出本项目")
    current = root
    _plain_path(root, directory=True)
    for part in Path(relative).parts:
        if part in {".", ".."}:
            raise ConflictError("原件路径不规范")
        current = current / part
        _plain_path(current, directory=current != path)
    if verify_hash:
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != media["sha256"]:
                raise ConflictError("原件字节与登记 SHA-256 不符")
    return path


def _package_directory(registry, create=False):
    from .documents import _plain_path
    root = registry.root.resolve(strict=True)
    _plain_path(root, directory=True)
    directory = root
    for part in ("11-导出", "资料包"):
        directory = directory / part
        if create:
            directory.mkdir(exist_ok=True)
        _plain_path(directory, directory=True)
        if directory.resolve(strict=True) != directory or not directory.is_relative_to(root):
            raise ValueError("资料包导出目录必须为项目内固定普通目录")
    return directory


def export_selected(registry, payload):
    from .core import ConflictError, canonical, content_hash
    from .documents import _plain_path
    _fields(payload, {"expected_project_id", "items"}, {"expected_project_id", "items"})
    registry.check_project_identity(payload["expected_project_id"])
    if not isinstance(payload["items"], list) or not 1 <= len(payload["items"]) <= 200:
        raise ValueError("导出必须明确选择 1 至 200 项准确资料")
    selected, seen = [], set()
    for value in payload["items"]:
        _fields(value, {"target_type", "target_id", "version", "expected_sha256"}, {"target_type", "target_id", "expected_sha256"})
        identity, target = _target(registry, {**value, "expected_project_id": payload["expected_project_id"]}, verify_original=True)
        if _key(identity) in seen:
            raise ValueError("导出选择不得重复")
        seen.add(_key(identity))
        item = _item_view(registry, identity, target)
        selected.append((identity, target, item))
    manifest = {"schema": "film-library-export/v1", "project_id": payload["expected_project_id"],
                "items": [entry[2] for entry in selected], "notice": "准确原件/正文的派生副本；不修改原记录，不代表新采用或发布。"}
    package_id = content_hash(manifest)
    directory = _package_directory(registry, create=True)
    target_path = directory / ("film-library-" + package_id + ".zip")
    temporary = directory / (".film-library-" + uuid.uuid4().hex + ".tmp")
    created = False
    try:
        _package_directory(registry)
        with temporary.open("xb") as outer:
            with zipfile.ZipFile(outer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                def write_bytes(name, body):
                    info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, body)
                write_bytes("资料清单.json", (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
                for index, (identity, target, item) in enumerate(selected, 1):
                    safe_id = re.sub(r"[^\w.-]", "_", identity["target_id"])[:60]
                    prefix = f"{index:03d}_{safe_id}_{target['sha256'][:16]}"
                    if identity["target_type"] == "artifact":
                        body = target["content"].encode("utf-8") if isinstance(target["content"], str) else canonical(target["content"]).encode("utf-8")
                        if hashlib.sha256(body).hexdigest() != target["sha256"]:
                            raise ConflictError("导出正文摘要不一致")
                        write_bytes("文稿/" + prefix + f"_v{identity['version']}" + (".md" if isinstance(target["content"], str) else ".json"), body)
                    else:
                        path = _media_path(registry, target, verify_hash=True)
                        name = "素材/" + item["media_kind"] + "/" + prefix + path.suffix.lower()
                        info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0)); info.compress_type = zipfile.ZIP_STORED
                        before = path.stat(); digest = hashlib.sha256()
                        with path.open("rb") as source, archive.open(info, "w", force_zip64=True) as output:
                            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                                digest.update(chunk); output.write(chunk)
                        after = _plain_path(path, directory=False)
                        if digest.hexdigest() != target["sha256"] or (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                            raise ConflictError("导出过程中原件发生变化")
            outer.flush(); os.fsync(outer.fileno())
        _plain_path(temporary, directory=False)
        with temporary.open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        size = temporary.stat().st_size
        _package_directory(registry)
        if not target_path.exists():
            try:
                if os.name == "nt":
                    os.rename(temporary, target_path)
                else:
                    os.link(temporary, target_path, follow_symlinks=False); temporary.unlink()
                created = True
            except FileExistsError:
                pass
        _plain_path(target_path, directory=False)
        _package_directory(registry)
        with target_path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != sha or target_path.stat().st_size != size:
            raise ConflictError("同名导出包与本次内容不同，保留已有包并拒绝覆盖")
        with zipfile.ZipFile(target_path) as archive:
            if archive.testzip() is not None:
                raise ConflictError("导出包读回校验失败")
        return {"saved_verified": True, "readback_verified": True, "local_path": str(target_path), "export_dir": str(directory),
                "filename": target_path.name, "sha256": sha, "size_bytes": size, "selected_count": len(selected),
                "status": "created" if created else "reused", "registry_changed": False, "project_id": payload["expected_project_id"]}
    finally:
        if temporary.exists():
            _plain_path(temporary, directory=False)
            temporary.unlink()

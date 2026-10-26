"""Project-local board preferences and reversible, exact-identity trash markers.

These operations only organize the board. Immutable content, original files,
approvals and exact downstream references are retained; no disk space is freed.
Core owns the transaction, operation journal, project identity and event audit.
"""
from __future__ import annotations

import json
import re


ORDER_PREFIX = "board-order/v1/"
TRASH_PREFIX = "board-trash/v1/"
ORDER_GROUPS = {
    "content_categories": ("idea", "requirements", "outline", "novel", "character_bio",
                           "style", "source_script", "script", "director", "vfx", "asset", "video_prompt"),
    "asset_types": ("character", "scene", "prop", "other", "unclassified"),
    "video_categories": ("take", "clip", "final", "unclassified"),
}
REFERENCE_NOTICE = "此操作只改变看板列表；已有批准、总稿、任务及精确依赖仍保留，不解除引用，不释放磁盘空间。"


def _read_setting(registry, key):
    row = registry.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def _write_setting(registry, key, entry):
    from .core import ConflictError, canonical

    registry.db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, canonical(entry)))
    readback = _read_setting(registry, key)
    if readback != entry:
        raise ConflictError("看板管理写入后读回不一致")
    return readback


def _revision(payload):
    value = payload["base_revision"]
    if type(value) is not int or value < 0:
        raise ValueError("base_revision 必须为非负整数")
    return value


def set_board_order(registry, payload):
    from .core import ConflictError, now, required

    fields = {"op_id", "expected_project_id", "group", "order", "base_revision"}
    required(payload, *fields)
    if set(payload) != fields:
        raise ValueError("分类排序仅接受 op_id、expected_project_id、group、order、base_revision")
    registry.check_project_identity(payload["expected_project_id"])
    group = payload["group"]
    if not isinstance(group, str) or group not in ORDER_GROUPS:
        raise ValueError("group 必须为 content_categories、asset_types 或 video_categories")
    order = payload["order"]
    if not isinstance(order, list) or any(not isinstance(value, str) for value in order):
        raise ValueError("order 必须为分类 ID 数组")
    expected = ORDER_GROUPS[group]
    if len(order) != len(expected) or set(order) != set(expected):
        raise ValueError("order 必须完整包含此组所有分类各一次，不能缺少、重复或增加分类")
    base = _revision(payload)
    key = ORDER_PREFIX + group
    previous = _read_setting(registry, key)
    revision = previous["revision"] if previous else 0
    if revision != base:
        raise ConflictError(f"分类排序修订冲突: expected={base}, current={revision}")
    before = previous or {"order": list(expected), "revision": 0}
    entry = {"order": list(order), "revision": revision + 1, "updated_at": now()}
    readback = _write_setting(registry, key, entry)
    return {"group": group, "entry": readback, "management_only": True, "readback_verified": True,
            "management_change": {"before": before, "after": readback}}


def board_order_view(registry):
    groups = {group: _read_setting(registry, ORDER_PREFIX + group) or {"order": list(order), "revision": 0}
              for group, order in ORDER_GROUPS.items()}
    return {"groups": groups, "project_scoped": True, "management_only": True}


def _title(registry, target_type, target):
    """Capture a descriptive label for this marker; it is not a live rename."""
    if target_type == "artifact":
        from .core import canonical
        from .presentation import SETTINGS_PREFIX
        presentation = _read_setting(registry, SETTINGS_PREFIX + canonical([target["artifact_id"], target["version"]]))
        if presentation and presentation.get("sha256") == target["sha256"]:
            label = presentation.get("title")
            if isinstance(label, str) and label.strip():
                return label
    label = target.get("metadata", {}).get("title")
    if isinstance(label, str) and label.strip():
        return label
    return target.get("artifact_id") or target["media_id"]


def set_trash(registry, payload):
    from .core import ConflictError, canonical, identifier, now, required

    fields = {"op_id", "expected_project_id", "target_type", "target_id", "expected_sha256", "base_revision", "deleted"}
    required(payload, *fields)
    target_type = payload["target_type"]
    if target_type not in ("artifact", "media"):
        raise ValueError("target_type 必须为 artifact 或 media")
    if target_type == "artifact":
        fields.add("version")
        required(payload, "version")
        if type(payload["version"]) is not int or payload["version"] < 1:
            raise ValueError("version 必须为准确正整数")
    if set(payload) != fields:
        raise ValueError("回收站仅接受准确登记身份和管理修订；media 不接受 version，不能传入任意路径")
    registry.check_project_identity(payload["expected_project_id"])
    identifier(payload["target_id"], "target_id")
    sha = payload["expected_sha256"]
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("expected_sha256 必须为准确的64位小写摘要")
    base = _revision(payload)
    if type(payload["deleted"]) is not bool:
        raise ValueError("deleted 必须为布尔值")
    if target_type == "artifact":
        target = registry._artifact(payload["target_id"], payload["version"])
        if not target:
            raise ValueError("回收站目标成果版本不存在")
        identity = {"target_type": target_type, "target_id": target["artifact_id"], "version": target["version"]}
    else:
        target = registry._get("media", "media_id", payload["target_id"])
        identity = {"target_type": target_type, "target_id": target["media_id"]}
    if target["sha256"] != sha:
        raise ConflictError("回收站目标登记摘要与所选准确版本不符")
    key = TRASH_PREFIX + canonical(identity)
    previous = _read_setting(registry, key)
    revision = previous["revision"] if previous else 0
    if revision != base:
        raise ConflictError(f"回收站修订冲突: expected={base}, current={revision}")
    changed_at = now()
    entry = {**identity, "sha256": sha, "kind": target["kind"], "title": _title(registry, target_type, target),
             "title_snapshot": True, "deleted": payload["deleted"], "revision": revision + 1,
             "deleted_at": changed_at if payload["deleted"] else None, "updated_at": changed_at}
    readback = _write_setting(registry, key, entry)
    before = previous or {**identity, "sha256": sha, "deleted": False, "revision": 0, "deleted_at": None}
    return {"entry": readback, "management_only": True, "readback_verified": True,
            "original_records_retained": True, "disk_space_reclaimed": False,
            "reference_notice": REFERENCE_NOTICE,
            "management_change": {"before": before, "after": readback}}


def trash_view(registry):
    entries = [json.loads(row[0]) for row in registry.db.execute(
        "SELECT value FROM settings WHERE substr(key,1,?)=? ORDER BY key",
        (len(TRASH_PREFIX), TRASH_PREFIX))]
    return {"entries": entries, "version_scoped": True, "management_only": True,
            "original_records_retained": True, "disk_space_reclaimed": False,
            "reference_notice": REFERENCE_NOTICE}

"""Version-scoped board organization, separate from immutable creative content."""
from __future__ import annotations

import json
import re


SETTINGS_PREFIX = "presentation/v1/"
PRESENTATION_CATEGORIES = ("idea", "requirements", "outline", "novel", "character_bio",
                           "source_script", "style", "script", "director", "vfx", "video_prompt")


def set_presentation(registry, payload):
    # Import locally: core owns the transaction and the shared error contract.
    from .core import (CREATIVE_SEGMENT_KINDS, ConflictError, canonical, content_category,
                       identifier, now, required)

    required(payload, "expected_project_id", "artifact_id", "version", "expected_sha256",
             "base_revision", "display_category", "title", "archived")
    registry.check_project_identity(payload["expected_project_id"])
    identifier(payload["artifact_id"], "artifact_id")
    version, base_revision = payload["version"], payload["base_revision"]
    if type(version) is not int or version < 1:
        raise ValueError("version 必须为准确正整数")
    if type(base_revision) is not int or base_revision < 0:
        raise ValueError("base_revision 必须为非负整数")
    sha = payload["expected_sha256"]
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("expected_sha256 必须为准确的64位小写摘要")
    category = payload["display_category"]
    if not isinstance(category, str) or category not in PRESENTATION_CATEGORIES:
        raise ValueError("display_category 必须为普通创作列表分类；资产与研究专页暂不支持展示整理")
    title = payload["title"]
    if not isinstance(title, str) or not title.strip() or len(title) > 500 or any(ord(c) < 32 for c in title):
        raise ValueError("title 必须为非空单行文字，最多500字符")
    if type(payload["archived"]) is not bool:
        raise ValueError("archived 必须为布尔值")

    artifact = registry._artifact(payload["artifact_id"], version)
    if not artifact:
        raise ValueError("展示管理目标成果版本不存在")
    if artifact["kind"] not in CREATIVE_SEGMENT_KINDS:
        raise ValueError("此成果不是可整理的创作内容")
    if content_category(artifact) not in PRESENTATION_CATEGORIES:
        raise ValueError("目标成果不属于普通创作列表；资产与研究专页暂不支持展示整理")
    if artifact["sha256"] != sha:
        raise ConflictError("展示管理目标正文摘要与所选准确版本不符")

    # Each exact content version has its own revision. Settings are ignored by
    # older runtimes, so no schema migration or content-table rewrite is needed.
    key = SETTINGS_PREFIX + canonical([artifact["artifact_id"], version])
    row = registry.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    old = json.loads(row[0]) if row else None
    revision = old["revision"] if old else 0
    if revision != base_revision:
        raise ConflictError(f"展示管理修订冲突: expected={base_revision}, current={revision}")
    entry = {"artifact_id": artifact["artifact_id"], "version": version, "sha256": sha,
             "display_category": category, "title": title, "archived": payload["archived"],
             "revision": revision + 1, "updated_at": now()}
    registry.db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, canonical(entry)))
    readback = json.loads(registry.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()[0])
    if readback != entry:
        raise ConflictError("展示管理读回不一致")
    return {"entry": readback, "presentation_only": True, "readback_verified": True}


def presentation_view(registry):
    """Return exact bindings only; callers must not inherit them by artifact ID."""
    entries = [json.loads(row[0]) for row in registry.db.execute(
        "SELECT value FROM settings WHERE substr(key,1,?)=? ORDER BY key",
        (len(SETTINGS_PREFIX), SETTINGS_PREFIX))]
    return {"entries": entries, "version_scoped": True, "approval_inferred": False,
            "supported_categories": list(PRESENTATION_CATEGORIES)}

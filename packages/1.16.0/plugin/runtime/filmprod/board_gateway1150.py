"""The board's closed management capability, separate from creative tools.

MCP Apps hosts enforce model/app visibility before forwarding a request. This
gateway additionally rejects every non-management action before opening a root.
It is deliberately not a generic dispatcher or a caller-provided origin flag.
"""
from __future__ import annotations

import json
import sqlite3

READ_ACTIONS = frozenset({
    "artifact.get", "artifact.history", "master.history", "planning.read",
    "context.read", "workspace.read", "workspace.resolve", "cloud.read",
    "art.read", "screenwriting.read", "delivery.read", "document.export",
    "document.save", "board.reference", "board.usage", "board.export",
})
WRITE_ACTIONS = frozenset({
    "board.item.set", "board.categories.set", "board.items.batch",
    "board.order.set", "presentation.set", "trash.set", "media.classify", "media.update",
})
MEDIA_ACTIONS = frozenset({
    "choose", "choose_image", "choose_audio", "import", "import_image", "import_audio",
    "preview", "preview_image", "preview_audio", "original",
})
PROJECT_ACTIONS = frozenset({"list", "resolve", "outcome", "register", "relink", "bind", "unbind", "forget"})
ALL_ACTIONS = frozenset({"snapshot", *READ_ACTIONS, *WRITE_ACTIONS,
    *("media." + action for action in MEDIA_ACTIONS),
    *("projects." + action for action in PROJECT_ACTIONS)})


def catalog_read(payload=None, action="list"):
    """Read catalog without creating a catalog or migrating any project."""
    from .projects import ProjectCatalog, catalog_path
    payload = payload or {}
    path = catalog_path()
    if not path.is_file():
        if action == "outcome":
            return {"found": False, "operation": None}
        return {"projects": [], "bindings": [], "resolved_project": None,
                "current_thread_project": None, "client_project": None,
                "resolution": "none", "operations": [], "catalog_path": str(path),
                "persistent": False, "host_context": {key: payload.get(key)
                    for key in ("thread_id", "client_project_id")}}
    catalog = ProjectCatalog.__new__(ProjectCatalog)
    catalog.path = path
    catalog.db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    catalog.db.row_factory = sqlite3.Row
    try:
        return catalog.dispatch(action, payload)
    finally:
        catalog.close()


def response(result, preview=False):
    meta = None
    if preview:
        meta = {"media_preview": result}
        result = {key: value for key, value in result.items()
                  if key not in ("thumbnail_data_uri", "preview_data_uri")}
    value = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, sort_keys=True)}],
             "structuredContent": result}
    if meta is not None:
        value["_meta"] = meta
    return value


def call_board(arguments, default_root, check_root):
    from .core import Registry
    from .projects import ProjectCatalog
    if set(arguments) - {"root", "action", "payload"}:
        raise ValueError("看板只接受 root、action、payload")
    action = arguments.get("action")
    payload = arguments.get("payload", {})
    if not isinstance(action, str) or action not in ALL_ACTIONS:
        raise ValueError("看板不允许此业务操作；请在相应工作对话中处理")
    if not isinstance(payload, dict):
        raise ValueError("payload 必须为对象")
    if action.startswith("projects."):
        project_action = action.removeprefix("projects.")
        if project_action in ("list", "resolve", "outcome"):
            return response(catalog_read(payload, project_action))
        catalog = ProjectCatalog()
        try:
            return response(catalog.dispatch(project_action, payload))
        finally:
            catalog.close()
    context = {key: payload.get(key) for key in ("thread_id", "client_project_id")}
    if action == "snapshot":
        if set(payload) - {"thread_id", "client_project_id", "expected_project_id"}:
            raise ValueError("刷新只接受项目身份和已知聊天关联")
        catalog = catalog_read(context)
        root_text = arguments.get("root") or default_root
        if not root_text:
            selected = catalog.get("resolved_project")
            root_text = selected.get("root") if selected and selected.get("available") else None
        if not root_text:
            return response({"project": None, "project_root": None, "empty_state": True,
                "catalog": catalog, "host_context": context, "board_mode": "management_only"})
        root = check_root(root_text, payload)
        registry = Registry.open_readonly(root)
        try:
            result = registry.snapshot()
        finally:
            registry.close()
        return response({**result, "project_root": str(root), "catalog": catalog,
                         "host_context": context, "board_mode": "management_only"})
    # A selected, stable project identity is mandatory on all board detail and
    # mutation calls, even where an old model tool allows the identity to be absent.
    if not isinstance(payload.get("expected_project_id"), str) or not payload["expected_project_id"]:
        raise ValueError("看板操作缺少打开时的准确项目身份，请刷新")
    root = check_root(arguments.get("root") or default_root, payload)
    media_action = action.removeprefix("media.") if action.startswith("media.") else None
    importing = media_action in ("import", "import_image", "import_audio")
    registry = Registry(root) if action in WRITE_ACTIONS or importing else Registry.open_readonly(root)
    try:
        registry.check_project_identity(payload["expected_project_id"])
        if media_action in MEDIA_ACTIONS:
            from .media120 import media_action as handle_media
            # The board never forwards arbitrary semantic approval metadata on imports.
            if importing:
                allowed = {"op_id", "expected_project_id", "media_id", "path", "kind", "metadata"}
                if set(payload) - allowed:
                    raise ValueError("媒体导入只能登记所选原件和展示信息")
                metadata = payload.get("metadata", {})
                if not isinstance(metadata, dict) or set(metadata) - {"title", "asset_type", "audio_category", "rights_status", "source_note"}:
                    raise ValueError("导入展示信息不能包含审核、采用、依赖或任务决定")
            result = handle_media(registry, media_action, payload)
        else:
            result = registry.dispatch(action, payload)
    finally:
        registry.close()
    return response(result, preview=media_action in ("preview", "preview_image", "preview_audio"))

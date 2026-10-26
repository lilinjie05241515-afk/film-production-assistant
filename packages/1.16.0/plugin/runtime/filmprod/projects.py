"""Explicit local project catalog. No directory scanning or host-chat mutations."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from .core import ConflictError, Registry, canonical, content_hash, identifier, now, required


def catalog_path():
    configured = os.environ.get("FILMPROD_CATALOG_PATH")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise ValueError("FILMPROD_CATALOG_PATH must be absolute")
        return path
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    return base / "FilmProduction/projects.sqlite3"


def project_identity(root):
    """Read identity without opening Registry or silently initializing/migrating."""
    path = Path(root).expanduser()
    if not path.is_absolute():
        raise ValueError("作品目录必须为绝对路径")
    path = path.resolve()
    db_path = path / ".project/registry.sqlite3"
    if not db_path.is_file():
        raise ValueError("目录没有影视项目记录；请明确新建项目")
    connection = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT value FROM settings WHERE key='project'").fetchone()
        if not row:
            raise ValueError("目录的影视项目尚未初始化")
        project = json.loads(row[0])
        required(project, "project_id", "title")
        return {**project, "root": str(path)}
    finally:
        connection.close()


class ProjectCatalog:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else catalog_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS projects(project_id TEXT PRIMARY KEY, root TEXT UNIQUE NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS bindings(kind TEXT NOT NULL, binding_id TEXT NOT NULL, project_id TEXT NOT NULL, PRIMARY KEY(kind,binding_id));
        CREATE TABLE IF NOT EXISTS operations(op_id TEXT PRIMARY KEY, action TEXT NOT NULL, request_hash TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL);
        """)

    def close(self):
        self.db.close()

    def _project(self, project_id):
        row = self.db.execute("SELECT data FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if not row:
            raise ValueError("影视项目未登记")
        return json.loads(row[0])

    def _checked_project(self, project_id):
        project = self._project(project_id)
        try:
            actual = project_identity(project["root"])
            available = actual["project_id"] == project_id
            reason = None if available else "目录项目ID不符，请重新关联"
        except (OSError, ValueError, sqlite3.Error) as exc:
            available, reason = False, str(exc)
        return {**project, "available": available, "unavailable_reason": reason}

    def snapshot(self, p=None):
        p = p or {}
        projects = [self._checked_project(row[0]) for row in self.db.execute("SELECT project_id FROM projects ORDER BY json_extract(data,'$.title'),project_id")]
        bindings = [dict(row) for row in self.db.execute("SELECT * FROM bindings ORDER BY kind,binding_id")]
        by_id = {item["project_id"]: item for item in projects}
        def bound(kind, key):
            match = next((b for b in bindings if b["kind"] == kind and b["binding_id"] == p.get(key)), None)
            return by_id.get(match["project_id"]) if match else None
        thread = bound("thread", "thread_id")
        client = bound("client_project", "client_project_id")
        resolved = thread or client
        operations = [{**dict(row), "result": json.loads(row["result"])} for row in self.db.execute("SELECT op_id,action,result,created_at FROM operations ORDER BY rowid DESC LIMIT 100")]
        return {"projects": projects, "bindings": bindings, "resolved_project": resolved,
                "current_thread_project": thread, "client_project": client,
                "resolution": "thread_binding" if thread else "client_project_binding" if client else "none",
                "operations": operations, "catalog_path": str(self.path), "persistent": True,
                "host_context": {"thread_id": p.get("thread_id"), "client_project_id": p.get("client_project_id")}}

    def _bind(self, project_id, p, preserve_existing=False):
        self._project(project_id)
        found = False
        for kind, key in (("thread", "thread_id"), ("client_project", "client_project_id")):
            if not p.get(key):
                continue
            found = True
            value = identifier(p[key], key)
            previous = self.db.execute("SELECT project_id FROM bindings WHERE kind=? AND binding_id=?", (kind, value)).fetchone()
            if previous and previous[0] != project_id and p.get("replace") is not True:
                if preserve_existing:
                    continue
                raise ConflictError("该聊天/客户端项目已绑定其他影视项目；明确重新关联才可替换")
            if kind == "client_project":
                other = self.db.execute("SELECT binding_id FROM bindings WHERE kind='client_project' AND project_id=? AND binding_id<>?", (project_id, value)).fetchone()
                if other:
                    if preserve_existing:
                        continue
                    raise ConflictError("影视项目已关联一个客户端项目；先明确解除旧关联")
            self.db.execute("INSERT INTO bindings VALUES(?,?,?) ON CONFLICT(kind,binding_id) DO UPDATE SET project_id=excluded.project_id", (kind, value, project_id))
        return found

    def dispatch(self, action, payload=None):
        p = dict(payload or {})
        if action in ("list", "resolve"):
            return self.snapshot(p)
        if action == "outcome":
            required(p, "op_id")
            row = self.db.execute("SELECT op_id,action,result,created_at FROM operations WHERE op_id=?", (p["op_id"],)).fetchone()
            return {"found": bool(row), "operation": {**dict(row), "result": json.loads(row["result"])} if row else None}
        if action not in ("register", "create", "relink", "bind", "unbind", "forget"):
            raise ValueError("不支持的项目登记操作")
        required(p, "op_id")
        identifier(p["op_id"], "op_id")
        request_hash = content_hash({"action": action, "payload": p})
        self.db.execute("BEGIN IMMEDIATE")
        try:
            old = self.db.execute("SELECT request_hash,result FROM operations WHERE op_id=?", (p["op_id"],)).fetchone()
            if old:
                if old[0] != request_hash:
                    raise ConflictError("op_id 已用于不同项目操作")
                self.db.execute("COMMIT")
                return json.loads(old[1])
            result = self._mutate(action, p)
            self.db.execute("INSERT INTO operations VALUES(?,?,?,?,?)", (p["op_id"], action, request_hash, canonical(result), now()))
            self.db.execute("COMMIT")
            return result
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def _mutate(self, action, p):
        result = {}
        # Validate all caller values before project creation can touch disk.
        for key in ("thread_id", "client_project_id"):
            if key in p:
                identifier(p[key], key)
        if "replace" in p and type(p["replace"]) is not bool:
            raise ValueError("replace 必须为布尔值")
        if action in ("register", "create", "relink"):
            required(p, "root")
            root = Path(p["root"]).expanduser()
            if not root.is_absolute():
                raise ValueError("作品目录必须为绝对路径")
            root = root.resolve()
            system = Path(os.environ.get("FILMPROD_SYSTEM_ROOT", Path(__file__).resolve().parents[1])).resolve()
            if root == system or system in root.parents:
                raise ValueError("作品数据必须与系统源代码目录分开")
            if action == "create":
                required(p, "project_id", "title", "test_only")
                identifier(p["project_id"], "project_id")
                if not isinstance(p["title"], str) or not p["title"].strip():
                    raise ValueError("项目名称必须为非空字符串")
                if type(p["test_only"]) is not bool:
                    raise ValueError("test_only 必须为布尔值")
                existing_id = self.db.execute("SELECT root FROM projects WHERE project_id=?", (p["project_id"],)).fetchone()
                if existing_id and Path(existing_id[0]).resolve() != root:
                    raise ConflictError("项目 ID 已登记在另一目录；搬家请使用重新关联")
                # Existing records are always resumed, never reinitialized.
                if (root / ".project/registry.sqlite3").is_file():
                    identity = project_identity(root)
                    if identity["project_id"] != p["project_id"]:
                        raise ConflictError("该目录已属于其他影视项目，请关联已有项目")
                    result["resumed_existing"] = True
                else:
                    if root.exists() and any(root.iterdir()):
                        raise ValueError("新建需要空目录；已有资料请先明确整理为作品目录")
                    registry = Registry(root)
                    try:
                        registry.dispatch("project.init", {"op_id": "catalog-create:" + p["op_id"], "project_id": p["project_id"], "title": p["title"], "test_only": p["test_only"]})
                    finally:
                        registry.close()
            identity = project_identity(root)
            project_id = identity["project_id"]
            existing = self.db.execute("SELECT root FROM projects WHERE project_id=?", (project_id,)).fetchone()
            same_root = self.db.execute("SELECT project_id FROM projects WHERE root=?", (str(root),)).fetchone()
            if same_root and same_root[0] != project_id:
                raise ConflictError("已登记路径的项目身份发生变化；不能静默覆盖")
            if action == "relink":
                required(p, "project_id")
                self._project(p["project_id"])
                if project_id != p["project_id"]:
                    raise ConflictError("重新关联目录的项目 ID 不匹配")
            elif existing and Path(existing[0]).resolve() != root:
                raise ConflictError("项目 ID 已登记在另一目录；搬家请使用重新关联")
            project = {"project_id": project_id, "title": identity["title"], "root": str(root), "test_only": identity.get("test_only", False), "registered_at": now()}
            self.db.execute("INSERT INTO projects VALUES(?,?,?) ON CONFLICT(project_id) DO UPDATE SET root=excluded.root,data=excluded.data", (project_id, str(root), canonical(project)))
            # Context identifies the caller; browsing/registration must not rebind
            # an already associated chat. Explicit bind is the replacement action.
            self._bind(project_id, p, preserve_existing=True)
            result["project"] = project
        elif action == "bind":
            required(p, "project_id")
            if not self._bind(p["project_id"], p):
                raise ValueError("绑定需要真实 thread_id 或 client_project_id")
            result["project"] = self._project(p["project_id"])
        elif action == "unbind":
            required(p, "kind", "binding_id", "project_id")
            if p["kind"] not in ("thread", "client_project"):
                raise ValueError("无效绑定类型")
            row = self.db.execute("SELECT project_id FROM bindings WHERE kind=? AND binding_id=?", (p["kind"], p["binding_id"])).fetchone()
            if not row or row[0] != p["project_id"]:
                raise ConflictError("绑定已变化或不存在")
            self.db.execute("DELETE FROM bindings WHERE kind=? AND binding_id=?", (p["kind"], p["binding_id"]))
            result["unbound"] = True
        elif action == "forget":
            required(p, "project_id")
            project = self._project(p["project_id"])
            # Compare the confirmed catalog record without touching its source
            # directory: unavailable/moved projects must still be removable.
            if "expected_root" in p:
                expected_root = p["expected_root"]
                if not isinstance(expected_root, str) or not expected_root.strip() or not Path(expected_root).is_absolute():
                    raise ValueError("expected_root 必须为登记项目的绝对目录")
                normalize = lambda value: os.path.normcase(os.path.normpath(value))
                if normalize(expected_root) != normalize(project["root"]):
                    raise ConflictError("项目源文件夹登记已变化，请重新打开项目设置后再删除登记")
            if "expected_registered_at" in p:
                expected_time = p["expected_registered_at"]
                if not isinstance(expected_time, str) or not expected_time:
                    raise ValueError("expected_registered_at 必须为原登记时间")
                if expected_time != project.get("registered_at"):
                    raise ConflictError("项目登记已更新，请重新打开项目设置后再删除登记")
            self.db.execute("DELETE FROM bindings WHERE project_id=?", (p["project_id"],))
            self.db.execute("DELETE FROM projects WHERE project_id=?", (p["project_id"],))
            result = {"forgotten": p["project_id"], "source_files_deleted": False}
        # Do not recursively persist prior operation results inside each result.
        state = self.snapshot(p)
        state.pop("operations", None)
        return {**state, **result}

"""Transactional project registry. No model calls, cloud writes or media generation.

All mutable operations require an operation ID. Content revisions are immutable;
decisions, observed cloud state and editor checkpoints have separate records.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import threading
import uuid
import zipfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import __version__
from .assets import add_asset_views, validate_asset_type
from .brainstorm import interface as brainstorm_interface, prepare_with_registry as prepare_brainstorm
from .board_management190 import board_order_view, set_board_order, set_trash, trash_view
from .presentation import presentation_view, set_presentation
from .workflow import GLOBAL_STYLE_SCOPE, MODES, OUTLINE_ORDERS, STYLE_CATEGORIES, STYLE_MODULES, validate_stage, workflow_view
from .workspace1110 import (prepare_workspace, read_workspace, record_workspace,
                            validate_workspace_payload, workspace_view)


class ConflictError(ValueError):
    """Optimistic concurrency or operation identity conflict."""


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def content_hash(content):
    return digest(content.encode("utf-8") if isinstance(content, str) else canonical(content).encode("utf-8"))


def required(p, *keys):
    for key in keys:
        if key not in p or p[key] is None or p[key] == "":
            raise ValueError(f"缺少字段: {key}")


def identifier(value, name="id"):
    if not isinstance(value, str) or not value.strip() or len(value) > 240 or any(ord(c) < 32 for c in value):
        raise ValueError(f"无效 {name}")
    return value


def text_value(value, name):
    if not isinstance(value, str):
        raise ValueError(f"{name} 必须为字符串")
    return value


def item_list(value, name):
    if not isinstance(value, list) or any(not isinstance(item, (str, dict)) for item in value):
        raise ValueError(f"{name} 必须为字符串或对象组成的数组")
    return value


def output_kinds(module):
    """Finite routing aliases; a module never chooses arbitrary output kinds."""
    routes = {
        "idea": {"idea"}, "idea-explorer": {"idea"},
        "requirements": {"requirements"}, "requirements-planner": {"requirements"},
        "screenwriter": {"story", "novel", "outline", "character", "character_bio", "source_script", "script", "screenplay"},
        "story": {"story", "novel", "outline", "character", "character_bio"},
        "novel-master": {"story", "novel", "outline", "character", "character_bio"},
        "screenplay": {"source_script", "script", "screenplay", "character_bio"},
        "novel-to-screenplay": {"source_script", "script", "screenplay", "character_bio"},
        "adaptation": {"source_script", "script", "screenplay", "character_bio"},
        "director-agent": {"director"}, "vfx-agent": {"vfx"},
        "assets": {"asset", "prompt"}, "seedance-prompt": {"asset", "prompt", "video_prompt"},
        "video_prompt": {"video_prompt"},
        "film-analysis": {"research", "analysis", "style_constraints", "style_bible"},
        "research": {"research", "analysis", "style_constraints", "style_bible"},
        "art_director": {"research", "style_bible"}, "film-art-director": {"research", "style_bible"},
        "music": {"cue", "music", "audio"},
        "editing": {"clip", "sequence", "timeline", "final", "subtitle", "audio", "dialogue_audio"},
        "delivery": {"final"},
    }
    return routes.get(module, {module})


CONTENT_CATEGORIES = {
    "idea": "idea", "requirements": "requirements",
    "outline": "outline", "story": "outline", "character": "outline", "novel": "novel",
    "character_bio": "character_bio", "source_script": "source_script", "style_bible": "style",
    "script": "script", "screenplay": "script", "director": "director", "vfx": "vfx",
    "asset": "asset", "prompt": "asset", "video_prompt": "video_prompt", "research": "research", "analysis": "research",
    "style_constraints": "research", "cue": "music", "music": "music", "audio": "music",
    "clip": "editing", "sequence": "editing", "timeline": "editing", "final": "editing",
    "render": "editing", "subtitle": "editing", "dialogue_audio": "editing",
}
CATEGORIES = {"idea", "requirements", "outline", "novel", "character_bio", "source_script", "style", "script", "director", "vfx", "asset", "video_prompt", "research", "music", "editing", "other"}
NON_APPROVABLE_KINDS = {"planning_record", "cloud_working_draft", "pages_observation", "cloud_observation", "render"}
CREATIVE_SEGMENT_KINDS = {"idea", "requirements", "outline", "story", "character", "character_bio", "novel", "source_script", "style_bible", "script", "screenplay", "director", "vfx", "asset", "prompt", "video_prompt", "research", "analysis", "style_constraints"}
TEXT_FILE_KINDS = CREATIVE_SEGMENT_KINDS | {"cue", "subtitle", "dialogue"}


def revision_precedes(value, reference):
    if type(value) is int and type(reference) is int:
        return value < reference
    if isinstance(value, str) and isinstance(reference, str):
        left, right = re.fullmatch(r"(.*?)(\d+)", value), re.fullmatch(r"(.*?)(\d+)", reference)
        if left and right and left[1] == right[1]:
            return int(left[2]) < int(right[2])
    # Opaque host revisions have no fabricated ordering. Binding updates below
    # still require an exact compare-and-swap against the intent's base.
    return False


def content_category(artifact):
    category = artifact.get("metadata", {}).get("category") or CONTENT_CATEGORIES.get(artifact["kind"], "other")
    category = {"assets": "asset"}.get(category, category)
    if category not in CATEGORIES:
        raise ValueError("内容 category 无效")
    return category


def segment_order(artifact):
    order = artifact.get("metadata", {}).get("order")
    if order is None:
        return None
    values = order if isinstance(order, list) else [order]
    if not values or any(type(v) is not int or v < 0 for v in values):
        raise ValueError("metadata.order 必须为非负整数或非空非负整数数组")
    return values


def segment_sort(segment):
    # Explicit chapter/scene/shot indexes first; natural numeric scope order is a fallback.
    natural = tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in re.split(r"(\d+)", segment["scope"]))
    return (segment.get("order") is None, segment.get("order") or [], natural, segment["artifact_id"])


class Registry:
    @classmethod
    def open_readonly(cls, root):
        """Open an existing schema 2 registry without initialization or migration."""
        instance = cls.__new__(cls)
        instance.root = Path(root).expanduser().resolve()
        instance.internal = instance.root / ".project"
        instance.db_path = instance.internal / "registry.sqlite3"
        if not instance.db_path.is_file():
            raise ValueError("只读接口需要明确的现存项目登记库；不会创建目录或数据库")
        instance.lock = threading.RLock()
        instance.read_only = True
        instance.db = sqlite3.connect(instance.db_path.as_uri() + "?mode=ro", uri=True, timeout=30, isolation_level=None, check_same_thread=False)
        instance.db.row_factory = sqlite3.Row
        try:
            instance.db.execute("PRAGMA query_only=ON")
            row = instance.db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()
            if not row or json.loads(row[0]) != 2:
                raise ValueError("只读接口需要现存 schema 2 项目；不会建库或迁移旧项目")
        except Exception:
            instance.close()
            raise
        return instance

    def __init__(self, root):
        self.read_only = False
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.internal = self.root / ".project"
        self.internal.mkdir(exist_ok=True)
        self.db_path = self.internal / "registry.sqlite3"
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.db_path, timeout=30, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS operations(op_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS artifacts(artifact_id TEXT NOT NULL, version INTEGER NOT NULL, kind TEXT NOT NULL, scope TEXT NOT NULL, content TEXT NOT NULL, sha256 TEXT NOT NULL, status TEXT NOT NULL, metadata TEXT NOT NULL, deps TEXT NOT NULL, parent_version INTEGER, created_at TEXT NOT NULL, PRIMARY KEY(artifact_id,version));
        CREATE TABLE IF NOT EXISTS tasks(task_id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS threads(thread_id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS decisions(decision_id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sync(sync_id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS media(media_id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(event_id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
        schema = self.db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()
        schema_version = json.loads(schema[0]) if schema else None
        if schema_version not in (None, 1, 2):
            self.close()
            raise ValueError("登记库版本不兼容；请使用匹配版本或迁移工具")
        backup_path = None
        if schema_version == 1:
            # SQLite backup includes WAL contents. Never convert old decisions into
            # approved pointers merely because a client opens an old project.
            backup_dir = self.internal / "migrations"
            backup_dir.mkdir(exist_ok=True)
            backup_path = backup_dir / ("schema1-before-schema2-" + uuid.uuid4().hex + ".sqlite3")
            backup_db = sqlite3.connect(backup_path)
            try:
                self.db.backup(backup_db)
            finally:
                backup_db.close()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute("CREATE TABLE IF NOT EXISTS approved_segments(category TEXT NOT NULL, scope TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(category,scope))")
            self.db.execute("CREATE TABLE IF NOT EXISTS master_revisions(category TEXT NOT NULL, version INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(category,version))")
            self.db.execute("CREATE TABLE IF NOT EXISTS master_bindings(category TEXT PRIMARY KEY, data TEXT NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS master_sync(category TEXT NOT NULL, version INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(category,version))")
            self.db.execute("INSERT OR REPLACE INTO settings VALUES('schema_version','2')")
            if schema_version == 1:
                migration = {"from_schema": 1, "to_schema": 2, "backup": str(backup_path), "migrated_at": now(), "legacy_decisions_require_mapping": True, "automatic_approvals": 0}
                self.db.execute("INSERT OR REPLACE INTO settings VALUES('schema2_migration',?)", (canonical(migration),))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            self.close()
            raise

    def close(self):
        self.db.close()

    def _get(self, table, key, value):
        row = self.db.execute(f"SELECT data FROM {table} WHERE {key}=?", (value,)).fetchone()
        if not row:
            raise ValueError(f"记录不存在: {table}/{value}")
        return json.loads(row[0])

    def _put(self, table, key, value, data):
        self.db.execute(f"INSERT INTO {table}({key},data) VALUES(?,?) ON CONFLICT({key}) DO UPDATE SET data=excluded.data", (value, canonical(data)))

    def _list(self, table):
        return [json.loads(row[0]) for row in self.db.execute(f"SELECT data FROM {table} ORDER BY rowid")]

    def _project(self):
        row = self.db.execute("SELECT value FROM settings WHERE key='project'").fetchone()
        return json.loads(row[0]) if row else None

    def check_project_identity(self, expected_project_id):
        if expected_project_id is None:
            return
        identifier(expected_project_id, "expected_project_id")
        project = self._project()
        if not project or project["project_id"] != expected_project_id:
            raise ConflictError("作品目录的项目身份已改变；保留原请求并重新关联，不能将旧项目写入转到另一项目")

    def _event(self, action, data):
        self.db.execute("INSERT INTO events(action,data,created_at) VALUES(?,?,?)", (action, canonical(data), now()))

    def _artifact(self, artifact_id, version=None):
        if version is None:
            row = self.db.execute("SELECT * FROM artifacts WHERE artifact_id=? ORDER BY version DESC LIMIT 1", (artifact_id,)).fetchone()
        else:
            row = self.db.execute("SELECT * FROM artifacts WHERE artifact_id=? AND version=?", (artifact_id, version)).fetchone()
        if row is None:
            return None
        result = dict(row)
        for key in ("content", "metadata", "deps"):
            result[key] = json.loads(result[key])
        return result

    def _latest(self):
        return [self._artifact(row[0]) for row in self.db.execute("SELECT DISTINCT artifact_id FROM artifacts ORDER BY artifact_id")]

    def _approved_pointer(self, artifact):
        row = self.db.execute("SELECT data FROM approved_segments WHERE category=? AND scope=?", (content_category(artifact), artifact["scope"])).fetchone()
        return json.loads(row[0]) if row else None

    def _current_dependency(self, ref):
        bound = self._artifact(ref["artifact_id"], ref["version"])
        if not bound:
            return None
        pointer = self._approved_pointer(bound)
        # An explicitly bound candidate is still allowed as a draft input. A
        # newer candidate cannot displace a user's approved exact input.
        if pointer and pointer["artifact_id"] == ref["artifact_id"] and ref["version"] <= pointer["version"]:
            return self._artifact(pointer["artifact_id"], pointer["version"])
        return self._artifact(ref["artifact_id"])

    def _ref(self, ref):
        if not isinstance(ref, dict):
            raise ValueError("依赖必须为 {artifact_id, version}")
        required(ref, "artifact_id", "version")
        if type(ref["version"]) is not int or ref["version"] < 1:
            raise ValueError("依赖版本必须为正整数")
        artifact = self._artifact(ref["artifact_id"], ref["version"])
        if not artifact:
            raise ValueError(f"依赖版本不存在: {ref['artifact_id']}@{ref['version']}")
        return {"artifact_id": ref["artifact_id"], "version": ref["version"]}

    def _deps(self, refs):
        if not isinstance(refs, list):
            raise ValueError("deps/inputs 必须为列表")
        result = []
        seen = set()
        for item in refs:
            ref = self._ref(item)
            if ref["artifact_id"] in seen:
                raise ValueError("单个输入集不能绑定同一成果的多个版本")
            seen.add(ref["artifact_id"])
            result.append(ref)
        return result

    def _fresh(self, refs):
        stale = []
        for ref in refs:
            if self._dependency_stale(ref):
                stale.append(ref)
        if stale:
            raise ConflictError("任务绑定输入已变化或待复核，旧输入提交被拒绝: " + canonical(stale))

    def _dependency_path(self, ref, target_id, seen=None):
        """Exact historical path, used to detect feedback before adding an edge."""
        seen = set() if seen is None else seen
        key = (ref["artifact_id"], ref["version"])
        if key in seen:
            return None
        seen.add(key)
        bound = self._artifact(*key)
        if not bound:
            raise ConflictError("依赖链版本不存在")
        exact = {k: bound[k] for k in ("artifact_id", "version", "sha256")}
        if ref["artifact_id"] == target_id:
            return [exact]
        for dep in bound["deps"]:
            path = self._dependency_path(dep, target_id, seen)
            if path:
                return [exact, *path]
        return None

    def _reject_dependency_cycle(self, refs, target_id):
        if target_id:
            for ref in refs:
                path = self._dependency_path(ref, target_id)
                if path:
                    raise ConflictError("显式输入会回到目标成果，不能形成版本回环；保留原请求并明确重建任务: " + canonical(path))

    def _style_binding_lock(self, task):
        return {"schema_version": 1, "method_lock_sha256": task["execution_lock"]["lock_sha256"],
                "binding_sha256": content_hash({"binding": task["style_binding"], "inputs": task["inputs"],
                    "artifact_id": task.get("artifact_id"), "scope": task["scope"], "module": task["module"]})}

    def _check_style_binding(self, task):
        binding = task.get("style_binding")
        if not binding:
            context = task.get("style_context") or {}
            checkpoint_binding = any("style_binding" in checkpoint or "style_execution_lock" in checkpoint
                                     for checkpoint in task.get("checkpoints", []))
            if ("style_binding" in task or "style_execution_lock" in task or checkpoint_binding
                    or context.get("reference_mode") in {"frozen_reference", "hard_dependency", "target_pending"}
                    or context.get("frozen_reference")):
                raise ConflictError("任务冻结风格字段缺失，但执行锁、上下文或检查点仍有绑定证据；保留原任务并恢复完整记录")
            return
        if task.get("style_execution_lock") != self._style_binding_lock(task):
            raise ConflictError("冻结风格参考或任务输入锁变化，不能改写原任务")
        self._check_style_reference(binding)

    def _check_style_reference(self, binding):
        if not isinstance(binding, dict) or not isinstance(binding.get("artifact"), dict):
            raise ConflictError("冻结风格参考结构不完整")
        style = self._artifact(binding["artifact"]["artifact_id"], binding["artifact"]["version"])
        if not style or binding["artifact"]["sha256"] != style["sha256"] or binding["content"] != style["content"] or content_hash(binding["content"]) != style["sha256"] or binding["deps"] != style["deps"]:
            raise ConflictError("冻结风格参考全文与准确原版本不一致")
        approved, status = self._global_style()
        if approved != {k: binding["artifact"][k] for k in ("artifact_id", "version")} or status != "approved":
            raise ConflictError("冻结风格基准已换版或待复核，先核对再明确建立新任务")
        # A reference is not a stale-input exemption: all its other sources must
        # still be current before a checkpoint or submission.
        self._fresh([approved])

    def _automatic_style_reference(self, target_id, inputs):
        approved, status = self._global_style()
        if not approved:
            return None
        from .board1150 import is_trashed_ref
        if is_trashed_ref(self, approved) and approved not in inputs:
            # Logical trash preserves adoption and historical dependencies, but
            # is never selected automatically for a new piece of work.
            return None
        if status != "approved":
            raise ConflictError("当前全剧风格待复核，不能以自动参考策略跳过")
        self._fresh([approved])
        declared = [ref for ref in inputs if self._artifact(ref["artifact_id"], ref["version"])["kind"] == "style_bible"]
        if any(ref != approved for ref in declared):
            raise ConflictError("显式风格与当前采用基准不一致，不会自动替换")
        if approved in inputs:
            return None
        style = self._artifact(approved["artifact_id"], approved["version"])
        path = self._dependency_path(approved, target_id)
        reference = {"artifact": {k: style[k] for k in ("artifact_id", "version", "sha256")},
            "scope": style["scope"], "content": deepcopy(style["content"]), "deps": deepcopy(style["deps"]),
            "mode": "frozen_reference" if path else "hard_dependency", "automatic": True,
            "reason": "automatic_style_would_return_to_output" if path else "automatic_style_without_return_path",
            "dependency_path": path or [], "target_artifact_id": target_id}
        if not path:
            inputs.append(approved)
        return reference

    def _task_effective_inputs(self, task, target_id):
        self._check_style_binding(task)
        inputs = deepcopy(task["inputs"])
        from .conversations1170 import task_frozen_source_ref
        frozen_source = task_frozen_source_ref(self, task)
        if frozen_source is not None:
            # Selected ideas are immutable creative provenance, not a live
            # dependency on every subsequent independent discussion update.
            inputs.remove(frozen_source)
        binding = deepcopy(task.get("style_binding"))
        if not binding and task["module"] in STYLE_MODULES:
            current_style, style_status = self._global_style()
            if current_style and style_status == "needs_review" and self._dependency_path(current_style, target_id):
                raise ConflictError("目标属于待复核风格的原来源，不能省略风格上下文绕过回环检查")
        if binding:
            path = self._dependency_path(binding["artifact"], target_id)
            if path:
                style_ref = {k: binding["artifact"][k] for k in ("artifact_id", "version")}
                # Only this recorded automatic edge can become a frozen
                # creative reference. Explicit inputs are never removed.
                if binding["mode"] in ("hard_dependency", "target_pending"):
                    inputs.remove(style_ref)
                binding.update(mode="frozen_reference", reason="automatic_style_would_return_to_output", dependency_path=path,
                               target_artifact_id=target_id)
            elif binding["mode"] == "target_pending":
                binding.update(mode="hard_dependency", reason="automatic_style_without_return_path", target_artifact_id=target_id)
        self._reject_dependency_cycle(inputs, target_id)
        self._fresh(inputs)
        return inputs, binding

    def _previous_style_reference(self, artifact):
        reference = artifact["metadata"]["style_reference"]
        return {"artifact": deepcopy(reference["artifact"]), "mode": reference["mode"], "reason": reference["reason"],
                "prior_output_ref": {k: artifact[k] for k in ("artifact_id", "version", "sha256")}}

    def _dependency_stale(self, ref, seen=None):
        seen = set() if seen is None else seen
        key = (ref["artifact_id"], ref["version"])
        if key in seen:
            return False
        seen.add(key)
        current = self._current_dependency(ref)
        if not current or current["version"] != ref["version"] or current["status"] == "needs_review":
            return True
        bound = self._artifact(ref["artifact_id"], ref["version"])
        return any(self._dependency_stale(dep, seen) for dep in bound["deps"])

    def _invalidate(self, changed_id, new_version):
        # Run only after approval. Mark approved revisions, never pending
        # candidates; exact dependencies determine transitive impact.
        approved = [json.loads(row[0]) for row in self.db.execute("SELECT data FROM approved_segments")]
        revisions = [dict(row, deps=json.loads(row["deps"])) for row in self.db.execute("SELECT artifact_id,version,deps FROM artifacts")]
        affected_versions = {(r["artifact_id"], r["version"]) for r in revisions if r["artifact_id"] == changed_id and r["version"] != new_version}
        repeat = True
        while repeat:
            repeat = False
            for item in revisions:
                revision_key = (item["artifact_id"], item["version"])
                if revision_key in affected_versions:
                    continue
                if any((r["artifact_id"], r["version"]) in affected_versions for r in item["deps"]):
                    affected_versions.add(revision_key)
                    repeat = True
        affected = {a["artifact_id"] for a in approved if a["artifact_id"] != changed_id and (a["artifact_id"], a["version"]) in affected_versions}
        for aid in affected:
            item = next(a for a in approved if a["artifact_id"] == aid)
            self.db.execute("UPDATE artifacts SET status='needs_review' WHERE artifact_id=? AND version=?", (aid, item["version"]))
            item.update(review_status="needs_review", review_reason={"upstream": changed_id, "version": new_version, "observed_at": now()})
            self.db.execute("UPDATE approved_segments SET data=? WHERE category=? AND scope=?", (canonical(item), item["category"], item["scope"]))
        for task in self._list("tasks"):
            if task["status"] in ("created", "in_progress", "needs_review") and any((r["artifact_id"], r["version"]) in affected_versions for r in task["inputs"]):
                task["status"] = "needs_review"
                task["review_reason"] = {"upstream": changed_id, "version": new_version, "observed_at": now()}
                self._put("tasks", "task_id", task["task_id"], task)
        return sorted(affected)

    def dispatch(self, action: str, payload: dict | None = None) -> dict:
        p = dict(payload or {})
        from .previs1190 import READ_ACTIONS as PREVIS_READ, WRITE_ACTIONS as PREVIS_WRITE, read as previs_read, mutate as previs_mutate
        if action in PREVIS_READ:
            with self.lock:
                self.db.execute("BEGIN")
                try:
                    result = previs_read(self, action, p)
                    self.db.execute("COMMIT")
                    return result
                except Exception:
                    self.db.execute("ROLLBACK")
                    raise
        if action in ("board.reference", "board.usage", "board.export"):
            from .board1150 import export_selected, reference
            with self.lock:
                self.db.execute("BEGIN")
                try:
                    result = export_selected(self, p) if action == "board.export" else reference(self, p)
                    self.db.execute("COMMIT")
                    return result
                except Exception:
                    self.db.execute("ROLLBACK")
                    raise
        if action.startswith("conversation."):
            from .conversations1170 import validate_conversation_payload
            validate_conversation_payload(action, p)
        if action == "conversation.read":
            from .conversations1170 import read_conversations
            with self.lock:
                self.db.execute("BEGIN")
                try:
                    result = read_conversations(self, p)
                    self.db.execute("COMMIT")
                    return result
                except Exception:
                    self.db.execute("ROLLBACK")
                    raise
        if action.startswith("screenwriting."):
            from .screenwriting1130 import validate_screenwriting_payload
            validate_screenwriting_payload(action, p)
        if action == "screenwriting.read":
            from .screenwriting1130 import read_screenwriting
            return read_screenwriting(self, p)
        if action.startswith("art."):
            from .art1130 import validate_art_payload
            validate_art_payload(action, p)
        if action == "art.read":
            from .art1130 import read_art
            return read_art(self, p)
        if action.startswith("cloud."):
            from .cloud1120 import validate_cloud_payload
            validate_cloud_payload(action, p)
        if action == "cloud.read":
            from .cloud1120 import read_cloud
            return read_cloud(self, p)
        if action.startswith("workspace."):
            validate_workspace_payload(action, p)
        if action in ("workspace.read", "workspace.resolve"):
            with self.lock:
                self.db.execute("BEGIN")
                try:
                    result = read_workspace(self, p, resolve=action == "workspace.resolve")
                    self.db.execute("COMMIT")
                    return result
                except Exception:
                    self.db.execute("ROLLBACK")
                    raise
        if action == "brainstorm.interface":
            return brainstorm_interface()
        if action == "brainstorm.prepare":
            with self.lock:
                self.db.execute("BEGIN")
                try:
                    result = prepare_brainstorm(self, p)
                    self.db.execute("COMMIT")
                    return result
                except Exception:
                    self.db.execute("ROLLBACK")
                    raise
        if action in ("snapshot", "project.snapshot"):
            return self.snapshot()
        if action == "context.read":
            from .efficient import read_context
            return read_context(self, p)
        if action == "delivery.read":
            from .delivery1110 import read_delivery
            return read_delivery(self, p)
        if action == "planning.read":
            with self.lock:
                return self._planning_read(p)
        if action in ("document.export", "document.save"):
            from .documents import export_document, save_document
            with self.lock:
                self.db.execute("BEGIN")
                try:
                    result = save_document(self, p) if action == "document.save" else export_document(self, p)
                    self.db.execute("COMMIT")
                    return result
                except Exception:
                    self.db.execute("ROLLBACK")
                    raise
        if action == "task.resume":
            required(p, "task_id")
            with self.lock:
                return self._resume(p["task_id"])
        if action == "artifact.get":
            required(p, "artifact_id")
            with self.lock:
                result = self._artifact(p["artifact_id"], p.get("version"))
                if not result:
                    raise ValueError("成果版本不存在")
                return result
        if action == "artifact.history":
            required(p, "artifact_id")
            identifier(p["artifact_id"], "artifact_id")
            with self.lock:
                versions = [self._artifact(p["artifact_id"], row[0]) for row in self.db.execute("SELECT version FROM artifacts WHERE artifact_id=? ORDER BY version", (p["artifact_id"],))]
                if not versions:
                    raise ValueError("成果不存在")
                return {"artifact_id": p["artifact_id"], "versions": versions, "read_only": True}
        if action == "master.history":
            required(p, "category")
            if p["category"] not in CATEGORIES:
                raise ValueError("内容 category 无效")
            with self.lock:
                versions = [self._master(p["category"], row[0]) for row in self.db.execute("SELECT version FROM master_revisions WHERE category=? ORDER BY version", (p["category"],))]
                return {"category": p["category"], "versions": versions, "read_only": True}
        if self.read_only:
            raise ValueError("只读登记连接不能执行写入操作")
        required(p, "op_id")
        identifier(p["op_id"], "op_id")
        from .efficient import WRITE_ACTIONS, checkpoint_file, save_artifact_file, submit_checkpoint
        from .delivery1110 import (WRITE_ACTIONS as DELIVERY_WRITE_ACTIONS, complete_delivery,
                                   define_delivery, review_delivery)
        from .cloud1120 import bind_cloud, configure_cloud, prepare_cloud, record_cloud
        from .art1130 import prepare_art, select_art, integrate_art, revise_art
        from .screenwriting1130 import record_screenwriting, resolve_screenwriting
        from .board1150 import batch_items, set_categories, set_item
        from .board1180 import WRITE_ACTIONS as CREATOR_ACTIONS, dispatch as creator_dispatch
        if action in WRITE_ACTIONS or action in DELIVERY_WRITE_ACTIONS or action in CREATOR_ACTIONS or action in PREVIS_WRITE:
            required(p, "expected_project_id")
        request_hash = digest(canonical({"action": action, "payload": p}).encode("utf-8"))
        with self.lock:
            self.check_project_identity(p.get("expected_project_id"))
            cached = self._cached(p["op_id"], request_hash)
            if cached is not None:
                if action == "conversation.claim":
                    return {**cached, "dispatch_allowed": False, "replayed": True}
                return cached
            if action in ("backup.create", "backup.restore"):
                return self._backup_dispatch(action, p, request_hash)
            handlers = {
                "project.init": self._init,
                "project.workflow.set": self._workflow_set,
                "workspace.prepare": lambda payload: prepare_workspace(self, payload),
                "workspace.record": lambda payload: record_workspace(self, payload),
                "delivery.define": lambda payload: define_delivery(self, payload),
                "delivery.review": lambda payload: review_delivery(self, payload),
                "delivery.complete": lambda payload: complete_delivery(self, payload),
                "cloud.configure": lambda payload: configure_cloud(self, payload),
                "cloud.bind": lambda payload: bind_cloud(self, payload),
                "cloud.prepare": lambda payload: prepare_cloud(self, payload),
                "cloud.record": lambda payload: record_cloud(self, payload),
                "art.prepare": lambda payload: prepare_art(self, payload),
                "art.select": lambda payload: select_art(self, payload),
                "art.integrate": lambda payload: integrate_art(self, payload),
                "art.revise": lambda payload: revise_art(self, payload),
                "screenwriting.record": lambda payload: record_screenwriting(self, payload),
                "screenwriting.resolve": lambda payload: resolve_screenwriting(self, payload),
                "artifact.save": self._save,
                "artifact.save_file": lambda payload: save_artifact_file(self, payload),
                "presentation.set": lambda payload: set_presentation(self, payload),
                "board.order.set": lambda payload: set_board_order(self, payload),
                "trash.set": lambda payload: set_trash(self, payload),
                "board.item.set": lambda payload: set_item(self, payload),
                "board.categories.set": lambda payload: set_categories(self, payload),
                "board.items.batch": lambda payload: batch_items(self, payload),
                "planning.record": self._planning_record,
                "artifact.restore": self._restore_artifact,
                "content.approve": self._approve,
                "master.bind_page": self._bind_master,
                "task.create": self._task_create,
                "task.checkpoint": self._checkpoint,
                "task.checkpoint_file": lambda payload: checkpoint_file(self, payload),
                "task.submit": self._submit,
                "task.submit_checkpoint": lambda payload: submit_checkpoint(self, payload),
                "task.cancel": self._cancel,
                "decision.record": self._decision,
                "thread.register": self._thread,
                "sync.intent": self._sync_intent,
                "sync.observe": self._sync_observe,
                "media.register": self._media,
                "media.classify": self._media_classify,
                "media.update": self._media_update,
                "cue.save": self._cue,
            }
            if action.startswith("conversation."):
                from .conversations1170 import mutate_conversations
                handlers[action] = lambda payload: mutate_conversations(self, action, payload)
            handlers.update({name: (lambda payload, name=name: creator_dispatch(self, name, payload)) for name in CREATOR_ACTIONS})
            handlers.update({name: (lambda payload, name=name: previs_mutate(self, name, payload)) for name in PREVIS_WRITE})
            if action not in handlers:
                raise ValueError(f"不支持操作: {action}")
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self.check_project_identity(p.get("expected_project_id"))
                # A second process could have completed the operation before lock acquisition.
                cached = self._cached(p["op_id"], request_hash)
                if cached is not None:
                    self.db.execute("COMMIT")
                    if action == "conversation.claim":
                        return {**cached, "dispatch_allowed": False, "replayed": True}
                    return cached
                if action != "project.init" and not self._project():
                    raise ValueError("请先执行 project.init")
                result = handlers[action](p)
                self._event(action, {"op_id": p["op_id"], "result": result})
                self.db.execute("INSERT INTO operations VALUES(?,?,?,?)", (p["op_id"], request_hash, canonical(result), now()))
                self.db.execute("COMMIT")
                return result
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def _cached(self, op_id, request_hash):
        row = self.db.execute("SELECT request_hash,result FROM operations WHERE op_id=?", (op_id,)).fetchone()
        if row:
            if row[0] != request_hash:
                raise ConflictError("op_id 已用于不同操作或参数")
            return json.loads(row[1])
        return None

    def _init(self, p):
        required(p, "project_id", "title", "test_only")
        identifier(p["project_id"], "project_id")
        if type(p["test_only"]) is not bool:
            raise ValueError("test_only 必须为布尔值")
        existing = self._project()
        if existing:
            raise ConflictError("项目已初始化；不能覆盖项目身份")
        project = {"project_id": p["project_id"], "title": p["title"], "test_only": p["test_only"], "system_version": __version__, "created_at": now(), "data_revision": 1}
        self.db.execute("INSERT INTO settings VALUES('project',?)", (canonical(project),))
        return project

    def _workflow_set(self, p):
        required(p, "expected_project_id", "base_revision", "mode")
        if not isinstance(p["mode"], str) or p["mode"] not in MODES:
            raise ValueError("workflow mode 必须为 novel_only/novel_to_screen/screenplay")
        project = self._project()
        previous = project.get("workflow") or {}
        revision = previous.get("revision", 0)
        if type(p["base_revision"]) is not int or p["base_revision"] != revision:
            raise ConflictError(f"流程基础修订冲突: expected={p['base_revision']}, current={revision}")
        outline_order = p.get("outline_order", previous.get("outline_order") or "after_novel")
        if not isinstance(outline_order, str) or outline_order not in OUTLINE_ORDERS:
            raise ValueError("outline_order 必须为 before_novel/after_novel")
        workflow = {"mode": p["mode"], "outline_order": outline_order, "revision": revision + 1, "updated_at": now()}
        project.update(workflow=workflow, data_revision=project.get("data_revision", 1) + 1)
        self.db.execute("UPDATE settings SET value=? WHERE key='project'", (canonical(project),))
        return {"project": project, "workflow": workflow, "automatic_creation": False, "automatic_approval": False}

    def _global_style(self):
        row = self.db.execute("SELECT data FROM approved_segments WHERE category='style' AND scope=?", (GLOBAL_STYLE_SCOPE,)).fetchone()
        pointer = json.loads(row[0]) if row else None
        if pointer:
            artifact = self._artifact(pointer["artifact_id"], pointer["version"])
            if not artifact or artifact["kind"] != "style_bible":
                return None, "missing"
            return {"artifact_id": artifact["artifact_id"], "version": artifact["version"]}, pointer["review_status"]
        return None, "missing"

    def _style_context(self, refs, *, recorded=True):
        approved_ref, approved_status = self._global_style()
        bound = [ref for ref in refs if self._artifact(ref["artifact_id"], ref["version"])["kind"] == "style_bible"]
        if approved_ref and approved_status == "needs_review":
            status = "needs_review"
        elif approved_ref and approved_ref in bound:
            status = "bound"
        elif approved_ref and bound:
            status = "different_version"
        elif approved_ref:
            status = "missing_reference"
        else:
            status = "candidate_bound" if bound else "missing"
        context = {"status": status, "approved_ref": approved_ref, "bound_refs": bound, "semantic_compliance": "not_assessed", "missing_context": [] if status == "bound" else ["global_style"]}
        if recorded:
            context["recorded_at"] = now()
        return context

    def _validate_media_artifact(self, kind, metadata, deps):
        def bind(ref):
            ref = self._ref(ref)
            if ref not in deps:
                raise ValueError("媒体/时间线引用必须同时列入精确 deps: " + canonical(ref))
            return self._artifact(ref["artifact_id"], ref["version"])
        def number(value, name):
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} 必须为非负有限秒数")
            return value
        def source_kind(artifact, allowed, field):
            source_id = artifact["metadata"].get("source_media_id")
            if not source_id:
                raise ValueError(f"{field} 必须绑定实际媒体 source_media_id，创作需求请放 planned 列表")
            source = self._get("media", "media_id", source_id)
            if source["kind"] not in allowed:
                raise ValueError(f"{field} 原件媒体类型错误")
            return source
        if kind == "clip":
            required(metadata, "source_media_id", "in_seconds", "out_seconds")
            source = self._get("media", "media_id", metadata["source_media_id"])
            if source["kind"] not in ("video", "audio"):
                raise ValueError("clip 源必须为视频或音频原件")
            start = number(metadata["in_seconds"], "in_seconds")
            end = number(metadata["out_seconds"], "out_seconds")
            if end <= start:
                raise ValueError("clip out_seconds 必须大于 in_seconds")
            duration = source["metadata"].get("duration_seconds")
            if duration is not None and end > duration:
                raise ValueError("clip 选段超出源素材时长")
        elif kind in ("sequence", "timeline"):
            required(metadata, "clips")
            if not isinstance(metadata["clips"], list) or not metadata["clips"]:
                raise ValueError("sequence 必须包含 clip 引用")
            for entry in metadata["clips"]:
                clip = bind(entry)
                if clip["kind"] != "clip":
                    raise ValueError("sequence 只接受 clip 引用")
                required(entry, "timeline_in_seconds")
                number(entry["timeline_in_seconds"], "timeline_in_seconds")
        elif kind == "final":
            required(metadata, "timeline", "shots", "music", "dialogue", "subtitles", "export_spec")
            timeline = bind(metadata["timeline"])
            if timeline["kind"] not in ("sequence", "timeline"):
                raise ValueError("final 必须绑定 sequence/timeline 精确版本")
            # Revalidate the bound manifest, including revisions saved before
            # this validator existed. An alias cannot bypass exact clip refs.
            self._validate_media_artifact(timeline["kind"], timeline["metadata"], timeline["deps"])
            for field in ("shots", "music", "dialogue", "subtitles"):
                if not isinstance(metadata[field], list):
                    raise ValueError(f"final {field} 必须为精确引用列表（明确无轨道时用空列表）")
                for ref in metadata[field]:
                    artifact = bind(ref)
                    if field == "shots":
                        if artifact["kind"] not in ("clip", "shot"):
                            raise ValueError("final shots 只接受视频 clip/shot 精确引用")
                        source_kind(artifact, {"video"}, "shots")
                    elif field in ("music", "dialogue"):
                        allowed = {"music", "audio", "clip"} if field == "music" else {"dialogue_audio", "audio", "clip"}
                        if artifact["kind"] not in allowed:
                            raise ValueError(f"final {field} 必须为实际音频成果，cue/对白文本属于计划")
                        source_kind(artifact, {"audio"}, field)
                    elif artifact["kind"] not in ("subtitle", "subtitles"):
                        raise ValueError("final subtitles 必须引用 subtitle/subtitles 成果")
            planned_types = {"planned_music": {"cue"}, "planned_shots": {"director", "shot"}, "planned_dialogue": {"script", "screenplay", "dialogue"}}
            for field, kinds in planned_types.items():
                planned = metadata.get(field, [])
                if not isinstance(planned, list):
                    raise ValueError(f"{field} 必须为引用数组")
                if planned:
                    if metadata.get("assembly_status") != "planned":
                        raise ValueError("存在未完成轨道需求时 assembly_status 必须为 planned")
                    if metadata.get("render_status") not in (None, "not_rendered", "planned"):
                        raise ValueError("存在计划轨道的清单不能标为已渲染成片")
                for ref in planned:
                    if bind(ref)["kind"] not in kinds:
                        raise ValueError(f"{field} 引用类型错误")
            if not isinstance(metadata["export_spec"], dict) or not metadata["export_spec"]:
                raise ValueError("final 缺少导出规格")
            spec = metadata["export_spec"]
            required(spec, "width", "height", "fps")
            for field in ("width", "height"):
                if type(spec[field]) is not int or spec[field] <= 0:
                    raise ValueError(f"export_spec.{field} 必须为正整数")
            if number(spec["fps"], "export_spec.fps") <= 0:
                raise ValueError("export_spec.fps 必须为正有限数")
            for field in ("format", "video_codec", "audio_codec"):
                if field in spec and (not isinstance(spec[field], str) or not spec[field].strip()):
                    raise ValueError(f"export_spec.{field} 必须为非空字符串")
            for field in ("sample_rate", "channels", "bitrate"):
                if field in spec and (type(spec[field]) is not int or spec[field] <= 0):
                    raise ValueError(f"export_spec.{field} 必须为正整数")
        elif kind in ("music", "audio", "dialogue_audio"):
            source_kind({"metadata": metadata}, {"audio"}, kind)
        elif kind == "cue":
            # Cue can exist before a timeline; absent alignment remains unknown.
            if metadata.get("timeline") is not None:
                bind(metadata["timeline"])
            for key in ("in_seconds", "out_seconds"):
                if metadata.get(key) is not None:
                    number(metadata[key], key)
            if metadata.get("in_seconds") is not None and metadata.get("out_seconds") is not None and metadata["out_seconds"] <= metadata["in_seconds"]:
                raise ValueError("cue 退出点必须大于进入点")

    def _save(self, p, *, trusted_task=None, trusted_planning=False):
        if "use_current_style" in p and type(p["use_current_style"]) is not bool:
            raise ValueError("use_current_style必须为布尔值")
        if trusted_task is not None and p.get("use_current_style"):
            raise ValueError("任务提交使用其冻结风格，不能另选自动风格策略")
        if "cloud_update" in p:
            required(p, "expected_project_id")
            self.check_project_identity(p["expected_project_id"])
        if p.get("kind") == "planning_record" and not trusted_planning:
            raise ValueError("planning_record 只能经 planning.record 增量保存，不能整体替换或恢复旧状态")
        required(p, "artifact_id", "kind", "scope", "content", "base_version")
        identifier(p["artifact_id"], "artifact_id")
        if "task_id" in p and trusted_task is None:
            raise ConflictError("artifact.save 不接受 task_id 授权；任务成果必须通过 task.submit 校验后保存")
        for task in self._list("tasks"):
            owns_target = task.get("artifact_id") == p["artifact_id"] or (task["scope"] == p["scope"] and p["kind"] in output_kinds(task["module"]))
            trusted_owner = trusted_task is not None and task["task_id"] == trusted_task["task_id"]
            if owns_target and task["status"] in ("created", "in_progress", "needs_review") and not trusted_owner:
                raise ConflictError(f"成果范围由任务 {task['task_id']} 编辑；请提交任务或先取消任务")
        if type(p["base_version"]) is not int or p["base_version"] < 0:
            raise ValueError("base_version 必须为非负整数")
        previous = self._artifact(p["artifact_id"])
        current_version = previous["version"] if previous else 0
        if current_version != p["base_version"]:
            raise ConflictError(f"基础版本冲突: expected={p['base_version']}, current={current_version}")
        if previous and (previous["kind"] != p["kind"] or previous["scope"] != p["scope"]):
            raise ConflictError("稳定成果 ID 的 kind/scope 不可改变")
        deps = self._deps(p.get("deps", []))
        if any(r["artifact_id"] == p["artifact_id"] for r in deps):
            raise ValueError("自身历史版本使用 parent_version，不可形成自身依赖")
        self._reject_dependency_cycle(deps, p["artifact_id"])
        metadata = p.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("metadata 必须为对象")
        metadata = dict(metadata)
        from .conversations1170 import check_frozen_source, task_frozen_source_ref
        previous_source = previous["metadata"].get("conversation_source_reference") if previous else None
        expected_source = previous_source
        if trusted_task is not None:
            task_frozen_source_ref(self, trusted_task)
            expected_source = trusted_task.get("conversation_source_reference") or previous_source
        if "conversation_source_reference" in metadata and metadata["conversation_source_reference"] != expected_source:
            raise ConflictError("冻结创意来源只能由准确任务登记，普通保存不能伪造或改写")
        if expected_source is not None:
            check_frozen_source(self, expected_source, artifact_id=p["artifact_id"], scope=p["scope"])
            metadata["conversation_source_reference"] = deepcopy(expected_source)
        prior_reference = previous["metadata"].get("style_reference") if previous else None
        if trusted_task is None:
            if "style_reference" in metadata and metadata["style_reference"] != prior_reference:
                raise ConflictError("冻结风格参考只能由真实任务通道登记，普通保存不能伪造或改写")
            if prior_reference is not None:
                metadata["style_reference"] = deepcopy(prior_reference)
        category = content_category({"kind": p["kind"], "metadata": metadata})
        if trusted_task is None:
            generated_reference = None
            if p.get("use_current_style") and category in STYLE_CATEGORIES | {"novel", "outline", "character_bio"}:
                generated_reference = self._automatic_style_reference(p["artifact_id"], deps)
            if generated_reference:
                if prior_reference is not None:
                    generated_reference["previous_reference"] = self._previous_style_reference(previous)
                metadata["style_reference"] = generated_reference
            elif prior_reference is not None:
                self._check_style_reference(prior_reference)
                required_style = {k: prior_reference["artifact"][k] for k in ("artifact_id", "version")}
                if prior_reference["mode"] == "hard_dependency" and required_style not in deps:
                    raise ConflictError("普通保存不能丢弃原明确风格依赖")
        if "asset_type" in metadata:
            if category != "asset":
                raise ValueError("metadata.asset_type 仅用于资产类别；不改变人物小传或其他成果类别")
            try:
                validate_asset_type(metadata["asset_type"])
            except ValueError:
                # A body edit may carry an uninterpreted legacy label forward.
                # JSON comparison deliberately distinguishes True from 1, also
                # inside arrays/objects. No unknown value may be introduced or
                # changed, and only the actual current asset version qualifies.
                prior_metadata = previous["metadata"] if previous else {}
                unchanged_legacy = (previous is not None and content_category(previous) == "asset"
                                    and "asset_type" in prior_metadata
                                    and canonical(prior_metadata["asset_type"]) == canonical(metadata["asset_type"]))
                if not unchanged_legacy:
                    raise
        if p["kind"] not in NON_APPROVABLE_KINDS:
            new_kinds = {"idea": "idea", "requirements": "requirements", "character_bio": "character_bio", "source_script": "source_script", "style_bible": "style", "video_prompt": "video_prompt"}
            if p["kind"] in new_kinds and category != new_kinds[p["kind"]]:
                raise ValueError("新内容类型必须使用自身独立 category")
            if category in new_kinds.values() and p["kind"] not in new_kinds:
                raise ValueError("人物小传、剧本底稿、全剧风格与 AI 视频提示词须保存为明确独立 kind，不能仅改 category 升级旧记录")
            if p["kind"] == "style_bible" and p["scope"] != GLOBAL_STYLE_SCOPE:
                raise ValueError("全剧风格 style_bible 的固定 scope 必须为 project/style")
            validate_stage(category, metadata)
        if p["kind"] == "video_prompt":
            text_value(p["content"], "AI 视频提示词正文")
            for field in ("target_platform", "target_model", "generation_unit"):
                if metadata.get(field) is not None:
                    text_value(metadata[field], "metadata." + field)
        if category in STYLE_CATEGORIES and p["kind"] not in NON_APPROVABLE_KINDS:
            # Save provenance for the new revision only; never fabricate historical refs.
            metadata["style_context"] = self._style_context(deps)
            if metadata.get("style_reference", {}).get("mode") == "frozen_reference":
                metadata["style_context"].update(frozen_reference=deepcopy(metadata["style_reference"]["artifact"]),
                    reference_mode="frozen_reference", reference_reason=metadata["style_reference"]["reason"],
                    status="frozen_reference", missing_context=[])
        segment_order({"metadata": metadata})
        if previous and content_category(previous) != category:
            raise ConflictError("稳定成果 ID 的 category 不可改变")
        if previous is None and p["kind"] in CREATIVE_SEGMENT_KINDS:
            duplicate = next((item for item in self._latest() if item["kind"] in CREATIVE_SEGMENT_KINDS and item["scope"] == p["scope"] and content_category(item) == category), None)
            if duplicate:
                raise ConflictError("该分类与分段已有稳定成果 ID：" + duplicate["artifact_id"] + "；请在原成果下保存候选，不创建无法并入总稿的重复分段")
        self._validate_media_artifact(p["kind"], metadata, deps)
        version = current_version + 1
        status = "recorded" if trusted_planning else "candidate"
        self.db.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?)", (p["artifact_id"], version, p["kind"], p["scope"], canonical(p["content"]), content_hash(p["content"]), status, canonical(metadata), canonical(deps), current_version or None, now()))
        result = {"artifact": self._artifact(p["artifact_id"], version), "invalidated": [], "approval_status": "pending_review"}
        if "cloud_update" in p:
            from .cloud1120 import prepare_saved_cloud
            result["cloud_update"] = prepare_saved_cloud(self, result["artifact"], p["cloud_update"])
        return result

    def _planning_read(self, p):
        self.check_project_identity(p.get("expected_project_id"))
        required(p, "record_id")
        identifier(p["record_id"], "record_id")
        version = p.get("version")
        if version is not None and (type(version) is not int or version < 1):
            raise ValueError("version 必须为正整数")
        artifact = self._artifact(p["record_id"], version)
        if not artifact or artifact["kind"] != "planning_record":
            raise ValueError("灵感/需求记录不存在")
        since, limit = p.get("since_version", 0), p.get("limit", 20)
        if type(since) is not int or since < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("since_version 非负，limit 为 1 到 100 的整数")
        rows = list(self.db.execute("SELECT version FROM artifacts WHERE artifact_id=? AND version>? AND version<=? ORDER BY version LIMIT ?", (p["record_id"], since, artifact["version"], limit)))
        history = []
        for row in rows:
            item = self._artifact(p["record_id"], row[0])
            history.append({"version": row[0], "sha256": item["sha256"], "change": item["metadata"]["change"], "recorded_at": item["created_at"]})
        cursor = rows[-1][0] if rows else since
        return {"record": artifact["content"], "artifact_ref": {"artifact_id": artifact["artifact_id"], "version": artifact["version"]}, "scope": artifact["scope"], "sha256": artifact["sha256"], "changes": history, "next_since_version": cursor if cursor < artifact["version"] else None, "read_only": True, "execution_authorized_by_tool": False, "project_root": str(self.root)}

    def _planning_record(self, p):
        from .planning import apply, check_attachments
        required(p, "expected_project_id", "record_id", "scope", "base_version", "change")
        identifier(p["record_id"], "record_id")
        identifier(p["scope"], "scope")
        if type(p["base_version"]) is not int or p["base_version"] < 0:
            raise ValueError("base_version 必须为非负整数")
        prior = self._artifact(p["record_id"])
        if prior and (prior["kind"] != "planning_record" or prior["scope"] != p["scope"]):
            raise ConflictError("记录编号或范围冲突")
        actual = prior["version"] if prior else 0
        if actual != p["base_version"]:
            raise ConflictError(f"基础版本冲突: expected={p['base_version']}, current={actual}")
        content = apply(prior["content"] if prior else None, p["change"], record_id=p["record_id"], version=actual+1, timestamp=now())
        check_attachments(self, content)
        from .modules import execution_lock
        metadata = {"category": "other", "title": content["title"], "change": p["change"], "execution_lock": execution_lock(content["record_kind"]), "execution_authorized_by_tool": False}
        saved = self._save({"artifact_id": p["record_id"], "kind": "planning_record", "scope": p["scope"], "content": content, "base_version": actual, "metadata": metadata, "deps": p.get("deps", prior["deps"] if prior else [])}, trusted_planning=True)
        artifact = saved["artifact"]
        if artifact["content"] != content or artifact["sha256"] != content_hash(content):
            raise ValueError("记录写后读回校验失败")
        return {"saved": True, "readback_verified": True, "record": content, "version": artifact["version"], "artifact_ref": {"artifact_id": p["record_id"], "version": artifact["version"]}, "sha256": artifact["sha256"], "project_root": str(self.root), "execution_authorized_by_tool": False}

    def _restore_artifact(self, p):
        required(p, "artifact_id", "version", "base_version")
        source = self._artifact(p["artifact_id"], self._ref(p)["version"])
        metadata = dict(source["metadata"], restored_from_version=source["version"], restored_from_sha256=source["sha256"])
        latest = self._artifact(p["artifact_id"])
        current_reference = latest["metadata"].get("style_reference")
        historical_reference = source["metadata"].get("style_reference")
        if historical_reference:
            # This exact source was read by the restore operation itself. It
            # remains historical provenance, not a caller-selected current
            # style binding or an exemption from its freshness checks.
            metadata["restored_style_reference"] = self._previous_style_reference(source)
        if current_reference:
            metadata["style_reference"] = deepcopy(current_reference)
        else:
            metadata.pop("style_reference", None)
        request = dict(p, kind=source["kind"], scope=source["scope"], content=source["content"], metadata=metadata, deps=source["deps"])
        if historical_reference and not current_reference:
            request["use_current_style"] = True
        return self._save(request)

    def _task_create(self, p):
        from .conversations1170 import guard_task_create
        guard_task_create(self, p)
        required(p, "task_id", "title", "module", "scope", "inputs", "must_keep", "allowed_changes", "requirements")
        identifier(p["task_id"], "task_id")
        identifier(p["module"], "module")
        for field in ("must_keep", "allowed_changes", "requirements"):
            item_list(p[field], field)
        if p.get("artifact_id"):
            identifier(p["artifact_id"], "artifact_id")
            existing_target = self._artifact(p["artifact_id"])
            if existing_target and (existing_target["scope"] != p["scope"] or existing_target["kind"] not in output_kinds(p["module"])):
                raise ConflictError("任务目标成果的范围或类型与模块不符")
        if self.db.execute("SELECT 1 FROM tasks WHERE task_id=?", (p["task_id"],)).fetchone():
            raise ConflictError("任务 ID 已存在")
        for task in self._list("tasks"):
            same_target = p.get("artifact_id") and task.get("artifact_id") == p["artifact_id"]
            shared_scope = task["scope"] == p["scope"] and bool(output_kinds(task["module"]) & output_kinds(p["module"]))
            if (same_target or shared_scope) and task["status"] in ("created", "in_progress", "needs_review"):
                raise ConflictError(f"同一范围已有编辑者: {task['task_id']}")
        inputs = self._deps(p["inputs"])
        self._reject_dependency_cycle(inputs, p.get("artifact_id"))
        style_binding = None
        if p["module"] in STYLE_MODULES:
            approved_style, style_status = self._global_style()
            declared_styles = [ref for ref in inputs if self._artifact(ref["artifact_id"], ref["version"])["kind"] == "style_bible"]
            if approved_style and any(ref != approved_style for ref in declared_styles):
                raise ConflictError("任务显式风格版本与当前全剧已通过风格冲突；请核查后明确选择当前版本，不会静默替换输入")
            if approved_style and style_status == "needs_review" and p.get("artifact_id") and self._dependency_path(approved_style, p["artifact_id"]):
                raise ConflictError("目标属于待复核风格的原来源，先完成准确基准复核，不能借自动参考绕过")
            from .board1150 import is_trashed_ref
            if approved_style and style_status == "approved" and approved_style not in inputs and not is_trashed_ref(self, approved_style):
                style = self._artifact(approved_style["artifact_id"], approved_style["version"])
                self._fresh([approved_style])
                path = self._dependency_path(approved_style, p["artifact_id"]) if p.get("artifact_id") else None
                style_binding = {"artifact": {k: style[k] for k in ("artifact_id", "version", "sha256")},
                    "scope": style["scope"], "content": deepcopy(style["content"]), "deps": deepcopy(style["deps"]),
                    "mode": "frozen_reference" if path else ("hard_dependency" if p.get("artifact_id") else "target_pending"),
                    "reason": "automatic_style_would_return_to_output" if path else "automatic_style_without_return_path",
                    "dependency_path": path or [], "target_artifact_id": p.get("artifact_id"), "automatic": True}
                if not path:
                    inputs.append(approved_style)
        data = {key: p[key] for key in ("task_id", "title", "module", "scope", "must_keep", "allowed_changes", "requirements")}
        from .modules import execution_lock
        data["execution_lock"] = execution_lock(p["module"], (self._project().get("workflow") or {}).get("mode"))
        data.update(inputs=inputs, thread_id=p.get("thread_id"), artifact_id=p.get("artifact_id"), status="created", created_at=now(), checkpoints=[], bound_versions=inputs)
        from .conversations1170 import frozen_source_for_task, task_frozen_source_ref
        source = frozen_source_for_task(self, data)
        if source is not None:
            data.update(conversation_source_reference=source, conversation_source_binding_sha256=source["binding_sha256"])
        frozen_source = task_frozen_source_ref(self, data)
        self._fresh([ref for ref in inputs if ref != frozen_source])
        if style_binding:
            data["style_binding"] = style_binding
            data["style_execution_lock"] = self._style_binding_lock(data)
        if p["module"] in STYLE_MODULES:
            data.update(style_context=self._style_context(inputs))
            if style_binding and style_binding["mode"] == "frozen_reference":
                data["style_context"].update(status="frozen_reference", reference_mode="frozen_reference",
                    frozen_reference=deepcopy(style_binding["artifact"]), reference_reason=style_binding["reason"], missing_context=[])
            data["missing_context"] = data["style_context"]["missing_context"]
        self._put("tasks", "task_id", p["task_id"], data)
        return data

    def _checkpoint(self, p):
        required(p, "task_id", "draft", "completed", "decisions", "unresolved", "next_step")
        for field in ("draft", "next_step"):
            text_value(p[field], field)
        for field in ("completed", "decisions", "unresolved"):
            item_list(p[field], field)
        task = self._get("tasks", "task_id", p["task_id"])
        if task["status"] in ("submitted", "cancelled"):
            raise ConflictError("已关闭任务不能再写检查点")
        from .modules import require_execution
        require_execution(task)
        self._check_style_binding(task)
        from .conversations1170 import task_frozen_source_ref
        task_frozen_source_ref(self, task)
        checkpoint = {key: p[key] for key in ("draft", "completed", "decisions", "unresolved", "next_step")}
        checkpoint.update(checkpoint_id=p["op_id"], saved_at=now(), draft_sha256=content_hash(p["draft"]), inputs=task["inputs"])
        if task.get("style_binding"):
            checkpoint.update(style_binding=deepcopy(task["style_binding"]), style_execution_lock=deepcopy(task["style_execution_lock"]))
        task["checkpoints"].append(checkpoint)
        if task["status"] != "needs_review":
            task["status"] = "in_progress"
        self._put("tasks", "task_id", p["task_id"], task)
        return {"task_id": p["task_id"], "checkpoint": checkpoint, "status": task["status"]}

    def _resume(self, task_id):
        task = self._get("tasks", "task_id", task_id)
        from .modules import execution_status
        compatibility = execution_status(task)
        from .conversations1170 import task_frozen_source_ref
        frozen_source = None
        try:
            frozen_source = task_frozen_source_ref(self, task)
        except (ConflictError, ValueError) as exc:
            compatibility = dict(compatibility, compatible=False, reason="frozen_conversation_source_changed", message=str(exc))
        if compatibility["compatible"]:
            try:
                self._check_style_binding(task)
            except ConflictError as exc:
                compatibility = dict(compatibility, compatible=False, reason="frozen_style_reference_changed", message=str(exc))
        frozen = [self._artifact(r["artifact_id"], r["version"]) for r in task["inputs"]]
        stale = []
        for ref in task["inputs"]:
            if ref == frozen_source:
                continue
            current = self._current_dependency(ref)
            if self._dependency_stale(ref):
                stale.append({"bound": ref, "current_version": current["version"], "status": current["status"]})
        return {"execution_compatibility": compatibility, "project": self._project(), "task": task, "frozen_inputs": frozen, "checkpoint": task["checkpoints"][-1] if task["checkpoints"] else None, "stale_inputs": stale, "project_root": str(self.root), "read_only": True}

    def _submit(self, p):
        required(p, "task_id", "artifact_id", "kind", "content", "base_version")
        task = self._get("tasks", "task_id", p["task_id"])
        if task["status"] in ("submitted", "cancelled"):
            raise ConflictError("任务已关闭")
        if p["kind"] not in output_kinds(task["module"]):
            raise ConflictError("提交成果类型与任务模块不符")
        if task.get("artifact_id") and task["artifact_id"] != p["artifact_id"]:
            raise ConflictError("提交成果 ID 与任务锁定目标不符")
        from .modules import require_execution
        require_execution(task)
        effective_inputs, style_reference = self._task_effective_inputs(task, p["artifact_id"])
        prior = self._artifact(p["artifact_id"])
        prior_reference = prior["metadata"].get("style_reference") if prior else None
        if prior_reference:
            if style_reference:
                style_reference["previous_reference"] = self._previous_style_reference(prior)
            else:
                self._check_style_reference(prior_reference)
                explicit_style = {k: prior_reference["artifact"][k] for k in ("artifact_id", "version")}
                if prior_reference["mode"] == "hard_dependency" and explicit_style not in effective_inputs:
                    raise ConflictError("任务不能省略原明确风格依赖")
                style_reference = deepcopy(prior_reference)
        metadata = dict(p.get("metadata") or {})
        if "style_reference" in metadata and metadata["style_reference"] != style_reference:
            raise ConflictError("提交不能伪造或替换冻结风格参考")
        if style_reference:
            metadata["style_reference"] = style_reference
        metadata["execution_lock"] = task["execution_lock"]
        save = dict(p, scope=task["scope"], deps=effective_inputs, metadata=metadata)
        result = self._save(save, trusted_task=task)
        task.update(status="submitted", submitted_at=now(), output={"artifact_id": p["artifact_id"], "version": result["artifact"]["version"]})
        if style_reference:
            task.update(submitted_style_reference=deepcopy(style_reference), submitted_inputs=deepcopy(effective_inputs))
        self._put("tasks", "task_id", p["task_id"], task)
        return dict(result, task=task)

    def _cancel(self, p):
        required(p, "task_id", "reason")
        task = self._get("tasks", "task_id", p["task_id"])
        if task["status"] == "submitted":
            raise ConflictError("已提交任务不能取消")
        task.update(status="cancelled", cancellation_reason=p["reason"], cancelled_at=now())
        self._put("tasks", "task_id", p["task_id"], task)
        return task

    def _decision(self, p):
        required(p, "artifact_id", "version", "scope", "decision", "evidence", "actor", "synthetic")
        ref = self._ref(p)
        if type(p["synthetic"]) is not bool:
            raise ValueError("synthetic 必须为布尔值")
        if self._project()["test_only"] and not p["synthetic"]:
            raise ValueError("测试项目只能记录 synthetic 决定，不可冒充真人采用")
        self._validate_authorization(p)
        if p["decision"] not in ("adopt", "reject", "review", "deliver", "publish"):
            raise ValueError("decision 必须为 adopt/reject/review/deliver/publish")
        artifact = self._artifact(ref["artifact_id"], ref["version"])
        if p["decision"] == "adopt" and p["scope"] == artifact["scope"]:
            result = self._approve(p)
            return dict(result["decision"], approval=result)
        data = {key: p[key] for key in ("artifact_id", "version", "scope", "decision", "evidence", "actor", "synthetic")}
        data.update(decision_id=p["op_id"], created_at=now(), sealed_sha256=artifact["sha256"], sealed_content=artifact["content"], user_authorization=p.get("user_authorization"))
        if p["decision"] == "adopt":
            data.update(approval_status="scope_mapping_required", updates_master=False)
        self._put("decisions", "decision_id", p["op_id"], data)
        return data

    def _master(self, category, version=None):
        if version is None:
            row = self.db.execute("SELECT data FROM master_revisions WHERE category=? ORDER BY version DESC LIMIT 1", (category,)).fetchone()
        else:
            row = self.db.execute("SELECT data FROM master_revisions WHERE category=? AND version=?", (category, version)).fetchone()
        if not row:
            return None
        data = json.loads(row[0])
        for segment in data.get("segments", []):
            # Enrich the read view from immutable exact revisions, not current drafts.
            artifact = self._artifact(segment["artifact_id"], segment["version"])
            segment["metadata"] = artifact["metadata"] if artifact else {}
        sync = self.db.execute("SELECT data FROM master_sync WHERE category=? AND version=?", (category, data["version"])).fetchone()
        data.update(json.loads(sync[0]) if sync else {"sync_status": "unbound"})
        return data

    def _validate_authorization(self, p):
        if p["synthetic"]:
            return
        auth = p.get("user_authorization")
        if p["actor"] != "human" or not isinstance(auth, dict):
            raise ValueError("真人决定需要宿主传入结构化 user_authorization 原话证据；系统不能自行采用")
        required(auth, "quote", "artifact_id", "version", "scope", "observed_at")
        if any(auth[key] != p[key] for key in ("artifact_id", "version", "scope")):
            raise ValueError("真人授权必须绑定本次精确成果版本及采用范围")
        text_value(auth["quote"], "user_authorization.quote")
        if not auth["quote"].strip():
            raise ValueError("用户操作证据不得为空")
        source = auth.get("source")
        if source == "panel-click":
            # An explicit UI action is evidence of the action, not a verified
            # account identity. Unknown account IDs must remain null.
            required(auth, "actor_identity")
        elif source == "conversation":
            required(auth, "thread_id")
        else:
            required(auth, "real_user_id")
        try:
            observed = datetime.fromisoformat(auth["observed_at"].replace("Z", "+00:00"))
            if observed.tzinfo is None:
                raise ValueError()
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("授权 observed_at 必须为带时区 ISO 8601") from exc

    def _binding(self, category):
        row = self.db.execute("SELECT data FROM master_bindings WHERE category=?", (category,)).fetchone()
        return json.loads(row[0]) if row else None

    def _set_master_sync(self, category, version, data):
        self.db.execute("INSERT INTO master_sync VALUES(?,?,?) ON CONFLICT(category,version) DO UPDATE SET data=excluded.data", (category, version, canonical(data)))

    def _approve(self, p):
        required(p, "artifact_id", "version", "scope", "evidence", "actor", "synthetic")
        ref = self._ref(p)
        artifact = self._artifact(ref["artifact_id"], ref["version"])
        if artifact["kind"] in NON_APPROVABLE_KINDS:
            raise ValueError("云稿观察或技术渲染记录不能直接批准并入创作总稿；请保存明确创作分段候选")
        if artifact["metadata"].get("deleted_in_cloud"):
            raise ValueError("云端删除观察只是待审核标记，不能把诊断占位正文批准进总稿；请先明确删除范围及处理方式并保存实际内容候选")
        if p["scope"] != artifact["scope"]:
            raise ValueError("批准范围必须与该成果分段 scope 完全一致；局部批准请先保存独立分段候选")
        if type(p["synthetic"]) is not bool:
            raise ValueError("synthetic 必须为布尔值")
        if self._project()["test_only"] and not p["synthetic"]:
            raise ValueError("测试项目只能记录 synthetic 决定，不可冒充真人采用")
        text_value(p["evidence"], "evidence")
        if not p["evidence"].strip():
            raise ValueError("批准必须保留明确用户操作或原话证据")
        self._validate_authorization(p)
        category = content_category(artifact)
        current = self._master(category)
        current_version = current["version"] if current else 0
        pointer = self._approved_pointer(artifact)
        if pointer and pointer["artifact_id"] != artifact["artifact_id"]:
            raise ConflictError("该分类与分段已有稳定成果 ID；请在原成果 ID 下保存修改候选")
        if pointer and pointer["version"] == artifact["version"]:
            return {"artifact": artifact, "approval": pointer, "decision": self._get("decisions", "decision_id", pointer["approval_id"]), "master": current, "already_approved": True, "invalidated": []}
        if "base_master_version" in p and (type(p["base_master_version"]) is not int or p["base_master_version"] != current_version):
            raise ConflictError(f"总稿基础版本冲突: expected={p['base_master_version']}, current={current_version}")
        if pointer and artifact["version"] < pointer["version"]:
            raise ConflictError("恢复历史内容必须 artifact.restore 保存为新候选，不能倒退已通过指针")
        if artifact["metadata"].get("style_reference", {}).get("mode") == "frozen_reference":
            self._check_style_reference(artifact["metadata"]["style_reference"])
        self._fresh(artifact["deps"])
        from .art1130 import guard_style_approval
        guard_style_approval(self, artifact)
        approval = {"artifact_id": artifact["artifact_id"], "version": artifact["version"], "scope": artifact["scope"], "category": category, "approval_id": p["op_id"], "approved_at": now(), "synthetic": p["synthetic"], "review_status": "approved"}
        self.db.execute("INSERT INTO approved_segments VALUES(?,?,?) ON CONFLICT(category,scope) DO UPDATE SET data=excluded.data", (category, artifact["scope"], canonical(approval)))
        self.db.execute("UPDATE artifacts SET status='approved' WHERE artifact_id=? AND version=?", (artifact["artifact_id"], artifact["version"]))
        decision = {key: p[key] for key in ("artifact_id", "version", "scope", "evidence", "actor", "synthetic")}
        decision.update(decision="adopt", decision_id=p["op_id"], created_at=now(), sealed_sha256=artifact["sha256"], sealed_content=artifact["content"], user_authorization=p.get("user_authorization"), approval_status="approved", updates_master=True, category=category)
        self._put("decisions", "decision_id", p["op_id"], decision)
        segments = []
        for row in self.db.execute("SELECT data FROM approved_segments WHERE category=?", (category,)):
            item = json.loads(row[0])
            saved = self._artifact(item["artifact_id"], item["version"])
            segments.append({"artifact_id": saved["artifact_id"], "version": saved["version"], "scope": saved["scope"], "title": saved["metadata"].get("title") or saved["scope"], "order": segment_order(saved), "content": saved["content"], "sha256": saved["sha256"], "approval_id": item["approval_id"]})
        segments.sort(key=segment_sort)
        content = "\n\n".join("## " + str(item["title"]) + "\n\n" + (item["content"] if isinstance(item["content"], str) else json.dumps(item["content"], ensure_ascii=False, indent=2, allow_nan=False)) for item in segments)
        master = {"category": category, "version": current_version + 1, "parent_version": current_version or None, "content": content, "sha256": content_hash(content), "segments": segments, "changed_segments": [ref], "approval_id": p["op_id"], "created_at": now(), "status": "approved", "synthetic": p["synthetic"]}
        self.db.execute("INSERT INTO master_revisions VALUES(?,?,?)", (category, master["version"], canonical(master)))
        binding = self._binding(category)
        self._set_master_sync(category, master["version"], {"sync_status": "pending" if binding else "unbound", "page_id": binding["page_id"] if binding else None, "base_revision": binding["base_revision"] if binding else None})
        affected = self._invalidate(artifact["artifact_id"], artifact["version"])
        return {"artifact": self._artifact(artifact["artifact_id"], artifact["version"]), "approval": approval, "decision": decision, "master": self._master(category), "already_approved": False, "invalidated": affected}

    def _bind_master(self, p):
        required(p, "category", "page_id", "base_revision")
        from .cloud1120 import guard_legacy_page_write
        guard_legacy_page_write(self, p["page_id"], binding=True)
        if p["category"] not in CATEGORIES:
            raise ValueError("内容 category 无效")
        identifier(p["page_id"], "page_id")
        if any(item["page_id"] == p["page_id"] and item["category"] != p["category"] for item in self._list("master_bindings")):
            raise ConflictError("同一页面不能绑定两个整稿分类；请为该分类指定独立页面，避免整页同步互相覆盖")
        previous = self._binding(p["category"])
        if previous and previous["page_id"] == p["page_id"] and revision_precedes(p["base_revision"], previous["base_revision"]):
            raise ConflictError("云稿绑定修订不能倒退；保留最新确认修订")
        if previous and previous["page_id"] != p["page_id"] and any(item.get("master_category") == p["category"] and item["status"] in ("intent", "sent", "unknown") for item in self._list("sync")):
            raise ConflictError("该分类有未决云同步，核查后才能更换页面")
        data = {"category": p["category"], "page_id": p["page_id"], "base_revision": p["base_revision"], "bound_at": now()}
        self._put("master_bindings", "category", p["category"], data)
        master = self._master(p["category"])
        if master and (not previous or previous["page_id"] != p["page_id"]):
            self._set_master_sync(p["category"], master["version"], {"sync_status": "pending", "page_id": p["page_id"], "base_revision": p["base_revision"]})
        return {"binding": data, "master": self._master(p["category"])}

    def _thread(self, p):
        required(p, "thread_id", "title", "scope", "status")
        identifier(p["thread_id"], "thread_id")
        if p.get("task_id"):
            self._get("tasks", "task_id", p["task_id"])
        if p.get("current_control"):
            for item in self._list("threads"):
                if item.get("current_control") and item["thread_id"] != p["thread_id"]:
                    item["current_control"] = False
                    self._put("threads", "thread_id", item["thread_id"], item)
        row = self.db.execute("SELECT data FROM threads WHERE thread_id=?", (p["thread_id"],)).fetchone()
        previous = json.loads(row[0]) if row else {}
        data = dict(previous, **{k: p[k] for k in ("thread_id", "title", "scope", "status")})
        data.update(task_id=p.get("task_id", previous.get("task_id")), current_control=bool(p.get("current_control", previous.get("current_control", False))), updated_at=now())
        for key in ("purpose", "client_project_id", "thread_url"):
            if key in p:
                text_value(p[key], key)
                data[key] = p[key]
        if "artifact_refs" in p:
            data["artifact_refs"] = self._deps(p["artifact_refs"])
        data.setdefault("purpose", "")
        data.setdefault("artifact_refs", [])
        data["host_thread_created_by_registry"] = False
        self._put("threads", "thread_id", p["thread_id"], data)
        return data

    def _sync_intent(self, p):
        required(p, "sync_id", "page_id", "base_revision", "intended_content")
        from .cloud1120 import guard_legacy_page_write
        guard_legacy_page_write(self, p["page_id"])
        if self.db.execute("SELECT 1 FROM sync WHERE sync_id=?", (p["sync_id"],)).fetchone():
            raise ConflictError("sync_id 已存在；结果未知时请读回核查，不要再次发送")
        for item in self._list("sync"):
            if item["page_id"] == p["page_id"] and item["status"] in ("intent", "sent", "unknown"):
                raise ConflictError("同一页面存在未完成发送意图，须先读回核查")
        data = {key: p[key] for key in ("sync_id", "page_id", "base_revision", "intended_content")}
        if "master_category" in p or "master_version" in p:
            required(p, "master_category", "master_version")
            if type(p["master_version"]) is not int or p["master_version"] < 1:
                raise ValueError("master_version 必须为正整数")
            master = self._master(p["master_category"], p["master_version"])
            binding = self._binding(p["master_category"])
            if not master or not binding or binding["page_id"] != p["page_id"]:
                raise ConflictError("总稿不存在或云稿绑定不匹配")
            if self._master(p["master_category"])["version"] != p["master_version"]:
                raise ConflictError("只有当前已通过总稿可创建云同步意图")
            if binding["base_revision"] != p["base_revision"]:
                raise ConflictError("云同步基础修订与最后确认绑定不符，须先读回核查")
            if content_hash(p["intended_content"]) != master["sha256"]:
                raise ConflictError("总稿同步内容必须与所指已通过版本完全一致")
            data.update(master_category=p["master_category"], master_version=p["master_version"])
        data.update(status="intent", intended_sha256=content_hash(p["intended_content"]), created_at=now(), last_observed_at=None, observations=[], authority="Pages editable working draft", cloud_write_performed_by_registry=False, cloud_write_executor="host-tools")
        self._put("sync", "sync_id", p["sync_id"], data)
        if data.get("master_category"):
            self._set_master_sync(data["master_category"], data["master_version"], {"sync_status": "pending", "sync_id": p["sync_id"], "page_id": p["page_id"], "base_revision": p["base_revision"]})
        return data

    def _sync_observe(self, p):
        required(p, "sync_id", "status")
        data = self._get("sync", "sync_id", p["sync_id"])
        status = p["status"]
        if status not in ("sent", "unknown", "verified", "conflict", "failed"):
            raise ValueError("同步状态无效")
        if data["status"] in ("verified", "conflict", "failed"):
            raise ConflictError("同步操作已结束；新编辑请创建新发送意图")
        if data["status"] == "unknown" and status == "sent":
            raise ConflictError("未知结果不能直接标为重发；必须核查云端内容")
        if status == "verified":
            required(p, "observed_content", "revision")
            if content_hash(p["observed_content"]) != data["intended_sha256"]:
                status = "conflict"
        observation = {key: p.get(key) for key in ("receipt", "observed_content", "revision", "comments")}
        observed_at = p.get("observed_at") or now()
        try:
            parsed_observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            if parsed_observed.tzinfo is None:
                raise ValueError("观察时间缺少时区")
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("observed_at 必须为带时区的 ISO 8601 实际观察时间") from exc
        earliest = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
        if data.get("last_observed_at"):
            earliest = max(earliest, datetime.fromisoformat(data["last_observed_at"].replace("Z", "+00:00")))
        if parsed_observed < earliest:
            raise ConflictError("云端观察时间不能早于本次同步意图或上次观察；旧证据不能确认新写入")
        if status == "verified" and revision_precedes(p.get("revision"), data["base_revision"]):
            raise ConflictError("读回修订早于本次同步基础修订，不能验证写入")
        observation.update(status=status, observed_at=observed_at, recorded_at=now())
        data["observations"].append(observation)
        data.update(status=status, receipt=p.get("receipt"), last_observed_at=observation["observed_at"], observed_content=p.get("observed_content"), revision=p.get("revision"), comments=p.get("comments"))
        # The registry does not itself contact Pages; host receipts describe the cloud action.
        data.pop("cloud_write_performed", None)
        data.update(cloud_write_performed_by_registry=False, cloud_write_executor="host-tools")
        self._put("sync", "sync_id", p["sync_id"], data)
        if data.get("master_category"):
            self._set_master_sync(data["master_category"], data["master_version"], {"sync_status": status if status in ("verified", "conflict", "failed") else "pending", "sync_id": data["sync_id"], "page_id": data["page_id"], "base_revision": data["base_revision"], "revision": p.get("revision"), "last_observed_at": observation["observed_at"]})
            if status == "verified":
                binding = self._binding(data["master_category"])
                if binding and binding["page_id"] == data["page_id"] and binding["base_revision"] == data["base_revision"]:
                    binding.update(base_revision=p["revision"], last_verified_at=observation["observed_at"])
                    self._put("master_bindings", "category", data["master_category"], binding)
                    current = self._master(data["master_category"])
                    if current and current["version"] != data["master_version"] and current.get("sync_status") == "pending" and not current.get("sync_id"):
                        self._set_master_sync(data["master_category"], current["version"], {"sync_status": "pending", "page_id": data["page_id"], "base_revision": p["revision"]})
        return data

    def _content_views(self):
        latest = [item for item in self._latest() if item["kind"] not in NON_APPROVABLE_KINDS]
        pointers = [json.loads(row[0]) for row in self.db.execute("SELECT data FROM approved_segments")]
        approved, pending, current = [], [], []
        for pointer in pointers:
            artifact = self._artifact(pointer["artifact_id"], pointer["version"])
            if artifact["kind"] in NON_APPROVABLE_KINDS:
                continue
            artifact.update(category=pointer["category"], approval_status=pointer["review_status"], approval=pointer)
            newest = self._artifact(pointer["artifact_id"])
            artifact["pending_candidate_version"] = newest["version"] if newest["version"] > pointer["version"] else None
            approved.append(artifact)
            current.append(dict(artifact))
        for artifact in latest:
            pointer = self._approved_pointer(artifact)
            artifact.update(category=content_category(artifact))
            if not pointer:
                artifact.update(approval_status="initial_draft", pending_candidate_version=artifact["version"])
                current.append(dict(artifact))
            if not pointer or pointer["artifact_id"] != artifact["artifact_id"] or pointer["version"] < artifact["version"]:
                artifact.update(approval_status="pending_review", approved_version=pointer["version"] if pointer and pointer["artifact_id"] == artifact["artifact_id"] else None)
                artifact["input_status"] = "stale" if any(self._dependency_stale(ref) for ref in artifact["deps"]) else "current"
                pending.append(artifact)
        for items in (approved, pending, current):
            for artifact in items:
                if artifact["category"] in STYLE_CATEGORIES:
                    # Current provenance warning is a read view. The revision's
                    # original metadata/dependencies stay untouched, including legacy data.
                    artifact["style_context"] = self._style_context(artifact["deps"], recorded=False)
            items.sort(key=lambda item: (item["category"], segment_sort(dict(item, order=segment_order(item)))))
        return approved, pending, current

    def _media(self, p):
        required(p, "media_id", "kind", "path", "metadata")
        identifier(p["media_id"], "media_id")
        if self.db.execute("SELECT 1 FROM media WHERE media_id=?", (p["media_id"],)).fetchone():
            raise ConflictError("媒体 ID 已存在；新原件使用新 ID")
        if p["kind"] not in ("image", "video", "audio", "project", "other"):
            raise ValueError("媒体 kind 必须为 image/video/audio/project/other")
        source = Path(p["path"]).expanduser().resolve()
        if not source.is_file():
            raise ValueError("媒体源文件不存在")
        if not isinstance(p["metadata"], dict):
            raise ValueError("metadata 必须为对象")
        metadata = dict(p["metadata"])
        if "asset_type" in metadata:
            validate_asset_type(metadata["asset_type"])
        duration = metadata.get("duration_seconds")
        if duration is not None and (type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0):
            raise ValueError("媒体时长无效")
        with source.open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        # One canonical original per type/hash. Never store a preview as a second original.
        folders = {"image": "03-资产/图片原件", "video": "05-片段/视频原件", "audio": "06-音乐/音频原件", "project": "07-成片/剪辑工程", "other": "00-设定与依据/原始资料"}
        existing = next((item for item in self._list("media") if item["kind"] == p["kind"] and item["sha256"] == sha), None)
        relative = existing["path"] if existing else f"{folders[p['kind']]}/{sha}{source.suffix.lower()}"
        destination = self._media_destination(relative, create=True)
        if not destination.exists():
            temp = destination.parent / (".media-" + uuid.uuid4().hex + ".tmp")
            try:
                self._media_destination(relative)
                with source.open("rb") as incoming, temp.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
                with temp.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != sha:
                        raise ConflictError("复制期间媒体源变化")
                self._media_destination(relative)
                # Never replace an existing original, link or concurrently
                # published file. A concurrent identical file is verified below.
                try:
                    if os.name == "nt":
                        os.rename(temp, destination)
                    else:
                        os.link(temp, destination, follow_symlinks=False)
                        temp.unlink()
                except FileExistsError:
                    pass
            finally:
                if temp.exists():
                    from .documents import _plain_path
                    self._media_destination(relative)
                    _plain_path(temp, directory=False)
                    temp.unlink()
        destination = self._media_destination(relative)
        with destination.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != sha:
                raise ConflictError("现存原件哈希不匹配")
        metadata.setdefault("rights_status", None)
        metadata.setdefault("stems", None)
        metadata.setdefault("technical_check", None)
        data = dict(media_id=p["media_id"], kind=p["kind"], path=relative, source_path=str(source), sha256=sha, size_bytes=destination.stat().st_size, metadata=metadata, registered_at=now(), status="registered", synthetic=self._project()["test_only"], classification_revision=0)
        self._put("media", "media_id", p["media_id"], data)
        return data

    def _media_destination(self, relative, *, create=False):
        """Validate every original-store component before any file write."""
        from .documents import _plain_path
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ConflictError("媒体原件路径必须为项目内规范相对路径")
        root = self.root.resolve(strict=True)
        _plain_path(root, directory=True)
        current = root
        parts = Path(relative).parts
        for part in parts[:-1]:
            current = current / part
            if create:
                current.mkdir(exist_ok=True)
            _plain_path(current, directory=True)
            if current.resolve(strict=True) != current or not current.is_relative_to(root):
                raise ConflictError("媒体原件目录越出本项目")
        target = current / parts[-1]
        if target.exists() or target.is_symlink():
            _plain_path(target, directory=False)
        if target.resolve(strict=False).parent != current:
            raise ConflictError("媒体原件路径不在已核验目录内")
        return target

    def _media_management_target(self, p, base_revision):
        """Verify a registered original inside the dispatch write transaction."""
        identifier(p["media_id"], "media_id")
        if type(base_revision) is not int or base_revision < 0:
            raise ValueError("base_revision 必须为非负整数")
        media = self._get("media", "media_id", p["media_id"])
        if media.get("media_id") != p["media_id"]:
            raise ConflictError("媒体 ID 与登记记录不符")
        revision = media.get("classification_revision", 0)
        if type(revision) is not int or revision < 0:
            raise ConflictError("媒体管理修订号无效")
        if base_revision != revision:
            raise ConflictError(f"媒体管理修订冲突: expected={base_revision}, current={revision}")
        if p["expected_sha256"] != media["sha256"]:
            raise ConflictError("媒体原件摘要与所选记录不符")
        relative = media.get("path")
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ConflictError("媒体原件路径必须为当前项目内的相对路径")
        original = (self.root / relative).resolve()
        if not original.is_relative_to(self.root) or not original.is_file():
            raise ConflictError("媒体原件缺失或越出当前项目")
        with original.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != media["sha256"]:
                raise ConflictError("媒体原件字节与登记摘要不符")
        return media, revision

    @staticmethod
    def _media_management_fields(media):
        """Keep absent legacy labels absent in the before/after audit."""
        metadata = media.get("metadata", {})
        fields = {key: metadata[key] for key in ("title", "asset_type", "video_category") if key in metadata}
        return {"metadata": fields, "classification_revision": media.get("classification_revision", 0),
                **{key: media[key] for key in ("classified_at", "management_updated_at") if key in media}}

    def _media_classify(self, p):
        required(p, "expected_project_id", "media_id", "expected_sha256", "asset_type")
        value = validate_asset_type(p["asset_type"])
        media, revision = self._media_management_target(p, p.get("base_revision", 0))
        before = self._media_management_fields(media)
        metadata = dict(media.get("metadata", {}))
        metadata["asset_type"] = value
        media.update(metadata=metadata, classification_revision=revision + 1,
                     classified_at=now())
        self._put("media", "media_id", p["media_id"], media)
        readback = self._get("media", "media_id", p["media_id"])
        if readback != media:
            raise ConflictError("媒体分类读回不一致")
        return {"media": readback, "asset_type": value, "classification_only": True,
                "readback_verified": True,
                "management_change": {"before": before, "after": self._media_management_fields(readback)}}

    def _media_update(self, p):
        required(p, "expected_project_id", "media_id", "expected_sha256", "base_revision", "title")
        allowed = {"op_id", "expected_project_id", "media_id", "expected_sha256", "base_revision",
                   "title", "asset_type", "video_category"}
        if set(p) - allowed:
            raise ValueError("media.update 仅接受媒体名称和分类管理字段")
        title = p["title"]
        if not isinstance(title, str) or not title.strip() or len(title) > 500 or any(ord(c) < 32 for c in title):
            raise ValueError("title 必须为非空单行文字，最多500字符")
        title = title.strip()
        sha = p["expected_sha256"]
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError("expected_sha256 必须为准确的64位小写摘要")
        media, revision = self._media_management_target(p, p["base_revision"])
        if media["kind"] == "image":
            required(p, "asset_type")
            if "video_category" in p:
                raise ValueError("图片只允许 asset_type 分类")
            field, value = "asset_type", validate_asset_type(p["asset_type"])
        elif media["kind"] == "video":
            required(p, "video_category")
            if "asset_type" in p:
                raise ValueError("视频只允许 video_category 分类")
            field, value = "video_category", p["video_category"]
            if not isinstance(value, str) or value not in ("take", "clip", "final", "unclassified"):
                raise ValueError("video_category 必须为 take/clip/final/unclassified")
        else:
            raise ValueError("媒体名称和分类管理仅支持 image/video")

        before = self._media_management_fields(media)
        metadata = dict(media.get("metadata", {}))
        metadata.update({"title": title, field: value})
        timestamp = now()
        media.update(metadata=metadata, classification_revision=revision + 1,
                     classified_at=timestamp, management_updated_at=timestamp)
        self._put("media", "media_id", p["media_id"], media)
        readback = self._get("media", "media_id", p["media_id"])
        if readback != media:
            raise ConflictError("媒体管理读回不一致")
        return {"media": readback, "management_only": True, "readback_verified": True,
                "management_change": {"before": before, "after": self._media_management_fields(readback)}}

    def _cue(self, p):
        required(p, "cue_id")
        return self._save(dict(p, artifact_id=p["cue_id"], kind="cue", scope=p.get("scope", "music/" + p["cue_id"])))

    def snapshot(self):
        with self.lock:
            # Consistent multi-table read; no event or write occurs on refresh.
            self.db.execute("BEGIN")
            try:
                result = {"project": self._project(), "artifacts": self._latest(), "tasks": self._list("tasks"), "threads": self._list("threads"), "decisions": self._list("decisions"), "sync": self._list("sync"), "media": self._list("media"), "events": [dict(row, data=json.loads(row["data"])) for row in self.db.execute("SELECT * FROM events ORDER BY event_id DESC LIMIT 200")], "capabilities": {"registry": True, "task_resume": True, "version_dependencies": True, "artifact_history": True, "music_data": True, "music_creation": False, "original_screenplay_workflow": "host-workflow", "cloud": "host-tools-required", "client_plugin": "client-verification-separate", "http_server_required": False, "external_model_api_required": False, "module_output_kinds": {name: sorted(output_kinds(name)) for name in ("idea", "requirements", "idea-explorer", "requirements-planner", "story", "screenplay", "director", "vfx", "assets", "video_prompt", "research", "music", "editing", "review", "director-agent", "vfx-agent", "seedance-prompt", "film-analysis", "novel-master", "novel-to-screenplay")}, "system_version": __version__}, "observed_at": now(), "project_root": str(self.root)}
                approved, pending, current = self._content_views()
                migration = self.db.execute("SELECT value FROM settings WHERE key='schema2_migration'").fetchone()
                result.update(schema_version=2, approved_artifacts=approved, pending_candidates=pending, current_content=current, masters=[self._master(row[0]) for row in self.db.execute("SELECT DISTINCT category FROM master_revisions ORDER BY category")], master_bindings=self._list("master_bindings"), migration=json.loads(migration[0]) if migration else None)
                result["workflow"] = workflow_view(result["project"], approved, pending)
                result["global_style"] = result["workflow"]["global_style"]
                result["planning_records"] = [{"record_id": a["artifact_id"], "version": a["version"], "scope": a["scope"], "record_kind": a["content"]["record_kind"], "title": a["content"]["title"], "status": a["content"]["state"].get("status"), "next_step": a["content"]["state"].get("next_step")} for a in result["artifacts"] if a["kind"] == "planning_record"]
                result["capabilities"].update(planning_records=True, idea_exploration=True, requirements_planning=True, planning_approval_is_execution_authorization=False)
                result["capabilities"].update(content_approval=True, partial_master_assembly=True, master_history=True, artifact_restore=True, candidate_isolation=True)
                result["capabilities"].update(project_workflow=True, character_bio=True, global_style_reference=True, stage_completion_inference=False)
                add_asset_views(result, content_category)
                result["capabilities"].update(asset_classification=True, media_management=True, document_export=True, document_save=True)
                result["capabilities"].update(compact_context=True, file_authoring=True, checkpoint_submission=True)
                result["presentation"] = presentation_view(self)
                result["capabilities"].update(presentation_management=True)
                result["board_order"] = board_order_view(self)
                result["trash"] = trash_view(self)
                result["capabilities"].update(board_ordering=True, trash_management=True)
                result["workspace"] = workspace_view(self)
                from .conversations1170 import conversation_view
                result["conversations"] = conversation_view(self)
                result["capabilities"].update(hierarchical_conversations=True, host_outbox=True, background_chat_scheduler=False)
                result["capabilities"].update(conversation_workspace=True, host_chat_execution=False)
                from .delivery1110 import delivery_summary
                result["delivery"] = delivery_summary(self)
                result["capabilities"].update(delivery_contracts=True, delivery_completion_is_approval=False)
                from .cloud1120 import cloud_summary
                result["cloud"] = cloud_summary(self)
                result["capabilities"].update(round_end_cloud_workflow=True, cloud_background_sync=False)
                from .art1130 import art_summary
                result["art"] = art_summary(self)
                result["capabilities"].update(art_direction_comparison=True, art_selection_is_approval=False)
                result["capabilities"]["module_output_kinds"].update({name: sorted(output_kinds(name)) for name in ("art_director", "film-art-director")})
                from .screenwriting1130 import screenwriting_summary
                result["screenwriting"] = screenwriting_summary(self)
                result["capabilities"].update(screenwriting=True, screenplay_default_recommended=True, director_feedback=True, original_screenplay_workflow="bundled-screenwriter")
                result["capabilities"]["module_output_kinds"].update({name: sorted(output_kinds(name)) for name in ("screenwriter", "adaptation")})
                from .board1150 import filter_new_input_suggestions, library_view
                filter_new_input_suggestions(self, result["workflow"])
                result["board_library"] = library_view(self, result)
                from .board1180 import view as creator_view
                result["creator_board"] = creator_view(self, result)
                from .previs1190 import view as previs_view
                result["previs"] = previs_view(self)
                result["capabilities"].update(board_explicit_decisions=True, board_object_assets=True)
                result["capabilities"].update(board_management_only=False, board_reference=True,
                                               board_audio_library=True, board_business_execution=False)
                self.db.execute("COMMIT")
                return result
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def _backup_dispatch(self, action, p, request_hash):
        # Filesystem + SQLite cannot be one atomic transaction. Completed backup
        # manifests make a crash after file replacement recoverable by op_id.
        if action == "backup.create":
            result = self._backup_create(p, request_hash)
        else:
            result = self._backup_restore(p, request_hash)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            cached = self._cached(p["op_id"], request_hash)
            if cached is not None:
                self.db.execute("COMMIT")
                return cached
            self._event(action, {"op_id": p["op_id"], "result": result})
            self.db.execute("INSERT INTO operations VALUES(?,?,?,?)", (p["op_id"], request_hash, canonical(result), now()))
            self.db.execute("COMMIT")
            return result
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def _backup_create(self, p, request_hash):
        required(p, "destination")
        if not self._project():
            raise ValueError("项目未初始化")
        target = Path(p["destination"]).expanduser().resolve()
        if target.is_relative_to(self.root):
            raise ValueError("备份必须保存于项目目录之外，避免递归备份")
        if target.exists():
            try:
                with zipfile.ZipFile(target) as z:
                    manifest = json.loads(z.read("backup-manifest.json"))
                if manifest.get("op_id") == p["op_id"] and manifest.get("request_hash") == request_hash:
                    return manifest["result"]
            except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                pass
            raise ConflictError("备份目标已存在，拒绝覆盖")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="filmprod-backup-") as temp:
            snapshot = Path(temp) / "registry.sqlite3"
            copydb = sqlite3.connect(snapshot)
            self.db.backup(copydb)
            copydb.close()
            files = {".project/registry.sqlite3": snapshot}
            for path in self.root.rglob("*"):
                if path.is_symlink():
                    raise ValueError("项目含符号链接，备份拒绝隐式跟随")
                if not path.is_file() or path.name in ("registry.sqlite3", "registry.sqlite3-wal", "registry.sqlite3-shm") or path.name.endswith(".tmp"):
                    continue
                relative = path.relative_to(self.root).as_posix()
                if relative == "backup-manifest.json":
                    continue
                files[relative] = path
            entries = {}
            for relative, path in files.items():
                with path.open("rb") as stream:
                    entries[relative] = {"sha256": hashlib.file_digest(stream, "sha256").hexdigest(), "size": path.stat().st_size}
            result = {"destination": str(target), "file_count": len(entries), "project_id": self._project()["project_id"], "format_version": 1}
            manifest = {"format_version": 1, "system_version": __version__, "created_at": now(), "op_id": p["op_id"], "request_hash": request_hash, "files": entries, "result": result}
            temp_zip = Path(temp) / "archive.zip"
            with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as z:
                for relative, path in files.items():
                    z.write(path, relative)
                z.writestr("backup-manifest.json", canonical(manifest))
            # Reopen and check hashes before publishing the archive.
            self._validate_archive(temp_zip)
            staged = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
            shutil.copyfile(temp_zip, staged)
            if target.exists():
                staged.unlink()
                raise ConflictError("备份目标并发创建")
            os.rename(staged, target)
        return result

    @staticmethod
    def _validate_archive(source):
        with zipfile.ZipFile(source) as z:
            names = z.namelist()
            if len(names) != len(set(names)):
                raise ValueError("备份含重复路径")
            for entry in z.infolist():
                path = PurePosixPath(entry.filename)
                if path.is_absolute() or ".." in path.parts or "\\" in entry.filename or ":" in entry.filename or any(part in ("", ".") for part in path.parts):
                    raise ValueError("备份路径不安全")
                if stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError("备份不能包含符号链接")
            manifest = json.loads(z.read("backup-manifest.json"))
            if manifest.get("format_version") != 1 or ".project/registry.sqlite3" not in manifest.get("files", {}):
                raise ValueError("备份清单格式不支持")
            if set(names) != set(manifest["files"]) | {"backup-manifest.json"}:
                raise ValueError("备份文件与清单不符")
            for name, info in manifest["files"].items():
                data = z.read(name)
                if len(data) != info["size"] or digest(data) != info["sha256"]:
                    raise ValueError("备份哈希验证失败: " + name)
            return manifest

    def _backup_restore(self, p, request_hash):
        required(p, "source", "destination")
        source = Path(p["source"]).expanduser().resolve()
        target = Path(p["destination"]).expanduser().resolve()
        if target == self.root or target.is_relative_to(self.root) or self.root.is_relative_to(target):
            raise ValueError("恢复目录必须与当前项目独立")
        marker = target / ".project" / "restore-receipt.json"
        if target.exists():
            if marker.is_file():
                data = json.loads(marker.read_text(encoding="utf-8"))
                if data.get("op_id") == p["op_id"] and data.get("request_hash") == request_hash:
                    return data["result"]
            raise ConflictError("恢复目标必须为不存在的新目录")
        manifest = self._validate_archive(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        # A short generated sibling avoids doubling a long user target name.
        staging = target.parent / (".restore-" + uuid.uuid4().hex[:12])
        staging.mkdir()
        try:
            with zipfile.ZipFile(source) as z:
                for name in manifest["files"]:
                    path = staging / name
                    if not path.resolve().is_relative_to(staging.resolve()):
                        raise ValueError("恢复路径越界")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(z.read(name))
            restored = Registry(staging)
            try:
                if restored.db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("恢复数据库完整性校验失败")
                for artifact in restored.db.execute("SELECT content,sha256 FROM artifacts"):
                    if content_hash(json.loads(artifact[0])) != artifact[1]:
                        raise ValueError("恢复成果哈希校验失败")
                for media in restored._list("media"):
                    path = (staging / media["path"]).resolve()
                    if not path.is_relative_to(staging.resolve()) or not path.is_file():
                        raise ValueError("恢复媒体缺失或越界")
                    with path.open("rb") as stream:
                        if hashlib.file_digest(stream, "sha256").hexdigest() != media["sha256"]:
                            raise ValueError("恢复媒体哈希校验失败")
            finally:
                restored.close()
            result = {"destination": str(target), "source": str(source), "file_count": len(manifest["files"]), "verified": True, "project_id": manifest["result"]["project_id"]}
            (staging / ".project" / "restore-receipt.json").write_text(canonical({"op_id": p["op_id"], "request_hash": request_hash, "result": result}), encoding="utf-8")
            if target.exists():
                raise ConflictError("恢复目标并发创建")
            os.rename(staging, target)
            return result
        except Exception:
            # Explicitly verified generated sibling; no caller-supplied deletion.
            if staging.exists() and staging.parent.resolve() == target.parent.resolve() and staging.name.startswith(".restore-"):
                shutil.rmtree(staging)
            raise

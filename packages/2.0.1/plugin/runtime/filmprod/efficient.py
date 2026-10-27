"""Bounded model-facing views and exact file/checkpoint authoring references.

Legacy registry operations retain their original contracts. These helpers run
inside the registry's existing write transaction; source references are read
only after its idempotency check. No approval or cloud operation is implied.
"""
from copy import deepcopy
import hashlib
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat


WRITE_ACTIONS = {"task.checkpoint_file", "artifact.save_file", "task.submit_checkpoint"}


def _fields(payload, allowed, required_fields=()):
    from .core import required
    required(payload, "expected_project_id", *required_fields)
    extra = set(payload) - set(allowed)
    if extra:
        raise ValueError("不支持的字段: " + ", ".join(sorted(extra)))


def _sha(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(name + " 必须为准确的 SHA-256")
    return value


def _plain(path, directory):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("正文来源含链接或重解析点")
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("正文来源的父路径必须为普通目录")
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("正文来源必须为独立普通文件")
    return info


def _source_path(root, source):
    if not isinstance(source, str) or not source or any(ord(c) < 32 for c in source):
        raise ValueError("source_path 必须为作品目录内的相对文件路径")
    relative = source.replace("\\", "/")
    parts = relative.split("/")
    if (PurePosixPath(relative).is_absolute() or PureWindowsPath(source).drive
            or any(p in ("", ".", "..") or ":" in p or p.casefold() == ".project" for p in parts)):
        raise ValueError("正文来源不得为绝对路径、父目录、数据内部目录或特殊路径")
    root = Path(root).resolve(strict=True)
    _plain(root, True)
    current = root
    for part in parts[:-1]:
        current = current / part
        _plain(current, True)
        if current.resolve(strict=True) != current:
            raise ValueError("正文来源目录身份已变化")
    path = current / parts[-1]
    if path.resolve(strict=True) != path or not path.is_relative_to(root):
        raise ValueError("正文来源超出明确作品目录")
    return path, relative


def _read_source(registry, payload):
    from .core import ConflictError, required
    required(payload, "source_path", "expected_file_sha256")
    expected = _sha(payload["expected_file_sha256"], "expected_file_sha256")
    path, relative = _source_path(registry.root, payload["source_path"])
    before = _plain(path, False)
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if identity(opened) != identity(before) or opened.st_nlink != 1:
            raise ConflictError("正文来源在读取前已变化")
        _source_path(registry.root, payload["source_path"])
        body = stream.read()
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise ConflictError("正文来源在读取中已变化")
    _source_path(registry.root, payload["source_path"])
    if identity(_plain(path, False)) != identity(before):
        raise ConflictError("正文来源在读取后已变化")
    actual = hashlib.sha256(body).hexdigest()
    if actual != expected:
        raise ConflictError("正文来源 SHA-256 与请求不一致，未保存")
    # utf-8 (not utf-8-sig) and bytes decoding preserve BOM and all newlines.
    text = body.decode("utf-8", errors="strict")
    return text, {"path": relative, "sha256": actual, "size_bytes": len(body)}


def _size(content):
    from .core import canonical
    return len((content if isinstance(content, str) else canonical(content)).encode("utf-8"))


def _artifact_summary(artifact):
    from .core import content_category
    keys = ("artifact_id", "version", "kind", "scope", "status", "sha256", "parent_version", "created_at", "deps",
            "approval_status", "approval", "pending_candidate_version", "approved_version", "input_status", "style_context")
    result = {key: deepcopy(artifact[key]) for key in keys if key in artifact}
    result["category"] = artifact.get("category") or content_category(artifact)
    result["size_bytes"] = _size(artifact["content"])
    metadata = artifact.get("metadata", {})
    result["metadata"] = {key: deepcopy(metadata[key]) for key in ("title", "chapter", "episode", "scene", "order", "workflow_stage", "asset_type") if key in metadata}
    if metadata.get("style_reference"):
        result["metadata"]["style_reference"] = _style_reference_summary(metadata["style_reference"])
    return result


def _style_reference_summary(reference):
    result = {key: deepcopy(value) for key, value in reference.items() if key not in {"content", "deps", "previous_reference"}}
    if reference.get("previous_reference"):
        result["previous_reference"] = _style_reference_summary(reference["previous_reference"])
    result["content_included"] = False
    return result


def _checkpoint_summary(checkpoint, *, constraints=False):
    keys = ["checkpoint_id", "saved_at", "draft_sha256", "inputs", "source"]
    if constraints:
        keys += ["completed", "decisions", "unresolved", "next_step"]
    result = {key: deepcopy(checkpoint[key]) for key in keys if key in checkpoint}
    result["size_bytes"] = _size(checkpoint["draft"])
    if checkpoint.get("style_binding"):
        result["style_binding"] = _style_reference_summary(checkpoint["style_binding"])
        result["style_execution_lock"] = deepcopy(checkpoint["style_execution_lock"])
    return result


def _task_summary(task, *, constraints=False):
    keys = ["task_id", "title", "module", "scope", "status", "artifact_id", "inputs", "bound_versions", "created_at", "submitted_at", "output", "execution_lock", "style_context", "missing_context", "review_reason", "thread_id"]
    if constraints:
        keys += ["must_keep", "allowed_changes", "requirements", "cancellation_reason"]
    result = {key: deepcopy(task[key]) for key in keys if key in task}
    for key in ("style_binding", "submitted_style_reference"):
        if task.get(key):
            result[key] = _style_reference_summary(task[key])
    for key in ("style_execution_lock", "submitted_inputs"):
        if key in task:
            result[key] = deepcopy(task[key])
    checkpoints = task.get("checkpoints", [])
    result["checkpoint_count"] = len(checkpoints)
    result["latest_checkpoint"] = _checkpoint_summary(checkpoints[-1]) if checkpoints else None
    return result


def compact_result(action, result):
    """Project legacy results without changing the persisted legacy response."""
    if result.get("compact") is True:
        return deepcopy(result)
    out = {"compact": True, "action": action}
    if action == "task.create":
        out.update(_task_summary(result))
    elif action in ("task.checkpoint", "task.checkpoint_file"):
        out.update(task_id=result["task_id"], status=result["status"], checkpoint=_checkpoint_summary(result["checkpoint"], constraints=True))
    elif action in ("artifact.save", "artifact.save_file", "task.submit", "task.submit_checkpoint"):
        artifact = _artifact_summary(result["artifact"])
        out.update(artifact=artifact, artifact_ref={"artifact_id": artifact["artifact_id"], "version": artifact["version"]},
                   sha256=artifact["sha256"], size_bytes=artifact["size_bytes"],
                   approval_status=result["approval_status"], invalidated=deepcopy(result.get("invalidated", [])))
        if "task" in result:
            out["task"] = _task_summary(result["task"])
        if "cloud_update" in result:
            out["cloud_update"] = deepcopy(result["cloud_update"])
    else:
        raise ValueError("该动作没有紧凑回执定义")
    return out


def checkpoint_file(registry, payload):
    _fields(payload, {"op_id", "expected_project_id", "task_id", "source_path", "expected_file_sha256", "completed", "decisions", "unresolved", "next_step"}, ("task_id",))
    body, source = _read_source(registry, payload)
    expanded = {key: value for key, value in payload.items() if key not in ("source_path", "expected_file_sha256")}
    result = registry._checkpoint(dict(expanded, draft=body))
    # Retain source provenance in the checkpoint without changing user metadata.
    task = registry._get("tasks", "task_id", payload["task_id"])
    task["checkpoints"][-1]["source"] = source
    registry._put("tasks", "task_id", task["task_id"], task)
    result["checkpoint"]["source"] = source
    receipt = compact_result("task.checkpoint_file", result)
    receipt["source"] = source
    return receipt


def save_artifact_file(registry, payload):
    from .core import TEXT_FILE_KINDS
    _fields(payload, {"op_id", "expected_project_id", "artifact_id", "kind", "scope", "base_version", "source_path", "expected_file_sha256", "metadata", "deps", "cloud_update", "use_current_style"}, ("kind",))
    if not isinstance(payload["kind"], str) or payload["kind"] not in TEXT_FILE_KINDS:
        raise ValueError("artifact.save_file 只保存创作文本，不将结构化记录或媒体转为正文")
    body, source = _read_source(registry, payload)
    expanded = {key: value for key, value in payload.items() if key not in ("source_path", "expected_file_sha256")}
    receipt = compact_result("artifact.save_file", registry._save(dict(expanded, content=body)))
    receipt["source"] = source
    return receipt


def submit_checkpoint(registry, payload):
    from .core import ConflictError, content_hash
    _fields(payload, {"op_id", "expected_project_id", "task_id", "checkpoint_id", "expected_draft_sha256", "artifact_id", "kind", "base_version", "metadata", "cloud_update"}, ("task_id", "checkpoint_id", "expected_draft_sha256", "artifact_id", "kind", "base_version"))
    expected = _sha(payload["expected_draft_sha256"], "expected_draft_sha256")
    task = registry._get("tasks", "task_id", payload["task_id"])
    checkpoints = task.get("checkpoints", [])
    if not checkpoints or checkpoints[-1]["checkpoint_id"] != payload["checkpoint_id"]:
        raise ConflictError("必须提交该任务最新的准确检查点；检查点已变化或不属于本任务")
    checkpoint = checkpoints[-1]
    if checkpoint["draft_sha256"] != expected or content_hash(checkpoint["draft"]) != expected:
        raise ConflictError("检查点正文摘要不一致，未提交")
    expanded = {key: value for key, value in payload.items() if key not in ("checkpoint_id", "expected_draft_sha256")}
    receipt = compact_result("task.submit_checkpoint", registry._submit(dict(expanded, content=checkpoint["draft"])))
    receipt["submitted_checkpoint"] = {"checkpoint_id": checkpoint["checkpoint_id"], "draft_sha256": expected}
    if "source" in checkpoint:
        receipt["source"] = deepcopy(checkpoint["source"])
    return receipt


def read_context(registry, payload):
    """Read one consistent bounded view; no cached freshness or schema mutation."""
    from .core import identifier, now
    mode = payload.get("mode", "summary")
    allowed = {"summary": {"expected_project_id", "mode"}, "resume": {"expected_project_id", "mode", "task_id"},
               "artifact": {"expected_project_id", "mode", "artifact_id", "version"}}
    if not isinstance(mode, str) or mode not in allowed:
        raise ValueError("context mode 必须为 summary/resume/artifact")
    _fields(payload, allowed[mode])
    with registry.lock:
        registry.db.execute("BEGIN")
        try:
            registry.check_project_identity(payload["expected_project_id"])
            result = {"read_only": True, "compact": True, "mode": mode, "project_id": payload["expected_project_id"], "project_root": str(registry.root), "observed_at": now()}
            if mode == "summary":
                from .workflow import workflow_view
                from .board_management190 import trash_view
                approved, pending, current = registry._content_views()
                result.update(project=registry._project(), workflow=workflow_view(registry._project(), approved, pending),
                              artifacts=[_artifact_summary(a) for a in registry._latest()],
                              approved_artifacts=[_artifact_summary(a) for a in approved],
                              pending_candidates=[_artifact_summary(a) for a in pending],
                              current_content=[_artifact_summary(a) for a in current],
                              tasks=[_task_summary(t) for t in registry._list("tasks")], trash=trash_view(registry))
                from .board1150 import filter_new_input_suggestions
                filter_new_input_suggestions(registry, result["workflow"])
                result["global_style"] = deepcopy(result["workflow"]["global_style"])
                from .workspace1110 import workspace_view
                from .delivery1110 import delivery_summary
                result["workspace"] = workspace_view(registry)
                result["delivery"] = delivery_summary(registry)
                from .cloud1120 import cloud_summary
                result["cloud"] = cloud_summary(registry)
                from .art1130 import art_summary
                result["art"] = art_summary(registry)
                result["bodies_included"] = False
            elif mode == "resume":
                from .core import required
                required(payload, "task_id")
                identifier(payload["task_id"], "task_id")
                resumed = registry._resume(payload["task_id"])
                result.update(project=resumed["project"], execution_compatibility=resumed["execution_compatibility"],
                              task=_task_summary(resumed["task"], constraints=True),
                              frozen_inputs=[_artifact_summary(a) for a in resumed["frozen_inputs"]],
                              checkpoint=deepcopy(resumed["checkpoint"]), stale_inputs=resumed["stale_inputs"])
                if resumed["task"].get("style_binding"):
                    result["frozen_style_reference"] = deepcopy(resumed["task"]["style_binding"])
            else:
                from .core import required
                required(payload, "artifact_id", "version")
                identifier(payload["artifact_id"], "artifact_id")
                if type(payload["version"]) is not int or payload["version"] < 1:
                    raise ValueError("正文读取必须指定准确正整数版本")
                artifact = registry._artifact(payload["artifact_id"], payload["version"])
                if not artifact:
                    raise ValueError("成果版本不存在")
                pointer = registry._approved_pointer(artifact)
                result.update(artifact=artifact, approval=pointer,
                              is_current_approved=bool(pointer and pointer["artifact_id"] == artifact["artifact_id"] and pointer["version"] == artifact["version"]))
            registry.db.execute("COMMIT")
            return result
        except Exception:
            registry.db.execute("ROLLBACK")
            raise

"""Exact text export and verified, non-overwriting local Markdown copies.

The registry is read-only for both actions. Only save_document writes derived
files, within a fixed project subdirectory; it never approves or revises text.
"""
import base64
import hashlib
import os
import re
import stat
import uuid
from pathlib import Path

NON_TEXT_DOCUMENT_KINDS = {"planning_record", "pages_observation", "cloud_observation", "render"}
EXPORT_PARTS = ("11-导出", "Markdown")


def export_document(registry, payload):
    from .core import required, identifier
    required(payload, "expected_project_id", "artifact_id", "version")
    registry.check_project_identity(payload["expected_project_id"])
    identifier(payload["artifact_id"], "artifact_id")
    if type(payload["version"]) is not int or payload["version"] < 1:
        raise ValueError("document.export version 必须为精确正整数")
    artifact = registry._artifact(payload["artifact_id"], payload["version"])
    if not artifact:
        raise ValueError("成果版本不存在")
    if artifact["kind"] in NON_TEXT_DOCUMENT_KINDS or not isinstance(artifact["content"], str):
        raise ValueError("仅能导出准确的字符串正文；结构化记录、诊断和对象不能转换成 Markdown 正文")
    body = artifact["content"].encode("utf-8")
    sha = hashlib.sha256(body).hexdigest()
    if sha != artifact["sha256"]:
        raise ValueError("正文摘要与登记不符；不能导出未经核验的版本")
    safe_id = re.sub(r"[^\w.-]", "_", artifact["artifact_id"])[:80]
    filename = f"{safe_id}_{hashlib.sha256(artifact['artifact_id'].encode('utf-8')).hexdigest()[:8]}_v{artifact['version']:03d}.md"
    return {"read_only": True, "artifact_ref": {"artifact_id": artifact["artifact_id"], "version": artifact["version"]},
            "kind": artifact["kind"], "status": artifact["status"], "content": artifact["content"],
            "filename": filename, "mime": "text/markdown; charset=utf-8", "encoding": "utf-8",
            "data_base64": base64.b64encode(body).decode("ascii"), "sha256": sha, "size_bytes": len(body)}


def _plain_path(path, *, directory):
    """Reject links/reparse points before using either directories or files."""
    info = path.lstat()
    reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if stat.S_ISLNK(info.st_mode) or reparse:
        raise ValueError("导出路径含符号链接或重解析点，未写入: " + str(path))
    if directory and not stat.S_ISDIR(info.st_mode):
        raise ValueError("导出目录位置已有其他文件: " + str(path))
    if not directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
        raise ValueError("导出文件必须是独立普通文件，不能是链接或目录: " + str(path))
    return info


def _export_directory(root, *, create=False):
    root = Path(root).resolve(strict=True)
    _plain_path(root, directory=True)
    current = root
    for part in EXPORT_PARTS:
        current = current / part
        if create:
            try:
                current.mkdir()
            except FileExistsError:
                pass
        _plain_path(current, directory=True)
        if current.resolve(strict=True) != current or not current.is_relative_to(root):
            raise ValueError("导出目录超出明确作品目录，未继续")
    return current


def _verified_file(path, root, expected_sha, expected_size):
    from .core import ConflictError
    _export_directory(root)
    before = _plain_path(path, directory=False)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        actual = os.fstat(stream.fileno())
        signature = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if signature(actual) != signature(before) or actual.st_nlink != 1:
            raise ConflictError("导出文件在核对期间已变化，未确认保存")
        _export_directory(root)
        _plain_path(path, directory=False)
        digest = hashlib.sha256()
        size = 0
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
        if signature(os.fstat(stream.fileno())) != signature(actual):
            raise ConflictError("导出文件在读回期间被修改，未确认保存")
    after = _plain_path(path, directory=False)
    _export_directory(root)
    if signature(after) != signature(before):
        raise ConflictError("导出文件在核对期间被替换，未确认保存")
    if size != expected_size or digest.hexdigest() != expected_sha:
        raise ConflictError("同名导出文件内容不一致，已保留原文件；请核对后另行处理")


def _publish_no_replace(temporary, target):
    # Re-check at the publication boundary as well as before creating/writing.
    # These checks are not an OS sandbox against a hostile same-user process.
    if _export_directory(target.parents[2]) != target.parent or temporary.parent != target.parent:
        raise ValueError("导出发布位置不一致，未继续")
    _plain_path(temporary, directory=False)
    # Windows rename refuses an existing target. POSIX rename would replace it,
    # so use an atomic hard-link publication there instead. No overwrite fallback.
    if os.name == "nt":
        os.rename(temporary, target)
    else:
        os.link(temporary, target, follow_symlinks=False)
        temporary.unlink()


def save_document(registry, payload):
    from .core import ConflictError, identifier, required
    required(payload, "op_id", "expected_sha256")
    identifier(payload["op_id"], "op_id")
    if not isinstance(payload["expected_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", payload["expected_sha256"]):
        raise ValueError("expected_sha256 必须为准确正文的 SHA-256")
    allowed = {"op_id", "expected_project_id", "artifact_id", "version", "expected_sha256"}
    if set(payload) - allowed:
        raise ValueError("document.save 只允许准确正文引用；不能指定目标目录、文件名或其他字段")
    exported = export_document(registry, payload)
    if exported["sha256"] != payload["expected_sha256"]:
        raise ConflictError("正文摘要与导出请求不符，未写入文件")
    body = exported["content"].encode("utf-8")
    root = registry.root.resolve(strict=True)
    directory = _export_directory(root, create=True)
    filename = exported["filename"][:-3] + "_" + exported["sha256"][:16] + ".md"
    target = directory / filename
    created = False
    try:
        _verified_file(target, root, exported["sha256"], len(body))
    except FileNotFoundError:
        # Only our own unpredictable temporary file may be removed on failure.
        temporary = directory / (".film-export-" + uuid.uuid4().hex + ".tmp")
        temporary_identity = None
        try:
            _export_directory(root)
            with temporary.open("xb") as stream:
                info = os.fstat(stream.fileno())
                temporary_identity = (info.st_dev, info.st_ino)
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            _verified_file(temporary, root, exported["sha256"], len(body))
            _export_directory(root)
            try:
                _publish_no_replace(temporary, target)
                created = True
            except FileExistsError:
                # A competing exact export may have won. It must pass readback.
                pass
        finally:
            if temporary_identity is not None:
                try:
                    _export_directory(root)
                    info = temporary.lstat()
                    if (info.st_dev, info.st_ino) == temporary_identity and not stat.S_ISLNK(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & 0x400):
                        temporary.unlink()
                except FileNotFoundError:
                    pass
        _verified_file(target, root, exported["sha256"], len(body))
    return {"saved_verified": True, "readback_verified": True, "status": "created" if created else "reused",
            "op_id": payload["op_id"], "project_id": payload["expected_project_id"], "project_root": str(root),
            "export_dir": str(directory), "local_path": str(target), "filename": filename,
            "artifact_ref": exported["artifact_ref"], "sha256": exported["sha256"], "size_bytes": len(body),
            "mime": exported["mime"], "encoding": "utf-8", "artifact_status": exported["status"],
            "registry_changed": False}


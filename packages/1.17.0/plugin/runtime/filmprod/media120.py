"""Local media import, bounded in-client previews and verified original paths."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import mimetypes
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from .core import ConflictError, canonical, content_hash, identifier, required
from .render import _exe, _job_lock, probe

INLINE_LIMIT = 12 * 1024 * 1024
THUMBNAIL_LIMIT = 1024 * 1024


def choose_video():
    """A native file picker is only invoked by an explicit user's import action."""
    import tkinter
    from tkinter import filedialog
    window = tkinter.Tk()
    window.withdraw()
    window.attributes("-topmost", True)
    try:
        path = filedialog.askopenfilename(parent=window, title="选择已制作好的本机视频（原件保存到当前项目）",
            filetypes=[("视频", "*.mp4 *.mov *.mkv *.webm *.avi *.m4v"), ("所有文件", "*.*")])
        return {"path": str(Path(path).resolve()) if path else None, "cancelled": not bool(path), "cloud_upload": False}
    finally:
        window.destroy()


def _digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _under_root(registry, relative):
    from .documents import _plain_path
    relative = Path(relative)
    if relative.is_absolute() or relative.drive or '..' in relative.parts:
        raise ValueError("媒体登记必须使用项目内相对路径")
    # Validate existing components before resolving them; resolving first would
    # erase an in-project link or permit reads from an unrelated linked cache.
    current = registry.root
    _plain_path(current, directory=True)
    for part in relative.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            _plain_path(current, directory=current.is_dir())
    if not current.resolve().is_relative_to(registry.root):
        raise ValueError("媒体路径越出当前项目目录")
    return current


def verified_original(registry, payload):
    """Resolve a registry ID only; never accept a caller-selected original path."""
    if set(payload) - {"media_id", "expected_project_id", "thumbnail_only"}:
        raise ValueError("原件核对仅接受已登记 media_id，不接受任意路径")
    required(payload, "media_id")
    identifier(payload["media_id"], "media_id")
    registry.check_project_identity(payload.get("expected_project_id"))
    media = registry._get("media", "media_id", payload["media_id"])
    if media["kind"] not in ("image", "video", "audio"):
        raise ValueError("原件核对仅支持已登记图片、视频和音频")
    source = _under_root(registry, media["path"])
    if not source.is_file() or _digest(source) != media["sha256"]:
        raise ConflictError("本机原件不存在或 SHA-256 与登记记录不符")
    return {"media_id": media["media_id"], "kind": media["kind"], "sha256": media["sha256"],
            "local_path": str(source), "project_id": registry._project()["project_id"],
            "hash_verified": True, "original_transmitted": False, "cloud_upload": False, "read_only": True}


def _thumbnail(registry, media):
    source = _under_root(registry, media["path"])
    if not source.is_file() or _digest(source) != media["sha256"]:
        raise ConflictError("本机原视频不存在或哈希已变化")
    target = _under_root(registry, ".project/previews/" + media["sha256"] + ".jpg")
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(".thumb-" + uuid.uuid4().hex + ".jpg")
        try:
            process = subprocess.run([_exe("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(source),
                "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "3", "-y", str(temporary)], capture_output=True, timeout=45)
            if process.returncode or not temporary.is_file():
                raise ValueError("视频缩略图生成失败")
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
    return target


def _preview_clip(registry, media):
    """Create a short, low resolution derivative, never transmit the original."""
    source = _under_root(registry, media["path"])
    target = _under_root(registry, ".project/previews/" + media["sha256"] + ".preview.mp4")
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(".preview-" + uuid.uuid4().hex + ".mp4")
        try:
            process = subprocess.run([_exe("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(source),
                "-t", "12", "-map", "0:v:0", "-map", "0:a:0?", "-vf", "scale=480:-2", "-c:v", "libx264", "-preset", "fast",
                "-crf", "30", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", "-y", str(temporary)], capture_output=True, timeout=90)
            if process.returncode or not temporary.is_file():
                raise ValueError("低清预览生成失败；原视频已本机保存，可直接打开")
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
    return target


def import_video(registry, payload):
    required(payload, "op_id", "media_id", "path", "kind")
    identifier(payload["op_id"], "op_id")
    identifier(payload["media_id"], "media_id")
    if payload.get("expected_project_id") is not None and registry._project()["project_id"] != payload["expected_project_id"]:
        raise ConflictError("视频导入项目身份与打开表单时不同，已拒绝写入")
    locks = registry.internal / "media-import-locks"
    locks.mkdir(exist_ok=True)
    with _job_lock(locks / (content_hash(payload["op_id"]) + ".lock")):
        return _import_video(registry, payload)


def _import_video(registry, payload):
    p = dict(payload)
    required(p, "op_id", "path", "media_id", "kind")
    if p["kind"] not in ("take", "clip", "final"):
        raise ValueError("视频分类必须为 take、clip 或 final")
    if not isinstance(p.get("metadata", {}), dict):
        raise ValueError("metadata 必须为对象")
    request_hash = content_hash(p)
    registry.db.execute("CREATE TABLE IF NOT EXISTS media_import_jobs(op_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, request TEXT NOT NULL, prepared TEXT, result TEXT, frozen TEXT)")
    if "frozen" not in {row["name"] for row in registry.db.execute("PRAGMA table_info(media_import_jobs)")}:
        registry.db.execute("ALTER TABLE media_import_jobs ADD COLUMN frozen TEXT")
    registry.db.execute("INSERT OR IGNORE INTO media_import_jobs(op_id,request_hash,request,prepared,result) VALUES(?,?,?,NULL,NULL)", (p["op_id"], request_hash, canonical(p)))
    row = registry.db.execute("SELECT * FROM media_import_jobs WHERE op_id=?", (p["op_id"],)).fetchone()
    if row["request_hash"] != request_hash:
        raise ConflictError("视频导入 op_id 已用于不同参数或源文件")
    if row["result"]:
        saved = json.loads(row["result"])
        original = verified_original(registry, {"media_id": p["media_id"], "expected_project_id": registry._project()["project_id"]})
        return {**saved, "local_path": original["local_path"]}
    if row["prepared"]:
        prepared = json.loads(row["prepared"])
        committed = registry.db.execute("SELECT 1 FROM operations WHERE op_id=?", (p["op_id"],)).fetchone()
        if not committed:
            # A moved/restored project carries its own staged bytes. Never follow
            # the previous root or change the payload of a committed operation.
            staged = _under_root(registry, ".project/import-staging/" + content_hash(p["op_id"]) + Path(prepared["path"]).suffix.lower())
            if not staged.is_file() or _digest(staged) != prepared["metadata"]["probe_source_sha256"]:
                raise ConflictError("未提交导入的暂存原件缺失或校验不符；保留原请求等待核查")
            if Path(prepared["path"]).resolve() != staged.resolve():
                prepared = {**prepared, "path": str(staged)}
                registry.db.execute("UPDATE media_import_jobs SET prepared=? WHERE op_id=?", (canonical(prepared), p["op_id"]))
    else:
        if row["frozen"]:
            frozen = json.loads(row["frozen"])
        else:
            source = Path(p["path"]).expanduser()
            if not source.is_absolute() or not source.is_file():
                raise ValueError("请选择存在的本机视频绝对路径")
            frozen = {"source_path": str(source.resolve()), "sha256": _digest(source), "suffix": source.suffix.lower()}
            registry.db.execute("UPDATE media_import_jobs SET frozen=? WHERE op_id=?", (canonical(frozen), p["op_id"]))
        source = Path(frozen["source_path"])
        source_sha = frozen["sha256"]
        staging = _under_root(registry, ".project/import-staging/" + content_hash(p["op_id"]) + frozen["suffix"])
        staging.parent.mkdir(parents=True, exist_ok=True)
        if not staging.is_file():
            if not source.is_file() or _digest(source) != source_sha:
                raise ConflictError("源视频与原操作冻结的字节不同；保留原操作等待核查")
            temporary = staging.with_name(".video-" + uuid.uuid4().hex + ".tmp")
            try:
                shutil.copyfile(source, temporary)
                if _digest(temporary) != source_sha or _digest(source) != source_sha:
                    raise ConflictError("复制期间源视频变化，请重新选择")
                os.replace(temporary, staging)
            finally:
                if temporary.exists():
                    temporary.unlink()
        if _digest(staging) != source_sha:
            raise ConflictError("视频暂存原件与冻结摘要不符；保留原操作等待核查")
        info = probe(staging)
        stream = next((item for item in info.get("streams", []) if item.get("codec_type") == "video"), None)
        if not stream:
            raise ValueError("文件不包含视频流")
        duration = info.get("format", {}).get("duration") or stream.get("duration")
        duration = float(duration) if duration is not None else None
        if duration is not None and (not math.isfinite(duration) or duration < 0):
            duration = None
        if _digest(staging) != source_sha:
            raise ConflictError("技术读取期间源视频变化，请重新选择")
        metadata = {**p.get("metadata", {}), "video_category": p["kind"], "duration_seconds": duration,
                    "width": stream.get("width"), "height": stream.get("height"), "codec": stream.get("codec_name"),
                    "probe_source_sha256": source_sha, "original_source_path": str(source.resolve()),
                    "original_storage": "local_project", "cloud_upload": False}
        metadata.setdefault("title", source.stem)
        prepared = {"op_id": p["op_id"], "media_id": p["media_id"], "kind": "video", "path": str(staging), "metadata": metadata}
        if p.get("expected_project_id") is not None:
            prepared["expected_project_id"] = p["expected_project_id"]
        registry.db.execute("UPDATE media_import_jobs SET prepared=? WHERE op_id=?", (canonical(prepared), p["op_id"]))
    existing = next((item for item in registry._list("media") if item["kind"] == "video" and item["sha256"] == prepared["metadata"]["probe_source_sha256"]), None)
    _under_root(registry, existing["path"] if existing else "05-片段/视频原件/" + prepared["metadata"]["probe_source_sha256"] + Path(prepared["path"]).suffix.lower())
    media = registry.dispatch("media.register", prepared)
    warning = None
    if media["sha256"] != prepared["metadata"]["probe_source_sha256"]:
        warning = "复制前源文件发生变化，已保存原件但技术信息需重新检查"
    try:
        thumbnail = str(_thumbnail(registry, media).relative_to(registry.root))
        _preview_clip(registry, media)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        thumbnail = None
        warning = str(exc) if warning is None else warning + "；" + str(exc)
    original = verified_original(registry, {"media_id": p["media_id"], "expected_project_id": registry._project()["project_id"]})
    result = {**media, "thumbnail_path": thumbnail, "warning": warning, "local_path": original["local_path"], "cloud_upload": False}
    registry.db.execute("UPDATE media_import_jobs SET result=? WHERE op_id=?", (canonical(result), p["op_id"]))
    staged = _under_root(registry, ".project/import-staging/" + content_hash(p["op_id"]) + Path(prepared["path"]).suffix.lower())
    if staged.is_file() and _digest(staged) == prepared["metadata"]["probe_source_sha256"]:
        staged.unlink()
    return result


def preview_video(registry, payload):
    if set(payload) - {"media_id", "expected_project_id", "thumbnail_only"}:
        raise ValueError("视频预览只接受已登记的媒体身份")
    required(payload, "media_id")
    media = registry._get("media", "media_id", payload["media_id"])
    if media["kind"] != "video":
        raise ValueError("该媒体不是视频")
    source = _under_root(registry, media["path"])
    if not source.is_file() or _digest(source) != media["sha256"]:
        raise ConflictError("本机原视频不存在或哈希已变化")
    thumb = _under_root(registry, ".project/previews/" + media["sha256"] + ".jpg")
    thumbnail_data = "data:image/jpeg;base64," + base64.b64encode(thumb.read_bytes()).decode("ascii") if thumb.is_file() and thumb.stat().st_size <= THUMBNAIL_LIMIT else None
    # Only generated derivatives travel through UI-only _meta, never the original.
    derivative = _under_root(registry, ".project/previews/" + media["sha256"] + ".preview.mp4")
    inline = derivative.is_file() and derivative.stat().st_size <= INLINE_LIMIT
    preview = "data:video/mp4;base64," + base64.b64encode(derivative.read_bytes()).decode("ascii") if inline and not payload.get("thumbnail_only") else None
    return {"media_id": media["media_id"], "title": media.get("metadata", {}).get("title", source.stem),
            "kind": "video", "sha256": media["sha256"], "source_sha256": media["sha256"],
            "project_id": registry._project()["project_id"],
            "local_path": str(source), "duration_seconds": media["metadata"].get("duration_seconds"),
            "thumbnail_data_uri": thumbnail_data, "preview_data_uri": preview, "preview_inline_available": inline,
            "preview_kind": "low_resolution_first_12_seconds", "original_transmitted": False,
            "reason": None if inline else "暂无内嵌低清预览，请通过宿主打开本机文件",
            "cloud_upload": False, "read_only": True}


def _import_with_outcome(registry, payload, operation):
    """Report a known pre-commit failure without guessing from exception type."""
    try:
        return operation(registry, payload)
    except Exception as exc:
        if getattr(exc, "operation_outcome", None) not in {"no_write", "failed_before_commit", "unknown", "resumable"}:
            try:
                op_id = payload.get("op_id")
                committed = registry.db.execute("SELECT 1 FROM operations WHERE op_id=?", (op_id,)).fetchone() if isinstance(op_id, str) else None
                exc.operation_outcome = "unknown" if committed else "failed_before_commit"
            except Exception:
                exc.operation_outcome = "unknown"
        raise


def media_action(registry, action, payload):
    if not isinstance(payload, dict):
        raise ValueError("payload 必须为对象")
    registry.check_project_identity(payload.get("expected_project_id"))
    if action in ("choose_audio", "import_audio", "preview_audio"):
        from .audio1150 import choose_audio, import_audio, preview_audio
        if action == "choose_audio":
            return choose_audio()
        return _import_with_outcome(registry, payload, import_audio) if action == "import_audio" else preview_audio(registry, payload)
    if action == "original":
        if set(payload) - {"media_id", "expected_project_id"}:
            raise ValueError("原件核对仅接受 media_id 和 expected_project_id")
        return verified_original(registry, payload)
    if action in ("choose_image", "import_image", "preview_image"):
        from .image_preview180 import choose_image, import_image, preview_image
        if action == "choose_image":
            return choose_image()
        if action == "import_image":
            return _import_with_outcome(registry, payload, import_image)
        return preview_image(registry, payload)
    if action == "choose":
        return choose_video()
    if action == "import":
        return _import_with_outcome(registry, payload, import_video)
    if action == "preview":
        return preview_video(registry, payload)
    raise ValueError("不支持的媒体操作")

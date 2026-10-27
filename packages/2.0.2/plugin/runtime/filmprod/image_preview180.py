"""Bounded local still-image import and disposable previews, without image models.

Registry originals are immutable. Preview reads may write only .project/previews;
they never register assets, migrate a database, or modify source image bytes.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import struct
import subprocess
import uuid
from pathlib import Path

from .assets import validate_asset_type
from .core import ConflictError, canonical, content_hash, identifier, required
from .media120 import _digest, _under_root, verified_original
from .render import _exe, _job_lock

MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_SIDE = 16384
MAX_IMAGE_PIXELS = 40_000_000
THUMBNAIL_BYTES = 1024 * 1024
PREVIEW_BYTES = 4 * 1024 * 1024
PREVIEW_VERSION = "image-png-v1"
IMAGE_SUFFIXES = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}


def choose_image():
    import tkinter
    from tkinter import filedialog
    window = tkinter.Tk()
    window.withdraw()
    window.attributes("-topmost", True)
    try:
        path = filedialog.askopenfilename(parent=window, title="选择本机图片（原件保存到当前项目）",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.webp")])
        return {"path": str(Path(path).resolve()) if path else None, "cancelled": not bool(path), "cloud_upload": False}
    finally:
        window.destroy()


def _dimensions(data):
    """Read declared dimensions before letting a decoder allocate image buffers."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 33 and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        offset, ended = 8, False
        while offset + 12 <= len(data):
            size = int.from_bytes(data[offset:offset + 4], "big")
            kind = data[offset + 4:offset + 8]
            if offset + size + 12 > len(data):
                raise ValueError("PNG 数据不完整")
            if kind == b"acTL":
                raise ValueError("此入口仅支持静态图片，不支持动态 PNG")
            offset += size + 12
            if kind == b"IEND":
                ended = True
                break
        if not ended:
            raise ValueError("PNG 缺少结束块")
        return "png", width, height
    if data.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 3 < len(data):
            if data[offset] != 255:
                raise ValueError("JPEG 标记无效")
            while offset < len(data) and data[offset] == 255:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker in (0xD9, 0xDA):
                break
            if marker in range(0xD0, 0xD8) or marker == 0x01:
                continue
            size = int.from_bytes(data[offset:offset + 2], "big")
            if size < 2 or offset + size > len(data):
                raise ValueError("JPEG 数据不完整")
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                if size < 8 or not data.endswith(b"\xff\xd9"):
                    raise ValueError("JPEG 数据不完整")
                height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
                return "jpeg", width, height
            offset += size
    if len(data) >= 30 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        if int.from_bytes(data[4:8], "little") + 8 != len(data):
            raise ValueError("WebP 数据长度不符")
        kind = data[12:16]
        if kind == b"VP8X":
            if data[20] & 2:
                raise ValueError("此入口仅支持静态图片，不支持动态 WebP")
            return "webp", 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
        if kind == b"VP8L" and data[20] == 0x2F:
            bits = int.from_bytes(data[21:25], "little")
            return "webp", (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if kind == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
            return "webp", int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(data[28:30], "little") & 0x3FFF
    raise ValueError("内容不是受支持的静态 PNG、JPEG 或 WebP")


def _bounded_header(path):
    path = Path(path)
    if not 0 < path.stat().st_size <= MAX_IMAGE_BYTES:
        raise ValueError("图片为空或超过 64 MiB 上限")
    with path.open("rb") as stream:
        data = stream.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("图片超过 64 MiB 上限")
    kind, width, height = _dimensions(data)
    if min(width, height) < 1 or max(width, height) > MAX_IMAGE_SIDE or width * height > MAX_IMAGE_PIXELS:
        raise ValueError("图片尺寸超过单边 16384 或 4000 万像素上限")
    if IMAGE_SUFFIXES.get(path.suffix.lower()) != kind:
        raise ValueError("图片扩展名与实际内容类型不符")
    return {"image_format": kind, "width": width, "height": height}


def validate_image(path):
    info = _bounded_header(path)
    process = subprocess.run([_exe("ffprobe"), "-v", "error", "-protocol_whitelist", "file,pipe", "-show_streams", "-of", "json", str(path)],
                             capture_output=True, timeout=20)
    if process.returncode:
        raise ValueError("图片技术读取失败")
    try:
        streams = json.loads(process.stdout).get("streams", [])
        stream = streams[0]
    except (ValueError, IndexError, TypeError) as exc:
        raise ValueError("图片技术读取失败") from exc
    if len(streams) != 1 or stream.get("codec_type") != "video" or stream.get("codec_name") != {"png": "png", "jpeg": "mjpeg", "webp": "webp"}[info["image_format"]]:
        raise ValueError("图片内容或编码类型不符")
    if (stream.get("width"), stream.get("height")) != (info["width"], info["height"]):
        raise ValueError("图片尺寸声明与解码信息不一致")
    # Decode the complete still frame: a plausible header is not a valid image.
    decoded = subprocess.run([_exe("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-xerror",
        "-protocol_whitelist", "file,pipe", "-i", str(path), "-frames:v", "1", "-f", "null", "-"], capture_output=True, timeout=30)
    if decoded.returncode or decoded.stderr.strip():
        raise ValueError("图片损坏或无法完整解码")
    return {**info, "codec": stream["codec_name"]}


def _cache_path(registry, relative):
    path = _under_root(registry, relative)
    boundary = registry.root / ".project" / "previews"
    if not path.is_relative_to(boundary):
        raise ValueError("预览缓存路径越界")
    return path


def _cache_valid(target, manifest, media, edge, limit):
    try:
        record = json.loads(manifest.read_text(encoding="utf-8"))
        if record.get("source_sha256") != media["sha256"] or record.get("version") != PREVIEW_VERSION or record.get("edge") != edge:
            return False
        if not 0 < target.stat().st_size <= limit or _digest(target) != record.get("sha256"):
            return False
        info = _bounded_header(target)
        return max(info["width"], info["height"]) <= edge and info["width"] == record.get("width") and info["height"] == record.get("height")
    except (OSError, ValueError, TypeError):
        return False


def _image_derivative(registry, media, source, edge, limit):
    key = media["sha256"] + "." + content_hash({"version": PREVIEW_VERSION, "edge": edge})[:16]
    target = _cache_path(registry, ".project/previews/images/" + key + ".png")
    manifest = _cache_path(registry, ".project/previews/images/" + key + ".json")
    lock = _cache_path(registry, ".project/previews/image-locks/" + key + ".lock")
    target.parent.mkdir(parents=True, exist_ok=True)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with _job_lock(lock):
        if _cache_valid(target, manifest, media, edge, limit):
            return target
        _bounded_header(source)
        temporary = target.with_name(key + "." + uuid.uuid4().hex + ".png")
        temporary_manifest = manifest.with_name(key + "." + uuid.uuid4().hex + ".json")
        try:
            process = subprocess.run([_exe("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-xerror",
                "-protocol_whitelist", "file,pipe", "-i", str(source), "-frames:v", "1", "-vf",
                f"scale=w=min({edge}\\,iw):h=min({edge}\\,ih):force_original_aspect_ratio=decrease",
                "-c:v", "png", "-threads", "1", "-y", str(temporary)], capture_output=True, timeout=45)
            if process.returncode or not temporary.is_file() or process.stderr.strip():
                raise ValueError("图片低清预览生成失败；原件保存状态见导入回执")
            info = _bounded_header(temporary)
            if max(info["width"], info["height"]) > edge or temporary.stat().st_size > limit:
                raise ValueError("图片派生预览超过尺寸或字节上限")
            if _digest(source) != media["sha256"]:
                raise ConflictError("生成预览期间原件发生变化")
            record = {"source_sha256": media["sha256"], "version": PREVIEW_VERSION, "edge": edge,
                      "sha256": _digest(temporary), "width": info["width"], "height": info["height"]}
            temporary_manifest.write_text(canonical(record), encoding="utf-8")
            os.replace(temporary, target)
            os.replace(temporary_manifest, manifest)
        finally:
            temporary.unlink(missing_ok=True)
            temporary_manifest.unlink(missing_ok=True)
    return target


def preview_image(registry, payload):
    if set(payload) - {"media_id", "thumbnail_only", "expected_project_id"}:
        raise ValueError("图片预览仅接受已登记 media_id，不接受路径")
    if "thumbnail_only" in payload and type(payload["thumbnail_only"]) is not bool:
        raise ValueError("thumbnail_only 必须为布尔值")
    original = verified_original(registry, payload)
    if original["kind"] != "image":
        raise ValueError("该媒体不是图片")
    media = registry._get("media", "media_id", payload["media_id"])
    source = Path(original["local_path"])
    _bounded_header(source)
    thumbnail = _image_derivative(registry, media, source, 480, THUMBNAIL_BYTES)
    preview = None if payload.get("thumbnail_only") else _image_derivative(registry, media, source, 960, PREVIEW_BYTES)
    # Bound bytes again at the read boundary, not only when the cache was created.
    def data_uri(path, limit):
        if path is None:
            return None
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("预览缓存超过传输上限")
        manifest = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        if hashlib.sha256(data).hexdigest() != manifest["sha256"]:
            raise ConflictError("读取期间预览缓存发生变化")
        return "data:image/png;base64," + base64.b64encode(data).decode("ascii")
    thumb_data = data_uri(thumbnail, THUMBNAIL_BYTES)
    preview_data = data_uri(preview, PREVIEW_BYTES)
    verified_original(registry, payload)
    return {**original, "title": media.get("metadata", {}).get("title", source.stem),
            "thumbnail_data_uri": thumb_data, "preview_data_uri": preview_data,
            "preview_inline_available": True, "preview_kind": "low_resolution_image", "source_sha256": media["sha256"],
            "thumbnail_max_edge": 480, "preview_max_edge": 960, "cache_version": PREVIEW_VERSION,
            "original_transmitted": False, "cloud_upload": False, "read_only": False,
            "cache_only": True, "write_scope": "preview_cache", "reason": None}


def import_image(registry, payload):
    required(payload, "op_id", "media_id", "path", "expected_project_id")
    identifier(payload["op_id"], "op_id")
    identifier(payload["media_id"], "media_id")
    registry.check_project_identity(payload["expected_project_id"])
    if payload.get("kind", "image") != "image":
        raise ValueError("图片导入 kind 必须为 image")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("metadata 必须为对象")
    if "asset_type" in metadata:
        validate_asset_type(metadata["asset_type"])
    if "title" in metadata and (not isinstance(metadata["title"], str) or not metadata["title"].strip() or len(metadata["title"]) > 500 or any(ord(char) < 32 or ord(char) == 127 for char in metadata["title"])):
        raise ValueError("图片名称必须为 1 到 500 字符的非空文字，且不含控制字符")
    locks = _under_root(registry, ".project/media-import-locks")
    locks.mkdir(exist_ok=True)
    with _job_lock(locks / (content_hash(payload["op_id"]) + ".lock")):
        try:
            return _import_image(registry, dict(payload))
        except Exception as exc:
            committed = registry.db.execute("SELECT 1 FROM operations WHERE op_id=?", (payload["op_id"],)).fetchone()
            exc.operation_outcome = "unknown" if committed else "failed_before_commit"
            raise


def _import_image(registry, p):
    registry.db.execute("CREATE TABLE IF NOT EXISTS image_import_jobs(op_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, request TEXT NOT NULL, frozen TEXT, prepared TEXT, result TEXT)")
    request_hash = content_hash(p)
    registry.db.execute("INSERT OR IGNORE INTO image_import_jobs VALUES(?,?,?,NULL,NULL,NULL)", (p["op_id"], request_hash, canonical(p)))
    row = registry.db.execute("SELECT * FROM image_import_jobs WHERE op_id=?", (p["op_id"],)).fetchone()
    if row["request_hash"] != request_hash:
        raise ConflictError("图片导入 op_id 已用于不同参数；保留原请求核查")
    if row["result"]:
        saved = json.loads(row["result"])
        original = verified_original(registry, {"media_id": p["media_id"], "expected_project_id": p["expected_project_id"]})
        return {**saved, "local_path": original["local_path"]}
    if row["frozen"]:
        frozen = json.loads(row["frozen"])
    else:
        source = Path(p["path"]).expanduser()
        if not source.is_absolute() or not source.is_file() or source.suffix.lower() not in IMAGE_SUFFIXES:
            raise ValueError("请选择存在的 PNG、JPEG 或 WebP 本机绝对路径")
        if not 0 < source.stat().st_size <= MAX_IMAGE_BYTES:
            raise ValueError("图片为空或超过 64 MiB 上限")
        frozen = {"source_path": str(source.resolve()), "sha256": _digest(source), "suffix": source.suffix.lower()}
        # Save the byte identity before copy/decode. A failed retry must never adopt
        # new bytes from the same path with the same operation ID.
        registry.db.execute("UPDATE image_import_jobs SET frozen=? WHERE op_id=?", (canonical(frozen), p["op_id"]))
    staging = _under_root(registry, ".project/import-staging/" + content_hash(p["op_id"]) + frozen["suffix"])
    if row["prepared"]:
        prepared = json.loads(row["prepared"])
        if not registry.db.execute("SELECT 1 FROM operations WHERE op_id=?", (p["op_id"],)).fetchone():
            if not staging.is_file() or _digest(staging) != frozen["sha256"]:
                raise ConflictError("未提交图片的暂存原件缺失或摘要不符；保留原请求核查")
            if Path(prepared["path"]).resolve() != staging:
                prepared = {**prepared, "path": str(staging)}
                registry.db.execute("UPDATE image_import_jobs SET prepared=? WHERE op_id=?", (canonical(prepared), p["op_id"]))
    else:
        if not staging.is_file():
            source = Path(frozen["source_path"])
            if not source.is_file() or _digest(source) != frozen["sha256"]:
                raise ConflictError("源图片与此操作冻结的字节不同；不得用原 op_id 导入另一原件")
            staging.parent.mkdir(parents=True, exist_ok=True)
            temporary = staging.with_name(staging.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                shutil.copyfile(source, temporary)
                if _digest(temporary) != frozen["sha256"] or _digest(source) != frozen["sha256"]:
                    raise ConflictError("复制期间源图片发生变化，原操作保留待核")
                os.replace(temporary, staging)
            finally:
                temporary.unlink(missing_ok=True)
        if _digest(staging) != frozen["sha256"]:
            raise ConflictError("图片暂存摘要不符；保留原请求核查")
        info = validate_image(staging)
        if _digest(staging) != frozen["sha256"]:
            raise ConflictError("技术读取期间暂存图片发生变化")
        metadata = {**p.get("metadata", {}), **info, "probe_source_sha256": frozen["sha256"],
                    "original_source_path": frozen["source_path"], "original_storage": "local_project", "cloud_upload": False}
        metadata.setdefault("title", Path(frozen["source_path"]).stem)
        metadata["title"] = metadata["title"].strip()
        metadata.setdefault("asset_type", "unclassified")
        prepared = {"op_id": p["op_id"], "media_id": p["media_id"], "kind": "image", "path": str(staging),
                    "metadata": metadata, "expected_project_id": p["expected_project_id"]}
        registry.db.execute("UPDATE image_import_jobs SET prepared=? WHERE op_id=?", (canonical(prepared), p["op_id"]))
    # Preflight the same deduplicated destination used by media.register before
    # it copies bytes. Symlinked asset folders cannot redirect this import.
    existing = next((item for item in registry._list("media") if item["kind"] == "image" and item["sha256"] == frozen["sha256"]), None)
    _under_root(registry, existing["path"] if existing else "03-资产/图片原件/" + frozen["sha256"] + frozen["suffix"])
    media = registry.dispatch("media.register", prepared)
    if media["sha256"] != frozen["sha256"]:
        raise ConflictError("图片已登记但原件与冻结摘要不符；需核查，不能报告导入成功")
    original = verified_original(registry, {"media_id": p["media_id"], "expected_project_id": p["expected_project_id"]})
    thumbnail, warning = None, None
    try:
        source = Path(original["local_path"])
        thumbnail = str(_image_derivative(registry, media, source, 480, THUMBNAIL_BYTES).relative_to(registry.root))
        _image_derivative(registry, media, source, 960, PREVIEW_BYTES)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        warning = str(exc)
    verified_original(registry, {"media_id": p["media_id"], "expected_project_id": p["expected_project_id"]})
    result = {**media, "local_path": original["local_path"], "thumbnail_path": thumbnail,
              "import_status": "registered", "original_saved": True, "hash_verified": True,
              "preview_status": "unavailable" if warning else "ready", "warning": warning, "cloud_upload": False}
    registry.db.execute("UPDATE image_import_jobs SET result=? WHERE op_id=?", (canonical(result), p["op_id"]))
    if staging.is_file() and _digest(staging) == frozen["sha256"]:
        staging.unlink()
    return result

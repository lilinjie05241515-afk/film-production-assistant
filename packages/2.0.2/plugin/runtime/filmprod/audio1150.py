"""Register selected existing audio and produce a short listening derivative.

No synthesis, music generation, timeline editing or adoption takes place here.
"""
from __future__ import annotations

import base64
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from .core import ConflictError, canonical, content_hash, identifier, required
from .documents import _plain_path
from .media120 import _digest, _under_root, verified_original
from .render import _exe, _job_lock, probe

SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".aiff", ".aif"}
MAX_BYTES = 512 * 1024 * 1024
PREVIEW_BYTES = 1024 * 1024
PREVIEW_SECONDS = 20


def choose_audio():
    import tkinter
    from tkinter import filedialog
    window = tkinter.Tk()
    window.withdraw()
    window.attributes("-topmost", True)
    try:
        selected = filedialog.askopenfilename(parent=window, title="选择已有音频（登记原件，不生成音乐）",
            filetypes=[("音频", "*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.opus *.aiff *.aif")])
        return {"path": str(Path(selected).resolve()) if selected else None,
                "cancelled": not bool(selected), "cloud_upload": False}
    finally:
        window.destroy()


def _directory(registry, name):
    _plain_path(registry.root, directory=True)
    _plain_path(registry.internal, directory=True)
    directory = registry.internal / name
    directory.mkdir(exist_ok=True)
    _plain_path(directory, directory=True)
    return directory


def _derivative(registry, media):
    original = verified_original(registry, {"media_id": media["media_id"],
        "expected_project_id": registry._project()["project_id"]})
    source = Path(original["local_path"])
    target = _directory(registry, "previews") / (media["sha256"] + ".audio20-v1.mp3")
    if target.exists():
        _plain_path(target, directory=False)
        if 0 < target.stat().st_size <= PREVIEW_BYTES:
            return target
        raise ValueError("音频预览缓存无效；原件保持不变")
    temporary = target.with_name(".audio-preview-" + uuid.uuid4().hex + ".mp3")
    try:
        process = subprocess.run([_exe("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", str(source), "-t", str(PREVIEW_SECONDS), "-map", "0:a:0", "-vn",
            "-ac", "1", "-ar", "22050", "-c:a", "libmp3lame", "-b:a", "64k",
            "-y", str(temporary)], capture_output=True, timeout=45)
        if process.returncode or not temporary.is_file() or not 0 < temporary.stat().st_size <= PREVIEW_BYTES:
            raise ValueError("短音频预览未生成；已登记原件仍可打开")
        if _digest(source) != media["sha256"]:
            raise ConflictError("音频原件在预览期间发生变化")
        # Another preview can have completed in parallel; never replace a foreign link.
        if target.exists():
            _plain_path(target, directory=False)
        os.replace(temporary, target)
        return target
    finally:
        if temporary.exists():
            temporary.unlink()


def preview_audio(registry, payload):
    if set(payload) - {"expected_project_id", "media_id", "thumbnail_only"}:
        raise ValueError("音频预览只接受已登记的媒体身份")
    required(payload, "media_id")
    media = registry._get("media", "media_id", payload["media_id"])
    if media["kind"] != "audio":
        raise ValueError("该原件不是音频")
    original = verified_original(registry, {"media_id": media["media_id"],
        "expected_project_id": registry._project()["project_id"]})
    preview, reason = None, None
    try:
        derivative = _derivative(registry, media)
        preview = "data:audio/mpeg;base64," + base64.b64encode(derivative.read_bytes()).decode("ascii")
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        reason = str(exc)
    return {**original, "source_sha256": media["sha256"], "title": media.get("metadata", {}).get("title", media["media_id"]),
            "preview_data_uri": preview, "thumbnail_data_uri": None,
            "preview_inline_available": bool(preview), "duration_seconds": media.get("metadata", {}).get("duration_seconds"),
            "preview_kind": "low_bitrate_first_20_seconds", "preview_max_seconds": PREVIEW_SECONDS,
            "reason": reason, "read_only": True, "music_generated": False}


def import_audio(registry, payload):
    required(payload, "op_id", "expected_project_id", "media_id", "path")
    if set(payload) - {"op_id", "expected_project_id", "media_id", "path", "metadata", "kind"}:
        raise ValueError("音频导入仅接受所选文件与登记信息")
    if "kind" in payload and payload["kind"] != "audio":
        raise ValueError("音频导入 kind 只能为 audio")
    identifier(payload["op_id"], "op_id")
    identifier(payload["media_id"], "media_id")
    registry.check_project_identity(payload["expected_project_id"])
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("metadata 必须为对象")
    if metadata.get("audio_category", "unclassified") not in {"music", "dialogue", "sfx", "effect", "ambience", "other", "unclassified"}:
        raise ValueError("音频管理分类须为 music/dialogue/sfx/ambience/other/unclassified")
    with _job_lock(_directory(registry, "media-import-locks") / (content_hash(payload["op_id"]) + ".audio.lock")):
        registry.db.execute("CREATE TABLE IF NOT EXISTS audio_import_jobs(op_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, frozen TEXT, prepared TEXT, result TEXT)")
        request_hash = content_hash(payload)
        old = registry.db.execute("SELECT * FROM audio_import_jobs WHERE op_id=?", (payload["op_id"],)).fetchone()
        if old and old["request_hash"] != request_hash:
            raise ConflictError("音频导入 op_id 已用于不同请求")
        if old and old["result"]:
            result = json.loads(old["result"])
            verified_original(registry, {"media_id": result["media_id"]})
            return {**result, "local_path": str(_under_root(registry, result["path"]))}
        if old and old["prepared"]:
            prepared = json.loads(old["prepared"])
            if not registry.db.execute("SELECT 1 FROM operations WHERE op_id=?", (payload["op_id"],)).fetchone():
                staged = _directory(registry, "import-staging") / (content_hash(payload["op_id"]) + Path(prepared["path"]).suffix)
                if not staged.is_file() or _digest(staged) != prepared["metadata"]["probe_source_sha256"]:
                    raise ConflictError("待核对导入的暂存原件不完整；保留原操作号")
                prepared["path"] = str(staged)
        else:
            if old and old["frozen"]:
                frozen = json.loads(old["frozen"])
                source = Path(frozen["path"])
                if not source.is_file() or _digest(source) != frozen["sha256"]:
                    raise ConflictError("音频源与此操作冻结字节不同；保留原操作号核查")
            else:
                source = Path(payload["path"]).expanduser()
                if not source.is_absolute() or not source.is_file() or source.suffix.lower() not in SUFFIXES:
                    raise ValueError("请选择支持格式的已有音频绝对路径")
                _plain_path(source, directory=False)
                if not 0 < source.stat().st_size <= MAX_BYTES:
                    raise ValueError("音频为空或超过512 MiB导入上限")
                frozen = {"path": str(source.resolve()), "sha256": _digest(source)}
                registry.db.execute("INSERT INTO audio_import_jobs VALUES(?,?,?,NULL,NULL)",
                    (payload["op_id"], request_hash, canonical(frozen)))
            if not source.is_absolute() or not source.is_file() or source.suffix.lower() not in SUFFIXES:
                raise ValueError("请选择支持格式的已有音频绝对路径")
            _plain_path(source, directory=False)
            if not 0 < source.stat().st_size <= MAX_BYTES:
                raise ValueError("音频为空或超过512 MiB导入上限")
            source_sha = frozen["sha256"]
            info = probe(source)
            stream = next((entry for entry in info.get("streams", []) if entry.get("codec_type") == "audio"), None)
            if not stream or any(entry.get("codec_type") == "video" and not entry.get("disposition", {}).get("attached_pic") for entry in info.get("streams", [])):
                raise ValueError("所选文件不是独立音频；视频请在视频页登记")
            duration = info.get("format", {}).get("duration") or stream.get("duration")
            try:
                duration = float(duration)
                if not math.isfinite(duration) or duration < 0:
                    duration = None
            except (ValueError, TypeError):
                duration = None
            staged = _directory(registry, "import-staging") / (content_hash(payload["op_id"]) + source.suffix.lower())
            if staged.exists():
                _plain_path(staged, directory=False)
            temporary = staged.with_name(".audio-" + uuid.uuid4().hex + ".tmp")
            try:
                shutil.copyfile(source, temporary)
                if _digest(temporary) != source_sha or _digest(source) != source_sha:
                    raise ConflictError("复制期间音频变化")
                os.replace(temporary, staged)
            finally:
                if temporary.exists():
                    temporary.unlink()
            prepared = {"op_id": payload["op_id"], "expected_project_id": payload["expected_project_id"],
                "media_id": payload["media_id"], "kind": "audio", "path": str(staged), "metadata": {
                **metadata, "title": metadata.get("title") or source.stem,
                "audio_category": "sfx" if metadata.get("audio_category") == "effect" else metadata.get("audio_category", "unclassified"),
                "duration_seconds": duration, "sample_rate": stream.get("sample_rate"),
                "channels": stream.get("channels"), "codec": stream.get("codec_name"),
                "probe_source_sha256": source_sha, "original_source_path": str(source.resolve()),
                "original_storage": "local_project", "cloud_upload": False}}
            registry.db.execute("UPDATE audio_import_jobs SET prepared=? WHERE op_id=?",
                (canonical(prepared), payload["op_id"]))
        existing = next((item for item in registry._list("media") if item["kind"] == "audio" and item["sha256"] == prepared["metadata"]["probe_source_sha256"]), None)
        _under_root(registry, existing["path"] if existing else "06-音乐/音频原件/" + prepared["metadata"]["probe_source_sha256"] + Path(prepared["path"]).suffix.lower())
        media = registry.dispatch("media.register", prepared)
        warning = None
        try:
            _derivative(registry, media)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            warning = str(exc)
        result = {**media, "local_path": str(_under_root(registry, media["path"])),
                  "cloud_upload": False, "music_generated": False, "warning": warning}
        registry.db.execute("UPDATE audio_import_jobs SET result=? WHERE op_id=?", (canonical(result), payload["op_id"]))
        staged = _directory(registry, "import-staging") / (content_hash(payload["op_id"]) + Path(prepared["path"]).suffix)
        if staged.is_file() and _digest(staged) == prepared["metadata"]["probe_source_sha256"]:
            staged.unlink()
        return result

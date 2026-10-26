"""Local FFmpeg renderer for a deliberately small, exact edit manifest.

No network or generative calls. Supports contiguous cuts, source audio,
additional aligned audio with gain and MP4 selectable subtitle tracks.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from .core import ConflictError, Registry, canonical, content_hash, now, required


RENDERER_VERSION = "1.1.0"
CLEARED_RIGHTS = {"owned", "licensed", "public_domain", "cleared"}


def _hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _number(value, name, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{name} 必须为{'正' if positive else '非负'}有限数字")
    return float(value)


def _exe(name, supplied=None):
    path = Path(supplied).expanduser().resolve() if supplied else Path(shutil.which(name) or "")
    if not path.is_file():
        raise ValueError(f"本机未找到 {name}；请安装或显式传入可执行文件路径")
    return str(path.resolve())


def _run(args, cwd=None, timeout=600):
    result = subprocess.run(args, cwd=cwd, capture_output=True, timeout=timeout, shell=False)
    if result.returncode:
        raise ValueError("本地媒体命令失败: " + result.stderr.decode("utf-8", errors="replace")[-6000:])
    return result.stdout


def probe(path, executable=None):
    return json.loads(_run([_exe("ffprobe", executable), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]))


@contextlib.contextmanager
def _job_lock(path):
    """An OS-owned lock, released by process exit even after an interruption."""
    with Path(path).open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ConflictError("同一渲染操作正在执行，请等待其结果") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _stream(info, kind):
    return next((s for s in info.get("streams", []) if s["codec_type"] == kind), None)


def _duration(info, kind=None):
    stream = _stream(info, kind) if kind else None
    if stream and stream.get("duration") is not None:
        return float(stream["duration"])
    durations = [float(s["duration"]) for s in info.get("streams", []) if s.get("duration") is not None]
    if info.get("format", {}).get("duration") is not None:
        durations.append(float(info["format"]["duration"]))
    return max(durations) if durations else None


def _rights(metadata, label, issues):
    if metadata.get("rights_status") not in CLEARED_RIGHTS or not metadata.get("rights_evidence"):
        issues.append({"code": "rights_unverified", "source": label, "rights_status": metadata.get("rights_status")})


def _freeze(registry, final_id, version, ffprobe):
    """Take exact immutable revisions and check every declared dependency."""
    snapshot = registry.snapshot()
    latest = {a["artifact_id"]: a for a in snapshot["artifacts"]}
    approved = {a["artifact_id"]: a for a in snapshot.get("approved_artifacts", [])}
    media_lookup = {m["media_id"]: m for m in snapshot["media"]}
    frozen, sources, issues = {}, {}, []
    def artifact(ref):
        key = (ref["artifact_id"], ref["version"])
        if key in frozen:
            return frozen[key]
        item = registry.dispatch("artifact.get", ref)
        if content_hash(item["content"]) != item["sha256"]:
            raise ValueError("成果内容哈希不匹配: " + item["artifact_id"])
        frozen[key] = item
        current = latest.get(item["artifact_id"])
        accepted = approved.get(item["artifact_id"])
        if accepted and item["version"] <= accepted["version"]:
            current = accepted
        if not current or current["version"] != item["version"]:
            issues.append({"code": "old_version", "artifact_id": item["artifact_id"], "version": item["version"], "latest": current["version"] if current else None})
        if item["status"] == "needs_review" or (current and current["status"] == "needs_review"):
            issues.append({"code": "needs_review", "artifact_id": item["artifact_id"], "version": item["version"]})
        if item["metadata"].get("deleted_in_cloud"):
            issues.append({"code": "deleted_in_cloud", "artifact_id": item["artifact_id"]})
        for dep in item["deps"]:
            artifact(dep)
        return item
    def source(media_id, expected):
        if media_id in sources:
            item = sources[media_id]
            if item["kind"] != expected:
                raise ValueError("媒体类型不符: " + media_id)
            return item
        if media_id not in media_lookup:
            raise ValueError("源媒体未登记: " + media_id)
        item = dict(media_lookup[media_id])
        path = (registry.root / item["path"]).resolve()
        if not path.is_relative_to(registry.root) or not path.is_file():
            raise ValueError("原件缺失或路径越界: " + media_id)
        if item["kind"] != expected or _hash(path) != item["sha256"]:
            raise ValueError("原件类型或 SHA256 核验失败: " + media_id)
        info = probe(path, ffprobe)
        if not _stream(info, expected):
            raise ValueError("实际文件缺少所需媒体流: " + media_id)
        item.update(absolute_path=str(path), actual_probe=info)
        sources[media_id] = item
        _rights(item["metadata"], media_id, issues)
        return item
    final = artifact({"artifact_id": final_id, "version": version})
    if final["kind"] != "final":
        raise ValueError("渲染入口必须绑定 final 精确版本")
    metadata = final["metadata"]
    registry._validate_media_artifact("final", metadata, final["deps"])
    for field in ("planned_music", "planned_shots", "planned_dialogue"):
        if metadata.get(field):
            issues.append({"code": "unfulfilled_plan", "field": field, "references": metadata[field]})
    if metadata.get("assembly_status") == "planned":
        issues.append({"code": "planned_manifest"})
    spec = metadata["export_spec"]
    if spec.get("format", "mp4") != "mp4" or spec.get("video_codec", "h264") not in ("h264", "libx264") or spec.get("audio_codec", "aac") != "aac":
        raise ValueError("1.1.0 只支持 MP4 / H.264 / AAC，不会忽略请求的其他导出格式")
    width, height, fps = spec["width"], spec["height"], spec["fps"]
    if width % 2 or height % 2:
        raise ValueError("H.264 yuv420p 导出宽高须为偶数")
    if spec.get("sample_rate", 48000) != 48000 or spec.get("channels", 2) != 2:
        raise ValueError("1.1.0 音频输出仅支持 48000 Hz 双声道")
    timeline = artifact(metadata["timeline"])
    segments, cursor = [], 0.0
    entries = sorted(timeline["metadata"]["clips"], key=lambda e: e["timeline_in_seconds"])
    if len(entries) > 200:
        raise ValueError("1.1.0 单批渲染上限为 200 个顺序片段")
    for entry in entries:
        clip = artifact(entry)
        if clip["kind"] != "clip":
            raise ValueError("时间线只能包含精确 clip 引用")
        cm = clip["metadata"]
        media = source(cm["source_media_id"], "video")
        start, end = _number(cm["in_seconds"], "source in"), _number(cm["out_seconds"], "source out", True)
        at = _number(entry["timeline_in_seconds"], "timeline in")
        if abs(at - cursor) > 0.0001:
            raise ValueError("1.1.0 仅支持从 0 开始连续顺切；时间线含间隙或重叠，请先明确剪辑方案")
        actual_duration = _duration(media["actual_probe"], "video")
        if end <= start or actual_duration is None or end > actual_duration + 0.03:
            raise ValueError("clip 入出点超出实际探测时长或时长未知")
        segment = {"clip": {"artifact_id": clip["artifact_id"], "version": clip["version"]}, "media_id": media["media_id"], "in_seconds": start, "out_seconds": end, "timeline_in_seconds": at, "duration_seconds": end - start, "source_audio": bool(_stream(media["actual_probe"], "audio")) and not cm.get("muted", False)}
        segments.append(segment)
        cursor += end - start
    if cursor <= 0:
        raise ValueError("时间线为空")
    tracks = []
    for role in ("music", "dialogue"):
        for ref in metadata[role]:
            item = artifact(ref)
            am = item["metadata"]
            media = source(am["source_media_id"], "audio")
            duration = _duration(media["actual_probe"], "audio")
            if duration is None:
                raise ValueError("音频实际时长未知")
            start = _number(am.get("in_seconds", 0), "audio in")
            end = _number(am.get("out_seconds", duration), "audio out", True)
            at = _number(ref.get("timeline_in_seconds", am.get("timeline_in_seconds", 0)), "audio timeline in")
            gain = _number(ref.get("gain", am.get("gain", 1)), "audio gain")
            if end <= start or end > duration + 0.03 or at >= cursor or at + end - start > cursor + 0.03:
                raise ValueError("音轨选段/对齐超出源或成片时长；不会自动截断未知意图")
            if gain > 4:
                raise ValueError("单轨 gain 最大为 4；更复杂混音请预先制作音轨")
            tracks.append({"artifact_id": item["artifact_id"], "version": item["version"], "role": role, "media_id": media["media_id"], "in_seconds": start, "out_seconds": end, "timeline_in_seconds": at, "gain": gain})
    subtitles = []
    for ref in metadata["subtitles"]:
        item = artifact(ref)
        _rights(item["metadata"], item["artifact_id"], issues)
        cues = item["metadata"].get("cues")
        if not isinstance(cues, list):
            raise ValueError("字幕需 metadata.cues=[{start_seconds,end_seconds,text}]，不解析含糊自然语言时间")
        for cue in cues:
            required(cue, "start_seconds", "end_seconds", "text")
            start, end = _number(cue["start_seconds"], "subtitle start"), _number(cue["end_seconds"], "subtitle end", True)
            if not isinstance(cue["text"], str) or "\x00" in cue["text"] or end <= start or end > cursor + 0.001:
                raise ValueError("字幕文字或时间范围无效")
            subtitles.append({"start_seconds": start, "end_seconds": end, "text": cue["text"]})
    subtitles.sort(key=lambda cue: cue["start_seconds"])
    for first, second in zip(subtitles, subtitles[1:]):
        if first["end_seconds"] > second["start_seconds"]:
            raise ValueError("1.1.0 单字幕轨不支持重叠字幕")
    return {"renderer_version": RENDERER_VERSION, "project_id": snapshot["project"]["project_id"], "test_only": snapshot["project"]["test_only"], "source_final": {"artifact_id": final_id, "version": version}, "source_final_scope": final["scope"], "artifacts": list(frozen.values()), "sources": list(sources.values()), "segments": segments, "audio_tracks": tracks, "subtitles": subtitles, "subtitle_mode": "selectable_mov_text", "duration_seconds": cursor, "export_spec": spec, "issues": issues, "frozen_at": now()}


def _time(seconds):
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _command(manifest, job, ffmpeg, preview):
    spec = manifest["export_spec"]
    width, height, fps = spec["width"], spec["height"], spec["fps"]
    sources = {s["media_id"]: s for s in manifest["sources"]}
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n"]
    filters, concat = [], []
    for index, segment in enumerate(manifest["segments"]):
        args += ["-i", sources[segment["media_id"]]["absolute_path"]]
        start, end, duration = segment["in_seconds"], segment["out_seconds"], segment["duration_seconds"]
        filters.append(f"[{index}:v:0]trim=start={start}:end={end},setpts=PTS-STARTPTS,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v{index}]")
        if segment["source_audio"]:
            filters.append(f"[{index}:a:0]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,apad=whole_dur={duration},atrim=duration={duration}[a{index}]")
        else:
            filters.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={duration}[a{index}]")
        concat.extend([f"[v{index}]", f"[a{index}]"])
    filters.append("".join(concat) + f"concat=n={len(manifest['segments'])}:v=1:a=1[cutvideo][cutaudio]")
    video_label = "cutvideo"
    if preview:
        font = Path(os.environ["WINDIR"]) / "Fonts/arial.ttf" if os.environ.get("WINDIR") else None
        font_arg = ""
        if font is not None and font.is_file():
            # Read the installed font in place; never distribute a copied OS
            # font inside a project archive or render deliverable.
            font_filter_path = font.resolve().as_posix().replace(":", "\\:").replace("'", "\\'")
            font_arg = f"fontfile='{font_filter_path}':"
        filters.append(f"[cutvideo]drawtext={font_arg}text='TEST PREVIEW - NOT APPROVED':fontcolor=white:fontsize={max(12, width // 45)}:box=1:boxcolor=black@0.65:x=10:y=10[previewvideo]")
        video_label = "previewvideo"
    mix_labels = ["[cutaudio]"]
    for offset, track in enumerate(manifest["audio_tracks"]):
        index = len(manifest["segments"]) + offset
        args += ["-i", sources[track["media_id"]]["absolute_path"]]
        delay = round(track["timeline_in_seconds"] * 1000)
        filters.append(f"[{index}:a:0]atrim=start={track['in_seconds']}:end={track['out_seconds']},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,volume={track['gain']},adelay={delay}:all=1[t{offset}]")
        mix_labels.append(f"[t{offset}]")
    filters.append("".join(mix_labels) + f"amix=inputs={len(mix_labels)}:duration=longest:normalize=0,alimiter=limit=0.95:latency=1,apad=whole_dur={manifest['duration_seconds']},atrim=duration={manifest['duration_seconds']}[mixedaudio]")
    if manifest["subtitles"]:
        srt = "\n\n".join(f"{i+1}\n{_time(c['start_seconds'])} --> {_time(c['end_seconds'])}\n{c['text']}" for i, c in enumerate(manifest["subtitles"])) + "\n"
        (job / "captions.srt").write_text(srt, encoding="utf-8")
        subtitle_index = len(manifest["segments"]) + len(manifest["audio_tracks"])
        args += ["-sub_charenc", "UTF-8", "-i", "captions.srt"]
    # A filter file keeps the command bounded and contains only numeric config
    # and fixed labels. Paths and arbitrary subtitle strings never enter it.
    (job / "filters.txt").write_text(";\n".join(filters), encoding="utf-8")
    args += ["-filter_complex_script", "filters.txt", "-map", f"[{video_label}]", "-map", "[mixedaudio]"]
    if manifest["subtitles"]:
        args += ["-map", f"{subtitle_index}:s:0", "-c:s", "mov_text", "-disposition:s:0", "default", "-metadata:s:s:0", "language=zho"]
    args += ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-b:a", str(spec.get("bitrate", 192000)), "-ar", "48000", "-ac", "2", "-t", str(manifest["duration_seconds"]), "-movflags", "+faststart", "-metadata", "comment=" + ("TEST PREVIEW; NOT APPROVED" if preview else "LOCAL RENDER; NOT ADOPTED OR PUBLISHED"), "output.mp4"]
    return args


def _verify(output, manifest, ffprobe, ffmpeg, job):
    info = probe(output, ffprobe)
    video, audio = _stream(info, "video"), _stream(info, "audio")
    spec = manifest["export_spec"]
    if not video or not audio:
        raise ValueError("导出文件缺少预期视频/音频流")
    actual_fps = float(Fraction(video["avg_frame_rate"]))
    if (video["width"], video["height"]) != (spec["width"], spec["height"]) or abs(actual_fps - spec["fps"]) > 0.001:
        raise ValueError("导出尺寸或帧率不符合冻结规格")
    if abs(float(video["duration"]) - manifest["duration_seconds"]) > 1 / spec["fps"] + 0.03:
        raise ValueError("导出视频时长不符合时间线")
    if video.get("codec_name") != "h264" or audio.get("codec_name") != "aac" or int(audio["sample_rate"]) != 48000 or audio["channels"] != 2:
        raise ValueError("导出编解码器或音频规格不符")
    subtitle_verified = False
    if manifest["subtitles"]:
        if not _stream(info, "subtitle") or _stream(info, "subtitle")["codec_name"] != "mov_text":
            raise ValueError("输出缺少 MP4 字幕轨")
        extracted = _run([ffmpeg, "-v", "error", "-i", str(output), "-map", "0:s:0", "-f", "srt", "-"], cwd=job).decode("utf-8-sig")
        for cue in manifest["subtitles"]:
            if cue["text"].replace("\r\n", "\n") not in extracted.replace("\r\n", "\n"):
                raise ValueError("输出字幕读回文字不符")
            if f"{_time(cue['start_seconds'])} --> {_time(cue['end_seconds'])}" not in extracted:
                raise ValueError("输出字幕读回时间不符")
        (job / "subtitle-readback.srt").write_text(extracted, encoding="utf-8")
        subtitle_verified = True
    # Decode the complete small/large output once: a successful container probe
    # alone does not establish decodability of all frames and packets.
    _run([ffmpeg, "-v", "error", "-xerror", "-i", str(output), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], cwd=job)
    return {"ffprobe": info, "fully_decoded": True, "subtitle_text_readback": subtitle_verified, "actual_fps": actual_fps, "verified_at": now()}


def _current_result(registry, stored_result, ffprobe):
    """Technical evidence is historical; current readiness is a fresh read."""
    result = dict(stored_result)
    media = next((m for m in registry.snapshot()["media"] if m["media_id"] == result["media_id"]), None)
    path = (registry.root / media["path"]).resolve() if media else None
    if path is None or not path.is_relative_to(registry.root) or not path.is_file() or _hash(path) != result["sha256"]:
        raise ConflictError("已完成渲染的原件缺失或改变；不以同一操作号静默重做")
    manifest_path = Path(result["manifest_path"])
    if not manifest_path.is_file() or _hash(manifest_path) != result["manifest_sha256"]:
        raise ConflictError("渲染来源清单缺失或哈希改变，不能声称已核验可接续结果")
    render = registry.dispatch("artifact.get", {"artifact_id": result["render_id"]})
    try:
        source = result["source_final"]
        current_issues = _freeze(registry, source["artifact_id"], source["version"], ffprobe)["issues"]
    except ValueError as exc:
        current_issues = [{"code": "current_input_check_failed", "message": str(exc)}]
    historical = result.get("historical_issues", result.get("issues", []))
    combined = {canonical(issue): issue for issue in [*historical, *current_issues]}
    needs_review = render["status"] == "needs_review" or bool(current_issues)
    result.update(path=str(path), result_basis="historical_render", technical_verification_scope="saved_output_at_render_time", historical_issues=historical, current_issues=current_issues, issues=list(combined.values()), registry_status=render["status"], current_registry_status=render["status"], current_readiness="needs_review" if needs_review else "ready_for_review", current_checked_at=now(), saved_technical_status=stored_result["status"])
    if needs_review:
        result["status"] = "historical_render_needs_review"
    return result


def render_operation_outcome(registry: Registry, payload: dict) -> str:
    """Classify the *whole operation*, never merely this invocation's stage.

    no_write/failed_before_commit guarantee no encoded bytes or registered
    media/artifact for this operation while holding its OS lock. Diagnostic
    intent files may exist. Anything committed, partial or uninspectable stays
    resumable/unknown so a UI must keep the original request journal.
    """
    op_id = payload.get("op_id") if isinstance(payload, dict) else None
    if not isinstance(op_id, str) or not op_id:
        return "no_write"
    key = hashlib.sha256(op_id.encode()).hexdigest()[:24]
    job = registry.internal / "render-jobs" / key
    try:
        job.mkdir(parents=True, exist_ok=True)
        with _job_lock(job / "operation.lock"), registry.lock:
            state_path = job / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
            committed = registry.db.execute("SELECT 1 FROM operations WHERE op_id IN (?,?) LIMIT 1", (op_id + ":render-media", op_id + ":render-result")).fetchone()
            known_media = registry.db.execute("SELECT 1 FROM media WHERE media_id=?", ("RENDER-MEDIA-" + key,)).fetchone()
            known_artifact = registry.db.execute("SELECT 1 FROM artifacts WHERE artifact_id=?", ("RENDER-" + key,)).fetchone()
            if committed or known_media or known_artifact or (job / "output.mp4").exists():
                return "resumable"
            if state.get("phase") == "encoding":
                # A killed Python parent can release its OS lock while an
                # orphaned FFmpeg child is still alive and has not created the
                # output yet. No persisted child-liveness proof exists here.
                return "unknown"
            if state.get("phase") in ("encoded", "registered", "completed") or state.get("pending_media_request") or state.get("pending_artifact_request"):
                return "resumable"
            return "failed_before_commit" if state else "no_write"
    except Exception:
        return "unknown"


def render_final(registry: Registry, payload: dict) -> dict:
    """Public renderer; exceptions include a proven operation_outcome."""
    try:
        return _render_final_impl(registry, payload)
    except Exception as exc:
        exc.operation_outcome = render_operation_outcome(registry, payload)
        raise


def _render_final_impl(registry: Registry, payload: dict) -> dict:
    """Render one exact final revision. Repeated op_id recovers the same job.

    payload: artifact_id, version, op_id, preview(bool, default False), optional
    ffmpeg/ffprobe executable paths. Formal rendering requires cleared sources.
    """
    p = dict(payload)
    required(p, "artifact_id", "version", "op_id")
    if not isinstance(p["op_id"], str) or len(p["op_id"]) > 190 or type(p["version"]) is not int or p["version"] < 1:
        raise ValueError("op_id/版本无效")
    preview = p.get("preview", False)
    if type(preview) is not bool:
        raise ValueError("preview 必须为布尔值")
    ffmpeg, ffprobe = _exe("ffmpeg", p.get("ffmpeg")), _exe("ffprobe", p.get("ffprobe"))
    request = {"artifact_id": p["artifact_id"], "version": p["version"], "op_id": p["op_id"], "preview": preview, "ffmpeg": ffmpeg, "ffprobe": ffprobe}
    request_hash = content_hash(request)
    job_key = hashlib.sha256(p["op_id"].encode()).hexdigest()[:24]
    job = registry.internal / "render-jobs" / job_key
    job.mkdir(parents=True, exist_ok=True)
    state_path = job / "state.json"
    with _job_lock(job / "operation.lock"):
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"request_hash": request_hash, "request": request, "phase": "intent", "created_at": now()}
        if state["request_hash"] != request_hash:
            raise ConflictError("渲染 op_id 已用于不同参数")
        if state.get("phase") == "encoding" and not state.get("error"):
            raise ConflictError("上次编码中断且没有终止回执；可能仍有 FFmpeg 子进程，拒绝自动启动第二次编码。请先核对本机进程与输出，保留原操作号")
        if state.get("result"):
            return _current_result(registry, dict(state["result"], manifest_path=str(job / "source-manifest.json")), ffprobe)
        _write(state_path, state)
        try:
            pending = state.get("pending_artifact_request")
            if pending and registry._artifact(pending["artifact_id"], 1) is not None:
                # A prior send committed and its return was lost. Reconcile the
                # exact original request before applying today's readiness view.
                saved = registry.dispatch("artifact.save", pending)
                recovered = dict(pending["content"], registry_status=saved["artifact"]["status"])
                state.update(phase="completed", result=recovered)
                _write(job / "result.json", recovered)
                _write(state_path, state)
                partial = job / "output.mp4"
                if partial.is_file() and _hash(partial) == recovered["sha256"]:
                    partial.unlink()
                return _current_result(registry, dict(recovered, manifest_path=str(job / "source-manifest.json")), ffprobe)
            manifest_path = job / "source-manifest.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            else:
                manifest = _freeze(registry, p["artifact_id"], p["version"], ffprobe)
                manifest.update(preview=preview, operation_id=p["op_id"], request_hash=request_hash)
                if manifest["test_only"] and not preview:
                    raise ValueError("测试项目只允许 preview=true，不能产生正式渲染标记")
                if not preview and manifest["issues"]:
                    raise ConflictError("正式渲染前置条件不满足: " + canonical(manifest["issues"]))
                _write(manifest_path, manifest)
            # Recovering an interrupted job uses the original frozen plan but
            # still checks files and freshness, never silently rebinding inputs.
            runtime_sources = []
            for media in manifest["sources"]:
                source_path = (registry.root / media["path"]).resolve()
                if not source_path.is_relative_to(registry.root) or not source_path.is_file() or _hash(source_path) != media["sha256"]:
                    raise ConflictError("冻结源素材丢失或哈希改变，拒绝渲染/恢复")
                runtime_sources.append(dict(media, absolute_path=str(source_path)))
            runtime_manifest = dict(manifest, sources=runtime_sources)
            current = _freeze(registry, p["artifact_id"], p["version"], ffprobe)
            if not preview and current["issues"]:
                raise ConflictError("恢复时输入已失效: " + canonical(current["issues"]))
            output = job / "output.mp4"
            if state.get("phase") not in ("encoded", "registered"):
                # A partial file is only removed in this exact generated job
                # directory; source media and other jobs are never touched.
                if output.exists():
                    if output.resolve().parent != job.resolve():
                        raise ValueError("渲染临时文件路径异常")
                    output.unlink()
                command = _command(runtime_manifest, job, ffmpeg, preview)
                state.pop("error", None)
                state.update(phase="encoding", command=command, started_at=now())
                _write(state_path, state)
                _run(command, cwd=job)
                verification = _verify(output, manifest, ffprobe, ffmpeg, job)
                state.update(phase="encoded", output_sha256=_hash(output), verification=verification)
                _write(state_path, state)
            elif not output.exists():
                registered = next((m for m in registry.snapshot()["media"] if m["media_id"] == "RENDER-MEDIA-" + job_key), None)
                if not registered:
                    raise ConflictError("渲染恢复缺少编码输出及登记原件")
                output = registry.root / registered["path"]
            if _hash(output) != state["output_sha256"]:
                raise ConflictError("编码输出哈希改变")
            current = _freeze(registry, p["artifact_id"], p["version"], ffprobe)
            if not preview and current["issues"]:
                raise ConflictError("渲染完成后输入已变化，保留技术输出但拒绝正式登记: " + canonical(current["issues"]))
            media_request = {"op_id": p["op_id"] + ":render-media", "media_id": "RENDER-MEDIA-" + job_key, "kind": "video", "path": str(job / "output.mp4"), "metadata": {"duration_seconds": manifest["duration_seconds"], "role": "rendered_preview" if preview else "rendered_output", "technical_check": state["verification"], "rights_status": None if preview else "cleared", "rights_evidence": None if preview else "See exact source-manifest; no new rights granted", "source_final": manifest["source_final"], "preview": preview, "synthetic": manifest["test_only"]}}
            if state.get("pending_media_request") is not None:
                media_request = state["pending_media_request"]
                committed = registry.db.execute("SELECT 1 FROM operations WHERE op_id=?", (media_request["op_id"],)).fetchone()
                current_output = str(output)
                if not committed and media_request["path"] != current_output:
                    # A backed-up pre-send intent has no committed operation.
                    # Rebase only its local source path, preserve the previous
                    # intent, and let core dedupe reject any unexpected race.
                    state.setdefault("media_request_relocations", []).append({"previous_request": media_request, "new_path": current_output, "observed_at": now(), "reason": "no committed operation; local restore path changed"})
                    media_request = dict(media_request, path=current_output)
                    state["pending_media_request"] = media_request
                    _write(state_path, state)
            else:
                state["pending_media_request"] = media_request
                _write(state_path, state)
            registered = registry.dispatch("media.register", media_request)
            state.update(phase="registered")
            _write(state_path, state)
            actual_path = registry.root / registered["path"]
            result = {"render_id": "RENDER-" + job_key, "media_id": registered["media_id"], "path": str(actual_path), "sha256": registered["sha256"], "preview": preview, "synthetic": manifest["test_only"], "source_final": manifest["source_final"], "manifest_path": str(manifest_path), "manifest_sha256": _hash(manifest_path), "verification": state["verification"], "issues": current["issues"], "status": "technical_preview_verified" if preview else "technical_render_verified", "adoption": "not_recorded", "delivery": "not_recorded", "publication": "not_recorded", "completed_at": now()}
            # Persist the exact future artifact request before its first send.
            # A lost return can replay it byte-for-byte, including timestamps.
            if state.get("pending_result") is not None:
                result = dict(state["pending_result"])
            else:
                state["pending_result"] = dict(result)
                _write(state_path, state)
            artifact_request = {"op_id": p["op_id"] + ":render-result", "artifact_id": result["render_id"], "kind": "render", "scope": manifest["source_final_scope"] + "/render", "content": result, "base_version": 0, "deps": [manifest["source_final"]], "metadata": {"source_media_id": registered["media_id"], "source_final": manifest["source_final"], "preview": preview, "synthetic": manifest["test_only"], "technical_status": result["status"], "issues": current["issues"]}}
            if state.get("pending_artifact_request") is not None:
                artifact_request = state["pending_artifact_request"]
            else:
                state["pending_artifact_request"] = artifact_request
                _write(state_path, state)
            saved = registry.dispatch("artifact.save", artifact_request)
            result["registry_status"] = saved["artifact"]["status"]
            if not preview and result["registry_status"] == "needs_review":
                raise ConflictError("登记时输入并发变化，输出保留为待复核，不能宣称当前正式渲染")
            _write(job / "result.json", result)
            state.update(phase="completed", result=result)
            _write(state_path, state)
            if output == job / "output.mp4" and output.resolve() != actual_path.resolve():
                output.unlink()  # canonical registered original is now the sole video copy
            return _current_result(registry, result, ffprobe)
        except Exception as exc:
            # Preserve frozen input, command, log message and completed bytes
            # for diagnosis/recovery. This is not a successful render event.
            state.update(error={"type": type(exc).__name__, "message": str(exc), "at": now()})
            _write(state_path, state)
            raise

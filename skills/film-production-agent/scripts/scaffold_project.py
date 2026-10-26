"""Build local film folders and derived navigation; never writes the film registry.

Chats are created and verified by the host, not by this helper. Requires a
registered project and a selected route. Generated navigation is a dated snapshot.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import uuid

RULES = Path(__file__).resolve().parents[1] / "references/project-bootstrap.md"
BEGIN = "<!-- film-workspace-managed:start -->"
END = "<!-- film-workspace-managed:end -->"
INDEX = Path("09-任务与接续/工作对话")
STATE = INDEX / ".scaffold-state.json"
ROLES = {
    "control": "项目总控", "planning": "灵感与需求", "novel": "小说创作",
    "script": "编剧与修订", "art": "美术总监", "director": "导演与特效",
    "assets": "资产与视频提示词", "review": "审核与交付",
}
ROUTES = {"screenplay", "novel_to_screen", "novel_only"}
FOLDERS = [
    "00-设定与依据", "01-故事与剧本", "02-导演方案", "03-资产",
    "04-提示词与生成任务", "05-片段", "06-音乐", "07-成片",
    "08-审核记录", "09-任务与接续", "10-影视研究与复盘", "11-导出/Markdown",
    "01-故事与剧本/故事讨论", "01-故事与剧本/大纲", "01-故事与剧本/剧本",
    "01-故事与剧本/人物小传", "03-资产/人物", "03-资产/场景",
    "03-资产/道具", "03-资产/图片原件", "04-提示词与生成任务/资产提示词",
    "04-提示词与生成任务/AI视频提示词", "05-片段/视频原件",
    "05-片段/低清预览", "06-音乐/音频原件", "06-音乐/配乐",
    "06-音乐/音效", "07-成片/剪辑工程", "07-成片/交付成片",
    "09-任务与接续/工作对话", "09-任务与接续/交接记录",
]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def trusted_mac_system_alias(path: Path) -> bool:
    if sys.platform != "darwin":
        return False
    target = {"/var": "/private/var", "/tmp": "/private/tmp"}.get(path.as_posix())
    if not target:
        return False
    try:
        return path.resolve(strict=True) == Path(target) and Path(target).is_dir()
    except (OSError, RuntimeError):
        return False


def check_path(path: Path, kind: str | None = None) -> None:
    """Reject user links/reparse points; verify only macOS's fixed system aliases."""
    for item in reversed((path, *path.parents)):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            if stat.S_ISLNK(info.st_mode) and trusted_mac_system_alias(item):
                if item == path and kind == "file":
                    raise ValueError(f"目标不是普通文件：{item}")
                continue
            raise ValueError(f"拒绝链接或重解析路径：{item}")
        if item != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"父路径不是目录：{item}")
        if item == path and kind == "directory" and not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"目标不是目录：{item}")
        if item == path and kind == "file" and not stat.S_ISREG(info.st_mode):
            raise ValueError(f"目标不是普通文件：{item}")


def load_source(root: Path, expected_id: str):
    db_path = root / ".project/registry.sqlite3"
    check_path(db_path, "file")
    if not db_path.is_file():
        raise ValueError("请先通过影视 Agent 登记项目；缺少 .project/registry.sqlite3")
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        values = dict(db.execute("SELECT key,value FROM settings WHERE key IN ('schema_version','project','workspace/v1')"))
    if json.loads(values.get("schema_version", "null")) != 2:
        raise ValueError("只支持 schema_version=2；本助手不迁移登记库")
    project = json.loads(values.get("project", "null"))
    if not isinstance(project, dict) or project.get("project_id") != expected_id:
        raise ValueError("项目身份不符，未创建目录或写入文件")
    if not isinstance(project.get("title"), str) or not isinstance(project.get("workflow"), dict):
        raise ValueError("项目格式未知或尚未选择路线")
    mode = project["workflow"].get("mode")
    if mode not in ROUTES:
        raise ValueError("请先通过影视工具选择 screenplay/novel_to_screen/novel_only 路线")
    workspace = json.loads(values.get("workspace/v1", "null"))
    if workspace is None:
        workspace = {"revision": 0, "prepared": False, "slots": [], "initialization_id": None}
    if (not isinstance(workspace, dict) or type(workspace.get("revision")) is not int
            or not isinstance(workspace.get("slots"), list)):
        raise ValueError("workspace/v1 格式未知")
    for slot in workspace["slots"]:
        if (not isinstance(slot, dict) or slot.get("role") not in ROLES
                or not isinstance(slot.get("scope"), str)
                or not isinstance(slot.get("slot_id"), str)
                or slot.get("project_id") != expected_id
                or not isinstance(slot.get("observations", []), list)):
            raise ValueError("工作区槽位格式未知或项目身份不符")
        for key in ("thread_id", "client_thread_id", "client_project_id"):
            if slot.get(key) is not None and not isinstance(slot[key], str):
                raise ValueError(f"工作区 {key} 格式未知")
    return project, workspace


def compact_slots(workspace):
    result = []
    for slot in workspace["slots"]:
        observations = []
        for event in slot.get("observations", []):
            obs = event.get("observation", {})
            observations.append({"event": event.get("event"), "observed_at": obs.get("observed_at"),
                                 "recorded_at": event.get("recorded_at"), "tool": obs.get("tool"),
                                 "reason": obs.get("reason")})
        pending_events = set()
        if slot.get("status") in {"unknown", "failed"}:
            pending_events.update({"unknown", "failed"})
        if slot.get("open_status") == "host_reported_failed":
            pending_events.add("open_failed")
        pending = next((o for o in reversed(observations) if o["event"] in pending_events and o["reason"]), None)
        thread_id = slot.get("thread_id")
        host = slot.get("host_observation") or {}
        verified_link = bool(thread_id and thread_id != slot.get("client_thread_id") and host.get("thread_id") == thread_id)
        result.append({
            "slot_id": slot["slot_id"], "role": slot["role"], "role_label": ROLES[slot["role"]],
            "scope": slot["scope"], "title": slot.get("title"), "status": slot.get("status"),
            "thread_id": thread_id, "chat_url": f"codex://threads/{thread_id}" if verified_link else None,
            "client_thread_id": slot.get("client_thread_id"), "request_id": slot.get("request_id"),
            "catalog_binding_status": slot.get("catalog_binding_status"),
            "client_project_status": slot.get("client_project_status"), "client_project_id": slot.get("client_project_id"),
            "open_status": slot.get("open_status"), "pending_reason": pending,
            "host_observed_at": host.get("observed_at"), "observations": observations,
        })
    return result


def md(value):
    return str(value if value is not None else "未确认").replace("|", "\\|").replace("\r", " ").replace("\n", " ").replace("[", "\\[").replace("]", "\\]")


def merge_block(old: bytes | None, body: str, previous_hash: str | None, path: Path):
    block = f"{BEGIN}\n{body.rstrip()}\n{END}".encode("utf-8")
    text = old or b""
    text.decode("utf-8-sig")  # Check encoding while preserving original bytes.
    begin, end = BEGIN.encode(), END.encode()
    if begin in text or end in text:
        if text.count(begin) != 1 or text.count(end) != 1 or text.index(end) < text.index(begin):
            raise ValueError(f"管理区标记冲突：{path}")
        start, stop = text.index(begin), text.index(end) + len(end)
        previous_block = text[start:stop]
        if previous_hash != sha(previous_block):
            raise ValueError(f"管理区已有外部修改或缺少校验记录，保留原文：{path}")
        text = text[:start] + block + text[stop:]
    else:
        if previous_hash:
            raise ValueError(f"管理区已被移除，保留原文：{path}")
        text = text + (b"\n\n" if text and not text.endswith(b"\n\n") else b"") + block + b"\n"
    return text, sha(block)


def scaffold(root_value: str, expected_id: str):
    if not RULES.is_file():
        raise ValueError("缺少包内 references/project-bootstrap.md，请使用完整插件包")
    raw = Path(root_value).expanduser()
    if not raw.is_absolute():
        raise ValueError("--root 必须是显式绝对路径")
    check_path(raw, "directory")
    root = raw.resolve(strict=True)
    project, workspace = load_source(root, expected_id)
    directories = list(FOLDERS)
    if project["workflow"]["mode"] in {"novel_to_screen", "novel_only"}:
        directories.append("01-故事与剧本/小说")
    paths = [Path("AGENTS.md"), Path("项目入口.md"), INDEX / "对话索引.md", INDEX / "对话索引.json", STATE]
    # Preflight every destination before making a directory or modifying a file.
    for relative in directories:
        check_path(root / relative, "directory")
    for relative in paths:
        check_path(root / relative, "file")
    previous = {p.as_posix(): (root / p).read_bytes() if (root / p).exists() else None for p in paths}
    state_bytes = previous[STATE.as_posix()]
    state = json.loads(state_bytes) if state_bytes else {"schema": 1, "project_id": expected_id, "files": {}}
    if state.get("schema") != 1 or state.get("project_id") != expected_id or not isinstance(state.get("files"), dict):
        raise ValueError("搭建文件校验记录不匹配")
    generated = {}
    new_state = {"schema": 1, "project_id": expected_id, "files": {}}
    snapshot = {
        "project_id": expected_id, "title": project["title"], "root": str(root),
        "workflow_mode": project["workflow"]["mode"], "workspace_revision": workspace["revision"],
        "initialization_id": workspace.get("initialization_id"), "prepared": workspace.get("prepared", False),
        "read_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": ".project/registry.sqlite3 settings workspace/v1",
        "evidence_level": "derived_snapshot_of_caller_reported_observations", "observations_are_live": False,
        "slots": compact_slots(workspace),
    }
    # Keep a byte-identical snapshot on an unchanged repeat; its original read time
    # remains explicit. The command result separately reports this run's read time.
    current_read_at = snapshot["read_at"]
    old_snapshot_bytes = previous[(INDEX / "对话索引.json").as_posix()]
    if old_snapshot_bytes:
        old_snapshot = json.loads(old_snapshot_bytes)
        if {k: v for k, v in old_snapshot.items() if k != "read_at"} == {k: v for k, v in snapshot.items() if k != "read_at"}:
            snapshot["read_at"] = old_snapshot.get("read_at")
    lines = [f"# {project['title']} · 工作对话索引", "", f"项目 ID：`{expected_id}` · 工作区修订：{workspace['revision']}",
             f"读取时间：{snapshot['read_at']}", "", "这是项目登记中的宿主观察快照，不是实时聊天状态。真实聊天保留在客户端；排队 ID 不能打开为聊天。",
             "目录绑定、侧栏项目归属、就绪和业务完成是不同事实；null 保持未确认。调用前重新用 film_workspace 核对。",
             "索引包含当前及历史已登记职责；当前必需职责以 film_workspace.required_roles 为准。", "",
             "| 职责 | 聊天 | 范围 | 槽位状态 | 目录绑定 | 侧栏项目观察 | 待处理原因 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for slot in snapshot["slots"]:
        title = md(slot["title"])
        chat = f"[{title}]({slot['chat_url']})" if slot["chat_url"] else title + "（暂无已核对链接）"
        pending = slot["pending_reason"]
        reason = f"{md(pending['event'])}：{md(pending['reason'])}" if pending else "未记录当前原因"
        lines.append(f"| {md(slot['role_label'])} | {chat} | {md(slot['scope'])} | {md(slot['status'])} | {md(slot['catalog_binding_status'])} | {md(slot['client_project_status'])} / {md(slot['client_project_id'])} | {reason} |")
    if not snapshot["slots"]:
        lines.append("\n主要工作对话尚未登记；由主协调器核对本使用者的授权，再按包内项目搭建流程完成宿主搭建。")
    complete = {INDEX / "对话索引.json": encoded(snapshot), INDEX / "对话索引.md": ("\n".join(lines) + "\n").encode("utf-8")}
    for relative, content in complete.items():
        key = relative.as_posix()
        old = previous[key]
        saved = state["files"].get(key, {})
        if old is not None and saved.get("sha256") != sha(old):
            raise ValueError(f"索引已有外部修改或缺少校验记录，保留原文：{relative}")
        generated[key] = content
        new_state["files"][key] = {"sha256": sha(content)}
    agents = f"""## 影视项目工作入口

项目 ID：`{expected_id}`；授权作品根目录：`{root}`；创作路线以登记库当前记录为准。
使用当前已核验的影视制作助手插件；读取其总控技能的 `references/project-bootstrap.md`，以及本目录 `09-任务与接续/工作对话/对话索引.md`。
主协调器核对本使用者当前请求或个人默认，仅在已授权范围补齐主要工作区；专业聊天只核对本职关联、报告就绪并等待创作指令，不递归创建其他聊天。
接续先通过 film_context(summary) / film_workspace(read) 取得该项目的最新状态，精确读取本轮所需成果版本；索引只是派生快照。
用户文件、候选、已采用版本、云端手改分别保留；目录存在、聊天已建或文件已保存不代表创作或审核完成。
"""
    entry = f"""# {project['title']} · 项目入口

项目 ID：`{expected_id}`；当前搭建路线：`{project['workflow']['mode']}`。
[工作对话索引](09-任务与接续/工作对话/对话索引.md) · [项目协作规则](AGENTS.md)

实际对话保留在客户端；项目目录保存入口、交接记录、文本、素材及审核资料。该目录结构本身不产生创作成果。

| 目录 | 用途 |
| --- | --- |
| 00-设定与依据 | 需求、世界设定、风格及来源 |
| 01-故事与剧本 | 故事讨论、大纲、剧本、人物小传；小说路线另有小说目录 |
| 02-导演方案 | 导演拍摄建议和特效方案 |
| 03-资产 | 人物、场景、道具、图片原件 |
| 04-提示词与生成任务 | 资产提示词和 AI 视频提示词文本 |
| 05-片段 | 视频原件和低清预览 |
| 06-音乐 | 音频原件、配乐和音效 |
| 07-成片 | 剪辑工程和交付成片 |
| 08-审核记录 | 审核意见与准确版本的采用记录 |
| 09-任务与接续 | 对话索引、搭建状态和交接记录 |
| 10-影视研究与复盘 | 影视分析、来源与复盘 |
| 11-导出 | 已有成果的派生导出 |

最新内容与采用状态从影视工具及准确版本读取，不根据文件修改时间、聊天标题或索引推定。
"""
    for relative, body in ((Path("AGENTS.md"), agents), (Path("项目入口.md"), entry)):
        key = relative.as_posix()
        content, block_hash = merge_block(previous[key], body, state["files"].get(key, {}).get("block_sha256"), relative)
        generated[key] = content
        new_state["files"][key] = {"block_sha256": block_hash}
    generated[STATE.as_posix()] = encoded(new_state)
    changed = [key for key, content in generated.items() if previous[key] != content]
    # Final check catches ordinary concurrent edits before any mutation. This is
    # not a sandbox against a malicious process swapping ancestors concurrently.
    for key, old in previous.items():
        path = root / key
        check_path(path, "file")
        if (path.read_bytes() if path.exists() else None) != old:
            raise ValueError(f"文件发生并发修改，请重新读取：{key}")
    created = []
    for relative in directories:
        path = root / relative
        check_path(path, "directory")
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(relative)
    for key in changed:
        path = root / key
        check_path(path, "file")
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(generated[key])
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        if path.read_bytes() != generated[key]:
            raise OSError(f"写入读回不匹配：{path}")
    return {"project_id": expected_id, "root": str(root), "workspace_revision": workspace["revision"],
            "read_at": current_read_at, "snapshot_read_at": snapshot["read_at"], "created_directories": created,
            "changed_files": changed, "slot_count": len(snapshot["slots"]), "registry_written": False,
            "host_chats_created": False, "observations_are_live": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--expected-project-id", required=True)
    args = parser.parse_args()
    try:
        result = scaffold(args.root, args.expected_project_id)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f"搭建未完成：{exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

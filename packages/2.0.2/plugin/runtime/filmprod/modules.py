"""Read-only bundled professional methods and immutable task execution identity."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from . import __version__

ALIASES = {
    "idea": "idea-explorer", "requirements": "requirements-planner",
    "story": "screenwriter", "novel": "screenwriter", "outline": "screenwriter",
    "character_bio": "screenwriter", "adaptation": "screenwriter",
    "novel-master": "screenwriter", "novel-to-screenplay": "screenwriter",
    "original-screenplay": "screenwriter", "screenwriter": "screenwriter",
    "director": "director-agent",
    "vfx": "vfx-agent", "assets": "seedance-prompt", "asset": "seedance-prompt",
    "asset_prompt": "seedance-prompt", "video_prompt": "seedance-prompt",
    "research": "film-analysis", "style": "film-art-director",
    "art_director": "film-art-director", "art": "film-art-director",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def module_root():
    """No personal skill or old engine fallback, including in source checkouts."""
    package = Path(__file__).resolve().parent
    for candidate in (package.parent.parent / "modules", package.parent / "modules"):
        if (candidate / "manifest.json").is_file():
            return candidate
    raise ValueError("专业模块包不完整：缺少 modules/manifest.json，请重新校验并安装完整发行包")


def checked_path(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or "\\" in relative:
        raise ValueError("模块路径必须是包内相对路径")
    target = (root / relative).resolve()
    if root.resolve() not in target.parents or not target.is_file():
        raise ValueError("模块引用越界或缺失: " + relative)
    return target


def catalog(verify=True):
    root = module_root()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("modules"), list):
        raise ValueError("不支持的专业模块清单")
    entries = []
    for item in manifest["modules"]:
        entry = dict(item)
        if entry["entrypoint"] not in [record["path"] for record in entry["files"]]:
            raise ValueError("专业模块入口未纳入文件锁: " + entry["entrypoint"])
        if verify:
            for record in entry["files"]:
                file = checked_path(root, record["path"])
                if hashlib.sha256(file.read_bytes()).hexdigest() != record["sha256"]:
                    raise ValueError("专业模块文件校验失败: " + record["path"])
        checked_path(root, entry["entrypoint"])
        entry["absolute_entrypoint"] = str(root / entry["entrypoint"])
        entries.append(entry)
    return {"schema_version": 1, "system_version": __version__, "root": str(root),
            "verified": verify, "modules": entries,
            "music_creation": False, "brainstorm_provider": "not_connected", "host_idea_exploration": True, "host_requirements_planning": True}


SCRIPT_ROUTES = {"screenplay", "source_script", "script", "dynamic_script"}
TASK_MODULES = {"idea-explorer": "idea", "requirements-planner": "requirements", "novel": "story", "outline": "story", "character_bio": "story",
                "adaptation": "novel-to-screenplay", "asset": "assets", "asset_prompt": "assets",
                "style": "art_director", "art": "art_director", "film-art-director": "art_director", "source_script": "screenplay", "script": "screenplay",
                "dynamic_script": "screenplay"}


def core_screenplay():
    """Legacy helper resolves to the new bundled method without loading old files."""
    return next(entry for entry in catalog()["modules"] if entry["id"] == "screenwriter")


def resolve(module, workflow_mode=None):
    if workflow_mode not in (None, "novel_only", "novel_to_screen", "screenplay"):
        raise ValueError("未知创作路线")
    requested = module
    if module in SCRIPT_ROUTES:
        if workflow_mode not in {"screenplay", "novel_to_screen"}:
            return {"system_version": __version__, "module": None, "workflow_mode": workflow_mode,
                    "task_module": None, "status": "needs_workflow_selection", "generation_performed": False,
                    "recommended_workflow_mode": "screenplay",
                    "message": "新创作推荐直接剧本；先读取或明确选择项目路线，不改写既有项目。"}
        module = "screenwriter"
    wanted = ALIASES.get(module, module)
    state = catalog()
    entry = next((e for e in state["modules"] if e["id"] == wanted), None)
    if entry is None:
        raise ValueError("该阶段没有独立专业模块: " + str(module))
    task_module = TASK_MODULES.get(requested, requested)
    mode = None
    if wanted == "screenwriter":
        if requested in {"story", "novel", "novel-master"} or (requested in {"outline", "character_bio", "screenwriter"} and workflow_mode == "novel_only"):
            mode = "novel"
        elif requested in {"adaptation", "novel-to-screenplay"} or workflow_mode == "novel_to_screen":
            mode = "adaptation"
        else:
            mode = "original"
        if requested == "novel-master":
            task_module = "story"
        elif requested == "original-screenplay":
            task_module = "screenplay"
        elif requested == "screenwriter":
            task_module = "screenwriter"
    return {"system_version": __version__, "module": entry,
            "task_module": task_module, "workflow_mode": workflow_mode,
            "screenwriting_mode": mode, "preferred_format": "ai_short_drama" if wanted == "screenwriter" else None,
            "load_policy": "read_entrypoint_then_relevant_references",
            "registration": "project_registry_or_explicit_external_idea_library" if wanted in {"idea-explorer", "requirements-planner"} else "current_project_registry_only",
            "project_creation_required": False,
            "creative_execution": "host_model", "generation_performed": False}


def execution_lock(module, workflow_mode=None):
    wanted = ALIASES.get(module, module)
    state = catalog()
    entry = next((e for e in state["modules"] if e["id"] == wanted), None)
    if module in SCRIPT_ROUTES:
        entry = resolve(module, workflow_mode)["module"]
        wanted = entry["id"] if entry else "unselected_script_route"
    # Unified screenwriter is frozen like the other bundled methods; review, editing and music data remain host/core routes.
    value = {"schema_version": 1, "system_version": __version__,
             "module_id": wanted if entry else "core:" + module,
             "workflow_mode": workflow_mode,
             "module_content_version": entry.get("content_version") if entry else __version__,
             "module_sha256": digest({k: v for k, v in entry.items() if k != "absolute_entrypoint"}) if entry else None}
    value["lock_sha256"] = digest(value)
    return value


def execution_status(task):
    frozen = task.get("execution_lock")
    if not frozen:
        return {"compatible": False, "reason": "legacy_task_version_unknown", "required": None,
                "message": "旧任务未记录方法版本；请在创建它的旧运行环境接续，或结束旧任务后明确新建任务。"}
    try:
        current = execution_lock(task["module"], frozen.get("workflow_mode"))
    except (OSError, ValueError, KeyError) as exc:
        return {"compatible": False, "reason": "methods_unavailable", "required": frozen,
                "current": None, "message": "任务草稿可只读恢复；专业方法无法核验，请修复对应版本安装。", "error": str(exc)}
    compatible = frozen == current
    return {"compatible": compatible, "reason": None if compatible else "execution_version_mismatch",
            "required": frozen, "current": current,
            "message": "版本相符" if compatible else "任务规则已冻结；请使用记录的旧运行版本接续，不会自动改绑新规则。"}


def require_execution(task):
    status = execution_status(task)
    if not status["compatible"]:
        raise ValueError(status["message"])
    return status

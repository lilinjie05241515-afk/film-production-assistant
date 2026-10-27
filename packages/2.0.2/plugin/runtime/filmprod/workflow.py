"""Read-only workflow advice. Existing content never selects or completes a route."""
from copy import deepcopy


MODES = {"novel_only", "novel_to_screen", "screenplay"}
OUTLINE_ORDERS = {"before_novel", "after_novel"}
GLOBAL_STYLE_SCOPE = "project/style"
STYLE_MODULES = {"screenwriter", "screenplay", "novel-to-screenplay", "director", "director-agent", "vfx", "vfx-agent", "assets", "seedance-prompt", "video_prompt"}
STYLE_CATEGORIES = {"source_script", "script", "director", "vfx", "asset", "video_prompt"}
STAGES = {
    "idea": {"label": "灵感探索与创意碰撞", "category": "idea"},
    "requirements": {"label": "需求澄清与执行规划", "category": "requirements"},
    "novel": {"label": "小说", "category": "novel"},
    "outline": {"label": "大纲", "category": "outline"},
    "character_bio": {"label": "人物小传", "category": "character_bio"},
    "source_script": {"label": "源剧本（底稿）", "category": "source_script"},
    "style": {"label": "全剧风格", "category": "style"},
    "dynamic_script": {"label": "剧本创作与修订", "category": "script"},
    "director": {"label": "导演", "category": "director"},
    "vfx": {"label": "特效", "category": "vfx"},
    "asset": {"label": "资产提示词", "category": "asset"},
    "video_prompt": {"label": "AI 视频提示词", "category": "video_prompt"},
    "research": {"label": "影视研究", "category": "research"},
}


def route(mode, outline_order="after_novel"):
    if mode == "novel_only":
        return ["novel"], ["outline", "character_bio", "style", "research"]
    if mode == "novel_to_screen":
        early = ["outline", "novel", "style"] if outline_order == "before_novel" else ["novel", "style", "outline"]
        return early + ["character_bio", "dynamic_script", "director", "vfx", "asset", "video_prompt"], ["research"]
    if mode == "screenplay":
        return ["dynamic_script", "director", "vfx", "asset", "video_prompt"], ["outline", "character_bio", "source_script", "style", "research"]
    return [], []


def ref(artifact):
    return {"artifact_id": artifact["artifact_id"], "version": artifact["version"]}


def stage_key(artifact):
    category = artifact.get("category")
    explicit = artifact.get("metadata", {}).get("workflow_stage")
    if explicit:
        return explicit if isinstance(explicit, str) and explicit in STAGES and STAGES[explicit]["category"] == category else None
    if artifact.get("kind") == "character":
        return None  # Keep its legacy outline pointer, without asserting its stage.
    if category == "script":
        return None  # A legacy screenplay is not evidence of a dynamic script.
    return category if category in STAGES else None


def validate_stage(category, metadata):
    stage = metadata.get("workflow_stage")
    if stage is not None and (not isinstance(stage, str) or stage not in STAGES or STAGES[stage]["category"] != category):
        raise ValueError("metadata.workflow_stage 与成果 category 不匹配；剧本底稿用 source_script，动态稿用 script/dynamic_script")


def global_style(approved, pending):
    chosen = next((a for a in approved if a["kind"] == "style_bible" and a.get("category") == "style" and a["scope"] == GLOBAL_STYLE_SCOPE), None)
    candidates = [ref(a) for a in pending if a["kind"] == "style_bible" and a.get("category") == "style" and a["scope"] == GLOBAL_STYLE_SCOPE]
    status = ("needs_review" if chosen.get("approval_status") == "needs_review" else "approved") if chosen else ("candidate" if candidates else "missing")
    return {"status": status, "approved_ref": ref(chosen) if chosen else None, "pending_refs": candidates, "scope": GLOBAL_STYLE_SCOPE, "semantic_compliance": "not_assessed"}


def workflow_view(project, approved, pending):
    saved = (project or {}).get("workflow") or {}
    mode = saved.get("mode", "unset")
    outline_order = saved.get("outline_order") if mode != "unset" else None
    keys, optional = route(mode, outline_order)
    definitions = {
        "modes": [{"key": m, "label": label, "stage_keys": route(m)[0], "optional_stage_keys": route(m)[1]} for m, label in (("novel_only", "只写小说"), ("novel_to_screen", "小说再做影视"), ("screenplay", "直接写剧本"))],
        "stages": [{"key": key, **value} for key, value in STAGES.items()],
        "outline_orders": [{"key": "before_novel", "label": "先大纲后小说"}, {"key": "after_novel", "label": "先小说后大纲"}],
    }
    approved_by = {key: [a for a in approved if stage_key(a) == key] for key in STAGES}
    pending_by = {key: [a for a in pending if stage_key(a) == key] for key in STAGES}
    dependencies = {
        "idea": [], "requirements": [],
        "novel": ["outline"] if mode == "novel_to_screen" and outline_order == "before_novel" else [],
        "outline": ["novel"] if mode == "novel_to_screen" and outline_order != "before_novel" else [],
        "style": [] if mode == "screenplay" else ["novel"],
        "character_bio": [] if mode == "screenplay" else (["novel"] if mode == "novel_only" else ["novel", "outline", "style"]),
        "dynamic_script": [] if mode == "screenplay" else ["novel", "outline", "character_bio", "style"],
        "director": ["dynamic_script", "style"],
        "vfx": ["dynamic_script", "director", "style"],
        "asset": ([] if mode == "screenplay" else ["novel", "outline"]) + ["character_bio", "dynamic_script", "director", "vfx", "style"],
        "video_prompt": ["dynamic_script", "director", "vfx", "character_bio", "style"],
        "research": [] if mode == "screenplay" else ["novel"],
    }
    optional_dependencies = {
        "requirements": ["idea"],
        "source_script": ["requirements"],
        "outline": ["source_script"] if mode == "screenplay" else [],
        "research": ["source_script", "dynamic_script"] if mode == "screenplay" else [],
        "novel": ["outline", "character_bio"] if mode == "novel_only" else [],
        "style": ["research", "source_script", "dynamic_script"] if mode == "screenplay" else ["research"],
        "character_bio": ["outline", "novel", "source_script", "style"] if mode == "screenplay" else (["outline", "style"] if mode == "novel_only" else ["source_script"]),
        "dynamic_script": ["novel", "outline", "source_script", "character_bio", "style"] if mode == "screenplay" else ["source_script"],
        "asset": ["novel", "outline", "source_script"] if mode == "screenplay" else ["source_script"],
        "video_prompt": ["asset"],
    }

    for key in STAGES:
        if key not in {'idea', 'requirements'} and 'requirements' not in optional_dependencies.get(key, []):
            optional_dependencies.setdefault(key, []).append('requirements')

    def stage(key, is_optional):
        passed = approved_by[key]
        candidates = pending_by[key]
        ready = [a for a in passed if a.get("approval_status") != "needs_review"]
        review = [a for a in passed if a.get("approval_status") == "needs_review"]
        approved_ids = {a["artifact_id"] for a in passed}
        ids = approved_ids | {a["artifact_id"] for a in candidates}
        if not ids:
            status = "empty"
        elif review:
            status = "needs_review"
        elif ready and candidates:
            status = "mixed"
        elif ready:
            status = "approved"
        else:
            status = "candidate"
        suggestions = []
        present_optional = [upstream for upstream in optional_dependencies.get(key, []) if approved_by[upstream] or pending_by[upstream]]
        for upstream in dependencies.get(key, []) + present_optional:
            available = [a for a in approved_by[upstream] if a.get("approval_status") != "needs_review"]
            needs_review = [a for a in approved_by[upstream] if a.get("approval_status") == "needs_review"]
            pending_inputs = pending_by[upstream]
            suggestions.append({"stage_key": upstream, "label": STAGES[upstream]["label"], "optional": upstream in present_optional, "refs": [ref(a) for a in available], "candidate_refs": [ref(a) for a in pending_inputs], "review_refs": [ref(a) for a in needs_review], "status": "needs_review" if needs_review else ("available" if available else ("candidate" if pending_inputs else "missing")), "note": "refs 仅列已通过且无需复核的精确版本；待审与需复核引用单列，建议不会自动建立依赖或阻止跳阶段。"})
        return {
            "key": key, **STAGES[key], "optional": is_optional, "status": status,
            "counts": {"segments": len(ids), "approved": len(ready), "needs_review": len(review), "pending_candidates": len(candidates), "initial_drafts": sum(a["artifact_id"] not in approved_ids for a in candidates)},
            "approved_refs": [ref(a) for a in ready], "review_refs": [ref(a) for a in review], "candidate_refs": [ref(a) for a in candidates],
            "dependency_suggestions": suggestions, "completion_status": "unknown", "scope_status": "not_declared",
            "status_note": "状态只描述已有分段；已有条目均通过不代表全阶段完成。",
        }

    unclassified = []
    seen = set()
    outside_route = []
    for a in approved + pending:
        identity = (a["artifact_id"], a["version"])
        if identity in seen:
            continue
        seen.add(identity)
        key = stage_key(a)
        if key is None:
            reason = "no_matching_workflow_stage"
            if not a.get("metadata", {}).get("workflow_stage"):
                if a.get("category") == "script":
                    reason = "script_stage_not_declared"
                elif a["kind"] == "character":
                    reason = "legacy_character_stage_not_declared"
            unclassified.append({**ref(a), "kind": a["kind"], "category": a.get("category"), "scope": a["scope"], "reason": reason})
        elif key not in keys + optional + ["idea", "requirements"]:
            outside_route.append({**ref(a), "stage_key": key})
    return {
        "mode": mode, "recommended_mode": "screenplay", "screenwriting_focus": "ai_short_drama", "outline_order": outline_order, "revision": saved.get("revision", 0), "updated_at": saved.get("updated_at"),
        "preproduction_stages": [stage("idea", True), stage("requirements", True)],
        "preproduction_required": False, "execution_authorization_inferred": False,
        "definitions": deepcopy(definitions), "stages": [stage(key, False) for key in keys], "optional_stages": [stage(key, True) for key in optional],
        "unclassified": unclassified, "outside_route": outside_route, "global_style": global_style(approved, pending), "advisory_only": True,
        "completion_status": "unknown", "scope_status": "not_declared",
    }

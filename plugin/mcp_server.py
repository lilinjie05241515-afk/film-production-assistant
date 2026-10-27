"""Dependency-free MCP stdio adapter; host model remains the creative engine.

One JSON-RPC object per line. Nothing except protocol messages goes to stdout.
Installed releases prefer their bundled runtime; source is a development fallback.
"""
from __future__ import annotations
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYSTEM = HERE if (HERE / "runtime/filmprod").is_dir() else HERE.parent
sys.path.insert(0, str(SYSTEM))
if (HERE / "runtime/filmprod").is_dir():
    sys.path.insert(0, str(HERE / "runtime"))
from filmprod import __version__ as VERSION
UI_URI = "ui://film-production-agent/board"
ROOT_SCHEMA = {"type": "string", "description": "Explicit absolute project directory; not the system directory"}
UI_META = {"ui": {"resourceUri": UI_URI}, "openai/ui": {"entrypoints": [{"type": "global"}, {"type": "thread"}]}}

def tool(name, description, properties, required=(), readonly=True, ui=False):
    value = {"name": name, "description": description,
             "inputSchema": {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False},
             "annotations": {"readOnlyHint": readonly, "destructiveHint": not readonly, "idempotentHint": True, "openWorldHint": False}}
    if ui:
        value["_meta"] = UI_META
    return value

TOOLS = [
    tool("film_modules", "Verify and resolve bundled methods. Script stages require explicit workflow_mode. idea/requirements can begin without creating a film project: existing projects use Registry planning.record/read; unprojected records use the bundled helper only with an explicit external library root. Read entrypoint and references. No old personal skill directory is required.", {"module": {"type": "string"}, "workflow_mode": {"type": "string", "enum": ["novel_only", "novel_to_screen", "screenplay"]}}),
    tool("film_board", "Open the film project board. Supply the real current thread_id/client_project_id when known; bound chat takes priority. No global last project and no implicit sample project.", {"root": ROOT_SCHEMA, "thread_id": {"type": "string"}, "client_project_id": {"type": "string"}}, ui=True),
    tool("film_projects", "List explicitly registered local film projects or perform register/create/relink/bind/unbind/forget. Never scans folders or creates host chats. Write actions require op_id. list/resolve/outcome are read-only; existing chat bindings take priority over client-project bindings.",
         {"action": {"type": "string"}, "payload": {"type": "object"}}, ["action"], readonly=False),
    tool("film_brainstorm", "Read the unconnected brainstorm interface or prepare an exact-version input handoff. interface needs no project; prepare requires root and payload.expected_project_id plus topic. Read-only: no generation, writes, tasks, chat creation or approval. Prepared is not generated; provider_status remains not_connected and can_generate=false.",
         {"root": ROOT_SCHEMA, "action": {"type": "string", "enum": ["interface", "prepare"]}, "payload": {"type": "object"}}, ["action"]),
    tool("film_media", "Manage already-made local media. Video actions choose/import/preview retain the first-12-second low-resolution preview. Audio actions choose_audio/import_audio/preview_audio register existing audio and offer a low-bitrate first-20-second listening preview, never generate music. Image actions choose_image/import_image/preview_image support bounded static PNG/JPEG/WebP; import_image requires op_id/media_id/path/expected_project_id, with title and asset_type in metadata. preview_image reads registered originals and may write only disposable 480/960-edge preview caches, not registry data. Image/video/audio binary derivatives return only through UI-only _meta.media_preview, never content or structuredContent. original resolves registered media_id inside the current project and verifies SHA-256 before returning a local path for the host to open; no arbitrary path reads. Never generates creative media, uploads originals or opens files itself.",
         {"root": ROOT_SCHEMA, "action": {"type": "string"}, "payload": {"type": "object"}}, ["root", "action"], readonly=False),
    tool("film_snapshot", "Read a project registry, exact approved versions, candidates, dependencies, sync observations and its explicitly selected creative workflow. AI video prompts use independent video_prompt content and masters; legacy prompt remains asset. Unclassified legacy scripts are not inferred as dynamic scripts.", {"root": ROOT_SCHEMA}, ["root"]),
    tool("film_resume", "Restore a task's frozen input and persisted checkpoint in a fresh context.", {"root": ROOT_SCHEMA, "task_id": {"type": "string"}}, ["root", "task_id"]),
    tool("film_history", "Read every immutable version of one artifact in ascending version order.", {"root": ROOT_SCHEMA, "artifact_id": {"type": "string"}}, ["root", "artifact_id"]),
    tool("film_health", "Inspect this local stdio runtime and an optional project without networking or creating files.", {"root": ROOT_SCHEMA}),
    tool("film_export", "Generate Chinese reading copies and handoff packages from the explicit project registry; does not change canonical versions.", {"root": ROOT_SCHEMA}, ["root"], readonly=False),
    tool("film_render", "Render a fully bound final version using local media and a local renderer. No paid API. Payload requires artifact_id, version, op_id and preview. May take longer than UI timeout: preserve the same request and operation ID for recovery; never claim completion until result is read back.",
         {"root": ROOT_SCHEMA, "payload": {"type": "object"}}, ["root", "payload"], readonly=False),
    tool("film_pages_import", "Import an already obtained complete host Pages read result into local version snapshots. Never fetches or writes cloud content. Preserve observed_at and actual read view/selection; truncated or partial reads are rejected.",
         {"root": ROOT_SCHEMA, "observation": {"type": "object"}, "op_prefix": {"type": "string"}}, ["root", "observation", "op_prefix"], readonly=False),
    tool("film_dispatch", "Apply an explicitly requested registry action. Write payloads require unique op_id. board.order.set saves project category display order with expected_project_id, group (content_categories/asset_types/video_categories), a complete unique order of IDs and base_revision; it does not reorder story content or workflow stages. trash.set requires expected_project_id, target_type (artifact/media), target_id, version only for artifact, expected_sha256, base_revision and deleted boolean. It moves an exact registered version/item to a reversible logical recycle bin or restores visibility; no file is physically deleted, no disk space is reclaimed, and existing approvals/dependencies remain intact. Exclude deleted entries from ordinary new-work selections while preserving explicitly resolved existing dependencies. Never delete cloud Pages or arbitrary filesystem paths through this action. presentation.set manages exact-version display title/category/archive with expected_project_id, artifact_id, version, expected_sha256 and base_revision; never changes content, approval or dependencies. planning.record incrementally saves discussions; planning.read is read-only. media.classify requires expected_project_id/media_id/expected_sha256/asset_type and base_revision (initial 0); changes only management classification, never original bytes or approval. Asset metadata.asset_type accepts character/scene/prop/other/unclassified. media.update requires op_id/expected_project_id/media_id/expected_sha256/base_revision/title and asset_type for images or video_category for videos (take/clip/final/unclassified); base_revision is the shared classification_revision also used by media.classify. It only changes display title and explicit management classification after checking current original bytes; it never renames files, edits bytes, approves assets or changes creative records. document.export is read-only and requires expected_project_id/artifact_id/exact version; returns UTF-8 Markdown data_base64/sha256 without changing text or writing files. document.save requires op_id/expected_project_id/artifact_id/exact version/expected_sha256; writes a derived UTF-8 .md copy only inside the explicit project 11-导出/Markdown directory, without opening the registry writable or changing content/approvals/events. It accepts no destination path. Returns saved_verified/local_path/export_dir/project_root/sha256/size_bytes after actual file readback, without content/base64. Exact existing bytes may be reused; different existing bytes or links are never overwritten. Its op_id is a response correlation token, not a registry transaction or approval. Structured records cannot be flattened into document text. Planning records do not approve content or authorize execution. project.workflow.set selects an explicit route without creating chats or approving content. Save AI video prompt text as kind video_prompt; legacy prompt remains asset. Does not generate media, access Pages or publish. Do not invent human adoption decisions.",
         {"root": ROOT_SCHEMA, "action": {"type": "string"}, "payload": {"type": "object"}}, ["root", "action", "payload"], readonly=False),
]

from filmprod.action_schemas import tool_definitions, validate as validate_creative_schema
CREATIVE_TOOLS = tool_definitions(ROOT_SCHEMA)
CREATIVE_TOOL_NAMES = {definition["name"] for definition in CREATIVE_TOOLS}
TOOLS.extend(CREATIVE_TOOLS)

from filmprod.workflow_tools1110 import tool_definitions as workflow_tool_definitions, READ_ACTIONS as WORKFLOW_READ_ACTIONS
WORKFLOW_TOOLS = workflow_tool_definitions(ROOT_SCHEMA)
WORKFLOW_TOOL_NAMES = {definition["name"] for definition in WORKFLOW_TOOLS}
TOOLS.extend(WORKFLOW_TOOLS)

# Existing creative tools remain callable by work-chat agents only.
# MCP Apps hosts MUST reject app calls to tools without app visibility.
for definition in TOOLS:
    definition.setdefault("_meta", {}).setdefault("ui", {})["visibility"] = ["model"]
TOOLS.append(tool("film_board_manage",
    "Board-only management gateway: read exact project state and manage registered files. "
    "Only explicit exact-version board.confirm, board.style.select and board.asset.select may record user decisions. No creative tasks, edits, workflow execution, messages, chat creation or rendering.",
    {"root": ROOT_SCHEMA, "action": {"type": "string"}, "payload": {"type": "object"}},
    ["action"], readonly=False))
TOOLS[-1]["_meta"] = {"ui": {"visibility": ["app"]}}


def checked_project_root(root_text, payload=None, allow_init=False):
    """Check a path and its catalog identity without opening a writable Registry."""
    if not root_text or not isinstance(root_text, str):
        raise ValueError("explicit project root required")
    root = Path(root_text)
    if not root.is_absolute() or root.resolve() == SYSTEM.resolve() or SYSTEM.resolve() in root.resolve().parents:
        raise ValueError("root must be an absolute work directory separate from the system")
    database = root / ".project/registry.sqlite3"
    if not allow_init and not database.is_file():
        raise ValueError("project registry not found; initialize the explicit project first")
    if database.is_file():
        from filmprod.projects import catalog_path, project_identity
        actual = project_identity(root)
        expected = (payload or {}).get("expected_project_id")
        if expected is not None and actual["project_id"] != expected:
            raise ValueError("project identity changed since the form opened; refusing this root")
        registered_path = catalog_path()
        if registered_path.is_file():
            connection = sqlite3.connect(registered_path.as_uri() + "?mode=ro", uri=True)
            try:
                for registered_id, registered_root in connection.execute("SELECT project_id,root FROM projects"):
                    if Path(registered_root).resolve() == root.resolve() and registered_id != actual["project_id"]:
                        raise ValueError("registered root now contains a different project identity; explicitly relink before proceeding")
            finally:
                connection.close()
    return root

def call_tool(name, arguments, default_root):
    from filmprod.core import Registry
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    definition = next((t for t in TOOLS if t["name"] == name), None)
    if definition is None:
        raise ValueError("unknown tool")
    schema = definition["inputSchema"]
    if name == "film_board_manage":
        from filmprod.board_gateway1150 import call_board
        return call_board(arguments, default_root, checked_project_root)
    if name in WORKFLOW_TOOL_NAMES:
        validate_creative_schema(arguments, schema)
        from filmprod.workflow_tools1110 import dispatch_arguments
        action, payload = dispatch_arguments(name, arguments)
        root = checked_project_root(arguments["root"], payload)
        registry = Registry.open_readonly(root) if action in WORKFLOW_READ_ACTIONS else Registry(root)
        try:
            result = registry.dispatch(action, payload)
        finally:
            registry.close()
        result = {**result, "project_root": str(root.resolve())}
        if "op_id" in payload:
            result["op_id"] = payload["op_id"]
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, sort_keys=True)}], "structuredContent": result}
    if name in CREATIVE_TOOL_NAMES:
        # New contracts are strict and validated before touching a project.
        # Legacy schemas/returns remain unchanged for existing UI and clients.
        validate_creative_schema(arguments, schema)
        from filmprod.action_schemas import action_help, creative_dispatch
        if name == "film_action_help":
            result = action_help(arguments["action"])
        else:
            from filmprod.efficient import read_context, compact_result
            if name == "film_context":
                payload = {key: value for key, value in arguments.items() if key != "root"}
                root = checked_project_root(arguments["root"], payload)
                registry = Registry.open_readonly(root)
                try:
                    result = read_context(registry, payload)
                finally:
                    registry.close()
            else:
                action, payload = creative_dispatch(name, arguments)
                root = checked_project_root(arguments["root"], payload)
                registry = Registry(root)
                try:
                    result = compact_result(action, registry.dispatch(action, payload))
                    result = {**result, "op_id": payload["op_id"], "project_id": payload["expected_project_id"], "project_root": str(root.resolve())}
                finally:
                    registry.close()
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, sort_keys=True)}], "structuredContent": result}
    if any(k not in arguments for k in schema["required"]):
        raise ValueError("missing required arguments")
    if set(arguments) - set(schema["properties"]):
        raise ValueError("unknown arguments")
    for key, value in arguments.items():
        expected = schema["properties"][key]["type"]
        if expected == "string" and not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        if expected == "object" and not isinstance(value, dict):
            raise ValueError(f"{key} must be an object")
    if name == "film_brainstorm" or (name == "film_dispatch" and arguments.get("action") in ("brainstorm.interface", "brainstorm.prepare")):
        from filmprod.brainstorm import interface, prepare
        action, payload = arguments["action"], arguments.get("payload", {})
        if name == "film_dispatch":
            action = action.removeprefix("brainstorm.")
        if action == "interface":
            if payload:
                raise ValueError("interface is a static read and does not accept a payload")
            result = interface()
        elif action == "prepare":
            expected = payload.get("expected_project_id")
            if not isinstance(expected, str) or not expected.strip():
                raise ValueError("prepare requires explicit payload.expected_project_id")
            root = checked_project_root(arguments.get("root"), payload)
            result = prepare(root, payload)
        else:
            raise ValueError("brainstorm action must be interface or prepare")
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, sort_keys=True)}], "structuredContent": result}
    if name == "film_modules":
        from filmprod.modules import catalog, resolve
        result = resolve(arguments["module"], arguments.get("workflow_mode")) if arguments.get("module") else catalog()
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, sort_keys=True)}], "structuredContent": result}
    if name == "film_dispatch" and arguments.get("action", "").startswith("conversation."):
        # The legacy dispatcher must enforce the same contract before opening a
        # writable Registry. It cannot bypass the typed conversation gateway.
        from filmprod.conversations1170 import validate_conversation_payload
        validate_conversation_payload(arguments["action"], arguments["payload"])
    catalog_state = None
    if name in ("film_projects", "film_board"):
        from filmprod.projects import ProjectCatalog
        from filmprod.board_gateway1150 import catalog_read, response as board_response
        context = {k: arguments[k] for k in ("thread_id", "client_project_id") if arguments.get(k)}
        if name == "film_projects":
            action, payload = arguments["action"], arguments.get("payload", {})
            if action in ("list", "resolve", "outcome"):
                return board_response(catalog_read(payload, action))
            catalog = ProjectCatalog()
            try:
                return board_response(catalog.dispatch(action, payload))
            finally:
                catalog.close()
        catalog_state = catalog_read(context)
    if name == "film_health":
        root = arguments.get("root")
        from filmprod.modules import catalog
        try:
            modules = catalog()
            module_health = {"verified": True, "count": len(modules["modules"]), "manifest": str(Path(modules["root"]) / "manifest.json")}
        except (OSError, ValueError, KeyError) as exc:
            module_health = {"verified": False, "error": str(exc)}
        result = {"modules": module_health, "server": "film-production-agent", "version": VERSION, "transport": "stdio",
                  "system_root": str(SYSTEM), "ui_uri": UI_URI, "ui_resource_present": (HERE / "ui/board.html").is_file(),
                  "runtime_root": str(HERE / "runtime") if (HERE / "runtime/filmprod").is_dir() else str(SYSTEM),
                  "runtime_isolated": (HERE / "runtime/filmprod").is_dir(),
                  "http_listener": False, "external_model_api": False, "pages_access": "host_tools_only",
                  "project_root": root, "project_registered": (Path(root) / ".project/registry.sqlite3").is_file() if root else None}
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, sort_keys=True)}], "structuredContent": result}
    root_text = arguments.get("root") or default_root
    if name == "film_board" and not root_text:
        selected = catalog_state.get("resolved_project")
        if selected and selected.get("available"):
            root_text = selected["root"]
        else:
            result = {"project": None, "empty_state": True, "catalog": catalog_state,
                      "host_context": catalog_state["host_context"], "project_root": None,
                      "message": "选择已登记影视项目，或明确新建/关联已有项目。"}
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, sort_keys=True)}], "structuredContent": result}
    is_init = name == "film_dispatch" and arguments.get("action") == "project.init"
    root = checked_project_root(root_text, arguments.get("payload", {}), allow_init=is_init)
    registry_readonly = name in ("film_snapshot", "film_board", "film_history", "film_resume") or (name == "film_dispatch" and arguments.get("action") in ("previs.read", "previs.chunk", "planning.read", "document.export", "document.save", "context.read", *WORKFLOW_READ_ACTIONS)) or (name == "film_media" and arguments.get("action") in ("choose", "choose_image", "choose_audio", "preview", "preview_image", "preview_audio", "original"))
    registry = Registry.open_readonly(root) if registry_readonly else Registry(root)
    try:
        if name in ("film_snapshot", "film_board"):
            result = registry.snapshot()
            result = {**result, "project_root": str(root)}
            if name == "film_board":
                result.update(catalog=catalog_state, host_context=catalog_state["host_context"])
        elif name == "film_media":
            from filmprod.media120 import media_action
            result = media_action(registry, arguments["action"], arguments.get("payload", {}))
        elif name == "film_resume":
            result = registry.dispatch("task.resume", {"task_id": arguments["task_id"]})
        elif name == "film_history":
            result = registry.dispatch("artifact.history", {"artifact_id": arguments["artifact_id"]})
        elif name == "film_export":
            from filmprod.export import export_project
            result = export_project(registry)
        elif name == "film_render":
            from filmprod.render import render_final, render_operation_outcome
            if type(arguments["payload"].get("preview")) is not bool:
                error = ValueError("render payload must explicitly set preview to true or false")
                error.operation_outcome = render_operation_outcome(registry, arguments["payload"])
                raise error
            result = render_final(registry, arguments["payload"])
        elif name == "film_pages_import":
            from filmprod.pages_bridge import import_observation
            if not arguments["op_prefix"].strip():
                raise ValueError("op_prefix must not be empty")
            result = import_observation(registry, arguments["observation"], arguments["op_prefix"])
        else:
            if not isinstance(arguments.get("payload"), dict):
                raise ValueError("payload must be an object")
            result = registry.dispatch(arguments["action"], arguments["payload"])
    finally:
        registry.close()
    meta = None
    if name == "film_media" and arguments["action"] in ("preview", "preview_image", "preview_audio"):
        meta = {"media_preview": result}
        result = {k: v for k, v in result.items() if k not in ("thumbnail_data_uri", "preview_data_uri")}
    response = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, sort_keys=True)}], "structuredContent": result}
    if meta is not None:
        response["_meta"] = meta
    return response

def handle(request, default_root):
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    request_id = request.get("id")
    if "id" not in request:
        return None
    method, params = request.get("method"), request.get("params") or {}
    response = {"jsonrpc": "2.0", "id": request_id}
    try:
        if method == "initialize":
            supported = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"}
            version = params.get("protocolVersion", "2025-11-25")
            result = {"protocolVersion": version if version in supported else "2025-11-25",
                      "capabilities": {"tools": {}, "resources": {}, "extensions": {"io.modelcontextprotocol/ui": {}}},
                      "serverInfo": {"name": "film-production-agent", "version": VERSION},
                      "instructions": "Read explicit project state, chosen workflow and exact approved global style before work. The board shows project overview, creative stages and object assets. Explicit confirmation and selection use its narrow board-only endpoints with exact identity, version, revision and op_id checks. Creative tools are model-only and run in work chats; never treat a board refresh or file organization as execution authorization. In an enabled hierarchical conversation workflow, controllers coordinate while topic chats discuss or execute; read film_conversations and reconcile pending host requests before creating or sending. This server never runs a background chat scheduler. Research is not automatic style adoption. AI video prompt text uses video_prompt; its three-section content is separate from project metadata. Actual video and music generation providers are not connected. Use host Pages tools for cloud drafts; this adapter has no private Pages access."}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "resources/list":
            result = {"resources": [{"uri": UI_URI, "name": "影视创作看板", "mimeType": "text/html;profile=mcp-app"}]}
        elif method == "resources/templates/list":
            result = {"resourceTemplates": []}
        elif method == "resources/read":
            if params.get("uri") != UI_URI:
                raise ValueError("unknown resource")
            result = {"contents": [{"uri": UI_URI, "mimeType": "text/html;profile=mcp-app", "text": (HERE / "ui" / "board.html").read_text(encoding="utf-8"),
                                   "_meta": {"ui": {"csp": {"connectDomains": [], "resourceDomains": ["data:", "blob:"]}}}}]}
        elif method == "tools/call":
            try:
                result = call_tool(params.get("name"), params.get("arguments", {}), default_root)
            except Exception as exc:
                error = {"type": type(exc).__name__, "message": str(exc)}
                name = params.get("name")
                action = params.get("arguments", {}).get("action")
                media_import = ((name == "film_media" and action in {"import", "import_image", "import_audio"}) or
                                (name == "film_board_manage" and action in {"media.import", "media.import_image", "media.import_audio"}))
                if name == "film_render" or media_import:
                    outcome = getattr(exc, "operation_outcome", "unknown")
                    error["operation_outcome"] = outcome if outcome in {"no_write", "failed_before_commit", "unknown", "resumable"} else "unknown"
                result = {"isError": True, "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                          "structuredContent": {"error": error}}
        else:
            response["error"] = {"code": -32601, "message": "Method not found"}
            return response
        response["result"] = result
    except (ValueError, TypeError, OSError, AttributeError) as exc:
        response["error"] = {"code": -32602, "message": str(exc)}
    return response

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=os.environ.get("FILMPROD_PROJECT"))
    args = parser.parse_args()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            response = handle(json.loads(line), args.root)
        except json.JSONDecodeError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main()

"""Shared, non-executing action contracts and compact creative-work MCP schemas.

Legacy film_dispatch remains compatible. These schemas govern only new tools;
the registry still owns transaction, version, authority and filesystem checks.
"""
from copy import deepcopy
import re
from .core import TEXT_FILE_KINDS
from .cloud1120 import cloud_update_schema


def obj(properties, required=(), **extra):
    return dict(type="object", properties=properties, required=list(required), additionalProperties=False, **extra)


TEXT = {"type": "string", "minLength": 1}
STRING = {"type": "string"}
HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
VERSION = {"type": "integer", "minimum": 1}
BASE_VERSION = {"type": "integer", "minimum": 0}
ITEMS = {"type": "array", "items": {"type": ["string", "object"]}}
METADATA = {"type": "object", "description": "Artifact metadata; title, chapter, category and workflow_stage as applicable. Never approval evidence."}
REF = obj({"artifact_id": TEXT, "version": VERSION}, ("artifact_id", "version"))
REFS = {"type": "array", "items": REF}
WRITE = {"op_id": dict(TEXT, description="Unique operation ID. Retry the same operation with this ID and identical arguments."),
         "expected_project_id": dict(TEXT, description="Project identity returned by an explicit registered project lookup.")}
FILE = {"source_path": dict(TEXT, description="Relative UTF-8 source file within this explicit project, outside .project. No absolute paths, traversal, links or reparse points."),
        "expected_file_sha256": dict(HASH, description="SHA-256 of the actual source file bytes, including BOM and original newlines.")}
TASK = {**WRITE, "task_id": TEXT, "title": TEXT, "module": dict(TEXT, description="Use task_module returned by film_modules for the current stage."),
        "scope": TEXT, "inputs": REFS, "must_keep": ITEMS, "allowed_changes": ITEMS,
        "requirements": ITEMS, "artifact_id": TEXT, "thread_id": TEXT}
CHECKPOINT = {**WRITE, "task_id": TEXT, "draft": TEXT, "completed": ITEMS,
              "decisions": ITEMS, "unresolved": ITEMS, "next_step": TEXT}
ARTIFACT = {**WRITE, "artifact_id": TEXT, "kind": TEXT, "scope": TEXT, "content": {},
            "base_version": BASE_VERSION, "deps": REFS, "metadata": METADATA, "cloud_update": cloud_update_schema(),
            "use_current_style": {"type": "boolean", "description": "Request automatic current-style binding. Only a newly automatic cyclic style edge becomes a frozen full reference; explicit dependencies are never removed."}}
SUBMIT = {**WRITE, "task_id": TEXT, "artifact_id": TEXT, "kind": TEXT, "content": {},
          "base_version": BASE_VERSION, "metadata": METADATA, "cloud_update": cloud_update_schema()}
SUBMIT_CHECKPOINT = {k: v for k, v in SUBMIT.items() if k != "content"}
SUBMIT_CHECKPOINT.update(checkpoint_id=TEXT, expected_draft_sha256=HASH)

AUTH = obj({"source": {"type": "string", "enum": ["conversation", "panel-click"]}, "quote": TEXT,
            "artifact_id": TEXT, "version": VERSION, "scope": TEXT,
            "observed_at": dict(TEXT, description="Actual evidence observation time, ISO 8601 with timezone."),
            "thread_id": TEXT, "actor_identity": TEXT, "real_user_id": {"type": ["string", "null"]}},
           ("source", "quote", "artifact_id", "version", "scope", "observed_at"),
           oneOf=[{"properties": {"source": {"const": "conversation"}}, "required": ["thread_id"]},
                  {"properties": {"source": {"const": "panel-click"}}, "required": ["actor_identity"]}])
APPROVAL = {**WRITE, "artifact_id": TEXT, "version": VERSION, "scope": TEXT, "evidence": TEXT,
            "actor": TEXT, "synthetic": {"type": "boolean"}, "base_master_version": BASE_VERSION,
            "user_authorization": AUTH}

ACTION_SCHEMAS = {
    "task.create": obj(TASK, (*WRITE, "task_id", "title", "module", "scope", "inputs", "must_keep", "allowed_changes", "requirements")),
    "task.checkpoint": obj(CHECKPOINT, tuple(CHECKPOINT)),
    "task.checkpoint_file": obj({**{k: v for k, v in CHECKPOINT.items() if k != "draft"}, **FILE}, (*WRITE, "task_id", *FILE, "completed", "decisions", "unresolved", "next_step")),
    "task.submit": obj(SUBMIT, (*WRITE, "task_id", "artifact_id", "kind", "content", "base_version")),
    "task.submit_checkpoint": obj(SUBMIT_CHECKPOINT, (*WRITE, "task_id", "artifact_id", "kind", "base_version", "checkpoint_id", "expected_draft_sha256")),
    "artifact.save": obj(ARTIFACT, (*WRITE, "artifact_id", "kind", "scope", "content", "base_version")),
    "artifact.save_file": obj({**{k: v for k, v in ARTIFACT.items() if k != "content"}, "kind": {"type": "string", "enum": sorted(TEXT_FILE_KINDS)}, **FILE}, (*WRITE, "artifact_id", "kind", "scope", "base_version", *FILE)),
    "content.approve": obj(APPROVAL, (*WRITE, "artifact_id", "version", "scope", "evidence", "actor", "synthetic"),
        oneOf=[{"properties": {"synthetic": {"const": True}}},
               {"properties": {"synthetic": {"const": False}, "actor": {"const": "human"}}, "required": ["user_authorization"]}]),
}

EXAMPLES = {
    "task.create": dict(op_id="TEST-create-1", expected_project_id="TEST-PROJECT", task_id="TEST-TASK", artifact_id="TEST-CHAPTER", title="TEST chapter", module="story", scope="chapter/01", inputs=[], must_keep=["Explicit source facts"], allowed_changes=["Candidate prose"], requirements=["Complete chapter"]),
    "task.checkpoint": dict(op_id="TEST-draft-1", expected_project_id="TEST-PROJECT", task_id="TEST-TASK", draft="# TEST chapter\n", completed=["Draft written"], decisions=[], unresolved=[], next_step="Review the saved draft"),
    "task.submit": dict(op_id="TEST-submit-legacy", expected_project_id="TEST-PROJECT", task_id="TEST-TASK", artifact_id="TEST-CHAPTER", kind="novel", content="# TEST chapter\n", base_version=0, metadata={"title": "TEST chapter"}),
    "task.submit_checkpoint": dict(op_id="TEST-submit-1", expected_project_id="TEST-PROJECT", task_id="TEST-TASK", checkpoint_id="TEST-draft-1", expected_draft_sha256="0" * 64, artifact_id="TEST-CHAPTER", kind="novel", base_version=0, metadata={"title": "TEST chapter"}),
    "artifact.save": dict(op_id="TEST-save-1", expected_project_id="TEST-PROJECT", artifact_id="TEST-CHAPTER", kind="novel", scope="chapter/01", content="# TEST chapter\n", base_version=0, deps=[], metadata={"title": "TEST chapter"}),
    "content.approve": dict(op_id="TEST-approve-1", expected_project_id="TEST-PROJECT", artifact_id="TEST-CHAPTER", version=1, scope="chapter/01", evidence="TEST synthetic decision only; not a human approval", actor="test", synthetic=True, base_master_version=0),
}
EXAMPLES["task.checkpoint_file"] = {k: v for k, v in EXAMPLES["task.checkpoint"].items() if k != "draft"}
EXAMPLES["task.checkpoint_file"].update(source_path="drafts/chapter-01.md", expected_file_sha256="0" * 64)
EXAMPLES["artifact.save_file"] = {k: v for k, v in EXAMPLES["artifact.save"].items() if k != "content"}
EXAMPLES["artifact.save_file"].update(source_path="drafts/chapter-01.md", expected_file_sha256="0" * 64)

ACTION_TO_TOOL = {"task.create": "film_task_create", "task.checkpoint": "film_draft_save", "task.checkpoint_file": "film_draft_save",
                  "task.submit_checkpoint": "film_draft_submit", "artifact.save_file": "film_artifact_save_file"}


def action_help(action):
    if action.startswith("screenwriting."):
        from .screenwriting1130 import action_schemas as screenwriting_schemas
        schema = screenwriting_schemas().get(action)
        if schema is None:
            raise ValueError("Unsupported action help: " + str(action))
        return {"read_only": True, "executed": False, "action": action, "inputSchema": schema,
                "example_payload": None, "preferred_tool": "film_screenwriting",
                "call_shape": "film_screenwriting takes root, action without prefix, payload. film_dispatch takes root, full action, payload.",
                "notes": ["Read current revision first. Source hash and anchor must match an exact saved script.",
                          "Scene ID and issue classification are host reported; semantic scope still needs review.",
                          "Major story changes require actual user choice. Recording feedback never approves or edits a script."]}
    if action not in ACTION_SCHEMAS:
        raise ValueError("Unsupported action help: " + str(action))
    return {"read_only": True, "executed": False, "action": action,
            "inputSchema": deepcopy(ACTION_SCHEMAS[action]), "example_payload": deepcopy(EXAMPLES[action]),
            "example_only": True, "contract_scope": "supported_recommended_calls", "preferred_tool": ACTION_TO_TOOL.get(action, "film_dispatch"),
            "call_shape": "Dedicated tools take root and the payload fields directly; film_dispatch takes root, action, payload.",
            "notes": ["Examples are synthetic data, never evidence of user adoption. Replace identities, scope, version and hashes with exact observed values.",
                      "Every write requires op_id and expected_project_id. Same operation retries must preserve all arguments.",
                      "File actions require an explicit project-relative UTF-8 source and the hash of actual bytes.",
                      "Submission from checkpoint requires that task's latest checkpoint and exact draft hash. Saving/submitting does not approve.",
                      "content.approve synthetic=false requires an actual human instruction bound to the exact artifact/version/scope; do not fabricate authorization.",
                      "Approval help describes the conversation and panel-click host contracts. Legacy film_dispatch retains its other-source/real_user_id compatibility branch; it is not recommended as a substitute for actual host evidence."]}


def with_root(schema, root_schema):
    result = deepcopy(schema)
    result["properties"] = {"root": deepcopy(root_schema), **result["properties"]}
    result["required"] = ["root", *result["required"]]
    return result


def tool_definitions(root_schema):
    from .screenwriting1130 import SCHEMAS as screenwriting_schemas
    context = obj({"root": root_schema, "expected_project_id": TEXT,
                   "mode": {"type": "string", "enum": ["summary", "resume", "artifact"], "description": "summary omits prose; resume returns latest checkpoint draft once; artifact reads one exact full version."},
                   "task_id": TEXT, "artifact_id": TEXT, "version": VERSION}, ("root", "expected_project_id", "mode"),
                  oneOf=[{"properties": {"mode": {"const": "summary"}}, "not": {"anyOf": [{"required": ["task_id"]}, {"required": ["artifact_id"]}, {"required": ["version"]}]}},
                         {"properties": {"mode": {"const": "resume"}}, "required": ["task_id"], "not": {"anyOf": [{"required": ["artifact_id"]}, {"required": ["version"]}]}},
                         {"properties": {"mode": {"const": "artifact"}}, "required": ["artifact_id", "version"], "not": {"required": ["task_id"]}}])
    draft = with_root(obj({**CHECKPOINT, **FILE}, (*WRITE, "task_id", "completed", "decisions", "unresolved", "next_step"),
                     oneOf=[{"required": ["draft"], "not": {"anyOf": [{"required": ["source_path"]}, {"required": ["expected_file_sha256"]}]}},
                            {"required": ["source_path", "expected_file_sha256"], "not": {"required": ["draft"]}}]), root_schema)
    entries = [
        ("film_context", "Read compact project context, latest task draft or one exact artifact. Choose only the needed mode. Read-only registry: never initializes or migrates a project.", context, True),
        ("film_action_help", "Read the supported recommended parameter schema and a synthetic example for a common creative action. This executes nothing and needs no project; use instead of reading implementation code.", obj({"action": {"type": "string", "enum": list(ACTION_SCHEMAS) + list(screenwriting_schemas)}}, ("action",)), True),
        ("film_task_create", "Create a scoped creative task with exact inputs and an execution lock. Returns a compact receipt; does not create chats, approve or generate prose. Resolve module with film_modules first.", with_root(ACTION_SCHEMAS["task.create"], root_schema), False),
        ("film_draft_save", "Checkpoint a full draft once, either inline draft OR project-relative source_path plus expected_file_sha256. Returns checkpoint_id/draft_sha256 without echoing prose. Same request retries preserve op_id and all fields.", draft, False),
        ("film_draft_submit", "Submit the task's exact latest checkpoint as a new candidate without resending the draft. Requires checkpoint_id/hash and current base_version; all execution-lock, input and scope checks remain. Does not approve.", with_root(ACTION_SCHEMAS["task.submit_checkpoint"], root_schema), False),
        ("film_artifact_save_file", "Save a text candidate from an already written UTF-8 file within the explicit project. Requires actual file hash, exact deps and base_version. Returns a compact receipt, never approves or bypasses another task's editing scope.", with_root(ACTION_SCHEMAS["artifact.save_file"], root_schema), False),
    ]
    return [{"name": name, "description": desc, "inputSchema": deepcopy(schema),
             "annotations": {"readOnlyHint": ro, "destructiveHint": not ro, "idempotentHint": True, "openWorldHint": False}}
            for name, desc, schema, ro in entries]


def validate(value, schema, path="arguments"):
    """Validate the JSON Schema subset used above before any registry is opened."""
    types = schema.get("type")
    if types:
        types = [types] if isinstance(types, str) else types
        checks = {"object": lambda: isinstance(value, dict), "array": lambda: isinstance(value, list),
                  "string": lambda: isinstance(value, str), "integer": lambda: type(value) is int,
                  "boolean": lambda: type(value) is bool, "null": lambda: value is None}
        if not any(checks[t]() for t in types):
            raise ValueError(path + " must be " + "/".join(types))
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        raise ValueError(path + " has incorrect fixed value")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(path + " is not a supported value")
    if isinstance(value, dict):
        missing = set(schema.get("required", [])) - value.keys()
        if missing:
            raise ValueError(path + " missing required fields: " + ", ".join(sorted(missing)))
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False and value.keys() - props.keys():
            raise ValueError(path + " unknown fields: " + ", ".join(sorted(value.keys() - props.keys())))
        for key in value.keys() & props.keys():
            validate(value[key], props[key], path + "." + key)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ValueError(path + " has too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ValueError(path + " has too many items")
        if "items" in schema:
            for index, item in enumerate(value):
                validate(item, schema["items"], path + "[" + str(index) + "]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise ValueError(path + " must not be empty")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise ValueError(path + " has invalid format")
    if type(value) is int and "minimum" in schema and value < schema["minimum"]:
        raise ValueError(path + " is below its minimum")
    def matches(part):
        try:
            validate(value, part, path)
            return True
        except ValueError:
            return False
    if "oneOf" in schema and sum(matches(part) for part in schema["oneOf"]) != 1:
        raise ValueError(path + " must match exactly one supported field combination")
    if "anyOf" in schema and not any(matches(part) for part in schema["anyOf"]):
        raise ValueError(path + " must match a supported field combination")
    if "not" in schema and matches(schema["not"]):
        raise ValueError(path + " includes incompatible fields")


def creative_dispatch(name, arguments):
    payload = {key: value for key, value in arguments.items() if key != "root"}
    actions = {"film_task_create": "task.create", "film_draft_submit": "task.submit_checkpoint", "film_artifact_save_file": "artifact.save_file"}
    action = actions.get(name)
    if name == "film_draft_save":
        action = "task.checkpoint_file" if "source_path" in payload else "task.checkpoint"
    if action is None:
        raise ValueError("Unsupported creative tool: " + str(name))
    validate(payload, ACTION_SCHEMAS[action], "payload")
    return action, payload

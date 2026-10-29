"""Typed workspace orchestration and delivery-evidence tools.

These tools record local state. Real Codex chats and independent creative review
are performed by the host and remain separate from registry observations.
"""
from copy import deepcopy

READ_ACTIONS = {"workspace.read", "workspace.resolve", "delivery.read", "cloud.read", "art.read", "screenwriting.read", "conversation.read"}
PREFIXES = {"film_workspace": "workspace", "film_delivery": "delivery", "film_cloud": "cloud", "film_art": "art", "film_screenwriting": "screenwriting", "film_conversations": "conversation"}


def action_schemas():
    from .workspace1110 import action_schemas as workspace_schemas
    from .delivery1110 import action_schemas as delivery_schemas
    from .cloud1120 import action_schemas as cloud_schemas
    from .art1130 import action_schemas as art_schemas
    from .screenwriting1130 import action_schemas as screenwriting_schemas
    from .conversations1170 import action_schemas as conversation_schemas
    return {**conversation_schemas(), **workspace_schemas(), **delivery_schemas(), **cloud_schemas(), **art_schemas(), **screenwriting_schemas()}


def tool_definitions(root_schema):
    contracts = action_schemas()
    descriptions = {
        "film_conversations": "Manage project-scoped department controllers and independent execution chats for planning, writing, directing, art, assets and review. Route work with the original request, exact inputs, scope, deliverable and return target; the accurate receiving department accepts before execution preparation. Read derives task submission, recorded completion and recipient-specific report status separately and never writes. Complete records an exact submitted result without implying messaging authorization or approval; report prepares authorized durable host requests. Configure is explicit; legacy workspace bindings and old task locks remain intact. Prepare creates one topic, not a full role workspace. Claim grants first dispatch once; replayed or unknown requests must be reconciled, never resent. Only the host creates, messages or archives chats under actual user authorization and records observed results. Queued IDs are not real thread IDs. Host acceptance is not creative completion, user approval or authenticated receipt. No background chat scheduler.",
        "film_screenwriting": "Read, record and resolve exact-version script feedback from a director, user or reviewer. Locate issues with a scene ID and an exact source-text anchor. Expression, structure and major changes link to an already saved newer full script candidate; major story changes require the user choice with its original quote and scope. Preserve all feedback history. These records never write scripts, approve content, authenticate a user, execute chats or sync cloud Pages.",
        "film_art": "Read or register an exact main/alternate art-direction comparison, record the user's exact selection, integrate only the selected complete visual proposal, or revise exact local ranges within the adopted baseline. Preserve the complete working draft, stable style identity and current cloud binding. Selection, integration and revision never approve. Full source context, current working draft and approved baseline are checked separately. Host range classification and within_baseline judgment are not programmatic semantic proof.",
        "film_cloud": "Coordinate an exact artifact's editable cloud working draft after a full first draft or confirmed revision. Read is non-mutating; configuration, bindings, pending requests and complete host readbacks are persisted locally. The host performs actual Page creation and guarded editing. Unknown creation is reconciled without duplicate pages; a create receipt alone never proves sync. Preserve manual cloud edits and local candidate history. No background network synchronization or approval occurs in this tool.",
        "film_workspace": "Read, prepare or record a route-specific Codex chat workspace. Prepare only creates local role slots. The host must actually create/open chats, retain queued or unknown outcomes and record observed receipts. Reuse exact existing associations; never create duplicate chats after an unknown result. Read and resolve do not write. No creative execution or host calls occur inside this tool.",
        "film_delivery": "Define the requested full-text deliverable, record coverage and independent-review observations for an exact saved artifact, and complete only when recorded evidence is current and unresolved substantive gaps are closed. Read does not write. Drafts remain saveable. Evidence readiness is not creative-quality proof or user approval; reviewer identity is host-reported. Summary mode requires the user's actual request.",
    }
    result = []
    for name, prefix in PREFIXES.items():
        selected = {action.split(".", 1)[1]: contract for action, contract in contracts.items() if action.startswith(prefix + ".")}
        schema = {"type": "object", "properties": {"root": deepcopy(root_schema), "action": {"type": "string", "enum": list(selected)}, "payload": {"type": "object"}},
                  "required": ["root", "action", "payload"], "additionalProperties": False,
                  "oneOf": [{"properties": {"action": {"const": action}, "payload": deepcopy(contract)}} for action, contract in selected.items()]}
        result.append({"name": name, "description": descriptions[name], "inputSchema": schema,
                       "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}})
    return result


def dispatch_arguments(name, arguments):
    from .action_schemas import validate
    if name not in PREFIXES:
        raise ValueError("Unsupported workflow tool")
    action = PREFIXES[name] + "." + arguments["action"]
    contracts = action_schemas()
    if action not in contracts:
        raise ValueError("Unsupported workflow action")
    payload = deepcopy(arguments["payload"])
    validate(payload, contracts[action], "payload")
    if action.startswith("workspace."):
        from .workspace1110 import validate_workspace_payload
        validate_workspace_payload(action, payload)
    if action.startswith("cloud."):
        from .cloud1120 import validate_cloud_payload
        validate_cloud_payload(action, payload)
    if action.startswith("art."):
        from .art1130 import validate_art_payload
        validate_art_payload(action, payload)
    if action.startswith("screenwriting."):
        from .screenwriting1130 import validate_screenwriting_payload
        validate_screenwriting_payload(action, payload)
    if action.startswith("conversation."):
        from .conversations1170 import validate_conversation_payload
        validate_conversation_payload(action, payload)
    return action, payload

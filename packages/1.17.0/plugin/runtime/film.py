"""Film Production Agent: explicit-project, client-invoked command entry."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

def main():
    from filmprod import __version__
    parser = argparse.ArgumentParser(description="影视开发制作总控 Agent " + __version__)
    parser.add_argument("--root", required=True, help="Explicit work/project directory; never inferred")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("snapshot", help="Read registry state")
    commands.add_parser("export", help="Generate Chinese reading copies from registry")
    history = commands.add_parser("history", help="Read immutable artifact versions")
    history.add_argument("artifact_id")
    pages = commands.add_parser("pages-import", help="Import complete existing host Pages observation; no network request")
    pages.add_argument("--file", required=True)
    pages.add_argument("--op-prefix", required=True)
    resume = commands.add_parser("resume", help="Restore task from persisted checkpoint")
    resume.add_argument("task_id")
    dispatch = commands.add_parser("dispatch", help="Apply a registry or derived-file action; mutations require op_id")
    dispatch.add_argument("action")
    dispatch.add_argument("--file", required=True, help="UTF-8 JSON payload file, or - for stdin")
    args = parser.parse_args()
    from filmprod.core import Registry
    root = Path(args.root)
    if not root.is_absolute() or root.resolve() == Path(__file__).resolve().parent:
        parser.error("必须显式指定与系统代码分离的作品绝对目录")
    is_init = args.command == "dispatch" and args.action == "project.init"
    if not is_init and not (root / ".project/registry.sqlite3").is_file():
        parser.error("作品登记库不存在；请先显式初始化")
    registry = None
    try:
        registry = Registry.open_readonly(args.root) if args.command == "dispatch" and args.action in ("planning.read", "document.export", "document.save", "context.read", "workspace.read", "workspace.resolve", "delivery.read", "cloud.read", "art.read", "screenwriting.read") else Registry(args.root)
        if args.command == "snapshot":
            result = registry.snapshot()
        elif args.command == "export":
            from filmprod.export import export_project
            result = export_project(registry)
        elif args.command == "resume":
            result = registry.dispatch("task.resume", {"task_id": args.task_id})
        elif args.command == "history":
            result = registry.dispatch("artifact.history", {"artifact_id": args.artifact_id})
        elif args.command == "pages-import":
            from filmprod.pages_bridge import import_observation
            result = import_observation(registry, json.loads(Path(args.file).read_text(encoding="utf-8-sig")), args.op_prefix)
        else:
            raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8-sig")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("payload must be a JSON object")
            result = registry.dispatch(args.action, payload)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        if registry is not None:
            registry.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

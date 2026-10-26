#!/usr/bin/env python3
"""Small deterministic helpers for a fiction project; no semantic review."""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path


TEMPLATE_NAMES = ("PROJECT.md", "BIBLE.md", "OUTLINE.md", "STATE.md", "VOICE.md")
PROJECT_DIRS = ("drafts", "reviews", "versions")
HANZI = re.compile(r"[\u3400-\u9fff\U00020000-\U0002ebe0]")
RELATIVE_TERMS = {
    "前天早上": -2,
    "前天晚上": -2,
    "昨天早上": -1,
    "昨天晚上": -1,
    "明天早上": 1,
    "明天晚上": 1,
    "后天早上": 2,
    "后天晚上": 2,
    "昨早": -1,
    "昨晚": -1,
    "今早": 0,
    "今晚": 0,
    "明早": 1,
    "明晚": 1,
    "前天": -2,
    "前日": -2,
    "昨天": -1,
    "昨日": -1,
    "今日": 0,
    "今天": 0,
    "明天": 1,
    "后天": 2,
}
RELATIVE_PATTERN = re.compile("|".join(map(re.escape, sorted(RELATIVE_TERMS, key=len, reverse=True))))


def init_project(target: Path, title: str, dry_run: bool) -> dict:
    raise ValueError("内置模块不建立独立项目或版本库；请使用总控 Registry 项目、成果和检查点接口。")


def count_hanzi(text: str) -> int:
    return len(HANZI.findall(text))


def check_draft(draft: Path, rules_path: Path) -> tuple[dict, bool]:
    text = draft.read_text(encoding="utf-8-sig")
    rules = json.loads(rules_path.read_text(encoding="utf-8-sig"))
    if not isinstance(rules, dict):
        raise ValueError("Rules must be a JSON object")
    failures: list[str] = []
    hanzi_count = count_hanzi(text)
    for key, comparator in (("min_hanzi", lambda n: hanzi_count >= n), ("max_hanzi", lambda n: hanzi_count <= n)):
        if key in rules:
            value = rules[key]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{key} must be a non-negative integer")
            if not comparator(value):
                failures.append(f"{key}: expected {value}, got {hanzi_count}")
    locked = rules.get("locked_texts", [])
    forbidden = rules.get("forbidden_literals", [])
    for key, items in (("locked_texts", locked), ("forbidden_literals", forbidden)):
        if not isinstance(items, list) or any(not isinstance(item, str) or not item for item in items):
            raise ValueError(f"{key} must be an array of non-empty strings")
    locked_counts = {item: text.count(item) for item in locked}
    for item, count in locked_counts.items():
        if count != 1:
            failures.append(f"locked_text count {count}, expected 1: {item}")
    forbidden_counts = {item: text.count(item) for item in forbidden}
    for item, count in forbidden_counts.items():
        if count:
            failures.append(f"forbidden_literal count {count}: {item}")
    scene_date = None
    yearless = False
    if "scene_date" in rules:
        try:
            raw_date = rules["scene_date"]
            if not isinstance(raw_date, str):
                raise ValueError("date is not a string")
            yearless = raw_date.startswith("--")
            scene_date = dt.date.fromisoformat("2000-" + raw_date[2:] if yearless else raw_date)
        except (TypeError, ValueError) as exc:
            raise ValueError("scene_date must be YYYY-MM-DD or --MM-DD") from exc
    relative = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in RELATIVE_PATTERN.finditer(line):
            term = match.group()
            relative.append({
                "line": line_number,
                "term": term,
                "resolved_date": (
                    "--" + (scene_date + dt.timedelta(days=RELATIVE_TERMS[term])).strftime("%m-%d")
                    if yearless else str(scene_date + dt.timedelta(days=RELATIVE_TERMS[term]))
                ) if scene_date else None,
                "context": line.strip()[:160],
            })
    result = {
        "draft": str(draft.resolve()),
        "hanzi_count": hanzi_count,
        "locked_counts": locked_counts,
        "forbidden_counts": forbidden_counts,
        "relative_dates_for_manual_review": relative,
        "failures": failures,
        "semantic_review_required": True,
    }
    return result, not failures


def snapshot(project: Path, source: Path) -> dict:
    raise ValueError("内置模块不建立独立项目或版本库；请使用总控 Registry 项目、成果和检查点接口。")


def diff_text(old: Path, new: Path) -> str:
    old_lines = old.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    new_lines = new.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    return "".join(difflib.unified_diff(old_lines, new_lines, fromfile=str(old), tofile=str(new)))


def calculate_ledger(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("initial"), dict) or not isinstance(data.get("events"), list):
        raise ValueError("Ledger needs initial object and events array")
    balances = data["initial"].copy()
    if not balances or any(not isinstance(k, str) or not k or not isinstance(v, int) or isinstance(v, bool) or v < 0 for k, v in balances.items()):
        raise ValueError("Initial balances must be named non-negative integers")
    seen: set[str] = set()
    steps = []
    for event in data["events"]:
        if not isinstance(event, dict) or not isinstance(event.get("id"), str) or not event["id"]:
            raise ValueError("Each event needs a non-empty id")
        event_id = event["id"]
        if event_id in seen:
            raise ValueError(f"Duplicate event id: {event_id}")
        seen.add(event_id)
        requirements, changes = event.get("requires", {}), event.get("delta")
        if not isinstance(requirements, dict) or not isinstance(changes, dict):
            raise ValueError(f"{event_id}: requires and delta must be objects")
        for kind, values in (("requires", requirements), ("delta", changes)):
            for resource, amount in values.items():
                if resource not in balances or not isinstance(amount, int) or isinstance(amount, bool):
                    raise ValueError(f"{event_id}: invalid {kind} entry for {resource}")
                if kind == "requires" and amount < 0:
                    raise ValueError(f"{event_id}: requires cannot be negative")
        for resource, minimum in requirements.items():
            if balances[resource] < minimum:
                raise ValueError(f"{event_id}: needs {minimum} {resource}, has {balances[resource]}")
        next_balances = {resource: value + changes.get(resource, 0) for resource, value in balances.items()}
        for resource, value in next_balances.items():
            if value < 0:
                raise ValueError(f"{event_id}: {resource} would become negative ({value})")
        balances = next_balances
        steps.append({"event_id": event_id, "balances": balances.copy()})
    return {"ledger": str(path.resolve()), "final_balances": balances, "steps": steps, "semantic_review_required": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a small, non-overwriting book project")
    init.add_argument("--target", type=Path, required=True)
    init.add_argument("--title", required=True)
    init.add_argument("--dry-run", action="store_true")
    check = commands.add_parser("check", help="Check literal constraints and locate relative dates")
    check.add_argument("--draft", type=Path, required=True)
    check.add_argument("--rules", type=Path, required=True)
    save = commands.add_parser("snapshot", help="Save a non-overwriting version of a project file")
    save.add_argument("--project", type=Path, required=True)
    save.add_argument("--source", type=Path, required=True)
    compare = commands.add_parser("diff", help="Show a unified text diff")
    compare.add_argument("--old", type=Path, required=True)
    compare.add_argument("--new", type=Path, required=True)
    ledger = commands.add_parser("ledger", help="Validate integer resource transitions")
    ledger.add_argument("--file", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = init_project(args.target, args.title, args.dry_run)
            success = True
        elif args.command == "check":
            result, success = check_draft(args.draft, args.rules)
        elif args.command == "snapshot":
            result = snapshot(args.project, args.source)
            success = True
        elif args.command == "ledger":
            result = calculate_ledger(args.file)
            success = True
        else:
            print(diff_text(args.old, args.new), end="")
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if success else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

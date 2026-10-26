"""Inspect installed skill discovery through an independent official app-server.

No thread is started, resumed, or messaged. This is not desktop hot-reload evidence.
"""
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path


def probe_skill_discovery(cli, cwd, cache, expected_skills):
    messages = queue.Queue()
    stderr_tail = []
    process = subprocess.Popen([str(cli), "app-server"], cwd=str(cwd), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

    def read_stdout():
        for line in process.stdout:
            try:
                messages.put(json.loads(line))
            except ValueError:
                pass
        messages.put({"diagnostic_eof": True})

    def drain_stderr():
        for line in process.stderr:
            stderr_tail.append(line.rstrip())
            del stderr_tail[:-5]

    threading.Thread(target=read_stdout, daemon=True).start()
    threading.Thread(target=drain_stderr, daemon=True).start()

    def send(message):
        process.stdin.write(json.dumps(message, ensure_ascii=False)+"\n")
        process.stdin.flush()

    def response(request_id):
        deadline = time.monotonic()+45
        while time.monotonic() < deadline:
            item = messages.get(timeout=max(0.1, deadline-time.monotonic()))
            if item.get("id") == request_id:
                if "error" in item:
                    raise ValueError(json.dumps(item["error"], ensure_ascii=False))
                return item["result"]
            if item.get("diagnostic_eof"):
                raise ValueError("independent app-server closed before response")
        raise TimeoutError("independent app-server response timed out")

    result = {"executor": "independent desktop-bundled app-server stdio", "requests": ["initialize", "skills/list"],
              "thread_started": False, "existing_desktop_chat_reloaded": False,
              "expected_cache": str(cache), "matches": [], "passed": False}
    try:
        send({"jsonrpc":"2.0", "id":1, "method":"initialize", "params":{"clientInfo":{"name":"film-production-skill-verifier","version":"1"}}})
        response(1)
        send({"jsonrpc":"2.0", "method":"initialized"})
        send({"jsonrpc":"2.0", "id":2, "method":"skills/list", "params":{"cwds":[str(cwd)],"forceReload":True}})
        listing = response(2)
        # Walk only to find entries for our explicit skill names. Unrelated user
        # skills and app configuration are not copied into the release report.
        def visit(value):
            if isinstance(value, dict):
                name = str(value.get("name", "")).rsplit(":", 1)[-1]
                if name in expected_skills and isinstance(value.get("path"), str):
                    path = Path(value["path"])
                    expected = Path(cache)/"skills"/name/"SKILL.md"
                    result["matches"].append({"name":name,"reported_name":value["name"],"plugin_id":value.get("pluginId"),"path":str(path),"enabled":value.get("enabled"),
                        "scope":value.get("scope"),"from_expected_installed_cache":path.resolve()==expected.resolve()})
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(listing)
        result["passed"] = all(any(row["name"] == name and row["from_expected_installed_cache"] and row["enabled"] is not False for row in result["matches"]) for name in expected_skills)
    except (OSError, ValueError, TimeoutError, queue.Empty, KeyError) as error:
        result["error"] = str(error) or type(error).__name__
    finally:
        try:
            process.stdin.close()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            # Only our newly-created diagnostic child, never a desktop process.
            process.terminate()
            process.wait(timeout=5)
        result["diagnostic_exit_code"] = process.returncode
    return result

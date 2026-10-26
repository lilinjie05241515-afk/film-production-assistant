"""Local-only, standard-library dashboard host for Film Production Agent 1.0.0."""
from __future__ import annotations

import argparse
import hashlib
import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

VERSION = "1.0.0"
WEB_ROOT = Path(__file__).resolve().parent / "web"
MAX_BODY = 4 * 1024 * 1024
UI_ACTIONS = frozenset({"artifact.get", "artifact.history", "master.history", "snapshot"})
# Legacy diagnostic path is read-only. The supported management board uses MCP.

STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/styles.css": ("styles.css", "text/css; charset=utf-8")}


def registry_class():
    from filmprod.core import Registry
    return Registry


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, roots, registry_factory=None):
        if address[0] not in {"127.0.0.1", "localhost"}:
            raise ValueError("看板仅允许绑定本机 127.0.0.1")
        self.projects = {}
        for root in roots:
            resolved = Path(root).resolve()
            key = hashlib.sha256(str(resolved).casefold().encode()).hexdigest()[:12]
            self.projects[key] = resolved
        if not self.projects:
            raise ValueError("请通过 --root 显式注册一个作品目录")
        self.default_project = next(iter(self.projects))
        self.registry_factory = registry_factory or registry_class()
        super().__init__(address, DashboardHandler)

    @contextmanager
    def registry(self, key):
        if key not in self.projects:
            raise ValueError("未注册的项目；只能使用启动命令显式加入的目录")
        factory = self.registry_factory
        instance = factory.open_readonly(self.projects[key]) if hasattr(factory, "open_readonly") else factory(self.projects[key])
        try:
            yield instance
        finally:
            close = getattr(instance, "close", None)
            if callable(close):
                close()


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "FilmProduction/1.0.0"

    def log_message(self, fmt, *args):
        # Avoid writing user-provided request bodies or query strings into logs.
        print(f"dashboard {self.client_address[0]} {args[1] if len(args) > 1 else ''}")

    def respond(self, status, data, content_type="application/json; charset=utf-8"):
        body = json.dumps(data, ensure_ascii=False).encode() if not isinstance(data, bytes) else data
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def validate_local(self, mutation=False):
        port = self.server.server_address[1]
        allowed = {f"localhost:{port}", f"127.0.0.1:{port}"}
        host = self.headers.get("Host", "")
        if host not in allowed:
            self.respond(403, {"error": "拒绝非本机 Host"})
            return False
        origin = self.headers.get("Origin")
        if (origin is not None and origin != "http://" + host) or (mutation and origin is None):
            self.respond(403, {"error": "写请求必须来自本机看板同源页面"})
            return False
        top_level_home = (
            not mutation and self.command == "GET" and urlsplit(self.path).path == "/"
            and self.headers.get("Sec-Fetch-Mode") == "navigate"
            and self.headers.get("Sec-Fetch-Dest") == "document"
        )
        if self.headers.get("Sec-Fetch-Site") == "cross-site" and not top_level_home:
            self.respond(403, {"error": "拒绝跨站请求"})
            return False
        return True

    def project_key(self):
        values = parse_qs(urlsplit(self.path).query).get("project", [self.server.default_project])
        if len(values) != 1 or values[0] not in self.server.projects:
            raise ValueError("未注册的项目")
        return values[0]

    def failure(self, exc):
        conflict = "conflict" in type(exc).__name__.lower() or isinstance(exc, RuntimeError)
        if isinstance(exc, (ValueError, KeyError, TypeError)) or conflict:
            self.respond(409 if conflict else 400, {"error": str(exc), "type": type(exc).__name__})
        else:
            self.respond(500, {"error": "登记服务未完成本次操作，请检查服务日志；不要假定写入成功", "type": type(exc).__name__})

    def do_GET(self):
        if not self.validate_local():
            return
        path = urlsplit(self.path).path
        try:
            if path in STATIC:
                filename, mime = STATIC[path]
                self.respond(200, (WEB_ROOT / filename).read_bytes(), mime)
            elif path == "/health":
                self.respond(200, {"status": "ok", "version": VERSION, "local_only": True})
            elif path == "/api/projects":
                projects = []
                for key, root in self.server.projects.items():
                    with self.server.registry(key) as reg:
                        snap = reg.snapshot()
                    project = snap.get("project") or {}
                    if not isinstance(project, dict):
                        project = {}
                    projects.append({"key": key, "title": project.get("title", root.name),
                                     "root": str(root), "test_only": project.get("test_only", None)})
                self.respond(200, {"projects": projects, "default": self.server.default_project, "version": VERSION})
            elif path == "/api/snapshot":
                with self.server.registry(self.project_key()) as reg:
                    snapshot = reg.snapshot()
                self.respond(200, snapshot)
            else:
                self.respond(404, {"error": "路径不存在"})
        except Exception as exc:
            self.failure(exc)

    def do_POST(self):
        if not self.validate_local(mutation=True):
            return
        if urlsplit(self.path).path != "/api/dispatch":
            self.respond(404, {"error": "路径不存在"})
            return
        try:
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self.respond(415, {"error": "只接受 application/json"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY or self.headers.get("Transfer-Encoding"):
                self.respond(413, {"error": "请求大小无效（上限 4 MiB）"})
                return
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(request, dict) or not isinstance(request.get("payload"), dict):
                raise ValueError("请求必须包含 action 与 payload 对象")
            action, payload = request.get("action"), request["payload"]
            if action not in UI_ACTIONS:
                self.respond(403, {"error": "此操作不开放给看板；请通过授权的本地 CLI 或宿主工具执行"})
                return
            if action not in {"task.resume", "artifact.get"} and not payload.get("op_id"):
                raise ValueError("写请求必须包含唯一 op_id")
            with self.server.registry(self.project_key()) as reg:
                result = reg.dispatch(action, payload)
            self.respond(200, result)
        except Exception as exc:
            self.failure(exc)

    def do_OPTIONS(self):
        self.respond(403, {"error": "不支持跨源访问"})


def main():
    parser = argparse.ArgumentParser(description="影视开发制作总控 Agent 1.0.0 本机看板")
    parser.add_argument("--root", required=True, help="显式注册的作品目录")
    parser.add_argument("--project", action="append", default=[], help="追加已授权的作品目录白名单，可重复")
    parser.add_argument("--port", type=int, default=18765)
    args = parser.parse_args()
    server = DashboardServer(("127.0.0.1", args.port), [args.root, *args.project])
    print(f"Film Production Agent {VERSION}: http://127.0.0.1:{server.server_port}")
    print("仅本机服务；项目由命令行显式注册。音乐创作待接入。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

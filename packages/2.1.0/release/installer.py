"""Windows and macOS local installer. Standard library only; no downloads or host mutations.

The archive is immutable. A separate deployment contains machine-specific MCP
configuration. Only explicitly supplied project roots are ever inspected.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

IDENTITY = "film-production-agent@film-production-local"
MANIFEST = "release-manifest.json"
ACTIVE_STATUSES = {"created", "in_progress", "needs_review"}
MAC_MEDIA_DIRECTORIES = ("/opt/homebrew/opt/ffmpeg-full/bin", "/usr/local/opt/ffmpeg-full/bin",
                         "/opt/homebrew/bin", "/usr/local/bin")
CATALOG_SQL = """
CREATE TABLE IF NOT EXISTS projects(project_id TEXT PRIMARY KEY, root TEXT UNIQUE NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bindings(kind TEXT NOT NULL, binding_id TEXT NOT NULL, project_id TEXT NOT NULL, PRIMARY KEY(kind,binding_id));
CREATE TABLE IF NOT EXISTS operations(op_id TEXT PRIMARY KEY, action TEXT NOT NULL, request_hash TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL);
"""


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def absolute(value, label):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{label} 必须是明确的绝对路径")
    return path.resolve()


def safe_name(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or any(ord(c) < 32 or c in '<>"|?*' for c in name):
        raise ValueError(f"不安全的相对路径: {name!r}")
    parts = PurePosixPath(name).parts
    if PurePosixPath(name).is_absolute() or any(p in (".", "..") or p.endswith((".", " ")) for p in parts):
        raise ValueError(f"不安全的相对路径: {name}")
    if any(re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", p, re.I) for p in parts):
        raise ValueError(f"Windows 保留路径: {name}")
    if str(PurePosixPath(name)) != name:
        raise ValueError(f"非规范相对路径: {name}")
    return name


def path_identity(name):
    # APFS/HFS+ may expose decomposed Unicode even when ZIP names use NFC.
    # The release remains portable to case-insensitive filesystems as well.
    return unicodedata.normalize("NFC", name).casefold()


def no_links(root):
    for path in [root, *root.rglob("*")]:
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError(f"发行包/快照不接受链接或目录联接: {path}")


def version_tuple(version):
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?", version)
    if not match:
        raise ValueError("版本必须为不可变 SemVer，例如 1.6.0")
    return tuple(map(int, match.groups()[:3])) + (match.group(4) is None, match.group(4) or "")


@contextlib.contextmanager
def package_directory(package):
    package = absolute(package, "package")
    if package.is_dir():
        yield package
        return
    if not package.is_file() or not zipfile.is_zipfile(package):
        raise ValueError("发行包必须是已解压目录或 ZIP")
    with tempfile.TemporaryDirectory(prefix="filmprod-install-") as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(package) as archive:
            seen = set()
            entries = archive.infolist()
            if len(entries) > 25000 or sum(i.file_size for i in entries) > 1024 * 1024 * 1024:
                raise ValueError("ZIP 超过发行安装器的 25000 文件/1 GiB 展开上限")
            files = set()
            parents = set()
            for info in entries:
                name = info.filename.rstrip("/")
                safe_name(name)
                if path_identity(name) in seen:
                    raise ValueError("ZIP 包含重复、仅大小写或 Unicode 规范形式不同的路径")
                seen.add(path_identity(name))
                folded = path_identity(name)
                ancestors = {path_identity(str(p)) for p in PurePosixPath(name).parents if str(p) != "."}
                if files & ancestors or (not info.is_dir() and folded in parents):
                    raise ValueError("ZIP 文件与目录路径冲突")
                parents.update(ancestors)
                if info.is_dir():
                    parents.add(folded)
                else:
                    files.add(folded)
                if info.flag_bits & 1:
                    raise ValueError("安装器不接受加密 ZIP")
                if info.file_size > 256 * 1024 * 1024:
                    raise ValueError("ZIP 单文件超过 256 MiB 上限")
                if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                    raise ValueError("ZIP 不允许符号链接")
            # Complete archive metadata validation precedes extraction.
            for info in entries:
                name = info.filename.rstrip("/")
                if info.is_dir():
                    (root / name).mkdir(parents=True, exist_ok=True)
                    continue
                dest = root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, dest.open("wb") as target:
                    shutil.copyfileobj(source, target)
        yield root


def verify_directory(root, overrides=None):
    root = Path(root)
    no_links(root)
    manifest = read_json(root / MANIFEST)
    if manifest.get("schema_version") != 1 or manifest.get("identity") != IDENTITY:
        raise ValueError("不支持的发行清单或插件身份")
    version_tuple(manifest["version"])
    if manifest.get("channel") not in {"stable", "development"}:
        raise ValueError("发行渠道必须为 stable/development")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("发行清单没有完整文件列表")
    expected = {}
    folded = set()
    for entry in entries:
        name = safe_name(entry["path"])
        if name == MANIFEST or path_identity(name) in folded:
            raise ValueError("发行清单重复路径或包含自身")
        folded.add(path_identity(name))
        if not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise ValueError("SHA-256 格式错误")
        expected[name] = entry
    overrides = overrides or {}
    if len({path_identity(safe_name(n)) for n in overrides}) != len(overrides):
        raise ValueError("本机配置包含 Unicode 或大小写重复路径")
    normalized = lambda name: unicodedata.normalize("NFC", name)
    expected = {normalized(n): entry for n, entry in expected.items()}
    overrides = {normalized(n): sha for n, sha in overrides.items()}
    actual_files = list(p for p in root.rglob("*") if p.is_file())
    actual_names = [p.relative_to(root).as_posix() for p in actual_files]
    if len({path_identity(n) for n in actual_names}) != len(actual_names):
        raise ValueError("发行目录包含仅大小写或 Unicode 规范形式不同的文件")
    actual = {normalized(n): p for n, p in zip(actual_names, actual_files)}
    wanted_names = set(expected) | {MANIFEST} | set(overrides)
    if set(actual) != wanted_names:
        raise ValueError("发行文件缺失或存在未登记文件: " + str(sorted(set(actual) ^ wanted_names)))
    for name, entry in expected.items():
        path = actual[name]
        wanted = overrides.get(name, entry["sha256"])
        if digest(path) != wanted or (name not in overrides and path.stat().st_size != entry["size"]):
            raise ValueError(f"文件校验失败: {name}")
    for name, sha in overrides.items():
        if digest(actual[name]) != sha:
            raise ValueError(f"本机配置校验失败: {name}")
    plugin = read_json(root / "plugin/.codex-plugin/plugin.json")
    if plugin.get("name") != "film-production-agent" or plugin.get("version") != manifest["version"]:
        raise ValueError("插件清单和发行版本不一致")
    if (root / "plugin/plugin.json").is_file():
        portable = read_json(root / "plugin/plugin.json")
        if portable.get("name") != "film-production-agent" or portable.get("version") != manifest["version"]:
            raise ValueError("portable 插件清单和发行版本不一致")
    runtime = manifest.get("runtime", {})
    if runtime.get("data_schema_min") is None or runtime.get("data_schema_max") is None:
        raise ValueError("必须声明作品 schema 兼容区间")
    if any(type(runtime[k]) is not int for k in ("data_schema_min", "data_schema_max")) or runtime["data_schema_min"] < 1 or runtime["data_schema_max"] < runtime["data_schema_min"]:
        raise ValueError("作品 schema 兼容区间不合法")
    lock = manifest.get("modules_lock")
    if lock and digest(root / safe_name(lock["path"])) != lock["sha256"]:
        raise ValueError("专业模块锁不一致")
    return manifest


def verify_package(package):
    with package_directory(package) as root:
        manifest = verify_directory(root)
        return {"verified": True, "version": manifest["version"], "identity": manifest["identity"],
                "manifest_sha256": digest(root / MANIFEST), "files": len(manifest["files"]),
                "archive_sha256": digest(package) if Path(package).is_file() else None}


def optional_executable(name, current_platform):
    executable = shutil.which(name)
    if executable:
        return str(Path(executable).resolve())
    # GUI-launched apps on macOS do not necessarily inherit the shell's PATH.
    if current_platform == "macos":
        for directory in MAC_MEDIA_DIRECTORIES:
            candidate = Path(directory) / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate.resolve())
    return None


def environment(python=None):
    executable = absolute(python or sys.executable, "Python")
    probe_code = ("import sys,sqlite3,json,platform; "
                  "print(json.dumps({'version':list(sys.version_info[:3]),'sqlite':sqlite3.sqlite_version,"
                  "'executable':sys.executable,'sys_platform':sys.platform,'machine':platform.machine()}))")
    guidance = "请安装 Python 3.11 或更新版本（含 sqlite3），并用 --python 指定解释器的绝对路径；macOS 使用 python3，Windows 使用 python.exe"
    try:
        probe = subprocess.run([str(executable), "-I", "-c", probe_code], capture_output=True, text=True, encoding="utf-8", timeout=30)
    except OSError as exc:
        raise ValueError("找不到可运行的 Python；" + guidance) from exc
    if probe.returncode:
        raise ValueError("Python 无法运行；" + guidance)
    try:
        result = json.loads(probe.stdout)
        if tuple(result["version"]) < (3, 11, 0):
            raise ValueError("需要 Python 3.11 或更新版本，且必须包含 sqlite3")
        result["executable"] = str(absolute(result["executable"], "Python"))
        current_platform = {"win32": "windows", "darwin": "macos"}.get(result["sys_platform"], result["sys_platform"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Python 环境探测未返回有效信息；" + guidance) from exc
    result.update(current_platform=current_platform, supported_platforms=["windows", "macos"],
                  platform_supported=current_platform in {"windows", "macos"}, environment_checked=True,
                  ffmpeg=optional_executable("ffmpeg", current_platform), ffprobe=optional_executable("ffprobe", current_platform),
                  ffmpeg_required=False, missing_optional_guidance="FFmpeg/ffprobe 缺失时文字创作与登记可用；媒体预览和本地渲染需安装 FFmpeg。macOS 同时检查 Homebrew ffmpeg-full 与标准 bin 目录，其他安装位置需加入启动环境 PATH；带字幕本地渲染需要含 drawtext 的完整构建。不会自动下载或调用付费服务。")
    return result


@contextlib.contextmanager
def installation_lock(app):
    app.mkdir(parents=True, exist_ok=True)
    lock = app / ".installer.lock"
    try:
        stream = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise ValueError(f"已有安装事务；先核查 {lock}，确认进程结束后人工移走锁文件并执行 recover")
    with stream:
        stream.write(json.dumps({"pid": os.getpid(), "time": now()}))
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def layout(app_root):
    app = absolute(app_root, "app-root")
    state = read_json(app / "state.json") if (app / "state.json").is_file() else None
    return app, state


@contextlib.contextmanager
def database(*args, **kwargs):
    connection = sqlite3.connect(*args, **kwargs)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def database_copy(source, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with database(Path(source).as_uri() + "?mode=ro", uri=True) as original:
        with database(destination) as target:
            original.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLite 备份完整性检查失败")


def catalog_init(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with database(path.as_uri() + "?mode=ro", uri=True) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("现有 catalog 完整性检查失败")
            for table in ("projects", "bindings", "operations"):
                connection.execute(f"SELECT * FROM {table} LIMIT 0")
        return False
    with database(path) as connection:
        connection.executescript(CATALOG_SQL)
    return True


def deployment_config(plugin, python, config, catalog):
    return {"mcpServers": {"film-production": {"command": python,
            "args": ["-B", "-X", "utf8", str(plugin / "mcp_server.py")], "cwd": str(plugin),
            "env": {"FILMPROD_SYSTEM_ROOT": str(plugin), "FILMPROD_CATALOG_PATH": str(catalog),
                    "FILMPROD_CONFIG_PATH": str(config / "user.json"), "PYTHONDONTWRITEBYTECODE": "1"}}}}


def smoke(deployment, version):
    server = read_json(deployment / "plugin/.mcp.json")["mcpServers"]["film-production"]
    env = dict(os.environ)
    for key in ("FILMPROD_PROJECT", "PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    env.update(server["env"])
    requests = [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "film_health", "arguments": {}}}]
    probe = subprocess.run([server["command"], *server["args"]], input="".join(json.dumps(r) + "\n" for r in requests), cwd=server["cwd"], env=env,
                           capture_output=True, text=True, encoding="utf-8", timeout=45)
    if probe.returncode:
        raise ValueError("安装副本 stdio 启动失败: " + probe.stderr[-2000:])
    responses = {r.get("id"): r for r in map(json.loads, probe.stdout.splitlines())}
    health = responses.get(2, {}).get("result", {}).get("structuredContent", {})
    tools = responses.get(1, {}).get("result", {}).get("tools", [])
    if health.get("version") != version or health.get("runtime_isolated") is not True or not health.get("ui_resource_present"):
        raise ValueError("安装副本 health 版本/runtime/UI 检查失败")
    if len(tools) < 12:
        raise ValueError("安装副本工具发现不完整")
    return {"health": health, "tool_count": len(tools), "native_panel_verified": False, "running_host_reloaded": False}


def verify_deployment(app, version):
    source = app / "releases" / version
    manifest = verify_directory(source)
    record = read_json(app / "deployment-records" / (version + ".json"))
    if digest(source / MANIFEST) != record["source_manifest_sha256"]:
        raise ValueError("安装来源清单被改动")
    deployment = app / "deployments" / version
    if digest(deployment / MANIFEST) != record["source_manifest_sha256"]:
        raise ValueError("安装副本清单被改动")
    verify_directory(deployment, record["overrides"])
    return manifest, record


def install(package, app_root, data_root, config_root, python=None, catalog_path=None, activate=True):
    app, old_state = layout(app_root)
    data = absolute(data_root, "data-root")
    config = absolute(config_root, "config-root")
    for left, right in ((app, data), (app, config)):
        if left == right or left in right.parents or right in left.parents:
            raise ValueError("程序目录必须与用户数据/配置目录互相独立")
    catalog = absolute(catalog_path if catalog_path else data / "catalog/projects.sqlite3", "catalog-path")
    config_file = config / "user.json"
    configured_python = read_json(config_file).get("python") if config_file.is_file() else None
    env = environment(python or configured_python)
    if not env["platform_supported"]:
        raise ValueError("当前安装器仅支持 Windows 和 macOS；检测到 " + env["current_platform"])
    desired = {"config_version": 1, "app_root": str(app), "data_root": str(data), "catalog_path": str(catalog),
               "python": env["executable"], "cloud_bindings": {}, "default_project": None}
    with installation_lock(app), package_directory(package) as source:
        manifest = verify_directory(source)
        if env["current_platform"] not in manifest["runtime"].get("platforms", []):
            raise ValueError("发行包未声明支持当前系统 " + env["current_platform"] + "；请使用兼容版本")
        version = manifest["version"]
        if config_file.exists():
            existing = read_json(config_file)
            for key in ("app_root", "data_root", "catalog_path"):
                if absolute(existing.get(key), key) != absolute(desired[key], key):
                    raise ValueError(f"现有配置 {key} 不匹配；请通过明确迁移处理，安装不会覆盖用户配置")
        if old_state and any(absolute(old_state[key], key) != location for key, location in (("config_root", config), ("data_root", data), ("catalog_path", catalog))):
            raise ValueError("升级必须沿用现有独立配置、数据和登记库位置")
        release = app / "releases" / version
        deployment = app / "deployments" / version
        if os.name == "nt":
            roots = [release, deployment, app / ".stage-00000000/release"]
            if any(len(str(base / item["path"])) >= 260 for base in roots for item in manifest["files"]):
                raise ValueError("安装目录过长，可能超过 Windows 路径上限；请选择较短的 app-root，作品/配置位置可保持不变")
        if release.exists() or deployment.exists():
            if release.exists() and deployment.exists():
                _, record = verify_deployment(app, version)
                if record["source_manifest_sha256"] == digest(source / MANIFEST):
                    return {"status": "already_staged", "version": version, "state": old_state, "deployment": str(deployment)}
            raise ValueError("版本目录已存在且不一致/残缺；不可覆盖不可变发行版本，请先诊断")
        # A long random staging component previously exceeded classic Windows
        # MAX_PATH even when the final immutable destination was short enough.
        staging = app / (".stage-" + uuid.uuid4().hex[:8])
        try:
            shutil.copytree(source, staging / "release")
            verify_directory(staging / "release")
            shutil.copytree(staging / "release", staging / "deployment")
            # Config points to the final immutable version directory, never current/.
            local_mcp = deployment_config(deployment / "plugin", env["executable"], config, catalog)
            write_json(staging / "deployment/plugin/.mcp.json", local_mcp)
            overrides = {"plugin/.mcp.json": digest(staging / "deployment/plugin/.mcp.json")}
            verify_directory(staging / "deployment", overrides)
            release.parent.mkdir(parents=True, exist_ok=True)
            deployment.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging / "release", release)
            os.replace(staging / "deployment", deployment)
            record = {"version": version, "source_manifest_sha256": digest(release / MANIFEST), "overrides": overrides,
                      "python": env["executable"], "installed_at": now(), "deployment": str(deployment)}
            write_json(app / "deployment-records" / (version + ".json"), record)
            evidence = smoke(deployment, version)
            fresh_catalog = catalog_init(catalog)
            if not config_file.exists():
                write_json(config_file, desired)
            # Staging another version never changes the current pointer or host.
            if not old_state:
                state = {"state_version": 1, "identity": IDENTITY, "active_version": version if activate else None,
                         "enabled": activate, "config_root": str(config), "data_root": str(data), "catalog_path": str(catalog),
                         "staged_versions": [version], "last_transaction": None}
            else:
                state = dict(old_state)
                # Windows app virtualization/junction aliases can resolve to the
                # same existing directory under a newer desktop process. Identity
                # was compared above; normalize the local state, never move data.
                state.update(config_root=str(config), data_root=str(data), catalog_path=str(catalog))
                state["staged_versions"] = sorted(set(state["staged_versions"]) | {version}, key=version_tuple)
            write_json(app / "state.json", state)
            return {"status": "installed" if not old_state and activate else "staged", "version": version,
                    "deployment": str(deployment), "state": state, "empty_catalog_created": fresh_catalog,
                    "environment": env, "smoke": evidence, "host_registration_performed": False,
                    "normalized_path_aliases": {key: {"previous": old_state[key], "resolved": state[key]} for key in ("config_root", "data_root", "catalog_path") if old_state and old_state[key] != state[key]},
                    "next": "运行 host-plan 查看固定版本本机 marketplace；实际宿主安装与新聊天 health 另行验证。"}
        except Exception:
            # Keep incomplete immutable directories inspectable; never erase data.
            raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def inspect_project(root, manifest, reject_active=True):
    root = absolute(root, "project-root")
    path = root / ".project/registry.sqlite3"
    if not path.is_file():
        raise ValueError(f"显式作品缺少数据库: {root}")
    with database(path.as_uri() + "?mode=ro", uri=True) as connection:
        settings = dict(connection.execute("SELECT key,value FROM settings"))
        schema = json.loads(settings["schema_version"])
        identity = json.loads(settings["project"])
        tasks = [json.loads(row[0]) for row in connection.execute("SELECT data FROM tasks")]
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("作品数据库完整性检查失败")
    runtime = manifest["runtime"]
    if not runtime["data_schema_min"] <= schema <= runtime["data_schema_max"]:
        raise ValueError(f"作品 schema {schema} 不在目标兼容区间；需独立备份及显式迁移，不自动降级")
    active = [t["task_id"] for t in tasks if t.get("status") in ACTIVE_STATUSES]
    if reject_active and active:
        raise ValueError("作品存在在执行任务，保持原 runtime 完成/取消后重试；不能改变规则: " + ", ".join(active))
    return {"root": str(root), "project_id": identity["project_id"], "schema": schema, "active_tasks": active}


def tree_snapshot(source, destination):
    source, destination = Path(source), Path(destination)
    no_links(source)
    shutil.copytree(source, destination)
    # SQLite backup includes WAL and prevents a torn file copy.
    for db in source.rglob("*.sqlite3"):
        copy = destination / db.relative_to(source)
        copy.unlink(missing_ok=True)
        database_copy(db, copy)
        Path(str(copy) + "-wal").unlink(missing_ok=True)
        Path(str(copy) + "-shm").unlink(missing_ok=True)


def snapshot_hashes(root):
    return {p.relative_to(root).as_posix(): digest(p) for p in root.rglob("*") if p.is_file() and p.name != "snapshot.json"}


def make_snapshot(app, state, projects=(), kind="switch"):
    transaction = uuid.uuid4().hex
    backup = app / "backups" / transaction
    backup.mkdir(parents=True)
    write_json(backup / "state.json", state)
    config = Path(state["config_root"])
    if config.exists():
        tree_snapshot(config, backup / "config")
    catalog = Path(state["catalog_path"])
    if catalog.exists():
        database_copy(catalog, backup / "catalog.sqlite3")
    entries = []
    for index, info in enumerate(projects):
        root = Path(info["root"])
        if root == app or root in app.parents or app in root.parents:
            raise ValueError("作品目录不能包含程序和备份目录")
        tree_snapshot(root, backup / "projects" / str(index))
        entries.append(dict(info, snapshot_directory="projects/" + str(index)))
    meta = {"snapshot_version": 1, "transaction": transaction, "kind": kind, "created_at": now(),
            "app_root": str(app), "projects": entries, "files": snapshot_hashes(backup)}
    write_json(backup / "snapshot.json", meta)
    return backup, meta


def validate_snapshot(app, backup):
    backup = absolute(backup, "backup")
    if backup.parent != app / "backups":
        raise ValueError("只能恢复当前 app-root/backups 下的已登记快照")
    meta = read_json(backup / "snapshot.json")
    if meta.get("app_root") != str(app) or snapshot_hashes(backup) != meta.get("files"):
        raise ValueError("备份来源或 SHA-256 校验失败")
    state = read_json(backup / "state.json")
    version = state.get("active_version")
    if version:
        verify_deployment(app, version)
    return meta, state


def replace_sqlite(source, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Caller must first stop writers; never unlink live -wal/-shm files.
    with database(target, timeout=2) as destination:
        with database(Path(source).as_uri() + "?mode=ro", uri=True) as original:
            original.backup(destination)
        if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("恢复后 SQLite 验证失败")


def restore_snapshot(app, backup):
    meta, state = validate_snapshot(app, backup)
    # No directory deletion: newer files remain in the pre-restore safety backup;
    # extra project media also remain on disk but registry pointers are restored.
    config = Path(state["config_root"])
    if (backup / "config").exists():
        # Restore the exact config set; retain displaced files beside the config
        # as well as the explicit pre-rollback snapshot. No files are deleted.
        replacement = config.with_name(config.name + ".restore-" + uuid.uuid4().hex)
        displaced = config.with_name(config.name + ".before-restore-" + uuid.uuid4().hex)
        shutil.copytree(backup / "config", replacement)
        if config.exists():
            os.replace(config, displaced)
        try:
            os.replace(replacement, config)
        except Exception:
            if displaced.exists() and not config.exists():
                os.replace(displaced, config)
            raise
    if (backup / "catalog.sqlite3").exists():
        replace_sqlite(backup / "catalog.sqlite3", state["catalog_path"])
    for info in meta["projects"]:
        source = backup / info["snapshot_directory"]
        target = Path(info["root"])
        for file in source.rglob("*"):
            if not file.is_file():
                continue
            dest = target / file.relative_to(source)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if file.suffix == ".sqlite3":
                replace_sqlite(file, dest)
            else:
                shutil.copy2(file, dest)
    write_json(app / "state.json", state)
    return {"restored_version": state.get("active_version"), "projects": len(meta["projects"]),
            "catalog_restored": (backup / "catalog.sqlite3").exists(), "config_restored": (backup / "config").exists()}


def switch(app_root, version, project_roots=(), fault=None, quiescent=False):
    app, state = layout(app_root)
    if not state:
        raise ValueError("尚未安装")
    if not quiescent:
        raise ValueError("切换及其故障恢复需要 catalog/配置/显式作品停止写入；确认后传 --quiescent，不会强杀进程")
    with installation_lock(app):
        manifest, _ = verify_deployment(app, version)
        previous = state.get("active_version")
        if previous and version_tuple(version) < version_tuple(previous):
            raise ValueError("禁止只切低版本；请使用带程序/配置/catalog/作品快照的 rollback")
        projects = [inspect_project(r, manifest) for r in project_roots]
        backup, meta = make_snapshot(app, state, projects)
        journal = {"transaction": meta["transaction"], "phase": "prepared", "backup": str(backup), "target_version": version, "created_at": now()}
        write_json(app / "transaction.json", journal)
        try:
            evidence = smoke(app / "deployments" / version, version)
            if fault:
                fault("after_backup", state)
            next_state = dict(state, active_version=version, enabled=True, last_transaction=meta["transaction"])
            write_json(app / "state.json", next_state)
            if fault:
                fault("after_switch", state)
            journal["phase"] = "committed"
            write_json(app / "transaction.json", journal)
            return {"status": "selected", "version": version, "previous_version": previous, "backup": str(backup),
                    "inspected_projects": projects, "other_projects": "not_opened_or_migrated", "running_task_protection": "immutable runtime path and task execution lock; no host hot reload", "smoke": evidence,
                    "host_registration_performed": False, "running_host_reloaded": False}
        except Exception:
            restored = restore_snapshot(app, backup)
            journal.update(phase="rolled_back_after_failure", restoration=restored)
            write_json(app / "transaction.json", journal)
            raise


def rollback(app_root, transaction=None, quiescent=False):
    app, state = layout(app_root)
    if not quiescent:
        raise ValueError("恢复前必须结束本插件写入/关闭相关 stdio 进程，并传 --quiescent；运行中的 SQLite 不能安全回退")
    if not state:
        raise ValueError("尚未安装")
    transaction = transaction or state.get("last_transaction")
    if not transaction or not re.fullmatch(r"[0-9a-f]{32}", transaction):
        raise ValueError("缺少明确可恢复事务 ID")
    with installation_lock(app):
        backup = app / "backups" / transaction
        meta, old_state = validate_snapshot(app, backup)
        # Preserve every post-update change before deliberately rewinding data.
        before, _ = make_snapshot(app, state, meta["projects"], "before-rollback")
        result = restore_snapshot(app, backup)
        write_json(app / "transaction.json", {"phase": "manual_rollback_complete", "backup": str(backup), "safety_backup": str(before), "created_at": now()})
        return dict(result, status="restored", backup=str(backup), post_update_safety_backup=str(before),
                    retained_new_media=True, host_registration_performed=False, running_host_reloaded=False)


def recover(app_root, quiescent=False):
    app, state = layout(app_root)
    journal = read_json(app / "transaction.json")
    if journal.get("phase") != "prepared":
        return {"status": "no_incomplete_transaction", "phase": journal.get("phase")}
    return rollback(app, journal["transaction"], quiescent=quiescent)


def status(app_root):
    app, state = layout(app_root)
    if not state:
        return {"installed": False}
    checks = []
    for version in state["staged_versions"]:
        try:
            verify_deployment(app, version)
            checks.append({"version": version, "valid": True})
        except Exception as exc:
            checks.append({"version": version, "valid": False, "error": str(exc)})
    return {"installed": True, "state": state, "versions": checks, "running_host_version": "unknown_until_film_health_in_target_chat",
            "projects_inspected": False, "config_present": (Path(state["config_root"]) / "user.json").is_file(),
            "catalog_present": Path(state["catalog_path"]).is_file()}


def check_update(app_root, package):
    info = verify_package(package)
    _, state = layout(app_root)
    current = state.get("active_version") if state else None
    return dict(info, current_version=current, update_available=current is None or version_tuple(info["version"]) > version_tuple(current),
                installed=False, switched=False, running_host_reloaded=False)


def deactivate(app_root, uninstall=False):
    app, state = layout(app_root)
    if not state:
        raise ValueError("尚未安装")
    with installation_lock(app):
        write_json(app / "state.json", dict(state, enabled=False))
    return {"status": "unregistered_locally" if uninstall else "disabled_locally", "data_preserved": True, "config_preserved": True,
            "versions_preserved": True, "host_uninstall_performed": False,
            "next": "在桌面插件管理中停用/卸载 film-production-agent；该本地动作没有替宿主操作，也不会删除作品。"}


def host_plan(app_root):
    app, state = layout(app_root)
    if not state or not state.get("enabled") or not state.get("active_version"):
        raise ValueError("没有已启用的本地版本")
    version = state["active_version"]
    verify_deployment(app, version)
    # The source stays fixed to a version. Generating this directory is not CLI installation.
    market = app / "host-marketplaces" / version
    source_plugin = app / "deployments" / version / "plugin"
    market_plugin = market / "plugin"
    if market_plugin.exists():
        source_hashes = {p.relative_to(source_plugin).as_posix(): digest(p) for p in source_plugin.rglob("*") if p.is_file()}
        target_hashes = {p.relative_to(market_plugin).as_posix(): digest(p) for p in market_plugin.rglob("*") if p.is_file()}
        if source_hashes != target_hashes:
            raise ValueError("本机 marketplace 插件副本已改变；拒绝覆盖版本目录")
    else:
        shutil.copytree(source_plugin, market_plugin)
    manifest = {"name": "film-production-local", "interface": {"displayName": "影视开发制作稳定发行"},
                "plugins": [{"name": "film-production-agent", "source": {"source": "local", "path": "./plugin"}, "category": "Productivity",
                             "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}}]}
    write_json(market / ".agents/plugins/marketplace.json", manifest)
    return {"marketplace_root": str(market), "identity": IDENTITY, "version": version,
            "plugin_root": str(app / "deployments" / version / "plugin"), "mcp_config": str(app / "deployments" / version / "plugin/.mcp.json"),
            "host_registration_performed": False,
            "instructions": "使用当前桌面附带 CLI 的 plugin marketplace add / plugin add（先读该版本 --help），或宿主插件界面添加此目录。新聊天执行 film_health 核对实际运行版本；刷新来源和本地 state 不证明现有聊天升级。"}


def duplicates(skill_roots):
    names = ("film-production-agent", "novel-master", "novel-to-screenplay", "director-agent", "vfx-agent", "seedance-prompt", "film-analysis")
    entries = []
    for root in skill_roots:
        base = absolute(root, "skill-root")
        for name in names:
            entry = base / name / "SKILL.md"
            if entry.is_file():
                entries.append({"name": name, "path": str(entry), "sha256": digest(entry), "action": "可逆停用重复个人总控" if name == "film-production-agent" else "保留独立技能；总控内按模块加载，单独使用仍可用"})
    return {"entries": entries, "changed": False}


def migrate_entry(skill_directory, backup_root):
    source = absolute(skill_directory, "skill-directory")
    backup = absolute(backup_root, "backup-root")
    if source.name != "film-production-agent" or not (source / "SKILL.md").is_file():
        raise ValueError("仅接受明确的重复个人 film-production-agent 目录；不会迁移六专业技能")
    if source == backup or source in backup.parents or backup in source.parents:
        raise ValueError("备份目录必须位于技能发现目录树之外")
    # Require outside the parent skills directory, not merely a renamed sibling.
    if source.parent == backup or source.parent in backup.parents:
        raise ValueError("备份不可位于 skills 根目录下，防止宿主仍发现重复入口")
    no_links(source)
    destination = backup / ("film-production-agent-" + uuid.uuid4().hex)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    original = {p.relative_to(source).as_posix(): digest(p) for p in source.rglob("*") if p.is_file()}
    copied = {p.relative_to(destination).as_posix(): digest(p) for p in destination.rglob("*") if p.is_file()}
    if original != copied:
        raise ValueError("旧总控备份校验失败，原目录未动")
    receipt = {"migration_version": 1, "source": str(source), "backup": str(destination), "files": original, "time": now(), "mode": "reversible_move"}
    write_json(destination.parent / (destination.name + ".json"), receipt)
    # Backup is checked before removing only this exact, explicitly named tree.
    shutil.rmtree(source)
    return dict(receipt, receipt_path=str(destination.parent / (destination.name + ".json")), disabled=True, other_skills_changed=False)


def restore_entry(receipt_path):
    receipt = read_json(absolute(receipt_path, "receipt"))
    source = absolute(receipt["source"], "source")
    backup = absolute(receipt["backup"], "backup")
    if source.name != "film-production-agent" or source.exists():
        raise ValueError("恢复目标已存在或不是个人总控；拒绝覆盖")
    actual = {p.relative_to(backup).as_posix(): digest(p) for p in backup.rglob("*") if p.is_file()}
    if actual != receipt["files"]:
        raise ValueError("旧技能备份 SHA-256 校验失败")
    shutil.copytree(backup, source)
    return {"restored": True, "source": str(source), "files": len(actual)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="影视插件 Windows/macOS 安装/检查/恢复。不会联网、扫描作品、调用宿主安装或删除作品。")
    sub = parser.add_subparsers(dest="command", required=True)
    env = sub.add_parser("env"); env.add_argument("--python")
    verify = sub.add_parser("verify"); verify.add_argument("--package", required=True)
    for name in ("install", "stage"):
        p = sub.add_parser(name)
        for flag in ("package", "app-root", "data-root", "config-root"):
            p.add_argument("--" + flag, required=True)
        p.add_argument("--python"); p.add_argument("--catalog-path")
    for name in ("status", "deactivate", "uninstall", "host-plan", "recover", "rollback", "switch", "check-update"):
        p = sub.add_parser(name); p.add_argument("--app-root", required=True)
        if name in ("recover", "rollback"):
            p.add_argument("--quiescent", action="store_true")
        if name == "rollback": p.add_argument("--transaction")
        if name == "switch":
            p.add_argument("--version", required=True); p.add_argument("--project-root", action="append", default=[])
            p.add_argument("--quiescent", action="store_true")
        if name == "check-update": p.add_argument("--package", required=True)
    p = sub.add_parser("duplicates"); p.add_argument("--skill-root", action="append", required=True)
    p = sub.add_parser("migrate-entry"); p.add_argument("--skill-directory", required=True); p.add_argument("--backup-root", required=True)
    p = sub.add_parser("restore-entry"); p.add_argument("--receipt", required=True)
    args = vars(parser.parse_args(argv)); command = args.pop("command")
    actions = {"env": environment, "verify": verify_package, "status": status, "host-plan": host_plan,
               "switch": switch, "rollback": rollback, "recover": recover, "check-update": check_update,
               "migrate-entry": migrate_entry, "restore-entry": restore_entry}
    if command in ("install", "stage"):
        args["activate"] = command == "install"; result = install(**args)
    elif command in ("deactivate", "uninstall"):
        result = deactivate(uninstall=command == "uninstall", **args)
    elif command == "duplicates": result = duplicates(args["skill_root"])
    elif command == "restore-entry": result = restore_entry(args["receipt"])
    elif command == "switch":
        args["project_roots"] = args.pop("project_root"); result = switch(**args)
    else: result = actions[command](**args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError, sqlite3.Error, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)

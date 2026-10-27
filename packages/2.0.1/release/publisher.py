"""Immutable, local-first release publisher. Standard library only; never installs.

The SHA-256 chain detects corruption, not the identity of an untrusted publisher.
Keep the Git origin and release digest in a trusted channel. No command uploads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
import zipfile
import unicodedata

IDENTITY = "film-production-agent@film-production-local"
NAME = "film-production-agent"
MARKETPLACE = "film-production-local"
MANIFEST = "release-manifest.json"
CHANNELS = ("stable", "development")
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_FILES = 20000
TEXT_EXTENSIONS = {".json", ".md", ".py", ".ps1", ".toml", ".yaml", ".yml", ".txt", ".html", ".js", ".css", ".cmd", ".bat", ".sh"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def version_key(value: str) -> tuple:
    match = re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*))?", value)
    if not match:
        raise ValueError("版本必须为 major.minor.patch 或附加预发行标记")
    major, minor, patch, prerelease = match.groups()
    suffix = tuple((0, int(x)) if x.isdigit() else (1, x) for x in re.split(r"[.-]", prerelease or ""))
    return int(major), int(minor), int(patch), prerelease is None, suffix


def valid_version_channel(version: str, channel: str) -> None:
    version_key(version)
    if channel not in CHANNELS:
        raise ValueError("未知发行通道")
    if channel == "stable" and "-" in version:
        raise ValueError("stable 通道拒绝预发行版本")


def safe_name(name: str) -> str:
    """Reject paths ambiguous or dangerous on Windows before any extraction."""
    p = PurePosixPath(name)
    if not name or "\\" in name or name.startswith("/") or p.is_absolute() or name != p.as_posix():
        raise ValueError(f"不安全的包路径: {name}")
    for part in p.parts:
        if part in (".", "..") or any(c in part for c in ':<>"|?*') or part.rstrip(" .") != part or any(ord(c) < 32 for c in part):
            raise ValueError(f"不安全的包路径: {name}")
        if re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part, re.I):
            raise ValueError(f"Windows 保留路径: {name}")
    return name


def validate_names(names: list[str]) -> None:
    normalized = set()
    for name in names:
        safe_name(name)
        key = unicodedata.normalize("NFC", name).casefold()
        if key in normalized:
            raise ValueError(f"重复、大小写或 Unicode 等价冲突路径: {name}")
        normalized.add(key)
    for name in normalized:
        if any(unicodedata.normalize("NFC", parent.as_posix()).casefold() in normalized for parent in PurePosixPath(name).parents if parent.as_posix() != "."):
            raise ValueError(f"文件与目录冲突: {name}")


def inspect_payload(files: dict[str, bytes]) -> list[dict]:
    """Conservative release hygiene gate; it is not a secrets certification."""
    findings = []
    for name, data in files.items():
        parts = {p.casefold() for p in PurePosixPath(name).parts}
        suffix = PurePosixPath(name).suffix.lower()
        if parts & {".project", ".git", "__pycache__", "node_modules", "private", "secrets"} or suffix in {".sqlite", ".sqlite3", ".db", ".pyc", ".pyo", ".pem", ".key", ".mp4", ".mov", ".mp3", ".wav"} or any(p == ".env" or p.startswith(".env.") for p in parts):
            findings.append({"path": name, "reason": "作品、数据库、环境秘密或非发行文件"})
        if suffix not in TEXT_EXTENSIONS and not PurePosixPath(name).name.startswith("LICENSE"):
            continue
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            findings.append({"path": name, "reason": "文本文件不是 UTF-8"})
            continue
        # Reject concrete Windows paths, including JSON-escaped paths. Runtime
        # installers construct paths from user choices rather than hardcoding them.
        if re.search(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/])(?=[^\s<>{}\[\]])", text):
            findings.append({"path": name, "reason": "包含机器绝对盘符路径"})
        if re.search(r"/(?:Users|home)/[^\s/<>{}]+/", text):
            findings.append({"path": name, "reason": "包含机器用户目录"})
        if re.search(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", text):
            findings.append({"path": name, "reason": "疑似秘密"})
        if re.search(r"https://(?:chatgpt\.com|chat\.openai\.com)/(?:c|g|share)/[A-Za-z0-9-]{8,}", text):
            findings.append({"path": name, "reason": "包含私人聊天或共享绑定"})
    return findings


def directory_files(root: Path) -> dict[str, bytes]:
    root = root.resolve(strict=True)
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError(f"发行包拒绝链接: {path.relative_to(root)}")
        if path.is_file():
            if path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("单文件超出限制")
            name = unicodedata.normalize("NFC", path.relative_to(root).as_posix())
            if name in files:
                raise ValueError(f"Unicode 等价冲突路径: {name}")
            files[name] = path.read_bytes()
    validate_names(list(files))
    if len(files) > MAX_FILES or sum(map(len, files.values())) > MAX_TOTAL_BYTES:
        raise ValueError("发行包超出容量限制")
    return files


def validate_manifest(manifest: dict, files: dict[str, bytes]) -> dict:
    if manifest.get("schema_version") != 1 or manifest.get("identity") != IDENTITY:
        raise ValueError("发行清单版本或身份不符")
    valid_version_channel(manifest.get("version", ""), manifest.get("channel", ""))
    items = manifest.get("files")
    if not isinstance(items, list) or not items:
        raise ValueError("清单没有文件列表")
    names = [item["path"] for item in items]
    validate_names(names)
    if MANIFEST in names or set(names) != set(files) - {MANIFEST}:
        raise ValueError("发行包实际文件与清单不一致（缺失或额外文件）")
    for item in items:
        raw = files[item["path"]]
        if len(raw) != item.get("size") or sha256(raw) != item.get("sha256"):
            raise ValueError(f"文件哈希或大小不符: {item['path']}")
    plugin_manifest = "plugin/.codex-plugin/plugin.json"
    if plugin_manifest not in files:
        raise ValueError("缺少兼容插件清单")
    plugin = json.loads(files[plugin_manifest].decode("utf-8-sig"))
    if plugin.get("name") != NAME or plugin.get("version") != manifest["version"]:
        raise ValueError("插件版本或名称与发行清单不一致")
    if "plugin/plugin.json" in files:
        portable = json.loads(files["plugin/plugin.json"].decode("utf-8-sig"))
        if portable.get("name") != NAME or portable.get("version") != manifest["version"]:
            raise ValueError("portable 插件版本或名称不一致")
    lock = manifest.get("modules_lock")
    if lock and (lock.get("path") not in files or sha256(files[lock["path"]]) != lock.get("sha256")):
        raise ValueError("专业模块依赖锁不符")
    findings = inspect_payload({name: content for name, content in files.items() if name != MANIFEST})
    if findings:
        raise ValueError("发行扫描未通过: " + json.dumps(findings, ensure_ascii=False))
    return manifest


def package_files(package: Path) -> dict[str, bytes]:
    if package.is_dir():
        return directory_files(package)
    with zipfile.ZipFile(package) as archive:
        entries = archive.infolist()
        # Directory entries are unnecessary in our format and can conceal path
        # collisions. Only regular file entries are accepted.
        validate_names([entry.filename for entry in entries])
        if len(entries) > MAX_FILES or sum(entry.file_size for entry in entries) > MAX_TOTAL_BYTES:
            raise ValueError("发行包展开后超出容量限制")
        for entry in entries:
            mode = entry.external_attr >> 16
            if entry.is_dir() or stat.S_ISLNK(mode) or entry.flag_bits & 1 or entry.file_size > MAX_FILE_BYTES:
                raise ValueError(f"发行包包含不支持成员: {entry.filename}")
        return {entry.filename: archive.read(entry) for entry in entries}


def verify(package: Path, expected_sha256: str | None = None) -> dict:
    package = Path(package)
    archive_digest = sha256(package.read_bytes()) if package.is_file() else None
    if expected_sha256 and (not archive_digest or archive_digest != expected_sha256.lower()):
        raise ValueError("ZIP SHA-256 不符")
    files = package_files(package)
    if MANIFEST not in files:
        raise ValueError("发行清单缺失")
    manifest = validate_manifest(json.loads(files[MANIFEST].decode("utf-8-sig")), files)
    return {"verified": True, "identity": IDENTITY, "version": manifest["version"], "channel": manifest["channel"],
            "files": len(manifest["files"]), "archive_sha256": archive_digest,
            "manifest_sha256": sha256(files[MANIFEST]), "manifest": manifest, "runtime_changed": False}


def build(payload: Path, output: Path, version: str, channel: str = "stable") -> dict:
    valid_version_channel(version, channel)
    files = directory_files(Path(payload))
    if MANIFEST in files:
        raise ValueError("输入目录已含发行清单；使用干净 payload，禁止覆盖封存包")
    findings = inspect_payload(files)
    if findings:
        raise ValueError("发行扫描未通过: " + json.dumps(findings, ensure_ascii=False))
    manifest = {"schema_version": 1, "identity": IDENTITY, "version": version, "channel": channel,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "runtime": {"python": ">=3.11", "platforms": ["windows", "macos"], "data_schema_min": 2, "data_schema_max": 2},
                "distribution": "source_and_optional_dependency_rights_recorded_in_module_manifest",
                "files": [{"path": name, "sha256": sha256(raw), "size": len(raw)} for name, raw in sorted(files.items())]}
    for name in ("plugin/modules/manifest.json", "plugin/modules/modules-lock.json", "plugin/modules-lock.json"):
        if name in files:
            manifest["modules_lock"] = {"path": name, "sha256": sha256(files[name])}
            break
    files[MANIFEST] = json_bytes(manifest)
    validate_manifest(manifest, files)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"{NAME}-{version}-{channel}.zip"
    metadata = target.with_suffix(".release.json")
    checksum = Path(str(target) + ".sha256")
    if any(path.exists() for path in (target, metadata, checksum)):
        raise FileExistsError("版本已存在，发行版本不可覆盖")
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, raw in sorted(files.items()):
            entry = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(entry, raw)
    result = verify(target)
    record = {"schema_version": 1, "identity": IDENTITY, "version": version, "channel": channel,
              "archive": target.name, "archive_sha256": result["archive_sha256"],
              "manifest_sha256": result["manifest_sha256"], "size": target.stat().st_size,
              "created_at": manifest["created_at"], "runtime_changed": False}
    with metadata.open("xb") as stream:
        stream.write(json_bytes(record))
    with checksum.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(f"{record['archive_sha256']}  {target.name}\n")
    return {**record, "archive_path": str(target.resolve()), "release_record": str(metadata.resolve())}


def git(repo: Path, *args: str) -> str:
    run = subprocess.run(["git", "-c", "core.autocrlf=false", "-C", str(repo), *args],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if run.returncode:
        raise ValueError("Git 操作失败: " + run.stderr.strip())
    return run.stdout.strip()


def init_repo(repo: Path) -> None:
    repo = Path(repo)
    marker = repo / "release-source.json"
    if marker.exists():
        if read_json(marker).get("identity") != IDENTITY or not (repo / ".git").is_dir():
            raise ValueError("发布源身份或 Git 不符")
        return
    if repo.exists() and any(repo.iterdir()):
        raise ValueError("首次发布要求空目录，拒绝接管已有目录")
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "--initial-branch=main")
    write_json(marker, {"schema_version": 1, "identity": IDENTITY,
                        "remote_status": "not_configured", "remote_url": None,
                        "public_release_authorized": False})
    (repo / ".gitattributes").write_text("* -text\n", encoding="utf-8")


def extract_verified(package: Path, destination: Path) -> None:
    verify(package)
    if destination.exists():
        raise FileExistsError("目标版本目录已存在")
    destination.mkdir(parents=True)
    for name, raw in package_files(package).items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)


def publish(package: Path, repo: Path) -> dict:
    """Write an immutable version, update one channel head, commit locally."""
    package, repo = Path(package).resolve(), Path(repo).resolve()
    verified = verify(package)
    if not package.is_file():
        raise ValueError("publish 要求已冻结的 ZIP")
    version, channel = verified["version"], verified["channel"]
    init_repo(repo)
    lock = repo / ".publish.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    try:
        # Do not include caller changes or overwrite an uncommitted release.
        dirty = git(repo, "status", "--porcelain", "--untracked-files=all")
        allowed_initial = {"?? release-source.json", "?? .gitattributes", "?? .publish.lock"}
        if any(line not in allowed_initial for line in dirty.splitlines()):
            raise ValueError("发布仓库有未提交修改，先核查；禁止混入发行提交")
        target = repo / "releases" / channel / version
        if target.exists() or git(repo, "tag", "--list", f"{channel}/v{version}"):
            raise FileExistsError("该版本已发布，不可覆盖")
        channel_root = repo if channel == "stable" else repo / "development"
        payload_root = channel_root / "packages" / version
        target.mkdir(parents=True)
        archive = target / package.name
        shutil.copyfile(package, archive)
        verify(archive, verified["archive_sha256"])
        extract_verified(archive, payload_root)
        record = {"schema_version": 1, "identity": IDENTITY, "version": version, "channel": channel,
                  "archive": archive.relative_to(repo).as_posix(), "archive_sha256": verified["archive_sha256"],
                  "manifest_sha256": verified["manifest_sha256"], "size": archive.stat().st_size}
        write_json(target / "release.json", record)
        (target / (archive.name + ".sha256")).write_text(f"{record['archive_sha256']}  {archive.name}\n", encoding="utf-8")
        index_path = repo / "channels" / f"{channel}.json"
        index = read_json(index_path) if index_path.exists() else {"schema_version": 1, "identity": IDENTITY, "channel": channel, "releases": []}
        index["releases"].append(record)
        index["releases"].sort(key=lambda x: version_key(x["version"]))
        index["latest"] = index["releases"][-1]["version"]
        write_json(index_path, index)
        marketplace_name = MARKETPLACE if channel == "stable" else MARKETPLACE + "-development"
        write_json(channel_root / ".agents/plugins/marketplace.json", {
            "name": marketplace_name, "interface": {"displayName": "影视制作稳定发行" if channel == "stable" else "影视制作开发验证"},
            "plugins": [{"name": NAME, "source": {"source": "local", "path": f"./packages/{index['latest']}/plugin"},
                         "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Productivity"}]})
        # Lock is outside the commit. Explicit allowlist prevents unrelated files
        # introduced by another process from being swept into this release.
        paths = ["release-source.json", ".gitattributes", target.relative_to(repo).as_posix(),
                 payload_root.relative_to(repo).as_posix(), index_path.relative_to(repo).as_posix(),
                 (channel_root / ".agents/plugins/marketplace.json").relative_to(repo).as_posix()]
        git(repo, "add", "--", *paths)
        git(repo, "-c", "user.name=Film Production Release", "-c", "user.email=local-release@invalid", "commit", "-m", f"Release {channel} {version}")
        git(repo, "tag", f"{channel}/v{version}")
        commit = git(repo, "rev-parse", "HEAD")
        return {**record, "git_commit": commit, "git_tag": f"{channel}/v{version}", "remote_published": False,
                "marketplace_root": str(channel_root), "runtime_changed": False}
    finally:
        lock.unlink(missing_ok=True)


def check(repo: Path, installed_version: str | None = None, channel: str = "stable") -> dict:
    if channel not in CHANNELS:
        raise ValueError("未知通道")
    repo = Path(repo).resolve(strict=True)
    index = read_json(repo / "channels" / f"{channel}.json")
    if index.get("identity") != IDENTITY or index.get("channel") != channel or index.get("schema_version") != 1:
        raise ValueError("发布索引身份不符")
    records = index.get("releases", [])
    if not records or len({r["version"] for r in records}) != len(records):
        raise ValueError("发行索引为空或含重复版本")
    for record in records:
        valid_version_channel(record["version"], channel)
        if record.get("identity") != IDENTITY or record.get("channel") != channel:
            raise ValueError("发行记录身份或通道不符")
        safe_name(record["archive"])
        if not (repo / record["archive"]).resolve().is_relative_to(repo):
            raise ValueError("发行记录路径越界")
    latest = max(records, key=lambda r: version_key(r["version"]))
    if latest["version"] != index.get("latest"):
        raise ValueError("latest 指针与索引不一致")
    result = verify(repo / latest["archive"], latest["archive_sha256"])
    if result["version"] != latest["version"] or result["manifest_sha256"] != latest["manifest_sha256"]:
        raise ValueError("索引与实际包不一致")
    available = installed_version is None or version_key(latest["version"]) > version_key(installed_version)
    return {"identity": IDENTITY, "channel": channel, "installed_version": installed_version,
            "latest": latest["version"], "update_available": available, "release": latest,
            "runtime_changed": False, "remote_refreshed": False,
            "note": "仅检查明确的本地发布源；下载、安装和运行中聊天切换是不同步骤"}


def fetch(repo: Path, destination: Path, version: str | None = None, channel: str = "stable", expected_sha256: str | None = None) -> dict:
    state = check(repo, channel=channel)
    records = read_json(Path(repo) / "channels" / f"{channel}.json")["releases"]
    record = next((r for r in records if r["version"] == (version or state["latest"])), None)
    if record is None:
        raise ValueError("未找到指定版本")
    origin = Path(repo) / record["archive"]
    verify(origin, expected_sha256 or record["archive_sha256"])
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / origin.name
    if target.exists():
        verify(target, record["archive_sha256"])
        status = "already_fetched_verified"
    else:
        # Exclusive temp + rename avoid exposing a partial ZIP as complete.
        temporary = target.with_name(target.name + ".partial")
        with origin.open("rb") as src, temporary.open("xb") as dst:
            shutil.copyfileobj(src, dst)
        verify(temporary, record["archive_sha256"])
        if target.exists():
            raise FileExistsError("获取期间目标已出现，请核验")
        temporary.rename(target)
        status = "fetched_verified"
    return {"status": status, "version": record["version"], "path": str(target.resolve()),
            "archive_sha256": record["archive_sha256"], "runtime_changed": False}


def main() -> None:
    parser = argparse.ArgumentParser(description="影视制作发行：构建、只读核验、本地 Git 发布、检查与获取；不安装、不联网上传")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build")
    p.add_argument("--payload", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--channel", choices=CHANNELS, default="stable")
    p = sub.add_parser("verify")
    p.add_argument("package", type=Path)
    p.add_argument("--sha256")
    p = sub.add_parser("publish")
    p.add_argument("package", type=Path)
    p.add_argument("--repo", type=Path, required=True)
    p = sub.add_parser("check")
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--installed-version")
    p.add_argument("--channel", choices=CHANNELS, default="stable")
    p = sub.add_parser("fetch")
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--destination", type=Path, required=True)
    p.add_argument("--version")
    p.add_argument("--channel", choices=CHANNELS, default="stable")
    p.add_argument("--sha256")
    args = parser.parse_args()
    try:
        if args.command == "build":
            result = build(args.payload, args.output, args.version, args.channel)
        elif args.command == "verify":
            result = verify(args.package, args.sha256)
            result.pop("manifest", None)
        elif args.command == "publish":
            result = publish(args.package, args.repo)
        elif args.command == "check":
            result = check(args.repo, args.installed_version, args.channel)
        else:
            result = fetch(args.repo, args.destination, args.version, args.channel, args.sha256)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        parser.exit(2, f"发行操作失败：{error}\n")


if __name__ == "__main__":
    main()

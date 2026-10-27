"""Install a checksum-pinned Blender into an ephemeral macOS CI directory only.

4.5 LTS is the final upstream release family supporting Intel Macs. Sources:
https://www.blender.org/download/requirements/
https://download.blender.org/release/Blender4.5/blender-4.5.15.sha256
This is a CI helper, never an installer dependency or automatic user download.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request

VERSION = "4.5.15"
ARCHIVES = {
    "arm64": ("blender-4.5.15-macos-arm64.dmg", "bfbc0bda099d1ab7aef0992a584f872f58bed9bb491210ad45f9ca071aa2e688"),
    "x86_64": ("blender-4.5.15-macos-x64.dmg", "3801a97619292a012ede0e855ee705ae872a680474845297b777254f7f21ed78"),
}


def main():
    if sys.platform != "darwin" or not os.environ.get("RUNNER_TEMP") or not os.environ.get("GITHUB_ENV"):
        raise SystemExit("This helper only runs in an explicit macOS GitHub Actions environment")
    name, digest = ARCHIVES[platform.machine()]
    target = Path(tempfile.mkdtemp(prefix="TEST-blender-", dir=os.environ["RUNNER_TEMP"]))
    archive, mount = target / name, target / "mount"
    url = "https://download.blender.org/release/Blender4.5/" + name
    with urllib.request.urlopen(url, timeout=120) as response, archive.open("xb") as output:
        shutil.copyfileobj(response, output)
    with archive.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != digest:
            raise RuntimeError("Official Blender archive checksum mismatch; refusing to mount")
    mount.mkdir()
    subprocess.run(["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(archive)], check=True, timeout=120)
    try:
        subprocess.run(["ditto", str(mount / "Blender.app"), str(target / "Blender.app")], check=True, timeout=180)
    finally:
        subprocess.run(["hdiutil", "detach", str(mount)], check=True, timeout=60)
    executable = target / "Blender.app/Contents/MacOS/Blender"
    version = subprocess.check_output([str(executable), "--version"], text=True, timeout=60).splitlines()[0]
    if version not in ("Blender " + VERSION, "Blender " + VERSION + " LTS"):
        raise RuntimeError("Downloaded Blender reports an unexpected version")
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as environment:
        environment.write(f"FILMPROD_CI_BLENDER={executable}\n")
    print(json.dumps({"blender": version, "architecture": platform.machine(), "source": url, "sha256": digest}))


if __name__ == "__main__":
    main()

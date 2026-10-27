"""Exercise a real release in disposable TEST directories on each CI platform."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from filmprod import __version__
from release import assemble, installer, publisher
from release.ci_previs_smoke import run_previs


def run_json(command, *, env=None, cwd=None):
    result = subprocess.run(command, env=env, cwd=cwd, capture_output=True,
                            text=True, encoding="utf-8", timeout=90)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return json.loads(result.stdout)


def main():
    with tempfile.TemporaryDirectory(prefix="fp-CI-") as temporary:
        root = Path(temporary).resolve()
        payload = root / "payload"
        assemble.assemble(SOURCE, payload)
        published = SOURCE / "releases/stable" / __version__ / f"film-production-agent-{__version__}-stable.zip"
        if published.is_file():
            package = published
            files = publisher.package_files(package)
            assert {k: v for k, v in files.items() if k != publisher.MANIFEST} == publisher.directory_files(payload), "Frozen release differs from source"
            package_origin = "frozen_release"
        else:
            package = Path(publisher.build(payload, root / "archives", __version__)["archive_path"])
            package_origin = "assembled_source"
        verified = publisher.verify(package)
        assert verified["version"] == __version__
        app, data, config = (root / "应用 空格", root / "数据", root / "配置")
        # Run the installer shipped in the artifact, not just the source copy.
        unpacked = root / "unpacked"
        publisher.extract_verified(package, unpacked)
        install_result = run_json([
            sys.executable, "-X", "utf8", "-B", str(unpacked / "install.py"), "install",
            "--package", str(package), "--app-root", str(app),
            "--data-root", str(data), "--config-root", str(config),
        ], cwd=root)
        assert install_result["status"] == "installed"
        health = install_result["smoke"]["health"]
        assert health["version"] == __version__ and health["runtime_isolated"]
        assert health["modules"]["verified"] and health["modules"]["count"] == 8
        assert install_result["smoke"]["tool_count"] == 26
        assert install_result["host_registration_performed"] is False
        host = installer.host_plan(app)
        assert host["host_registration_performed"] is False
        server = installer.read_json(Path(host["plugin_root"]) / ".mcp.json")["mcpServers"]["film-production"]
        assert Path(server["command"]).is_absolute()
        entries = sorted(p.name for p in (Path(host["plugin_root"]) / "skills").iterdir()
                         if (p / "SKILL.md").is_file())
        assert entries == ["film-art-director", "film-brainstorm-interface", "film-director",
                           "film-production-agent", "film-screenwriter"]
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("FILMPROD_") and k not in ("PYTHONPATH", "PYTHONHOME")}
        env.update(server["env"])
        # Finder-launched apps may not inherit the shell's Homebrew paths.
        if sys.platform == "darwin":
            env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
        runtime = Path(host["plugin_root"]) / "runtime"
        work = root / "TEST 剧本 空格"
        code = r'''
import json,sys,subprocess
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from filmprod.core import Registry
from filmprod.render import _exe,probe
work=Path(sys.argv[2]); work.mkdir()
r=Registry(work)
try:
 r.dispatch('project.init',{'op_id':'TEST-init','project_id':'TEST-MAC-COMPAT','title':'TEST 合成项目','test_only':True})
 r.dispatch('artifact.save',{'op_id':'TEST-save','artifact_id':'TEST-SCRIPT','kind':'screenplay','scope':'TEST','content':'中文与空格路径测试','base_version':0})
 assert r._artifact('TEST-SCRIPT',1)['content']=='中文与空格路径测试'
finally:r.close()
video=work/'TEST 色块.mp4'
ffmpeg=_exe('ffmpeg');ffprobe=_exe('ffprobe')
subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-f','lavfi','-i','color=c=blue:s=160x90:r=24:d=0.5','-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True)
info=probe(video)
assert any(s['codec_type']=='video' and s['width']==160 for s in info['streams'])
print(json.dumps({'project_write_read':True,'media_encode_probe':True,'ffmpeg':ffmpeg,'ffprobe':ffprobe}))
'''
        packaged = run_json([server["command"], "-I", "-X", "utf8", "-B", "-c", code, str(runtime), str(work)], env=env, cwd=root)
        if sys.platform == "darwin":
            bootstrap = run_json(["/bin/bash", str(unpacked / "release/bootstrap.sh"), "env"], env=env, cwd=root)
            assert bootstrap["platform_supported"] is True
        blender = os.environ.get("FILMPROD_CI_BLENDER")
        if sys.platform == "darwin" and os.environ.get("GITHUB_ACTIONS") == "true" and not blender:
            raise RuntimeError("macOS CI requires its pinned Blender for actual packaged rendering")
        previs = (run_previs(host["plugin_root"], server["command"], root / "TEST 预演 空格", blender, env)
                  if blender else {"status": "not_run", "reason": "No explicit CI Blender supplied"})
        receipt = {
            "version": __version__, "system": platform.system(), "architecture": platform.machine(),
            "python": platform.python_version(), "package_origin": package_origin,
            "archive_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
            "modules": 8, "tools": 26, "skill_entries": entries, "runtime_isolated": True,
            "unicode_space_paths": True, "gui_path_tested": sys.platform == "darwin",
            "packaged_runtime": packaged, "previs": previs, "native_desktop_ui_verified": False,
            "source_commit": os.environ.get("GITHUB_SHA"),
        }
        target = SOURCE / "work/ci-compatibility.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

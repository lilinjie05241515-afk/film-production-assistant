"""Actual packaged Blender render and readback using a tiny synthetic scene."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


def synthetic_plan():
    return {
        "schema_version": 1, "fps": 4, "frames": 4, "width": 160, "height": 90,
        "space": {
            "visible_structure": "TEST synthetic floor and pillar",
            "assumed_dimensions": "TEST arbitrary metres",
            "unseen_areas": "TEST none",
            "allowed_adjustments": "TEST only",
            "boxes": [
                {"id": "floor", "position": [0, 0, -0.1], "size": [10, 10, 0.2]},
                {"id": "pillar", "position": [0, 0, 1.5], "size": [0.5, 0.5, 3]},
            ],
        },
        "actors": [{
            "id": "A", "name": "TEST actor", "color": "#ee6633",
            "keys": [{"frame": 0, "position": [-2, 1, 0], "yaw": 0},
                     {"frame": 4, "position": [2, 1, 0], "yaw": 90}],
        }],
        "shots": [
            {"id": "SH010", "start": 0, "end": 2, "method": "TEST wide",
             "camera": [{"frame": 0, "position": [5, -7, 4], "target": [0, 0, 1]},
                        {"frame": 2, "position": [4, -6, 3], "target": [0, 0, 1]}]},
            {"id": "SH020", "start": 2, "end": 4, "method": "TEST reverse",
             "camera": [{"frame": 2, "position": [-5, -5, 3], "target": [0, 1, 1]},
                        {"frame": 4, "position": [-4, -4, 3], "target": [1, 1, 1]}]},
        ],
    }


BLEND_CHECK = r'''
import bpy,json,sys,math
from pathlib import Path
plan_path,report_path=sys.argv[sys.argv.index('--')+1:]
plan=json.loads(Path(plan_path).read_text(encoding='utf-8'))
assert json.loads(bpy.data.texts['PREVIS_PLAN.json'].as_string())==plan
scene=bpy.context.scene
assert scene.frame_start==1 and scene.frame_end==plan['frames']
for frame in range(plan['frames']):
    scene.frame_set(frame+1)
    shot=next(s for s in plan['shots'] if s['start']<=frame<s['end'])
    assert scene.camera.name==shot['id'], (frame,scene.camera.name)
    actor=bpy.data.objects['A-root']
    expected=[-2+frame,1,0]
    assert max(abs(x-y) for x,y in zip(actor.location,expected))<0.001
    assert abs(math.degrees(actor.rotation_euler.z)-22.5*frame)<0.001
Path(report_path).write_text(json.dumps({'opened_in_blender':True,'embedded_plan_matches':True,
    'frames_checked':plan['frames'],'camera_cuts_checked':2,'actor_motion_checked':True,
    'saved':False,'subjective_review':'pending'}),encoding='utf-8')
'''


def run_previs(plugin, python, work, blender, env):
    """All executing product scripts come from the installed package."""
    plugin, work = Path(plugin), Path(work)
    work.mkdir()
    plan = work / "TEST 计划.json"
    plan.write_text(json.dumps(synthetic_plan(), ensure_ascii=False), encoding="utf-8")
    out = work / "TEST 双画面"
    command = [python, "-I", "-X", "utf8", "-B",
               str(plugin / "modules/director-agent/previs/execute.py"),
               "--plan", str(plan), "--out", str(out), "--blender", str(blender),
               "--engine", "CYCLES"]
    execution = subprocess.run(command, env=env, capture_output=True, text=True,
                               encoding="utf-8", timeout=360)
    if execution.returncode:
        logs = "\n".join(p.read_text(encoding="utf-8", errors="replace")[-8000:]
                         for p in sorted(out.glob("*.log")))
        raise RuntimeError("Packaged previs render failed:\n" + execution.stderr + execution.stdout + logs)
    receipt = json.loads(execution.stdout)
    assert receipt["frames"] == 4 and receipt["fps"] == 4
    assert receipt["render_engine"] == "CYCLES" and receipt["render_device"] == "CPU"
    assert receipt["subjective_review"] == "pending"
    for view in ("camera", "top"):
        info = receipt["probes"][view]
        assert (info["frames"], info["width"], info["height"], info["duration"]) == (4, 160, 90, 1.0)
        assert hashlib.sha256((out / (view + ".mp4")).read_bytes()).hexdigest() == receipt["files"][view]
    assert receipt["files"]["camera"] != receipt["files"]["top"]
    assert hashlib.sha256((out / "scene.blend").read_bytes()).hexdigest() == receipt["files"]["blend"]
    check_script, check_report = work / "TEST readback.py", work / "TEST readback.json"
    check_script.write_text(BLEND_CHECK, encoding="utf-8")
    checked = subprocess.run([str(blender), "--background", "--disable-autoexec",
                              str(out / "scene.blend"), "--python-exit-code", "1",
                              "--python", str(check_script), "--", str(out / "plan.json"), str(check_report)],
                             env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    if checked.returncode:
        raise RuntimeError("Blender readback failed:\n" + checked.stdout + checked.stderr)
    return {"status": "passed", "packaged_renderer": True, "synthetic_only": True,
            "blender_version": receipt["blender_version"], "frames_per_view": 4,
            "render_engine": "CYCLES", "render_device": "CPU",
            "views": ["camera", "top"], "decoded_frames_and_duration": True,
            "blend_readback": json.loads(check_report.read_text(encoding="utf-8")),
            "subjective_review": "pending"}

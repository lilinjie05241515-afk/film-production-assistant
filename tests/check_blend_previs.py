"""Read-only check of an actually opened .blend. Does not save the scene."""
import bpy
import json
import math
import sys
from pathlib import Path
plan_path,out=sys.argv[sys.argv.index('--')+1:]
m=json.loads(Path(plan_path).read_text(encoding='utf-8'));scene=bpy.context.scene;errors=[]
if json.loads(bpy.data.texts['PREVIS_PLAN.json'].as_string())!=m:errors.append('embedded plan mismatch')
observations=[]
for f in range(m['frames']):
    scene.frame_set(f+1);shot=next(s for s in m['shots'] if s['start']<=f<s['end'])
    if scene.camera.name!=shot['id']:errors.append(f'camera mismatch {f}')
    for a in m['actors']:
        for p,q in zip(a['keys'],a['keys'][1:]):
            if p['frame']<=f<=q['frame']:break
        t=(f-p['frame'])/(q['frame']-p['frame']);expected=[x+(y-x)*t for x,y in zip(p['position'],q['position'])]
        actual=list(bpy.data.objects[a['id']+'-root'].location)
        if max(abs(x-y) for x,y in zip(actual,expected))>0.001:errors.append(f'position mismatch {f} {a["id"]}')
        if f in {0,71,72,143,144,m['frames']-1}:observations.append({'frame':f,'shot_id':shot['id'],'actor':a['id'],'position':actual,'yaw':math.degrees(bpy.data.objects[a['id']+'-root'].rotation_euler.z)})
report={'blend':bpy.data.filepath,'opened_in_blender':True,'frames_checked':m['frames'],'actor_samples_checked':m['frames']*len(m['actors']),
        'camera_markers':len(scene.timeline_markers),'errors':errors,'cut_observations':observations,'saved':False,'subjective_directing_acceptance':False}
Path(out).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
if errors:raise RuntimeError(str(errors[:10]))
print('BLEND_READONLY_QC_OK',m['frames'])

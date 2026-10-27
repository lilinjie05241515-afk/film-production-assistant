"""Compose current exact shot choices into a NEW plan; reject continuity gaps."""
import argparse
import copy
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from execute import validate_plan
from filmprod.core import Registry


def interpolate(keys,f):
    for a,b in zip(keys,keys[1:]):
        if a['frame']<=f<=b['frame']:
            t=(f-a['frame'])/(b['frame']-a['frame']);return {'frame':f,'position':[x+(y-x)*t for x,y in zip(a['position'],b['position'])],
                'yaw':a['yaw']+((b['yaw']-a['yaw']+180)%360-180)*t}
    raise ValueError('无法采样衔接边界')


def compose(s):
    versions={v['version']:v for v in s['versions']};latest=s['versions'][-1]['manifest'];result=copy.deepcopy(latest)
    result['shots']=[];result['actors']=[dict(a,keys=[]) for a in latest['actors']];cursor=0;origin=None;provenance=[]
    for shot in latest['shots']:
        c=s['shot_choices'].get(shot['id'])
        if not c:raise ValueError('每个镜头都需有准确选择')
        v=versions[c['version']]
        if v['sha256']!=c['sha256'] or v.get('stale_reasons'):raise ValueError('选择摘要或来源已变化')
        m=v['manifest']
        if origin is None:origin=m
        if m['space']!=origin['space'] or m['fps']!=origin['fps'] or {a['id']:a['color'] for a in m['actors']}!={a['id']:a['color'] for a in origin['actors']}:
            raise ValueError('混选空间、帧率或角色身份不一致，需导演处理')
        sh=next(x for x in m['shots'] if x['id']==shot['id']);start,end=sh['start'],sh['end'];offset=cursor-start
        for dst in result['actors']:
            src=next(x for x in m['actors'] if x['id']==dst['id']);a=interpolate(src['keys'],start);b=interpolate(src['keys'],end)
            if dst['keys']:
                last=dst['keys'][-1];distance=sum((x-y)**2 for x,y in zip(last['position'],a['position']))**0.5;angle=abs((last['yaw']-a['yaw']+180)%360-180)
                if distance>0.02 or angle>1:raise ValueError(f"切点 {shot['id']} / {dst['id']} 不连续：{distance:.3f} m / {angle:.2f} deg")
            rows=[a]+[k for k in src['keys'] if start<k['frame']<end]+[b]
            dst['keys'].extend(dict(k,frame=k['frame']+offset) for k in (rows[1:] if dst['keys'] else rows))
        result['shots'].append(dict(sh,start=cursor,end=cursor+end-start,camera=[dict(k,frame=k['frame']+offset) for k in sh['camera']]))
        cursor+=end-start;provenance.append({'shot_id':shot['id'],**c})
    result.update(frames=cursor,composition={'source_choices':provenance,'boundary_check':'position <= 0.02 m; yaw <= 1 degree','subjective_continuity':'pending'})
    return validate_plan(result)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True);p.add_argument('--project-id',required=True);p.add_argument('--previs-id',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    r=Registry.open_readonly(a.root)
    try:s=r.dispatch('previs.read',{'expected_project_id':a.project_id,'previs_id':a.previs_id})['series'][0];m=compose(s)
    finally:r.close()
    with Path(a.out).open('x',encoding='utf-8') as f:json.dump(m,f,ensure_ascii=False,indent=2)
    print('新计划已生成，待执行、实际画面检查、登记与用户选择；没有批准新整段。')

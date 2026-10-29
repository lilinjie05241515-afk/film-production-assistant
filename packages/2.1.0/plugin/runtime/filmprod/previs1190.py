"""Exact, immutable previs deliveries in the existing project Registry.

No renderer, chat sender, HTTP listener or subprocess is reachable from this module.
Media is transported as bounded chunks, checked against the registered full file.
"""
import base64
import hashlib
import json
import math
import re
from pathlib import Path
from .board1150 import _fields, _read, _write

PREFIX = 'previs1190/'
READ_ACTIONS = {'previs.read', 'previs.chunk'}
WRITE_ACTIONS = {'previs.register', 'previs.feedback', 'previs.select'}
MAX_CHUNK = 192 * 1024
MAX_VIDEO = 128 * 1024 * 1024


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def ident(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        raise ValueError('预演及镜头编号须为稳定字母、数字、下划线或短横线')
    return value


def text(value, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('需要非空原文，且不得超长')
    return value  # Preserve user quote verbatim, including newlines and spaces.


def number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError('时间和坐标必须为有限数值')
    return value


def file_ref(root, ref, suffixes=None):
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
        raise ValueError('文件必须包含准确相对 path 和 sha256')
    rel = ref['path']
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or '\\' in rel or '..' in Path(rel).parts:
        raise ValueError('仅接受项目内相对路径')
    target = Path(root) / rel
    for p in (target, *target.parents):
        if p == Path(root):
            break
        if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
            raise ValueError('不能通过链接读取项目外文件')
    target = target.resolve()
    if Path(root).resolve() not in target.parents or not target.is_file():
        raise ValueError('文件缺失或越出项目目录')
    if suffixes and target.suffix.lower() not in suffixes:
        raise ValueError('文件类型不匹配')
    if sha(target) != ref['sha256']:
        raise ValueError('文件摘要变化，请重新交付')
    return target


def validate_plan(m):
    """Shared contract for the renderer and registry; times use integer frames."""
    if not isinstance(m, dict) or m.get('schema_version') != 1:
        raise ValueError('不支持的预演计划版本')
    for key in ('fps', 'frames'):
        if type(m.get(key)) is not int or m[key] < 1:
            raise ValueError('fps / frames 必须是正整数')
    if m['fps'] > 60 or m['frames'] / m['fps'] > 1800:
        raise ValueError('首版支持最多 60 fps / 30 分钟；请拆分场次')
    for key,maximum in (('width',1920),('height',1080)):
        value=m.get(key,640 if key=='width' else 360)
        if type(value)is not int or not 64<=value<=maximum or value%2:
            raise ValueError('审看尺寸须为偶数，范围 64 至 1920×1080')
    shots = m.get('shots', [])
    cursor = 0; ids = set()
    for s in shots:
        sid = ident(s['id'])
        if sid in ids or type(s.get('start')) is not int or type(s.get('end')) is not int or s['start'] != cursor or s['end'] <= cursor:
            raise ValueError('镜头必须唯一、连续，使用 [start,end) 帧范围')
        ids.add(sid); cursor = s['end']
        text(s['method'])
        keys(s['camera'], s['start'], s['end'], ('position','target'), angle=False)
    if cursor != m['frames']:
        raise ValueError('镜头范围未覆盖完整时长')
    actors = m.get('actors', [])
    if not actors or len({ident(a['id']) for a in actors}) != len(actors):
        raise ValueError('角色身份缺失或重复')
    colors = set()
    for a in actors:
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', a['color']) or a['color'].lower() in colors:
            raise ValueError('人物必须使用固定且互不相同的颜色')
        colors.add(a['color'].lower()); text(a['name'],100)
        keys(a['keys'], 0, m['frames'], ('position',), angle=True)
    for box in m.get('space', {}).get('boxes', []):
        ident(box['id'])
        for k in ('position', 'size'):
            vector(box[k])
        if min(box['size']) <= 0:
            raise ValueError('空间尺寸必须为正值')
    space=m.get('space', {})
    for k in ('visible_structure','assumed_dimensions','unseen_areas','allowed_adjustments'):
        text(space.get(k))
    return m


def vector(v):
    if not isinstance(v,list) or len(v)!=3:
        raise ValueError('位置须为三个数值')
    for n in v:number(n)


def keys(rows, start, end, vectors, angle):
    if not isinstance(rows,list) or len(rows)<2 or rows[0].get('frame')!=start or rows[-1].get('frame')!=end:
        raise ValueError('关键帧必须覆盖完整范围含结束边界')
    previous=start-1
    for k in rows:
        f=k.get('frame')
        if type(f)is not int or not previous<f<=end:
            raise ValueError('关键帧必须递增')
        previous=f
        for v in vectors:vector(k[v])
        if angle:number(k['yaw'])


def all_rows(r, suffix):
    prefix=PREFIX+suffix
    return [json.loads(row[0]) for row in r.db.execute('SELECT value FROM settings WHERE substr(key,1,?)=? ORDER BY key',(len(prefix),prefix))]


def series(r, pid):
    return _read(r,PREFIX+'series/'+ident(pid)) or {'previs_id':pid,'revision':0,'versions':[], 'shot_choices':{},'approved_version':None,'decisions':[],'feedback':[]}


def version(r,p):
    s=series(r,p['previs_id'])
    v=next((v for v in s['versions'] if v['version']==p.get('version')),None)
    if not v or v['sha256']!=p.get('expected_sha256'):
        raise ValueError('预演版本或摘要不匹配，请重新读取')
    return s,v


def stale(r,v):
    reasons=[]
    for role,ref in v['sources'].items():
        current=r._artifact(ref['artifact_id'])
        if not current or current['sha256']!=ref['sha256'] or current['version']!=ref['version']:
            reasons.append(role+'已有其他版本，须由导演复核依赖')
    return reasons


def view(r):
    rows=all_rows(r,'series/')
    for s in rows:
        for v in s['versions']:v['stale_reasons']=stale(r,v)
        s['assembly_required']=len({c['version'] for c in s['shot_choices'].values()})>1
    return {'series':rows,'frame_accuracy':'ordinary_video_seek','render_on_browse':False}


def revision(p,s):
    from .core import ConflictError
    if type(p.get('base_revision'))is not int or p['base_revision']!=s['revision']:
        raise ConflictError('预演记录已变化，请刷新后再操作')


def register(r,p):
    from .core import canonical, now
    _fields(p, {'op_id','expected_project_id','base_revision','previs_id','task_id','scope','title','manifest','sources','files','change_note','feedback_ids'},
            {'op_id','expected_project_id','base_revision','previs_id','task_id','scope','title','manifest','sources','files','change_note','feedback_ids'})
    s=series(r,p['previs_id']);revision(p,s)
    task=r.db.execute('SELECT data FROM tasks WHERE task_id=?',(p['task_id'],)).fetchone()
    if not task:raise ValueError('需要准确导演任务')
    task=json.loads(task[0])
    from .modules import require_execution
    require_execution(task)
    if task['module'] not in {'director','director-agent'} or task['scope']!=p['scope']:
        raise ValueError('预演范围必须对应导演任务')
    if s['versions'] and (s['task_id']!=p['task_id'] or s['scope']!=p['scope']):
        raise ValueError('不能改变预演所属任务或场次')
    refs=p['sources']
    if not isinstance(refs,dict) or set(refs)!={'script','director'}:raise ValueError('需要准确剧本和导演方案来源')
    for role,ref in refs.items():
        if not isinstance(ref,dict) or set(ref)!={'artifact_id','version','sha256'}:raise ValueError('来源须含精确身份、版本和摘要')
        a=r._artifact(ref['artifact_id'],ref['version'])
        if not a or a['sha256']!=ref['sha256'] or a['kind'] not in ({'director'} if role=='director' else {'script','screenplay','source_script'}):
            raise ValueError('来源版本、摘要或类型不匹配')
    if {k:refs['script'][k] for k in ('artifact_id','version')} not in task.get('inputs',[]):
        raise ValueError('剧本来源不属于导演任务的冻结输入；请按原任务流程复核依赖')
    m=validate_plan(p['manifest'])
    files=p['files']
    if not isinstance(files,dict) or set(files)!={'blend','camera','top','plan','receipt'}:
        raise ValueError('交付需 .blend、完整镜头/俯视视频、计划与渲染回执')
    paths={k:file_ref(r.root,ref,{'.blend'} if k=='blend' else {'.mp4'} if k in {'camera','top'} else {'.json'}) for k,ref in files.items()}
    if json.loads(paths['plan'].read_text(encoding='utf-8'))!=m:raise ValueError('工程计划与登记计划不一致')
    receipt=json.loads(paths['receipt'].read_text(encoding='utf-8'))
    if receipt.get('plan_sha256')!=files['plan']['sha256'] or receipt.get('frames')!=m['frames'] or receipt.get('fps')!=m['fps']:
        raise ValueError('渲染回执与计划不一致')
    for k in ('blend','camera','top'):
        if receipt.get('files',{}).get(k)!=files[k]['sha256']:raise ValueError('渲染回执文件摘要不匹配')
    for k in ('camera','top'):
        probe=receipt.get('probes',{}).get(k,{})
        if probe.get('frames')!=m['frames'] or abs(probe.get('duration',0)-m['frames']/m['fps'])>1/m['fps']:
            raise ValueError('视频帧数/时长与计划不一致')
        if probe.get('width')!=m.get('width',640) or probe.get('height')!=m.get('height',360):
            raise ValueError('审看视频画幅与计划不一致')
        if paths[k].stat().st_size>MAX_VIDEO:raise ValueError('审看视频超过 128 MiB，请降低审看码率，保持完整时长')
    if m.get('reference_image'):file_ref(r.root,m['reference_image'],{'.png','.jpg','.jpeg'})
    if s['versions']:
        prev=s['versions'][-1]['manifest']
        if {a['id']:a['color'] for a in prev['actors']}!={a['id']:a['color'] for a in m['actors']}:
            raise ValueError('同一场次版本必须保留角色身份与颜色')
        if [x['id'] for x in prev['shots']] != [x['id'] for x in m['shots']]:
            raise ValueError('同一审看序列须保持镜头编号；重分镜请新建预演范围')
    if not isinstance(p['feedback_ids'],list) or any(i not in {f['id'] for f in s['feedback']} for i in p['feedback_ids']):
        raise ValueError('修订须指向本预演准确反馈')
    v={'version':len(s['versions'])+1,'manifest':m,'sources':refs,'files':files,
       'change_note':text(p['change_note']), 'feedback_ids':p['feedback_ids'], 'created_at':now()}
    v['sha256']=hashlib.sha256(canonical(v).encode()).hexdigest()
    s.update(task_id=p['task_id'],scope=p['scope'],title=text(p['title'],200),revision=s['revision']+1)
    s['versions'].append(v)
    _write(r,PREFIX+'series/'+p['previs_id'],s)
    return {'series':s,'registered':v,'adopted':False}


def feedback(r,p):
    from .core import now
    _fields(p,{'op_id','expected_project_id','previs_id','version','expected_sha256','base_revision','shot_id','time','quote'},
            {'op_id','expected_project_id','previs_id','version','expected_sha256','base_revision','shot_id','time','quote'})
    s,v=version(r,p);revision(p,s)
    shot=next((x for x in v['manifest']['shots'] if x['id']==p['shot_id']),None)
    t=number(p['time']);fps=v['manifest']['fps']
    if not shot or not shot['start']/fps<=t<shot['end']/fps:raise ValueError('时间位置不在所指镜头范围')
    row={'id':p['op_id'],'version':v['version'],'sha256':v['sha256'],'shot_id':shot['id'],'time':t,'quote':text(p['quote']),
         'created_at':now(),'synthetic':bool(r._project().get('test_only'))}
    s['feedback'].append(row);s['revision']+=1;_write(r,PREFIX+'series/'+p['previs_id'],s)
    return {'feedback':row,'revision':s['revision'],'execution_started':False}


def select(r,p):
    from .core import now, ConflictError
    _fields(p,{'op_id','expected_project_id','previs_id','version','expected_sha256','base_revision','shot_id','confirmed'},
            {'op_id','expected_project_id','previs_id','version','expected_sha256','base_revision','confirmed'})
    if 'shot_id' not in p:raise ValueError('须明确 shot_id 或 null 表示整段')
    s,v=version(r,p);revision(p,s)
    if p['confirmed'] is not True:raise ValueError('需要用户明确点击通过')
    if stale(r,v):raise ConflictError('来源有新版，请导演复核并重新登记准确交接版本')
    for k,ref in v['files'].items():file_ref(r.root,ref)
    ids=[x['id'] for x in v['manifest']['shots']]
    if p['shot_id'] is not None and p['shot_id'] not in ids:raise ValueError('镜头不存在')
    row={'id':p['op_id'],'version':v['version'],'sha256':v['sha256'],'shot_id':p['shot_id'],'created_at':now(),
         'synthetic':bool(r._project().get('test_only')),'actor':{'source':'panel-click','identity_verified':False}}
    choice={'version':v['version'],'sha256':v['sha256']}
    for sid in ([p['shot_id']] if p['shot_id'] else ids):s['shot_choices'][sid]=choice
    # A shot decision never implicitly approves a whole reel, even if all choices match.
    if p['shot_id'] is None:s['approved_version']=choice
    s['decisions'].append(row);s['revision']+=1
    _write(r,PREFIX+'series/'+p['previs_id'],s)
    return {'decision':row,'revision':s['revision'],'assembly_required':len({x['version'] for x in s['shot_choices'].values()})>1}


def read(r,action,p):
    r.check_project_identity(p.get('expected_project_id'))
    if action=='previs.read':
        _fields(p,{'expected_project_id','previs_id'},{'expected_project_id'})
        data=view(r)
        if p.get('previs_id'):data['series']=[s for s in data['series'] if s['previs_id']==ident(p['previs_id'])]
        return data
    _fields(p,{'expected_project_id','previs_id','version','expected_sha256','view','offset'},
            {'expected_project_id','previs_id','version','expected_sha256','view','offset'})
    s,v=version(r,p)
    if p['view'] not in {'camera','top'}:raise ValueError('只能读取已登记审看视频')
    path=file_ref(r.root,v['files'][p['view']],{'.mp4'})
    size=path.stat().st_size;offset=p['offset']
    if size>MAX_VIDEO or type(offset)is not int or not 0<=offset<size:raise ValueError('分块范围不合法')
    with path.open('rb') as f:f.seek(offset);chunk=f.read(MAX_CHUNK)
    return {'previs_id':s['previs_id'],'version':v['version'],'view':p['view'],'sha256':v['files'][p['view']]['sha256'],
            'offset':offset,'total':size,'next':offset+len(chunk),'data_base64':base64.b64encode(chunk).decode(),'mime':'video/mp4'}


def mutate(r,action,p):
    r.check_project_identity(p.get('expected_project_id'))
    return {'previs.register':register,'previs.feedback':feedback,'previs.select':select}[action](r,p)

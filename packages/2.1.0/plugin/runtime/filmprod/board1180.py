"""Explicit creator-panel decisions. Registry owns transaction and operation IDs.

These endpoints do not create tasks, send chats, generate media or write cloud data.
Display organization remains separate from exact user adoption.
"""
from copy import deepcopy
from .board1150 import _fields, _read, _write, _revision, _text, _target, _trash, _identity

PREFIX = 'board1180/'
WRITE_ACTIONS = {'board.project.set', 'board.confirm', 'board.style.select', 'board.object.set',
                 'board.asset.link', 'board.asset.select'}


def check_revision(p, current):
    from .core import ConflictError
    if _revision(p['base_revision']) != current:
        raise ConflictError('内容已更新，请刷新后重新确认。')


def project_set(r, p):
    from .core import canonical
    _fields(p, {'op_id','expected_project_id','base_revision','title','intro','cover'},
            {'op_id','expected_project_id','base_revision','title'})
    if not {'intro','cover'} <= set(p):
        raise ValueError('请提交完整的项目资料。')
    project = r._project()
    check_revision(p, project.get('profile_revision', 0))
    title = _text(p['title'], '项目名称', 40)
    if not isinstance(p['intro'], str) or len(p['intro']) > 200:
        raise ValueError('项目介绍最多 200 字。')
    cover = p['cover']
    if cover is not None:
        if not isinstance(cover, dict) or set(cover) != {'media_id','sha256'}:
            raise ValueError('封面需要准确的图片身份。')
        ident, target = _target(r, {'expected_project_id':p['expected_project_id'],
            'target_type':'media','target_id':cover['media_id'],'expected_sha256':cover['sha256']}, verify_original=True)
        if target['kind'] != 'image' or _trash(r, ident).get('deleted'):
            raise ValueError('封面必须是未回收的项目图片。')
    project.update(title=title, intro=p['intro'].strip(), cover=cover,
                   profile_revision=project.get('profile_revision',0)+1)
    r.db.execute("UPDATE settings SET value=? WHERE key='project'", (canonical(project),))
    return {'project':project}


def confirm(r, p):
    from .core import ConflictError, content_category, now
    _fields(p, {'op_id','expected_project_id','target_type','target_id','version','expected_sha256',
                'base_master_version','base_latest_version','confirmed','note'},
            {'op_id','expected_project_id','target_type','target_id','version','expected_sha256',
                'base_master_version','base_latest_version','confirmed'})
    ident, target = _target(r, p, verify_original=True)
    if p['confirmed'] is not True or ident['target_type'] != 'artifact':
        raise ValueError('请阅读准确版本后明确确认。')
    if target['kind'] not in {'script','screenplay','source_script','novel','outline','character_bio','style_bible','style','director','vfx','asset','video_prompt'}:
        raise ValueError('这类记录不能通过此入口采用。')
    if _trash(r, ident).get('deleted') or target.get('metadata',{}).get('reference_role') in {'reference','inspiration'}:
        raise ValueError('参考或回收内容不能直接采用。')
    latest = r._artifact(target['artifact_id'])
    if type(p['base_latest_version']) is not int or latest['version'] != p['base_latest_version'] or target['version'] != latest['version']:
        raise ConflictError('已有更新的候选，请重新阅读当前版本。')
    master = r._master(content_category(target))
    if type(p['base_master_version']) is not int or p['base_master_version'] != (master['version'] if master else 0):
        raise ConflictError('采用记录已变化，请刷新后重新确认。')
    note = _text(p.get('note',''), '确认意见', 1000, empty=True)
    quote = '确认采用「'+str(target.get('metadata',{}).get('title') or target['artifact_id'])+'」第 '+str(target['version'])+' 版'
    synthetic = bool(r._project().get('test_only'))
    result = r._approve({'op_id':p['op_id'],'artifact_id':target['artifact_id'],'version':target['version'],
        'sha256':target['sha256'],'scope':target['scope'],'base_master_version':p['base_master_version'],
        'actor':'test' if synthetic else 'human','synthetic':synthetic,'evidence':quote+('；'+note if note else ''),
        'user_authorization':{'source':'panel-click','quote':quote,'artifact_id':target['artifact_id'],
            'version':target['version'],'scope':target['scope'],'observed_at':now(),
            'actor_identity':{'verified':False,'user_id':None}}})
    return result


def object_set(r, p):
    _fields(p, {'op_id','expected_project_id','object_id','base_revision','title','type','intro','scope'},
            {'op_id','expected_project_id','object_id','base_revision','title','type'})
    oid = _text(p['object_id'],'对象身份',160)
    old = _read(r, PREFIX+'object/'+oid) or {'revision':0}
    check_revision(p, old['revision'])
    if p['type'] not in {'character','scene','prop','shot','sound','final','other'}:
        raise ValueError('请选择对象分类。')
    row = {'object_id':oid,'title':_text(p['title'],'对象名称',100), 'type':p['type'],
           'intro':_text(p.get('intro',''),'对象说明',200,empty=True),
           'scope':_text(p.get('scope',''),'所属范围',160,empty=True),'revision':old['revision']+1}
    _write(r,PREFIX+'object/'+oid,row)
    return row


def style_select(r, p):
    from .art1130 import select_art, _load, _comparison
    from .core import ConflictError
    _fields(p, {'op_id','expected_project_id','base_revision','comparison_id','choice',
                'target_id','version','expected_sha256','confirmed','note'},
            {'op_id','expected_project_id','base_revision','comparison_id','choice',
                'target_id','version','expected_sha256','confirmed'})
    if p['choice'] not in {'main','alternate'} or p['confirmed'] is not True:
        raise ValueError('请明确选择已登记的一套完整方案。')
    comparison=_comparison(_load(r),p['comparison_id'])
    ref={'artifact_id':p['target_id'],'version':p['version'],'sha256':p['expected_sha256']}
    if comparison[p['choice']] != ref:
        raise ConflictError('对比方案已变化，请重新阅读。')
    ident,target=_target(r,{**p,'target_type':'artifact'},verify_original=True)
    if _trash(r,ident).get('deleted'):
        raise ValueError('已回收方案不能选用。')
    note=_text(p.get('note',''),'选择意见',1000,empty=True)
    return select_art(r,{'op_id':p['op_id'],'expected_project_id':p['expected_project_id'],
        'base_revision':p['base_revision'],'comparison_id':p['comparison_id'],'choice':p['choice'],
        'synthetic':bool(r._project().get('test_only')),
        'user_request':{'source':'panel','reference':p['op_id'],
            'quote':'选择'+('主选方案' if p['choice']=='main' else '备选方案')+('；'+note if note else '')}})


def item_key(ident):
    from .core import canonical
    return PREFIX+'link/'+canonical(ident)


def asset_link(r,p):
    from .core import ConflictError
    _fields(p, {'op_id','expected_project_id','target_type','target_id','version','expected_sha256',
                'base_revision','object_id','purpose','reference'},
            {'op_id','expected_project_id','target_type','target_id','expected_sha256','base_revision','object_id','purpose','reference'})
    ident,target = _target(r,p,verify_original=True)
    if _trash(r,ident).get('deleted'):
        raise ValueError('回收内容请先恢复。')
    obj = _read(r,PREFIX+'object/'+_text(p['object_id'],'对象身份',160))
    if not obj:
        raise ValueError('请先登记人物、场景或其他对象。')
    key=item_key(ident);old=_read(r,key) or {'revision':0}
    check_revision(p,old['revision'])
    if type(p['reference']) is not bool:
        raise ValueError('参考标记必须为布尔值。')
    purpose=_text(p['purpose'],'素材用途',100)
    # Changing a selected item's association would silently change its meaning.
    for selected in _all(r,'selection/'):
        if selected['reference']=={**ident,'sha256':target['sha256']} and (selected['object_id']!=obj['object_id'] or selected['purpose']!=purpose or p['reference']):
            raise ConflictError('这份素材已选用，请先为原用途选用其他素材，再调整关联。')
    row={**ident,'object_id':obj['object_id'],'purpose':purpose,'reference_only':p['reference'],
         'sha256':target['sha256'],'revision':old['revision']+1}
    _write(r,key,row)
    return row


def selection_key(oid,purpose):
    from .core import canonical
    return PREFIX+'selection/'+canonical([oid,purpose])


def asset_select(r,p):
    from .core import ConflictError, now
    _fields(p, {'op_id','expected_project_id','target_type','target_id','version','expected_sha256',
                'object_id','purpose','base_revision','link_revision','confirmed','note'},
            {'op_id','expected_project_id','target_type','target_id','expected_sha256','object_id','purpose',
                'base_revision','link_revision','confirmed'})
    ident,target=_target(r,p,verify_original=True)
    if ident['target_type']!='media' or p['confirmed'] is not True or _trash(r,ident).get('deleted'):
        raise ValueError('请明确选用未回收的媒体素材。')
    link=_read(r,item_key(ident))
    if not link or link['object_id']!=p['object_id'] or link['purpose']!=p['purpose'] or link['sha256']!=target['sha256'] or link['revision']!=p['link_revision']:
        raise ConflictError('素材用途或版本已变化，请刷新。')
    if link['reference_only']:
        raise ValueError('参考素材不能作为制作成果选用。')
    key=selection_key(p['object_id'],p['purpose']);old=_read(r,key) or {'revision':0}
    check_revision(p,old['revision'])
    ref={**ident,'sha256':target['sha256']}
    if old.get('reference')==ref:
        return {**old,'already_selected':True}
    row={'object_id':p['object_id'],'purpose':p['purpose'],'reference':ref,
         'revision':old['revision']+1,'previous':old.get('reference'),'decision_id':p['op_id'],
         'observed_at':now(),'synthetic':bool(r._project().get('test_only')),
         'evidence':'选用此素材用于「'+p['purpose']+'」',
         'note':_text(p.get('note',''),'选用意见',1000,empty=True),
         'actor_identity':{'source':'panel-click','verified':False,'user_id':None}}
    _write(r,key,row)
    _write(r,PREFIX+'decision/'+p['op_id'],row)
    return row


def _all(r,suffix):
    import json
    prefix=PREFIX+suffix
    return [json.loads(row[0]) for row in r.db.execute('SELECT value FROM settings WHERE substr(key,1,?)=? ORDER BY key',(len(prefix),prefix))]


def view(r,snapshot):
    items=snapshot.get('board_library',{}).get('items',[])
    objects=_all(r,'object/');byid={o['object_id']:o for o in objects}
    links=_all(r,'link/');selections=_all(r,'selection/')
    for item in items:
        oid=item.get('asset_id')
        if oid and oid not in byid:
            group=[i for i in items if i.get('asset_id')==oid]
            kinds={i.get('category_id') for i in group if i.get('category_id') in {'character','scene','prop'}}
            obj={'object_id':oid,'title':oid,'type':next(iter(kinds)) if len(kinds)==1 else 'other','intro':'','scope':'','revision':0,'legacy_association':True}
            objects.append(obj);byid[oid]=obj
    from .core import content_category
    targets=[]
    for a in snapshot.get('artifacts',[]):
        master=r._master(content_category(a))
        targets.append({'artifact_id':a['artifact_id'],'version':a['version'],'sha256':a['sha256'],'base_master_version':master['version'] if master else 0})
    return {'confirm_targets':targets,'objects':objects,'links':links,'selections':selections,
            'decisions':sorted(_all(r,'decision/'),key=lambda d:d['observed_at'],reverse=True),
            'profile_revision':snapshot.get('project',{}).get('profile_revision',0)}


def dispatch(r,action,p):
    r.check_project_identity(p.get('expected_project_id'))
    return {'board.project.set':project_set,'board.confirm':confirm,'board.object.set':object_set,
            'board.style.select':style_select,'board.asset.link':asset_link,'board.asset.select':asset_select}[action](r,p)

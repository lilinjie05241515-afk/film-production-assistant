"""Rebuild human-readable derived files from the registry without editing originals."""
import hashlib
import json
import re
from pathlib import Path
from . import __version__

FOLDERS=['00-设定与依据','01-故事与剧本','02-导演方案','03-资产','04-提示词与生成任务','05-片段','06-音乐','07-成片','08-审核记录','09-任务与接续','10-影视研究与复盘']
KINDS={'idea':0,'requirements':0,'planning_record':0,'script':1,'source_script':1,'screenplay':1,'story':1,'outline':1,'novel':1,'character_bio':1,'style_bible':0,'director':2,'asset':3,'vfx':2,'prompt':4,'video_prompt':4,'clip':5,'sequence':5,'cue':6,'music':6,'subtitle':7,'final':7,'render':7,'research':10,'review':8}
STATUS={'recorded':'已记录，未授予执行授权','candidate':'待审核候选','approved':'已通过','needs_review':'需复核','created':'已建立','in_progress':'进行中','submitted':'已提交','cancelled':'已取消'}
CATEGORY_LABELS={'idea':'灵感探索','requirements':'需求与执行规划','novel':'小说','outline':'故事大纲','character_bio':'人物小传','style':'全剧风格','source_script':'源剧本（底稿）','script':'动态分场剧本 / 既有剧本（阶段以记录为准）','director':'导演拍摄建议','vfx':'特效分析','asset':'资产提示词','video_prompt':'AI 视频提示词','research':'影视研究'}
MODE_LABELS={'novel_only':'只创作小说','novel_to_screen':'小说转影视','screenplay':'直接创作剧本','unset':'尚未选择'}
STAGE_STATUS={'empty':'尚无内容','candidate':'有待审初稿','mixed':'已有通过稿，也有待审修改','approved':'已有条目均通过','needs_review':'部分内容需复核'}

def reading_location(metadata):
    labels=[]
    for field in ('episode','chapter','scene','shot'):
        value=metadata.get(field)
        if isinstance(value,dict): value=value.get('title') or value.get('id')
        if isinstance(value,(str,int)) and not isinstance(value,bool) and str(value).strip():
            labels.append(str(value).strip().replace('\n',' '))
    return ' / '.join(labels) if labels else '未分章'

def reading_sort(item):
    order=item.get('metadata',{}).get('order')
    order=order if isinstance(order,list) else [order] if isinstance(order,int) and not isinstance(order,bool) else []
    if not all(type(n) is int for n in order): order=[]
    natural=tuple((0,int(x)) if x.isdigit() else (1,x.casefold()) for x in re.split(r'(\d+)',item.get('scope','')))
    return (0,tuple(order),natural,item['artifact_id']) if order else (1,(),natural,item['artifact_id'])
def safe(value):
    # IDs are data, never path segments without sanitization.
    return re.sub(r'[^\w\-.]', '_', value)[:100]+'-'+hashlib.sha256(value.encode()).hexdigest()[:8]

def export_video_prompt_texts(root, versions, snap):
    """Each exact generation unit gets its own unwrapped UTF-8 body.

    Approval/provenance stays in the reading index and registry. A master is a
    reading collection with headings, not a single executable video prompt.
    """
    approved = {(a['artifact_id'], a['version']): a for a in snap.get('approved_artifacts', [])}
    pending = {(a['artifact_id'], a['version']) for a in snap.get('pending_candidates', [])}
    historical = {(d['artifact_id'], d['version']) for d in snap.get('decisions', []) if d.get('updates_master')}
    exports = []
    for item in versions:
        if item['kind'] != 'video_prompt':
            continue
        identity = (item['artifact_id'], item['version'])
        if identity in approved:
            status = 'needs_review' if approved[identity].get('approval_status') == 'needs_review' else 'current_approved'
        elif identity in pending:
            status = 'candidate'
        else:
            status = 'historical_approved' if identity in historical else 'historical_candidate'
        path = Path(FOLDERS[4])/'AI视频提示词纯正文'/f"{safe(item['artifact_id'])}_v{item['version']:03d}.txt"
        target = root/path
        body = item['content'].encode('utf-8')
        if target.exists() and target.read_bytes() != body:
            raise ValueError('纯提示词副本已被外部修改，保留差异：'+str(target))
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        exports.append({'artifact_id': item['artifact_id'], 'version': item['version'], 'scope': item['scope'],
                        'path': str(target), 'relative_path': path.as_posix(), 'status': status,
                        'sha256': hashlib.sha256(body).hexdigest()})
    return exports
def export_project(registry):
    snap=registry.snapshot(); root=registry.root
    if not snap['project']: raise ValueError('项目未初始化')
    for folder in FOLDERS: (root/folder).mkdir(exist_ok=True)
    lines=['# '+snap['project']['title'],'','这是由登记库生成的阅读入口；请通过总控或看板修改登记，再导出。此处的正文文件为派生阅读副本。',
           '',f"系统版本 {__version__} · 生成时间 {snap['observed_at']}",'',
           '测试状态：原创测试，无真人作品采用。' if snap['project']['test_only'] else '正式项目：采用状态以精确版本的决定登记为准。','',
           '在 Codex 客户端调用影视开发制作总控，提供本作品目录与任务 ID。','',
           '## 当前成果','','| 成果 | 范围 | 版本 | 状态 |','|---|---|---|---|']
    current = snap.get('current_content', snap['artifacts'])
    current_refs = {(a['artifact_id'], a['version']) for a in current}
    # Export every immutable section version, but list only the current approved
    # section (or explicitly labelled first draft) at the reading entrance.
    versions = [v for a in snap['artifacts'] for v in registry.dispatch('artifact.history', {'artifact_id':a['artifact_id']})['versions']]
    video_prompt_texts = export_video_prompt_texts(root, versions, snap)
    for item in versions:
        folder=FOLDERS[KINDS.get(item['kind'],0)]
        path=Path(folder)/f"{safe(item['artifact_id'])}_v{item['version']:03d}.md"
        body=item['content'] if isinstance(item['content'],str) else json.dumps(item['content'],ensure_ascii=False,indent=2)
        # Reading Markdown uses uniform line endings. Exact prompt TXT above
        # retains the original bytes, including mixed CRLF/LF content.
        body=body.replace('\r\n','\n').replace('\r','\n')
        text=f"# {item['artifact_id']} v{item['version']}\n\n{body}\n\n---\n\n范围：{item['scope']}；源内容 SHA256：{item['sha256']}\n\n精确依赖：{json.dumps(item['deps'],ensure_ascii=False)}\n"
        target=root/path
        if target.exists() and target.read_text(encoding='utf-8') != text:
            raise ValueError('派生正文已被外部修改，保留差异：'+str(target))
        if not target.exists(): target.write_text(text,encoding='utf-8')
        if (item['artifact_id'], item['version']) in current_refs:
            selected = next(a for a in current if a['artifact_id']==item['artifact_id'])
            approved = any(a['artifact_id']==item['artifact_id'] and a['version']==item['version'] for a in snap.get('approved_artifacts',[]))
            label = STATUS.get(selected['status'], selected['status']) if approved else '初稿 · 尚无通过版'
            lines.append(f"| [{item.get('metadata',{}).get('title') or item['scope']}]({path.as_posix()}) | {item['scope']} | {item['version']} | {label} |")
    lines += ['', '## 章节与分集阅读目录', '', '目录仅组织已有分段；未分章正文不会被自动拆成新的批准范围。', '']
    for category,label in CATEGORY_LABELS.items():
        items=[a for a in current if a.get('category')==category]
        if not items: continue
        lines += ['### '+label,'']
        for item in sorted(items,key=reading_sort):
            path=Path(FOLDERS[KINDS.get(item['kind'],0)])/f"{safe(item['artifact_id'])}_v{item['version']:03d}.md"
            title=item.get('metadata',{}).get('title') or item['scope']
            location=reading_location(item.get('metadata',{}))
            lines.append(f"- {location} · [{title}]({path.as_posix()}) · v{item['version']}")
    if video_prompt_texts:
        labels = {'current_approved': '当前已通过', 'needs_review': '当前通过版本 · 需复核',
                  'candidate': '待审核候选', 'historical_approved': '历史已通过 · 非当前版',
                  'historical_candidate': '历史候选 · 非当前版'}
        lines += ['', '## AI 视频提示词纯正文', '',
                  '每个 TXT 仅含该精确分段或生成单元的提示词正文，不附审核状态、来源或参数元数据。使用前核对下列版本状态；总稿仅供合集阅读，不是单个视频生成指令。', '']
        for item in video_prompt_texts:
            lines.append(f"- {item['scope']} · {item['artifact_id']} v{item['version']} · {labels[item['status']]}：[纯提示词 TXT]({item['relative_path']})")
    workflow=snap.get('workflow')
    if workflow:
        lines += ['', '## 创作路线与全剧风格', '', '路线：'+MODE_LABELS.get(workflow.get('mode'),'尚未选择'), '',
                  '阶段中的已有内容不等于整个阶段已完成。研究结论只有在明确批准为全剧风格后才成为后续任务依据；绑定精确版本也不替代正文语义复核。', '']
        for stage in workflow.get('stages',[]):
            lines.append(f"- {stage.get('label',stage.get('key',''))}：{STAGE_STATUS.get(stage.get('status'),'未知')}")
    lines += ['', '## 已通过总稿与总稿历史', '', '总稿只由通过的分段组成；待审核修改不会替换总稿。', '']
    for master in snap.get('masters', []):
        category = master['category']
        history = registry.dispatch('master.history', {'category': category})
        for version in history['versions']:
            folder = root/'已通过总稿'/safe(category)
            folder.mkdir(parents=True, exist_ok=True)
            target = folder/f"总稿_v{version['version']:03d}.md"
            body = version['content'].replace('\r\n','\n').replace('\r','\n')
            if target.exists() and target.read_text(encoding='utf-8') != body:
                raise ValueError('总稿阅读副本已被外部修改，保留差异：'+str(target))
            if not target.exists(): target.write_text(body, encoding='utf-8')
            label = '当前总稿' if version['version']==master['version'] else '历史总稿'
            lines.append(f"- {category} {label} v{version['version']}：[阅读]({target.relative_to(root).as_posix()})")
    if snap.get('pending_candidates'):
        lines += ['', '## 待审核修改', '']
        for item in snap['pending_candidates']:
            path=Path(FOLDERS[KINDS.get(item['kind'],0)])/f"{safe(item['artifact_id'])}_v{item['version']:03d}.md"
            lines.append(f"- {item['scope']} v{item['version']}：[候选内容]({path.as_posix()})")
    lines+=['','## 任务接续','','| 任务 | 状态 | 接续包 |','|---|---|---|']
    for task in snap['tasks']:
        package=registry.dispatch('task.resume',{'task_id':task['task_id']})
        payload=json.dumps(package,ensure_ascii=False,indent=2)
        path=Path(FOLDERS[9])/f"{safe(task['task_id'])}_{hashlib.sha256(payload.encode()).hexdigest()[:12]}.json"
        (root/path).write_text(payload,encoding='utf-8')
        lines.append(f"| {task['task_id']} | {STATUS.get(task['status'],task['status'])} | [完整接续包]({path.as_posix()}) |")
    lines+=['','## 能力与采用边界','','音乐技能待接入；只管理 cue、音频引用和对齐。实际渲染结果另存；成片清单本身不是已渲染视频。影视研究的采用范围单独登记。','',
           '## 同步观察','','Pages 为云端可编辑工作稿权威，本地保存观察快照。没有后台实时同步；开工前由宿主重新读取必要云源。']
    for row in snap['sync']:
        lines.append(f"\n- {row['sync_id']}：{row['status']}；最后观察 {row.get('last_observed_at') or '未知'}")
    (root/'项目入口.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    rules=root/'AGENTS.md'
    if not rules.exists(): rules.write_text('# 作品工作规则\n\n先核对项目入口和真实登记。测试决定不是作品采用。场次、角色、镜头保持独立范围。任务用精确输入版本；完整检查点及时保存。生成阅读副本不可当成云端权威；更改用新版本。未知字段保持未知。媒体只保留一份归档原件。\n',encoding='utf-8')
    return {'entry':str(root/'项目入口.md'),'artifacts':len(snap['artifacts']),'tasks':len(snap['tasks']),'generated_at':snap['observed_at'],
            'video_prompt_texts':video_prompt_texts}

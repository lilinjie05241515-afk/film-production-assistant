"""Import complete host Pages observations; never call private cloud APIs."""
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


WORKING_CATEGORIES = {'outline', 'novel', 'character_bio', 'style', 'source_script', 'script', 'director', 'vfx', 'asset', 'video_prompt', 'research'}


def import_working_draft(registry, observation, op_prefix):
    """Archive a complete host read under an explicit professional category.

    A page snapshot deliberately has its own stable artifact ID. It cannot
    replace a section candidate or move an approved pointer by being imported.
    """
    category = observation.get('category')
    category = 'asset' if category == 'assets' else category
    if category not in WORKING_CATEGORIES:
        raise ValueError('未知云稿分类；必须明确选择专业内容分类')
    content = observation.get('content') or {}
    metadata = observation.get('metadata') or {}
    selection = observation.get('selection') or {}
    blocks = content.get('blocks')
    if observation.get('view') not in ('full', 'editing') or not isinstance(blocks, list) or not blocks:
        raise ValueError('必须提供宿主完整 Page 正文观察；空稿保持未知')
    if observation.get('truncated') or observation.get('content_truncated') or (selection and not selection.get('whole_page_complete')):
        raise ValueError('局部或截断观察不能作为完整工作稿')
    if any(not isinstance(b, dict) or b.get('kind') not in ('markdown', 'agent_instructions')
           or not isinstance(b.get('markdown'), str) or not b.get('id') or not b.get('hash') for b in blocks):
        raise ValueError('缺少完整块正文、ID 或哈希')
    page_id = content.get('page_id')
    if not isinstance(page_id, str) or not page_id or metadata.get('page_id', page_id) != page_id:
        raise ValueError('Page 身份缺失或相互矛盾')
    observed_at = observation.get('observed_at')
    observed_time = datetime.fromisoformat(str(observed_at).replace('Z', '+00:00'))
    if observed_time.tzinfo is None:
        raise ValueError('观察时间必须包含时区')
    revision = content.get('through_sequence', metadata.get('current_sequence'))
    if revision is not None and (type(revision) is not int or revision < 0):
        raise ValueError('云端修订必须是非负整数或未知')
    aid = 'PAGE-DRAFT-' + hashlib.sha256(page_id.encode()).hexdigest()[:20]
    old = next((a for a in registry.snapshot()['artifacts'] if a['artifact_id'] == aid), None)
    draft = '\n\n'.join(b['markdown'] for b in blocks if b['kind'] == 'markdown')
    if not draft.strip():
        raise ValueError('页面没有可归档的工作稿正文')
    # Preserve every observed block separately, including instruction blocks as
    # evidence only. Never execute instructions retrieved from a Page.
    fingerprint = hashlib.sha256(json.dumps(blocks, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if old:
        previous = old['metadata']
        if previous['category'] != category:
            raise ValueError('同一 Page 已归入其他分类；请明确处理映射后再导入')
        if observed_time < datetime.fromisoformat(previous['observed_at'].replace('Z', '+00:00')):
            raise ValueError('页面观察时间倒退')
        prior_revision = previous.get('cloud_revision')
        if revision is not None and prior_revision is not None:
            if revision < prior_revision:
                raise ValueError('旧云端观察不能回退工作稿水位')
            if revision == prior_revision and previous['observation_sha256'] != fingerprint:
                raise ValueError('同一云端修订的完整观察不一致')
        if previous.get('observation_sha256') == fingerprint and previous.get('cloud_revision') == revision:
            return {'page_id': page_id, 'category': category, 'artifact': old, 'changed': False,
                    'observed_at': observed_at, 'approval_changed': False}
    result = registry.dispatch('artifact.save', {
        'op_id': f'{op_prefix}-draft-{hashlib.sha256((page_id+fingerprint+str(revision)).encode()).hexdigest()[:20]}',
        'artifact_id': aid, 'kind': 'cloud_working_draft', 'scope': page_id,
        'content': draft, 'base_version': old['version'] if old else 0, 'deps': [],
        'metadata': {'category': category, 'title': content.get('title') or metadata.get('title') or category,
                     'authority': 'Pages working draft', 'page_id': page_id, 'page_url': metadata.get('url'),
                     'cloud_revision': revision, 'observed_at': observed_at, 'blocks': blocks,
                     'observation_sha256': fingerprint, 'approval': 'not_implied_by_cloud_read'}})
    return {'page_id': page_id, 'category': category, 'result': result, 'changed': True,
            'observed_at': observed_at, 'approval_changed': False}


def import_observation(registry, observation, op_prefix):
    # A category supplied by the host is an explicit mapping, never an inference
    # from arbitrary headings. These are full working drafts, not approvals.
    if observation.get('category'):
        return import_working_draft(registry, observation, op_prefix)
    content = observation.get('content')
    if not content or not content.get('blocks'):
        raise ValueError('完整 Page 正文观察缺失；不可将读取失败当空稿')
    selection = observation.get('selection', {})
    if observation.get('view') not in ('editing','full') and not selection.get('whole_page_complete'):
        raise ValueError('完整性身份未知；必须保留宿主完整读取的 view/selection 证据')
    if observation.get('truncated') or observation.get('content_truncated'):
        raise ValueError('截断观察不可导入')
    if selection and not selection.get('whole_page_complete'):
        raise ValueError('局部读取不能作为整页快照')
    if observation.get('view') == 'excerpts':
        raise ValueError('片段读取不能作为整页快照')
    page_id = content['page_id']
    observed_at = observation['observed_at']
    blocks = content['blocks']
    if any(b.get('kind') not in ('markdown','agent_instructions') or not isinstance(b.get('markdown'), str) for b in blocks):
        raise ValueError('不支持或不完整的页面块；保留原始观察供人工映射')
    sections, current = {}, None
    for block in blocks:
        if block['kind'] != 'markdown':
            continue
        match = re.match(r'^# .*?\b(S\d+)\b', block['markdown'])
        if match:
            current = match[1]
            if current in sections:
                raise ValueError('重复场次 ID')
            sections[current] = []
        if current:
            sections[current].append(block['markdown'])
    if not sections:
        raise ValueError('未识别稳定场次 ID；需人工映射，不猜测')
    existing = {a['artifact_id']: a for a in registry.snapshot()['artifacts']}
    revision = content.get('through_sequence', observation['metadata'].get('current_sequence'))
    observed_time = datetime.fromisoformat(observed_at.replace('Z','+00:00'))
    if observed_time.tzinfo is None:
        raise ValueError('观察时间必须包含时区')
    observation_id = 'PAGE-OBS-' + hashlib.sha256(page_id.encode()).hexdigest()[:16]
    observation_text = json.dumps({'blocks':blocks,'revision':revision},ensure_ascii=False,sort_keys=True)
    last = existing.get(observation_id)
    if last:
        last_meta=last['metadata']; last_revision=last_meta.get('cloud_revision')
        if revision is not None and last_revision is not None and revision < last_revision:
            raise ValueError('旧云端观察不能回退页面观察水位')
        if observed_time < datetime.fromisoformat(last_meta['observed_at'].replace('Z','+00:00')):
            raise ValueError('页面观察时间倒退')
        if revision is not None and revision == last_revision and last['content'] != observation_text:
            raise ValueError('同一云端修订的完整观察不一致')
    previous_scenes = set(last['metadata']['scenes']) if last else {a['scope'] for a in existing.values() if a['kind']=='script' and a.get('metadata',{}).get('page_id')==page_id and not a.get('metadata',{}).get('deleted_in_cloud')}
    removed = previous_scenes - set(sections)
    if any(existing.get('SCRIPT-'+s,{}).get('metadata',{}).get('local_candidate') for s in removed):
        raise ValueError('云端删除场次与本地候选冲突；保留双方供人工处理')
    # Reject old evidence before writing any scene. Revision is observation data,
    # never substituted for a Pages content edit guard.
    for scope in sections:
        old = existing.get('SCRIPT-' + scope)
        if not old:
            continue
        metadata = old.get('metadata', {})
        if metadata.get('local_candidate') and old['content'] != '\n\n'.join(sections[scope]):
            raise ValueError('本地候选与云稿并发差异；保留两者，需人工合并后另存版本')
        if metadata.get('page_id') not in (None, page_id):
            raise ValueError('场次已绑定其他页面；需明确迁移映射')
        prior = metadata.get('cloud_revision')
        if revision is not None and prior is not None and revision < prior:
            raise ValueError('旧云端观察不能回退新快照')
        if metadata.get('observed_at') and datetime.fromisoformat(observed_at.replace('Z','+00:00')) < datetime.fromisoformat(metadata['observed_at'].replace('Z','+00:00')):
            raise ValueError('观察时间倒退；保留最新已核快照')
        if revision is not None and revision == prior and old['content'] != '\n\n'.join(sections[scope]):
            raise ValueError('相同远端修订的正文不一致')
    results = []
    for scope, parts in sections.items():
        text = '\n\n'.join(parts)
        aid = 'SCRIPT-' + scope
        old = existing.get(aid)
        if old and old['content'] == text:
            continue
        digest = hashlib.sha256(text.encode()).hexdigest()
        results.append(registry.dispatch('artifact.save', dict(
            op_id=f'{op_prefix}-{scope}-{digest[:12]}', artifact_id=aid,
            kind='script', scope=scope, content=text,
            base_version=old['version'] if old else 0, deps=[],
            metadata={'authority':'Pages working draft','page_id':page_id,
                      'page_url':observation['metadata']['url'],
                      'observed_at':observed_at,
                      'cloud_revision':revision,
                      'blocks':[{'id':b['id'],'hash':b['hash']} for b in blocks if b['markdown'] in parts]})))
    for scope in sorted(removed):
        old=existing['SCRIPT-'+scope]
        results.append(registry.dispatch('artifact.save',dict(
            op_id=f'{op_prefix}-{scope}-removed',artifact_id=old['artifact_id'],kind='script',scope=scope,
            content='该场次已从本次完整云端工作稿移除；这是待审核删除标记，当前总稿未改变。旧稿保留在历史版本。',base_version=old['version'],deps=[],
            metadata={'authority':'Pages working draft','page_id':page_id,'page_url':observation['metadata']['url'],
                      'observed_at':observed_at,'cloud_revision':revision,'deleted_in_cloud':True})))
    # The page observation advances even when all scene text is unchanged.
    if not last or last['content'] != observation_text or last['metadata']['observed_at'] != observed_at:
        obs_digest=hashlib.sha256((observation_text+observed_at).encode()).hexdigest()[:16]
        registry.dispatch('artifact.save',dict(op_id=f'{op_prefix}-observe-{obs_digest}',artifact_id=observation_id,
            kind='pages_observation',scope=page_id,content=observation_text,base_version=last['version'] if last else 0,deps=[],
            metadata={'page_id':page_id,'page_url':observation['metadata']['url'],'cloud_revision':revision,'observed_at':observed_at,'scenes':sorted(sections)}))
    return {'page_id':page_id,'observed_at':observed_at,'changed_scenes':[r.get('artifact',r).get('scope') for r in results], 'results':results}


def load_observation(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

"""Incremental project planning records; Registry owns persistence and identity.

Collection/update semantics follow the user-authorized idea-explorer records
method. This module has no separate store, default project, or execution engine.
"""
from copy import deepcopy
import hashlib
import json
import re

ARRAYS = {'facts', 'preferences', 'assumptions', 'unknowns', 'branches', 'decisions',
          'authorizations', 'sources', 'attachments', 'alternatives', 'projects',
          'validation_cards', 'requirements', 'constraints', 'tasks'}
IMMUTABLE = {'decisions', 'authorizations', 'sources', 'attachments', 'projects'}
SCALARS = {'goal', 'status', 'next_step', 'current_branch', 'summary', 'details', 'origin'}
KINDS = {'idea', 'requirements'}


def nonempty(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(field + ' 必须为非空字符串')


def source(item, field):
    value = item.get('source')
    if not isinstance(value, dict):
        raise ValueError(field + ' 必须保留实际来源')
    nonempty(value.get('type'), field + '.source.type')
    nonempty(value.get('reference'), field + '.source.reference')


def items(field, values):
    if not isinstance(values, list):
        raise ValueError(field + ' 必须为数组')
    seen = set()
    for item in values:
        if not isinstance(item, dict):
            raise ValueError(field + ' 项目必须为对象')
        ident = item.get('id')
        nonempty(ident, field + '.id')
        if len(ident) > 200 or any(ord(c) < 32 for c in ident) or ident in seen:
            raise ValueError(field + ' 的稳定编号重复或无效')
        seen.add(ident)
        if field in {'decisions', 'authorizations'}:
            source(item, field)
        if field == 'authorizations':
            nonempty(item.get('scope'), 'authorization.scope')
            nonempty(item['source'].get('quote'), 'authorization.source.quote')
        if field == 'attachments':
            if item.get('status') == 'link_only':
                nonempty(item.get('reference'), 'attachment.reference')
            elif item.get('status') == 'saved':
                nonempty(item.get('media_id'), 'attachment.media_id')
            else:
                raise ValueError('附件须为 link_only 或指向已登记真实媒体的 saved')


def validate(state):
    if not isinstance(state, dict) or set(state) - ARRAYS - SCALARS:
        raise ValueError('未知状态字段放入 details；不能静默丢弃')
    if not isinstance(state.get('details', {}), dict):
        raise ValueError('details 必须为对象')
    for field in ARRAYS:
        items(field, state.get(field, []))
    chosen = state.get('current_branch')
    if chosen is not None and not any(b['id'] == chosen for b in state['branches']):
        raise ValueError('current_branch 必须引用已保存分支，未知用 null')


def frozen_selection(entry):
    """Validate exact provenance structure, not the authenticity of host evidence."""
    source(entry, 'frozen_selection')
    selection = entry.get('selection')
    if not isinstance(selection, dict):
        raise ValueError('frozen_selection 需要完整 selection 来源快照')
    for key in ('store_id', 'record_id', 'branch_id', 'transfer_id'):
        nonempty(selection.get(key), 'selection.' + key)
    if type(selection.get('version')) is not int or selection['version'] < 1:
        raise ValueError('selection.version 必须为精确正整数')
    if not isinstance(selection.get('head_hash'), str) or not re.fullmatch('[0-9a-f]{64}', selection['head_hash']):
        raise ValueError('selection.head_hash 缺失或无效')
    if selection.get('history_coverage') not in {'snapshot_only', 'complete_events'} or selection.get('attachment_coverage') not in {'link_only', 'copied_verified', 'mixed'}:
        raise ValueError('必须明确历史与附件取得范围')
    snapshot = selection.get('snapshot')
    if not isinstance(snapshot, dict) or any(snapshot.get(key) != selection[target] for key, target in [('id', 'record_id'), ('version', 'version'), ('head_hash', 'head_hash')]):
        raise ValueError('来源快照身份与冻结引用不一致')
    state = snapshot.get('state')
    if not isinstance(state, dict) or not isinstance(state.get('branches'), list):
        raise ValueError('来源快照缺少分支状态')
    if not any(isinstance(b, dict) and b.get('id') == selection['branch_id'] for b in state['branches']):
        raise ValueError('冻结分支不在来源快照中')
    if selection['history_coverage'] == 'complete_events':
        events = selection.get('events')
        if not isinstance(events, list) or len(events) != selection['version']:
            raise ValueError('完整事件覆盖必须从第 1 版连续到冻结版本')
        previous_hash, requests = None, set()
        for index, event in enumerate(events, 1):
            if not isinstance(event, dict):
                raise ValueError('历史事件必须为对象')
            unsigned = {k: v for k, v in event.items() if k != 'hash'}
            digest = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
            if event.get('version') != index or event.get('schema') != 1 or event.get('store_id') != selection['store_id'] or event.get('record_id') != selection['record_id'] or event.get('prev_hash') != previous_hash or event.get('hash') != digest:
                raise ValueError('完整历史事件的身份、版本或摘要链不符')
            request_id = event.get('request_id')
            nonempty(request_id, 'event.request_id')
            if request_id in requests:
                raise ValueError('历史事件请求号重复')
            requests.add(request_id)
            previous_hash = event['hash']
        if previous_hash != selection['head_hash']:
            raise ValueError('完整事件头与冻结版本不符')


def apply(previous, payload, *, record_id, version, timestamp):
    """Pure reducer; previous state, entries and protected evidence stay immutable."""
    if not isinstance(payload, dict):
        raise ValueError('change 必须为对象')
    create = previous is None
    allowed = {'record_kind', 'title', 'state', 'entries'} if create else {'title', 'set', 'append', 'item_updates', 'branch_updates', 'entries'}
    if set(payload) - allowed:
        raise ValueError('未知 change 字段或试图改变记录类型')
    for key in ('state', 'set', 'append', 'item_updates'):
        if key in payload and not isinstance(payload[key], dict):
            raise ValueError(key + ' 必须为对象')
    if create:
        if payload.get('record_kind') not in KINDS:
            raise ValueError('record_kind 必须为 idea 或 requirements')
        nonempty(payload.get('title'), 'title')
        state = {'goal': None, 'status': '仅登记', 'next_step': '未安排',
                 'current_branch': None, 'summary': None, 'details': {},
                 **{key: [] for key in sorted(ARRAYS)}}
        state.update(deepcopy(payload.get('state', {})))
        result = {'schema_version': 1, 'record_id': record_id, 'record_kind': payload['record_kind'],
                  'title': payload['title'], 'state': state, 'entries': [], 'created_at': timestamp}
    else:
        result = deepcopy(previous)
        if 'title' in payload:
            nonempty(payload['title'], 'title')
            result['title'] = payload['title']
        changes = payload.get('set', {})
        if set(changes) - SCALARS:
            raise ValueError('set 不得整体覆盖集合；请追加或按编号修订')
        result['state'].update(deepcopy(changes))
        for key, additions in payload.get('append', {}).items():
            if key not in ARRAYS:
                raise ValueError('未知 append 集合: ' + key)
            items(key, additions)
            result['state'][key].extend(deepcopy(additions))
        updates = deepcopy(payload.get('item_updates', {}))
        branches = payload.get('branch_updates', [])
        if not isinstance(branches, list):
            raise ValueError('branch_updates 必须为数组')
        if branches:
            if not isinstance(updates.get('branches', []), list):
                raise ValueError('branches updates 必须为数组')
            updates.setdefault('branches', []).extend(branches)
        for key, patches in updates.items():
            if key not in ARRAYS or key in IMMUTABLE:
                raise ValueError('不可改写历史决定、授权、来源、附件或关联；追加 supersedes 记录')
            if not isinstance(patches, list):
                raise ValueError('item_updates 值必须为数组')
            for patch in patches:
                if not isinstance(patch, dict):
                    raise ValueError('item update 必须为对象')
                targets = [i for i in result['state'][key] if i['id'] == patch.get('id')]
                if len(targets) != 1:
                    raise ValueError('修订目标编号不存在')
                targets[0].update(deepcopy(patch))
    validate(result['state'])
    entries = payload.get('entries', [])
    if not isinstance(entries, list):
        raise ValueError('entries 必须为数组')
    existing = {e['id'] for e in result['entries']}
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get('text'), str):
            raise ValueError('entry 必须有 kind 和原样 text')
        nonempty(entry.get('kind'), 'entry.kind')
        if entry['kind'] == 'original_input':
            source(entry, 'original_input')
        if entry['kind'] == 'frozen_selection':
            frozen_selection(entry)
        saved = deepcopy(entry)
        saved.setdefault('id', f'ENTRY-{version:08d}-{position:04d}')
        nonempty(saved['id'], 'entry.id')
        if saved['id'] in existing:
            raise ValueError('entry 编号重复')
        existing.add(saved['id'])
        saved['record_version'] = version
        result['entries'].append(saved)
    result.update(version=version, updated_at=timestamp)
    return result


def check_attachments(registry, record):
    """Saved means a byte-checked file in this explicit project's media registry."""
    import hashlib
    media = {m['media_id']: m for m in registry._list('media')}
    for attachment in record['state']['attachments']:
        if attachment['status'] != 'saved':
            continue
        found = media.get(attachment['media_id'])
        if not found:
            raise ValueError('saved 附件没有本项目真实媒体登记')
        file = (registry.root / found['path']).resolve()
        if not file.is_relative_to(registry.root) or not file.is_file():
            raise ValueError('saved 附件文件缺失或越界')
        actual = hashlib.sha256(file.read_bytes()).hexdigest()
        if actual != found['sha256']:
            raise ValueError('saved 附件摘要不符')
        for key in ('sha256', 'path', 'size_bytes'):
            if key in attachment and attachment[key] != found[key]:
                raise ValueError('附件声明与实际登记不符')
            attachment[key] = found[key]
    for entry in record['entries']:
        if entry['kind'] != 'frozen_selection':
            continue
        selection = entry['selection']
        if selection['attachment_coverage'] == 'copied_verified':
            source_attachments = selection['snapshot'].get('state', {}).get('attachments', [])
            if not isinstance(source_attachments, list) or any(not isinstance(a, dict) or not a.get('id') for a in source_attachments):
                raise ValueError('来源附件列表无效')
            # A link-only original cannot be claimed to have been copied as bytes.
            copies = selection.get('attachment_copies', [])
            if not isinstance(copies, list):
                raise ValueError('attachment_copies 必须为数组')
            for original in source_attachments:
                match = next((a for a in record['state']['attachments'] if any(isinstance(c, dict) and c.get('source_attachment_id') == original['id'] and c.get('project_attachment_id') == a['id'] for c in copies)), None)
                if original.get('status') != 'saved' or not match or match.get('status') != 'saved' or match['sha256'] != original.get('sha256'):
                    raise ValueError('copied_verified 需要每份源附件与本项目真实媒体的摘要映射')

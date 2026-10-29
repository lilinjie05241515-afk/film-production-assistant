"""Explicit exploration transitions inside the existing planning record.

The caller interprets the user's message. These checks verify structure and exact
saved branches, never authenticate a human or infer intent from quoted words.
"""
from copy import deepcopy
import hashlib
import json
import re

ACTIONS = ('open', 'select', 'preview', 'return_open', 'pause', 'resume')
PHASES = ('open', 'deepening', 'paused')
SOURCE_TYPES = ('user_message', 'synthetic_user_message')


def branch_sha256(branch):
    return hashlib.sha256(json.dumps(branch, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _text(value, field, *, identifier=False):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(field + ' 必须为非空字符串')
    if identifier and (len(value) > 500 or any(ord(c) < 32 for c in value)):
        raise ValueError(field + ' 编号或引用无效')


def _source(value):
    if not isinstance(value, dict) or set(value) != {'type', 'reference', 'quote'}:
        raise ValueError('exploration.source 需要 type、reference 和原样 quote')
    if value['type'] not in SOURCE_TYPES:
        raise ValueError('exploration.source 只能引用用户原话；助手判断不是用户决定')
    _text(value['reference'], 'exploration.source.reference', identifier=True)
    _text(value['quote'], 'exploration.source.quote')


def _ref(value, *, snapshot=False):
    keys = {'branch_id', 'record_version', 'branch_sha256'} | ({'snapshot'} if snapshot else set())
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError('exploration.branch_refs 需要准确分支编号、记录版本和摘要')
    _text(value['branch_id'], 'branch_id', identifier=True)
    if type(value['record_version']) is not int or value['record_version'] < 1:
        raise ValueError('record_version 必须为精确正整数')
    if not isinstance(value['branch_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', value['branch_sha256']):
        raise ValueError('branch_sha256 必须为准确小写 SHA-256')
    if snapshot and (not isinstance(value['snapshot'], dict)
                     or value['snapshot'].get('id') != value['branch_id']
                     or branch_sha256(value['snapshot']) != value['branch_sha256']):
        raise ValueError('探索分支快照与冻结引用不一致')


def validate_command(command):
    if not isinstance(command, dict):
        raise ValueError('exploration 必须为显式转换对象')
    action = command.get('action')
    if action not in ACTIONS:
        raise ValueError('未知 exploration.action')
    required = {'action', 'event_id', 'source'} | ({'branch_refs'} if action in {'select', 'preview'} else set())
    if set(command) != required:
        raise ValueError('exploration 转换字段缺失或多余')
    _text(command['event_id'], 'exploration.event_id', identifier=True)
    _source(command['source'])
    if 'branch_refs' in command:
        refs = command['branch_refs']
        if not isinstance(refs, list) or not refs:
            raise ValueError('select/preview 必须引用至少一个已保存分支')
        seen = set()
        for ref in refs:
            _ref(ref)
            if ref['branch_id'] in seen:
                raise ValueError('探索分支引用不能重复')
            seen.add(ref['branch_id'])


def validate_state(value):
    """Validate managed state without rewriting or interpreting legacy records."""
    keys = {'schema_version', 'phase', 'selected_refs', 'history', 'resume_phase', 'last_preview'}
    if not isinstance(value, dict) or set(value) != keys or type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('exploration 状态结构无效；请使用显式转换')
    phase = value['phase']
    if phase not in PHASES or value['resume_phase'] not in (None, 'open', 'deepening'):
        raise ValueError('exploration 阶段无效')
    if (phase == 'paused') != (value['resume_phase'] is not None):
        raise ValueError('exploration 暂停恢复阶段不一致')
    refs = value['selected_refs']
    if not isinstance(refs, list):
        raise ValueError('selected_refs 必须为数组')
    for ref in refs:
        _ref(ref, snapshot=True)
    effective = value['resume_phase'] if phase == 'paused' else phase
    if (effective == 'deepening') != bool(refs) or len({r['branch_id'] for r in refs}) != len(refs):
        raise ValueError('exploration 阶段与选定分支不一致')
    history = value['history']
    if not isinstance(history, list) or not history:
        raise ValueError('exploration 需要明确转换历史')
    seen = set()
    last_version = 0
    for event in history:
        if not isinstance(event, dict):
            raise ValueError('exploration 历史项必须为对象')
        command = {key: event[key] for key in ('action', 'event_id', 'source', 'branch_refs') if key in event}
        # Saved history keeps full branch snapshots; command refs remain minimal.
        if 'branch_refs' in command:
            command['branch_refs'] = [{k: v for k, v in r.items() if k != 'snapshot'} for r in command['branch_refs']]
            for ref in event['branch_refs']:
                _ref(ref, snapshot=True)
        validate_command(command)
        if event['event_id'] in seen or type(event.get('record_version')) is not int or event['record_version'] <= last_version:
            raise ValueError('exploration 历史编号或版本重复')
        seen.add(event['event_id'])
        last_version = event['record_version']
        if event.get('evidence_level') != 'caller_reported_user_message' or event.get('user_authenticated') is not False:
            raise ValueError('exploration 不认证人类身份或原话语义')
        if event.get('production_authorized') is not False or event.get('approval_changed') is not False:
            raise ValueError('exploration 转换不能授予制作或批准')
    preview = value['last_preview']
    if preview is not None and (not isinstance(preview, dict) or preview.get('scope') != 'this_request_only'
                                or preview.get('event_id') not in seen):
        raise ValueError('preview 必须明确仅本次请求范围')


def apply_exploration(previous, result, command, *, version, timestamp):
    """Apply one explicit command; preserve source and exact prior branch bytes."""
    validate_command(command)
    if result['record_kind'] != 'idea':
        raise ValueError('exploration 仅用于 idea 记录；明确需求不强制进入脑暴')
    old_state = previous['state'] if previous else {}
    old = old_state.get('exploration')
    if old is not None:
        validate_state(old)
    action = command['action']
    if old and any(e['event_id'] == command['event_id'] for e in old['history']):
        raise ValueError('exploration.event_id 已存在；未知结果请用原 op_id 核查')
    if action == 'open' and (old is not None or old_state.get('current_branch') is not None
                             or result['state'].get('current_branch') is not None):
        raise ValueError('open 不能重置已有探索或选择；返回发散须显式 return_open')
    if action in {'preview', 'pause', 'resume'} and old is None:
        raise ValueError('探索状态未知；先核对原记录并明确建立阶段')
    if old and old['phase'] == 'paused' and action not in {'resume', 'return_open'}:
        raise ValueError('探索已暂停；需显式恢复或返回发散')
    if action == 'resume' and old['phase'] != 'paused':
        raise ValueError('只有暂停的探索可以 resume')

    value = deepcopy(old) if old is not None else {
        'schema_version': 1, 'phase': 'open', 'selected_refs': [],
        'resume_phase': None, 'last_preview': None, 'history': []}
    refs = []
    for ref in command.get('branch_refs', []):
        if previous is None or ref['record_version'] != previous['version']:
            raise ValueError('选择必须引用本次基础版本中已保存的准确分支')
        found = next((b for b in old_state['branches'] if b['id'] == ref['branch_id']), None)
        if found is None or branch_sha256(found) != ref['branch_sha256']:
            raise ValueError('分支不存在或摘要已变化；重读后按用户实际选择接续')
        current = next((b for b in result['state']['branches'] if b['id'] == ref['branch_id']), None)
        if current != found:
            raise ValueError('不能同轮改写所引用分支并选择旧快照；先保存再核对')
        refs.append({**deepcopy(ref), 'snapshot': deepcopy(found)})

    event = {**deepcopy(command), 'record_version': version, 'at': timestamp,
             'previous_phase': old['phase'] if old else None,
             'previous_selected_refs': deepcopy(value['selected_refs']),
             'legacy_current_branch': old_state.get('current_branch') if old is None else None,
             'evidence_level': 'caller_reported_user_message', 'user_authenticated': False,
             'production_authorized': False, 'approval_changed': False}
    if refs:
        event['branch_refs'] = refs
    if action in {'open', 'return_open'}:
        value.update(phase='open', selected_refs=[], resume_phase=None, last_preview=None)
        # open is allowed only without a legacy choice; return_open is explicit.
        result['state']['current_branch'] = None
    elif action == 'select':
        value.update(phase='deepening', selected_refs=deepcopy(refs), resume_phase=None, last_preview=None)
        result['state']['current_branch'] = refs[0]['branch_id'] if len(refs) == 1 else None
    elif action == 'preview':
        value['last_preview'] = {'event_id': command['event_id'], 'record_version': version,
                                 'scope': 'this_request_only', 'branch_refs': deepcopy(refs)}
    elif action == 'pause':
        value.update(resume_phase=value['phase'], phase='paused', last_preview=None)
    elif action == 'resume':
        value.update(phase=value['resume_phase'], resume_phase=None, last_preview=None)
    event['next_phase'] = value['phase']
    value['history'].append(event)
    validate_state(value)
    result['state']['exploration'] = value


def exploration_help():
    """Read-only schema/help for the existing planning.record change field."""
    ref_schema = {'type': 'object', 'additionalProperties': False,
                  'required': ['branch_id', 'record_version', 'branch_sha256'], 'properties': {
                      'branch_id': {'type': 'string', 'minLength': 1},
                      'record_version': {'type': 'integer', 'minimum': 1},
                      'branch_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}}}
    source_schema = {'type': 'object', 'additionalProperties': False,
                     'required': ['type', 'reference', 'quote'], 'properties': {
                         'type': {'type': 'string', 'enum': list(SOURCE_TYPES)},
                         'reference': {'type': 'string', 'minLength': 1},
                         'quote': {'type': 'string', 'minLength': 1}}}
    choices = []
    for action in ACTIONS:
        properties = {'action': {'const': action}, 'event_id': {'type': 'string', 'minLength': 1},
                      'source': source_schema}
        if action in {'select', 'preview'}:
            properties['branch_refs'] = {'type': 'array', 'minItems': 1, 'items': ref_schema}
        choices.append({'type': 'object', 'additionalProperties': False,
                        'required': list(properties), 'properties': properties})
    example = {'id': 'TEST-A', 'title': 'TEST synthetic branch', 'status': 'candidate'}
    return {
        'change_field': 'exploration', 'state_path': 'record.state.exploration',
        'command_schema': {'oneOf': choices},
        'commands': {
            'open': 'Start explicit open exploration only when no managed state or legacy current_branch exists.',
            'select': 'Persist an explicitly selected exact branch/combination as deepening; no approval or production.',
            'preview': 'Explicitly deepen referenced branches for this request only; phase and selection stay unchanged.',
            'return_open': 'Explicitly return to open exploration; retain former choices and sources in history.',
            'pause': 'Pause while retaining the exact phase and choices.',
            'resume': 'Restore the saved pre-pause phase; never guess a new choice.'},
        'branch_digest': 'SHA-256 UTF-8 json.dumps(branch, ensure_ascii=False, sort_keys=True, separators=(comma, colon), allow_nan=False).',
        'example_branch': example,
        'example_select_change': {'exploration': {
            'action': 'select', 'event_id': 'TEST-SELECT-1',
            'source': {'type': 'synthetic_user_message', 'reference': 'TEST:turn2',
                       'quote': 'TEST: choose branch A for further discussion only.'},
            'branch_refs': [{'branch_id': 'TEST-A', 'record_version': 1, 'branch_sha256': branch_sha256(example)}]}},
        'evidence_boundary': 'Caller-reported user message only; syntax and saved references are checked, not human identity or semantic intent.',
        'compatibility': 'Omitted exploration preserves legacy records. No state means unknown; read never migrates. Ordinary preferences, answers and summaries do not change phase.',
        'selection_boundary': 'Read the referenced planning base version first. New/changed branches must be saved before selecting. Direct state/set.exploration is rejected; current_branch is managed once enabled.',
        'preview_boundary': 'last_preview is historical evidence for its one request, not permission to continue deepening on later turns.',
        'side_effects': 'No task, conversation, authorization, approval or production is created by an exploration transition.'}

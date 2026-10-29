"""Synthetic-only regression tests for persistent exploration, not human intent."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from filmprod.core import ConflictError, Registry
from filmprod.exploration2100 import branch_sha256, exploration_help, validate_command
from filmprod.planning import apply


def command(action, event=None, refs=None):
    event = event or 'TEST-' + action
    result = {'action': action, 'event_id': event, 'source': {
        'type': 'synthetic_user_message', 'reference': 'TEST:turn-' + event,
        'quote': 'TEST synthetic user instruction for ' + action}}
    if refs is not None:
        result['branch_refs'] = refs
    return result


def initial(*, managed=True, kind='idea', chosen=None):
    change = {'record_kind': kind, 'title': 'TEST branching', 'state': {
        'branches': [{'id': 'A', 'mechanism': 'TEST relationship reversal'},
                     {'id': 'B', 'mechanism': 'TEST unreliable viewpoint'}],
        'current_branch': chosen}}
    if managed:
        change['exploration'] = command('open')
    return change


def reduce(previous, change):
    return apply(previous, change, record_id='TEST-IDEA',
                 version=previous['version'] + 1 if previous else 1, timestamp='TEST-time')


def refs(record, *ids):
    return [{'branch_id': ident, 'record_version': record['version'],
             'branch_sha256': branch_sha256(next(b for b in record['state']['branches'] if b['id'] == ident))}
            for ident in ids]


class ExplorationReducer2100(unittest.TestCase):
    def test_ordinary_turns_preserve_open_without_interpreting_words(self):
        record = reduce(None, initial())
        for number, text in enumerate(('TEST 我更喜欢 A', 'TEST 继续', 'TEST 人物年龄补充', 'TEST 回答前一个问题')):
            prior = deepcopy(record['state']['exploration'])
            record = reduce(record, {'append': {'preferences': [{'id': 'P' + str(number), 'text': text}]},
                                     'set': {'summary': text}, 'entries': [{'kind': 'discussion', 'text': text}]})
            self.assertEqual(record['state']['exploration'], prior)
        self.assertEqual(record['state']['exploration']['phase'], 'open')
        self.assertIsNone(record['state']['current_branch'])

    def test_explicit_selection_freezes_exact_branch_and_no_authorization(self):
        before = reduce(None, initial())
        selection = command('select', 'TEST-select', refs(before, 'A'))
        selection['source']['quote'] = 'TEST 原样\r\n选 A 继续讨论，先不制作。'
        result = reduce(before, {'exploration': selection})
        state = result['state']['exploration']
        self.assertEqual(state['phase'], 'deepening')
        self.assertEqual(result['state']['current_branch'], 'A')
        self.assertEqual(state['selected_refs'][0]['snapshot'], before['state']['branches'][0])
        event = state['history'][-1]
        self.assertEqual(event['source']['quote'], selection['source']['quote'])
        self.assertEqual(event['evidence_level'], 'caller_reported_user_message')
        self.assertFalse(event['user_authenticated'])
        self.assertFalse(event['production_authorized'])
        self.assertFalse(event['approval_changed'])
        self.assertEqual(result['state']['authorizations'], [])
        self.assertEqual(result['state']['decisions'], [])
        self.assertEqual(before['state']['exploration']['phase'], 'open')

    def test_preview_is_temporary_and_does_not_choose(self):
        record = reduce(None, initial())
        result = reduce(record, {'exploration': command('preview', 'TEST-preview', refs(record, 'B'))})
        state = result['state']['exploration']
        self.assertEqual(state['phase'], 'open')
        self.assertEqual(state['selected_refs'], [])
        self.assertEqual(state['last_preview']['scope'], 'this_request_only')
        self.assertIsNone(result['state']['current_branch'])
        continued = reduce(result, {'entries': [{'kind': 'discussion', 'text': 'TEST 继续'}]})
        self.assertEqual(continued['state']['exploration']['phase'], 'open')
        self.assertEqual(continued['state']['exploration']['last_preview']['record_version'], 2)
        self.assertEqual(continued['version'], 3)

    def test_preview_of_another_branch_preserves_previous_selection(self):
        record = reduce(None, initial())
        selected = reduce(record, {'exploration': command('select', 'TEST-select', refs(record, 'A'))})
        previewed = reduce(selected, {'exploration': command('preview', 'TEST-preview', refs(selected, 'B'))})
        self.assertEqual(previewed['state']['exploration']['selected_refs'], selected['state']['exploration']['selected_refs'])
        self.assertEqual(previewed['state']['current_branch'], 'A')

    def test_combination_and_return_open_retain_previous_choice(self):
        record = reduce(None, initial())
        selected = reduce(record, {'exploration': command('select', 'TEST-select', refs(record, 'A', 'B'))})
        self.assertEqual(len(selected['state']['exploration']['selected_refs']), 2)
        self.assertIsNone(selected['state']['current_branch'])
        returned = reduce(selected, {'exploration': command('return_open', 'TEST-return')})
        state = returned['state']['exploration']
        self.assertEqual(state['phase'], 'open')
        self.assertEqual(state['selected_refs'], [])
        self.assertEqual(state['history'][-1]['previous_selected_refs'], selected['state']['exploration']['selected_refs'])
        self.assertEqual(state['history'][1]['action'], 'select')
        self.assertEqual(returned['state']['branches'], record['state']['branches'])

    def test_pause_resume_restores_exact_phase_and_choices(self):
        for choose in (False, True):
            with self.subTest(choose=choose):
                record = reduce(None, initial())
                if choose:
                    record = reduce(record, {'exploration': command('select', 'TEST-select', refs(record, 'B'))})
                paused = reduce(record, {'exploration': command('pause', 'TEST-pause')})
                self.assertEqual(paused['state']['exploration']['phase'], 'paused')
                for action in ('select', 'preview'):
                    with self.assertRaisesRegex(ValueError, '暂停'):
                        reduce(paused, {'exploration': command(action, 'TEST-fail', refs(paused, 'A'))})
                resumed = reduce(paused, {'exploration': command('resume', 'TEST-resume')})
                self.assertEqual(resumed['state']['exploration']['phase'], record['state']['exploration']['phase'])
                self.assertEqual(resumed['state']['exploration']['selected_refs'], record['state']['exploration']['selected_refs'])
                returned = reduce(paused, {'exploration': command('return_open', 'TEST-return')})
                self.assertEqual(returned['state']['exploration']['phase'], 'open')

    def test_legacy_choice_is_not_migrated_or_reset_by_open(self):
        record = reduce(None, initial(managed=False, chosen='A'))
        updated = reduce(record, {'set': {'summary': 'TEST ordinary note'}})
        self.assertNotIn('exploration', updated['state'])
        self.assertEqual(updated['state']['current_branch'], 'A')
        with self.assertRaisesRegex(ValueError, '不能重置'):
            reduce(updated, {'exploration': command('open')})
        returned = reduce(updated, {'exploration': command('return_open')})
        self.assertEqual(returned['state']['exploration']['history'][0]['legacy_current_branch'], 'A')
        self.assertEqual(returned['state']['exploration']['phase'], 'open')
        self.assertEqual(record['state']['current_branch'], 'A')

    def test_legacy_record_can_explicitly_select_but_unknown_cannot_resume(self):
        record = reduce(None, initial(managed=False))
        for action in ('resume', 'pause', 'preview'):
            with self.assertRaisesRegex(ValueError, '状态未知'):
                reduce(record, {'exploration': command(action, refs=refs(record, 'A') if action == 'preview' else None)})
        selected = reduce(record, {'exploration': command('select', refs=refs(record, 'A'))})
        self.assertEqual(selected['state']['exploration']['phase'], 'deepening')

    def test_direct_requirements_do_not_require_exploration(self):
        record = reduce(None, initial(managed=False, kind='requirements'))
        self.assertNotIn('exploration', record['state'])
        updated = reduce(record, {'append': {'requirements': [{'id': 'REQ', 'text': 'TEST make the requested outline'}]}})
        self.assertNotIn('exploration', updated['state'])
        with self.assertRaisesRegex(ValueError, '仅用于 idea'):
            reduce(record, {'exploration': command('open')})

    def test_references_reject_stale_hash_version_unknown_and_same_round_edit(self):
        record = reduce(None, initial())
        good = refs(record, 'A')
        invalid = [[], [{**good[0], 'branch_id': 'missing'}], [{**good[0], 'record_version': 99}],
                   [{**good[0], 'branch_sha256': '0' * 64}], [good[0], good[0]],
                   [{**good[0], 'record_version': True}]]
        for bad in invalid:
            with self.subTest(refs=bad), self.assertRaises(ValueError):
                reduce(record, {'exploration': command('select', refs=bad)})
        with self.assertRaisesRegex(ValueError, '同轮改写'):
            reduce(record, {'branch_updates': [{'id': 'A', 'mechanism': 'TEST changed'}],
                            'exploration': command('select', refs=good)})
        fresh_branch = {'id': 'NEW', 'mechanism': 'TEST newly proposed'}
        with self.assertRaisesRegex(ValueError, '不存在'):
            reduce(record, {'append': {'branches': [fresh_branch]}, 'exploration': command('select', refs=[{
                'branch_id': 'NEW', 'record_version': 1, 'branch_sha256': branch_sha256(fresh_branch)}])})

    def test_later_branch_edits_do_not_retarget_selection_or_history(self):
        record = reduce(None, initial())
        selected = reduce(record, {'exploration': command('select', refs=refs(record, 'A'))})
        changed = reduce(selected, {'branch_updates': [{'id': 'A', 'mechanism': 'TEST candidate revision'}]})
        self.assertEqual(changed['state']['exploration'], selected['state']['exploration'])
        self.assertNotEqual(changed['state']['branches'][0], changed['state']['exploration']['selected_refs'][0]['snapshot'])

    def test_no_direct_state_bypass_or_automatic_status_transition(self):
        record = reduce(None, initial())
        bad_create = initial(managed=False)
        bad_create['state']['exploration'] = record['state']['exploration']
        with self.assertRaises(ValueError):
            reduce(None, bad_create)
        for update in ({'set': {'exploration': record['state']['exploration']}},
                       {'set': {'current_branch': 'A'}}, {'exploration': command('open', 'TEST-second-open')}):
            with self.assertRaises(ValueError):
                reduce(record, update)
        updated = reduce(record, {'set': {'status': 'TEST selected-looking label',
                                         'details': {'exploration': {'phase': 'deepening'}}},
                                 'branch_updates': [{'id': 'A', 'status': 'TEST selected-looking label'}]})
        self.assertEqual(updated['state']['exploration']['phase'], 'open')

    def test_schema_rejects_model_evidence_missing_quote_and_extra_permissions(self):
        for edit in ({'source': {'type': 'assistant', 'reference': 'TEST', 'quote': 'TEST'}},
                     {'source': {'type': 'user_message', 'reference': 'TEST'}},
                     {'source': {'type': 'user_message', 'reference': '', 'quote': 'TEST'}},
                     {'production_authorized': True}, {'action': 'infer'}, {'branch_refs': []}, {'event_id': ''}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                validate_command({**command('open'), **edit})
        help_result = exploration_help()
        validate_command(help_result['example_select_change']['exploration'])
        self.assertEqual(help_result['example_select_change']['exploration']['branch_refs'][0]['branch_sha256'],
                         branch_sha256(help_result['example_branch']))
        self.assertEqual({x['properties']['action']['const'] for x in help_result['command_schema']['oneOf']},
                         {'open', 'select', 'preview', 'return_open', 'pause', 'resume'})

    def test_event_reuse_rejected_but_source_text_is_not_semantically_certified(self):
        record = reduce(None, initial())
        with self.assertRaisesRegex(ValueError, 'event_id 已存在'):
            reduce(record, {'exploration': command('pause', 'TEST-open')})
        selection = command('select', 'TEST-select', refs(record, 'A'))
        selection['source']['quote'] = 'TEST opaque content; semantic decision is the host responsibility'
        result = reduce(record, {'exploration': selection})
        self.assertFalse(result['state']['exploration']['history'][-1]['user_authenticated'])


class ExplorationRegistry2100(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='TEST-exploration2100-')
        self.root = Path(self.temp.name) / 'project'
        self.reg = Registry(self.root)
        self.reg.dispatch('project.init', {'op_id': 'init', 'project_id': 'TEST-P2100',
                                          'title': 'TEST only', 'test_only': True})

    def tearDown(self):
        self.reg.close()
        self.temp.cleanup()

    def save(self, op, base, change):
        return self.reg.dispatch('planning.record', {'op_id': op, 'expected_project_id': 'TEST-P2100',
            'record_id': 'TEST-IDEA', 'scope': 'development/TEST', 'base_version': base, 'change': change})

    def read(self, **kwargs):
        return self.reg.dispatch('planning.read', {'record_id': 'TEST-IDEA', **kwargs})['record']

    def test_versioned_replay_conflict_reopen_and_no_production_effects(self):
        self.save('open', 0, initial())
        record = self.read()
        change = {'exploration': command('select', 'TEST-select', refs(record, 'A'))}
        selected = self.save('choose', 1, change)
        self.assertEqual(self.save('choose', 1, change), selected)
        self.assertTrue(selected['saved'] and selected['readback_verified'])
        with self.assertRaises(ConflictError):
            self.save('stale', 1, {'exploration': command('return_open', 'TEST-return')})
        with self.assertRaises(ValueError):
            self.save('bad-ref', 2, {'exploration': command('select', 'TEST-invalid', refs(record, 'B'))})
        self.assertEqual(self.read()['version'], 2)
        self.assertEqual(self.read(version=1)['state']['exploration']['phase'], 'open')
        self.reg.close()
        self.reg = Registry(self.root)
        self.assertEqual(self.read(), selected['record'])
        snap = self.reg.snapshot()
        self.assertEqual(snap['tasks'], [])
        self.assertEqual(snap['pending_candidates'], [])
        self.assertEqual(snap['workflow']['mode'], 'unset')
        self.assertEqual(self.read()['state']['authorizations'], [])

    def test_legacy_read_reopen_does_not_migrate_or_change_artifact(self):
        saved = self.save('legacy', 0, initial(managed=False, chosen='A'))
        self.reg.close()
        self.reg = Registry(self.root)
        for _ in range(2):
            read = self.reg.dispatch('planning.read', {'record_id': 'TEST-IDEA'})
            self.assertEqual(read['record'], saved['record'])
            self.assertEqual(read['sha256'], saved['sha256'])
            self.assertNotIn('exploration', read['record']['state'])


if __name__ == '__main__':
    unittest.main()

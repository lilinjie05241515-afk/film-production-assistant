import copy
import json
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from filmprod.core import ConflictError, Registry
from filmprod.modules import resolve


class Planning170(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='TEST-plan170-')
        self.root = Path(self.temp.name) / 'project'
        self.reg = Registry(self.root)
        self.reg.dispatch('project.init', {'op_id': 'init', 'project_id': 'TEST-P170', 'title': 'TEST only', 'test_only': True})

    def tearDown(self):
        self.reg.close()
        self.temp.cleanup()

    def request(self, op='register', version=0, change=None):
        return {'op_id': op, 'expected_project_id': 'TEST-P170', 'record_id': 'REC-A', 'scope': 'development/A', 'base_version': version,
                'change': change if change is not None else {'record_kind': 'idea', 'title': 'TEST雨声',
                    'entries': [{'kind': 'original_input', 'text': '下雨散步的声音。\r\n先记一下，暂时不做。', 'source': {'type': 'synthetic_user_message', 'reference': 'TEST:turn1'}}]}}

    def save(self, *args, **kwargs):
        return self.reg.dispatch('planning.record', self.request(*args, **kwargs))

    def test_register_preserves_verbatim_without_approval_task_or_route(self):
        result = self.save()
        self.assertTrue(result['saved'] and result['readback_verified'])
        record = self.reg.dispatch('planning.read', {'record_id': 'REC-A'})['record']
        self.assertEqual(record['entries'][0]['text'], '下雨散步的声音。\r\n先记一下，暂时不做。')
        self.assertEqual(record['state']['status'], '仅登记')
        self.assertEqual(record['state']['next_step'], '未安排')
        self.assertFalse(result['execution_authorized_by_tool'])
        snap = self.reg.snapshot()
        self.assertEqual(snap['workflow']['mode'], 'unset')
        self.assertEqual(snap['tasks'], [])
        self.assertEqual(snap['pending_candidates'], [])
        self.assertEqual(len(snap['planning_records']), 1)
        with self.assertRaises(ValueError):
            self.reg.dispatch('content.approve', {'op_id': 'approve', 'artifact_id': 'REC-A', 'version': 1, 'scope': 'development/A', 'evidence': 'TEST', 'actor': 'test', 'synthetic': True})

    def test_append_versions_conflict_and_idempotency(self):
        first = self.save()
        self.assertEqual(self.save(), first)
        change = {'append': {'branches': [{'id': 'a', 'title': '声音日记', 'status': '候选'}, {'id': 'b', 'title': '旅行线索', 'status': '候选'}]}, 'entries': [{'kind': 'suggestion', 'text': '两个方向分别服务私密体验与叙事线索'}]}
        self.save('branches', 1, change)
        with self.assertRaises(ConflictError):
            self.save('stale', 1, {'set': {'summary': 'stale overwrite'}})
        with self.assertRaises(ConflictError):
            self.save('branches', 1, {'set': {'status': 'wrong replay'}})
        self.save('reject', 2, {'branch_updates': [{'id': 'b', 'status': '已否定', 'reason': '用户不想做旅行题材'}], 'set': {'status': '暂时搁置', 'next_step': '未安排'}})
        read = self.reg.dispatch('planning.read', {'record_id': 'REC-A', 'since_version': 1, 'limit': 1})
        self.assertEqual(len(read['changes']), 1)
        self.assertEqual(read['next_since_version'], 2)
        self.assertEqual(read['record']['state']['branches'][1]['reason'], '用户不想做旅行题材')
        old = self.reg.dispatch('planning.read', {'record_id': 'REC-A', 'version': 2})
        self.assertEqual(old['record']['state']['branches'][1]['status'], '候选')

    def test_protected_evidence_cannot_be_replaced(self):
        self.save()
        src = {'type': 'synthetic_user_message', 'reference': 'TEST:turn2', 'quote': '只做文字规划'}
        self.save('auth', 1, {'append': {'decisions': [{'id': 'd1', 'text': '喜欢A但还没选', 'source': src}], 'authorizations': [{'id': 'a1', 'scope': '文字规划', 'source': src}]}})
        for i, change in enumerate(({'set': {'decisions': []}}, {'item_updates': {'authorizations': [{'id': 'a1', 'scope': '付费生成'}]}}, {'append': {'authorizations': [{'id': 'a2', 'scope': '制作', 'source': {'type': 'message', 'reference': 'TEST'}}]}})):
            with self.assertRaises(ValueError):
                self.save('invalid'+str(i), 2, change)
        self.assertEqual(self.reg.dispatch('planning.read', {'record_id': 'REC-A'})['record']['version'], 2)
        self.assertEqual(self.reg.snapshot()['tasks'], [])

    def test_raw_record_save_restore_and_rename_bypasses_rejected(self):
        self.save()
        artifact = self.reg.dispatch('artifact.get', {'artifact_id': 'REC-A'})
        with self.assertRaises(ValueError):
            self.reg.dispatch('artifact.save', {'op_id': 'replace', 'artifact_id': 'REC-A', 'kind': 'planning_record', 'scope': artifact['scope'], 'base_version': 1, 'content': {}})
        with self.assertRaises(ValueError):
            self.reg.dispatch('artifact.restore', {'op_id': 'restore', 'artifact_id': 'REC-A', 'version': 1, 'base_version': 1})
        bad = self.request('scope', 1, {'set': {'summary': 'wrong'}})
        bad['scope'] = 'new/scope'
        with self.assertRaises(ConflictError):
            self.reg.dispatch('planning.record', bad)
        bad = self.request('identity', 1, {'set': {'summary': 'wrong'}})
        bad['expected_project_id'] = 'OTHER'
        with self.assertRaises(ValueError):
            self.reg.dispatch('planning.record', bad)

    def test_saved_attachment_requires_project_bytes(self):
        self.save()
        with self.assertRaises(ValueError):
            self.save('fake', 1, {'append': {'attachments': [{'id': 'f1', 'status': 'saved', 'media_id': 'unknown'}]}})
        file = Path(self.temp.name)/'TEST-source.txt'
        file.write_text('synthetic source bytes', encoding='utf-8')
        media = self.reg.dispatch('media.register', {'op_id': 'media', 'media_id': 'M', 'kind': 'other', 'path': str(file), 'metadata': {'test_only': True}})
        result = self.save('attachment', 1, {'append': {'attachments': [{'id': 'f1', 'status': 'saved', 'media_id': 'M'}]}})
        a = result['record']['state']['attachments'][0]
        self.assertEqual(a['sha256'], media['sha256'])
        (self.root / a['path']).write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '摘要'):
            self.save('new', 2, {'set': {'summary': 'must fail while evidence corrupt'}})

    def test_requirement_candidate_uses_method_and_never_starts_production(self):
        self.save()
        self.assertEqual(resolve('idea')['module']['id'], 'idea-explorer')
        self.assertEqual(resolve('requirements-planner')['task_module'], 'requirements')
        self.assertEqual(resolve('requirements')['module']['id'], 'requirements-planner')
        task = self.reg.dispatch('task.create', {'op_id': 'task', 'task_id': 'T', 'module': 'requirements', 'title': 'TEST规划', 'scope': 'development/plan', 'inputs': [{'artifact_id': 'REC-A', 'version': 1}], 'must_keep': [], 'allowed_changes': [], 'requirements': []})
        self.assertEqual(task['execution_lock']['module_id'], 'requirements-planner')
        with self.assertRaises(ValueError):
            self.reg.dispatch('task.submit', {'op_id': 'wrong-kind', 'task_id': 'T', 'artifact_id': 'PLAN', 'kind': 'script', 'base_version': 0, 'content': 'not permitted'})
        self.reg.dispatch('task.submit', {'op_id': 'submit', 'task_id': 'T', 'artifact_id': 'PLAN', 'kind': 'requirements', 'base_version': 0, 'content': 'TEST方案：只规划，不制作', 'metadata': {'workflow_stage': 'requirements'}})
        self.reg.dispatch('content.approve', {'op_id': 'approve-plan', 'artifact_id': 'PLAN', 'version': 1, 'scope': 'development/plan', 'evidence': 'TEST approve text only', 'actor': 'test', 'synthetic': True})
        snap = self.reg.snapshot()
        self.assertEqual(len(snap['tasks']), 1)
        self.assertEqual(snap['workflow']['mode'], 'unset')
        self.assertEqual(self.reg.dispatch('planning.read', {'record_id': 'REC-A'})['record']['state']['authorizations'], [])
        self.assertFalse(snap['capabilities']['planning_approval_is_execution_authorization'])

    def test_readonly_reopen_no_mutation_and_no_missing_project_creation(self):
        self.save()
        self.reg.close()
        file = self.root/'.project/registry.sqlite3'
        before = file.read_bytes()
        ro = Registry.open_readonly(self.root)
        result = ro.dispatch('planning.read', {'record_id': 'REC-A'})
        self.assertTrue(result['read_only'])
        ro.close()
        self.assertEqual(before, file.read_bytes())
        self.reg = Registry(self.root)
        missing = Path(self.temp.name)/'must-not-exist'
        request = Path(self.temp.name)/'read.json'
        request.write_text(json.dumps({'record_id': 'REC-A'}), encoding='utf-8')
        proc = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(Path(__file__).resolve().parents[1]/'film.py'), '--root', str(missing), 'dispatch', 'planning.read', '--file', str(request)], capture_output=True, text=True, encoding='utf-8')
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(missing.exists())

    def test_optional_preproduction_exists_without_route(self):
        snap = self.reg.snapshot()
        self.assertEqual([s['key'] for s in snap['workflow']['preproduction_stages']], ['idea', 'requirements'])
        self.assertEqual(snap['workflow']['stages'], [])
        self.assertFalse(snap['workflow']['preproduction_required'])
        self.assertFalse(snap['workflow']['execution_authorization_inferred'])

    def test_record_change_blocks_submission_against_stale_planning_input(self):
        self.save()
        self.reg.dispatch('task.create', {'op_id': 'task', 'task_id': 'T', 'module': 'requirements', 'title': 'TEST planning', 'scope': 'plan', 'inputs': [{'artifact_id': 'REC-A', 'version': 1}], 'must_keep': [], 'allowed_changes': [], 'requirements': []})
        self.save('new-decision', 1, {'set': {'summary': 'TEST revised constraint'}})
        with self.assertRaises(ConflictError):
            self.reg.dispatch('task.submit', {'op_id': 'submit', 'task_id': 'T', 'artifact_id': 'P', 'kind': 'requirements', 'base_version': 0, 'content': 'outdated'})

    def test_import_snapshot_requires_exact_source_and_does_not_reauthorize(self):
        self.save()
        with self.assertRaises(ValueError):
            self.save('bad-import', 1, {'entries': [{'kind': 'frozen_selection', 'text': 'Transferred'}]})
        selection = {'store_id': 'TEST-STORE', 'record_id': 'TEST-IDEA', 'version': 2, 'head_hash': 'a'*64, 'branch_id': 'A', 'transfer_id': 'TEST-XFER', 'history_coverage': 'snapshot_only', 'attachment_coverage': 'link_only',
                     'snapshot': {'id': 'TEST-IDEA', 'version': 2, 'head_hash': 'a'*64, 'state': {'branches': [{'id': 'A', 'status': '已选择'}], 'authorizations': [{'id': 'old-auth', 'scope': '旧授权'}]}}}
        entry = {'kind': 'frozen_selection', 'text': 'TEST exact observed snapshot; not a new authorization', 'source': {'type': 'external_idea_library', 'reference': 'TEST:show-v2'}, 'selection': selection}
        result = self.save('import', 1, {'entries': [entry]})
        self.assertEqual(result['record']['state']['authorizations'], [])
        self.assertEqual(result['record']['entries'][-1]['selection'], selection)
        wrong = copy.deepcopy(entry)
        wrong['selection']['version'] = 3
        with self.assertRaises(ValueError):
            self.save('mismatch', 2, {'entries': [wrong]})

    def external_frozen_entry(self):
        path = Path(__file__).resolve().parents[1]/'modules/idea-explorer/scripts/records.py'
        spec = importlib.util.spec_from_file_location('planning_test_external_records', path)
        records = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(records)
        store = records.Store(Path(self.temp.name)/'external-TEST-library')
        created = store.create({'kind': 'idea', 'title': 'TEST source', 'state': {'branches': [{'id': 'A', 'status': '候选'}]}}, 'TEST-create')
        store.update(created['id'], {'set': {'summary': 'TEST second version'}}, 'TEST-update', 1)
        snapshot = store.show(created['id'], version=2)
        events = store.history(created['id'])['events']
        selection = {'store_id': snapshot['store_id'], 'record_id': snapshot['id'], 'version': 2,
                     'head_hash': snapshot['head_hash'], 'branch_id': 'A', 'transfer_id': 'TEST-complete-transfer',
                     'history_coverage': 'complete_events', 'attachment_coverage': 'link_only', 'snapshot': snapshot, 'events': events}
        return {'kind': 'frozen_selection', 'text': 'TEST exact two-event transfer',
                'source': {'type': 'external_idea_library', 'reference': 'TEST:verified-v2'}, 'selection': selection}

    def test_complete_events_accepts_actual_external_store_protocol(self):
        entry = self.external_frozen_entry()
        result = self.save(change={'record_kind': 'idea', 'title': 'TEST complete transfer', 'entries': [entry]})
        self.assertEqual(result['record']['entries'][0]['selection'], entry['selection'])
        self.assertEqual(result['record']['state']['authorizations'], [])

    def test_complete_events_rejects_missing_prefix_corruption_and_wrong_identity(self):
        entry = self.external_frozen_entry()
        mutations = []
        missing = copy.deepcopy(entry)
        missing['selection']['events'] = missing['selection']['events'][-1:]
        mutations.append(missing)
        changed = copy.deepcopy(entry)
        changed['selection']['events'][0]['payload']['title'] = 'tampered source'
        mutations.append(changed)
        wrong = copy.deepcopy(entry)
        wrong['selection']['store_id'] = 'TEST-other-store'
        mutations.append(wrong)
        reordered = copy.deepcopy(entry)
        reordered['selection']['events'].reverse()
        mutations.append(reordered)
        for index, invalid in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.save(op='bad-'+str(index), change={'record_kind': 'idea', 'title': 'TEST refused', 'entries': [invalid]})
        self.assertEqual(self.reg.snapshot()['planning_records'], [])


if __name__ == '__main__':
    unittest.main()

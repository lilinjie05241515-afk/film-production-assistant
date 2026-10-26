"""Synthetic semantic invariants for bundled methods and task rule pinning."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from filmprod.core import Registry
from filmprod.modules import catalog, execution_lock, resolve


class ReleaseRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='film-release-TEST-')
        self.root=Path(self.tmp.name)/'project'
        self.reg=Registry(self.root)
        self.reg.dispatch('project.init',{'op_id':'init','project_id':'TEST-R160','title':'Synthetic release test','test_only':True})

    def tearDown(self):
        self.reg.close()
        self.tmp.cleanup()

    def create(self):
        return self.reg.dispatch('task.create',{'op_id':'task','task_id':'T','title':'TEST chapter','module':'story','scope':'chapter/1','inputs':[], 'must_keep':[],'allowed_changes':[],'requirements':[]})

    def checkpoint(self):
        return self.reg.dispatch('task.checkpoint',{'op_id':'cp','task_id':'T','draft':'synthetic draft','completed':[],'decisions':[],'unresolved':[],'next_step':'revise'})

    def test_all_six_modules_resolve_inside_bundle(self):
        data=catalog()
        self.assertGreaterEqual(len(data['modules']),6)
        for stage in ('story','adaptation','director','vfx','assets','research','video_prompt'):
            result=resolve(stage)
            entry=Path(result['module']['absolute_entrypoint'])
            self.assertTrue(entry.is_relative_to(Path(data['root'])))
            self.assertFalse(result['generation_performed'])
            self.assertGreater(len(result['module']['files']),0)

    def test_task_and_output_preserve_execution_lock(self):
        task=self.create()
        # dispatch returns the domain result, not a tool response.
        self.assertEqual(task['execution_lock'],execution_lock('story'))
        self.checkpoint()
        self.reg.close()
        self.reg=Registry(self.root)
        resumed=self.reg.dispatch('task.resume',{'task_id':'T'})
        self.assertTrue(resumed['execution_compatibility']['compatible'])
        self.assertEqual(resumed['checkpoint']['draft'],'synthetic draft')
        result=self.reg.dispatch('task.submit',{'op_id':'submit','task_id':'T','artifact_id':'A','kind':'novel','content':'synthetic final candidate','base_version':0})
        self.assertEqual(result['artifact']['metadata']['execution_lock'],task['execution_lock'])
        self.assertFalse(self.reg.snapshot()['approved_artifacts'])

    def test_new_runtime_cannot_checkpoint_or_submit_old_rules(self):
        self.create()
        changed=copy.deepcopy(execution_lock('story'))
        changed['system_version']='9.0.0'
        with patch('filmprod.modules.execution_lock',return_value=changed):
            before=self.reg.snapshot()
            self.assertFalse(self.reg.dispatch('task.resume',{'task_id':'T'})['execution_compatibility']['compatible'])
            with self.assertRaisesRegex(ValueError,'冻结'):
                self.checkpoint()
            with self.assertRaisesRegex(ValueError,'冻结'):
                self.reg.dispatch('task.submit',{'op_id':'submit','task_id':'T','artifact_id':'A','kind':'novel','content':'must not save','base_version':0})
            self.assertEqual(before['tasks'],self.reg.snapshot()['tasks'])
            self.assertEqual(before['artifacts'],self.reg.snapshot()['artifacts'])

    def test_legacy_task_does_not_gain_fabricated_version(self):
        task=self.create()
        del task['execution_lock']
        self.reg.db.execute('UPDATE tasks SET data=? WHERE task_id=?',(json.dumps(task),'T'))
        before=self.reg.db.execute('SELECT data FROM tasks').fetchone()[0]
        resumed=self.reg.dispatch('task.resume',{'task_id':'T'})
        self.assertEqual(resumed['execution_compatibility']['reason'],'legacy_task_version_unknown')
        with self.assertRaisesRegex(ValueError,'旧任务'):
            self.checkpoint()
        self.assertEqual(before,self.reg.db.execute('SELECT data FROM tasks').fetchone()[0])

    def test_tampered_method_rejected(self):
        from filmprod.modules import module_root
        import shutil
        copied=Path(self.tmp.name)/'modules'
        shutil.copytree(module_root(),copied)
        state=json.loads((copied/'manifest.json').read_text(encoding='utf-8'))
        entry=copied/state['modules'][0]['entrypoint']
        entry.write_text(entry.read_text(encoding='utf-8')+'\nTAMPER',encoding='utf-8')
        with patch('filmprod.modules.module_root',return_value=copied),self.assertRaisesRegex(ValueError,'校验失败'):
            self.create()
        self.assertEqual(self.reg.snapshot()['tasks'],[])

    def test_script_route_requires_explicit_mode(self):
        for stage in ('source_script','dynamic_script','screenplay','script'):
            self.assertEqual(resolve(stage)['status'],'needs_workflow_selection')
            original=resolve(stage,'screenplay')
            adaptation=resolve(stage,'novel_to_screen')
            self.assertEqual(original['module']['id'],'screenwriter')
            self.assertEqual(original['screenwriting_mode'],'original')
            self.assertEqual(adaptation['module']['id'],'screenwriter')
            self.assertEqual(adaptation['screenwriting_mode'],'adaptation')
        self.assertNotEqual(execution_lock('screenplay','screenplay'),execution_lock('screenplay','novel_to_screen'))

    def test_missing_methods_do_not_hide_saved_draft(self):
        self.create()
        self.checkpoint()
        with patch('filmprod.modules.catalog',side_effect=ValueError('missing files')):
            resumed=self.reg.dispatch('task.resume',{'task_id':'T'})
            self.assertEqual(resumed['execution_compatibility']['reason'],'methods_unavailable')
            self.assertEqual(resumed['checkpoint']['draft'],'synthetic draft')


if __name__=='__main__':
    unittest.main()

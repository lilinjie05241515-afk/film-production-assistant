import tempfile
import unittest
from pathlib import Path
from filmprod.core import Registry

class ClientContractTests(unittest.TestCase):
    def test_history_keeps_exact_contents_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=Registry(Path(tmp)/'test')
            try:
                r.dispatch('project.init',dict(op_id='init',project_id='TEST',title='客户端合同测试',test_only=True))
                for n in range(2):
                    r.dispatch('artifact.save',dict(op_id=f'save{n}',artifact_id='SCRIPT-S01',kind='script',scope='S01',content=f'完整正文 {n+1}',base_version=n,deps=[]))
                before=r.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
                history=r.dispatch('artifact.history',{'artifact_id':'SCRIPT-S01'})
                self.assertEqual([v['content'] for v in history['versions']],['完整正文 1','完整正文 2'])
                self.assertEqual([v['version'] for v in history['versions']],[1,2])
                self.assertTrue(history['read_only'])
                self.assertEqual(r.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],before)
                with self.assertRaises(ValueError): r.dispatch('artifact.history',{'artifact_id':'absent'})
                caps=r.snapshot()['capabilities']
                self.assertFalse(caps['http_server_required'])
                self.assertFalse(caps['external_model_api_required'])
                self.assertEqual(caps['module_output_kinds']['screenplay'],['character_bio','screenplay','script','source_script'])
            finally:
                r.close()

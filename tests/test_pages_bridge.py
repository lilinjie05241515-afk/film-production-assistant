import copy
import hashlib
import tempfile
import unittest
from filmprod.core import Registry
from filmprod.pages_bridge import import_observation

class PagesBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.r=Registry(self.temp.name)
        self.r.dispatch('project.init',{'op_id':'init','project_id':'TEST','title':'TEST','test_only':True})
        # Synthetic complete host observations: no personal Pages, accounts,
        # real manuscripts or old cloud evidence are required by this suite.
        texts = [
            'TEST synthetic working draft',
            '# 测试场 S01',
            '合成人物甲把纸片放在桌上。',
            '纸片保持完整。',
            '# 测试场 S02',
            '合成人物乙站在门边，等待回答。',
            '门外只有风声。',
            '# 测试场 S03',
            '合成人物丙转身看向窗户。',
            '窗户仍然关着。',
        ]
        def block(index, text):
            return {'kind':'markdown','id':f'TEST-BLOCK-{index}',
                    'hash':hashlib.sha256(text.encode()).hexdigest(),'markdown':text}
        self.before = {
            'test_only':True, 'synthetic':True, 'view':'full',
            'selection':{'whole_page_complete':True},
            'observed_at':'2026-10-24T10:00:00+00:00',
            'metadata':{'page_id':'TEST-SYNTHETIC-PAGE','current_sequence':1,
                        'url':'https://example.invalid/TEST-SYNTHETIC-PAGE'},
            'content':{'page_id':'TEST-SYNTHETIC-PAGE',
                       'blocks':[block(i,text) for i,text in enumerate(texts)]},
        }
        self.after = copy.deepcopy(self.before)
        self.after['metadata']['current_sequence'] = 2
        self.after['observed_at'] = '2026-10-24T11:00:00+00:00'
        self.after['content']['blocks'][8] = block(8, '合成人物丙停下脚步，再看向窗户。')
    def tearDown(self):
        self.r.close(); self.temp.cleanup()
    def test_only_changed_scene_new_version_and_stale_rejected(self):
        import_observation(self.r,self.before,'before')
        result=import_observation(self.r,self.after,'after')
        self.assertEqual(result['changed_scenes'],['S03'])
        self.assertEqual(import_observation(self.r,self.after,'duplicate')['results'],[])
        with self.assertRaises(ValueError): import_observation(self.r,self.before,'old')
        self.assertEqual({a['artifact_id']:a['version'] for a in self.r.snapshot()['artifacts'] if a['kind']=='script'},{'SCRIPT-S01':1,'SCRIPT-S02':1,'SCRIPT-S03':2})
    def test_partial_and_empty_reads_not_empty_script(self):
        for data in [{},dict(self.before,selection={'whole_page_complete':False}),dict(self.before,view='excerpts')]:
            with self.assertRaises(ValueError): import_observation(self.r,data,'bad')
        self.assertEqual(self.r.snapshot()['artifacts'],[])
    def test_duplicate_scene_mapping_rejected(self):
        data=copy.deepcopy(self.before)
        data['content']['blocks'].append(data['content']['blocks'][1])
        with self.assertRaises(ValueError): import_observation(self.r,data,'duplicate')

    def test_unchanged_text_advances_observation_watermark(self):
        import_observation(self.r,self.before,'v1')
        newer=copy.deepcopy(self.before); newer['metadata']['current_sequence']=3; newer['observed_at']='2026-10-24T19:00:00+00:00'
        self.assertEqual(import_observation(self.r,newer,'v3')['changed_scenes'],[])
        with self.assertRaises(ValueError): import_observation(self.r,self.after,'late-v2')

    def test_unapproved_cloud_deletion_does_not_invalidate_downstream(self):
        import_observation(self.r,self.before,'v1')
        self.r.dispatch('artifact.save',dict(op_id='director',artifact_id='D2',kind='director',scope='S02',content='director',base_version=0,deps=[{'artifact_id':'SCRIPT-S02','version':1}]))
        data=copy.deepcopy(self.after); data['content']['blocks']=data['content']['blocks'][:4]+data['content']['blocks'][7:]
        result=import_observation(self.r,data,'removed')
        self.assertIn('S02',result['changed_scenes'])
        self.assertEqual(self.r.dispatch('artifact.get',{'artifact_id':'D2'})['status'],'candidate')
        self.assertTrue(self.r.dispatch('artifact.get',{'artifact_id':'SCRIPT-S02'})['metadata']['deleted_in_cloud'])
        self.assertIn('合成人物乙',self.r.dispatch('artifact.get',{'artifact_id':'SCRIPT-S02','version':1})['content'])

    def test_unsupported_block_rejected_before_partial_write(self):
        data=copy.deepcopy(self.before); data['content']['blocks'].append({'kind':'image','id':'x'})
        with self.assertRaises(ValueError): import_observation(self.r,data,'unsupported')
        self.assertEqual(self.r.snapshot()['artifacts'],[])

    def test_unknown_completeness_not_interpreted_as_deletion(self):
        import_observation(self.r,self.before,'before')
        data=copy.deepcopy(self.after); data.pop('view',None); data.pop('selection',None); data['content']['blocks']=data['content']['blocks'][:4]
        with self.assertRaises(ValueError): import_observation(self.r,data,'unknown')
        self.assertEqual(self.r.dispatch('artifact.get',{'artifact_id':'SCRIPT-S02'})['version'],1)

    def test_local_candidate_kept_when_remote_changes(self):
        import_observation(self.r,self.before,'before')
        self.r.dispatch('artifact.save',dict(op_id='local',artifact_id='SCRIPT-S03',kind='script',scope='S03',content='本地修改',base_version=1,deps=[],metadata={'local_candidate':True,'page_id':self.before['content']['page_id']}))
        with self.assertRaises(ValueError): import_observation(self.r,self.after,'remote')
        self.assertEqual(self.r.dispatch('artifact.get',{'artifact_id':'SCRIPT-S03'})['content'],'本地修改')

if __name__=='__main__': unittest.main()

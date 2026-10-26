import copy
import tempfile
import unittest
from filmprod.core import Registry
from filmprod.pages_bridge import import_observation


class WorkingDraftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.r = Registry(self.tmp.name)
        self.r.dispatch('project.init', dict(op_id='init', project_id='TEST-PAGES120', title='TEST', test_only=True))
        self.obs = dict(category='novel', view='full', observed_at='2026-10-24T08:00:00+00:00',
            metadata={'page_id':'page_TEST', 'url':'https://chatgpt.com/space/page_TEST'},
            content={'page_id':'page_TEST', 'title':'TEST 小说工作稿', 'through_sequence':3,
                     'blocks':[{'id':'b1','hash':'h1','kind':'markdown','markdown':'# 第一章'},
                               {'id':'b2','hash':'h2','kind':'markdown','markdown':'TEST 初稿，尚未通过。\n换行保留。'}]})

    def tearDown(self):
        self.r.close()
        self.tmp.cleanup()

    def test_full_draft_has_content_category_and_no_approval(self):
        out = import_observation(self.r, self.obs, 'test')
        self.assertFalse(out['approval_changed'])
        a = self.r.snapshot()['artifacts'][0]
        self.assertEqual(a['kind'], 'cloud_working_draft')
        self.assertEqual(a['metadata']['cloud_revision'], 3)
        self.assertEqual(a['content'], '# 第一章\n\nTEST 初稿，尚未通过。\n换行保留。')
        self.assertFalse(self.r.snapshot()['decisions'])
        self.assertFalse(import_observation(self.r, self.obs, 'duplicate')['changed'])

    def test_partial_stale_and_same_revision_difference_rejected(self):
        import_observation(self.r, self.obs, 'before')
        for mutation in ('partial','stale','conflict','category'):
            bad = copy.deepcopy(self.obs)
            if mutation == 'partial': bad['selection']={'whole_page_complete':False}
            if mutation == 'stale': bad['content']['through_sequence']=2
            if mutation == 'conflict': bad['content']['blocks'][1]['markdown']='不同内容'
            if mutation == 'category': bad['category']='script'
            with self.assertRaises(ValueError): import_observation(self.r,bad,mutation)
        self.assertEqual(self.r.snapshot()['artifacts'][0]['version'],1)

    def test_new_observation_keeps_prior_body(self):
        import_observation(self.r,self.obs,'before')
        after=copy.deepcopy(self.obs)
        after['content']['through_sequence']=4
        after['content']['blocks'][1].update(hash='h3',markdown='TEST 云端修订，仍未通过。')
        import_observation(self.r,after,'after')
        a=self.r.snapshot()['artifacts'][0]
        history=self.r.dispatch('artifact.history',{'artifact_id':a['artifact_id']})['versions']
        self.assertEqual(len(history),2)
        self.assertIn('换行保留',history[0]['content'])
        self.assertEqual(history[1]['metadata']['cloud_revision'],4)

    def test_asset_alias_and_cloud_body_are_not_creative_segments(self):
        self.obs['category']='assets'
        import_observation(self.r,self.obs,'asset')
        snap=self.r.snapshot()
        self.assertEqual(snap['artifacts'][0]['metadata']['category'],'asset')
        self.assertFalse(snap['current_content'])
        self.assertFalse(snap['pending_candidates'])

    def test_character_and_style_cloud_reads_never_become_approved_context(self):
        for category in ('character_bio', 'style'):
            obs=copy.deepcopy(self.obs)
            obs['category']=category
            obs['content']['page_id']='page_TEST_'+category
            obs['metadata']['page_id']=obs['content']['page_id']
            import_observation(self.r,obs,'test-'+category)
        snap=self.r.snapshot()
        self.assertEqual({a['metadata']['category'] for a in snap['artifacts']},{'character_bio','style'})
        self.assertFalse(snap['approved_artifacts'])
        self.assertFalse(snap['masters'])
        self.assertFalse(snap['decisions'])


if __name__=='__main__': unittest.main()

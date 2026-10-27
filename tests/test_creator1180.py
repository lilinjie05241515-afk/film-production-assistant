import hashlib
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from filmprod.core import Registry, ConflictError
from filmprod.projects import ProjectCatalog
from filmprod.board_gateway1150 import ALL_ACTIONS


class CreatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='TEST-creator1180-')
        # Match the catalog's canonical root on Windows RUNNER~1 and macOS /var aliases.
        self.root=Path(self.tmp.name).resolve()/'TEST-project'
        self.r=Registry(self.root)
        self.call('project.init',project_id='TEST-1180',title='TEST creative',test_only=True)
        self.script=self.call('artifact.save',artifact_id='SCRIPT',kind='script',scope='episode/1',content='完整测试剧本',base_version=0)['artifact']
        self.image=self.root/'TEST-image.bin';self.image.write_bytes(b'TEST-SYNTHETIC-IMAGE')
        self.media=self.call('media.register',media_id='IMG',kind='image',path=str(self.image),metadata={'title':'TEST image'})
    def tearDown(self):
        self.r.close();self.tmp.cleanup()
    def call(self,action,**p):
        p.setdefault('op_id',uuid.uuid4().hex)
        if action!='project.init':p.setdefault('expected_project_id','TEST-1180')
        return self.r.dispatch(action,p)
    def ref(self,a):
        artifact='artifact_id' in a
        return {'target_type':'artifact' if artifact else 'media','target_id':a['artifact_id'] if artifact else a['media_id'],**({'version':a['version']} if artifact else {}),'expected_sha256':a['sha256']}
    def obj(self,oid='elder'):
        return self.call('board.object.set',object_id=oid,base_revision=0,title='老人',type='character',intro='',scope='project')
    def link(self,reference=False):
        return self.call('board.asset.link',**self.ref(self.media),base_revision=0,object_id='elder',purpose='日常造型',reference=reference)
    def select(self,**extra):
        return self.call('board.asset.select',**self.ref(self.media),object_id='elder',purpose='日常造型',base_revision=0,link_revision=1,confirmed=True,**extra)
    def test_profile_revision_and_catalog_read(self):
        self.call('board.project.set',base_revision=0,title='新名称',intro='介绍',cover=None)
        with self.assertRaises(ConflictError):self.call('board.project.set',base_revision=0,title='旧',intro='',cover=None)
        self.assertEqual(self.r.snapshot()['project']['title'],'新名称')
        catalog=ProjectCatalog(Path(self.tmp.name)/'catalog.sqlite')
        try:
            catalog.dispatch('register',{'root':str(self.root),'op_id':'register'})
            self.call('board.project.set',base_revision=1,title='再改名称',intro='',cover=None)
            self.assertEqual(catalog.snapshot()['projects'][0]['title'],'再改名称')
        finally:catalog.close()

    def test_board_gateway_real_stdio_confirmation_and_snapshot(self):
        import os, subprocess, sys
        self.r.close()
        payload={**self.ref(self.script),'op_id':'stdio-confirm','expected_project_id':'TEST-1180',
                 'base_master_version':0,'base_latest_version':1,'confirmed':True}
        requests=[{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'film_board_manage','arguments':{'root':str(self.root),'action':'board.confirm','payload':payload}}},
                  {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'film_board_manage','arguments':{'root':str(self.root),'action':'snapshot','payload':{'expected_project_id':'TEST-1180'}}}}]
        env={k:v for k,v in os.environ.items() if not k.startswith('FILMPROD_')}
        env['FILMPROD_CATALOG_PATH']=str(Path(self.tmp.name)/'isolated-catalog.sqlite')
        run=subprocess.run([sys.executable,'-X','utf8','-B','plugin/mcp_server.py'],input=''.join(json.dumps(x)+'\n' for x in requests),text=True,encoding='utf-8',capture_output=True,env=env,timeout=30)
        self.assertEqual(run.returncode,0,run.stderr)
        rows=[json.loads(x) for x in run.stdout.splitlines()]
        self.assertEqual(len(rows),2)
        for row in rows:self.assertFalse(row.get('error') or row.get('result',{}).get('isError'),str(row)[:1000])
        self.assertEqual(rows[1]['result']['structuredContent']['decisions'][0]['artifact_id'],'SCRIPT')
        self.assertTrue(rows[1]['result']['structuredContent']['decisions'][0]['synthetic'])
        self.r=Registry(self.root)

    def test_style_selection_records_choice_without_approval_or_generation(self):
        import test_art1130
        fixture=test_art1130.ArtTests();fixture.setUp()
        try:
            fixture.prepare()
            art=fixture.read();ref=fixture.alt
            p={'comparison_id':'comparison','choice':'alternate','target_id':ref['artifact_id'],
               'version':ref['version'],'expected_sha256':ref['sha256'],'base_revision':art['revision'],'confirmed':True}
            selected=fixture.call('board.style.select',**p)
            self.assertEqual(selected['selection']['choice'],'alternate')
            self.assertTrue(selected['selection']['synthetic'])
            self.assertFalse(selected['selection_is_approval'])
            self.assertIsNone(fixture.r._artifact('style'))
            with self.assertRaises(ConflictError):fixture.call('board.style.select',**p)
        finally:fixture.tearDown()
    def test_explicit_confirmation_uses_core_pointer_and_idempotency(self):
        p={**self.ref(self.script),'base_master_version':0,'base_latest_version':1,'confirmed':True,'op_id':'confirm1'}
        a=self.call('board.confirm',**p);b=self.call('board.confirm',**p)
        self.assertEqual(a,b)
        self.assertTrue(a['decision']['synthetic'])
        self.assertEqual(len(self.r.snapshot()['decisions']),1)
        self.assertEqual(a['decision']['user_authorization']['source'],'panel-click')
    def test_stale_candidate_and_wrong_hash_rejected(self):
        self.call('artifact.save',artifact_id='SCRIPT',kind='script',scope='episode/1',content='新稿',base_version=1)
        with self.assertRaises(ConflictError):self.call('board.confirm',**self.ref(self.script),base_master_version=0,base_latest_version=1,confirmed=True)
        p=self.ref(self.script);p['expected_sha256']='0'*64
        with self.assertRaises(ConflictError):self.call('board.confirm',**p,base_master_version=0,base_latest_version=2,confirmed=True)
        self.assertEqual(self.r.snapshot()['decisions'],[])
    def test_links_and_selections_exact_and_reference_not_adoptable(self):
        self.obj();self.link(reference=True)
        with self.assertRaises(ValueError):self.select()
        self.assertEqual(self.r.snapshot()['creator_board']['selections'],[])
        self.call('board.asset.link',**self.ref(self.media),base_revision=1,object_id='elder',purpose='日常造型',reference=False)
        result=self.call('board.asset.select',**self.ref(self.media),object_id='elder',purpose='日常造型',base_revision=0,link_revision=2,confirmed=True)
        self.assertEqual(result['reference']['sha256'],self.media['sha256'])
        with self.assertRaises(ConflictError):self.call('board.asset.link',**self.ref(self.media),base_revision=2,object_id='elder',purpose='基础形象',reference=False)
    def test_changed_bytes_cannot_be_selected(self):
        self.obj();self.link();(self.root/self.media['path']).write_bytes(b'CHANGED')
        with self.assertRaises((ConflictError,ValueError)):self.select()
    def test_selection_preserves_candidates_and_other_purposes(self):
        self.obj();self.link();self.select(op_id='select1')
        self.assertEqual(len(self.r.snapshot()['media']),1)
        with self.assertRaises(ConflictError):self.select(op_id='different')
        snap=self.r.snapshot()['creator_board']
        self.assertEqual(len(snap['decisions']),1)
        self.assertEqual(snap['selections'][0]['purpose'],'日常造型')
    def test_cross_project_and_arbitrary_actions_rejected(self):
        with self.assertRaises(ConflictError):self.call('board.object.set',expected_project_id='OTHER',object_id='x',base_revision=0,title='X',type='character',intro='',scope='')
        for action in ['task.create','artifact.save','decision.record','content.approve','cloud.record']:
            self.assertNotIn(action,ALL_ACTIONS)
        self.assertIn('board.confirm',ALL_ACTIONS)
    def test_archive_restore_survives_restart_and_keeps_registry_and_bindings(self):
        path=Path(self.tmp.name)/'catalog.sqlite';c=ProjectCatalog(path)
        try:
            c.dispatch('register',{'op_id':'reg','root':str(self.root),'thread_id':'TEST-chat'})
            before=self.image.read_bytes()
            args={'op_id':'arc','project_id':'TEST-1180','expected_root':str(self.root),'base_revision':0,'status':'archived'}
            c.dispatch('visibility',args);c.dispatch('visibility',args)
            self.assertIsNone(c.snapshot({'thread_id':'TEST-chat'})['resolved_project'])
            self.assertEqual(len(c.snapshot()['bindings']),1)
            c.close();c=ProjectCatalog(path)
            self.assertEqual(c.snapshot()['projects'][0]['status'],'archived')
            c.dispatch('visibility',{**args,'op_id':'restore','base_revision':1,'status':'active'})
            self.assertEqual(c.snapshot({'thread_id':'TEST-chat'})['resolved_project']['project_id'],'TEST-1180')
            self.assertEqual(self.image.read_bytes(),before)
            self.assertEqual(len(self.r.snapshot()['artifacts']),1)
            with self.assertRaises(ConflictError):c.dispatch('visibility',{**args,'op_id':'stale'})
        finally:c.close()

if __name__=='__main__':unittest.main()

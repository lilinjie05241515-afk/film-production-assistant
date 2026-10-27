import base64
import concurrent.futures
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from filmprod.core import Registry,ConflictError
from filmprod.previs1190 import validate_plan,sha,MAX_CHUNK
from filmprod.board_gateway1150 import ALL_ACTIONS
from filmprod.render import _exe

SOURCE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('test_previs_executor',SOURCE/'modules/director-agent/previs/execute.py')
executor=importlib.util.module_from_spec(spec)
spec.loader.exec_module(executor)


def synthetic_plan():
    """Registry contract fixture; no project content or Blender render claim."""
    def key(frame,x,y=0):return {'frame':frame,'position':[x,y,0],'yaw':0}
    return {'schema_version':1,'fps':12,'frames':216,'width':128,'height':72,
        'space':{'visible_structure':'TEST simple floor','assumed_dimensions':'TEST assumed metres',
                 'unseen_areas':'TEST none inferred','allowed_adjustments':'TEST only',
                 'boxes':[{'id':'floor','position':[0,0,-.1],'size':[8,8,.2]}]},
        'actors':[{'id':'A','name':'TEST A','color':'#db6651','keys':[key(0,-2),key(48,-1),key(72,-1),key(144,1),key(216,2)]},
                  {'id':'B','name':'TEST B','color':'#448cd3','keys':[key(0,2,1),key(216,2,1)]},
                  {'id':'C','name':'TEST C','color':'#d9b84a','keys':[key(0,-2,2),key(216,-2,2)]}],
        'shots':[{'id':sid,'start':start,'end':end,'method':'TEST camera '+sid,'lens':40,
                  'camera':[{'frame':frame,'position':[5,-8,5],'target':[0,0,1]} for frame in (start,end)]}
                 for sid,start,end in [('SH010',0,72),('SH020',72,144),('SH030',144,216)]]}


def make_registry_fixture(root):
    """Real encoded colour videos, with a deliberately non-rendered Blend stub.

    The executable Blender/scene validation is performed separately by CI. This
    fixture tests immutable hashes, references, decisions and chunk transport.
    """
    try:ffmpeg,ffprobe=_exe('ffmpeg'),_exe('ffprobe')
    except ValueError as exc:raise unittest.SkipTest(str(exc)) from exc
    encoded=root/'TEST-colour.mp4'
    subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-n','-f','lavfi','-i',
        'color=c=blue:s=128x72:r=12:d=18','-frames:v','216','-c:v','libx264','-pix_fmt','yuv420p',str(encoded)],
        check=True,capture_output=True,timeout=60)
    # A valid MP4 free atom makes the transport exercise more than one chunk.
    with encoded.open('ab') as stream:
        stream.write(struct.pack('>I4s',MAX_CHUNK+32,b'free')+bytes(MAX_CHUNK+24))
    observed=executor.probe(encoded,ffprobe)
    assert observed['frames']==216 and observed['duration']==18
    for version in (1,2):
        folder=root/f'v{version:03}';folder.mkdir()
        m=synthetic_plan()
        if version==2:
            m['actors'][0]['keys'].insert(3,{'frame':108,'position':[0,.5,0],'yaw':0})
            m['shots'][1]['method']='TEST alternate camera'
            m['shots'][1]['camera'][0]['position']=[5,-8,6]
        validate_plan(m)
        (folder/'plan.json').write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf-8')
        (folder/'scene.blend').write_bytes(b'BLENDER-v300\nTEST_ONLY_REGISTRY_STUB_NOT_A_RENDERED_SCENE\n')
        for view in ('camera','top'):shutil.copyfile(encoded,folder/(view+'.mp4'))
        receipt={'schema_version':1,'plan_sha256':sha(folder/'plan.json'),'frames':216,'fps':12,
                 'files':{k:sha(folder/f) for k,f in [('blend','scene.blend'),('camera','camera.mp4'),('top','top.mp4')]},
                 'probes':{'camera':observed,'top':observed},'test_only':True,
                 'validation':'real_ffmpeg_colour_video; blend_is_registry_stub_not_rendered'}
        (folder/'receipt.json').write_text(json.dumps(receipt),encoding='utf-8')


def initialize(root):
    r=Registry(root)
    def call(action,**p):
        return r.dispatch(action,dict(op_id=uuid.uuid4().hex,**({'expected_project_id':'TEST-PREVIS'} if action!='project.init' else {}),**p))
    try:
        call('project.init',project_id='TEST-PREVIS',title='TEST 三人立柱调度',test_only=True)
        script=call('artifact.save',artifact_id='TEST-SCRIPT',kind='script',scope='TEST-S01',content='TEST 原创技术场景：A 进场穿过立柱前方与 B 会合；C 在后方观察。停顿、转向、走位用于测试。',base_version=0)['artifact']
        director=call('artifact.save',artifact_id='TEST-DIRECTOR',kind='director',scope='TEST-S01',content='TEST 拍法：SH010 全景推进；SH020 侧移跟 A；SH030 双人会合。角色连续，立柱保留。',base_version=0,deps=[{'artifact_id':script['artifact_id'],'version':1}])['artifact']
        call('task.create',task_id='TEST-DIRECTOR-TASK',title='TEST 三人场景预演',module='director',scope='TEST-S01',inputs=[{'artifact_id':script['artifact_id'],'version':1}],must_keep=['TEST identities'],allowed_changes=['camera and blocking within TEST'],requirements=['18 seconds, 3 shots'])
        return r,script,director
    except Exception:
        r.close()
        raise


def payload(root,script,director,folder='v001',revision=0,feedback_ids=None):
    return {'op_id':uuid.uuid4().hex,'expected_project_id':'TEST-PREVIS','previs_id':'TEST-S01','task_id':'TEST-DIRECTOR-TASK','scope':'TEST-S01','title':'三人 · 立柱 · 会合','base_revision':revision,
        'manifest':json.loads((root/folder/'plan.json').read_text(encoding='utf-8')),
        'sources':{role:{k:a[k] for k in ('artifact_id','version','sha256')} for role,a in [('script',script),('director',director)]},
        'files':{k:{'path':f'{folder}/{f}','sha256':sha(root/folder/f)} for k,f in {'blend':'scene.blend','camera':'camera.mp4','top':'top.mp4','plan':'plan.json','receipt':'receipt.json'}.items()},
        'change_note':'初版 TEST' if folder=='v001' else 'TEST 修订：SH020 摄影机抬高外移；A 绕行路线远离柱脚。','feedback_ids':feedback_ids or []}


class PrevisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_tmp=tempfile.TemporaryDirectory(prefix='TEST-previs-fixture-')
        cls.addClassCleanup(cls.fixture_tmp.cleanup)
        cls.fixture=Path(cls.fixture_tmp.name).resolve()
        make_registry_fixture(cls.fixture)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='TEST-previs-');self.root=Path(self.tmp.name).resolve()
        self.addCleanup(self.tmp.cleanup)
        for v in ('v001','v002'):
            (self.root/v).mkdir()
            for f in ('plan.json','scene.blend','camera.mp4','top.mp4','receipt.json'):shutil.copy2(self.fixture/v/f,self.root/v/f)
        self.r,self.script,self.director=initialize(self.root)
        self.p=payload(self.root,self.script,self.director)
        self.v=self.r.dispatch('previs.register',self.p)['registered']
    def tearDown(self):self.r.close();self.tmp.cleanup()
    def exact(self,**p):return dict(op_id=uuid.uuid4().hex,expected_project_id='TEST-PREVIS',previs_id='TEST-S01',version=1,expected_sha256=self.v['sha256'],base_revision=1,**p)
    def test_exact_feedback_preserves_quote_idempotency_and_conflicts(self):
        p=self.exact(shot_id='SH020',time=8.125,quote='  摄影机抬高一些\n 保留脚下路线  ')
        a=self.r.dispatch('previs.feedback',p);self.assertEqual(a,self.r.dispatch('previs.feedback',p));self.assertEqual(a['feedback']['quote'],p['quote']);self.assertTrue(a['feedback']['synthetic'])
        with self.assertRaises(ConflictError):self.r.dispatch('previs.feedback',{**p,'quote':'另一个意思'})
        with self.assertRaises(ConflictError):self.r.dispatch('previs.feedback',{**p,'op_id':'stale'})
    def test_read_and_full_chunk_do_not_mutate_or_execute(self):
        self.r.close();before=sha(self.root/'.project/registry.sqlite3');self.r=Registry.open_readonly(self.root)
        allbytes=b'';offset=0
        while True:
            d=self.r.dispatch('previs.chunk',{k:v for k,v in self.exact(view='camera',offset=offset).items() if k not in {'op_id','base_revision'}})
            part=base64.b64decode(d['data_base64']);self.assertLessEqual(len(part),MAX_CHUNK);allbytes+=part;offset=d['next']
            if offset==d['total']:break
        self.assertEqual(hashlib.sha256(allbytes).hexdigest(),self.v['files']['camera']['sha256'])
        self.r.snapshot();self.r.dispatch('previs.read',{'expected_project_id':'TEST-PREVIS'})
        self.assertEqual(before,sha(self.root/'.project/registry.sqlite3'))
        self.assertNotIn('previs.register',ALL_ACTIONS);self.assertNotIn('previs.render',ALL_ACTIONS)
    def test_hash_tamper_path_traversal_and_wrong_project_rejected(self):
        with self.assertRaises(ValueError):self.r.dispatch('previs.feedback',{**self.exact(shot_id='SH010',time=1,quote='x'),'expected_sha256':'0'*64})
        with self.assertRaises(ValueError):self.r.dispatch('previs.read',{'expected_project_id':'wrong'})
        (self.root/'v001/camera.mp4').write_bytes(b'changed')
        with self.assertRaises(ValueError):self.r.dispatch('previs.select',self.exact(shot_id=None,confirmed=True))
        p=payload(self.root,self.script,self.director,'v002',1);p['files']['blend']['path']='../outside.blend'
        with self.assertRaises(ValueError):self.r.dispatch('previs.register',p)
    def test_synthetic_scope_selection_and_mixed_choices_require_assembly(self):
        a=self.r.dispatch('previs.select',self.exact(shot_id=None,confirmed=True));self.assertTrue(a['decision']['synthetic'])
        v2=self.r.dispatch('previs.register',payload(self.root,self.script,self.director,'v002',2))['registered']
        self.r.dispatch('previs.select',{**self.exact(shot_id='SH020',confirmed=True),'base_revision':3,'version':2,'expected_sha256':v2['sha256']})
        s=self.r.dispatch('previs.read',{'expected_project_id':'TEST-PREVIS'})['series'][0]
        self.assertTrue(s['assembly_required']);self.assertEqual(s['approved_version']['version'],1)
        sys.path.insert(0,str(SOURCE/'modules/director-agent/previs'));from compose import compose
        plan=compose(s);self.assertEqual(plan['frames'],216);self.assertEqual(plan['composition']['source_choices'][1]['version'],2)
        broken=copy.deepcopy(s);broken['versions'][1]['manifest']['actors'][0]['keys'][2]['position'][0]+=1
        with self.assertRaises(ValueError):compose(broken)
    def test_dependency_changes_keep_history_but_block_new_selection(self):
        self.r.dispatch('artifact.save',dict(op_id='change',artifact_id='TEST-SCRIPT',kind='script',scope='TEST-S01',content='新剧情',base_version=1))
        s=self.r.dispatch('previs.read',{'expected_project_id':'TEST-PREVIS'})['series'][0]
        self.assertTrue(s['versions'][0]['stale_reasons'])
        with self.assertRaises(ConflictError):self.r.dispatch('previs.select',self.exact(shot_id=None,confirmed=True))
    def test_parallel_same_base_only_one_commit(self):
        def write(i):
            r=Registry(self.root)
            try:return r.dispatch('previs.feedback',self.exact(shot_id='SH010',time=1,quote=str(i)))
            except ConflictError:return 'conflict'
            finally:r.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(write,range(2)))
        self.assertEqual(results.count('conflict'),1)
    def test_timing_boundaries_and_manifest_validation(self):
        for time in (-1,6,18,float('nan')):
            with self.assertRaises(ValueError):self.r.dispatch('previs.feedback',self.exact(shot_id='SH010',time=time,quote='x'))
        m=copy.deepcopy(self.p['manifest']);m['shots'][1]['start']=71
        with self.assertRaises(ValueError):validate_plan(m)
        m=copy.deepcopy(self.p['manifest']);m['actors'][1]['color']=m['actors'][0]['color']
        with self.assertRaises(ValueError):validate_plan(m)
    def test_real_stdio_contract_and_visibility(self):
        calls=[{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'film_board_manage','arguments':{'root':str(self.root),'action':'previs.read','payload':{'expected_project_id':'TEST-PREVIS'}}}},
               {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'film_board_manage','arguments':{'root':str(self.root),'action':'previs.register','payload':self.p}}}]
        env=dict(os.environ,FILMPROD_CATALOG_PATH=str(self.root/'catalog.sqlite'))
        run=subprocess.run([sys.executable,'-X','utf8','-B',str(SOURCE/'plugin/mcp_server.py')],input=''.join(json.dumps(c)+'\n' for c in calls),capture_output=True,text=True,encoding='utf-8',env=env,timeout=30)
        rows=[json.loads(x) for x in run.stdout.splitlines()]
        self.assertEqual(rows[0]['result']['structuredContent']['series'][0]['versions'][0]['manifest']['frames'],216)
        self.assertTrue(rows[1]['result']['isError'])


class PrevisExecutableTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='TEST-previs-executable-')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        self.plan=self.root/'计划 test.json'
        self.plan.write_text(json.dumps(synthetic_plan()),encoding='utf-8')
        self.out=self.root/'输出 new version'

    def test_missing_explicit_dependencies_fail_before_output_or_process(self):
        valid=sys.executable;missing=str(self.root/'missing-executable')
        for blender,ffmpeg,ffprobe in ((missing,valid,valid),(valid,missing,valid),(valid,valid,missing),(valid,'',valid)):
            with self.subTest(blender=blender,ffmpeg=ffmpeg,ffprobe=ffprobe),patch.object(executor,'run') as run:
                with self.assertRaises(ValueError):executor.execute(self.plan,self.out,blender,ffmpeg,ffprobe)
                self.assertFalse(self.out.exists());run.assert_not_called()

    def test_existing_output_is_not_overwritten_or_resumed(self):
        self.out.mkdir();sentinel=self.out/'keep';sentinel.write_bytes(b'original')
        with patch.object(executor,'run') as run:
            with self.assertRaisesRegex(ValueError,'输出已存在'):
                executor.execute(self.plan,self.out,sys.executable,sys.executable,sys.executable)
        self.assertEqual(sentinel.read_bytes(),b'original');run.assert_not_called()

    def test_unknown_engine_is_rejected_before_any_output(self):
        with patch.object(executor,'run') as run:
            with self.assertRaisesRegex(ValueError,'预演引擎'):
                executor.execute(self.plan,self.out,sys.executable,engine='AUTO')
        self.assertFalse(self.out.exists());run.assert_not_called()

    def test_missing_gui_path_dependencies_fail_before_starting_blender(self):
        with patch('filmprod.render.shutil.which',return_value=None),patch('filmprod.render.sys.platform','darwin'), \
                patch('filmprod.render.MACOS_EXECUTABLE_DIRS',()),patch.object(executor,'run') as run:
            with self.assertRaisesRegex(ValueError,'ffmpeg'):
                executor.execute(self.plan,self.out,sys.executable)
        self.assertFalse(self.out.exists());run.assert_not_called()


if __name__=='__main__':unittest.main()

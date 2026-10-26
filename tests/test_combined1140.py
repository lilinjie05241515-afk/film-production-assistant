"""Writer feedback and art baseline coexist on the same isolated TEST project."""
import tempfile,unittest,uuid
from pathlib import Path
from filmprod.core import Registry

class Combined1140Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='TEST-combined1140-');self.root=Path(self.tmp.name)/'project';self.r=Registry(self.root)
  self.call('project.init',project_id='TEST-COMBINED',title='TEST 编剧美术共同项目',test_only=True)
 def tearDown(self):self.r.close();self.tmp.cleanup()
 def call(self,action,**kw):
  kw.setdefault('op_id',uuid.uuid4().hex)
  if action!='project.init':kw.setdefault('expected_project_id','TEST-COMBINED')
  return self.r.dispatch(action,kw)
 def ref(self,a):return {k:a[k] for k in ('artifact_id','version','sha256')}
 def read(self,action):return self.r.dispatch(action,{'expected_project_id':'TEST-COMBINED'})
 def save(self,aid,kind,scope,text,version=0,deps=[]):return self.call('artifact.save',artifact_id=aid,kind=kind,scope=scope,content=text,base_version=version,deps=deps)['artifact']
 def approve(self,a):return self.call('content.approve',artifact_id=a['artifact_id'],version=a['version'],scope=a['scope'],actor='test',synthetic=True,evidence='TEST synthetic decision')
 def feedback(self,a):
  return self.call('screenwriting.record',base_revision=self.read('screenwriting.read')['revision'],feedback_id='TEST-FB',script=self.ref(a),scope=a['scope'],scene_id='S01',anchor='母亲拧紧螺钉。',problem='动作不清楚',expected_effect='看清工具接触',must_keep=['母女共同修理'],impact='expression',source={'role':'director','reference':'TEST-director'})
 def test_candidate_writer_revision_does_not_adopt_or_displace_art_until_explicit_approval(self):
  script=self.save('TEST-SCRIPT','script','S01','S01 内 修理铺 清晨\n母亲拧紧螺钉。女儿扶稳收音机。');self.approve(script)
  style=self.save('TEST-STYLE','style_bible','project/style','# 基准\n米灰墙，深蓝外套。\n声音：保留收音机杂音。\n表演：克制。',deps=[self.ref(script)]);self.approve(style)
  before=self.read('art.read');self.assertEqual(before['revision_source_kind'],'legacy_approved')
  feedback=self.feedback(script);self.assertEqual(self.read('art.read'),before)
  revised=self.save('TEST-SCRIPT','script','S01','S01 内 修理铺 清晨\n母亲把螺丝刀尖卡入螺钉槽，顺时针拧紧。女儿扶稳收音机。',1)
  self.call('screenwriting.resolve',base_revision=feedback['revision'],feedback_id='TEST-FB',status='addressed',response='TEST 已明确工具接触，保留共同修理。',revised_script=self.ref(revised))
  self.assertEqual(self.read('art.read')['current_style'],self.ref(style));self.assertEqual(self.read('art.read')['current_style_status'],'approved')
  self.assertEqual(self.r._artifact('TEST-SCRIPT',2)['status'],'candidate')
  self.approve(revised)
  self.assertEqual(self.read('art.read')['current_style_status'],'needs_review')
  self.assertEqual(self.r._artifact('TEST-STYLE',1)['content'],style['content'])
 def test_art_local_revision_does_not_resolve_writer_feedback_or_rewrite_script(self):
  script=self.save('TEST-SCRIPT','script','S01','母亲拧紧螺钉。女儿扶稳收音机。');self.approve(script)
  style=self.save('TEST-STYLE','style_bible','project/style','# 基准\n米灰墙。\n声音：收音机杂音。',deps=[self.ref(script)]);self.approve(style)
  self.feedback(script);before=self.read('screenwriting.read')
  start=style['content'].index('米灰墙')
  result=self.call('art.revise',base_revision=0,selection_id=None,source_ref=self.ref(style),working_ref=self.ref(style),baseline=self.ref(style),base_version=1,edits=[{'start':start,'end':start+3,'quote':'米灰墙','replacement':'浅米灰墙'}],scope_judgment='within_baseline',reason='TEST 局部明度细化',user_request={'source':'conversation','reference':'TEST-art-user','quote':'TEST 墙面略浅一点'},synthetic=True)
  self.assertEqual(result['artifact']['content'],style['content'].replace('米灰墙','浅米灰墙'))
  self.assertEqual(self.read('screenwriting.read'),before)
  self.assertEqual(self.r._artifact('TEST-SCRIPT',1)['content'],script['content'])
  self.assertEqual(self.read('art.read')['current_style'],self.ref(style))

if __name__=='__main__':unittest.main()

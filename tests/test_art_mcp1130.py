"""Typed art MCP validation and read-only behavior; isolated TEST fixtures."""
import hashlib,importlib.util,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from filmprod.core import Registry

SOURCE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('mcp_art1130',SOURCE/'plugin/mcp_server.py')
server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)

class ArtMCPTests(unittest.TestCase):
 def setUp(self):
  temp=tempfile.TemporaryDirectory(prefix='TEST-art-mcp1130-');self.addCleanup(temp.cleanup)
  self.base=Path(temp.name);self.root=self.base/'TEST-project';self.pid='TEST-ART-MCP1130'
  self.env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','FILMPROD_CATALOG_PATH':str(self.base/'TEST-catalog.sqlite3')}
  r=Registry(self.root)
  try:r.dispatch('project.init',{'op_id':'init','project_id':self.pid,'title':'TEST art only','test_only':True})
  finally:r.close()
  self.db=self.root/'.project/registry.sqlite3'
 def args(self,action,**payload):return {'root':str(self.root),'action':action,'payload':{'expected_project_id':self.pid,**payload}}
 def call(self,name,args,error=False):
  with patch.dict(os.environ,self.env):result=server.handle({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}},None)['result']
  self.assertEqual(bool(result.get('isError')),error,result)
  if not error:self.assertEqual(json.loads(result['content'][0]['text']),result['structuredContent'])
  return result['structuredContent']
 def test_stdio_discovers_art_and_summary_has_no_writes(self):
  before=self.db.read_bytes()
  requests=[{'jsonrpc':'2.0','id':1,'method':'tools/list'},{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'film_art','arguments':self.args('read')}}]
  p=subprocess.run([sys.executable,'-B','-X','utf8',str(SOURCE/'plugin/mcp_server.py')],cwd=SOURCE,env=self.env,input=''.join(json.dumps(r)+'\n' for r in requests).encode(),capture_output=True,timeout=30)
  self.assertEqual(p.returncode,0,p.stderr);results=[json.loads(s) for s in p.stdout.splitlines()]
  names=[x['name'] for x in results[0]['result']['tools']];self.assertEqual(len(names),26);self.assertEqual(names.count('film_art'),1)
  state=results[1]['result']['structuredContent'];self.assertFalse(state['selection_is_approval']);self.assertEqual(state['comparisons'],[])
  self.assertEqual(self.db.read_bytes(),before)
 def test_both_read_entrypoints_use_readonly_registry(self):
  before=self.db.read_bytes()
  with patch.object(Registry,'__init__',side_effect=AssertionError('Read opened writable registry')):
   self.call('film_art',self.args('read'))
   self.call('film_dispatch',self.args('art.read'))
  self.assertEqual(self.db.read_bytes(),before)
 def test_invalid_types_and_fullbody_bypass_rejected_before_project_lookup(self):
  invalid=[self.args('read',op_id='extra'),self.args('read',include_content=True),self.args('select',op_id='s',base_revision=True,comparison_id='c',choice='main',user_request={'source':'conversation','reference':'TEST','quote':'TEST choose'},synthetic=True),self.args('integrate',op_id='i',base_revision=0,selection_id='s',base_version=0,content='unsafe replacement')]
  with patch.object(server,'checked_project_root',side_effect=AssertionError('Invalid input touched project')):
   for args in invalid:self.assertEqual(self.call('film_art',args,error=True)['error']['type'],'ValueError')
 def test_wrong_project_read_preserves_bytes(self):
  before=self.db.read_bytes();args=self.args('read');args['payload']['expected_project_id']='TEST-WRONG'
  self.call('film_art',args,error=True);self.assertEqual(self.db.read_bytes(),before)
 def test_main_alternate_to_complete_candidate_and_markdown_export(self):
  def dispatch(action,**p):return self.call('film_dispatch',self.args(action,**p))
  def save(aid,kind,scope,content,deps=[]):return dispatch('artifact.save',op_id='save-'+aid,artifact_id=aid,kind=kind,scope=scope,content=content,base_version=0,deps=deps)['artifact']
  def ref(a):return {k:a[k] for k in ('artifact_id','version','sha256')}
  scene=save('TEST-SCENE','script','scene/01','TEST 合成修理铺场景，母女一起接线。')
  main=save('TEST-MAIN','research','art/main','# 主选\n\n灰墙，木台，手部可见。',[ref(scene)])
  alt=save('TEST-ALT','research','art/alternate','# 备选\n\n暖墙，灰台，手部可见。',[ref(scene)])
  prepared=self.call('film_art',self.args('prepare',op_id='p',base_revision=0,comparison_id='TEST-CMP',title='TEST 主备',target_artifact_id='TEST-STYLE',baseline=None,working_ref=None,main=ref(main),alternate=ref(alt),context=[ref(scene)],visual_ranges=[],nonvisual_sections={'direction':'TEST 镜头不越轴。','performance':'TEST 表演克制。','sound':'TEST 保留收音机杂音。','world_rules':'TEST 普通物理。'}))
  selected_args=self.args('select',op_id='s',base_revision=prepared['revision'],comparison_id='TEST-CMP',choice='alternate',user_request={'source':'conversation','reference':'TEST-user','quote':'TEST 选择备选'},synthetic=True)
  selected=self.call('film_art',selected_args);self.assertEqual(selected,self.call('film_art',selected_args))
  full=self.call('film_art',self.args('read',comparison_id='TEST-CMP',include_content=True))
  self.assertEqual(full['proposals']['alternate']['content'],alt['content']);self.assertIn('TEST 表演克制。',full['integration_preview'])
  args=self.args('integrate',op_id='i',base_revision=selected['revision'],selection_id=selected['selection']['selection_id'],base_version=0)
  integrated=self.call('film_art',args);self.assertEqual(integrated,self.call('film_art',args));a=integrated['artifact']
  self.assertEqual(a['content'],full['integration_preview']);self.assertEqual(a['status'],'candidate')
  self.assertIsNone(self.call('film_art',self.args('read'))['current_style'])
  exported=dispatch('document.save',op_id='md',artifact_id=a['artifact_id'],version=a['version'],expected_sha256=a['sha256'])
  self.assertTrue(exported['saved_verified']);self.assertTrue(exported['readback_verified'])
  self.assertEqual(hashlib.sha256(Path(exported['local_path']).read_bytes()).hexdigest(),exported['sha256'])
  dispatch('content.approve',op_id='approve',artifact_id=a['artifact_id'],version=a['version'],scope=a['scope'],evidence='TEST synthetic acceptance only',actor='test',synthetic=True)
  quote='手部可见。';start=a['content'].index(quote)
  args=self.args('revise',op_id='revise',base_revision=integrated['art_revision'],selection_id=selected['selection']['selection_id'],source_ref=ref(a),working_ref=ref(a),baseline=ref(a),base_version=a['version'],edits=[{'start':start,'end':start+len(quote),'quote':quote,'replacement':'手部接触工具的位置清楚可见。'}],scope_judgment='within_baseline',reason='TEST 局部可读性',user_request={'source':'conversation','reference':'TEST-revision','quote':'TEST 只加强手部可读性'},synthetic=True)
  revised=self.call('film_art',args);self.assertEqual(revised,self.call('film_art',args))
  self.assertEqual(revised['artifact']['content'],a['content'].replace(quote,'手部接触工具的位置清楚可见。'))
  state=self.call('film_art',self.args('read'));self.assertEqual(state['current_style'],ref(a));self.assertEqual(len(state['comparisons']),1)

if __name__=='__main__':unittest.main()

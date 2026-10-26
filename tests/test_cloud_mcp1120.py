"""Public cloud orchestration integration; isolated projects, no remote calls."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from filmprod.core import Registry

SOURCE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('mcp_cloud1120',SOURCE/'plugin/mcp_server.py')
server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)

class CloudMCPTests(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory(prefix='filmprod-TEST-cloud-mcp1120-');self.addCleanup(t.cleanup)
  self.base=Path(t.name);self.root=self.base/'TEST-project';self.pid='TEST-CLOUD1120'
  self.env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','FILMPROD_CATALOG_PATH':str(self.base/'TEST-catalog.sqlite3')}
  r=Registry(self.root)
  try:r.dispatch('project.init',{'op_id':'init','project_id':self.pid,'title':'TEST cloud only','test_only':True})
  finally:r.close()
  self.db=self.root/'.project/registry.sqlite3'
 def payload(self,**kw):return {'expected_project_id':self.pid,**kw}
 def cloud(self,action,**kw):return {'root':str(self.root),'action':action,'payload':self.payload(**kw)}
 def call(self,name,args,error=False):
  with patch.dict(os.environ,self.env):result=server.handle({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}},None)['result']
  self.assertEqual(bool(result.get('isError')),error,result)
  if not error:self.assertEqual(json.loads(result['content'][0]['text']),result['structuredContent'])
  return result['structuredContent']
 def dispatch(self,action,**kw):return self.call('film_dispatch',{'root':str(self.root),'action':action,'payload':self.payload(**kw)})
 def update(self,trigger='full_draft'):return {'trigger':trigger,'user_request':{'source':'conversation','reference':'TEST-user-turn','quote':'整理完整初稿，并按每轮修改同步云稿。'}}
 def file_args(self,**kw):
  body='# TEST 大纲\n\n甲推开门，乙后退，先确认伤口再传递药盒。\n'
  p=self.root/'TEST-draft.md';p.write_text(body,encoding='utf-8')
  return {'root':str(self.root),**self.payload(op_id='save',artifact_id='TEST-OUTLINE',kind='outline',scope='project',base_version=0,source_path=p.name,expected_file_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),cloud_update=self.update(),**kw)}
 def test_real_stdio_discovery_and_read(self):
  requests=[{'jsonrpc':'2.0','id':1,'method':'tools/list'},{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'film_cloud','arguments':self.cloud('read')}}]
  p=subprocess.run([sys.executable,'-B','-X','utf8',str(SOURCE/'plugin/mcp_server.py')],cwd=SOURCE,env=self.env,input=''.join(json.dumps(r)+'\n' for r in requests).encode(),capture_output=True,timeout=30)
  self.assertEqual(p.returncode,0,p.stderr);results=[json.loads(line) for line in p.stdout.splitlines()]
  names=[t['name'] for t in results[0]['result']['tools']]
  self.assertEqual(len(names),25);self.assertEqual(names.count('film_cloud'),1)
  value=results[1]['result'];self.assertFalse(value.get('isError'),value)
  self.assertEqual(value['structuredContent']['jobs'],[])
 def test_read_never_opens_writable_registry_and_preserves_bytes(self):
  before=self.db.read_bytes()
  with patch.object(Registry,'__init__',side_effect=AssertionError('Read opened writable registry')):
   self.call('film_cloud',self.cloud('read'))
   self.dispatch('cloud.read')
  self.assertEqual(self.db.read_bytes(),before)
 def test_fixed_bad_arguments_reject_before_project_lookup(self):
  invalid=[self.cloud('read',op_id='extra'),self.cloud('configure',op_id='cfg',base_revision=True,mode='round_end',user_request=self.update()['user_request']),self.cloud('prepare',op_id='p',base_revision=0,artifact={'artifact_id':'TEST','version':True,'sha256':'0'*64},trigger='discussion',user_request=self.update()['user_request'])]
  with patch.object(server,'checked_project_root',side_effect=AssertionError('Invalid input touched project')):
   for args in invalid:self.assertEqual(self.call('film_cloud',args,error=True)['error']['type'],'ValueError')
   args=self.file_args();args['cloud_update']['unexpected']=True
   self.assertEqual(self.call('film_artifact_save_file',args,error=True)['error']['type'],'ValueError')
 def test_file_save_keeps_compact_queue_receipt_and_is_idempotent(self):
  args=self.file_args();receipt=self.call('film_artifact_save_file',args)
  self.assertIn('cloud_update',receipt);self.assertNotIn('甲推开门',json.dumps(receipt,ensure_ascii=False))
  self.assertEqual(receipt,self.call('film_artifact_save_file',args))
  state=self.call('film_cloud',self.cloud('read'));self.assertEqual(len(state['jobs']),1)
  self.assertEqual(state['jobs'][0]['artifact']['version'],1)
  summary=self.call('film_context',{'root':str(self.root),'mode':'summary',**self.payload()})
  self.assertIn('cloud',summary);self.assertNotIn('甲推开门',json.dumps(summary,ensure_ascii=False))
 def test_local_only_keeps_candidate_without_cloud_job(self):
  args=self.file_args();args['cloud_update']=self.update('local_only')
  receipt=self.call('film_artifact_save_file',args);self.assertEqual(receipt['artifact']['version'],1)
  self.assertEqual(self.call('film_cloud',self.cloud('read'))['jobs'],[])
 def test_checkpoint_has_no_cloud_side_effect_submit_retains_trigger(self):
  self.call('film_task_create',{'root':str(self.root),**self.payload(op_id='task',task_id='TEST-TASK',artifact_id='TEST-NOVEL',title='TEST novel',module='story',scope='chapter/1',inputs=[],must_keep=[],allowed_changes=['TEST candidate'],requirements=['full draft'])})
  saved=self.call('film_draft_save',{'root':str(self.root),**self.payload(op_id='draft',task_id='TEST-TASK',draft='TEST 完整正文：甲开门，乙让路。',completed=['full draft'],decisions=[],unresolved=[],next_step='submit')})
  self.assertEqual(self.call('film_cloud',self.cloud('read'))['jobs'],[])
  c=saved['checkpoint']
  receipt=self.call('film_draft_submit',{'root':str(self.root),**self.payload(op_id='submit',task_id='TEST-TASK',artifact_id='TEST-NOVEL',kind='novel',base_version=0,checkpoint_id=c['checkpoint_id'],expected_draft_sha256=c['draft_sha256'],cloud_update=self.update())})
  self.assertIn('cloud_update',receipt)
  state=self.call('film_cloud',self.cloud('read'));self.assertEqual(len(state['jobs']),1)
  self.assertEqual(state['jobs'][0]['artifact']['artifact_id'],'TEST-NOVEL')
 def test_wrong_identity_does_not_change_existing_queue(self):
  self.call('film_artifact_save_file',self.file_args());before=self.db.read_bytes()
  args=self.cloud('read');args['payload']['expected_project_id']='TEST-WRONG'
  self.call('film_cloud',args,error=True);self.assertEqual(self.db.read_bytes(),before)
 def test_cloud_markdown_format_is_preserved_as_new_exact_candidate_without_second_write(self):
  original='# TEST\n\n- 一\n- 二\n\n```text\ncode\n```'
  observed=original.replace('- 一\n- 二','- 一\n\n- 二')
  saved=self.dispatch('artifact.save',op_id='fmt-save',artifact_id='TEST-FMT',kind='outline',scope='project',content=original,base_version=0,cloud_update=self.update())
  job=saved['cloud_update'];revision=job['revision']
  def record(event,extra):
   nonlocal revision
   result=self.call('film_cloud',self.cloud('record',op_id='fmt-'+event+'-'+str(revision),base_revision=revision,job_id=job['job_id'],event=event,observation={'request_id':job['request_id'],**extra}))
   revision=result['revision'];return result
  def reading():return {'source':'host_tool','tool':'read_page','observed_at':datetime.now(timezone.utc).isoformat(),'page_id':'TEST-PAGE-FMT','page_url':'https://example.invalid/TEST-FMT','content':observed,'whole_page_complete':True,'revision':1}
  record('request_started',{})
  record('page_created',{'source':'host_tool','tool':'create_page','observed_at':datetime.now(timezone.utc).isoformat(),'page_id':'TEST-PAGE-FMT','page_url':'https://example.invalid/TEST-FMT'})
  conflict=record('verified',reading());self.assertEqual(conflict['job']['status'],'conflict')
  update=self.update();update['base_observation_id']=conflict['document']['last_observation_id']
  saved=self.dispatch('artifact.save',op_id='fmt-align',artifact_id='TEST-FMT',kind='outline',scope='project',content=observed,base_version=1,metadata={'cloud_format_source':{'artifact_id':'TEST-FMT','version':1}},cloud_update=update)
  job=saved['cloud_update'];revision=job['revision'];self.assertEqual(job['page_id'],'TEST-PAGE-FMT')
  checked=record('preflight',reading());self.assertEqual(checked['job']['status'],'synced');self.assertEqual(checked['document']['last_synced_ref']['version'],2)
  old=self.call('film_context',{'root':str(self.root),'mode':'artifact',**self.payload(artifact_id='TEST-FMT',version=1)})
  self.assertIn(original,json.dumps(old,ensure_ascii=False).replace('\\n','\n'))

if __name__=='__main__':unittest.main()

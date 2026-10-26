import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from filmprod.core import Registry


class PresentationStdioTests(unittest.TestCase):
    def test_real_protocol_management_and_exact_history_preserved(self):
        with tempfile.TemporaryDirectory(prefix='film-board173-TEST-') as temp:
            root=Path(temp)/'TEST-PROJECT'
            r=Registry(root)
            r.dispatch('project.init',{'op_id':'init','project_id':'TEST-BOARD173','title':'Synthetic board','test_only':True})
            item=r.dispatch('artifact.save',{'op_id':'draft','artifact_id':'D','kind':'director','scope':'episode/01/ref','base_version':0,'content':'# 原文\r\n不会因归档改变。','deps':[],'metadata':{'title':'reading'}})['artifact']
            r.close()
            payload={'op_id':'archive','expected_project_id':'TEST-BOARD173','artifact_id':'D','version':1,'expected_sha256':item['sha256'],'base_revision':0,'display_category':'video_prompt','title':'旧画面稿','archived':True}
            calls=[('film_dispatch',{'action':'presentation.set','payload':payload}),
                   ('film_dispatch',{'action':'presentation.set','payload':payload}),
                   ('film_snapshot',{}),('film_history',{'artifact_id':'D'}),
                   ('film_dispatch',{'action':'presentation.set','payload':{**payload,'op_id':'wrong-project','expected_project_id':'OTHER'}})]
            messages=[{'jsonrpc':'2.0','id':i+1,'method':'tools/call','params':{'name':name,'arguments':{'root':str(root),**args}}} for i,(name,args) in enumerate(calls)]
            env={**os.environ,'FILMPROD_CATALOG_PATH':str(Path(temp)/'catalog.sqlite3'),'PYTHONDONTWRITEBYTECODE':'1'}
            proc=subprocess.run([sys.executable,'-B','-X','utf8',str(Path(__file__).resolve().parents[1]/'plugin/mcp_server.py')],input=''.join(json.dumps(m,ensure_ascii=False)+'\n' for m in messages),capture_output=True,text=True,encoding='utf-8',env=env,timeout=30)
            self.assertEqual(proc.returncode,0,proc.stderr)
            rows=[json.loads(line)['result'] for line in proc.stdout.splitlines()]
            self.assertTrue(all(not row.get('isError') for row in rows[:4]),rows)
            self.assertEqual(rows[0]['structuredContent'],rows[1]['structuredContent'])
            snapshot=rows[2]['structuredContent']
            self.assertEqual(snapshot['presentation']['entries'][0]['revision'],1)
            self.assertEqual(snapshot['artifacts'],[item])
            self.assertEqual(snapshot['masters'],[])
            self.assertEqual(snapshot['decisions'],[])
            self.assertEqual(rows[3]['structuredContent']['versions'],[item])
            self.assertTrue(rows[4]['isError'])


if __name__=='__main__': unittest.main()

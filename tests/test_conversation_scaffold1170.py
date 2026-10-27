"""Derived navigation includes hierarchy without copying authorizations/prompts."""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('scaffold1170', SOURCE/'skills/film-production-agent/scripts/scaffold_project.py')
scaffold = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scaffold)


class ConversationScaffoldTests(unittest.TestCase):
    def test_read_only_hierarchy_index_and_unchanged_repeat(self):
        with tempfile.TemporaryDirectory(prefix='film-conversation-scaffold-TEST-') as temporary:
            root=Path(temporary);(root/'.project').mkdir()
            dbpath=root/'.project/registry.sqlite3'
            state={'revision':4,'enabled':True,'parents':{'planning':{'thread_id':'TEST-PARENT','title':'合成灵感总控','client_project_id':'TEST-CLIENT'}},
                'authorization':{'quote':'PRIVATE-AUTH-TEST'},'topics':[{'topic_id':'IDEA-TEST','kind':'idea','title':'合成想法','scope':'idea/test',
                'parent_role':'planning','parent_thread_id':'TEST-PARENT','thread_id':'TEST-CHILD','status':'active','brief':'PRIVATE-PROMPT-TEST'}],
                'handoffs':[],'outbox':[{'request_id':'TEST-REQUEST','topic_id':'IDEA-TEST','tool':'send_message_to_thread','status':'unknown',
                'purpose':'handoff','target_thread_id':'TEST-PARENT','authorization':{'quote':'PRIVATE-AUTH-TEST'},'payload':{'text':'PRIVATE-PROMPT-TEST'}}]}
            with sqlite3.connect(dbpath) as db:
                db.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
                db.executemany('INSERT INTO settings VALUES(?,?)',[(k,json.dumps(v,ensure_ascii=False)) for k,v in {
                    'schema_version':2,'project':{'project_id':'TEST-SCAFFOLD','title':'合成项目','workflow':{'mode':'screenplay'}},
                    'workspace/v1':{'revision':1,'prepared':True,'slots':[]},'conversation/v1':state}.items()])
            db.close()
            original=dbpath.read_bytes()
            scaffold.scaffold(str(root),'TEST-SCAFFOLD')
            index=root/'09-任务与接续/工作对话/对话索引.json'
            data=json.loads(index.read_text(encoding='utf-8'))
            self.assertEqual(data['conversations']['topics'][0]['chat_url'],'codex://threads/TEST-CHILD')
            self.assertEqual(data['conversations']['pending_host_actions'][0]['status'],'unknown')
            self.assertNotIn('PRIVATE-',index.read_text(encoding='utf-8'))
            self.assertEqual(original,dbpath.read_bytes())
            first=index.read_bytes();scaffold.scaffold(str(root),'TEST-SCAFFOLD')
            self.assertEqual(first,index.read_bytes())
            self.assertEqual(original,dbpath.read_bytes())


if __name__=='__main__':unittest.main()

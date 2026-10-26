import tempfile
import unittest
from pathlib import Path
from filmprod.core import Registry
from filmprod.export import export_project


class ApprovedExportTests(unittest.TestCase):
    def test_chapter_index_orders_numeric_scopes_and_keeps_source_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=Registry(tmp)
            r.dispatch('project.init',dict(op_id='i',project_id='TEST-LONG-EXPORT',title='TEST',test_only=True))
            content='# 明确标题\n\nTEST 长文原样保留。\n'
            for n,location in ((10,'第十章'),(2,{'id':'C2','title':'第二章','order':2})):
                r.dispatch('artifact.save',dict(op_id=f'n{n}',artifact_id=f'N{n}',kind='novel',scope=f'chapter/{n}',content=content,base_version=0,deps=[],metadata={'chapter':location,'title':f'TEST N{n}'}))
            export_project(r)
            entry=(Path(tmp)/'项目入口.md').read_text(encoding='utf-8')
            index=entry.split('## 章节与分集阅读目录',1)[1]
            self.assertLess(index.index('第二章'),index.index('第十章'))
            self.assertEqual(r.dispatch('artifact.get',{'artifact_id':'N2','version':1})['content'],content)
            self.assertFalse(r.snapshot()['decisions'])
            self.assertIn('未分章正文不会被自动拆成新的批准范围',entry)
            r.close()

    def test_reading_entry_preserves_approved_and_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=Registry(tmp)
            r.dispatch('project.init',dict(op_id='i',project_id='TEST-EXPORT',title='TEST',test_only=True))
            r.dispatch('artifact.save',dict(op_id='s1',artifact_id='S01',kind='script',scope='S01',content='TEST 已通过正文',base_version=0,deps=[]))
            r.dispatch('content.approve',dict(op_id='a1',artifact_id='S01',version=1,scope='S01',evidence='synthetic test',actor='test-runner',synthetic=True))
            r.dispatch('artifact.save',dict(op_id='s2',artifact_id='S01',kind='script',scope='S01',content='TEST 尚待审核修改',base_version=1,deps=[]))
            export_project(r)
            entry=(Path(tmp)/'项目入口.md').read_text(encoding='utf-8')
            self.assertIn('| S01 | 1 | 已通过 |',entry)
            self.assertIn('待审核修改',entry)
            self.assertIn('S01 v2',entry)
            masters=list((Path(tmp)/'已通过总稿').rglob('*.md'))
            self.assertEqual(len(masters),1)
            self.assertIn('TEST 已通过正文',masters[0].read_text(encoding='utf-8'))
            self.assertNotIn('尚待审核',masters[0].read_text(encoding='utf-8'))
            export_project(r)
            r.close()


if __name__=='__main__': unittest.main()

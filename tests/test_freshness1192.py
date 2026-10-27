import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from filmprod.core import Registry
from filmprod.projects import ProjectCatalog, project_identity
from filmprod.freshness1192 import freshness
from filmprod.board_gateway1150 import call_board


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / 'TEST'
        self.env = patch.dict(os.environ, {'FILMPROD_CATALOG_PATH': str(self.base/'catalog.sqlite3')})
        self.env.start()
        self.r = Registry(self.root)
        self.r.dispatch('project.init', {'op_id':'init','project_id':'TEST','title':'TEST','test_only':True})
        self.catalog = ProjectCatalog()
        self.catalog.dispatch('register', {'op_id':'register','root':str(self.root)})

    def tearDown(self):
        self.catalog.close()
        self.r.close()
        self.env.stop()
        self.tmp.cleanup()

    def checked(self, root, payload):
        actual=project_identity(root)
        if payload.get('expected_project_id') and actual['project_id']!=payload['expected_project_id']:
            raise ValueError('identity mismatch')
        return Path(root)

    def call(self, action, **payload):
        return call_board({'action':action,'root':str(self.root),'payload':{'expected_project_id':'TEST',**payload}}, None, self.checked)['structuredContent']

    def test_poll_is_small_read_only_and_detects_external_wal_commit(self):
        before=self.call('board.poll')
        self.assertEqual(before,self.call('board.poll'))
        self.assertLess(len(json.dumps(before)),200)
        with sqlite3.connect(self.root/'.project/registry.sqlite3') as external:
            project=project_identity(self.root);project.pop('root');project['title']='TEST changed elsewhere'
            external.execute("UPDATE settings SET value=? WHERE key='project'",(json.dumps(project),))
        external.close()
        after=self.call('board.poll')
        self.assertNotEqual(before['freshness_token'],after['freshness_token'])
        snap=self.call('snapshot')
        self.assertEqual(snap['project']['title'],'TEST changed elsewhere')
        self.assertEqual(snap['freshness_token'],self.call('board.poll')['freshness_token'])

    def test_catalog_add_archive_remove_each_invalidates(self):
        initial=freshness(self.root)
        other=Registry(self.base/'TEST-B')
        try:
            other.dispatch('project.init',{'op_id':'init','project_id':'TEST-B','title':'TEST B','test_only':True})
            self.catalog.dispatch('register',{'op_id':'reg-b','root':str(other.root)})
            added=freshness(self.root);self.assertNotEqual(initial,added)
            self.catalog.dispatch('visibility',{'op_id':'archive-b','project_id':'TEST-B','expected_root':str(other.root),'base_revision':0,'status':'archived'})
            archived=freshness(self.root);self.assertNotEqual(added,archived)
            self.catalog.dispatch('forget',{'op_id':'forget-b','project_id':'TEST-B','expected_root':str(other.root)})
            self.assertNotEqual(archived,freshness(self.root))
        finally:other.close()

    def test_poll_rejects_wrong_identity_and_write_payload(self):
        with self.assertRaises(ValueError):self.call('board.poll',expected_project_id='OTHER')
        with self.assertRaises(ValueError):self.call('board.poll',op_id='unexpected')

    def test_no_catalog_or_project_is_created_by_empty_poll(self):
        missing=self.base/'absent'/'catalog.sqlite3'
        with patch.dict(os.environ,{'FILMPROD_CATALOG_PATH':str(missing)}):
            self.assertIn('freshness_token',freshness())
            self.assertFalse(missing.parent.exists())

if __name__=='__main__':unittest.main()

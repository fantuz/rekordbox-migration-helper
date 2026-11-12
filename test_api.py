import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import app as application


class ExportProtectionTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        metadata={"name":"Unicode 日本 library","version":"6.7.7"}
        self.session={"id":"a"*32,"name":metadata['name'],"metadata":metadata,"catalog":SimpleNamespace(metadata=metadata,counts={}),
                      "decisions":{},"relocations":{},"events":[],"policy":"newest","backup_acknowledged":None}
        for name,value in (("DATA",self.root),("sessions",{self.session['id']:self.session}),("active",self.session['id'])):
            patcher=patch.object(application,name,value);patcher.start();self.addCleanup(patcher.stop)
        self.client=application.app.test_client()
        self.headers={'X-Workbench-Token':application.TOKEN}

    def test_transform_export_requires_backup_acknowledgement(self):
        response=self.client.post('/api/export',json={'format':'pair'},headers=self.headers)
        self.assertEqual(response.status_code,400)
        self.assertIn('untouched',response.json['error'])
        self.assertFalse((self.root/'exports').exists())

    def test_backup_acknowledgement_persists_per_workspace_with_unicode(self):
        response=self.client.post('/api/backup/acknowledge',json={'confirmed':True},headers=self.headers)
        self.assertEqual(response.status_code,200)
        state=json.loads((self.root/self.session['id']/'state.json').read_text(encoding='utf-8'))
        self.assertTrue(state['backup_acknowledged'])
        self.assertEqual(state['name'],'Unicode 日本 library')
        response=self.client.post('/api/backup/acknowledge',json={'confirmed':False},headers=self.headers)
        self.assertIsNone(response.json['session']['backup_acknowledged'])

    def test_older_version_is_not_silently_allowed_to_create_native_backups(self):
        self.session['backup_acknowledged']='test acknowledgement'
        response=self.client.post('/api/export',json={'format':'zip'},headers=self.headers)
        self.assertEqual(response.status_code,400)
        self.assertIn('v7 inputs only',response.json['error'])

    def test_backup_acknowledgement_requires_local_action_token(self):
        response=self.client.post('/api/backup/acknowledge',json={'confirmed':True})
        self.assertEqual(response.status_code,403)
        self.assertIsNone(self.session['backup_acknowledged'])


if __name__=='__main__':unittest.main()

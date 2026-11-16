"""Regression tests deliberately use raw clients, without automatic scope headers."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import io
import errno
import unittest

import app as application
from temporary_files import TemporaryWorkspace
from upload_recovery import receive, slot
from workspace_safety import revision
from werkzeug.exceptions import ClientDisconnected, Conflict


class WorkspaceSafetyTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        def state(identity):
            return {'id':identity,'name':identity,'metadata':{'name':identity,'version':'7.2.0'},
                    'catalog':SimpleNamespace(counts={},tracks={'1':{'title':'Shared ID'}}),
                    'decisions':{'pair':{'action':'skip'}},'relocations':{},'events':[],
                    'policy':'newest','last_batch':['pair'],'batches':[],'backup_acknowledged':None}
        self.a=state('a'*32);self.b=state('b'*32)
        for name,value in [('DATA',self.root),('sessions',{self.a['id']:self.a,self.b['id']:self.b}),('active',self.a['id'])]:
            p=patch.object(application,name,value);p.start();self.addCleanup(p.stop)
        self.client=application.app.test_client()
        self.headers={'X-Workbench-Token':application.TOKEN,'X-Workbench-Workspace':self.a['id'],
                      'X-Workbench-Revision':revision(self.a)}

    def test_stale_tab_cannot_undo_relocate_acknowledge_or_export_another_workspace(self):
        application.active=self.b['id']
        for path,body in [('/api/bulk/undo',{}),('/api/relocation',{'track_id':'1','uri':'file://localhost/D:/other.mp3'}),
                          ('/api/backup/acknowledge',{'confirmed':True}),('/api/export',{'format':'xml'}),
                          ('/api/session/name',{'name':'Wrong name'})]:
            with self.subTest(path=path):
                before=(deepcopy(self.a['decisions']),deepcopy(self.b['decisions']))
                response=self.client.post(path,json=body,headers=self.headers)
                self.assertEqual(response.status_code,409,response.json)
                self.assertEqual(before,(self.a['decisions'],self.b['decisions']))
        self.assertFalse(self.a['relocations']);self.assertFalse(self.b['relocations'])
        self.assertIsNone(self.b['backup_acknowledged'])
        self.assertEqual(self.b['name'],self.b['id'])

    def test_missing_scope_is_rejected_and_two_writes_need_updated_revision(self):
        response=self.client.post('/api/backup/acknowledge',json={'confirmed':True},
                                  headers={'X-Workbench-Token':application.TOKEN})
        self.assertEqual(response.status_code,409)
        response=self.client.post('/api/backup/acknowledge',json={'confirmed':True},headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)
        self.assertNotEqual(response.json['session']['revision'],self.headers['X-Workbench-Revision'])
        again=self.client.post('/api/backup/acknowledge',json={'confirmed':False},headers=self.headers)
        self.assertEqual(again.status_code,409)
        self.assertTrue(self.a['backup_acknowledged'])
        fresh={**self.headers,'X-Workbench-Revision':response.json['session']['revision']}
        self.assertEqual(self.client.post('/api/backup/acknowledge',json={'confirmed':False},headers=fresh).status_code,200)
        self.assertIsNone(self.a['backup_acknowledged'])

    def test_stale_reads_are_rejected_and_error_does_not_leave_lock_held(self):
        application.active=self.b['id']
        response=self.client.get('/api/inventory',headers=self.headers)
        self.assertEqual(response.status_code,409)
        application.active=self.a['id']
        self.assertEqual(self.client.post('/api/backup/acknowledge',json={'confirmed':True},headers=self.headers).status_code,200)


class UploadRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.runtime=TemporaryWorkspace(self.root);self.addCleanup(self.runtime.best_effort_cleanup)
        p=patch.object(application,'TEMPORARY',self.runtime);p.start();self.addCleanup(p.stop)
        self.client=application.app.test_client();self.headers={'X-Workbench-Token':application.TOKEN}
        self.sid=self.client.post('/api/import',json={'zip':'synthetic.zip','xml':'synthetic.xml'},headers=self.headers).json['session']
        self.folder=self.runtime.folder(self.sid)

    def upload(self,data=b'replacement'):
        return self.client.put('/api/upload/'+self.sid+'/zip',data=data,headers=self.headers)

    def test_disconnect_removes_partial_and_same_session_can_retry(self):
        class Broken(io.BytesIO):
            calls=0
            def readinto(self,buffer):
                self.calls+=1
                if self.calls>1:raise ClientDisconnected()
                data=self.read(min(4,len(buffer)));buffer[:len(data)]=data;return len(data)
        response=self.client.put('/api/upload/'+self.sid+'/zip',headers=self.headers,
            environ_overrides={'wsgi.input':Broken(b'123456789'),'CONTENT_LENGTH':'9'})
        self.assertEqual(response.status_code,400)
        self.assertIsInstance(response.json['error'],str)
        self.assertFalse((self.folder/'zip.part').exists())
        self.assertEqual(self.upload().status_code,200)
        self.assertEqual((self.folder/'synthetic.zip').read_bytes(),b'replacement')

    def test_disk_full_permission_and_publish_failure_keep_retry_available(self):
        for code in (errno.ENOSPC,errno.EACCES,errno.EIO):
            with self.subTest(code=code),patch('upload_recovery.os.replace',side_effect=OSError(code,'synthetic storage error')):
                response=self.upload()
                self.assertEqual(response.status_code,400,response.json)
                self.assertFalse((self.folder/'zip.part').exists())
                self.assertFalse((self.folder/'synthetic.zip').exists())
        self.assertEqual(self.upload().status_code,200)

    def test_capacity_cancellation_old_partial_and_concurrent_retry(self):
        with patch('upload_recovery.shutil.disk_usage',return_value=SimpleNamespace(free=0)):
            self.assertEqual(self.upload().status_code,400)
        with self.assertRaisesRegex(ValueError,'cancelled'):
            receive(self.runtime,self.sid,'zip',io.BytesIO(b'data'),4,lambda:True)
        self.assertFalse((self.folder/'zip.part').exists())
        (self.folder/'zip.part').write_bytes(b'abandoned')
        key=(str(self.runtime.path),self.sid,'zip')
        with slot(key):
            self.assertEqual(self.upload().status_code,409)
            self.assertEqual((self.folder/'zip.part').read_bytes(),b'abandoned')
        self.assertEqual(self.upload().status_code,200)
        self.assertFalse((self.folder/'zip.part').exists())

if __name__=='__main__':unittest.main()

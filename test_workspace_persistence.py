"""Failed writes must leave durable and in-memory review state in agreement."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import json
import unittest

import app as application
from workspace_safety import revision


class WorkspacePersistenceTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        metadata={'name':'Original','version':'7.2.0'}
        self.catalog=SimpleNamespace(metadata=metadata,counts={},policy='newest',
            tracks={'1':{'title':'Track','current_path':'D:/Music/Track.wav','original_path':None,'xml_location':None}},
            pairs={'pair':{}},descriptions={'pair':{'title':'Track'}})
        self.session={'id':'a'*32,'name':'Original','catalog':self.catalog,'metadata':metadata,
            'decisions':{'pair':{'action':'skip'}},'relocations':{},'held_pairs':{},'events':[],
            'policy':'newest','last_batch':['pair'],'batches':[],'media_verifications':{},'backup_acknowledged':None}
        for name,value in [('DATA',self.root),('active',self.session['id']),('sessions',{self.session['id']:self.session})]:
            p=patch.object(application,name,value);p.start();self.addCleanup(p.stop)
        p=patch.dict(application.app.config,TESTING=False,PROPAGATE_EXCEPTIONS=False);p.start();self.addCleanup(p.stop)
        self.headers={'X-Workbench-Token':application.TOKEN,'X-Workbench-Workspace':self.session['id'],
                      'X-Workbench-Revision':revision(self.session,self.root)}
        application.persist(self.session)
        self.path=self.root/self.session['id']/'state.json';self.client=application.app.test_client()

    def working(self):return deepcopy({k:v for k,v in self.session.items() if k!='catalog'})

    def test_failed_write_or_replace_restores_mutations_events_revision_and_disk(self):
        actions=[('/api/session/name',{'name':'Failed rename'}),('/api/backup/acknowledge',{'confirmed':True}),
                 ('/api/decision',{'pair':'pair','action':'undo'}),('/api/bulk/undo',{}),
                 ('/api/relocation',{'track_id':'1','uri':'file://localhost/D:/New.wav'}),
                 ('/api/export-target',{'target':'windows'})]
        for fault in ('app.Path.write_text','app.os.replace'):
            for endpoint,body in actions:
                with self.subTest(fault=fault,endpoint=endpoint):
                    before=self.working();disk=self.path.read_bytes();stamp=revision(self.session,self.root)
                    with patch(fault,side_effect=OSError('disk full')):
                        response=self.client.post(endpoint,json=body,headers=self.headers)
                    self.assertEqual(response.status_code,500)
                    self.assertEqual(self.working(),before);self.assertEqual(self.path.read_bytes(),disk)
                    self.assertEqual(revision(self.session,self.root),stamp)
                    self.assertFalse(self.path.with_suffix('.tmp').exists())
        saved=self.client.post('/api/session/name',json={'name':'Successful'},headers=self.headers)
        self.assertEqual(saved.status_code,200,saved.json)
        durable=json.loads(self.path.read_text())
        self.assertEqual(durable['name'],'Successful');self.assertEqual(durable['decisions'],{'pair':{'action':'skip'}})
        self.assertEqual(durable['relocations'],{});self.assertIsNone(durable['backup_acknowledged'])
        self.assertEqual(len(durable['events']),1)

    def test_failed_background_policy_save_restores_derived_suggestions(self):
        def refresh():
            self.catalog.counts={'changed':1};self.catalog.descriptions={'changed':{}}
        self.catalog.refresh_counts=refresh
        before=self.working();counts=self.catalog.counts;descriptions=self.catalog.descriptions
        with patch.object(application,'launch',side_effect=lambda work,*_args,**_kwargs:work(lambda *_:None)),patch.object(application,'persist',side_effect=OSError('disk full')):
            response=self.client.post('/api/policy',json={'policy':'last_played'},headers=self.headers)
        self.assertEqual(response.status_code,500);self.assertEqual(self.working(),before)
        self.assertEqual(self.catalog.policy,'newest');self.assertIs(self.catalog.counts,counts)
        self.assertIs(self.catalog.descriptions,descriptions)

    def test_failed_inventory_save_does_not_replace_previous_inventory_file(self):
        previous=self.path.parent/'inventory.json';previous.write_text('{"old":true}')
        self.session.update(inventory={'scan_id':'old'},inventory_path=str(previous))
        application.persist(self.session);self.headers['X-Workbench-Revision']=revision(self.session,self.root)
        before=self.working();disk=self.path.read_bytes()
        result={'file_count':1,'counts':{},'warnings':[]}
        with patch.object(application,'scan_media',return_value=result),patch.object(application,'launch',side_effect=lambda work,*_args,**_kwargs:work(lambda *_:None)),patch.object(application,'persist',side_effect=OSError('disk full')):
            response=self.client.post('/api/inventory/scan',json={'workspace':self.session['id'],'roots':[]},headers=self.headers)
        self.assertEqual(response.status_code,500);self.assertEqual(self.working(),before)
        self.assertEqual(self.path.read_bytes(),disk);self.assertEqual(previous.read_text(),'{"old":true}')
        self.assertFalse(list(self.path.parent.glob('inventory-*.json')))

    def test_response_failure_after_commit_keeps_memory_and_disk_in_agreement(self):
        with patch.object(application,'summary',side_effect=RuntimeError('render failed')):
            response=self.client.post('/api/session/name',json={'name':'Committed'},headers=self.headers)
        self.assertEqual(response.status_code,500)
        self.assertEqual(self.session['name'],'Committed')
        self.assertEqual(json.loads(self.path.read_text())['name'],'Committed')

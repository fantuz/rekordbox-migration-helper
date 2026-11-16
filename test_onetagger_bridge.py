"""Local selection identity, retained errors and explicit atomic tag staging."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import unquote
import json
import struct
import wave

import app
from audio_paths import validate
from onetagger_bridge import read_tags
from workbench_store import Store


class OneTaggerBridgeTests(TestCase):
    def setUp(self):
        tmp=TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.audio=self.root/'100%20 Café.wav'
        with wave.open(str(self.audio),'wb') as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(8000);out.writeframes(struct.pack('<h',0)*800)
        self.track={'id':'one','title':'Original','artist':'DJ','album':'Library album','genre':'House','year':2000,'rating':5,
                    'current_path':'D:/Music/'+self.audio.name,'xml_location':'file://localhost/D:/Music/a.wav'}
        self.store=Store(self.root/'workbench-sidecar.sqlite3')
        self.sid=self.store.save_snapshot({'scope_key':'capture:'+'a'*32,'tracks':[self.track]},'Bridge fixture')['id']
        self.maps=validate([{'recorded_root':'D:/Music','local_root':str(self.root)}],[self.root])
        self.store.set_setting('audio_paths:'+'capture:'+'a'*32,self.maps)
        self.before=deepcopy(self.store.snapshot(self.sid));self.bytes=self.audio.read_bytes()
        for name,value in [('DATA',self.root),('tasks',{})]:
            p=patch.object(app,name,value);p.start();self.addCleanup(p.stop)
        self.client=app.app.test_client();self.headers={'X-Workbench-Token':app.TOKEN}

    def export(self):
        response=self.client.post('/api/onetagger/export',json={'snapshot':self.sid,'track_ids':['one']},headers=self.headers)
        self.assertEqual(response.status_code,200,response.json);return response.json['id']

    def scan(self,identity,tags=None):
        values=tags or {'title':'Tagged title','genre':'Techno','year':2020}
        def launch(work,*_,**kwargs):work(lambda *_:None);return 'job'
        with patch.object(app,'launch',side_effect=launch),patch('onetagger_bridge.read_tags',return_value=(values,[1,2,3,4,5],[])):
            response=self.client.post('/api/onetagger/'+identity+'/rescan',json={},headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)
        return self.client.get('/api/onetagger/'+identity+'/review').json['scan']

    def stage(self,identity,scan,**kwargs):
        self.client.post('/api/lab/unlock',json={'snapshot':self.sid,'unlocked':True},headers=self.headers)
        body={'reviewed':True,'review_revision':scan['review_revision'],'edit_revision':scan['edit_revision'],
              'changes':[{'track_id':'one','field':'genre'}],**kwargs}
        with patch('onetagger_bridge.read_tags',return_value=(scan['rows'][0].get('tags'),scan['rows'][0].get('file_stamp'),[])):
            return self.client.post('/api/onetagger/'+identity+'/stage',json=body,headers=self.headers)

    def test_real_audio_tag_reader_and_manifest_keep_original_references(self):
        self.assertEqual(read_tags(self.audio)[0],{})
        identity=self.export();base='/api/onetagger/'+identity
        manifest=json.loads(self.client.get(base+'/manifest').data)
        self.assertEqual(manifest['tracks'][0]['track_id'],'one')
        self.assertEqual(manifest['tracks'][0]['recorded_references']['current_path'],self.track['current_path'])
        self.assertEqual(manifest['tracks'][0]['local_path'],str(self.audio.resolve()))
        playlist=self.client.get(base+'/playlist').data.decode().splitlines()
        self.assertEqual(unquote(playlist[1]),str(self.audio.resolve()))
        self.assertIn('%2520',playlist[1])
        self.assertEqual(self.audio.read_bytes(),self.bytes);self.assertEqual(self.store.snapshot(self.sid),self.before)

    def test_selection_requires_local_token_and_membership(self):
        body={'snapshot':self.sid,'track_ids':['one']}
        self.assertEqual(self.client.post('/api/onetagger/export',json=body).status_code,403)
        for ids in ([],['other'],['one','one'],['one']*501):
            self.assertEqual(self.client.post('/api/onetagger/export',json={**body,'track_ids':ids},headers=self.headers).status_code,400)
        self.assertEqual(self.client.post('/api/onetagger/export',json=body,headers=self.headers,environ_overrides={'REMOTE_ADDR':'192.0.2.1'}).status_code,400)

    def test_only_reviewed_field_is_staged_with_provenance_and_stars_unchanged(self):
        identity=self.export();scan=self.scan(identity)
        self.assertEqual(self.store.overrides(self.before['scope_key']),{})
        self.assertEqual(self.stage(identity,scan,reviewed=False).status_code,400)
        result=self.stage(identity,scan);self.assertEqual(result.status_code,200,result.json)
        edits=self.store.overrides(self.before['scope_key'])['one']
        self.assertEqual(set(edits),{'genre'});self.assertEqual(edits['genre']['value'],'Techno')
        self.assertEqual(json.loads(edits['genre']['origin'])['selection_id'],identity)
        self.assertEqual(self.store.snapshot(self.sid)['tracks'][0]['rating'],5)
        self.assertEqual(self.audio.read_bytes(),self.bytes)
        self.assertEqual(self.stage(identity,scan).status_code,409)

    def test_stale_scan_changed_mappings_and_changed_tags_block_staging(self):
        identity=self.export();scan=self.scan(identity)
        self.assertEqual(self.stage(identity,scan,review_revision='stale').status_code,409)
        self.client.post('/api/lab/unlock',json={'snapshot':self.sid,'unlocked':True},headers=self.headers)
        body={'reviewed':True,'review_revision':scan['review_revision'],'edit_revision':scan['edit_revision'],'changes':[{'track_id':'one','field':'genre'}]}
        with patch('onetagger_bridge.read_tags',return_value=({'genre':'Later change'},[9],[])):
            result=self.client.post('/api/onetagger/'+identity+'/stage',json=body,headers=self.headers)
        self.assertEqual(result.status_code,409,result.json)
        self.store.set_setting('audio_paths:'+self.before['scope_key'],[])
        self.assertEqual(self.stage(identity,scan).status_code,409)
        self.assertEqual(self.store.overrides(self.before['scope_key']),{})

    def test_unreadable_tags_remain_visible_and_missing_tags_do_not_clear_values(self):
        identity=self.export()
        def launch(work,*_,**kwargs):work(lambda *_:None);return 'job'
        with patch.object(app,'launch',side_effect=launch),patch('onetagger_bridge.read_tags',side_effect=ValueError('Damaged tag block')):
            response=self.client.post('/api/onetagger/'+identity+'/rescan',json={},headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)
        scan=self.client.get('/api/onetagger/'+identity+'/review').json['scan']
        self.assertEqual(scan['rows'][0]['error'],'Damaged tag block');self.assertEqual(scan['rows'][0]['changes'],[])
        self.assertEqual(self.store.overrides(self.before['scope_key']),{})

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
from onetagger_bridge import read_tags,stamp,FIELDS
from workbench_store import Store


class OneTaggerBridgeTests(TestCase):
    def test_shared_rust_report_fixture_is_supported(self):
        from onetagger_results import validate_report
        report=json.loads((Path(__file__).parent/'docs/fixtures/onetagger-results-v1.json').read_text(encoding='utf-8'))
        manifest={**report['selection'],'tracks':[{'track_id':r['track_id'],'local_path':r['local_path']} for r in report['tracks']]}
        parsed=validate_report(report,manifest)
        self.assertEqual(parsed['rows']['library-1']['after']['title'],'Tagged Café')
        self.assertEqual(parsed['rows']['library-1']['attempts'][0]['track_id'],'provider-42')

    def results_report(self,identity,values=None):
        manifest=self.store.setting('onetagger:'+identity)
        values=values if values is not None else {'title':'Tagged title','genre':'Techno','year':2020}
        state=stamp(self.audio)
        return {'schema':'onetagger.tagging-results','version':1,'run_id':'d'*32,
                'application_version':'1.7.2','application_commit':'synthetic','created_at':'2026-11-17T12:00:00Z',
                'completed_at':'2026-11-17T12:01:00Z','cancelled':False,
                'selection':{k:manifest[k] for k in ('id','snapshot','snapshot_digest','scope_key','mapping_revision')},
                'tracks':[{'track_id':'one','local_path':str(self.audio.resolve()),'final_path':str(self.audio.resolve()),
                    'status':'written','before':{f:self.track.get(f) for f in FIELDS},'after':{f:values.get(f) for f in FIELDS},
                    'before_error':None,'after_error':None,'file_state':{'size':state[2],'modified_ns':str(state[3])},
                    'attempts':[{'provider':'fixture','track_id':'provider-42','release_id':'album-1','status':'written',
                                 'score':.91,'reason':'fuzzy','used_shazam':False}]}]}

    def import_report(self,identity,report,values=None,real=False):
        def launch(work,*_,**kwargs):work(lambda *_:None);return 'job'
        with patch.object(app,'launch',side_effect=launch):
            if real:return self.client.post('/api/onetagger/'+identity+'/import-results',json={'report':report},headers=self.headers)
            with patch('onetagger_bridge.read_tags',return_value=(values or {'title':'Tagged title','genre':'Techno','year':2020},stamp(self.audio),[])):
                return self.client.post('/api/onetagger/'+identity+'/import-results',json={'report':report},headers=self.headers)

    def test_report_import_only_prepares_review_and_retains_match_provenance(self):
        identity=self.export();report=self.results_report(identity)
        result=self.import_report(identity,report);self.assertEqual(result.status_code,200,result.json)
        scan=self.client.get('/api/onetagger/'+identity+'/review').json['scan']
        self.assertEqual(scan['report']['run_id'],report['run_id'])
        self.assertEqual(scan['rows'][0]['report']['attempts'][0]['track_id'],'provider-42')
        self.assertEqual(self.store.overrides(self.before['scope_key']),{})
        self.assertEqual(self.stage(identity,scan).status_code,200)
        edits=self.store.overrides(self.before['scope_key'])['one'];self.assertEqual(set(edits),{'genre'})
        origin=json.loads(edits['genre']['origin']);self.assertEqual(origin['report']['run_id'],report['run_id'])
        self.assertEqual(self.store.snapshot(self.sid),self.before);self.assertEqual(self.audio.read_bytes(),self.bytes)

    def test_rejects_malformed_foreign_duplicate_and_moved_results_before_reading_files(self):
        identity=self.export();valid=self.results_report(identity)
        bad=[]
        for version in (2,True,'1'):
            value=deepcopy(valid);value['version']=version;bad.append(value)
        for key in valid['selection']:
            value=deepcopy(valid);value['selection'][key]='foreign';bad.append(value)
        for key in ('local_path','final_path','track_id'):
            value=deepcopy(valid);value['tracks'][0][key]='other';bad.append(value)
        value=deepcopy(valid);value['tracks']*=2;bad.append(value)
        value=deepcopy(valid);value['tracks'][0]['attempts'][0]['score']=float('inf');bad.append(value)
        value=deepcopy(valid);value['tracks'][0]['attempts'][0]['status']=[];bad.append(value)
        value=deepcopy(valid);value['tracks'][0]['after']['rating']=5;bad.append(value)
        with patch('onetagger_bridge.read_tags',side_effect=AssertionError('Invalid report must not open audio')):
            for value in bad:
                response=self.client.post('/api/onetagger/'+identity+'/import-results',json={'report':value},headers=self.headers)
                self.assertEqual(response.status_code,400,response.json)
        self.assertEqual(self.store.overrides(self.before['scope_key']),{})

    def test_stale_report_and_tag_disagreement_remain_ineligible_evidence(self):
        identity=self.export();valid=self.results_report(identity)
        bad=deepcopy(valid);bad['tracks'][0]['file_state']['size']+=1
        for report,values in ((bad,None),(valid,{'title':'Changed later'})):
            response=self.import_report(identity,report,values);self.assertEqual(response.status_code,200,response.json)
            scan=self.client.get('/api/onetagger/'+identity+'/review').json['scan']
            self.assertEqual(scan['rows'][0]['status'],'unreadable');self.assertEqual(scan['rows'][0]['changes'],[])
            self.assertEqual(self.stage(identity,scan).status_code,400)

    def test_unsuccessful_and_cancelled_rows_cannot_offer_library_edits(self):
        identity=self.export()
        for state in ('failed','skipped','unprocessed'):
            report=self.results_report(identity);report['cancelled']=True;report['tracks'][0]['status']=state
            report['tracks'][0]['attempts']=[]
            response=self.import_report(identity,report);self.assertEqual(response.status_code,200,response.json)
            scan=self.client.get('/api/onetagger/'+identity+'/review').json['scan']
            self.assertTrue(scan['report']['cancelled']);self.assertEqual(scan['rows'][0]['report']['status'],state)
            self.assertEqual(scan['rows'][0]['changes'],[])

    def test_real_wave_report_import_stages_only_reviewed_field_without_audio_writes(self):
        identity=self.export()
        items=[]
        for key,value in ((b'INAM','Tagged Café'),(b'IGNR','Techno')):
            data=value.encode()+b'\0';items.append(key+struct.pack('<I',len(data))+data+(b'\0' if len(data)%2 else b''))
        info=b'INFO'+b''.join(items);chunk=b'LIST'+struct.pack('<I',len(info))+info
        original=self.audio.read_bytes();self.audio.write_bytes(original[:4]+struct.pack('<I',len(original)-8+len(chunk))+original[8:]+chunk)
        values=read_tags(self.audio)[0];report=self.results_report(identity,values);written=self.audio.read_bytes()
        response=self.import_report(identity,report,real=True);self.assertEqual(response.status_code,200,response.json)
        scan=self.client.get('/api/onetagger/'+identity+'/review').json['scan']
        self.assertEqual(scan['rows'][0]['status'],'read');self.assertEqual(self.stage(identity,scan).status_code,200)
        self.assertEqual(self.audio.read_bytes(),written);self.assertEqual(self.store.snapshot(self.sid),self.before)

    def test_import_requires_local_session_and_bounded_payload(self):
        identity=self.export();report=self.results_report(identity);url='/api/onetagger/'+identity+'/import-results'
        self.assertEqual(self.client.post(url,json={'report':report}).status_code,403)
        self.assertEqual(self.client.post(url,json={'report':report},headers=self.headers,environ_overrides={'REMOTE_ADDR':'192.0.2.1'}).status_code,400)
        with patch('onetagger_bridge.MAX_BYTES',100):
            self.assertEqual(self.client.post(url,json={'report':report},headers=self.headers).status_code,400)

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


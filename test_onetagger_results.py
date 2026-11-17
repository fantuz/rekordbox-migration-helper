"""Producer-shaped reports, real metadata reads and protected review transitions."""
from copy import deepcopy
from hashlib import sha256
import json
import struct
from unittest import TestCase
from unittest.mock import patch

import app
from metadata_export import payload
from onetagger_bridge import read_tags,stamp
from onetagger_results import FIELDS,decode_report,validate_report
from task_control import OperationCancelled
import test_onetagger_bridge as bridge_fixtures
from workbench_store import Store


def syncsafe(value):return bytes((value>>21&127,value>>14&127,value>>7&127,value&127))


def mp3_tags(path,values):
    """Invented ID3v2.4 metadata; no songs, codecs, models or provider requests."""
    frames=[]
    for key,field in (('TIT2','title'),('TPE1','artist'),('TALB','album'),('TCON','genre'),('TDRC','year')):
        if values.get(field) is None:continue
        data=b'\x03'+str(values[field]).encode('utf-8')
        frames.append(key.encode()+syncsafe(len(data))+b'\0\0'+data)
    data=b''.join(frames);path.write_bytes(b'ID3\x04\0\0'+syncsafe(len(data))+data+bytes(64))


def mp4_tags(path,values):
    """ISO metadata atoms exercise repeated MP4 text values without real audio."""
    def box(tag,body):return struct.pack('>I',len(body)+8)+tag+body
    fields=[]
    for key,field in ((b'\xa9nam','title'),(b'\xa9ART','artist'),(b'\xa9alb','album'),(b'\xa9gen','genre'),(b'\xa9day','year')):
        raw=values.get(field)
        if raw is None:continue
        items=raw if isinstance(raw,list) else [raw]
        fields.append(box(key,b''.join(box(b'data',struct.pack('>II',1,0)+str(item).encode()) for item in items)))
    path.write_bytes(box(b'ftyp',b'M4A '+bytes(4))+box(b'moov',box(b'udta',box(b'meta',bytes(4)+box(b'ilst',b''.join(fields))))))


class ResultsTests(TestCase):
    setUp=bridge_fixtures.OneTaggerBridgeTests.setUp
    export=bridge_fixtures.OneTaggerBridgeTests.export
    results_report=bridge_fixtures.OneTaggerBridgeTests.results_report
    import_report=bridge_fixtures.OneTaggerBridgeTests.import_report
    stage=bridge_fixtures.OneTaggerBridgeTests.stage

    def raw_import(self,identity,data,**options):
        def launch(work,*_,**kwargs):work(lambda *_:None);return 'job'
        with patch.object(app,'launch',side_effect=launch):
            return self.client.post('/api/onetagger/'+identity+'/import-results',data=data,
                                    content_type='application/json',headers=self.headers,**options)

    def review(self,identity):return self.client.get('/api/onetagger/'+identity+'/review').json['scan']

    def real_selection(self):
        self.audio=self.root/'100%20 Café 日本.mp3'
        before={'title':'Old disk title','artist':'Disk artist','album':'Disk album','genre':'House','year':'2010-06-01'}
        mp3_tags(self.audio,before)
        self.track={**self.track,'current_path':'D:/Music/'+self.audio.name,'bpm':128,'tonality':'8A',
                    'play_count':17,'cues':[{'in_ms':1000,'kind':1}],'playlists':['Keep this set']}
        self.sid=self.store.save_snapshot({'scope_key':self.before['scope_key'],'tracks':[self.track]},'Report fixture')['id']
        self.before=deepcopy(self.store.snapshot(self.sid));self.bytes=self.audio.read_bytes()
        identity=self.export()
        after={'title':'Tagged Café 日本 <mix>','artist':'DJ, Producer','album':'New album','genre':'Techno','year':2020}
        mp3_tags(self.audio,{**after,'year':'2020-12-31'})
        report=self.results_report(identity,after);report['tracks'][0]['before']={**before,'year':2010}
        return identity,report,after

    def real_stage(self,identity,scan,fields=('genre',),unlock=True):
        self.client.post('/api/lab/unlock',json={'snapshot':self.sid,'unlocked':unlock},headers=self.headers)
        return self.client.post('/api/onetagger/'+identity+'/stage',headers=self.headers,json={
            'reviewed':True,'review_revision':scan['review_revision'],'edit_revision':scan['edit_revision'],
            'changes':[{'track_id':'one','field':field} for field in fields]})

    def test_raw_producer_report_reads_actual_id3_dates_and_retains_original_baseline(self):
        identity,report,after=self.real_selection();tagged=self.audio.read_bytes()
        data=json.dumps(report,ensure_ascii=False,indent=2).encode()
        response=self.raw_import(identity,data);self.assertEqual(response.status_code,200,response.json)
        scan=self.review(identity);self.assertEqual(scan['rows'][0]['tags'],after)
        self.assertEqual(scan['report']['digest'],sha256(data).hexdigest())
        genre=next(c for c in scan['rows'][0]['changes'] if c['field']=='genre')
        self.assertEqual(genre['library_value'],'House');self.assertEqual(genre['working_value'],'House')
        self.assertEqual(self.store.overrides(self.before['scope_key']),{})
        self.assertEqual(self.real_stage(identity,scan,('genre','year')).status_code,200)
        edits=self.store.overrides(self.before['scope_key'])['one']
        self.assertEqual(set(edits),{'genre','year'});self.assertEqual(edits['year']['value'],2020)
        self.assertEqual(edits['genre']['baseline'],'House')
        origin=json.loads(edits['genre']['origin']);self.assertEqual(origin['report']['application_commit'],'synthetic')
        self.assertEqual(origin['attempts'][0]['track_id'],'provider-42')
        self.assertEqual(self.store.snapshot(self.sid),self.before);self.assertEqual(self.audio.read_bytes(),tagged)
        exported=json.dumps(payload(self.store.effective(self.before),'Public fixture'))
        for private in ('snapshot_digest','mapping_revision','provider-42','uploaded_json_bytes'):
            self.assertNotIn(private,exported)

    def test_locked_review_never_stages_then_only_selected_field_is_applied(self):
        identity,report,_=self.real_selection();self.assertEqual(self.raw_import(identity,json.dumps(report)).status_code,200)
        scan=self.review(identity)
        self.assertEqual(self.real_stage(identity,scan,unlock=False).status_code,400)
        self.assertEqual(self.store.overrides(self.before['scope_key']),{})
        self.assertEqual(self.real_stage(identity,scan).status_code,200)
        self.assertEqual(set(self.store.overrides(self.before['scope_key'])['one']),{'genre'})
        self.assertEqual(self.store.snapshot(self.sid),self.before)

    def test_missing_tags_never_clear_captured_library_values(self):
        identity,report,_=self.real_selection();mp3_tags(self.audio,{'genre':'Techno'})
        report['tracks'][0]['after']={f:'Techno' if f=='genre' else None for f in FIELDS}
        s=stamp(self.audio);report['tracks'][0]['file_state']={'size':s[2],'modified_ns':str(s[3])}
        self.assertEqual(self.raw_import(identity,json.dumps(report)).status_code,200)
        scan=self.review(identity);self.assertEqual([c['field'] for c in scan['rows'][0]['changes']],['genre'])
        self.assertEqual(self.real_stage(identity,scan).status_code,200)
        self.assertEqual(self.store.effective(self.before)['tracks'][0]['title'],'Original')

    def test_reported_before_tags_cannot_replace_the_library_baseline(self):
        identity,report,_=self.real_selection();report['tracks'][0]['before']['genre']='Invented baseline'
        self.assertEqual(self.raw_import(identity,json.dumps(report)).status_code,200)
        proposal=next(c for c in self.review(identity)['rows'][0]['changes'] if c['field']=='genre')
        self.assertEqual(proposal['library_value'],'House')

    def test_duplicate_keys_nonfinite_invalid_encoding_and_depth_are_rejected_before_audio(self):
        identity,report,_=self.real_selection();valid=json.dumps(report)
        bad=[b'\xff',b'{',b'['*1500+b']'*1500,
             valid.replace('"version": 1','"version": 2, "version": 1').encode(),
             valid.replace('"score": 0.91','"score": NaN').encode(),
             valid.replace('"score": 0.91','"score": 1e999').encode(),
             valid.replace('"genre": "Techno"','"genre": "House", "genre": "Techno"').encode()]
        with patch('onetagger_bridge.read_tags',side_effect=AssertionError('Untrusted report opened audio')):
            for data in bad:
                response=self.raw_import(identity,data);self.assertEqual(response.status_code,400,response.data)
        self.assertIsNone(self.review(identity));self.assertEqual(self.store.overrides(self.before['scope_key']),{})

    def test_wrong_types_extreme_values_and_invalid_provider_evidence_are_rejected(self):
        identity=self.export();report=self.results_report(identity);manifest=self.store.setting('onetagger:'+identity)
        mutations=[lambda r:r.update(cancelled=1),lambda r:r.update(created_at='not a date'),
                   lambda r:r.update(completed_at='2026-11-17T12:01:00'),
                   lambda r:r['tracks'][0].update(attempts=[{}]),
                   lambda r:r['tracks'][0]['file_state'].update(size=True),
                   lambda r:r['tracks'][0]['file_state'].update(size=2**64),
                   lambda r:r['tracks'][0]['file_state'].update(modified_ns=1234),
                   lambda r:r['tracks'][0]['after'].update(year=True),
                   lambda r:r['tracks'][0]['after'].update(title='\ud800'),
                   lambda r:r['tracks'][0]['attempts'][0].update(reason='guessed'),
                   lambda r:r['tracks'][0]['attempts'][0].update(score=10**1000),
                   lambda r:r['tracks'][0]['attempts'][0].update(used_shazam='false')]
        for mutate in mutations:
            bad=deepcopy(report);mutate(bad)
            with self.assertRaises(ValueError):validate_report(bad,manifest)

    def test_scores_retain_provider_scale_without_becoming_probabilities(self):
        identity=self.export();report=self.results_report(identity);manifest=self.store.setting('onetagger:'+identity)
        report['tracks'][0]['attempts'][0]['score']=91.5
        self.assertEqual(validate_report(report,manifest)['rows']['one']['attempts'][0]['score'],91.5)

    def test_unknown_config_and_provider_response_fields_are_not_retained(self):
        identity=self.export();report=self.results_report(identity)
        report['config']={'password':'DO-NOT-RETAIN'};report['tracks'][0]['attempts'][0]['response']={'secret':'DO-NOT-RETAIN'}
        self.assertEqual(self.import_report(identity,report).status_code,200)
        self.assertNotIn('DO-NOT-RETAIN',json.dumps(self.review(identity)))

    def test_invalid_import_preserves_the_previous_review_and_generation(self):
        identity=self.export();report=self.results_report(identity);self.import_report(identity,report)
        previous=deepcopy(self.store.setting('onetagger:'+identity))
        report['selection']['mapping_revision']='foreign'
        with patch('onetagger_bridge.read_tags',side_effect=AssertionError('Foreign report opened audio')):
            self.assertEqual(self.raw_import(identity,json.dumps(report)).status_code,400)
        self.assertEqual(self.store.setting('onetagger:'+identity),previous)

    def test_changed_mapping_and_snapshot_are_rejected_before_readback(self):
        identity=self.export();report=self.results_report(identity)
        self.store.set_setting('audio_paths:'+self.before['scope_key'],[])
        with patch('onetagger_bridge.read_tags',side_effect=AssertionError('Stale mapping opened audio')):
            self.assertEqual(self.raw_import(identity,json.dumps(report)).status_code,409)
        self.store.set_setting('audio_paths:'+self.before['scope_key'],self.maps)
        manifest=self.store.setting('onetagger:'+identity);manifest['snapshot_digest']='different'
        self.store.set_setting('onetagger:'+identity,manifest)
        report['selection']['snapshot_digest']='different'
        with patch('onetagger_bridge.read_tags',side_effect=AssertionError('Changed snapshot opened audio')):
            self.assertEqual(self.raw_import(identity,json.dumps(report)).status_code,409)

    def test_unsupported_fields_and_unselected_ids_cannot_be_staged(self):
        identity=self.export();self.import_report(identity,self.results_report(identity));scan=self.review(identity)
        for field in ('rating','bpm','tonality','play_count','cues','current_path','playlists'):
            response=self.stage(identity,scan,changes=[{'track_id':'one','field':field}])
            self.assertEqual(response.status_code,400,response.json)
        self.assertEqual(self.stage(identity,scan,changes=[{'track_id':'other','field':'genre'}]).status_code,400)
        self.assertEqual(self.store.overrides(self.before['scope_key']),{})

    def test_superseded_report_and_intervening_edit_invalidate_approval(self):
        identity=self.export();report=self.results_report(identity);self.import_report(identity,report);old=self.review(identity)
        report['run_id']='e'*32;self.import_report(identity,report);current=self.review(identity)
        self.assertEqual(self.stage(identity,old).status_code,409)
        self.store.save_override(self.before['scope_key'],'one','title','Manual edit','Original')
        self.assertEqual(self.stage(identity,current,edit_revision=self.store.edit_state(self.before['scope_key'])['edit_revision']).status_code,409)
        self.assertEqual(set(self.store.overrides(self.before['scope_key'])['one']),{'title'})

    def test_cancellation_invalidates_old_approval_without_publishing_partial_scan(self):
        identity=self.export();report=self.results_report(identity);self.import_report(identity,report);old=self.review(identity)
        pending=[]
        with patch.object(app,'launch',side_effect=lambda work,*_,**kw:pending.append(work) or 'queued'):
            response=self.client.post('/api/onetagger/'+identity+'/import-results',json={'report':report},headers=self.headers)
        self.assertEqual(response.status_code,200)
        def stop(*_):raise OperationCancelled('Synthetic cancellation')
        with self.assertRaises(OperationCancelled):pending[0](stop)
        self.assertEqual(self.review(identity),old);self.assertEqual(self.stage(identity,old).status_code,409)
        self.assertEqual(self.store.overrides(self.before['scope_key']),{})

    def test_changed_file_during_staging_rolls_back_values_history_and_revisions(self):
        identity=self.export();self.import_report(identity,self.results_report(identity));scan=self.review(identity)
        real_stamp=stamp
        def external_write(path):
            path.write_bytes(path.read_bytes()+b'externally changed')
            return real_stamp(path)
        with patch('onetagger_bridge.stamp',side_effect=external_write):
            response=self.stage(identity,scan,changes=[{'track_id':'one','field':'title'},{'track_id':'one','field':'genre'}])
        self.assertEqual(response.status_code,409,response.json)
        self.assertEqual(self.store.edit_state(self.before['scope_key'],history=True),{'edit_revision':'0','overrides':{},'history':[]})

    def test_renamed_file_is_not_resolved_from_the_report(self):
        identity,report,_=self.real_selection();moved=self.audio.with_name('renamed.mp3');self.audio.rename(moved)
        self.assertEqual(self.raw_import(identity,json.dumps(report)).status_code,200)
        scan=self.review(identity);self.assertEqual(scan['rows'][0]['status'],'unreadable')
        self.assertEqual(scan['rows'][0]['changes'],[])
        report['tracks'][0]['final_path']=str(moved)
        with patch('onetagger_bridge.read_tags',side_effect=AssertionError('Report redirected file access')):
            self.assertEqual(self.raw_import(identity,json.dumps(report)).status_code,400)

    def test_results_and_provider_evidence_survive_store_restart_and_download(self):
        identity=self.export();self.import_report(identity,self.results_report(identity));scan=self.review(identity)
        restored=Store(self.root/'workbench-sidecar.sqlite3').setting('onetagger:'+identity)
        self.assertEqual(restored['scan'],scan)
        response=self.client.get('/api/onetagger/'+identity+'/review?download=1')
        self.assertEqual(response.json['scan'],scan);self.assertIn('attachment',response.headers['Content-Disposition'])

    def test_utf8_bom_and_legacy_envelope_are_supported(self):
        identity=self.export();report=self.results_report(identity)
        self.assertEqual(decode_report(b'\xef\xbb\xbf'+json.dumps(report).encode()),report)
        self.assertEqual(decode_report(json.dumps({'report':report}).encode()),report)

    def test_stream_size_is_bounded_even_without_a_content_length(self):
        identity=self.export();report=self.results_report(identity,{})
        report['tracks'][0]['after']={field:None for field in FIELDS}
        data=json.dumps(report).encode()
        response=self.raw_import(identity,data,environ_overrides={'CONTENT_LENGTH':'','wsgi.input_terminated':True})
        self.assertEqual(response.status_code,200,response.json)
        with patch('onetagger_bridge.MAX_BYTES',100),patch('onetagger_bridge.read_tags',side_effect=AssertionError('Oversize upload opened audio')):
            response=self.raw_import(identity,b' '*101,environ_overrides={'CONTENT_LENGTH':'','wsgi.input_terminated':True})
        self.assertEqual(response.status_code,400,response.json)

    def test_actual_tag_changes_after_review_block_staging(self):
        identity,report,_=self.real_selection();self.assertEqual(self.raw_import(identity,json.dumps(report)).status_code,200)
        scan=self.review(identity);mp3_tags(self.audio,{'title':'Changed outside Workbench','genre':'Other'})
        response=self.real_stage(identity,scan)
        self.assertEqual(response.status_code,409,response.json)
        self.assertEqual(self.store.overrides(self.before['scope_key']),{})

    def test_mp4_repeated_text_atoms_match_the_producer_scalar_representation(self):
        self.audio=self.root/'100%20 Café.m4a'
        mp4_tags(self.audio,{'title':'Tagged MP4','artist':['First','Second'],'album':['Album','Edition'],
                             'genre':'Techno','year':'2020-12-31'})
        self.track={**self.track,'current_path':'D:/Music/'+self.audio.name}
        self.sid=self.store.save_snapshot({'scope_key':self.before['scope_key'],'tracks':[self.track]},'MP4 report')['id']
        self.before=self.store.snapshot(self.sid);identity=self.export()
        values={'title':'Tagged MP4','artist':'First, Second','album':'Album, Edition','genre':'Techno','year':2020}
        report=self.results_report(identity,values);original=self.audio.read_bytes()
        self.assertEqual(self.raw_import(identity,json.dumps(report)).status_code,200)
        scan=self.review(identity);self.assertEqual(scan['rows'][0]['status'],'read')
        self.assertEqual(scan['rows'][0]['tags'],values)
        self.assertEqual(self.real_stage(identity,scan,('artist',)).status_code,200)
        self.assertEqual(self.store.overrides(self.before['scope_key'])['one']['artist']['value'],'First, Second')
        self.assertEqual(self.audio.read_bytes(),original);self.assertEqual(self.store.snapshot(self.sid),self.before)

    def test_duplicate_ids_are_rejected_even_when_the_row_count_matches(self):
        source=deepcopy(self.before);source['tracks'].append({**source['tracks'][0],'id':'two'})
        self.sid=self.store.save_snapshot(source,'Two selected IDs')['id']
        identity=self.client.post('/api/onetagger/export',json={'snapshot':self.sid,'track_ids':['one','two']},headers=self.headers).json['id']
        report=self.results_report(identity);report['tracks'].append(deepcopy(report['tracks'][0]))
        with patch('onetagger_bridge.read_tags',side_effect=AssertionError('Duplicate IDs opened audio')):
            response=self.raw_import(identity,json.dumps(report))
        self.assertEqual(response.status_code,400,response.json)

    def test_mixed_cancelled_results_keep_all_rows_and_only_verify_written_files(self):
        identity=self.export();manifest=self.store.setting('onetagger:'+identity)
        # A native library can contain several IDs for the same selected audio.
        snapshot=deepcopy(self.before);snapshot['tracks'].append({**snapshot['tracks'][0],'id':'two'})
        self.sid=self.store.save_snapshot(snapshot,'Two IDs')['id'];self.before=self.store.snapshot(self.sid)
        identity=self.client.post('/api/onetagger/export',json={'snapshot':self.sid,'track_ids':['one','two']},headers=self.headers).json['id']
        report=self.results_report(identity);second=deepcopy(report['tracks'][0]);second.update(track_id='two',status='unprocessed',attempts=[])
        report['tracks'].append(second);report['cancelled']=True
        with patch('onetagger_bridge.read_tags',return_value=({'title':'Tagged title','genre':'Techno','year':2020},stamp(self.audio),[])) as reader:
            def launch(work,*_,**kw):work(lambda *_:None);return 'job'
            with patch.object(app,'launch',side_effect=launch):
                self.assertEqual(self.client.post('/api/onetagger/'+identity+'/import-results',json={'report':report},headers=self.headers).status_code,200)
        scan=self.review(identity);self.assertEqual(reader.call_count,1)
        self.assertEqual(scan['summary']['verified'],1);self.assertEqual(scan['summary']['not_written'],1)
        self.assertTrue(scan['report']['cancelled']);self.assertEqual(scan['rows'][1]['changes'],[])


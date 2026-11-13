"""Synthetic regression cases only. Never load a user's library or call a service."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import json
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import wave
import zipfile

from analysis_audit import audit_assets
from library_checks import compare_snapshots,metadata_consistency,collection_coverage
from metadata_export import track,payload
from metadata_overrides import validate,plan,apply_xml,apply_native
from musicbrainz_pilot import sample_genres,public_query,proposals,MusicBrainzClient,RateGate,create_batch,run_batch
from workbench_store import Store


def song(identity='one',**values):
    return {**track({'id':identity,'title':'A song '+identity,'artist':'An artist','genre':'House','duration':240,'rating':2,'play_count':0,'analysed':True,'manual_cues':1,'auto_cues':0}),
            'uuid':'uuid-'+identity,'cues':[{'kind':1,'in_ms':1000,'out_ms':-1,'label':'Drop','color':3,'auto':False}],**values}


def snapshot(tracks=None):
    return {'schema':1,'id':'synthetic','scope_key':'scope','tracks':[song()] if tracks is None else tracks,'playlists':[],
            'capabilities':{'playlist_order':True,'cue_positions':True,'analysis_references':True},'asset_references':[]}


class ComparisonTests(unittest.TestCase):
    def test_positions_labels_ratings_and_order_are_independent_evidence(self):
        before=snapshot([song('one'),song('two')]);after=deepcopy(before)
        before['playlists']=[{'id':'p','uuid':'p-uuid','name':'Set','parent':'root','tracks':['one','two']}]
        after['playlists']=deepcopy(before['playlists']);after['playlists'][0]['tracks'].reverse()
        after['tracks'][0]['cues'][0]['in_ms']=2000;after['tracks'][0]['rating']=4
        after['tracks'][1]['cues'][0]['label']='Mix here'
        summary,rows=compare_snapshots(before,after)
        self.assertEqual(summary['changed_cue'],1);self.assertEqual(summary['cue_annotation'],1)
        self.assertEqual(summary['ratings_changed'],1)
        playlist=next(r for r in rows if r['section']=='playlist')
        self.assertTrue(playlist['changes']['order_changed']);self.assertEqual(playlist['changes']['removed'],[])

    def test_reused_ids_and_ambiguous_matches_never_claim_lost_cues(self):
        before=snapshot();after=snapshot([song(uuid='different',cues=[])])
        summary,rows=compare_snapshots(before,after)
        self.assertEqual(summary['matched_tracks'],0);self.assertNotIn('lost_cue',summary)
        self.assertTrue(all(r['section'].startswith('unmatched') for r in rows))

    def test_cue_tolerance_and_missing_capabilities(self):
        before=snapshot();after=deepcopy(before);after['tracks'][0]['cues'][0]['in_ms']+=2
        self.assertNotIn('changed_cue',compare_snapshots(before,after,2)[0])
        after['tracks'][0]['cues']=None;after['capabilities']['playlist_order']=False
        summary,_=compare_snapshots(before,after)
        self.assertEqual(summary['cue_comparison_unavailable'],1);self.assertEqual(summary['playlist_comparison_unavailable'],1)

    def test_smart_playlist_rules_are_compared_without_invented_manual_changes(self):
        before=snapshot();after=deepcopy(before)
        p={'id':'p','uuid':'p','name':'Smart','parent':'root','tracks':['one'],'smart':True,'criteria_sha256':'old'}
        before['playlists']=[p];after['playlists']=[{**p,'tracks':[],'criteria_sha256':'new'}]
        _,rows=compare_snapshots(before,after);changes=rows[0]['changes']
        self.assertEqual(changes,{'smart_criteria':'changed'})

    def test_case_spacing_and_unicode_variants_are_conservative_candidates(self):
        s=snapshot([song('one',artist='Ａrtist',genre='Deep House'),song('two',artist='artist',genre='deep  house'),song('three',raw_tags={'year':9999})])
        summary,rows=metadata_consistency(s)
        self.assertEqual(summary['variant_groups'],2);self.assertEqual(summary['implausible_values'],1)
        self.assertTrue(any(r['section']=='missing' for r in rows))

    def test_unknown_preparation_is_not_counted_as_prepared_or_unplayed(self):
        s=snapshot([song('one',analysed=None,manual_cues=None,auto_cues=None,play_count=None),song('two')])
        summary,rows=collection_coverage(s)
        self.assertEqual(summary['unplayed'],1);self.assertEqual(summary['unknown_preparation'],1)
        group=next(r for r in rows if r['section']=='coverage_group' and r['group_kind']=='genre')
        self.assertEqual(group['prepared_percent'],50)


class StoreAndOverrideTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name);self.store=Store(self.root/'working.sqlite3')

    def test_edits_and_reset_do_not_modify_immutable_snapshots(self):
        s=snapshot();identity=self.store.save_snapshot(s,'Original')['id'];original=self.store.snapshot(identity)
        self.store.save_override('scope','one','genre','Deep House','House')
        self.assertEqual(self.store.effective(original)['tracks'][0]['genre'],'Deep House')
        self.assertEqual(self.store.snapshot(identity),original)
        self.store.clear_override('scope','one','genre');self.assertEqual(self.store.effective(original)['metadata_overrides_applied'],0)

    def test_whole_stars_plausible_year_and_merge_conflicts(self):
        for field,value in [('rating',2.5),('rating',6),('year',42),('genre','bad\0tag')]:
            with self.assertRaises(ValueError):validate(field,value)
        c=SimpleNamespace(tracks={'one':{},'two':{}},metadata={'field_overrides':{'one':{'genre':'House'},'two':{'genre':'Techno'}}})
        with self.assertRaisesRegex(ValueError,'conflicting'):plan(c,{'two':'one'})
        c.metadata['field_overrides']['two']['genre']='House';self.assertEqual(plan(c,{'two':'one'}),{'one':{'genre':'House'}})

    def test_native_metadata_creates_named_rows_and_verifies_foreign_keys(self):
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.executescript('CREATE TABLE djmdContent(ID TEXT,Title TEXT,ReleaseYear INTEGER,Rating INTEGER,ArtistID TEXT,AlbumID TEXT,GenreID TEXT,rb_local_deleted INTEGER); INSERT INTO djmdContent VALUES ("one","Old",0,0,NULL,NULL,NULL,0);')
        for table in ('djmdArtist','djmdAlbum','djmdGenre'):db.execute('CREATE TABLE '+table+'(ID TEXT PRIMARY KEY,Name TEXT,UUID TEXT,rb_local_deleted INTEGER,rb_local_usn INTEGER,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)')
        tables={r[0]:{c[1] for c in db.execute('PRAGMA table_info('+r[0]+')')} for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        def update(table,where,params,values):db.execute('UPDATE '+table+' SET '+','.join(k+'=?' for k in values)+' WHERE '+where,[*values.values(),*params])
        edits={'one':{'year':2001,'rating':5,'genre':'Deep House','artist':'An artist','album':'An album','title':'A title'}}
        created=apply_native(db,tables,edits,update,'2026-01-01',lambda:1)
        self.assertEqual(created,3);self.assertEqual(db.execute('SELECT Title,ReleaseYear,Rating FROM djmdContent').fetchone(),('A title',2001,5))
        self.assertEqual(apply_native(db,tables,edits,update,'2026-01-01',lambda:2),0)
        apply_native(db,tables,{'one':{'genre':'','year':None}},update,'2026-01-01',lambda:3)
        self.assertEqual(db.execute('SELECT GenreID,ReleaseYear FROM djmdContent').fetchone(),(None,0))

    def test_xml_rating_scaling_year_clear_and_offline_projection(self):
        from xml.etree.ElementTree import Element
        element=Element('TRACK',Year='2000');apply_xml(element,{'year':None,'rating':4,'genre':'Deep House'})
        self.assertNotIn('Year',element.attrib);self.assertEqual(element.get('Rating'),'204')
        self.store.save_override('scope','one','rating',4,2)
        data=payload(self.store.effective(snapshot()),'Test',False)
        self.assertEqual(data['metadata_overrides_applied'],1);self.assertFalse(data['staged_changes_applied'])
        self.assertEqual(data['rows'][0][data['columns'].index('rating')],4)

    def test_reports_filter_and_bulk_edits_are_bounded(self):
        r=self.store.save_report('test',['synthetic'],{},[{'section':'x','title':'one'},{'section':'y','title':'two'}])
        self.assertEqual(self.store.report(r['id'],section='x')['total'],1)
        self.assertEqual(self.store.report(r['id'],query="' OR 1=1 --")['total'],0)
        with self.assertRaises(ValueError):self.store.save_bulk(snapshot(),['outside'],'genre','House')

    def test_real_xml_and_encrypted_zip_writers_share_field_edits_and_keep_sources(self):
        from native_export import mutable_copy,export_native
        from engine import export_xml,open_master,parse_xml
        from hashlib import sha256
        from contextlib import closing
        master=self.root/'fixture.db'
        with closing(mutable_copy(master)) as db:
            db.executescript('''
              CREATE TABLE djmdContent(ID TEXT PRIMARY KEY,Title TEXT,ReleaseYear INTEGER,Rating INTEGER,ArtistID TEXT,AlbumID TEXT,GenreID TEXT,rb_local_deleted INTEGER,rb_local_synced INTEGER,rb_local_usn INTEGER,updated_at TEXT,Commnt TEXT,ColorID TEXT);
              INSERT INTO djmdContent VALUES ('one','Original',2000,1,NULL,NULL,NULL,0,1,0,'old','Original comment','0');
              CREATE TABLE djmdColor(ID TEXT PRIMARY KEY,ColorCode INTEGER,SortKey INTEGER,Commnt TEXT,rb_local_deleted INTEGER);
              INSERT INTO djmdColor VALUES ('custom-red-row',NULL,2,'Peak time',0);
              CREATE TABLE agentRegistry(registry_id TEXT,int_1 INTEGER,updated_at TEXT);
              INSERT INTO agentRegistry VALUES ('localUpdateCount',0,'old');
            ''')
            for table in ('djmdArtist','djmdAlbum','djmdGenre'):db.execute('CREATE TABLE '+table+'(ID TEXT PRIMARY KEY,Name TEXT,UUID TEXT,rb_local_deleted INTEGER,rb_local_synced INTEGER,rb_local_usn INTEGER,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)')
            db.commit()
        backup=self.root/'source.zip';xml=self.root/'source.xml'
        with zipfile.ZipFile(backup,'w') as z:
            z.write(master,'master.db');z.writestr('contents.xml','<ROOT><VALUE name="CONTENT_NUM" val="1"/></ROOT>');z.writestr('USBANLZ/a/b/ANLZ0000.DAT',b'unchanged analysis')
        xml.write_text('<DJ_PLAYLISTS><PRODUCT Version="7.0.0"/><COLLECTION Entries="1"><TRACK TrackID="one" Name="Original" Artist="" Year="2000" Rating="51"><TEMPO Inizio="0" Bpm="120" Metro="4/4" Battito="1"/><POSITION_MARK Name="Drop" Num="0" Type="0" Start="1.000"/></TRACK></COLLECTION><PLAYLISTS><NODE><TRACK Key="one"/></NODE></PLAYLISTS></DJ_PLAYLISTS>',encoding='utf-8')
        original=[sha256(p.read_bytes()).hexdigest() for p in (backup,xml)]
        edits={'one':{'title':'Łódź · Ελληνικά · Česky · Русский · 🎧','artist':'Grüße & Français','album':'Città più · Español ñ','genre':'House · Δοκιμή','year':2024,'rating':4,'comment':'First line\nGrüße Français Città Español Ελληνικά Łódź Český Русский 🎧 & <mix>','colour':'#FF0000'}}
        c=SimpleNamespace(tracks={'one':{'october_xml':True}},metadata={'xml_path':str(xml),'zip_path':str(backup),'version':'7.0.0','field_overrides':edits})
        outxml=self.root/'edited.xml';outzip=self.root/'edited.zip'
        x=export_xml(c,{}, {},outxml,lambda *_:None);n=export_native(c,{}, {},outzip,lambda *_:None)
        self.assertEqual((x['metadata_fields'],n['metadata_fields']),(8,8))
        checked=parse_xml(outxml,lambda *_:None)[0]['one'];self.assertEqual(checked['attrs']['Genre'],edits['one']['genre']);self.assertEqual(checked['attrs']['Rating'],'204')
        self.assertEqual(checked['attrs']['Name'],edits['one']['title']);self.assertEqual(checked['attrs']['Artist'],edits['one']['artist']);self.assertEqual(checked['attrs']['Album'],edits['one']['album'])
        self.assertEqual(checked['tempo'],1);self.assertEqual(checked['marks'][0]['Name'],'Drop')
        self.assertEqual(checked['attrs']['Comments'],edits['one']['comment'])
        self.assertEqual(checked['attrs']['Colour'],'0xFF0000')
        self.assertEqual((x['metadata_changes_by_field']['comment'],n['metadata_changes_by_field']['colour']),(1,1))
        with zipfile.ZipFile(outzip) as z:
            extracted=self.root/'check.db';extracted.write_bytes(z.read('master.db'));self.assertEqual(z.read('USBANLZ/a/b/ANLZ0000.DAT'),b'unchanged analysis')
        with closing(open_master(extracted.resolve())) as db:
            self.assertEqual(tuple(db.execute('SELECT Title,ReleaseYear,Rating FROM djmdContent').fetchone()),(edits['one']['title'],2024,4))
            self.assertEqual(db.execute('SELECT Name FROM djmdGenre').fetchone()[0],edits['one']['genre'])
            self.assertEqual(db.execute('SELECT Name FROM djmdArtist').fetchone()[0],edits['one']['artist']);self.assertEqual(db.execute('SELECT Name FROM djmdAlbum').fetchone()[0],edits['one']['album'])
            self.assertEqual(db.execute('SELECT Commnt FROM djmdContent').fetchone()[0],edits['one']['comment'])
            self.assertEqual(db.execute('SELECT ColorID FROM djmdContent').fetchone()[0],'custom-red-row')
        self.assertEqual([sha256(p.read_bytes()).hexdigest() for p in (backup,xml)],original)

    def test_plaintext_private_wal_capture_keeps_committed_rows(self):
        import shutil
        from research_capture import open_capture
        from contextlib import closing
        source=self.root/'source';source.mkdir();private=self.root/'detached';private.mkdir()
        with closing(sqlite3.connect(source/'master.db')) as db:
            db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA wal_autocheckpoint=0')
            db.execute('CREATE TABLE synthetic(value TEXT)');db.execute("INSERT INTO synthetic VALUES ('committed in WAL')");db.commit()
            for p in source.iterdir():
                if p.name!='master.db-shm':shutil.copyfile(p,private/p.name)
            with closing(open_capture(private/'master.db')) as captured:self.assertEqual(captured.execute('SELECT value FROM synthetic').fetchone()[0],'committed in WAL')


class AssetAndOrphanTests(unittest.TestCase):
    def test_candidates_are_not_verified_until_requested_and_scope_is_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);s=snapshot();s['asset_references']=['/USBANLZ/missing/id/ANLZ0000.DAT']
            for part in ('one','two'):
                p=root/'USBANLZ'/part/'id';p.mkdir(parents=True);(p/'ANLZ0000.DAT').write_bytes(b'same analysis')
            summary,rows=audit_assets(s,str(root),lambda *_:None)
            self.assertEqual(summary['missing_in_scope'],1);self.assertEqual(summary['unreferenced_folders'],2)
            self.assertEqual(summary['verified_duplicate_groups'],0)
            self.assertEqual(audit_assets(s,str(root),lambda *_:None,True)[0]['verified_duplicate_groups'],1)
            self.assertEqual(audit_assets(s,str(root),lambda *_:None,True,1)[0]['verified_duplicate_groups'],0)
            s['capabilities']['analysis_references']=False
            self.assertIsNone(audit_assets(s,str(root),lambda *_:None)[0]['unreferenced_folders'])

    def test_unreferenced_local_wav_tags_fallback_is_read_only(self):
        from orphan_metadata import capture_orphans
        from media import file_record,scan
        from hashlib import sha256
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'An artist - A song.wav'
            with wave.open(str(path),'wb') as out:out.setparams((1,2,8000,0,'NONE','not compressed'));out.writeframes(b'\0\0'*800)
            original=sha256(path.read_bytes()).hexdigest()
            inventory=scan({},[{'root':temporary}],lambda *_:None)
            self.assertEqual(len(inventory['orphans']),1)
            s=capture_orphans(inventory,lambda *_:None)
            self.assertEqual(s['tracks'][0]['artist'],'An artist');self.assertEqual(s['tracks'][0]['title'],'A song')
            self.assertEqual(sha256(path.read_bytes()).hexdigest(),original)
            with patch('orphan_metadata.file_record',return_value={**file_record(path),'cloud_only':True}):self.assertEqual(capture_orphans(inventory,lambda *_:None)['tracks'],[])


class MusicBrainzTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.store=Store(Path(temporary.name)/'pilot.sqlite3')

    def test_sample_twenty_per_top_genre_plus_fifty_unknown_unique_and_stable(self):
        tracks=[song(str(n),genre='Genre '+str(n//30)) for n in range(180)]+[song('unknown'+str(n),genre='') for n in range(70)]
        selected,groups=sample_genres(snapshot(tracks),5,'seed')
        self.assertEqual(len(selected),150);self.assertEqual([g['sampled'] for g in groups],[20]*5+[50])
        self.assertEqual(selected,sample_genres(snapshot(tracks),5,'seed')[0])
        with self.assertRaises(ValueError):sample_genres(snapshot(tracks),13)

    def test_queries_withhold_paths_and_rating_is_not_search_relevance(self):
        with self.assertRaises(ValueError):public_query(song(title='C:/Private/Music/file.mp3'))
        query=public_query(song(title='Track "quoted"',current_path='/private/path'))
        self.assertNotIn('path',json.dumps(query));self.assertIn('\\"quoted\\"',query['query'])
        self.assertIsNone(proposals({'score':100,'rating':{'value':5,'votes-count':0}})['community_score'])
        self.assertEqual(proposals({'rating':{'value':'4.2','votes-count':6}})['community_score'],4.2)

    def test_feature_disabled_blocks_even_cached_retrieval_and_delay_has_floor(self):
        with self.assertRaises(ValueError):MusicBrainzClient(self.store,RateGate(),lambda:True,delay=.5)
        client=MusicBrainzClient(self.store,RateGate(),lambda:False)
        with self.assertRaises(InterruptedError):client.get('recording/',{'query':'a'})
        event=threading.Event();gate=RateGate();gate.last=10
        with patch('musicbrainz_pilot.time.monotonic',return_value=10),patch.object(event,'wait',return_value=False) as wait:gate.wait(.1,event);wait.assert_called_once_with(1.1)

    def test_cached_queries_and_retry_after_are_serial_and_bounded(self):
        gate=SimpleNamespace(wait=lambda *args:None);response=BytesIO(b'{"recordings":[]}');calls=[]
        def transport(req,timeout):calls.append(req);return response
        client=MusicBrainzClient(self.store,gate,lambda:True,transport=transport)
        self.assertEqual(client.get('recording/',{'query':'synthetic'}),{'recordings':[]})
        client.get('recording/',{'query':'synthetic'});self.assertEqual(len(calls),1);self.assertEqual(client.cache_hits,1)
        event=threading.Event();error=urllib.error.HTTPError('https://musicbrainz.org',429,'busy',{'Retry-After':'7'},None)
        client=MusicBrainzClient(self.store,gate,lambda:True,cancel=event,transport=lambda *a,**k:(_ for _ in ()).throw(error))
        with patch.object(event,'wait',return_value=False) as wait:
            with self.assertRaises(urllib.error.HTTPError):client.get('recording/',{'query':'another'})
            wait.assert_called_once_with(7)

    def test_provider_failures_are_not_local_tag_failures_and_matches_not_approved(self):
        s=snapshot();record=create_batch(self.store,s)
        client=SimpleNamespace(requests=0,cache_hits=0,get=lambda *a:(_ for _ in ()).throw(ValueError('provider JSON malformed')))
        self.assertEqual(run_batch(self.store,record['id'],client,lambda *_:None)['status'],'complete_with_errors')
        with self.store.connection() as db:r=db.execute('SELECT status FROM mb_results').fetchone()
        self.assertEqual(r[0],'service_error')

    def test_resuming_does_not_erase_reviewed_matches_or_query_them_again(self):
        from workbench_store import encoded
        s=snapshot();record=create_batch(self.store,s)
        previous={'status':'candidate_needs_review','match_approved':True,'proposal':{'community_score':4.1,'genre':'house','year':2001}}
        with self.store.connection() as db:db.execute('INSERT INTO mb_results VALUES (?,?,?,?)',(record['id'],'one',previous['status'],encoded(previous)))
        client=SimpleNamespace(requests=0,cache_hits=0,get=lambda *a:(_ for _ in ()).throw(AssertionError('Reviewed tracks must not be queried again')))
        result=run_batch(self.store,record['id'],client,lambda *_:None)
        self.assertEqual(result['summary']['rating_available'],1)
        with self.store.connection() as db:saved=json.loads(db.execute('SELECT payload FROM mb_results').fetchone()[0])
        self.assertTrue(saved['match_approved'])


class LabApiTests(unittest.TestCase):
    def setUp(self):
        import app as application
        self.application=application;temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.store=Store(self.root/'workbench-sidecar.sqlite3');self.sid=self.store.save_snapshot(snapshot(),'Synthetic')['id']
        for name,value in [('DATA',self.root),('sessions',{}),('active',None)]:
            p=patch.object(application,name,value);p.start();self.addCleanup(p.stop)
        self.client=application.app.test_client();self.headers={'X-Workbench-Token':application.TOKEN}

    def test_metadata_locked_token_and_host_guards(self):
        data={'snapshot':self.sid,'track_id':'one','field':'genre','value':'Deep House'}
        self.assertEqual(self.client.post('/api/lab/overrides',json=data).status_code,403)
        self.assertEqual(self.client.post('/api/lab/overrides',json=data,headers=self.headers).status_code,400)
        self.client.post('/api/lab/unlock',json={'snapshot':self.sid,'unlocked':True},headers=self.headers)
        self.assertEqual(self.client.post('/api/lab/overrides',json=data,headers=self.headers).status_code,200)
        self.assertEqual(self.client.get('/api/status',headers={'Host':'evil.example'}).status_code,400)
        self.assertIsNone(self.client.get('/api/status',headers={'Origin':'https://evil.example'}).headers.get('Access-Control-Allow-Origin'))

    def test_local_sample_preview_does_not_enable_network(self):
        response=self.client.post('/api/lab/musicbrainz/preview',json={'snapshot':self.sid,'speed':'gentle'},headers=self.headers)
        self.assertEqual(response.status_code,200);self.assertEqual(response.json['summary']['seconds_per_request'],3)
        start=self.client.post('/api/lab/musicbrainz/'+response.json['id']+'/start',json={'query_consent':True},headers=self.headers)
        self.assertEqual(start.status_code,400)
        with patch.dict('os.environ',{'LIBRARY_WORKBENCH_MUSICBRAINZ':'0'}):
            self.assertEqual(self.client.post('/api/lab/features',json={'musicbrainz_enabled':True},headers=self.headers).status_code,400)

    def test_provider_proposals_require_unlock_and_identity_approval(self):
        from workbench_store import encoded
        record=create_batch(self.store,self.store.snapshot(self.sid))
        result={'status':'candidate_needs_review','match_approved':False,'candidates':[{'mbid':'01234567-89ab-cdef-0123-456789abcdef'}],
                'proposal':{'year':2001,'genre':'deep house','retrieved_at':'2026-01-01'}}
        with self.store.connection() as db:db.execute('INSERT INTO mb_results VALUES (?,?,?,?)',(record['id'],'one',result['status'],encoded(result)))
        endpoint='/api/lab/musicbrainz/'+record['id'];data={'track_id':'one','field':'year'}
        self.assertEqual(self.client.post(endpoint+'/stage',json=data,headers=self.headers).status_code,400)
        self.client.post('/api/lab/unlock',json={'snapshot':self.sid,'unlocked':True},headers=self.headers)
        self.assertEqual(self.client.post(endpoint+'/stage',json=data,headers=self.headers).status_code,400)
        self.client.post(endpoint+'/review',json={'track_id':'one','approved':True},headers=self.headers)
        response=self.client.post(endpoint+'/stage',json=data,headers=self.headers)
        self.assertEqual(response.json['value'],2001);self.assertIn('MusicBrainz',response.json['origin'])
        self.assertEqual(self.client.post(endpoint+'/stage',json={'track_id':'one','field':'rating'},headers=self.headers).status_code,400)


if __name__=='__main__':unittest.main()

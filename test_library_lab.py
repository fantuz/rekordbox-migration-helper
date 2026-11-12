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
        self.assertEqual(run_batch(self.store,record['id'],client,lambda *_:None)['status'],'complete')
        with self.store.connection() as db:r=db.execute('SELECT status FROM mb_results').fetchone()
        self.assertEqual(r[0],'service_error')


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


if __name__=='__main__':unittest.main()

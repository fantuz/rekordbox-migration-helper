from test_support import workspace_client
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
from musicbrainz_pilot import sample_genres,public_query,proposals,MusicBrainzClient,RateGate,create_batch,run_batch,batch_record
from workbench_store import Store


def song(identity='one',**values):
    return {**track({'id':identity,'title':'A song '+identity,'artist':'An artist','genre':'House','duration':240,'rating':2,'play_count':0,'analysed':True,'manual_cues':1,'auto_cues':0}),
            'uuid':'uuid-'+identity,'cues':[{'kind':1,'in_ms':1000,'out_ms':-1,'label':'Drop','color':3,'auto':False}],**values}


def snapshot(tracks=None):
    return {'schema':1,'id':'synthetic','scope_key':'scope','tracks':[song()] if tracks is None else tracks,'playlists':[],
            'capabilities':{'playlist_order':True,'cue_positions':True,'analysis_references':True},'asset_references':[]}


class ComparisonTests(unittest.TestCase):
    def test_active_loop_changes_are_independent_from_positions_and_annotations(self):
        before=snapshot();before['tracks'][0]['cues'][0].update(kind=4,out_ms=2000,active_loop=0)
        after=deepcopy(before);after['tracks'][0]['cues'][0].update(active_loop='1',label='Active loop')
        summary,rows=compare_snapshots(before,after)
        self.assertEqual(summary['cue_active_loop'],1);self.assertEqual(summary['cue_annotation'],1)
        result=next(r for r in rows if r['section']=='cue_active_loop')
        self.assertEqual(result['before']['active_loop'],0);self.assertEqual(result['after']['active_loop'],'1')
        self.assertEqual(compare_snapshots(after,before)[0]['cue_active_loop'],1)

    def test_active_loop_normalization_and_missing_evidence_do_not_invent_changes(self):
        before=snapshot();before['tracks'][0]['cues'][0]['active_loop']=1
        for value in (True,'1',None,2,'unknown'):
            after=deepcopy(before);after['tracks'][0]['cues'][0]['active_loop']=value
            self.assertEqual(compare_snapshots(before,after)[1],[])
        after=deepcopy(before);after['tracks'][0]['cues'][0].update(in_ms=1100,active_loop=0)
        summary,_=compare_snapshots(before,after)
        self.assertEqual(summary['changed_cue'],1);self.assertEqual(summary['cue_active_loop'],1)

    def test_known_performance_metadata_changes_retain_before_and_after_evidence(self):
        before=snapshot([song(bpm=87,tonality='Am',play_count=0,analysed=False)])
        after=deepcopy(before)
        after['tracks'][0].update(title='Renamed song',bpm=174,tonality='C',play_count=1,analysed=True)
        summary,rows=compare_snapshots(before,after)
        self.assertEqual(summary['metadata_changed'],5)
        fields={r['field']:r for r in rows}
        self.assertEqual((fields['bpm']['before'],fields['bpm']['after']),(87,174))
        self.assertEqual(fields['play_count']['before'],0)
        for name in ('bpm','tonality','play_count','analysed'):before['tracks'][0][name]=None
        self.assertEqual(compare_snapshots(before,after)[0]['metadata_changed'],1)

    def playlist_snapshot(self):
        result=snapshot()
        result['playlists']=[{'id':n,'uuid':'folder-'+n,'name':n,'parent':'root',
                              'folder':True,'smart':False,'tracks':[]} for n in ('a','b')]
        result['playlists'].append({'id':'p','uuid':'playlist-p','name':'Set','parent':'a',
                                    'folder':False,'smart':False,'tracks':['one','one']})
        return result

    def test_playlist_moves_and_type_changes_are_reported_without_invented_member_loss(self):
        before=self.playlist_snapshot();after=deepcopy(before)
        after['playlists'][2].update(parent='b',smart=True)
        summary,rows=compare_snapshots(before,after)
        self.assertEqual(summary['playlists_changed'],1)
        self.assertEqual(rows[0]['changes'],{'parent':['a','b'],'smart':[False,True]})
        after=deepcopy(before);after['playlists'][2]['folder']=True
        self.assertEqual(compare_snapshots(before,after)[1][0]['changes'],{'folder':[False,True]})

    def test_renumbered_parent_ids_are_resolved_before_hierarchy_comparison(self):
        before=self.playlist_snapshot();after=deepcopy(before)
        after['playlists'][0]['id']='new-a';after['playlists'][1]['id']='new-b'
        after['playlists'][2].update(id='new-p',parent='new-a')
        self.assertEqual(compare_snapshots(before,after)[1],[])
        after['playlists'][2]['parent']='new-b'
        self.assertEqual(compare_snapshots(before,after)[1][0]['changes'],{'parent':['a','new-b']})

    def test_uuid_matches_win_when_ids_are_reused_by_other_playlists(self):
        before=self.playlist_snapshot();after=deepcopy(before)
        after['playlists'][0]['id']='b';after['playlists'][1]['id']='a'
        after['playlists'][2]['parent']='b'
        summary,rows=compare_snapshots(before,after)
        self.assertEqual(rows,[]);self.assertNotIn('playlists_unmatched',summary)

    def test_unknown_or_unmatched_parents_do_not_become_proven_moves(self):
        before=self.playlist_snapshot();after=deepcopy(before)
        after['playlists'][2]['parent']='not-captured'
        summary,rows=compare_snapshots(before,after)
        self.assertEqual(rows,[]);self.assertEqual(summary['playlist_hierarchy_unavailable'],1)
        before['playlists'][2]['parent']=None
        after['playlists'][2]['parent']='root'
        self.assertEqual(compare_snapshots(before,after)[1],[])
        before=self.playlist_snapshot();after=deepcopy(before)
        after['playlists'][2]['parent']=0
        self.assertEqual(compare_snapshots(before,after)[1][0]['changes'],{'parent':['a',0]})

    def test_missing_playlist_type_fields_are_not_assumed_to_be_manual(self):
        before=self.playlist_snapshot();after=deepcopy(before)
        del before['playlists'][2]['smart'];del before['playlists'][2]['folder']
        after['playlists'][2].update(smart=True,folder=True)
        self.assertEqual(compare_snapshots(before,after)[1],[])

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
        c=SimpleNamespace(tracks={'one':{'october_xml':True}},metadata={'xml_path':str(xml),'zip_path':str(backup),'version':'7.0.0','field_overrides':edits,'export_target':'windows'})
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


    def test_full_batch_sort_survives_paging_and_updates(self):
        tracks=[song(str(i),title=f'Track {149-i:03}',artist=f'Artist {i%4}',year=2000+i%10)
                for i in range(150)]
        record=create_batch(self.store,snapshot(tracks),sample_size=150,target='random',seed='ordered')
        identity=record['id']
        default=batch_record(self.store,identity)
        first=batch_record(self.store,identity,0,'title','asc')
        second=batch_record(self.store,identity,50,'title','asc')
        third=batch_record(self.store,identity,100,'title','asc')
        expected=sorted([t['title'] for t in record['sample']],key=str.casefold)
        self.assertEqual([r['title'] for part in (first,second,third) for r in part['rows']],expected)
        self.assertEqual(first['sort'],'title')
        self.assertEqual(second['direction'],'asc')
        self.assertEqual(len(second['rows']),50)
        self.assertEqual(default['rows'][0]['id'],record['sample'][0]['id'])
        desc=batch_record(self.store,identity,50,'title','desc')
        self.assertEqual([r['title'] for r in desc['rows']],list(reversed(expected))[50:100])
        # Late provider results must not reset the active sort, and missing
        # numeric evidence remains at the end in both sort directions.
        with self.store.connection() as db:
            db.execute('INSERT INTO mb_results VALUES (?,?,?,?)',
                       (identity,record['sample'][0]['id'],'candidate_needs_review',
                        json.dumps({'status':'candidate_needs_review','candidates':[{'confidence':.98}],
                                    'proposal':{'year':2022}})))
        ranked=batch_record(self.store,identity,0,'confidence','desc')
        self.assertEqual(ranked['rows'][0]['id'],record['sample'][0]['id'])
        self.assertEqual(batch_record(self.store,identity,0,'confidence','asc')['rows'][0]['id'],record['sample'][0]['id'])
        self.assertEqual(batch_record(self.store,identity,50,'title','asc')['rows'][0]['title'],expected[50])
        for kwargs in ({'sort':'sql injection'}, {'direction':'sideways'}, {'offset':'n/a'}, {'offset':-1}):
            with self.assertRaises(ValueError):batch_record(self.store,identity,**kwargs)


    def test_combined_sort_fields_saved_health_and_missing_values(self):
        tracks=[song(str(i),title=f'Title {124-i:03}',artist='Same artist',genre='House') for i in range(125)]
        saved=self.store.save_snapshot(snapshot(tracks),'Recovered sorting')
        before=self.store.snapshot(saved['id'])
        batch=create_batch(self.store,before,target='random',sample_size=150,seed='combined')
        with self.store.connection() as db:
            for i in range(125):
                db.execute('INSERT INTO mb_results VALUES (?,?,?,?)',
                           (batch['id'],str(i),'candidate_needs_review',json.dumps({
                               'status':'candidate_needs_review',
                               'candidates':[{'title':f'Candidate {124-i:03}','confidence':i/125}],
                               'proposal':{'community_score':i/25,'year':1900+i}})))
            for i,state in [(0,'missing'),(1,'playable'),(2,'inaccessible'),(3,'unverified')]:
                db.execute('INSERT INTO file_health_records VALUES (?,?,?,?,?,?,?,?)',
                           ('snapshot:'+saved['id'],str(i),'Title','Artist','House',state,123.0,''))
        pages=[batch_record(self.store,batch['id'],offset,'title') for offset in (0,50,100)]
        self.assertEqual([r['title'] for page in pages for r in page['rows']],[f'Title {i:03}' for i in range(125)])
        self.assertEqual([len(page['rows']) for page in pages],[50,50,25])
        for field in ('confidence','community','year'):
            self.assertEqual(batch_record(self.store,batch['id'],0,field,'desc')['rows'][0]['id'],'124')
        self.assertEqual(batch_record(self.store,batch['id'],0,'candidate')['rows'][0]['id'],'124')
        for direction,expected in [('asc',['1','0','2','3']),('desc',['3','2','0','1'])]:
            result=batch_record(self.store,batch['id'],0,'file_status',direction)
            self.assertEqual([r['id'] for r in result['rows'][:4]],expected)
            self.assertEqual(result['rows'][4]['file_status'],'unchecked')
            self.assertIsNone(result['rows'][4]['file_status_checked_at'])
            self.assertEqual(result['rows'][0]['file_status_checked_at'],123.0)
            self.assertEqual(result['file_status_basis'],'last_explicit_scan')
        # Status evidence is scoped to the batch snapshot, not merely track ID.
        other=create_batch(self.store,snapshot(tracks),target='random',sample_size=150)
        self.assertTrue(all(r['file_status']=='unchecked' for r in batch_record(self.store,other['id'])['rows']))
        self.assertEqual(self.store.snapshot(saved['id']),before)

    def test_sort_ties_nonfinite_values_and_original_order(self):
        batch=create_batch(self.store,snapshot([song(str(i)) for i in range(6)]),target='random',sample_size=150)
        ids=[row['id'] for row in batch['sample']]
        with self.store.connection() as db:
            for identity,number in zip(ids,[0.5,0.5,'NaN','Infinity',None,True]):
                db.execute('INSERT INTO mb_results VALUES (?,?,?,?)',
                           (batch['id'],identity,'candidate_needs_review',json.dumps({
                               'status':'candidate_needs_review',
                               'candidates':[{'confidence':number,'title':'Equal'}],
                               'proposal':{'community_score':number}})))
        for field in ('confidence','community'):
            for direction in ('asc','desc'):
                self.assertEqual([r['id'] for r in batch_record(self.store,batch['id'],0,field,direction)['rows']],ids)
        for field in ('sample','original','candidate','artist','genre','status'):
            self.assertEqual([r['id'] for r in batch_record(self.store,batch['id'],0,field,'desc')['rows']],ids)
        for kwargs in ({'sort':'not-a-field'},{'direction':'bad'},{'offset':-1},{'offset':1000001},{'offset':'bad'}):
            with self.assertRaises(ValueError):batch_record(self.store,batch['id'],**kwargs)

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


    def test_fallback_search_is_bounded_and_keeps_version_review(self):
        from musicbrainz_pilot import search_strategies,candidates_for
        track=song('fallback',title='Dancing (Extended Mix)',artist='Example DJ')
        options=search_strategies(track,public_query(track))
        self.assertEqual([kind for kind,_ in options],['exact','base_title','title_only'])
        self.assertNotIn('Extended Mix',options[1][1])
        isrc={'isrc':'USABC1234567','query':'isrc:USABC1234567'}
        self.assertEqual(len(search_strategies(track,isrc)),1)
        recording={'id':'01234567-89ab-cdef-0123-456789abcdef',
                   'title':'Dancing','artist-credit':[{'name':'Example DJ'}], 'length':240000}
        candidate=candidates_for(track,[recording])[0]
        self.assertTrue(candidate['version_needs_review'])
        self.assertFalse(candidate['match_approved'])

    def test_empty_strict_search_uses_tag_fallback_without_approval(self):
        track=song('fallback',title='Dancing (Extended Mix)',artist='Example DJ')
        batch=create_batch(self.store,snapshot([track]),playable_only=False)
        calls=[]
        recording={'id':'01234567-89ab-cdef-0123-456789abcdef',
                   'title':'Dancing','artist-credit':[{'name':'Example DJ'}], 'length':240000}
        def lookup(endpoint,params):
            calls.append((endpoint,params))
            if endpoint=='recording/':
                return {'recordings':[recording] if 'Extended Mix' not in params['query'] else []}
            return {'id':recording['id'],'rating':{'votes-count':0},'releases':[]}
        client=SimpleNamespace(requests=0,cache_hits=0,get=lookup)
        output=run_batch(self.store,batch['id'],client,lambda *_:None)
        self.assertEqual(output['status'],'complete')
        with self.store.connection() as db:
            found=json.loads(db.execute('SELECT payload FROM mb_results WHERE batch_id=?',(batch['id'],)).fetchone()[0])
        self.assertEqual(found['search_strategy'],'base_title')
        self.assertEqual(found['search_attempts'],2)
        self.assertTrue(found['candidates'][0]['version_needs_review'])
        self.assertFalse(found['match_approved'])
        self.assertEqual([value['limit'] for endpoint,value in calls if endpoint=='recording/'],[20,20])

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
        s=snapshot();record=create_batch(self.store,s,playable_only=False)
        client=SimpleNamespace(requests=0,cache_hits=0,get=lambda *a:(_ for _ in ()).throw(ValueError('provider JSON malformed')))
        self.assertEqual(run_batch(self.store,record['id'],client,lambda *_:None)['status'],'complete_with_errors')
        with self.store.connection() as db:r=db.execute('SELECT status FROM mb_results').fetchone()
        self.assertEqual(r[0],'service_error')

    def test_resuming_does_not_erase_reviewed_matches_or_query_them_again(self):
        from workbench_store import encoded
        s=snapshot();record=create_batch(self.store,s,playable_only=False)
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
        self.client=workspace_client(application);self.headers={'X-Workbench-Token':application.TOKEN}

    def test_metadata_locked_token_and_host_guards(self):
        data={'snapshot':self.sid,'track_id':'one','field':'genre','value':'Deep House'}
        self.assertEqual(self.client.post('/api/lab/overrides',json=data).status_code,403)
        self.assertEqual(self.client.post('/api/lab/overrides',json=data,headers=self.headers).status_code,400)
        self.client.post('/api/lab/unlock',json={'snapshot':self.sid,'unlocked':True},headers=self.headers)
        self.assertEqual(self.client.post('/api/lab/overrides',json=data,headers=self.headers).status_code,200)
        self.assertEqual(self.client.get('/api/status',headers={'Host':'evil.example'}).status_code,400)
        self.assertIsNone(self.client.get('/api/status',headers={'Origin':'https://evil.example'}).headers.get('Access-Control-Allow-Origin'))

    def test_local_sample_preview_does_not_enable_network(self):
        result={}
        def launch(work,*args):result.update(work(lambda *_:None));return 'synthetic-preview'
        with patch('enrichment_context.source_details',return_value={'kind':'workspace'}),patch.object(self.application,'launch',side_effect=launch):
            response=self.client.post('/api/lab/musicbrainz/preview',json={'snapshot':self.sid,'speed':'gentle','include_unavailable':True},headers=self.headers)
        self.assertEqual(response.status_code,200);self.assertEqual(result['summary']['seconds_per_request'],3)
        start=self.client.post('/api/lab/musicbrainz/'+result['id']+'/start',json={'query_consent':True},headers=self.headers)
        self.assertEqual(start.status_code,400)
        with patch.dict('os.environ',{'LIBRARY_WORKBENCH_MUSICBRAINZ':'0'}):
            self.assertEqual(self.client.post('/api/lab/features',json={'musicbrainz_enabled':True},headers=self.headers).status_code,400)

    def test_provider_proposals_require_unlock_and_identity_approval(self):
        from workbench_store import encoded
        record=create_batch(self.store,self.store.snapshot(self.sid))
        result={'status':'candidate_needs_review','match_approved':False,'candidates':[{'mbid':'01234567-89ab-cdef-0123-456789abcdef'}],
                'proposal':{'year':2001,'genre':'deep house','retrieved_at':'2026-01-01'}}
        with self.store.connection() as db:db.execute('INSERT INTO mb_results VALUES (?,?,?,?)',(record['id'],'one',result['status'],encoded(result)))
        endpoint='/api/lab/musicbrainz/'+record['id'];data={'track_id':'one','field':'year','review_revision':__import__('musicbrainz_review').revision(result)}
        self.assertEqual(self.client.post(endpoint+'/stage',json=data,headers=self.headers).status_code,400)
        self.client.post('/api/lab/unlock',json={'snapshot':self.sid,'unlocked':True},headers=self.headers)
        self.assertEqual(self.client.post(endpoint+'/stage',json=data,headers=self.headers).status_code,400)
        review=self.client.post(endpoint+'/review',json={'track_id':'one','approved':True,'review_revision':data['review_revision']},headers=self.headers)
        data['review_revision']=review.json['review_revision']
        response=self.client.post(endpoint+'/stage',json=data,headers=self.headers)
        self.assertEqual(response.json['value'],2001);self.assertIn('MusicBrainz',response.json['origin'])
        self.assertEqual(self.client.post(endpoint+'/stage',json={'track_id':'one','field':'rating'},headers=self.headers).status_code,400)


if __name__=='__main__':unittest.main()

"""Synthetic integration regressions; execution is delegated to GitHub Actions."""
from contextlib import closing
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import json
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from analyzer import analyze_folder
from chart_playlists import ChartClient,match_chart,chart_m3u,local_audio_path
from library_intelligence import playlist_contents,collection_lenses
from musicbrainz_pilot import create_batch,sample_genres,proposals,run_batch
from platform_paths import database_names
from serato_bridge import draft_package,volume_relative
from workbench_store import Store,encoded
from test_library_lab import snapshot,song


def chunks(data):
    """Independent strict length walker, deliberately not the export encoder."""
    offset=0;result=[]
    while offset<len(data):
        if len(data)-offset<8:raise AssertionError('Truncated record header')
        tag=data[offset:offset+4].decode('ascii');length=struct.unpack_from('>I',data,offset+4)[0]
        end=offset+8+length
        if end>len(data):raise AssertionError('Truncated payload')
        result.append((tag,data[offset+8:end]));offset=end
    return result


class LargerPilotTests(unittest.TestCase):
    def test_stratified_sample_is_bounded_deterministic_and_deduplicated(self):
        source=snapshot([song(str(n),genre='Genre '+str(n%3)) for n in range(1300)])
        first,groups=sample_genres(source,3,'bigger',1000)
        self.assertEqual(len(first),1000);self.assertEqual(sum(g['sampled'] for g in groups),1000)
        self.assertEqual(first,sample_genres(source,3,'bigger',1000)[0])
        self.assertLessEqual(max(g['sampled'] for g in groups if g['genre']!='Unknown genre')-min(g['sampled'] for g in groups if g['genre']!='Unknown genre'),1)
        for size in (True,0,1001,'1000.0'):
            with self.assertRaises(ValueError):sample_genres(source,3,sample_size=size)

    def test_tags_are_separate_from_genres_and_missing_ratings(self):
        result=proposals({'rating':{'votes-count':0,'value':5},'tags':[{'name':'warmup','count':4},{'name':'spam','count':-1}]})
        self.assertIsNone(result['community_score']);self.assertIsNone(result['genre'])
        self.assertEqual(result['tags'],[{'name':'warmup','count':4}])

    def test_abandoned_batch_is_discoverable_and_launch_failure_is_recoverable(self):
        import app
        with tempfile.TemporaryDirectory() as temp,patch.object(app,'DATA',Path(temp)):
            saved=Store(Path(temp)/'workbench-sidecar.sqlite3');s=saved.save_snapshot(snapshot(),'Synthetic')
            batch=create_batch(saved,saved.snapshot(s['id']),sample_size=300)
            with saved.connection() as db:db.execute("UPDATE mb_batches SET status='running' WHERE id=?",(batch['id'],))
            client=app.app.test_client();headers={'X-Workbench-Token':app.TOKEN}
            rows=client.get('/api/lab/musicbrainz/batches').json['batches']
            self.assertEqual(rows[0]['status'],'interrupted')
            saved.set_setting('musicbrainz_enabled',True)
            with patch.object(app,'launch',side_effect=ValueError('Synthetic failed launch')):
                response=client.post('/api/lab/musicbrainz/'+batch['id']+'/start',json={'query_consent':True},headers=headers)
                self.assertEqual(response.status_code,400)
            self.assertEqual(client.get('/api/lab/musicbrainz/'+batch['id']).json['status'],'interrupted')


class DiscoveryExtensions(unittest.TestCase):
    def test_direct_mixed_case_master_is_read_from_a_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'library';source.mkdir();master=source/'MASTER.DB'
            with closing(sqlite3.connect(master)) as db:
                db.execute('CREATE TABLE djmdContent(ID TEXT,Title TEXT,FolderPath TEXT)')
                db.execute("INSERT INTO djmdContent VALUES ('1','Synthetic','/Music/test.mp3')")
                db.commit()
            before=master.read_bytes()
            self.assertIn('MASTER.DB',database_names(source))
            report=analyze_folder(str(master.resolve()),root/'result',lambda *_:None)
            self.assertEqual(report['read_status'],'checked',report)
            self.assertEqual(report['database']['counters']['tracks'],1);self.assertEqual(master.read_bytes(),before)
            self.assertFalse((source/'master.db-wal').exists())

    def test_ambiguous_case_requires_explicit_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'library';source.mkdir()
            (source/'master.db').write_bytes(b'one')
            if (source/'MASTER.DB').exists():self.skipTest('Case-insensitive filesystem')
            (source/'MASTER.DB').write_bytes(b'two')
            with self.assertRaisesRegex(ValueError,'Several differently cased'):
                analyze_folder(str(source.resolve()),root/'out',lambda *_:None)

    def test_legacy_primary_missing_and_xml_key_types_remain_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'legacy';source.mkdir();edb=source/'ExtData.edb';edb.write_bytes(b'synthetic')
            r=analyze_folder(str(edb.resolve()),root/'out',lambda *_:None)
            self.assertFalse(r['legacy_inspection']['primary_present']);self.assertIsNone(r['legacy_inspection']['track_count'])
            self.assertEqual(edb.read_bytes(),b'synthetic')
            xml=root/'v5.xml';xml.write_text('<DJ_PLAYLISTS><PRODUCT Version="5.8.6"/><COLLECTION><TRACK TrackID="1" Name="Song" Rating="52" Location="file://localhost/Music/a.mp3"/></COLLECTION><PLAYLISTS><NODE Name="Set" Type="1" KeyType="9"><TRACK Key="1"/></NODE></PLAYLISTS></DJ_PLAYLISTS>')
            r=analyze_folder(str(xml.resolve()),root/'xmlout',lambda *_:None)
            self.assertEqual(r['xml']['counters']['unresolved_playlist_references'],1)
            self.assertEqual(r['xml']['counters']['invalid_ratings'],1)


class LateralViewsTests(unittest.TestCase):
    def source(self):
        return {'id':'s','tracks':[{'id':'a','title':'A'},{'id':'b','title':'B'},{'id':'c','title':'C'}],
                'playlists':[{'id':'p','name':'Set','tracks':['a','a','gone']}],
                'histories':[{'id':'h','entries':[{'track_id':'a'},{'track_id':'a'},{'track_id':'b'}]},
                             {'id':'h2','entries':[{'track_id':'b'}]}],
                'capabilities':{'playlist_order':True,'history_details':True}}

    def test_playlist_repeats_missing_metadata_and_search_positions(self):
        result=playlist_contents(self.source(),'p')
        self.assertEqual(result['summary']['repeated_entries'],1)
        self.assertEqual(result['summary']['missing_metadata'],1)
        self.assertTrue(result['rows'][2]['missing_metadata'])
        self.assertEqual(playlist_contents(self.source(),'p','gone')['rows'][0]['sequence'],3)

    def test_recurring_counts_sessions_not_repeated_entries(self):
        s=self.source();before=deepcopy(s)
        self.assertEqual([r['track_id'] for r in collection_lenses(s,'recurring')['rows']],['b'])
        self.assertEqual([r['track_id'] for r in collection_lenses(s,'unfiled')['rows']],['b','c'])
        self.assertEqual(collection_lenses(s,'history_absent')['rows'][0]['track_id'],'c')
        self.assertEqual(s,before)
        s['capabilities']['history_details']=False
        with self.assertRaises(ValueError):collection_lenses(s,'recurring')


class ChartsAndSeratoTests(unittest.TestCase):
    def source(self):
        return {'id':'s','scope_key':'fixture','tracks':[
            {'id':'1','title':'Track 🎧','artist':'Artist','current_path':'file://localhost/C:/Music/a%20b.mp3'},
            {'id':'2','title':'Track 🎧 (Remix)','artist':'Artist','current_path':'C:/Music/remix.mp3'},
            {'id':'3','title':'Other','artist':'Artist','current_path':'D:/Other/track.flac'}],
            'playlists':[{'id':'p','name':'../Set%%unsafe','tracks':['2','1','missing']}],
            'capabilities':{'playlist_order':True}}

    def chart(self):
        return {'rows':[{'rank':1,'title':'Track 🎧','artist':'Artist'},{'rank':2,'title':'Other','artist':'Artist'}]}

    def test_chart_matching_does_not_silently_select_a_remix_or_duplicate(self):
        source=self.source();matched=match_chart(source,self.chart())
        self.assertEqual(matched['rows'][0]['status'],'exact_tags')
        source['tracks'].append({**source['tracks'][0],'id':'duplicate'})
        self.assertEqual(match_chart(source,self.chart())['rows'][0]['status'],'ambiguous')
        source['tracks']=[source['tracks'][1]]
        self.assertEqual(match_chart(source,self.chart())['rows'][0]['status'],'review_version')

    def test_m3u_uses_only_reviewed_candidates_in_chart_order(self):
        source=self.source();matched=match_chart(source,self.chart())
        content=chart_m3u(source,matched,[{'rank':2,'track_id':'3'},{'rank':1,'track_id':'1'}])
        self.assertLess(content.index('C:/Music/a b.mp3'),content.index('D:/Other/track.flac'))
        with self.assertRaises(ValueError):chart_m3u(source,matched,[{'rank':1,'track_id':'2'}])
        for path in ('https://example.com/a.mp3','/Music/a\n#EXTINF:bad','file://remote/Music/a.mp3','C:/Music/../secret.mp3'):
            with self.assertRaises(ValueError):local_audio_path(path)

    def test_chart_transport_is_bounded_cached_and_obeys_cooldown(self):
        class Response(BytesIO):
            headers={'X-RateLimit-Remaining':'0','X-RateLimit-Reset-In':'30'}
            status=200
        calls=[]
        def transport(request,timeout):
            calls.append(request.full_url)
            return Response(json.dumps({'payload':{'recordings':[{'track_name':'Track','artist_name':'Artist','listen_count':4}]}}).encode())
        client=ChartClient(transport,clock=lambda:10)
        self.assertEqual(client.fetch()['rows'][0]['title'],'Track')
        self.assertTrue(client.fetch()['cached']);self.assertEqual(len(calls),1)
        with self.assertRaises(ValueError):client.fetch('month')
        self.assertNotIn('Artist',calls[0])

    def test_serato_package_has_correct_nested_lengths_unicode_and_volume_paths(self):
        source=self.source();before=deepcopy(source);payload,manifest=draft_package(source,'C:/')
        self.assertEqual(manifest['tracks_written'],2);self.assertFalse(manifest['serato_import_verified'])
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            records=chunks(archive.read('_Serato_/database V2'))
            self.assertEqual(records[0][1].decode('utf-16-be'),'2.0/Serato Scratch LIVE Database')
            first=dict(chunks(records[1][1]))
            self.assertEqual(first['pfil'].decode('utf-16-be'),'Music/a b.mp3')
            self.assertEqual(first['tsng'].decode('utf-16-be'),'Track 🎧')
            name=next(n for n in archive.namelist() if n.endswith('.crate'))
            self.assertNotIn('../',name)
            crate=chunks(archive.read(name))
            self.assertEqual(crate[0][1].decode('utf-16-be'),'1.0/Serato ScratchLive Crate')
            self.assertEqual(dict(chunks(crate[1][1]))['ptrk'].decode('utf-16-be'),'Music/remix.mp3')
            self.assertEqual(manifest['crates'][0]['omitted_entries'],1)
        self.assertEqual(source,before)
        with self.assertRaises(ValueError):volume_relative('D:/Music/a.mp3','C:/')
        self.assertEqual(volume_relative('/Volumes/DJ/Music/a.mp3','/Volumes/DJ'),'Music/a.mp3')

    def test_chart_and_serato_api_require_explicit_actions(self):
        import app
        with tempfile.TemporaryDirectory() as temp,patch.object(app,'DATA',Path(temp)):
            saved=Store(Path(temp)/'workbench-sidecar.sqlite3');sid=saved.save_snapshot(self.source(),'Synthetic')['id']
            client=app.app.test_client();headers={'X-Workbench-Token':app.TOKEN}
            self.assertEqual(client.post('/api/intelligence/serato',json={'snapshot':sid,'volume_root':'C:/'},headers=headers).status_code,400)
            result=client.post('/api/intelligence/serato',json={'snapshot':sid,'volume_root':'C:/','draft_acknowledged':True},headers=headers)
            self.assertEqual(result.status_code,200);self.assertEqual(result.mimetype,'application/zip')
            self.assertEqual(client.post('/api/intelligence/chart',json={'snapshot':sid},headers=headers).status_code,400)
            with patch('intelligence_routes.ChartClient.fetch',return_value=self.chart()):
                result=client.post('/api/intelligence/chart',json={'snapshot':sid,'network_consent':True},headers=headers)
            self.assertEqual(result.status_code,200)
            response=client.post('/api/intelligence/chart/export',json={'report_id':result.json['report_id'],'reviewed':True,'selected':[{'rank':1,'track_id':'1'}]},headers=headers)
            self.assertEqual(response.status_code,200);self.assertIn(b'C:/Music/a b.mp3',response.data)


if __name__=='__main__':unittest.main()

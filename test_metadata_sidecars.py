"""Filename-only optional projections; source records and cloud state stay intact."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import app as application
from collection_views import duplicate_groups, sidecar_groups, statistics
from dj_insights import InsightIndex, ranking, bubbles, tonalities
from metadata_sidecars import enabled, is_name_sidecar, is_sidecar, select
from test_library_lab import snapshot, song
from test_support import workspace_client
from workbench_store import Store


def tracks():
    return [song('audio', current_path='/music/song.mp3', tonality='Am'),
            song('contents', current_path='/music/contents_123/song.mp3', tonality='Am'),
            song('apple', current_path=r'C:\Music\._song.mp3', tonality='Am'),
            song('ds', current_path=None, xml_location='file://localhost/music/.DS_Store', tonality='Am'),
            song('thumbs', current_path=None, filename='Thumbs.db', tonality='Am'),
            song('desktop', current_path=None, original_path=r'D:\Old\desktop.ini', tonality='Am'),
            song('unknown', title='.DS_Store', current_path=None, tonality='Am')]


class SidecarNames(unittest.TestCase):
    def test_only_known_leaf_patterns_match_without_opening_or_probing(self):
        for name in ['._track.mp3', '/music/.DS_Store', r'C:\Music\THUMBS.DB',
                     'file://localhost/C:/Music/%2EDS_Store', '/a/desktop.ini']:
            self.assertTrue(is_name_sidecar(name), name)
        for name in [None, '', 1, '._', '/metadata/.DS_Store/song.mp3', '/music/contents_123/song.mp3',
                     '/music/song._remix.mp3', '/music/desktop.ini.mp3', '/music/._folder/',
                     '/music/.DS_Store/']:
            self.assertFalse(is_name_sidecar(name), name)
        self.assertFalse(is_sidecar({'title': '.DS_Store', 'artist': '._DJ'}))
        self.assertTrue(is_sidecar({'xml_location': 'file://localhost/D:/Music/._song.mp3'}))
        self.assertFalse(is_sidecar({'current_path':'/contents_ID/Music/Cloud Song.mp3',
                                     'original_path':r'E:\Old\._Earlier.mp3'}))
        self.assertFalse(is_sidecar({'filename':'Cloud Song.mp3','current_path':'/music/._Old.mp3'}))
        self.assertTrue(is_sidecar({'filename':'._Cloud Song.mp3','current_path':'/music/Cloud Song.mp3'}))
        self.assertTrue(is_sidecar({'current_path':'/music/._Cloud Song.mp3','original_path':'/old/Cloud Song.mp3'}))

    def test_filter_is_opt_in_and_restorable_with_explicit_counts(self):
        original=tracks(); before=deepcopy(original)
        visible,summary=select(original)
        self.assertEqual(visible,original);self.assertEqual(summary['excluded'],0)
        visible,summary=select(original,'1')
        self.assertEqual([t['id'] for t in visible],['audio','contents','unknown'])
        self.assertEqual((summary['total'],summary['recognized'],summary['excluded']),(7,4,4))
        self.assertEqual(select(original,'0')[0],original);self.assertEqual(original,before)
        with self.assertRaises(ValueError):enabled('automatic')

    def test_statistics_and_all_insights_keep_sources_unchanged(self):
        source=snapshot(tracks()); before=deepcopy(source)
        for hidden,total in [(False,7),(True,3)]:
            result=statistics(source,hide_sidecars=hidden)
            self.assertEqual(result['counters']['total'],total)
            self.assertEqual(result['sidecars']['excluded'],4 if hidden else 0)
        index=InsightIndex(source)
        self.assertEqual(index.options(hide_sidecars=True)['entries'],3)
        args={'perspective':'all','hide_metadata_sidecars':'1'}
        ranked=ranking(index,args);self.assertEqual({r['id'] for r in ranked['rows']},{'audio','contents','unknown'})
        self.assertEqual(ranked['context']['sidecars']['excluded'],4)
        self.assertEqual(bubbles(index,args)['summary']['entries'],3)
        self.assertEqual(tonalities(index,args)['summary']['entries'],3)
        self.assertEqual(source,before)

    def test_duplicate_id_and_review_identity_survive_reversible_projection(self):
        rows=tracks()
        for row in rows:row.update(title='Same captured title',artist='Same artist')
        original=duplicate_groups(snapshot(rows),'metadata');before=deepcopy(original)
        filtered,summary=sidecar_groups(original,True)
        self.assertEqual(filtered[0]['id'],original[0]['id'])
        self.assertEqual([t['id'] for t in filtered[0]['tracks']],['audio','contents','unknown'])
        self.assertEqual(filtered[0]['count'],3);self.assertEqual(summary['excluded'],4)
        self.assertEqual(sidecar_groups(original,False)[0],original);self.assertEqual(original,before)

    def test_insight_cloud_facets_exclude_sidecars_and_restore_with_the_toggle(self):
        source=snapshot([song(identity,current_path=path,tonality='Am') for identity,path in [
            ('dropbox','/Dropbox/song.mp3'),('dropbox-sidecar','/Dropbox/._song.mp3'),
            ('drive','/Google Drive/My Drive/song.mp3'),('drive-sidecar','/Google Drive/My Drive/.DS_Store'),
            ('ordinary','/Music/contents_123/song.mp3'),('unknown',None)]])
        before=deepcopy(source);index=InsightIndex(source)
        for hidden in (False,True,False):
            expected={'all':4 if hidden else 6,'dropbox':1 if hidden else 2,
                      'google_drive':1 if hidden else 2,'other':1,'unknown':1}
            self.assertEqual(index.options(hide_sidecars=hidden)['cloud_counts'],expected)
            for provider,total in expected.items():
                stats=statistics(source,provider=provider,hide_sidecars=hidden)
                self.assertEqual(stats['cloud']['counts'],expected)
                self.assertEqual(stats['counters']['total'],total)
                args={'provider':provider,'perspective':'all','hide_metadata_sidecars':hidden}
                results=[ranking(index,args),bubbles(index,args),tonalities(index,args)]
                for result in results:
                    self.assertEqual(result['context']['provider_counts'],expected)
                    self.assertEqual(result.get('total',result.get('summary',{}).get('entries')),total)
                    self.assertEqual(result['context']['sidecars']['excluded'],
                                     (2 if provider=='all' else 1 if provider in ('dropbox','google_drive') else 0) if hidden else 0)
        self.assertEqual(source,before)


class SidecarAPIs(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        for name,value in [('DATA',self.root),('sessions',{}),('active',None),('tasks',{})]:
            p=patch.object(application,name,value);p.start();self.addCleanup(p.stop)
        self.store=Store(self.root/'workbench-sidecar.sqlite3')
        self.source=snapshot(tracks())
        for row in self.source['tracks']:row.update(title='Same captured title',artist='Same artist')
        self.sid=self.store.save_snapshot(self.source,'Synthetic sidecars')['id'];self.key='snapshot:'+self.sid
        self.before=deepcopy(self.store.snapshot(self.sid));self.client=workspace_client(application)

    def get(self,path,**query):
        result=self.client.get(path,query_string={'source':self.key,**query})
        self.assertEqual(result.status_code,200,result.json);return result.json

    def test_collection_queries_and_detail_filter_before_pagination_without_rewriting(self):
        self.assertEqual(self.get('/api/collection/statistics')['counters']['total'],7)
        stats=self.get('/api/collection/statistics',hide_metadata_sidecars='1')
        self.assertEqual(stats['counters']['total'],3)
        refs=self.get('/api/collection/references',hide_metadata_sidecars='1')
        self.assertEqual(refs['total'],3);self.assertEqual(refs['sidecars']['excluded'],4)
        original=self.get('/api/collection/duplicates',basis='metadata')['rows'][0]
        self.store.set_setting('duplicate_reviews:'+self.key,{original['id']:'keep_separate'})
        filtered=self.get('/api/collection/duplicates',basis='metadata',hide_metadata_sidecars='1')
        self.assertEqual((filtered['rows'][0]['id'],filtered['rows'][0]['count'],filtered['rows'][0]['review']),
                         (original['id'],3,'keep_separate'))
        detail=self.get('/api/collection/duplicates/'+original['id'],basis='metadata',hide_metadata_sidecars='1')
        self.assertEqual(detail['total'],3);self.assertEqual(self.store.snapshot(self.sid),self.before)
        self.assertEqual(self.get('/api/collection/references',hide_metadata_sidecars='0')['total'],7)

    def test_insight_options_rows_and_csv_share_filter(self):
        params={'snapshot':self.sid,'hide_metadata_sidecars':'1'}
        options=self.get('/api/insights/options',**params);self.assertEqual(options['entries'],3)
        ranked=self.get('/api/insights/tracks',perspective='all',**params)
        self.assertEqual(ranked['total'],3);self.assertEqual(ranked['context']['sidecars']['excluded'],4)
        csv=self.client.get('/api/insights/tracks.csv',query_string={**params,'perspective':'all'})
        self.assertEqual(csv.status_code,200)
        self.assertNotIn('apple,',csv.text);self.assertIn('contents,',csv.text)
        self.assertEqual(self.store.snapshot(self.sid),self.before)

    def test_file_health_uses_indexed_hints_and_preserves_unknown_legacy_rows(self):
        with self.store.connection() as db:
            db.execute('INSERT INTO file_health_scans (source,total,done,checked_at,state) VALUES (?,?,?,?,?)',(self.key,7,7,1,'complete'))
            for row in self.source['tracks']:
                # Old rows without a filename/flag are genuinely unknown; their
                # titles alone must never cause exclusion.
                sidecar=1 if row['id'] in ('apple','desktop') else None
                name='.DS_Store' if row['id']=='ds' else 'Thumbs.db' if row['id']=='thumbs' else ''
                db.execute('INSERT INTO file_health_records (source,track_id,title,artist,genre,status,checked_at,search_text,filename,metadata_sidecar) VALUES (?,?,?,?,?,?,?,?,?,?)',
                           (self.key,row['id'],row['title'],row['artist'],'House','unverified',1,row['title'],name,sidecar))
        with patch('file_health.cached_inspect',side_effect=AssertionError('A view filter must not scan files')):
            filtered=self.get('/api/file-health',hide_metadata_sidecars='1')
        self.assertEqual({r['track_id'] for r in filtered['rows']},{'audio','contents','unknown'})
        self.assertEqual((filtered['checked'],filtered['unchecked'],filtered['source_total'],filtered['sidecars']['excluded']),(3,0,7,4))
        with self.store.connection() as db:
            db.execute("UPDATE file_health_records SET metadata_sidecar=1,filename='Cloud Song.mp3' WHERE source=? AND track_id='unknown'",(self.key,))
        observed=self.get('/api/file-health',hide_metadata_sidecars='1')
        self.assertEqual({r['track_id'] for r in observed['rows']},{'audio','contents','unknown'})
        self.assertEqual(self.get('/api/file-health',hide_metadata_sidecars='0')['total'],7)
        self.assertEqual(self.store.snapshot(self.sid),self.before)

    def test_workspace_statistics_and_invalid_filters_remain_scoped(self):
        rows={r['id']:{**r,'track_id':r['id'],'duration_seconds':r['duration'],'october_xml':True,'grid_sha256':''} for r in self.source['tracks']}
        catalog=SimpleNamespace(tracks=rows,cue_summary=lambda _:{'total':0,'other':0,'auto':0})
        current={'id':'d'*32,'catalog':catalog,'metadata':{},'decisions':{},'relocations':{}}
        application.sessions[current['id']]=current;application.active=current['id']
        result=self.client.get('/api/statistics',query_string={'hide_metadata_sidecars':'1'})
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['counters']['total'],3);self.assertEqual(result.json['sidecars']['excluded'],4)
        for route,query in [('/api/statistics',{}),('/api/collection/references',{'source':self.key}),
                            ('/api/insights/tracks',{'snapshot':self.sid})]:
            bad=self.client.get(route,query_string={**query,'hide_metadata_sidecars':'automatic'})
            self.assertEqual(bad.status_code,400,bad.json)


if __name__=='__main__':unittest.main()

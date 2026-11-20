"""Cloud lenses use synthetic recorded paths, never cloud APIs or media reads."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import app as application
import cloud_analysis
from collection_views import statistics
from dj_insights import InsightIndex, ranking, bubbles, tonalities
from test_dj_insights import song
from test_support import workspace_client
from workbench_store import Store


def collection():
    return {'scope_key':'synthetic:cloud-analysis','source_kind':'Invented paths','tracks':[
        song('dropbox',current_path=r'C:\Users\tester\DJ team Dropbox\Customer\track.mp3'),
        song('drive',current_path='/home/tester/Google Drive/My Drive/track.mp3',genre='Techno'),
        song('both',current_path='/home/tester/Dropbox/a.mp3',original_path='/home/tester/GoogleDrive/b.mp3',duration=600),
        song('ordinary',current_path='/Music/Dropbox.mp3'),
        song('custom',current_path='E:/Old/track.mp3'),
        song('unknown',current_path=None,genre=None,duration=None),
    ],'capabilities':{},'playlists':[]}


class CloudLensUnitTests(unittest.TestCase):
    def test_lexical_labels_do_not_probe_paths_or_turn_filename_into_provider(self):
        config={'roots':[], 'mappings':[{'recorded_root':'E:/Old','local_root':'/offline/Dropbox/Relocated'}]}
        tracks=collection()['tracks'];before=deepcopy(tracks)
        with patch.object(Path,'stat',side_effect=AssertionError('No filesystem probes')),patch.object(Path,'open',side_effect=AssertionError('No media reads')):
            selected,cloud=cloud_analysis.select(tracks,'dropbox',config)
        self.assertEqual([t['id'] for t in selected],['dropbox','both','custom'])
        self.assertEqual(cloud['counts'],{'all':6,'dropbox':3,'google_drive':2,'other':1,'unknown':1})
        self.assertEqual(cloud['selected_counts']['google_drive'],1)
        self.assertEqual(tracks,before)
        for value in ('../Dropbox/track.mp3','/Music/../Dropbox/track.mp3','smb://server/Dropbox/a.mp3'):
            self.assertEqual(cloud_analysis.classify({'current_path':value}),{'providers':0,'provider_checked':False})

    def test_custom_roots_are_component_bounded_and_windows_insensitive(self):
        config={'roots':[{'kind':'dropbox','root':'C:/Music','provider_verified':True},
                         {'kind':'google_drive','root':'/Custom/Drive','provider_verified':False}]}
        self.assertEqual(cloud_analysis.classify({'current_path':'c:/MUSIC/sub/a.mp3'},config)['providers'],1)
        self.assertEqual(cloud_analysis.classify({'current_path':'C:/MusicExtra/a.mp3'},config)['providers'],0)
        self.assertEqual(cloud_analysis.classify({'current_path':'/Custom/Drive/a.mp3'},config)['providers'],2)
        self.assertEqual(cloud_analysis.classify({'current_path':'/custom/drive/a.mp3'},config)['providers'],0)

    def test_statistics_filter_conserves_histograms_and_keeps_unknown_separate(self):
        source=collection();before=deepcopy(source)
        result=statistics(source,provider='google_drive',hide=True)
        self.assertEqual(result['counters']['total'],2)
        self.assertEqual(result['counters']['dropbox_paths'],1)
        self.assertEqual(result['counters']['google_drive_paths'],2)
        self.assertEqual(result['cloud']['counts']['unknown'],1)
        self.assertEqual(sum(r['count'] for r in result['histogram']),2)
        self.assertEqual(statistics(source,minimum=300,provider='dropbox')['counters']['total'],1)
        unknown=statistics(source,provider='unknown',hide=True)
        self.assertEqual(unknown['counters']['total'],1)
        self.assertEqual(unknown['unknown_duration'],1)
        self.assertEqual(source,before)
        with self.assertRaises(ValueError):statistics(source,provider='local')

    def test_every_insight_lens_and_csv_projection_share_cloud_scope(self):
        source=collection();before=deepcopy(source);index=InsightIndex(source)
        args={'provider':'dropbox','perspective':'all','dimension':'genre'}
        rows=ranking(index,args)
        self.assertEqual({t['id'] for t in rows['rows']},{'dropbox','both'})
        self.assertEqual(rows['context']['provider_counts']['google_drive'],2)
        self.assertEqual(bubbles(index,args)['summary']['entries'],2)
        self.assertEqual(tonalities(index,args)['summary']['entries'],2)
        self.assertEqual(ranking(index,{'provider':'unknown','perspective':'all'})['total'],1)
        self.assertEqual(index.options()['cloud_counts']['other'],2)
        self.assertNotIn('C:\\Users',json.dumps(rows))
        self.assertNotIn('/home/tester',json.dumps(rows))
        self.assertEqual(source,before)
        with self.assertRaises(ValueError):ranking(index,{'provider':'bad'})


class CloudLensApiTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        for key,value in (('DATA',self.root),('active',None),('sessions',{}),('tasks',{})):
            patched=patch.object(application,key,value);patched.start();self.addCleanup(patched.stop)
        patched=patch('cloud_analysis.provider_context',return_value=[]);patched.start();self.addCleanup(patched.stop)
        self.store=Store(self.root/'workbench-sidecar.sqlite3');self.saved=self.store.save_snapshot(collection(),'Invented cloud paths')
        self.identity=self.saved['id'];self.source='snapshot:'+self.identity;self.client=workspace_client(application)
        application.clear_insight_cache()

    def get(self,path,**values):
        response=self.client.get(path,query_string=values)
        self.assertEqual(response.status_code,200,response.json)
        return response

    def test_xml_zip_statistics_uses_same_provider_scope_and_keeps_source_unchanged(self):
        tracks={t['id']:{**t,'track_id':t['id'],'duration_seconds':t['duration'],'grid_sha256':'synthetic',
                         'october_xml':t['id']!='both'} for t in collection()['tracks']}
        catalog=SimpleNamespace(tracks=tracks,cue_summary=lambda identity:{'auto':0,'other':1,'total':1})
        session={'id':'a'*32,'name':'Invented XML and ZIP','catalog':catalog,'metadata':{}}
        before=deepcopy(tracks)
        with patch.object(application,'sessions',{session['id']:session}),patch.object(application,'active',session['id']):
            result=self.get('/api/statistics',provider='dropbox',cohort='xml').json
            self.assertEqual(result['counters']['total'],1)
            self.assertEqual(result['counters']['dropbox_paths'],1)
            self.assertEqual(result['counters']['google_drive_paths'],0)
            self.assertEqual(sum(row['count'] for row in result['histogram']),1)
            invalid=self.client.get('/api/statistics',query_string={'provider':'bad'})
            self.assertEqual(invalid.status_code,400)
        self.assertEqual(tracks,before)

    def test_stats_cache_changes_when_saved_audio_mapping_changes(self):
        path='/api/collection/statistics';query={'source':self.source,'provider':'dropbox'}
        first=self.get(path,**query);self.assertEqual(first.json['counters']['total'],2)
        self.assertEqual(self.get(path,**query).headers['X-Workbench-Cache'],'hit')
        self.store.set_setting('audio_paths:synthetic:cloud-analysis',[{'recorded_root':'E:/Old','local_root':'/offline/Dropbox/Relocated'}])
        moved=self.get(path,**query)
        self.assertEqual(moved.headers['X-Workbench-Cache'],'miss')
        self.assertEqual(moved.json['counters']['total'],3)
        self.assertEqual(self.store.snapshot(self.identity)['tracks'],collection()['tracks'])

    def test_attached_root_is_source_scoped_and_index_cache_refreshes(self):
        args={'snapshot':self.identity,'provider':'dropbox','perspective':'all'}
        self.assertEqual(self.get('/api/insights/tracks',**args).json['total'],2)
        self.store.set_setting('dropbox_mapping',{'source':'snapshot:other','scope_key':'other','local_root':'E:/Old'})
        self.assertEqual(self.get('/api/insights/tracks',**args).json['total'],2)
        self.store.set_setting('dropbox_mapping',{'source':self.source,'scope_key':'synthetic:cloud-analysis','local_root':'E:/Old'})
        self.assertEqual(self.get('/api/insights/tracks',**args).json['total'],3)
        self.assertEqual(self.get('/api/insights/bubbles',**args).json['summary']['entries'],3)
        self.assertEqual(self.get('/api/insights/tonality',**args).json['summary']['entries'],3)
        csv=self.get('/api/insights/tracks.csv',**args).get_data(as_text=True)
        self.assertIn('custom',csv);self.assertNotIn('ordinary',csv)
        self.assertEqual(self.client.get('/api/insights/tracks',query_string={**args,'provider':'bad'}).status_code,400)

    def test_duplicate_provider_filter_keeps_other_siblings_visible(self):
        snapshot=collection();snapshot['tracks'][3].update(title=snapshot['tracks'][0]['title'],artist=snapshot['tracks'][0]['artist'])
        identity=self.store.save_snapshot(snapshot,'Invented candidate group')['id'];source='snapshot:'+identity
        rows=self.get('/api/collection/duplicates',source=source,basis='metadata',provider='dropbox').json
        self.assertEqual(rows['total'],1);group=rows['rows'][0]
        self.assertEqual(group['count'],2)
        detail=self.get('/api/collection/duplicates/'+group['id'],source=source,basis='metadata').json
        self.assertEqual({t['id'] for t in detail['rows']},{'dropbox','ordinary'})
        refs=self.get('/api/collection/references',source=source,provider='google_drive').json
        self.assertEqual({t['id'] for t in refs['rows']},{'drive','both'})
        self.assertEqual(self.client.get('/api/collection/references',query_string={'source':source,'provider':'bad'}).status_code,400)


if __name__=='__main__':unittest.main()

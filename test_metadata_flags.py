"""Zero metadata is not missing metadata or proof of an empty physical file."""
from copy import deepcopy
import csv
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app
from dj_insights import InsightIndex,ranking
from metadata_export import track
from test_dj_insights import song
from track_flags import flags
from workbench_store import Store


class MetadataFlagTests(unittest.TestCase):
    def test_explicit_zero_unknown_and_unavailable_audio_are_independent(self):
        for value in (None,'',False,'unknown',float('nan'),-1):
            self.assertEqual(flags({'duration':value,'size':value}),[])
        for value in (0,0.0,'0','0.0'):
            self.assertEqual(flags({'duration':value,'size':value}),['zero_duration','zero_size'])
        row=track({'duration':0,'size_bytes':0,'current_path':'D:/Unavailable.wav'})
        self.assertEqual(flags(row),['zero_duration','zero_size'])
        self.assertIsNone(track({})['size'])

    def test_four_dj_views_use_explainable_known_metadata(self):
        rows=[song('missing',bpm=None,tonality='Am'),
              song('played',play_count=8,manual_cues=0,rating=2,tonality='Am'),
              song('favourite',play_count=0,manual_cues=0,rating=4,tonality='Am'),
              song('long',duration=600,tonality='Am'),
              song('unknown',play_count=None,manual_cues=None,rating=None,duration=None,tonality='Am'),
              song('normal',duration=599,tonality='Am')]
        snapshot={'tracks':rows,'captured':'2026-11-16'};before=deepcopy(snapshot);index=InsightIndex(snapshot)
        expected={'missing_mix':['missing'],'played_unprepared':['played'],
                  'favourites_prepare':['favourite'],'long_tracks':['long']}
        for mode,ids in expected.items():
            result=ranking(index,{'perspective':mode})
            self.assertEqual([r['id'] for r in result['rows']],ids)
            self.assertTrue(result['rows'][0]['reason'])
        self.assertEqual(snapshot,before)

    def test_duplicate_and_dj_flags_filter_before_pagination_and_export(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'DATA',Path(tmp)):
            store=Store(Path(tmp)/'workbench-sidecar.sqlite3');rows=[]
            for i in range(60):
                for sibling in (0,1):
                    rows.append(song(f'{i:03}-{sibling}',current_path=f'E:/Music/{i}.wav',
                        duration=0 if i>=58 and sibling==1 else None if i==0 else 240,
                        size=0 if i==59 and sibling==1 else None if i==0 else 1000,tonality='Am'))
            sid=store.save_snapshot({'scope_key':'test:flags','tracks':rows,'playlists':[]},'Flag fixture')['id']
            before=store.snapshot(sid);client=app.app.test_client();source='snapshot:'+sid
            result=client.get('/api/collection/duplicates',query_string={'source':source,'flag':'zero_duration'})
            self.assertEqual(result.status_code,200,result.json);self.assertEqual(result.json['total'],2)
            self.assertEqual(result.json['flag_counts'],{'zero_duration':2,'zero_size':1})
            group=result.json['rows'][-1]['id']
            detail=client.get('/api/collection/duplicates/'+group,query_string={'source':source}).json
            self.assertEqual(detail['total'],2)  # Healthy sibling stays available for comparison.
            self.assertEqual(sum('zero_duration' in r['flags'] for r in detail['rows']),1)
            self.assertEqual(client.get('/api/collection/duplicates',query_string={'source':source,'flag':'invalid'}).status_code,400)
            args={'snapshot':sid,'perspective':'all','quality':'zero_size','sort':'title','direction':'desc'}
            result=client.get('/api/insights/tracks',query_string=args)
            self.assertEqual(result.status_code,200,result.json)
            self.assertEqual([r['id'] for r in result.json['rows']],['059-1'])
            self.assertEqual(result.json['quality_counts'],{'zero_duration':2,'zero_size':1})
            with patch('track_playback.available_audio',side_effect=AssertionError('Metadata filters must not probe files')):
                downloaded=client.get('/api/insights/tracks.csv',query_string=args)
            data=list(csv.DictReader(StringIO(downloaded.data.decode('utf-8-sig'))))
            self.assertEqual([r['id'] for r in data],['059-1']);self.assertEqual(data[0]['size'],'0')
            self.assertEqual(client.get('/api/insights/tracks',query_string={**args,'quality':'bad'}).status_code,400)
            self.assertEqual(store.snapshot(sid),before)


if __name__=='__main__':unittest.main()

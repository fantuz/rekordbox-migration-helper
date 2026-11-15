"""Synthetic local-only MusicBrainz quick-target selection contracts."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import app as application
from musicbrainz_pilot import sample_genres,target_options,create_batch
from workbench_store import Store


class EnrichmentTargetTests(unittest.TestCase):
    def setUp(self):
        self.tracks=[
          {'id':str(i),'title':'Track '+str(i),'artist':'DJ '+str(i%3),
           'genre':'House' if i%2 else 'Techno',
           'album':'Album A' if i%3 else 'Album B',
           'year':2022 if i%4 else 2024,
           'duration':180+i,'isrc':''} for i in range(240)]
        self.tracks[0].update(genre='',album='',year=None)
        self.snapshot={'id':'a'*32,'tracks':self.tracks,
                       'playlists':[{'id':'p','name':'Late set','tracks':[str(i) for i in (10,20,30)]}],
                       'capabilities':{'playlist_membership':True}}

    def test_targets_respect_saved_genre_album_year_and_playlist(self):
        options=target_options(self.snapshot)
        self.assertTrue(any(x['value']=='House' for x in options['genres']))
        self.assertTrue(any(x['value']=='Album B' for x in options['albums']))
        self.assertTrue(any(x['value']=='2022' for x in options['years']))
        self.assertEqual(options['playlists'][0]['value'],'p')
        for kind,value,assertion in (
            ('genre','House',lambda t:t['genre']=='House'),
            ('album','Album A',lambda t:t['album']=='Album A'),
            ('year','2022',lambda t:t['year']==2022),
            ('playlist','p',lambda t:t['id'] in {'10','20','30'}),
            ('missing_genre','',lambda t:not t.get('genre')),
            ('missing_album','',lambda t:not t.get('album')),
            ('missing_year','',lambda t:not t.get('year'))):
            with self.subTest(kind=kind):
                selected,groups=sample_genres(self.snapshot,5,'repeat',150,kind,value)
                self.assertTrue(selected)
                self.assertTrue(all(assertion(t) for t in selected))
                self.assertEqual(groups[0]['sampled'],len(selected))

    def test_random_is_deterministic_and_not_genre_balanced(self):
        a,_=sample_genres(self.snapshot,5,'seed-one',150,'random')
        b,_=sample_genres(self.snapshot,5,'seed-one',150,'random')
        c,_=sample_genres(self.snapshot,5,'seed-two',150,'random')
        self.assertEqual([x['id'] for x in a],[x['id'] for x in b])
        self.assertNotEqual([x['id'] for x in a],[x['id'] for x in c])
        self.assertEqual(len(a),150)
        for bad,value in [('unknown',''),('genre','not-a-genre'),('playlist','wrong'),('year','2000')]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):sample_genres(self.snapshot,5,'seed',150,bad,value)

    def test_batch_summary_captures_target_without_provider_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'sidecar.sqlite3')
            saved=store.save_snapshot(self.snapshot,'Synthetic lookup')
            record=create_batch(store,store.snapshot(saved['id']),sample_size=150,target='playlist',target_value='p')
            self.assertEqual(record['summary']['target'],'playlist')
            self.assertEqual(record['summary']['target_value'],'p')
            self.assertEqual(record['summary']['tracks'],3)
            self.assertEqual(record['status'],'preview')

    def test_local_read_only_target_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(application,'DATA',Path(tmp)):
                store=Store(Path(tmp)/'workbench-sidecar.sqlite3')
                saved=store.save_snapshot(self.snapshot,'Target source')
                result=application.app.test_client().get('/api/lab/musicbrainz/targets',
                                                            query_string={'snapshot':saved['id']})
                self.assertEqual(result.status_code,200,result.json)
                self.assertEqual(result.json['total_tracks'],240)
                self.assertNotIn('current_path',str(result.json))
                self.assertEqual(application.app.test_client().get('/api/lab/musicbrainz/targets',
                                        query_string={'snapshot':'../../etc'}).status_code,400)


if __name__=='__main__':unittest.main()

"""Synthetic duplicate evidence checks for both library review entry points."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import app as application
from collection_views import duplicate_groups, sidecar_groups
from duplicate_evidence import isrc_key, recorded_comparisons
from pair_query import page
from test_engine import catalog
from test_support import workspace_client
from workbench_store import Store


def saved_tracks():
    return [
        {'id': 'a', 'title': 'Original mix', 'artist': 'DJ A', 'isrc': 'us-abc-24-00123',
         'duration': 240, 'size': 4000, 'current_path': '/Music/a.wav'},
        {'id': 'b', 'title': 'Club edit', 'artist': 'DJ A', 'isrc': 'USABC2400123',
         'duration': 243, 'size': 7000, 'current_path': 'file://localhost/D:/Music/b.flac'},
    ]


class DuplicateEvidenceTests(unittest.TestCase):
    def test_positive_evidence_requires_known_values_and_differences_are_explicit(self):
        tracks = saved_tracks()
        first = recorded_comparisons(tracks)
        self.assertEqual(first['duration_spread'], 3)
        self.assertEqual({key for key, found in first['evidence'].items() if found},
                         {'isrc_agrees', 'duration_differs', 'size_differs', 'extension_differs'})
        tracks[1].update(duration=242, size='4000', isrc='GBXYZ2100321', current_path='D:/Music/b.WAV')
        second = recorded_comparisons(tracks)
        self.assertEqual(second['duration_spread'], 2)
        self.assertEqual({key for key, found in second['evidence'].items() if found},
                         {'isrc_differs', 'duration_close', 'size_agrees'})
        tracks[1].update(duration=0, size=True, isrc='not captured', current_path='spotify:track:123')
        missing = recorded_comparisons(tracks)
        self.assertIsNone(missing['duration_spread'])
        self.assertFalse(any(missing['evidence'].values()))
        for invalid in ('', 'USABC240012', 'uſABC2400123', 'ßABC2400123', 123, None):
            self.assertIsNone(isrc_key(invalid))

    def test_retained_sidecar_projection_keeps_identity_and_recalculates_evidence(self):
        tracks = saved_tracks()
        tracks[1].update(duration=241, size=4000, current_path='/Music/b.wav')
        sidecar = {**tracks[1], 'id': 'metadata-sidecar', 'duration': 5, 'size': 20,
                   'current_path': '/Music/._b.wav'}
        original = duplicate_groups({'tracks': [*tracks, sidecar]}, 'isrc')
        filtered, _ = sidecar_groups(original, True)
        self.assertEqual(original[0]['id'], filtered[0]['id'])
        self.assertEqual(original[0]['count'], 3)
        self.assertEqual(filtered[0]['count'], 2)
        self.assertTrue(original[0]['evidence']['duration_differs'])
        self.assertTrue(filtered[0]['evidence']['duration_close'])
        self.assertTrue(filtered[0]['evidence']['size_agrees'])

    def test_workspace_pair_criteria_intersect_and_groups_use_only_matching_edges(self):
        cat, _ = catalog([], [])
        cat.tracks['c'] = dict(cat.tracks['b'])
        cat.cues['c'] = []
        for identity, duration, size, key in (
            ('a', 240, 4000, 'USABC2400123'), ('b', 242, 4000, 'USABC2400123'), ('c', 245, 7000, 'GBXYZ2100321'),
        ):
            cat.tracks[identity].update(track_id=identity, title='Track', artist='DJ A', duration_seconds=duration,
                                        size_bytes=size, isrc=key, current_path='/Music/' + identity + '.wav',
                                        preview_sha256=None, grid_sha256=None)
        cat.pairs = {'a~b': {'id': 'a~b', 'a': 'a', 'b': 'b'}, 'b~c': {'id': 'b~c', 'a': 'b', 'b': 'c'}}
        cat.refresh_counts()
        session = {'catalog': cat, 'decisions': {}}
        filters = {'view': 'groups', 'evidence': 'duration_differs,size_differs,isrc_differs'}
        result = page(session, filters, application.in_scope, application.media_evidence)
        self.assertEqual(result['rows'][0]['track_ids'], ['b', 'c'])
        self.assertEqual(result['rows'][0]['pair_ids'], ['b~c'])
        self.assertEqual(result['facets']['size_agrees'], 1)
        self.assertEqual(result['facets']['size_differs'], 1)
        self.assertFalse(application.in_scope(session, cat.descriptions['a~b'], filters))
        self.assertTrue(application.in_scope(session, cat.descriptions['b~c'], filters))
        contradictory = page(session, {'evidence': 'duration_close,duration_differs'},
                             application.in_scope, application.media_evidence)
        self.assertEqual(contradictory['total'], 0)
        self.assertEqual(session['decisions'], {})

    def test_snapshot_criteria_filter_preserves_siblings_and_saves_source_scoped_review(self):
        tracks = saved_tracks()
        with TemporaryDirectory() as directory, patch.object(application, 'DATA', Path(directory)):
            store = Store(Path(directory) / 'workbench-sidecar.sqlite3')
            snapshot = store.save_snapshot({'tracks': tracks, 'playlists': [], 'source_kind': 'test'}, 'Recorded group')
            source = 'snapshot:' + snapshot['id']
            client = workspace_client(application)
            query = {'source': source, 'basis': 'isrc', 'criterion': 'duration_differs', 'q': 'USABC2400123'}
            url = '/api/collection/duplicates'
            response = client.get(url, query_string=query)
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(response.json['total'], 1)
            identity = response.json['rows'][0]['id']
            self.assertEqual(client.get(url, query_string={**query, 'criterion': 'duration_close'}).json['total'], 0)
            for invalid in ({'criterion': 'unknown'}, {'review_status': 'unknown'}, {'basis': 'unknown'}):
                self.assertEqual(client.get(url, query_string={**query, **invalid}).status_code, 400)
            detail = client.get(url + '/' + identity, query_string=query).json
            self.assertEqual([item['title'] for item in detail['rows']], ['Original mix', 'Club edit'])
            review = client.post(url + '/' + identity + '/review',
                                 json={'source': source, 'basis': 'isrc', 'status': 'keep_separate'},
                                 headers={'X-Workbench-Token': application.TOKEN})
            self.assertEqual(review.status_code, 200, review.json)
            self.assertFalse(review.json['source_writes'])
            self.assertEqual(client.get(url, query_string={**query, 'review_status': 'keep_separate'}).json['total'], 1)
            self.assertEqual(client.get(url, query_string={**query, 'review_status': 'unreviewed'}).json['total'], 0)
            self.assertEqual(store.snapshot(snapshot['id'])['tracks'], tracks)


if __name__ == '__main__':
    unittest.main()

"""Reference grouping and quick searches over synthetic, inaccessible paths."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import app as application
from test_support import workspace_client
from workbench_store import Store


class ReferenceViewsTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.enterContext(patch.multiple(application, DATA=root, active=None, sessions={}))
        self.enterContext(patch('cloud_analysis.provider_context', return_value=[]))
        self.store = Store(root / 'workbench-sidecar.sqlite3')
        self.client = workspace_client(application)

    def source(self, tracks, analysis_captured=False):
        saved = self.store.save_snapshot(
            {'tracks': tracks, 'playlists': [],
             'capabilities': {'analysis_references': analysis_captured}}, 'Synthetic references'
        )
        return 'snapshot:' + saved['id']

    def get(self, source, **query):
        response = self.client.get('/api/collection/references', query_string={'source': source, **query})
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def test_grouped_pages_keep_collection_counts_and_case_rules(self):
        tracks = [
            {'id': str(index), 'title': f'Title {index:03}', 'current_path': f'/Volumes/Crate/{index}.mp3'}
            for index in range(51)
        ]
        tracks.extend([
            {'id': 'posix-distinct', 'title': 'A title', 'current_path': '/Volumes/crate/alias.mp3'},
            {'id': 'windows-first', 'title': 'B title', 'current_path': 'D:/Dance/a.mp3'},
            {'id': 'windows-second', 'title': 'C title', 'current_path': 'd:/dance/b.mp3'},
        ])
        source = self.source(tracks)
        for grouping in ('folder', 'volume'):
            first = self.get(source, group_by=grouping, sort='title', direction='desc')
            last = self.get(source, group_by=grouping, sort='title', direction='desc', offset=50)
            self.assertEqual(first['total'], 54)
            self.assertEqual([row['id'] for row in first['rows']], [str(i) for i in range(50, 0, -1)])
            self.assertEqual([row['group']['count'] for row in last['rows']], [51, 1, 2, 2])
            self.assertEqual(last['rows'][0]['group'], first['rows'][0]['group'])

    def test_quick_search_distinguishes_recorded_evidence_from_unavailable_fields(self):
        tracks = [
            {'id': 'main', 'current_path': 'D:/Music/Track.WAV',
             'original_path': '/Volumes/Archive/Track.wav', 'analysis_path': '/PIONEER/ANLZ0000.DAT'},
            {'id': 'Alias', 'current_path': 'd:\\music\\track.wav',
             'original_path': 'file://localhost/D:/Music/Track.WAV', 'analysis_path': '/PIONEER/ANLZ0000.EXT'},
            {'id': 'blank', 'current_path': ''},
            {'id': 'network', 'current_path': 'file://server/library/Track.wav',
             'original_path': '//server/library/Track.wav', 'analysis_path': '/PIONEER/ANLZ0001.DAT'},
            {'id': 'relative', 'current_path': './Track.ogg', 'analysis_path': '/PIONEER/ANLZ0002.DAT'},
            {'id': 'posix', 'current_path': '/Library/Track.wav', 'analysis_path': '/PIONEER/ANLZ0003.DAT'},
        ]
        source = self.source(tracks, analysis_captured=True)
        full = self.get(source, group_by='platform')
        kinds = {row['id']: row['group']['key'] for row in full['rows']}
        self.assertEqual(kinds, {'main': 'windows_drive', 'Alias': 'windows_drive', 'blank': 'unknown',
                                 'network': 'network_share', 'relative': 'unrecognized', 'posix': 'posix'})
        self.assertEqual(full['counts'],
                         {'all': 6, 'changed': 1, 'missing_path': 1, 'shared_path': 2,
                          'missing_analysis': 1, 'cross_platform': 1})
        formats = self.get(source, group_by='format')
        waves = [row['group'] for row in formats['rows'] if row['group']['label'] == 'WAV']
        self.assertEqual(waves, [{'key': 'WAV', 'label': 'WAV', 'count': 4, 'translated': False}] * 4)
        shared = self.get(source, mode='shared_path', q='alias', group_by='format')
        self.assertEqual([row['id'] for row in shared['rows']], ['Alias'])
        self.assertEqual(shared['rows'][0]['group']['label'], 'WAV')
        self.assertEqual(shared['rows'][0]['flags'], ['shared_path'])
        self.assertEqual(self.get(source, mode='cross_platform')['rows'][0]['id'], 'main')
        self.assertEqual(self.get(source, mode='missing_analysis')['rows'][0]['id'], 'blank')
        uncaptured = self.get(self.source(tracks), mode='missing_analysis')
        self.assertIsNone(uncaptured['counts']['missing_analysis'])
        self.assertEqual(uncaptured['total'], 0)

    def test_cloud_group_uses_recorded_path_hints(self):
        tracks = [
            {'id': 'dual', 'current_path': '/Users/User/Dropbox/one.mp3',
             'original_path': '/Users/User/Google Drive/one.mp3'},
            {'id': 'drive', 'current_path': '/Users/User/Google Drive/two.mp3'},
            {'id': 'local', 'current_path': '/Users/User/Music/Dropbox.mp3'},
        ]
        source = self.source(tracks)
        grouped = self.get(source, group_by='cloud', provider='google_drive')
        self.assertEqual({row['id']: row['group']['key'] for row in grouped['rows']},
                         {'dual': 'multiple', 'drive': 'google_drive'})
        self.assertEqual(grouped['cloud']['counts']['dropbox'], 1)
        self.assertEqual(grouped['counts']['all'], 2)
        for query in ({'group_by': '_not_a_group_'}, {'mode': '_not_a_filter_'}):
            response = self.client.get('/api/collection/references', query_string={'source': source, **query})
            self.assertEqual(response.status_code, 400)

    def test_workspace_browser_reads_sources_and_leaves_reference_staging_untouched(self):
        track = {'track_id': 'a', 'title': 'A track', 'current_path': 'D:/New/a.mp3',
                 'original_path': 'C:/Old/a.mp3', 'xml_location': 'file://localhost/C:/Old/a.mp3',
                 'size_bytes': 100000}
        catalog = SimpleNamespace(tracks={'a': track}, cues={'a': []}, metadata={},
                                  cue_summary=lambda _: {'other': 0, 'auto': 0})
        session = {'id': 'b' * 32, 'name': 'Reference test', 'catalog': catalog,
                   'relocations': {'a': 'file://localhost/D:/Reviewed/a.mp3'}}
        with patch.object(application, 'current', return_value=session):
            result = self.get('workspace', q='file://localhost/C:/Old', mode='changed')
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['rows'][0]['xml_location'], track['xml_location'])
        self.assertEqual(result['rows'][0]['size'], 100000)
        self.assertEqual(session['relocations'], {'a': 'file://localhost/D:/Reviewed/a.mp3'})

"""Recorded totals and local observations remain separately scoped."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import app as application
from audio_paths import validate as validate_audio_paths
from cloud_analysis import select_with_evidence
from cloud_file_evidence import refresh_download
from collection_storage import recorded_storage
from test_support import workspace_client
from workbench_store import Store


class RecordedStorageTests(TestCase):
    def test_expected_sizes_skip_bad_counts_and_deduplicate_consistent_paths(self):
        tracks = [
            {'current_path': 'C:/Music/Audio.mp3', 'size': 20},
            {'current_path': 'file:///c:/MUSIC/audio.mp3', 'size': '20'},
            {'current_path': '//Server/Share/Audio.mp3', 'size': 15},
            {'current_path': 'file://server/share/audio.mp3', 'size': 15},
            {'current_path': '/Music/Audio.mp3', 'size': 30},
            {'current_path': '/Music/audio.mp3', 'size': 40},
            {'current_path': '/Music/audio.mp3', 'size': 60},
            {'current_path': '/Dropbox/a.mp3', 'original_path': '/Google Drive/a.mp3', 'size': 50},
            {'current_path': 'https://music.apple.com/example', 'size': 0},
            {'current_path': 'spotify:track:example', 'size': 300},
            {'current_path': '/Gaps/missing.mp3', 'size': True},
            {'current_path': '/Gaps/fraction.mp3', 'size': 1.1},
            {'current_path': '/Gaps/large.mp3', 'size': 2**53},
        ]
        with patch.object(Path, 'stat', side_effect=AssertionError('Never stat audio from recorded data')):
            selected, _ = select_with_evidence(tracks)
            result = recorded_storage(selected)
        self.assertEqual(result['recorded'], {'bytes': 550, 'known': 9, 'total': 13})
        self.assertEqual(result['unique_paths'], {'bytes': 115, 'known': 4, 'total': 8, 'conflicts': 1})
        self.assertEqual(result['cloud'], {'bytes': 50, 'known': 1, 'total': 1})
        self.assertEqual(result['streaming'], {'bytes': 300, 'known': 1, 'total': 2})


class StorageObservationTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        profile = self.root / 'profile'
        folder = self.root / 'Dropbox'
        folder.mkdir()
        mappings = validate_audio_paths(
            [{'recorded_root': 'R:/Legacy', 'local_root': str(folder)}], [self.root])
        self.current = self.root / 'current.mp3'
        self.current.write_bytes(b'1234')
        alternate = self.root / 'alternate.mp3'
        alternate.write_bytes(b'123')
        mapped = folder / 'mapped.mp3'
        mapped.write_bytes(b'1234567')
        placeholder = folder / 'online.mp3'
        placeholder.write_bytes(b'123456')
        self.tracks = [
            {'id': 'current', 'duration': 60, 'current_path': str(self.current), 'size': 7},
            {'id': 'alternate', 'duration': 240, 'current_path': str(self.root / 'missing.mp3'),
             'original_path': str(alternate), 'size': 3},
            {'id': 'mapped', 'duration': 240, 'current_path': 'R:/Legacy/mapped.mp3', 'size': 5},
            {'id': 'online', 'duration': 240, 'current_path': str(placeholder), 'size': 6},
            {'id': 'unknown', 'duration': 240, 'current_path': str(self.root / 'unknown.mp3'), 'size': 0},
        ]
        self.store = Store(profile / 'workbench-sidecar.sqlite3')
        self.source = 'snapshot:' + self.store.save_snapshot(
            {'scope_key': 'synthetic:storage-observations', 'tracks': self.tracks},
            'Storage observations')['id']
        self.store.set_setting('audio_paths:synthetic:storage-observations', mappings)

        def execute(job, _message):
            job(lambda *_: None)
            return 'storage-scan-job'

        for target, value in [('DATA', profile), ('active', None), ('sessions', {}),
                              ('tasks', {}), ('launch', execute)]:
            substitute = patch.object(application, target, value)
            substitute.start()
            self.addCleanup(substitute.stop)
        cloud_roots = patch('cloud_analysis.provider_context', return_value=[])
        cloud_roots.start()
        self.addCleanup(cloud_roots.stop)
        self.client = workspace_client(application)

    def statistics(self, **query):
        response = self.client.get('/api/collection/statistics', query_string={'source': self.source, **query})
        self.assertEqual(response.status_code, 200, response.json)
        return response

    def scan(self, force=True):
        with patch('media.cloud_placeholder', side_effect=lambda info: info.st_size == 6):
            response = self.client.post('/api/file-health/scan', json={'source': self.source, 'force': force},
                                        headers={'X-Workbench-Token': application.TOKEN})
        self.assertEqual(response.status_code, 200, response.json)

    def test_stats_reuse_scan_only_for_selected_tracks_and_update_after_transfer(self):
        before = self.statistics()
        self.assertEqual(before.json['storage']['observed'], {'state': 'not_started'})
        self.assertEqual(self.statistics().headers['X-Workbench-Cache'], 'hit')
        self.scan()
        with patch('track_playback.inspect_audio_details', side_effect=AssertionError('Statistics must not probe audio')):
            result = self.statistics()
            self.assertEqual(result.headers['X-Workbench-Cache'], 'miss')
            observed = result.json['storage']['observed']
            self.assertEqual((observed['checked'], observed['total'], observed['state']), (5, 5, 'complete'))
            locations = observed['locations']
            self.assertEqual(locations['current']['bytes'], 4)
            self.assertEqual(locations['current']['recorded_bytes'], 7)
            self.assertEqual(locations['current']['mismatches'], 1)
            self.assertEqual(locations['alternate']['bytes'], 3)
            self.assertEqual(locations['mapped']['bytes'], 7)
            self.assertEqual(locations['placeholder']['bytes'], 6)
            self.assertEqual(result.json['storage']['cloud'], {'bytes': 11, 'known': 2, 'total': 2})
            scoped = self.statistics(min='2', provider='dropbox').json['storage']['observed']
            self.assertEqual((scoped['checked'], scoped['total']), (2, 2))
            self.assertIsNone(scoped['locations']['current']['bytes'])

        self.current.write_bytes(b'1234567')
        mappings = self.store.setting('audio_paths:synthetic:storage-observations')
        refresh_download(application.DATA, self.source, 'current', self.tracks[0], mappings)
        changed = self.statistics()
        self.assertEqual(changed.headers['X-Workbench-Cache'], 'miss')
        current = changed.json['storage']['observed']['locations']['current']
        self.assertEqual((current['bytes'], current['mismatches']), (7, 0))

    def test_legacy_or_changed_mapping_cannot_authorize_observed_sizes(self):
        with self.store.connection() as db:
            db.execute('INSERT INTO file_health_scans (source,total,done,checked_at,state) VALUES (?,?,?,?,?)',
                       (self.source, len(self.tracks), len(self.tracks), 1, 'complete'))
        self.assertEqual(self.statistics().json['storage']['observed'], {'state': 'legacy'})
        self.scan(force=False)
        self.assertEqual(self.statistics().json['storage']['observed']['state'], 'complete')
        self.store.set_setting('audio_paths:synthetic:storage-observations', [])
        self.assertEqual(self.statistics().json['storage']['observed'], {'state': 'mapping_changed'})

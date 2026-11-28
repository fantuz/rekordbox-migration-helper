"""Exercise the application’s existing task, authorization and saved-report interfaces together."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import app as application
from workbench_store import Store


class CleanupRouteTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(TemporaryDirectory())
        data = Path(folder)
        for name, value in [('DATA', data), ('sessions', {}), ('tasks', {}), ('task_controls', {}), ('active', None),
                            ('executor', SimpleNamespace(submit=lambda callback: callback()))]:
            self.enterContext(patch.object(application, name, value))
        self.store = Store(data / 'workbench-sidecar.sqlite3')
        self.source = self.snapshot('Original')
        self.client = application.app.test_client()
        self.token = {'X-Workbench-Token': application.TOKEN}
        self.remote = {'REMOTE_ADDR': '192.0.2.3'}

    def snapshot(self, label):
        paths = ['C:/Users/dj/Dropbox/Library/song.wav', '/Volumes/DJ/Audio/two.wav', '/Volumes/DJ/Audio/three.wav']
        tracks = [dict(id=str(i), current_path=p, title='Title ' + str(i), size=42) for i, p in enumerate(paths)]
        payload = dict(schema=1, scope_key='fixture:' + label, tracks=tracks, playlists=[], capabilities={})
        return 'snapshot:' + self.store.save_snapshot(payload, label)['id']

    def test_authorized_scan_scoped_filters_and_local_tasks(self):
        base = '/api/collection-cleanup'
        body = {'source': self.source}
        self.assertEqual(self.client.post(base + '/scan', json=body).status_code, 403)
        self.assertEqual(self.client.post(base + '/scan', headers=self.token, json=body,
                                          environ_overrides=self.remote).status_code, 403)
        created = self.client.post(base + '/scan', headers=self.token, json=body)
        self.assertEqual(created.status_code, 200, created.json)
        url = '/api/tasks/' + created.json['job']
        self.assertEqual(self.client.get(url, environ_overrides=self.remote).status_code, 403)
        self.assertEqual(self.client.post(url + '/cancel', headers=self.token, environ_overrides=self.remote).status_code, 403)
        job = self.client.get(url).json
        self.assertEqual(job['status'], 'complete', job)
        report = job['result']['id']
        scoped_url = base + '/' + report
        listed = self.client.get(base, query_string=body).json['reports']
        self.assertEqual([r['id'] for r in listed], [report])
        self.assertIn('incomplete_capture', listed[0]['summary']['gates'])
        filtered = self.client.get(scoped_url, query_string={**body, 'candidate':'protected', 'volume':'/Volumes/DJ',
                                                             'os':'macOS', 'offset':1, 'limit':1}).json
        self.assertEqual(filtered['total'], 2)
        self.assertEqual([r['id'] for r in filtered['rows']], ['2'])
        cloud = self.client.get(scoped_url, query_string={**body, 'status':'cloud', 'q':'TITLE 0'}).json
        self.assertEqual([r['id'] for r in cloud['rows']], ['0'])
        self.assertEqual(self.client.get(scoped_url, query_string={**body, 'limit':101}).status_code, 400)
        other = {'source': self.snapshot('Other')}
        self.assertEqual(self.client.get(base, query_string=other).json['reports'], [])
        self.assertEqual(self.client.get(scoped_url, query_string=other).status_code, 404)
        self.assertEqual(self.client.get(scoped_url, query_string=body, environ_overrides=self.remote).status_code, 403)

    def test_saved_report_filters_combine_evidence_and_recorded_size(self):
        rows = [
            dict(id='proof', section='duplicate', reasons=[], signals=['same_name_size'],
                 proof='sha256', recorded_size=1048576, observed_size=1048576),
            dict(id='conflict', section='protected', reasons=['size_conflict'], signals=['same_name_size'],
                 proof=None, recorded_size=1048576, observed_size=2097152),
            dict(id='unknown', section='protected', reasons=['unknown_metadata'], signals=['same_name_size']),
        ]
        report = self.store.save_report('collection cleanup', [self.source[9:]], {},
                                        [{**row, 'track_id':row['id']} for row in rows])
        url = '/api/collection-cleanup/' + report['id']

        def matches(**filters):
            response = self.client.get(url, query_string={'source':self.source, **filters})
            self.assertEqual(response.status_code, 200, response.json)
            return [row['id'] for row in response.json['rows']]

        self.assertEqual(matches(signal='same_name_size'), ['proof', 'conflict', 'unknown'])
        self.assertEqual(matches(signal='same_name_size', size_min='0'), ['proof', 'conflict'])
        self.assertEqual(matches(reason='size_conflict', candidate='protected', size_min='1048576',
                                 size_max='1048576'), ['conflict'])
        self.assertEqual(matches(proof='sha256', candidate='duplicate'), ['proof'])
        self.assertEqual(matches(reason='size_conflict', candidate='eligible'), [])
        self.assertEqual(matches(reason='size'), [])
        self.assertEqual(matches(size_max='1048575'), [])
        self.assertEqual(matches(size_min='1048577'), [])
        for invalid in ({'size_min':'2','size_max':'1'}, {'size_min':'-1'}, {'size_max':'9223372036854775808'},
                        {'size_min':'5.5'}):
            response = self.client.get(url, query_string={'source':self.source, **invalid})
            self.assertEqual(response.status_code, 400, response.json)

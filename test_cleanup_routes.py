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

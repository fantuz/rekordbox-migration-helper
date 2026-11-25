"""Native path-to-snapshot regression using the public cleanup web endpoints and generated WAVs."""
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
import wave
from xml.etree import ElementTree as ET

from flask import Flask

import cleanup_routes
from cleanup_paths import _windows_volume
from workbench_store import Store
from xml_analysis import analyze_xml


def _temporary_parent():
    # Windows hosted builds can place TEMP on a secondary drive. macOS defaults to
    # /var, an intentionally unclassified recorded path; use the startup Data volume.
    if sys.platform == 'darwin':
        return Path('/System/Volumes/Data/private/tmp')
    base = Path(tempfile.gettempdir())
    return Path(os.environ['SystemRoot']) / 'Temp' if os.name == 'nt' and base.drive.upper() != _windows_volume() else base


def _audio():
    stream = BytesIO()
    with wave.open(stream, 'wb') as wav:
        wav.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\x10\x00' * 1024)
    return stream.getvalue()


class NativeCleanupWorkflow(unittest.TestCase):
    def test_review_copy_and_return_to_the_original_snapshot(self):
        with tempfile.TemporaryDirectory(dir=_temporary_parent()) as tmp:
            home = Path(tmp)
            env = {'APPDATA': str(home), 'LOCALAPPDATA': str(home)}
            with patch.object(Path, 'home', return_value=home), patch.dict(os.environ, env), \
                 patch('cleanup_paths._windows_music', return_value=str(home / 'Music')), \
                 patch('cleanup_paths._registered_roots', return_value=[]):
                self.exercise(home)

    def exercise(self, home):
        data = home / 'Workbench'
        store = Store(data / 'workbench-sidecar.sqlite3')
        xml = ET.Element('DJ_PLAYLISTS')
        collection = ET.SubElement(xml, 'COLLECTION', Entries='4')
        audio = _audio()
        files = {}
        for identity, folder, title in [('1', 'Shelf A', 'Mix'), ('2', 'Shelf B', 'Mix'),
                                       ('3', 'Shelf C', 'Missing'), ('4', 'Team Dropbox', 'Cloud')]:
            path = home / 'Music' / folder / (title + '.wav')
            path.parent.mkdir(parents=True)
            path.write_bytes(audio)
            files[identity] = path
            ET.SubElement(collection, 'TRACK', TrackID=identity, Location=path.as_uri(), Name=title,
                          Artist='Fixture', Size=str(len(audio)), Rating='0', PlayCount='0')
        ET.SubElement(xml, 'PLAYLISTS')
        document = ET.tostring(xml, encoding='utf-8')
        xml_file = home / 'source.xml'
        xml_file.write_bytes(document)
        capture = home / uuid4().hex
        analyze_xml(xml_file, capture, lambda *_: None)
        meta = store.save_snapshot(json.loads((capture / 'comparison.json').read_text()), 'Fixture library')
        parent = meta['id']
        original = store.snapshot(parent)
        parked = home / 'temporarily relocated.wav'
        files['3'].rename(parked)
        jobs = {}
        callback = []

        def launch(work, label, *, local_only):
            self.assertTrue(local_only)
            def tick(n, status):
                if n == 99 and callback:
                    callback.pop()()
            key = uuid4().hex
            jobs[key] = work(tick)
            return key

        app = Flask(__name__)
        app.config['TESTING'] = True
        cleanup_routes.register(SimpleNamespace(app=app, DATA=data, lock=RLock(), launch=launch))
        client = app.test_client()
        source = 'snapshot:' + parent

        def post(endpoint, **kwargs):
            return client.post('/api/collection-cleanup/' + endpoint, json={'source': source, **kwargs})

        def run(endpoint, **kwargs):
            response = post(endpoint, **kwargs)
            self.assertEqual(response.status_code, 200, response.data)
            return jobs[response.json['job']]

        def scan(compare):
            identity = run('scan', compare_bytes=compare, local_only=compare)['id']
            result = client.get('/api/collection-cleanup/' + identity, query_string={'source': source})
            self.assertEqual(result.status_code, 200, result.data)
            return identity, result.json

        native = sys.platform in ('win32', 'darwin')
        report_id, report = scan(native)
        rows = {r['id']: r for r in report['rows']}
        self.assertEqual(rows['4']['status'], 'cloud')
        self.assertTrue(rows['4']['protected'])
        selected = {'report_id': report_id, 'selected_ids': ['2','3']}
        if native:
            self.assertEqual(report['summary']['counts']['eligible'], 2, rows)
            self.assertEqual((rows['2']['proof'], rows['2']['keeper_id']), ('sha256', '1'))
            self.assertEqual(rows['3']['candidate'], 'missing')
            preview = run('preview', **selected)
            self.assertEqual(preview['confirmation'], 'COPY 2')
            confirm = dict(confirmation='COPY 2', original_computer=True, local_only=True)
            # Reconnect the recording after the full reread, just before final publication.
            callback.append(lambda: parked.rename(files['3']))
            failed = post('apply', **selected, **confirm, token=preview['token'])
            self.assertEqual(failed.status_code, 409, failed.data)
            self.assertEqual(len(store.snapshots()), 1)
            files['3'].rename(parked)
            selected['report_id'], _ = scan(True)
            preview = run('preview', **selected)
            result = run('apply', **selected, **confirm, token=preview['token'])
            self.assertFalse(result['source_writes'])
            self.assertEqual(result['parent_snapshot_id'], parent)
            copy = store.snapshot(result['snapshot_id'])
            self.assertEqual({t['id'] for t in copy['tracks']}, {'1','4'})
            self.assertEqual(copy['cleanup_lineage']['parent_digest'], meta['digest'])
        else:
            self.assertFalse(report['summary']['can_apply'])
            self.assertEqual(report['summary']['counts']['eligible'], 0)
            self.assertEqual(post('preview', **selected).status_code, 403)
            self.assertEqual(post('apply', **selected, token='0'*32, original_computer=True,
                                  local_only=True, confirmation='COPY 2').status_code, 403)
            self.assertEqual(len(store.snapshots()), 1)
        self.assertEqual(store.snapshot(parent), original)
        self.assertEqual(xml_file.read_bytes(), document)
        self.assertFalse(files['3'].exists())
        for path in (parked, files['1'], files['2'], files['4']):
            self.assertEqual(path.read_bytes(), audio)

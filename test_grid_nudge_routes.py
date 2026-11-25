from contextlib import closing
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import shutil
import stat
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import zipfile

from file_workflow import archive_index_digest, fingerprint_inputs, pair_signature
from grid_nudge_routes import _read_siblings
from native_export import mutable_copy
from test_grid_nudge_fixture import create_grid_fixture, grid_files
from test_support import workspace_client


class GridNudgeRouteTests(TestCase):
    def setUp(self):
        import app as owner
        self.owner = owner
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.source = create_grid_fixture(root / 'inputs')
        self.master = root / 'private' / 'example' / 'master.db'
        self.master.parent.mkdir(parents=True)
        shutil.copyfile(self.source['master'], self.master)
        self.meta = {'xml_path': str(self.source['xml']), 'zip_path': str(self.source['backup'])}
        self.record_identity()
        self.track = {'analysis_path': self.source['analysis_path'], 'title': 'Night Signal', 'artist': 'Studio Example'}
        self.session = {'id': 'example', 'metadata': self.meta,
                        'catalog': SimpleNamespace(tracks={self.source['track_id']: self.track})}
        for name, value in dict(active='example', sessions={'example': self.session}, DATA=root,
                                TEMPORARY=SimpleNamespace(path=root / 'private')).items():
            override = patch.object(owner, name, value)
            override.start()
            self.addCleanup(override.stop)
        self.client = workspace_client(owner)
        self.inputs = dict(session_id='example', track_id=self.source['track_id'], offset_ms=1)

    def record_identity(self):
        self.meta['input_fingerprints'] = fingerprint_inputs(self.meta)
        self.meta['pair_signature'] = pair_signature(self.source['backup'], self.source['xml'])

    def post(self, op, **params):
        return self.client.post('/api/lab/grid-nudge/' + op, json={**self.inputs, **params},
                                headers={'X-Workbench-Token': self.owner.TOKEN})

    def test_compare_download_exact_bytes_and_untouched_sources(self):
        inputs = [self.source[k] for k in ('backup', 'xml', 'master')] + [self.master]
        before = [sha256(p.read_bytes()).digest() for p in inputs]
        for offset in (-1, 1):
            with self.subTest(offset=offset):
                preview = self.post('preview', offset_ms=offset)
                self.assertEqual(preview.status_code, 200, preview.json)
                self.assertEqual((preview.json['first_ms'], preview.json['beats']), (125, 2))
                changed = {row['name'] for row in preview.json['files'] if row['changed']}
                self.assertEqual(changed, {'ANLZ0000.DAT', 'ANLZ0000.EXT'})
                download = self.post('download', offset_ms=offset, proof=preview.json['proof'])
                self.assertEqual(download.status_code, 200)
                self.assertIn('analysis-grid-nudge.zip', download.headers['Content-Disposition'])
                with zipfile.ZipFile(BytesIO(download.data)) as result:
                    self.assertEqual({n: result.read(n) for n in result.namelist()}, grid_files(offset, clear_mirror=True))
                download.close()
        self.assertEqual([sha256(p.read_bytes()).digest() for p in inputs], before)

    def test_picker_workspace_search_and_limit(self):
        self.session['catalog'].tracks.update({str(i): {**self.track, 'title': 'Song 🥁'} for i in range(70)})
        self.session['catalog'].tracks['no-analysis'] = {'title': 'Invisible'}
        def search(**params):
            return self.client.get('/api/lab/grid-nudge/tracks', query_string={'session_id': 'example', **params})
        page = search(q='🥁').json
        self.assertEqual(len(page['tracks']), 50)
        self.assertTrue(page['has_more'])
        self.assertEqual(search(q='signal').json['tracks'], [{'id': '701', 'title': 'Night Signal', 'artist': 'Studio Example'}])
        self.assertFalse(search(q='Invisible').json['tracks'])
        self.assertEqual(search(session_id='previous').status_code, 409)
        self.assertEqual(search(q='x' * 201).status_code, 400)

    def test_rejects_invalid_input_ambiguous_track_and_replayed_previews(self):
        for invalid in (True, 0, 2, '1', 1.25):
            self.assertEqual(self.post('preview', offset_ms=invalid).status_code, 400)
        self.assertEqual(self.post('download').status_code, 400)
        self.assertEqual(self.post('preview', track_id='other').status_code, 400)
        self.assertEqual(self.post('preview', session_id='previous').status_code, 409)
        proof = self.post('preview').json['proof']
        self.assertEqual(self.post('download', offset_ms=-1, proof=proof).status_code, 409)
        self.session['_workspace_generation'] = 'newly loaded'
        self.assertEqual(self.post('download', proof=proof).status_code, 409)
        self.session['catalog'].tracks['other'] = {**self.track, 'analysis_path': self.track['analysis_path'].lower()}
        self.assertIn('Multiple catalog', self.post('preview').json['error'])

    def test_rechecks_zip_and_native_registry_after_preview(self):
        proof = self.post('preview').json['proof']
        with closing(mutable_copy(self.master)) as db:
            db.execute("UPDATE contentFile SET Hash='stale' WHERE Path LIKE '%.EXT'")
            db.commit()
        self.assertIn('checksum', self.post('download', proof=proof).json['error'])
        with zipfile.ZipFile(self.source['backup'], 'a') as archive:
            archive.writestr('unexpected-file', 'added')
        self.assertIn('changed', self.post('preview').json['error'])
        self.meta['input_fingerprints'] = fingerprint_inputs(self.meta)
        self.assertIn('backup directory changed', self.post('preview').json['error'])

    def test_requires_original_paired_xml_and_every_registered_companion(self):
        proof = self.post('preview').json['proof']
        with self.source['xml'].open('a') as stream:
            stream.write(' ')
        self.assertIn('changed', self.post('download', proof=proof).json['error'])
        backup = self.source['backup']
        with zipfile.ZipFile(backup) as archive:
            entries = [(i.filename, archive.read(i)) for i in archive.infolist() if not i.filename.endswith('.2EX')]
        with zipfile.ZipFile(backup, 'w') as archive:
            for name, content in entries:
                archive.writestr(name, content)
        self.record_identity()
        self.assertIn('companion is missing', self.post('preview').json['error'])

    def test_native_registration_missing_duplicate_and_unassigned(self):
        with closing(mutable_copy(self.master)) as db:
            db.execute("INSERT INTO contentFile SELECT 'other', replace(lower(Path), '/',char(92)), Size,Hash,0 "
                       "FROM contentFile WHERE Path LIKE '%.3EX'")
            db.commit()
        self.assertIn('More than one native', self.post('preview').json['error'])
        with closing(mutable_copy(self.master)) as db:
            db.execute("DELETE FROM contentFile WHERE Path LIKE '%.3EX'")
            db.commit()
        self.assertIn('Unassigned', self.post('preview').json['error'])
        with closing(mutable_copy(self.master)) as db:
            db.execute("UPDATE contentFile SET Path=replace(Path,'.2EX','.3EX') WHERE Path LIKE '%.2EX'")
            db.commit()
        self.assertIn('checksum', self.post('preview').json['error'])

    def test_scoped_inventory_matches_full_path_and_checks_all_siblings(self):
        ref = 'usbanlz/p001/000002bd/anlz0000.dat'
        base = 'share/PIONEER/USBANLZ/P001/000002BD/'
        dat = base + 'ANLZ0000.DAT'
        def read(entries):
            buf = BytesIO()
            with zipfile.ZipFile(buf, 'w') as z:
                for name, data in entries:
                    z.writestr(name, data)
            with zipfile.ZipFile(buf) as z:
                # Existing recorded workspace signatures must survive the incremental implementation.
                legacy = json.dumps([(i.filename, i.file_size, i.CRC) for i in z.infolist()], ensure_ascii=False).encode()
                self.assertEqual(archive_index_digest(z), sha256(legacy).hexdigest())
                return _read_siblings(z, ref)
        self.assertEqual(read([(dat, b'ours'), (dat.replace('000002BD', 'other'), b'other'),
                               ('music/🎧.wav', b'x')]), {'DAT': b'ours'})
        link = zipfile.ZipInfo(base + 'ANLZ0000.EXT')
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for other in (base + 'anlz0000.dat', base + 'ANLZ0000.4EX',
                      dat.replace('share/', '').replace('.DAT', '.EXT'), link):
            with self.subTest(member=other), self.assertRaises(ValueError):
                read([(dat, b'one'), (other, b'two')])

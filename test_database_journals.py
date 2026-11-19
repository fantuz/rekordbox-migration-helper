"""Generated database/WAL pairs: recover commits, reject unsafe pairs first."""
from contextlib import closing
from hashlib import sha256
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from analyzer import snapshot_database
from research_capture import open_capture


def hashes(root):
    return {p.name: sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}


class PrivateWalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def capture(self, encrypted=False, page_size=4096, name='source'):
        source = self.root / name
        source.mkdir()
        path = source / 'master.db'
        if encrypted:
            from native_export import mutable_copy
            writer = mutable_copy(path)
        else:
            writer = sqlite3.connect(path)
            writer.execute(f'PRAGMA page_size={page_size}')
        self.addCleanup(writer.close)
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('CREATE TABLE proof(value TEXT)')
        writer.commit()
        writer.execute("INSERT INTO proof VALUES ('latest committed value')")
        writer.commit()
        self.assertGreater((source / 'master.db-wal').stat().st_size, 32)
        before = hashes(source)
        private = self.root / (name + '-private')
        snapshot_database(source, private, lambda *_: None)
        self.assertEqual(hashes(source), before)
        return source, private, before

    def test_plain_and_encrypted_wal_commits_survive_without_source_connections(self):
        for encrypted in (False, True):
            with self.subTest(encrypted=encrypted):
                source, private, before = self.capture(encrypted, name=str(encrypted))
                # Every reader receives only the app's detached copy. The
                # immutable encrypted probe also ignores the copied WAL.
                from engine import open_master
                with patch('engine.open_master', wraps=open_master) as base_probe:
                    with closing(open_capture(private / 'master.db')) as reader:
                        self.assertEqual([tuple(row) for row in reader.execute('SELECT value FROM proof').fetchall()],
                                         [('latest committed value',)])
                        self.assertEqual(reader.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                    self.assertEqual(base_probe.call_count, int(encrypted))
                    if encrypted:
                        self.assertEqual(base_probe.call_args.args, ((private / 'master.db').resolve(),))
                self.assertEqual(hashes(source), before)

    def test_page_size_mismatch_is_rejected_before_wal_aware_plain_or_cipher_reader(self):
        _, other, _ = self.capture(page_size=8192, name='other-size')
        foreign_wal = (other / 'master.db-wal').read_bytes()
        for encrypted in (False, True):
            with self.subTest(encrypted=encrypted):
                source, private, before = self.capture(encrypted, name=str(encrypted))
                (private / 'master.db-wal').write_bytes(foreign_wal)
                if encrypted:
                    from sqlcipher3 import dbapi2 as cipher
                    with patch('native_export.mutable_copy', side_effect=AssertionError('unsafe WAL reader')) as recovery:
                        with patch.object(cipher, 'connect', wraps=cipher.connect) as connections:
                            with self.assertRaisesRegex(ValueError, 'page sizes differ'):
                                open_capture(private / 'master.db')
                            recovery.assert_not_called()
                            self.assertEqual(connections.call_count, 1)
                            self.assertEqual(connections.call_args.args,
                                             ((private / 'master.db').resolve().as_uri() + '?mode=ro&immutable=1',))
                else:
                    with patch('research_capture.sqlite3.connect', side_effect=AssertionError('unsafe WAL reader')) as recovery:
                        with self.assertRaisesRegex(ValueError, 'page sizes differ'):
                            open_capture(private / 'master.db')
                        recovery.assert_not_called()
                self.assertEqual(hashes(source), before)

    def test_invalid_or_truncated_wal_headers_never_reach_a_native_reader(self):
        source, private, before = self.capture()
        wal = private / 'master.db-wal'
        valid = wal.read_bytes()
        malformed = [b'partial', b'X' * 32, valid[:8] + (513).to_bytes(4, 'big') + valid[12:]]
        for payload in malformed:
            with self.subTest(header=payload[:12]):
                wal.write_bytes(payload)
                with patch('research_capture.sqlite3.connect', side_effect=AssertionError('unsafe WAL reader')) as recovery:
                    with self.assertRaisesRegex(ValueError, 'WAL.*(header|page size)'):
                        open_capture(private / 'master.db')
                    recovery.assert_not_called()
        self.assertEqual(hashes(source), before)

    def test_incomplete_trailing_frame_preserves_the_last_committed_prefix(self):
        source, private, before = self.capture()
        with (private / 'master.db-wal').open('ab') as stream:
            stream.write(b'incomplete uncommitted frame')
        with closing(open_capture(private / 'master.db')) as reader:
            self.assertEqual(reader.execute('SELECT value FROM proof').fetchone()[0], 'latest committed value')
        self.assertEqual(hashes(source), before)

    def test_ambiguous_nonempty_journals_require_a_fresh_capture(self):
        for encrypted in (False, True):
            with self.subTest(encrypted=encrypted):
                source, private, before = self.capture(encrypted, name=str(encrypted))
                journal = private / 'master.db-journal'
                journal.write_bytes(b'capture interrupted')
                with patch('engine.open_master', side_effect=AssertionError('unexpected reader')) as probe:
                    with patch('research_capture.sqlite3.connect', side_effect=AssertionError('unexpected reader')) as plain:
                        with patch('native_export.mutable_copy', side_effect=AssertionError('unexpected reader')) as cipher:
                            with self.assertRaisesRegex(ValueError, 'both a WAL and a rollback journal'):
                                open_capture(private / 'master.db')
                            probe.assert_not_called()
                            plain.assert_not_called()
                            cipher.assert_not_called()
                # An empty leftover journal cannot replay a different base file.
                journal.write_bytes(b'')
                with closing(open_capture(private / 'master.db')) as reader:
                    self.assertEqual(reader.execute('SELECT value FROM proof').fetchone()[0], 'latest committed value')
                self.assertEqual(hashes(source), before)

    def test_65536_byte_database_header_encoding_is_supported(self):
        source, private, before = self.capture(page_size=65536)
        with closing(open_capture(private / 'master.db')) as reader:
            self.assertEqual(reader.execute('PRAGMA page_size').fetchone()[0], 65536)
            self.assertEqual(reader.execute('SELECT count(*) FROM proof').fetchone()[0], 1)
        self.assertEqual(hashes(source), before)

    def test_empty_wal_is_valid_before_the_first_write(self):
        path = self.root / 'master.db'
        with closing(sqlite3.connect(path)) as database:
            database.execute('CREATE TABLE proof(value TEXT)')
            database.commit()
        path.with_name(path.name + '-wal').write_bytes(b'')
        with closing(open_capture(path)) as database:
            self.assertEqual(database.execute('SELECT count(*) FROM proof').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()

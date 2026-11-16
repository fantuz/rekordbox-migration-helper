from test_support import workspace_client
"""Journal activity monitoring never reads or alters the active database."""
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import sqlite3
import tempfile
import unittest

import app as application
from analyzer import analyze_folder


class JournalActivityTests(unittest.TestCase):
    def test_monitor_detects_wal_and_base_changes_without_database_connection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'source';root.mkdir()
            with closing(sqlite3.connect(root/'master.db')) as db:
                db.execute('CREATE TABLE synthetic(value TEXT)')
                db.commit()
            data=Path(temp)/'work'
            captured=analyze_folder(root,data/'analyzers'/('f'*32),lambda *_:None)
            original=(root/'master.db').read_bytes()
            with patch.object(application,'DATA',data):
                client=workspace_client(application)
                uri='/api/analyzer/'+('f'*32)+'/journal-status'
                initial=client.get(uri);self.assertEqual(initial.status_code,200,initial.json)
                self.assertTrue(initial.json['supported']);self.assertFalse(initial.json['changed'])
                self.assertFalse(initial.json['wal_present'])
                wal=root/'master.db-wal';wal.write_bytes(b'file activity only, not a valid commit')
                changed=client.get(uri);self.assertTrue(changed.json['changed'])
                self.assertTrue(changed.json['wal_present'])
                self.assertNotEqual(initial.json['signature'],changed.json['signature'])
                wal.unlink()
                back=client.get(uri);self.assertEqual(back.json['signature'],initial.json['signature'])
                self.assertFalse(back.json['changed'])
                self.assertEqual(client.get('/api/analyzer/invalid/journal-status').status_code,404)
            self.assertEqual((root/'master.db').read_bytes(),original)


if __name__=='__main__':
    unittest.main()

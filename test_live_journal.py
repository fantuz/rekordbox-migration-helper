from test_support import workspace_client
"""Journal activity monitoring never reads or alters the active database."""
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import json
import os
import sqlite3
import tempfile
import unittest

import app as application
from analyzer import analyze_folder


class JournalActivityTests(unittest.TestCase):
    def capture(self, temporary):
        root=Path(temporary)/'source';root.mkdir()
        database=root/'master.db'
        with closing(sqlite3.connect(database)) as db:
            db.execute('CREATE TABLE synthetic(value TEXT)')
            db.execute("INSERT INTO synthetic VALUES ('before')")
            db.commit()
        data=Path(temporary)/'work'
        output=data/'analyzers'/('f'*32)
        analyze_folder(root,output,lambda *_:None)
        return database,data,output/'report.json'

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

    def test_monitor_accepts_saved_reports_without_new_identity_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            database,data,report=self.capture(temporary)
            saved=json.loads(report.read_text(encoding='utf-8'))
            for row in saved['source_files']:
                row.pop('device',None)
                row.pop('ctime_ns',None)
            report.write_text(json.dumps(saved),encoding='utf-8')
            before=database.read_bytes()
            with patch.object(application,'DATA',data):
                client=workspace_client(application)
                response=client.get('/api/analyzer/'+('f'*32)+'/journal-status')
                self.assertEqual(response.status_code,200,response.json)
                self.assertTrue(response.json['supported'])
                self.assertFalse(response.json['changed'])
                database.with_name('master.db-wal').write_bytes(b'new activity')
                self.assertTrue(client.get('/api/analyzer/'+('f'*32)+'/journal-status').json['changed'])
            self.assertEqual(database.read_bytes(),before)

    def test_monitor_detects_restored_mtime_when_change_time_is_available(self):
        with tempfile.TemporaryDirectory() as temporary:
            database,data,_=self.capture(temporary)
            before=database.stat()
            with closing(sqlite3.connect(database)) as writer:
                writer.execute("UPDATE synthetic SET value='after!'")
                writer.commit()
            os.utime(database,ns=(before.st_atime_ns,before.st_mtime_ns))
            after=database.stat()
            self.assertEqual((after.st_size,after.st_mtime_ns,after.st_ino),
                             (before.st_size,before.st_mtime_ns,before.st_ino))
            if after.st_ctime_ns==before.st_ctime_ns:
                self.skipTest('The platform does not expose a changed file timestamp')
            content=database.read_bytes()
            with patch.object(application,'DATA',data):
                response=workspace_client(application).get('/api/analyzer/'+('f'*32)+'/journal-status')
                self.assertEqual(response.status_code,200,response.json)
                self.assertTrue(response.json['changed'])
            self.assertEqual(database.read_bytes(),content)


if __name__=='__main__':
    unittest.main()

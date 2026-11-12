from hashlib import sha256
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from analyzer import analyze_folder, snapshot_database


def schema(db):
    db.executescript('''
      CREATE TABLE djmdContent(ID TEXT,Title TEXT,FolderPath TEXT,OrgFolderPath TEXT,FileSize INTEGER,
        Length INTEGER,Rating INTEGER,DJPlayCount INTEGER,Analysed INTEGER,AnalysisDataPath TEXT,
        ArtistID TEXT,AlbumID TEXT,rb_local_deleted INTEGER DEFAULT 0);
      CREATE TABLE djmdCue(ID TEXT,ContentID TEXT,Comment TEXT,rb_local_deleted INTEGER DEFAULT 0);
      CREATE TABLE djmdArtist(ID TEXT,Name TEXT,rb_local_deleted INTEGER DEFAULT 0);
      CREATE TABLE djmdAlbum(ID TEXT,Name TEXT,rb_local_deleted INTEGER DEFAULT 0);
      CREATE TABLE djmdPlaylist(ID TEXT,Attribute INTEGER,rb_local_deleted INTEGER DEFAULT 0);
      CREATE TABLE contentFile(Path TEXT,rb_local_deleted INTEGER DEFAULT 0);
    ''')


def add_track(db,identifier="a",deleted=0):
    db.execute("INSERT INTO djmdContent VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (identifier,"Track",r"C:\Music\track.mp3",None,1024,300,3,0,1,"/PIONEER/USBANLZ/P001/A/ANLZ.DAT","artist","album",deleted))


def hashes(root):
    return {str(path.relative_to(root)):sha256(path.read_bytes()).hexdigest() for path in root.rglob("*") if path.is_file()}


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/"source";self.source.mkdir()
        self.output=self.root/"workbench"/"report-id"

    def test_read_only_health_and_footprint_leave_every_source_byte_unchanged(self):
        with closing(sqlite3.connect(self.source/"master.db")) as db:
            schema(db);add_track(db);add_track(db,"b");add_track(db,"retired",1)
            db.executemany("INSERT INTO djmdCue VALUES (?,?,?,0)",[("1","a","CUE(Auto)"),("2","a","My transition"),("3","b","1.1Bars"),("4","retired","Old cue")])
            db.executemany("INSERT INTO djmdPlaylist VALUES (?,?,0)",[("playlist",0),("folder",1)])
            db.commit()
        for name in ("PIONEER/USBANLZ/P001/A/ANLZ.DAT","PIONEER/USBANLZ/P001/unlinked/ANLZ.EXT"):
            path=self.source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b"analysis")
        before=hashes(self.source)
        report=analyze_folder(str(self.source),self.output,lambda *_:None,"7.2.19")
        self.assertEqual(report["read_status"],"checked")
        self.assertEqual(report["database"]["counters"]["tracks"],2)
        self.assertEqual(report["database"]["counters"]["mixed"],1)
        self.assertEqual(report["database"]["counters"]["only_auto"],1)
        self.assertEqual(report["database"]["counters"]["playlists"],1)
        self.assertEqual(report["database"]["health"]["broken_track_links"],1)
        self.assertEqual(report["database"]["health"]["duplicate_recorded_path_groups"],1)
        self.assertEqual(report["database"]["health"]["unlinked_analysis_folders"],1)
        self.assertEqual(report["footprint"]["files"],3)
        self.assertTrue(report["metadata_available"])
        metadata=json.loads((self.output/"metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(len(metadata["tracks"]),2)
        self.assertEqual(metadata["tracks"][0]["manual_cues"],1)
        self.assertIsNone(metadata["tracks"][0]["bpm"])
        self.assertNotIn("metadata_snapshot",report["database"])
        self.assertEqual(hashes(self.source),before)

    def test_encrypted_wal_commits_are_read_from_the_private_copy(self):
        from native_export import mutable_copy
        db=mutable_copy(self.source/"master.db")
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA wal_autocheckpoint=0")
            schema(db);add_track(db);db.commit()
            self.assertGreater((self.source/"master.db-wal").stat().st_size,0)
            before=hashes(self.source)
            report=analyze_folder(str(self.source),self.output,lambda *_:None)
            self.assertEqual(report["read_status"],"checked",report["messages"])
            self.assertEqual(report["database"]["counters"]["tracks"],1)
            self.assertEqual(report["database"]["encryption"],"SQLCipher SQLite")
            self.assertEqual(hashes(self.source),before)
            self.assertIn("master.db-wal",{row["name"] for row in report["source_files"]})
        finally:db.close()

    def test_legacy_detection_does_not_claim_to_decode_or_convert(self):
        (self.source/"datafile.edb").write_bytes(b"synthetic filename-detection fixture, not a real v5 database")
        before=hashes(self.source)
        report=analyze_folder(str(self.source),self.output,lambda *_:None,"5.8.6")
        self.assertEqual(report["read_status"],"inventory_only")
        self.assertIsNone(report["database"])
        self.assertEqual(hashes(self.source),before)
        self.assertFalse((self.output/"snapshot").exists())

    def test_device_export_is_not_misclassified_as_a_desktop_library(self):
        path=self.source/"PIONEER/rekordbox/export.pdb";path.parent.mkdir(parents=True);path.write_bytes(b"synthetic device detection fixture")
        report=analyze_folder(str(self.source),self.output,lambda *_:None)
        self.assertEqual(report["format"],"USB / device export")
        self.assertEqual(report["read_status"],"inventory_only")

    def test_unknown_schema_reports_its_limit_instead_of_empty_track_counters(self):
        with closing(sqlite3.connect(self.source/"master.db")) as db:db.execute("CREATE TABLE unrelated(value TEXT)")
        report=analyze_folder(str(self.source),self.output,lambda *_:None)
        self.assertEqual(report["read_status"],"needs_review")
        self.assertTrue(report["database"]["missing_core_columns"])
        self.assertEqual(report["database"]["counters"],{})

    def test_unreadable_database_produces_an_explicit_unsupported_report(self):
        (self.source/"master.db").write_bytes(b"not a readable database")
        report=analyze_folder(str(self.source),self.output,lambda *_:None)
        self.assertEqual(report["read_status"],"unsupported")
        self.assertTrue(any(message["level"]=="warning" for message in report["messages"]))

    def test_source_change_during_capture_is_rejected(self):
        (self.source/"master.db").write_bytes(b"before")
        def mutate(*_):(self.source/"master.db-wal").write_bytes(b"new journal")
        with self.assertRaisesRegex(ValueError,"changed during capture"):
            snapshot_database(self.source,self.output,mutate)

    def test_source_cannot_contain_the_analysis_destination(self):
        with self.assertRaisesRegex(ValueError,"parent"):
            analyze_folder(str(self.source),self.source/"nested-workbench",lambda *_:None)

    def test_online_only_source_database_is_held_before_reading_bytes(self):
        (self.source/'master.db').write_bytes(b'synthetic database placeholder')
        with patch('analyzer.cloud_placeholder',return_value=True):
            with self.assertRaisesRegex(ValueError,'online-only'):
                snapshot_database(self.source,self.output,lambda *_:None)
        self.assertFalse((self.output/'master.db').exists())

    def test_partial_schema_does_not_invent_zero_for_missing_statistics(self):
        with closing(sqlite3.connect(self.source/'master.db')) as db:
            db.execute('CREATE TABLE djmdContent(ID TEXT,Title TEXT,FolderPath TEXT)')
            db.execute("INSERT INTO djmdContent VALUES ('1','Track','C:/track.mp3')")
            db.commit()
        report=analyze_folder(str(self.source),self.output,lambda *_:None)
        self.assertEqual(report['database']['counters']['tracks'],1)
        self.assertIsNone(report['database']['counters']['cue_rows'])
        self.assertIsNone(report['database']['counters']['playlists'])
        self.assertIsNone(report['database']['health']['unlinked_analysis_folders'])


if __name__=="__main__":unittest.main()

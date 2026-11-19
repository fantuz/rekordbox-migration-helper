"""Cloud size agreement is metadata evidence, independent of audio identity."""
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from cloud_file_evidence import size_evidence


class CloudSizeEvidenceTests(unittest.TestCase):
    def test_only_exact_positive_recorded_sizes_can_agree(self):
        for value in (123,'123',123.0):
            with self.subTest(value=value):
                self.assertEqual(size_evidence({'size':value},{'size':123}),
                    {'expected_size':123,'remote_size':123,'size_comparison':'match'})
        self.assertEqual(size_evidence({'size_bytes':124},{'size':123})['size_comparison'],'mismatch')
        for value in (None,False,True,0,-1,1.5,float('nan'),float('inf'),'','no size','123.5',2**53):
            with self.subTest(value=value):
                result=size_evidence({'size':value},{'size':123})
                self.assertIsNone(result['expected_size']);self.assertEqual(result['size_comparison'],'unknown')
        for value in (None,False,True,-1,1.5,float('nan'),'invalid'):
            with self.subTest(remote=value):
                result=size_evidence({'size':123},{'size':value})
                self.assertIsNone(result['remote_size']);self.assertEqual(result['size_comparison'],'unknown')
        # A valid empty remote file contradicts a positive library recording.
        self.assertEqual(size_evidence({'size':123},{'size':0})['size_comparison'],'mismatch')
        self.assertEqual(size_evidence({'size':123},None)['size_comparison'],'unknown')

    def test_native_file_size_is_available_without_opening_audio(self):
        from research_capture import capture_private_database
        with closing(sqlite3.connect(':memory:')) as db:
            db.executescript('''CREATE TABLE djmdContent(ID TEXT,Title TEXT,FolderPath TEXT,FileSize INTEGER);
                INSERT INTO djmdContent VALUES ('known','Known','D:/Missing/audio.mp3',456789);
                INSERT INTO djmdContent VALUES ('unknown','Unknown','D:/Missing/other.mp3',NULL);''')
            snapshot=capture_private_database(db,'synthetic:cloud-size')
        rows={track['id']:track for track in snapshot['tracks']}
        self.assertEqual(size_evidence(rows['known'],{'size':456789})['size_comparison'],'match')
        self.assertEqual(size_evidence(rows['unknown'],{'size':456789})['size_comparison'],'unknown')

    def test_xml_size_survives_capture_without_touching_referenced_audio(self):
        import json
        from xml_analysis import analyze_xml
        with TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'collection.xml';output=root/'capture'
            source.write_text('''<DJ_PLAYLISTS><COLLECTION>
                <TRACK TrackID="known" Name="Known" Size="456789" Location="file://localhost/D:/Missing/audio.mp3"/>
                <TRACK TrackID="unknown" Name="Unknown" Location="file://localhost/D:/Missing/other.mp3"/>
                </COLLECTION></DJ_PLAYLISTS>''',encoding='utf-8')
            before=source.read_bytes();analyze_xml(source,output,lambda *_:None)
            rows={track['id']:track for track in json.loads((output/'comparison.json').read_text())['tracks']}
            self.assertEqual(size_evidence(rows['known'],{'size':456789})['size_comparison'],'match')
            self.assertEqual(size_evidence(rows['unknown'],{'size':456789})['size_comparison'],'unknown')
            self.assertEqual(source.read_bytes(),before)


if __name__=='__main__':unittest.main()

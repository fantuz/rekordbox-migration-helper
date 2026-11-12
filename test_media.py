from pathlib import Path
import tempfile
import unittest
from media import scan,verify_pair


def track(path,size):
    return {"current_path":path,"original_path":None,"xml_location":None,"size_bytes":size}


class InventoryTests(unittest.TestCase):
    def test_case_collisions_remain_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"Song.mp3").write_bytes(b"abc")
            (root/"song.mp3").write_bytes(b"def")
            result=scan({"a":track("C:/Old/Song.mp3",3)},[{"root":tmp}],lambda *_:None)
            self.assertEqual(result["matches"]["a"]["status"],"ambiguous")

    def test_mapped_path_and_export_uri(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"A song.mp3").write_bytes(b"abc")
            result=scan({"a":track("C:/Old/A song.mp3",3)},[{"root":tmp,"recorded_prefix":"C:/Old","export_uri":"file://localhost/D:/Music"}],lambda *_:None)
            match=result["matches"]["a"]
            self.assertEqual(match["status"],"found")
            self.assertEqual(match["evidence"],"mapped_path_and_size")
            self.assertEqual(match["candidates"][0]["export_uri"],"file://localhost/D:/Music/A%20song.mp3")

    def test_overlapping_root_maps_remain_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmp:
            folders=[Path(tmp)/"one",Path(tmp)/"two"]
            for folder in folders:
                folder.mkdir()
                (folder/"song.mp3").write_bytes(b"abc")
            result=scan({"a":track("C:/Old/song.mp3",3)},[{"root":str(f),"recorded_prefix":"C:/Old"} for f in folders],lambda *_:None)
            self.assertEqual(result["matches"]["a"]["status"],"ambiguous")

    def test_unavailable_root_is_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=scan({"a":track("C:/Old/song.mp3",3)},[{"root":str(Path(tmp)/"absent")}],lambda *_:None)
            self.assertEqual(result["matches"]["a"]["status"],"unverified")

    def test_hash_verification_detects_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"one.mp3").write_bytes(b"abc")
            (root/"two.mp3").write_bytes(b"abc")
            result=scan({"a":track("C:/one.mp3",3),"b":track("C:/two.mp3",3)},[{"root":tmp}],lambda *_:None)
            class Catalog: pairs={"pair":{"a":"a","b":"b"}}
            self.assertTrue(verify_pair(Catalog(),result,"pair",lambda *_:None)["same_file_bytes"])
            (root/"one.mp3").write_bytes(b"abcd")
            with self.assertRaises(ValueError):verify_pair(Catalog(),result,"pair",lambda *_:None)


if __name__=="__main__":unittest.main()

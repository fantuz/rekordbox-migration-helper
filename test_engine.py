import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from engine import Catalog, parse_xml, path_key


def cue(kind=1,start=1000,label="CUE(Auto)"):
    return {"Kind":kind,"InMsec":start,"OutMsec":-1,"Comment":label}


def catalog(cues_a,cues_b):
    c=Catalog.__new__(Catalog)
    c.policy="newest"
    c.source_cue_conflicts=defaultdict(list)
    c.cues={"a":cues_a,"b":cues_b}
    c.tracks={
        "a":{"rating":0,"october_xml":1,"date_added":"2024-01-01","last_played":None,"play_count":0},
        "b":{"rating":0,"october_xml":0,"date_added":"2026-01-01","last_played":None,"play_count":0}}
    return c,{"a":"a","b":"b"}


class KeeperTests(unittest.TestCase):
    def test_other_cues_outrank_recent_auto(self):
        c,p=catalog([cue(label="My transition")],[cue(),cue(2,2000)])
        self.assertEqual(c.preferred(p)[0],"a")

    def test_all_auto_use_newest(self):
        c,p=catalog([cue()],[cue(label="1.1Bars")])
        self.assertEqual(c.preferred(p)[0],"b")

    def test_last_played_beats_newest(self):
        c,p=catalog([cue()],[cue()])
        c.policy="last_played"
        c.tracks["a"]["last_played"]="2026-10-12"
        self.assertEqual(c.preferred(p)[0],"a")

    def test_play_count_policy(self):
        c,p=catalog([cue()],[cue()])
        c.policy="play_count"
        c.tracks["a"]["play_count"]=5
        self.assertEqual(c.preferred(p)[0],"a")

    def test_auto_slot_difference_requires_explicit_policy(self):
        c,p=catalog([cue(start=1000)],[cue(start=2000)])
        self.assertTrue(c.merge(p,"a")["conflicts"])
        self.assertFalse(c.merge(p,"a",prefer_auto=True)["conflicts"])
        self.assertEqual(c.merge(p,"a",prefer_auto=True)["cues"][0]["InMsec"],1000)

    def test_manual_difference_stays_in_review(self):
        c,p=catalog([cue(start=1000,label="Drop")],[cue(start=2000,label="Break")])
        self.assertTrue(c.merge(p,"a",prefer_auto=True)["conflicts"])

    def test_identical_position_recovers_custom_label(self):
        c,p=catalog([cue()],[cue(label="Mix here")])
        result=c.merge(p,"a")
        self.assertEqual(len(result["cues"]),1)
        self.assertEqual(result["cues"][0]["Comment"],"Mix here")

    def test_rating_conflict_requires_choice(self):
        c,p=catalog([cue()],[cue()])
        c.tracks["a"]["rating"]=3
        c.tracks["b"]["rating"]=5
        self.assertTrue(c.merge(p,"a")["conflicts"])
        self.assertEqual(c.merge(p,"a",prefer_rating=True)["rating"],3)

    def test_literal_hash_in_file_path(self):
        self.assertEqual(path_key("file://localhost/C:/Music/#track.mp3"),path_key("C:/Music/#track.mp3"))

    def test_xml_entities_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"test.xml"
            path.write_text('<!DOCTYPE x [<!ENTITY a "data">]><DJ_PLAYLISTS>&a;</DJ_PLAYLISTS>')
            with self.assertRaises(ValueError):
                parse_xml(path,lambda *_:None)


if __name__=="__main__":
    unittest.main()

class ArchiveCopyTests(unittest.TestCase):
    def test_raw_copy_preserves_zip64_and_stored_members(self):
        import zipfile
        from native_export import rewrite_archive
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/"source.zip"
            target=root/"target.zip"
            with zipfile.ZipFile(source,"w") as z:
                z.writestr("master.db",b"old database",compress_type=zipfile.ZIP_DEFLATED)
                with z.open("nested/forced-zip64.bin","w",force_zip64=True) as out:
                    out.write(b"analysis"*3000)
                z.writestr("stored.dat",b"\0\1\2"*900,compress_type=zipfile.ZIP_STORED)
                z.writestr("artwork/á.jpg",b"picture")
            rewrite_archive(source,target,{"master.db":b"new database"},lambda *_:None)
            with zipfile.ZipFile(target) as z,zipfile.ZipFile(source) as original:
                self.assertIsNone(z.testzip())
                self.assertEqual(z.read("master.db"),b"new database")
                for name in original.namelist():
                    if name!="master.db":
                        self.assertEqual(z.read(name),original.read(name))

class GroupMergeTests(unittest.TestCase):
    def test_multiple_donors_keep_union_of_cues(self):
        from engine import decision_map
        c,p=catalog([cue(1)],[cue(2,2000)])
        c.tracks["c"]=dict(c.tracks["b"])
        c.cues["c"]=[cue(3,3000)]
        c.pairs={"ab":p,"ac":{"a":"a","b":"c"}}
        decisions={"ab":{"action":"merge","keeper":"a"},"ac":{"action":"merge","keeper":"a"}}
        mapping,results=decision_map(c,decisions)
        self.assertEqual(mapping,{"b":"a","c":"a"})
        self.assertEqual(len(results["a"]["cues"]),3)
        self.assertEqual(results["a"]["donors"],["b","c"])

    def test_group_rejects_contradictory_keepers(self):
        from engine import decision_map
        c,p=catalog([cue()],[cue()])
        c.tracks["c"]=dict(c.tracks["b"])
        c.cues["c"]=[cue()]
        c.pairs={"ab":p,"bc":{"a":"b","b":"c"}}
        with self.assertRaises(ValueError):
            decision_map(c,{"ab":{"action":"merge","keeper":"a"},"bc":{"action":"merge","keeper":"b"}})

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import zipfile

from workflow import check_inputs, fingerprint_inputs, list_exports, prepare_export, select_inputs


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.zip=self.root/"original.zip";self.zip.write_bytes(b"source backup")
        self.xml=self.root/"original.xml";self.xml.write_bytes(b"source collection")
        self.meta={"zip_path":str(self.zip),"xml_path":str(self.xml)}
        self.meta["input_fingerprints"]=fingerprint_inputs(self.meta)
        self.catalog=SimpleNamespace(metadata=self.meta)
        self.snapshot={"id":"session","name":"Test library","counts":{"tracks":2}}
        self.decisions={"a~b":{"action":"merge","keeper":"a"}}

    def export(self,xml_writer,native_writer):
        return prepare_export(self.catalog,self.decisions,{},self.snapshot,self.root/"exports","f"*32,"pair",lambda *_:None,
                              xml_writer=xml_writer,native_writer=native_writer)

    def test_existing_input_selection_creates_no_copy(self):
        before={p.name:p.read_bytes() for p in self.root.iterdir()}
        selected=select_inputs({"zip":'"'+str(self.zip)+'"',"xml":str(self.xml)})
        self.assertEqual(selected,{"zip":self.zip.resolve(),"xml":self.xml.resolve()})
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()})
        with self.assertRaises(ValueError):select_inputs({"zip":"relative.zip","xml":str(self.xml)})

    def test_changed_input_invalidates_saved_analysis(self):
        self.zip.write_bytes(b"different backup bytes")
        with self.assertRaisesRegex(ValueError,"changed"):check_inputs(self.meta)

    def test_pair_keeps_one_snapshot_and_survives_history_reload(self):
        frozen=deepcopy(self.decisions)
        seen=[]
        def write_xml(catalog,decisions,relocations,path,progress):
            seen.append(deepcopy(decisions))
            self.decisions["a~b"]["keeper"]="b"
            self.snapshot["counts"]["tracks"]=999
            path.write_text("<collection/>")
            self.assertFalse((self.root/"exports"/("f"*32)).exists())
            return {"merges":1,"track_count":1}
        def write_zip(catalog,decisions,relocations,path,progress):
            seen.append(deepcopy(decisions))
            with zipfile.ZipFile(path,"w") as archive:archive.writestr("review.json",json.dumps(decisions))
            return {"merges":1,"active_tracks_after":1}
        result=self.export(write_xml,write_zip)
        self.assertEqual(seen,[frozen,frozen])
        folder=Path(result["directory"])
        report=json.loads((folder/"report.json").read_text())
        self.assertEqual(report["session"]["counts"]["tracks"],2)
        self.assertEqual(report["decisions"],frozen)
        self.assertEqual({p["kind"] for p in result["files"]},{"xml","zip","report"})
        self.assertEqual(list_exports(self.root/"exports")[0]["review_sha256"],result["review_sha256"])
        self.assertEqual(self.zip.read_bytes(),b"source backup")

    def test_failed_second_writer_never_publishes_half_a_pair(self):
        def write_xml(c,d,r,path,p):path.write_text("<collection/>");return {"merges":1}
        def broken(*args):raise ValueError("native validation failed")
        with self.assertRaisesRegex(ValueError,"native validation"):self.export(write_xml,broken)
        self.assertEqual(list((self.root/"exports").iterdir()),[])

    def test_source_change_during_export_stops_publication(self):
        def write_xml(c,d,r,path,p):
            path.write_text("<collection/>")
            self.xml.write_text("changed collection")
            return {"merges":1}
        with self.assertRaisesRegex(ValueError,"changed"):self.export(write_xml,None)
        self.assertEqual(list((self.root/"exports").iterdir()),[])

    def test_writer_plan_disagreement_stops_publication(self):
        def writer(count):
            def write(c,d,r,path,p):path.write_bytes(b"output");return {"merges":count}
            return write
        with self.assertRaisesRegex(ValueError,"different merge plans"):self.export(writer(1),writer(2))
        self.assertEqual(list_exports(self.root/"exports"),[])


if __name__=="__main__":unittest.main()

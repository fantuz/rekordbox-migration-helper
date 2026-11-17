"""Version negotiation, real extended tags, export mappings and per-run read reuse."""
from copy import deepcopy
from pathlib import Path
import json
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from xml.etree.ElementTree import Element

from metadata_overrides import apply_xml,apply_native,validate
from onetagger_bridge import ReadBatch,read_tags
from onetagger_results import EXTENDED_FIELDS,validate_report
from test_onetagger_results import ResultsTests,mp3_tags,syncsafe
from werkzeug.exceptions import Conflict


def extended_mp3(path):
    mp3_tags(path,{'title':'Tagged title','artist':'Artist','genre':'Techno'})
    data=path.read_bytes()
    original_size=sum((data[6+i]&127) << (21-7*i) for i in range(4))
    frames=data[10:10+original_size]
    for key,value in [('TPUB','Independent label'),('TCOM','Composer')]:
        body=b'\x03'+value.encode();frames+=key.encode()+syncsafe(len(body))+b'\0\0'+body
    path.write_bytes(b'ID3\x04\0\0'+syncsafe(len(frames))+frames+bytes(64))


class ExtendedResultsTests(TestCase):
    setUp=ResultsTests.setUp
    export=ResultsTests.export
    results_report=ResultsTests.results_report
    raw_import=ResultsTests.raw_import
    review=ResultsTests.review
    real_stage=ResultsTests.real_stage

    def test_real_extended_tags_and_legacy_report_boundaries(self):
        self.audio=self.root/'extended.mp3';extended_mp3(self.audio)
        self.track={**self.track,'current_path':'D:/Music/extended.mp3','label':'Old label','composer':'Old composer'}
        self.sid=self.store.save_snapshot({'scope_key':self.before['scope_key'],'tracks':[self.track]},'Extended')['id']
        self.before=self.store.snapshot(self.sid);identity=self.export()
        manifest=self.store.setting('onetagger:'+identity);self.assertEqual(manifest['results_version'],2)
        tags=read_tags(self.audio)[0];self.assertEqual(tags['label'],'Independent label');self.assertEqual(tags['composer'],'Composer')
        original=self.audio.read_bytes()
        legacy=self.results_report(identity,tags)
        self.assertEqual(self.raw_import(identity,json.dumps(legacy)).status_code,200)
        self.assertTrue(all(c['field'] not in ('label','composer') for c in self.review(identity)['rows'][0]['changes']))
        report=deepcopy(legacy);report['version']=2
        report['tracks'][0]['after']={field:tags.get(field) for field in EXTENDED_FIELDS}
        self.assertEqual(self.raw_import(identity,json.dumps(report)).status_code,200)
        scan=self.review(identity)
        self.assertEqual(self.real_stage(identity,scan,('label','composer')).status_code,200)
        edits=self.store.overrides(self.before['scope_key'])['one']
        self.assertEqual(set(edits),{'label','composer'})
        self.assertEqual(edits['label']['baseline'],'Old label')
        self.assertEqual(self.audio.read_bytes(),original);self.assertEqual(self.store.snapshot(self.sid),self.before)
        report['version']=1
        with self.assertRaises(ValueError):validate_report(report,manifest)

    def test_read_reuse_is_bounded_to_operation_and_rejects_changed_files(self):
        self.audio=self.root/'extended.mp3';extended_mp3(self.audio)
        with patch('onetagger_bridge.read_tags',wraps=read_tags) as reader:
            batch=ReadBatch()
            for _ in range(500):batch.read(self.audio)
            self.assertEqual(reader.call_count,1)
            ReadBatch().read(self.audio);self.assertEqual(reader.call_count,2)
            with self.audio.open('ab') as stream:stream.write(b'changed')
            with self.assertRaises(Conflict):batch.read(self.audio)

    def test_extended_metadata_exports_use_existing_native_lookup_tables(self):
        fields={'label':'Independent label','composer':'Composer'}
        for field,value in fields.items():self.assertEqual(validate(field,value),value)
        xml=Element('TRACK',{'Rating':'255','AverageBpm':'128','Tonality':'8A'})
        apply_xml(xml,fields)
        self.assertEqual(xml.attrib,{'Rating':'255','AverageBpm':'128','Tonality':'8A','Label':'Independent label','Composer':'Composer'})
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.execute('CREATE TABLE djmdContent (ID TEXT,LabelID TEXT,ComposerID TEXT,ArtistID TEXT,BPM INT,rb_local_deleted INT)')
        db.execute("INSERT INTO djmdContent VALUES ('one',NULL,NULL,'performer',12800,0)")
        for table in ('djmdArtist','djmdLabel'):
            db.execute('CREATE TABLE '+table+' (ID TEXT,Name TEXT,UUID TEXT,rb_local_deleted INT)')
        tables={t:{r[1] for r in db.execute('PRAGMA table_info('+t+')')} for t in ('djmdContent','djmdArtist','djmdLabel')}
        def update(table,where,args,values):
            db.execute('UPDATE '+table+' SET '+','.join(k+'=?' for k in values)+' WHERE '+where,(*values.values(),*args))
        self.assertEqual(apply_native(db,tables,{'one':fields},update,'now',lambda:1),2)
        self.assertEqual(db.execute('SELECT a.Name,l.Name,c.ArtistID,c.BPM FROM djmdContent c JOIN djmdArtist a ON a.ID=c.ComposerID JOIN djmdLabel l ON l.ID=c.LabelID').fetchone(),('Composer','Independent label','performer',12800))
        self.assertEqual(apply_native(db,tables,{'one':fields},update,'now',lambda:2),0)

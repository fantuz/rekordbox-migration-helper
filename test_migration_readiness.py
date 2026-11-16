"""Read-only readiness reports and checksum boundaries on invented fixtures."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from backup_manifest import backup_manifest
from migration_readiness import camelot,export_readiness,tempo_key_review,FAT32_MAX_BYTES
from task_control import OperationCancelled


class ReadinessTests(unittest.TestCase):
    def test_real_import_keeps_xml_tempo_evidence_in_saved_snapshots(self):
        import test_import_reliability
        from engine import Catalog
        from research_capture import capture_workspace
        fixture=test_import_reliability.ImportReliabilityTests('test_nulls_survive_import_capture_filters_and_statistics')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        text=fixture.xml.read_text().replace('TrackID="known"','TrackID="known" AverageBpm="174"')
        text=text.replace('/known.wav"/>','/known.wav"><TEMPO Bpm="174"/></TRACK>')
        fixture.xml.write_text(text)
        meta=fixture.run_analysis();catalog=Catalog(meta['source'],meta)
        catalog.tracks['known']['bpm']=87
        source=capture_workspace(catalog,'session:tempo-test')
        known=next(t for t in source['tracks'] if t['id']=='known')
        self.assertEqual(known['xml_bpm'],174);self.assertEqual(known['grid_bpms'],[174])
        summary,rows=tempo_key_review(source)
        self.assertEqual(summary['tempo_disagreements'],1)
        self.assertTrue(next(r for r in rows if r['section']=='tempo_disagreement')['half_double'])

    def test_profile_and_fat32_rules_preserve_unknowns_and_original_metadata(self):
        source={'tracks':[{'id':'1','title':'Huge','format':'WAV','size':FAT32_MAX_BYTES+1,'current_path':'C:/Music/CON.wav'},
                          {'id':'2','format':'FLAC','size':FAT32_MAX_BYTES,'current_path':'/Music/good.flac'},
                          {'id':'3','format':'OGG','size':200,'current_path':'/Music/a.ogg'},
                          {'id':'4'}]}
        before=deepcopy(source);summary,rows=export_readiness(source,'cdj-2000nxs2','fat32')
        self.assertEqual(summary['tracks_with_findings'],2)
        self.assertEqual(len(rows[0]['issues']),2);self.assertEqual(rows[1]['issues'],[])
        self.assertIn('OGG',rows[2]['detail']);self.assertIn('audio format',rows[3]['unknown'])
        self.assertEqual(source,before);self.assertIn('not checked',summary['note'])
        with self.assertRaises(ValueError):export_readiness(source,'invented player')

    def test_key_notations_sort_musically_without_rewriting_the_source(self):
        for text,expected in [('Am',(8,'A')),('C',(8,'B')),('G♭ minor',(11,'A')),('12b',(12,'B')),('Abm',(1,'A')),('D# major',(5,'B'))]:
            self.assertEqual(camelot(text),expected,text)
        self.assertIsNone(camelot('13A'));self.assertIsNone(camelot('unknown'))
        source={'tracks':[{'id':'a','title':'A','tonality':'C','bpm':87,'xml_bpm':174},
                          {'id':'b','title':'B','tonality':'Am','bpm':128,'xml_bpm':128,'grid_bpms':[128,130]},
                          {'id':'c','title':'C','tonality':'1A'}, {'id':'d','tonality':'?'}]}
        before=deepcopy(source);summary,rows=tempo_key_review(source)
        self.assertEqual(summary['tempo_disagreements'],2)
        self.assertEqual(summary['keys_recognized'],3);self.assertEqual(summary['tempo_comparison_unknown'],2)
        self.assertTrue(next(r for r in rows if r['track_id']=='a' and r['section']=='tempo_disagreement')['half_double'])
        self.assertEqual([r['camelot'] for r in rows if r['section']=='musical_key'],['1A','8A','8B'])
        self.assertEqual(source,before)


class BackupTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.backup=self.root/'backup.zip'
        with zipfile.ZipFile(self.backup,'w') as archive:
            archive.writestr('master.db',b'synthetic database')
            archive.writestr('PIONEER/USBANLZ/P001/ABC/ANLZ0000.DAT',b'synthetic analysis')
            archive.writestr('artwork/a.jpg',b'synthetic artwork')
        self.source={'asset_references':['PIONEER/USBANLZ/P001/ABC/ANLZ0000.DAT','PIONEER/USBANLZ/P002/DEF/ANLZ0000.DAT']}
        self.original=self.backup.read_bytes()

    def test_manifest_hashes_members_and_explains_missing_components(self):
        summary,rows=backup_manifest(self.source,self.backup,lambda *_:None,True)
        self.assertEqual(summary['verified_members'],3);self.assertEqual(summary['missing_analysis_references'],1)
        self.assertEqual(summary['checksum_status'],'verified')
        db=next(r for r in rows if r['section']=='backup_member' and r['component']=='database')
        self.assertEqual(db['sha256'],sha256(b'synthetic database').hexdigest())
        self.assertEqual(self.backup.read_bytes(),self.original)
        self.assertEqual(next(r for r in rows if r['title']=='music')['files'],0)

    def test_budget_never_claims_unread_members_are_verified(self):
        summary,rows=backup_manifest(self.source,self.backup,lambda *_:None,True,max_verify_bytes=1)
        self.assertEqual(summary['hashed_bytes'],0);self.assertEqual(summary['checksum_status'],'partial')
        self.assertTrue(all(r['verification']=='budget_exceeded' for r in rows if r['section']=='backup_member'))

    def test_cancel_and_unsafe_paths_do_not_write_or_extract_anything(self):
        def cancel(*_):raise OperationCancelled('stop')
        with self.assertRaises(OperationCancelled):backup_manifest(self.source,self.backup,cancel,True)
        with zipfile.ZipFile(self.backup,'w') as archive:archive.writestr('../escape',b'bad')
        with self.assertRaisesRegex(ValueError,'unsafe'):backup_manifest(self.source,self.backup,lambda *_:None)
        self.assertEqual({p.name for p in self.root.iterdir()},{'backup.zip'})

    def test_corrupt_member_fails_checksum_verification(self):
        raw=self.backup.read_bytes().replace(b'synthetic database',b'corrupted database')
        self.assertEqual(len(raw),len(self.original));self.backup.write_bytes(raw)
        with self.assertRaises(zipfile.BadZipFile):backup_manifest(self.source,self.backup,lambda *_:None,True)

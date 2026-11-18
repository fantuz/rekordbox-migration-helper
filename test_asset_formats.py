"""Invented binary layouts only; no model weights, personal libraries or audio."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import binascii
import json
import os
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from asset_formats import inspect_format,SETTINGS,MAX_STEM_FRAMES
from analysis_audit import audit_assets
from backup_manifest import backup_manifest,component
from task_control import OperationCancelled


def settings_bytes(name='MYSETTING.DAT'):
    raw=bytearray(104+SETTINGS[name.casefold()]);struct.pack_into('<I',raw,0,96)
    struct.pack_into('<I',raw,100,len(raw)-104)
    raw[104:]=bytes(range(len(raw)-104))
    crc=binascii.crc_hqx(raw if name.casefold()=='djmmysetting.dat' else raw[104:],0)
    return bytes(raw)+struct.pack('<I',crc)


def section(tag,extra=b'',body=b''):
    return tag.encode()+struct.pack('>II',12+len(extra),12+len(extra)+len(body))+extra+body


def anlz_bytes(bpms=(12800,12800),duplicate_cues=True):
    beats=b''.join(struct.pack('>HHI',i%4+1,bpm,25+i*500) for i,bpm in enumerate(bpms))
    body=section('PQTZ',struct.pack('>III',0,0,len(bpms)),beats)
    for kind in ((1,0) if duplicate_cues else (1,)):
        body+=section('PCOB',struct.pack('>IHHI',kind,0,0,0xffffffff))
        body+=section('PCO2',struct.pack('>IHH',kind,0,0))
    body+=section('PSSI')+section('PVDI')+section('ZZZZ',body=b'opaque')
    return b'PMAI'+struct.pack('>II',28,28+len(body))+bytes(16)+body


def pdb_bytes():
    data=bytearray(4096*2)
    struct.pack_into('<III',data,0,0,4096,1)
    struct.pack_into('<4I',data,28,0,0,1,1)
    return bytes(data)


def pqt2_bytes(fractions=(125,986),revision=0x01000002):
    extra=(struct.pack('>III',0,revision,0)+struct.pack('>HHI',1,12800,25)
           +struct.pack('>HHI',2,12800,525)+struct.pack('>II',len(fractions),26153)+bytes(8))
    body=section('PQT2',extra,b''.join(struct.pack('>H',v) for v in fractions))
    return b'PMAI'+struct.pack('>II',28,28+len(body))+bytes(16)+body


def stems_bytes(frames=8):
    return b'PDSTEMS1'+struct.pack('<Q',frames)+bytes(16*frames)


class FormatTests(unittest.TestCase):
    def inspect(self,name,raw,size=None):return inspect_format(name,raw,len(raw) if size is None else size)

    def test_non_pmai_3ex_is_unsupported_even_with_an_embedding_prefix(self):
        for raw in (b'opaque',b'',b'\x81\xa9embedding',b'\x81\xa9embedding\xc1',
                    b'\x81\xa9embedding\x81\xa2d4\xcb'+struct.pack('>d',1.25)):
            with self.subTest(raw=raw):
                result=self.inspect('ANLZ0000.3EX',raw)
                self.assertEqual(result['validation'],'unsupported')
                self.assertEqual(result['format'],'anlz_3ex');self.assertFalse(result['payload_verified'])
                self.assertEqual(result['embedding_signature'],raw.startswith(b'\x81\xa9embedding'))
                self.assertIsNone(result['native_stems_readiness'])
        self.assertEqual(self.inspect('ANLZ0000.3EX',anlz_bytes())['validation'],'recognized')
        self.assertEqual(self.inspect('ANLZ0000.3EX',b'PMAI'+bytes(20))['validation'],'corrupt')

    def test_known_extended_grid_checks_count_and_fraction_range_without_claiming_checksum(self):
        result=self.inspect('ANLZ0000.EXT',pqt2_bytes())
        self.assertEqual(result['validation'],'recognized')
        grid=result['extended_grid_evidence'][0]
        self.assertEqual(grid['validation'],'recognized');self.assertEqual(grid['beats'],2)
        self.assertEqual((grid['min_fraction'],grid['max_fraction']),(125,986))
        self.assertEqual(grid['checksum_validation'],'not_checked')
        self.assertIsNone(result['native_stems_readiness'])

    def test_extended_grid_rejects_mismatched_huge_counts_and_invalid_fractions(self):
        for count in (0,1,3,2**32-1):
            raw=bytearray(pqt2_bytes());struct.pack_into('>I',raw,28+40,count)
            result=self.inspect('ANLZ0000.EXT',raw)
            self.assertEqual(result['validation'],'corrupt')
            self.assertEqual(result['extended_grid_evidence'][0]['validation'],'corrupt')
        for fraction in (1000,65535):
            self.assertEqual(self.inspect('ANLZ0000.EXT',pqt2_bytes((fraction,)))['validation'],'corrupt')

    def test_extended_grid_unknown_revision_and_budget_limits_do_not_imply_corruption(self):
        result=self.inspect('ANLZ0000.EXT',pqt2_bytes((65535,),revision=0x02000002))
        self.assertEqual(result['validation'],'recognized')  # PMAI framing only
        self.assertEqual(result['extended_grid_evidence'][0]['validation'],'unsupported')
        raw=pqt2_bytes()
        for at in range(12,len(raw)):
            result=self.inspect('ANLZ0000.EXT',raw[:at],len(raw))
            self.assertIn(result['validation'],('recognized','not_checked'))
            if result['extended_grid_evidence']:
                self.assertEqual(result['extended_grid_evidence'][0]['validation'],'not_checked')

    def test_all_settings_types_and_distinct_checksum_scopes(self):
        for name in SETTINGS:
            with self.subTest(name=name):
                raw=settings_bytes(name);before=bytes(raw);r=self.inspect(name.upper(),raw)
                self.assertEqual(r['validation'],'recognized');self.assertTrue(r['crc_valid']);self.assertEqual(raw,before)
                edited=bytearray(raw);edited[104]^=1
                self.assertEqual(self.inspect(name,edited)['validation'],'corrupt')
                edited=bytearray(raw);edited[20]^=1
                self.assertEqual(self.inspect(name,edited)['validation'],'corrupt' if name=='djmmysetting.dat' else 'recognized')

    def test_settings_truncation_length_and_footer(self):
        raw=settings_bytes()
        for changed in (raw[:100],raw[:-1],raw+bytes(1),struct.pack('<I',95)+raw[4:]):
            self.assertEqual(self.inspect('MYSETTING.DAT',changed)['validation'],'corrupt')
        self.assertEqual(self.inspect('MYSETTING.DAT',raw[:108],len(raw))['validation'],'not_checked')

    def test_unknown_settings_payload_revision_is_unsupported_not_corrupt(self):
        raw=bytearray(149);struct.pack_into('<I',raw,0,96);struct.pack_into('<I',raw,100,41)
        self.assertEqual(self.inspect('MYSETTING.DAT',raw)['validation'],'unsupported')

    def test_anlz_repeated_groups_unknown_tags_and_variable_tempo(self):
        raw=anlz_bytes((12800,13000));r=self.inspect('ANLZ0000.DAT',raw)
        self.assertEqual(r['validation'],'recognized');self.assertEqual(r['section_counts']['PCOB'],2)
        self.assertEqual(r['section_counts']['PCO2'],2);self.assertEqual(len(r['cue_groups']),4)
        self.assertTrue(all(g['entries']==0 for g in r['cue_groups']))
        self.assertEqual(r['sections'][-1]['tag'],'ZZZZ');self.assertTrue(r['phrase_evidence']);self.assertTrue(r['vocal_activity_evidence'])
        self.assertEqual(r['tempo_evidence'][0]['bpms'],[128,130]);self.assertTrue(r['tempo_evidence'][0]['variable_tempo'])
        self.assertIsNone(r['native_stems_readiness']);self.assertEqual(raw,anlz_bytes((12800,13000)))

    def test_populated_legacy_and_extended_cues_keep_complementary_evidence(self):
        legacy=bytearray(56);legacy[:4]=b'PCPT';struct.pack_into('>II',legacy,4,28,56)
        struct.pack_into('>II',legacy,12,1,4);legacy[28]=2;struct.pack_into('>II',legacy,32,1000,2000)
        comment='Drop 日本\x00'.encode('utf-16-be')
        extended=bytearray(44+len(comment));extended[:4]=b'PCP2';struct.pack_into('>II',extended,4,16,len(extended))
        struct.pack_into('>I',extended,12,1);extended[16]=2;struct.pack_into('>II',extended,20,1000,2000)
        struct.pack_into('>I',extended,40,len(comment));extended[44:]=comment
        body=section('PCOB',struct.pack('>IHHI',1,0,1,0xffffffff),legacy)+section('PCO2',struct.pack('>IHH',1,1,0),extended)
        raw=b'PMAI'+struct.pack('>II',28,28+len(body))+bytes(16)+body
        result=self.inspect('ANLZ0000.EXT',raw)
        self.assertEqual(result['validation'],'recognized')
        old,new=result['cue_groups'];self.assertEqual(old['entries'],1);self.assertEqual(new['entries'],1)
        self.assertTrue(old['positions'][0]['active_loop']);self.assertIsNone(new['positions'][0]['active_loop'])
        self.assertEqual(new['positions'][0]['comment'],'Drop 日本');self.assertEqual(new['positions'][0]['in_ms'],1000)
        bad=bytearray(raw);struct.pack_into('>I',bad,28+24+8,2**32-1)
        self.assertEqual(self.inspect('ANLZ0000.EXT',bad)['validation'],'corrupt')

    def test_anlz_rejects_invalid_lengths_without_following_them(self):
        raw=anlz_bytes()
        for start,value in ((4,0),(8,0),(28+4,4),(28+8,2**32-1),(28+20,2**32-1)):
            changed=bytearray(raw);struct.pack_into('>I',changed,start,value)
            self.assertEqual(self.inspect('ANLZ0000.3EX',changed)['validation'],'corrupt',(start,value))
        self.assertEqual(self.inspect('ANLZ0000.DAT',b'not a container')['validation'],'corrupt')

    def test_anlz_truncated_prefix_never_reads_past_supplied_bytes(self):
        raw=anlz_bytes()
        for size in range(12,len(raw)):
            r=self.inspect('ANLZ0000.DAT',raw[:size],len(raw))
            self.assertIn(r['validation'],('not_checked','recognized'))
            self.assertIsNone(r['native_stems_readiness'])

    def test_grid_invalid_order_zero_tempo_and_declared_count(self):
        for bpms in ((0,12800),(12800,0)):
            self.assertEqual(self.inspect('ANLZ0000.DAT',anlz_bytes(bpms))['validation'],'corrupt')
        raw=bytearray(anlz_bytes());struct.pack_into('>I',raw,28+24+8+4,0)
        self.assertEqual(self.inspect('ANLZ0000.DAT',raw)['validation'],'corrupt')

    def test_analysis_section_count_is_bounded(self):
        body=section('ZZZZ')*1025;raw=b'PMAI'+struct.pack('>II',28,28+len(body))+bytes(16)+body
        result=self.inspect('ANLZ0000.DAT',raw)
        self.assertEqual(result['validation'],'not_checked');self.assertEqual(len(result['sections']),1024)

    def test_stems_header_proves_structure_only(self):
        r=self.inspect('name.stems',stems_bytes())
        self.assertEqual(r['validation'],'recognized');self.assertEqual(r['channels'],8)
        self.assertEqual(r['source_order'],['drums','bass','other','vocals'])
        self.assertFalse(r['payload_verified']);self.assertFalse(r['association_metadata_present']);self.assertEqual(r['source_association'],'unknown')
        self.assertIsNone(r['native_stems_readiness'])
        self.assertEqual(self.inspect('name.stems',stems_bytes()[:16],len(stems_bytes()))['validation'],'recognized')

    def test_recordbox_cache_retention_is_not_a_backup_or_preparation_guarantee(self):
        result=self.inspect('name.stems',stems_bytes())
        self.assertEqual(result['cache_retention'],'unknown')
        self.assertTrue(result['cache_eviction_possible'])
        self.assertIsNone(result['native_stems_readiness'])
        self.assertEqual(result['source_association'],'unknown')
        self.assertIn('disk budget',result['cache_lifecycle_note'])

    def test_stems_zero_huge_and_truncated_lengths_are_bounded(self):
        for frames in (0,MAX_STEM_FRAMES+1,2**60,2**64-1):
            raw=b'PDSTEMS1'+struct.pack('<Q',frames)
            self.assertEqual(self.inspect('name.stems',raw)['validation'],'corrupt')
        self.assertEqual(self.inspect('name.stems',stems_bytes()[:-1])['validation'],'corrupt')
        self.assertEqual(self.inspect('name.stems',b'PDSTEMS1')['validation'],'corrupt')

    def test_duration_policy_does_not_call_a_consistent_large_cache_corrupt(self):
        frames=MAX_STEM_FRAMES+1;prefix=b'PDSTEMS1'+struct.pack('<Q',frames)
        result=self.inspect('name.stems',prefix,16+frames*16)
        self.assertEqual(result['validation'],'not_checked');self.assertIsNone(result['native_stems_readiness'])

    def test_catalog_headers_and_onelibrary_limits_are_distinct(self):
        r=self.inspect('export.pdb',pdb_bytes());self.assertEqual(r['validation'],'recognized');self.assertFalse(r['records_decoded'])
        self.assertEqual(r['page_size'],4096)
        raw=bytearray(pdb_bytes());struct.pack_into('<I',raw,36,4)
        self.assertEqual(self.inspect('exportExt.pdb',raw)['validation'],'corrupt')
        self.assertEqual(self.inspect('export.pdb',pdb_bytes()+b'x')['validation'],'corrupt')
        r=self.inspect('exportLibrary.db',b'SQLite format 3\x00')
        self.assertEqual(r['validation'],'unsupported');self.assertEqual(r['catalog_layer'],'OneLibrary')

    def test_suffix_container_and_rbsc_are_candidates(self):
        for name,data in (('a.stems',b'unknown'),('drums.rbsc',b'unknown'),('a.stem.mp4',struct.pack('>I4s4sI',16,b'ftyp',b'M4A ',0))):
            r=self.inspect(name,data);self.assertEqual(r['validation'],'unsupported');self.assertIsNone(r['native_stems_readiness'])

    def test_single_byte_mutations_stay_bounded_and_return_evidence(self):
        for name,original in (('ANLZ0000.DAT',anlz_bytes()),('MYSETTING.DAT',settings_bytes()),('a.stems',stems_bytes())):
            for index in range(len(original)):
                damaged=bytearray(original);damaged[index]^=255
                result=self.inspect(name,damaged)
                self.assertIn(result['validation'],('recognized','corrupt','unsupported','not_checked'))


class AuditTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.folder=self.root/'files';self.folder.mkdir();self.files={
            'ANLZ0000.DAT':anlz_bytes(),'mix.stems':stems_bytes(),'broken.stems':stems_bytes()[:-1],
            'MYSETTING.DAT':settings_bytes(),'export.pdb':pdb_bytes(),'exportLibrary.db':b'opaque catalog','drums.rbsc':b'capture'}
        for name,raw in self.files.items():(self.folder/name).write_bytes(raw)
        self.archive=self.root/'fixture.zip'
        with zipfile.ZipFile(self.archive,'w') as z:
            for name,raw in self.files.items():z.writestr('PIONEER/'+name,raw)

    def audit(self,**kwargs):return audit_assets({'tracks':[]},kwargs.pop('source',str(self.folder)),lambda *_:None,inspect=True,**kwargs)

    def test_zip_and_folder_parity_hashing_and_preservation(self):
        original=self.archive.read_bytes();left,rows=self.audit(verify=True);right,zrows=self.audit(source=str(self.archive),verify=True)
        fields=('validation','format','sha256','checksum_status')
        project=lambda values:sorted((r['title'],*[r.get(f) for f in fields]) for r in values if 'validation' in r)
        self.assertEqual(project(rows),project(zrows));self.assertEqual(left['format_inspection']['files'],7)
        self.assertEqual(left['format_inspection']['corrupt'],1);self.assertIsNone(left['stems']['prepared_tracks'])
        self.assertTrue(all(r['checksum_status']=='computed' for r in rows if 'validation' in r))
        self.assertTrue(all(not r['zip_crc_verified'] for r in rows if 'validation' in r))
        self.assertTrue(all(r['zip_crc_verified'] for r in zrows if 'validation' in r))
        self.assertEqual(self.archive.read_bytes(),original)
        for name,raw in self.files.items():self.assertEqual((self.folder/name).read_bytes(),raw)

    def test_header_and_hash_budgets_keep_unchecked_separate(self):
        summary,rows=self.audit(verify=True,max_inspect_bytes=0,max_hash_bytes=0)
        self.assertEqual(summary['format_inspection']['not_checked'],7);self.assertEqual(summary['bytes_hashed'],0)
        self.assertTrue(all(r['checksum_status']=='not_checked' for r in rows if 'validation' in r))
        summary,rows=self.audit(verify=True,max_hash_bytes=1)
        self.assertTrue(all(r['checksum_status']=='budget_exceeded' for r in rows if 'validation' in r))
        self.assertLessEqual(summary['format_inspection']['bytes_inspected'],8*1024**2)

    def test_no_content_reads_when_format_inspection_is_not_requested(self):
        with patch('pathlib.Path.open',side_effect=AssertionError('unexpected content read')):
            summary,rows=audit_assets({},str(self.folder),lambda *_:None)
        self.assertNotIn('format_inspection',summary)

    def test_cancellation_during_hashing_is_not_swallowed(self):
        def cancel(amount,*_):
            if amount==80:raise OperationCancelled('stop')
        with self.assertRaises(OperationCancelled):audit_assets({},str(self.folder),cancel,True,inspect=True)

    def test_source_replacement_during_probe_rejects_report(self):
        import analysis_audit
        original=analysis_audit.inspect_format
        def mutate(name,prefix,size):
            path=self.folder/name;path.write_bytes(path.read_bytes()+b'x')
            return original(name,prefix,size)
        with patch('analysis_audit.inspect_format',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'changed'):self.audit()

    def test_same_size_and_mtime_replacement_during_probe_is_rejected(self):
        import analysis_audit
        original=analysis_audit.inspect_format
        def replace(name,prefix,size):
            path=self.folder/name;stamp=path.stat();replacement=path.with_name('replacement.tmp')
            replacement.write_bytes(b'x'*size);os.utime(replacement,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            replacement.replace(path)
            return original(name,prefix,size)
        with patch('analysis_audit.inspect_format',side_effect=replace):
            with self.assertRaisesRegex(ValueError,'changed'):self.audit()

    def test_archive_replacement_is_detected_before_report_publication(self):
        def mutate(amount,*_):
            if amount==75:
                data=self.archive.read_bytes();self.archive.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'changed'):audit_assets({},str(self.archive),mutate,inspect=True)

    def test_unavailable_and_cloud_assets_do_not_claim_verified_bytes(self):
        import analysis_audit
        original=analysis_audit.file_record
        def cloud(path):return {**original(path),'cloud_only':True}
        with patch('analysis_audit.file_record',side_effect=cloud),patch('pathlib.Path.open',side_effect=AssertionError('cloud read')):
            summary,rows=self.audit(verify=True)
        self.assertEqual(summary['format_inspection']['not_checked'],7)

    def test_unsafe_zip_names_are_rejected_without_extraction(self):
        with zipfile.ZipFile(self.archive,'w') as z:z.writestr('../mix.stems',stems_bytes())
        with self.assertRaisesRegex(ValueError,'unsafe'):self.audit(source=str(self.archive))
        self.assertFalse((self.root.parent/'mix.stems').exists())

    def test_settings_classification_and_crc_validation_in_backup(self):
        for name in SETTINGS:self.assertEqual(component('PIONEER/'+name.upper()),'settings')
        summary,rows=backup_manifest({},str(self.archive),lambda *_:None,True)
        item=next(r for r in rows if r['section']=='backup_member' and r['component']=='settings')
        self.assertTrue(item['format_evidence']['crc_valid'])
        self.assertEqual(next(r['files'] for r in rows if r['section']=='backup_component' and r['title']=='settings'),1)
        self.assertEqual(component('PIONEER/rekordbox/export.pdb'),'device_catalog')

    def test_3ex_coverage_is_an_exact_file_reference(self):
        source={'asset_references':['PIONEER/USBANLZ/P001/ABC/ANLZ0000.3EX']}
        with zipfile.ZipFile(self.archive,'w') as z:z.writestr('PIONEER/USBANLZ/P001/ABC/ANLZ0000.2EX',b'other')
        summary,rows=backup_manifest(source,str(self.archive),lambda *_:None)
        self.assertEqual(summary['missing_analysis_references'],1)
        self.assertEqual(next(r['title'] for r in rows if r['section']=='missing_analysis'),'usbanlz/p001/abc/anlz0000.3ex')

    def test_tempo_comparisons_require_unambiguous_exact_references(self):
        from analysis_audit import compare_analysis_tempos
        path='/PIONEER/USBANLZ/P001/ABC/ANLZ0000.DAT'
        source={'tracks':[{'id':'a','title':'Track A','analysis_path':path,'bpm':87}]}
        result={'format':'anlz','validation':'recognized','path':path,'scope':'synthetic',
                'tempo_evidence':[{'bpms':[174]}]}
        before=deepcopy(source);rows=compare_analysis_tempos(source,[result])
        self.assertEqual(len(rows),1);self.assertTrue(rows[0]['half_double']);self.assertEqual(source,before)
        self.assertIn('not verified',result['tempo_reference']['basis'])
        source['tracks'].append({**source['tracks'][0],'id':'b'})
        self.assertEqual(compare_analysis_tempos(source,[result]),[])
        source['tracks']=source['tracks'][:1];source['tracks'][0]['bpm']=None
        self.assertEqual(compare_analysis_tempos(source,[result]),[])

    def test_bounded_tempo_lists_cannot_establish_a_false_disagreement(self):
        from analysis_audit import compare_analysis_tempos
        raw=anlz_bytes(tuple(range(12000,12300)))
        evidence=inspect_format('ANLZ0000.DAT',raw,len(raw))
        grid=evidence['tempo_evidence'][0]
        self.assertFalse(grid['bpms_complete']);self.assertEqual(grid['distinct_tempo_count'],300)
        path='/USBANLZ/P001/ABC/ANLZ0000.DAT'
        source={'tracks':[{'id':'a','analysis_path':path,'bpm':122.99}]}
        evidence.update(path=path,scope='synthetic')
        self.assertEqual(compare_analysis_tempos(source,[evidence]),[])
        self.assertFalse(evidence['tempo_reference']['grid_tempos_complete'])

    def test_bad_settings_crc_remains_separate_from_successful_zip_crc(self):
        bad=bytearray(settings_bytes());bad[104]^=1
        with zipfile.ZipFile(self.archive,'w') as z:z.writestr('PIONEER/MYSETTING.DAT',bad)
        summary,rows=backup_manifest({},str(self.archive),lambda *_:None,True)
        self.assertEqual(summary['checksum_status'],'verified')
        row=next(r for r in rows if r['section']=='backup_member')
        self.assertEqual(row['verification'],'verified');self.assertEqual(row['format_evidence']['validation'],'corrupt')
        self.assertEqual(row['severity'],'review')

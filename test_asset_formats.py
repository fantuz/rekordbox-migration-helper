"""Invented binary layouts only; no model weights, personal libraries or audio."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
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


def anlz_file(*sections):
    body=b''.join(sections)
    return b'PMAI'+struct.pack('>II',28,28+len(body))+bytes(16)+body


def pqtz_section(entries=((1,12800,29),),shift=0,extra=b''):
    return section('PQTZ',struct.pack('>IHhI',0,8,shift,len(entries))+extra,
                   b''.join(struct.pack('>HHI',*entry) for entry in entries))


def pssi_section(version=0,count=1,mood=3,entry_size=24,masked=False):
    # Fixed generated headers, independently calculated from the documented format bytes.
    # count257 has the same mask adjustment as count1 modulo256.
    if masked:
        assert count in (1,257) and mood==3 and version in (0,1)
        header=bytes.fromhex(('cc e1 ef fb e6 ef ae ef ea c3 ea ec e5 ea',
                              'e2 ec fb e6 ef ae ef ea d3 fa ec e2 ed f4')[version])
    else:header=struct.pack('>H',mood)+bytes(6)+struct.pack('>H',16)+bytes(2)+bytes((7,0))
    return section('PSSI',struct.pack('>HHH',version,entry_size,count)+header,
                   bytes(entry_size*count))


def phrase_rows_section(rows, version=0, mood=3, masked=False):
    header = struct.pack('>H6sH4B', mood, b'abcdef', 120, 37, 52, 7, 19)
    body = header + b''.join(struct.pack('>12H', *row) for row in rows)
    if masked:
        seed = b'Kanzen-niRikaishita'
        body = bytes(byte ^ ((128 + seed[(version+i) % len(seed)] + len(rows)) & 255)
                     for i, byte in enumerate(body))
    return section('PSSI', struct.pack('>HHH', version, 24, len(rows)) + body[:14], body[14:])


def extended_cue_file(comment):
    entry=bytearray(88+len(comment));entry[:4]=b'PCP2'
    struct.pack_into('>II',entry,4,16,len(entry));entry[16]=1
    struct.pack_into('>II',entry,20,1000,0xffffffff)
    struct.pack_into('>I',entry,40,len(comment));entry[44:44+len(comment)]=comment
    return anlz_file(section('PCO2',struct.pack('>IHH',0,1,0),entry))


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

    def test_desktop_extended_table_and_cleared_marker(self):
        populated = self.inspect('ANLZ0000.EXT', pqt2_bytes(revision=0x02000002))
        grid = populated['extended_grid_evidence'][0]
        self.assertEqual((grid['table_state'], grid['beats'], grid['checksum_validation']),
                         ('populated', 2, 'not_checked'))
        empty = anlz_file(section('PQT2', struct.pack('>III', 0, 0x02000002, 0) + bytes(32)))
        grid = self.inspect('ANLZ0000.EXT', empty)['extended_grid_evidence'][0]
        self.assertEqual((grid['validation'], grid['table_state'], grid['beats']), ('recognized', 'cleared', 0))
        for at in (12, 20, 24, 32, 44, 48):
            damaged = bytearray(empty)
            damaged[28 + at] = 1
            self.assertEqual(self.inspect('ANLZ0000.EXT', damaged)['validation'], 'corrupt')

    def test_recognized_embedding_requires_the_complete_profile(self):
        from test_native_embedding import embedding
        for owner in (b'0', b'123'):
            data = embedding(owner)
            report = self.inspect('ANLZ0000.3EX', data)
            self.assertEqual((report['validation'], report['track_id_assigned']), ('recognized', owner != b'0'))
            self.assertFalse(report['payload_verified'])
            self.assertEqual(self.inspect('ANLZ0000.3EX', data[:30], len(data))['validation'], 'unsupported')

    def test_extended_grid_rejects_mismatched_huge_counts_and_invalid_fractions(self):
        for count in (0,1,3,2**32-1):
            raw=bytearray(pqt2_bytes());struct.pack_into('>I',raw,28+40,count)
            result=self.inspect('ANLZ0000.EXT',raw)
            self.assertEqual(result['validation'],'corrupt')
            self.assertEqual(result['extended_grid_evidence'][0]['validation'],'corrupt')
        for fraction in (1000,65535):
            self.assertEqual(self.inspect('ANLZ0000.EXT',pqt2_bytes((fraction,)))['validation'],'corrupt')

    def test_extended_grid_unknown_revision_and_budget_limits_do_not_imply_corruption(self):
        result=self.inspect('ANLZ0000.EXT',pqt2_bytes((65535,),revision=0x03000002))
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
        self.assertEqual(r['phrase_structure_evidence'][0]['validation'],'unsupported')
        self.assertFalse(r['phrase_structure_evidence'][0]['entry_semantics_decoded'])

    def test_grid_signed_header_shift_reports_effective_times_without_unsigned_wrap(self):
        for raw_ms,shift,effective_ms in ((29,0,29),(29,414,443),(178,-166,12),(236,-230,6),
                                          (1,-230,-229),(0,-32768,-32768),(2**32-1,32767,2**32+32766)):
            with self.subTest(raw_ms=raw_ms,shift=shift):
                raw=anlz_file(pqtz_section(((1,12800,raw_ms),),shift))
                before=bytes(raw);result=self.inspect('ANLZ0000.DAT',raw)
                self.assertEqual(result['validation'],'recognized')
                grid=result['beat_grid_evidence'][0]
                self.assertEqual(grid['validation'],'recognized');self.assertEqual(grid['header_shift_ms'],shift)
                self.assertEqual((grid['raw_first_ms'],grid['raw_last_ms']),(raw_ms,raw_ms))
                self.assertEqual((grid['effective_first_ms'],grid['effective_last_ms']),(effective_ms,effective_ms))
                self.assertEqual(grid['has_negative_effective_times'],effective_ms<0)
                self.assertEqual(result['tempo_evidence'][0]['effective_first_ms'],effective_ms)
                self.assertEqual(result['tempo_evidence'][0]['bpms'],[128]);self.assertEqual(raw,before)
                self.assertIsNone(result['native_stems_readiness'])

    def test_grid_empty_repeated_and_unknown_headers_do_not_invent_timing_association(self):
        result=self.inspect('ANLZ0000.DAT',anlz_file(pqtz_section((),-166),pqtz_section(shift=414)))
        empty,shifted=result['beat_grid_evidence']
        self.assertEqual(empty['beats'],0);self.assertIsNone(empty['effective_first_ms'])
        self.assertFalse(empty['has_negative_effective_times']);self.assertEqual(shifted['effective_first_ms'],443)
        raw=anlz_file(pqtz_section(extra=bytes(4)))
        result=self.inspect('ANLZ0000.DAT',raw)
        self.assertEqual(result['validation'],'recognized');self.assertEqual(result['tempo_evidence'],[])
        self.assertEqual(result['beat_grid_evidence'][0]['validation'],'unsupported')
        self.assertNotIn('header_shift_ms',result['beat_grid_evidence'][0])

    def test_grid_signed_shift_respects_prefix_budgets(self):
        raw=anlz_file(pqtz_section(((1,12800,29),(2,13000,529)),414))
        for at in range(12,len(raw)):
            result=self.inspect('ANLZ0000.DAT',raw[:at],len(raw))
            self.assertIn(result['validation'],('recognized','not_checked'))
            self.assertEqual(result['tempo_evidence'],[])
            if result['beat_grid_evidence']:
                self.assertEqual(result['beat_grid_evidence'][0]['validation'],'not_checked')

    def test_phrase_known_versions_plain_and_rotated_mask_report_known_layout(self):
        for version in (0,1):
            for masked in (False,True):
                for count in (1,257):
                    with self.subTest(version=version,masked=masked,count=count):
                        raw=anlz_file(pssi_section(version,count,masked=masked));before=bytes(raw)
                        result=self.inspect('ANLZ0000.EXT',raw);phrase=result['phrase_structure_evidence'][0]
                        self.assertEqual(result['validation'],'recognized');self.assertTrue(result['phrase_evidence'])
                        self.assertEqual(phrase['validation'],'recognized')
                        self.assertEqual((phrase['version'],phrase['entry_bytes'],phrase['entries']),(version,24,count))
                        self.assertEqual((phrase['mood'],phrase['mood_name'],phrase['end_beat'],phrase['bank']),(3,'low',16,7))
                        self.assertEqual(phrase['body_encoding'],'xor_mask_inferred' if masked else 'unmasked')
                        self.assertTrue(phrase['entry_semantics_decoded']);self.assertIsNone(phrase['native_stems_readiness'])
                        self.assertIsNone(result['native_stems_readiness']);self.assertEqual(raw,before)
        for mood in (1,2,3):
            phrase=self.inspect('ANLZ0000.EXT',anlz_file(pssi_section(mood=mood)))['phrase_structure_evidence'][0]
            self.assertEqual(phrase['mood'],mood)

    def test_phrase_rows_preserve_every_word_and_report_source_beat_indices_only(self):
        words = (1234, 65535, 0, 77, 88, 99, 17, 23, 4)
        rows = [(4, 1, 5, *words), (9, 39, 199, *reversed(words))]
        for version in (0, 1):
            for mood, label in ((1, 'Chorus'), (2, 'Verse 4'), (3, 'Verse 2')):
                plain = phrase_rows_section(rows, version, mood)
                for masked in (True, False):
                    raw = anlz_file(phrase_rows_section(rows, version, mood, masked))
                    phrase = self.inspect('ANLZ0000.EXT', raw)['phrase_structure_evidence'][0]
                    self.assertEqual(bytes.fromhex(phrase['decoded_header_hex']), plain[:32])
                    self.assertEqual((phrase['header_byte_28'], phrase['header_byte_29'], phrase['bank']), (37, 52, 7))
                    self.assertTrue(phrase['starts_in_order_and_range'])
                    self.assertEqual([r['kind_label'] for r in phrase['phrase_rows']], [label, None])
                    for i, observed in enumerate(phrase['phrase_rows']):
                        self.assertEqual((observed['index'], observed['start_beat'], observed['kind'], *observed['extra_words']), rows[i])
                        self.assertNotIn('time', observed)
        invalid = [(1, 0, 5, *words), (2, 121, 5, *words)]
        evidence = self.inspect('test.EXT', anlz_file(phrase_rows_section(invalid)))['phrase_structure_evidence'][0]
        self.assertFalse(evidence['starts_in_order_and_range'])

    def test_phrase_details_share_one_limit_and_late_disorder_is_still_reported(self):
        rows = [(i, i+1, 5, *([0]*9)) for i in range(95)] + [(96, 2, 1, *([0]*9))]
        part = phrase_rows_section(rows, 1, masked=True)
        first, second = self.inspect('test.EXT', anlz_file(part, part))['phrase_structure_evidence']
        self.assertEqual([len(p['phrase_rows']) for p in (first, second)], [64, 0])
        self.assertEqual([p['rows_omitted'] for p in (first, second)], [32, 96])
        self.assertTrue(all(p['starts_in_order_and_range'] is False for p in (first, second)))
        large = self.inspect('test.EXT', anlz_file(pssi_section(count=4097)))['phrase_structure_evidence'][0]
        self.assertEqual(large['validation'], 'not_checked')
        self.assertNotIn('phrase_rows', large)

    def test_phrase_unknown_profiles_remain_presence_evidence(self):
        unknown_header=section('PSSI',bytes(24),bytes(24))
        for phrase_section in (section('PSSI'),unknown_header,pssi_section(version=2,mood=0),
                               pssi_section(entry_size=32,mood=0)):
            result=self.inspect('ANLZ0000.EXT',anlz_file(phrase_section))
            self.assertEqual(result['validation'],'recognized');self.assertTrue(result['phrase_evidence'])
            phrase=result['phrase_structure_evidence'][0]
            self.assertEqual(phrase['validation'],'unsupported');self.assertNotIn('mood',phrase)
            self.assertFalse(phrase['entry_semantics_decoded']);self.assertIsNone(result['native_stems_readiness'])

    def test_phrase_known_profile_rejects_count_and_mood_mismatch_without_following_counts(self):
        for count in (0,2,65535):
            phrase=bytearray(pssi_section());struct.pack_into('>H',phrase,16,count)
            result=self.inspect('ANLZ0000.EXT',anlz_file(phrase))
            self.assertEqual(result['validation'],'corrupt')
            self.assertEqual(result['phrase_structure_evidence'][0]['validation'],'corrupt')
        for mood in (0,4,65535):
            result=self.inspect('ANLZ0000.EXT',anlz_file(pssi_section(mood=mood)))
            self.assertEqual(result['validation'],'corrupt')
            self.assertNotIn('mood',result['phrase_structure_evidence'][0])

    def test_phrase_partial_prefix_keeps_unchecked_distinct_from_corrupt(self):
        raw=anlz_file(pssi_section(version=1,masked=True))
        for at in range(12,len(raw)):
            result=self.inspect('ANLZ0000.EXT',raw[:at],len(raw))
            self.assertIn(result['validation'],('recognized','not_checked'))
            if result['phrase_structure_evidence']:
                phrase=result['phrase_structure_evidence'][0]
                self.assertEqual(phrase['validation'],'not_checked');self.assertFalse(phrase['entry_semantics_decoded'])
                self.assertIsNone(phrase['native_stems_readiness'])

    def test_extended_cue_nonempty_comment_requires_its_own_utf16_terminator(self):
        for comment in ('A'.encode('utf-16-be'),b'\x00',b'\xd8\x00\x00\x00'):
            raw=extended_cue_file(comment)
            result=self.inspect('ANLZ0000.EXT',raw)
            self.assertEqual(result['validation'],'corrupt')
            self.assertEqual(result['cue_groups'][0]['entry_validation'],'corrupt')
        # A zero-filled field after the declared comment cannot supply its missing terminator.
        self.assertIn('terminator',self.inspect('ANLZ0000.EXT',extended_cue_file(b'\x00A'))['detail'])

    def test_extended_cue_empty_unicode_and_literal_nuls_are_preserved(self):
        for comment in ('','Drop 日本😀','A\x00B','A\x00'):
            encoded=(comment+'\x00').encode('utf-16-be') if comment else b''
            raw=extended_cue_file(encoded);before=bytes(raw)
            result=self.inspect('ANLZ0000.EXT',raw)
            self.assertEqual(result['validation'],'recognized')
            self.assertEqual(result['cue_groups'][0]['positions'][0]['comment'],comment)
            self.assertEqual(raw,before)
        result=self.inspect('ANLZ0000.EXT',extended_cue_file(b'\x00\x00'))
        self.assertEqual(result['cue_groups'][0]['positions'][0]['comment'],'')

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

    def test_recordbox_model_evidence_requires_both_a_generated_name_and_recognized_layout(self):
        key = '0123456789abcdef01234567'
        data = stems_bytes()
        for model, variant in [('htdemucs', 'speed'), ('htdemucs_ft', 'quality')]:
            name = f'{key}-{model}.stems'
            result = self.inspect(name, data[:16], len(data))
            self.assertEqual((result['recordbox_key'], result['recordbox_model'], result['recordbox_variant']),
                             (key, model, variant))
            self.assertEqual(result['recordbox_model_basis'], 'filename')
            self.assertEqual(result['source_association'], 'unknown')
            self.assertIsNone(result['native_stems_readiness'])
            for invalid in (b'unknown', data[:12], data[:-1]):
                self.assertNotIn('recordbox_variant', self.inspect(name, invalid))
        for name in ('renamed.bin', f'{key}-future.stems', f'{key.upper()}-htdemucs.stems',
                     f'{key}-HTDEMUCS.stems', f'{key}-htdemucs.STEMS',
                     f'{key}-htdemucs.stems.tmp', f'{key}0-htdemucs.stems'):
            with self.subTest(name=name):
                result = self.inspect(name, data[:16], len(data))
                self.assertEqual(result['validation'], 'recognized')
                self.assertNotIn('recordbox_variant', result)
                self.assertNotIn('recordbox_key', result)

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

    def test_recordbox_inventory_tallies_only_observed_layouts_and_reads_headers(self):
        key = '1234567890abcdef12345678'
        members = {f'stems/{key}-htdemucs.stems': stems_bytes(20),
                   f'stems/{key}-htdemucs_ft.stems': stems_bytes(20),
                   'stems/renamed.bin': stems_bytes(30),
                   f'stems/{"0"*24}-htdemucs.stems': stems_bytes(5)[:-1]}
        folder = self.root / 'saved'
        for name, data in members.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        with zipfile.ZipFile(self.archive, 'w') as archive:
            for name, data in members.items():
                archive.writestr(name, data)

        for source in (folder, self.archive):
            with self.subTest(source=source):
                summary, rows = self.audit(source=str(source), max_inspect_bytes=64)
                inspection = summary['format_inspection']
                self.assertEqual(inspection['bytes_inspected'], 64)
                self.assertEqual(inspection['corrupt'], 1)
                self.assertEqual(inspection['recordbox_saved_stems'],
                                 {'speed_files': 1, 'quality_files': 1, 'unidentified_files': 1,
                                  'recognized_bytes': 2*len(stems_bytes(20)) + len(stems_bytes(30)),
                                  'paired_keys': 1, 'ambiguous_keys': 0, 'unconfirmed_pairs': 0})
                pair, = (r for r in rows if r['section'] == 'recordbox_stems_pair')
                self.assertEqual(pair['recordbox_key'], key)
                self.assertTrue(pair['matching_frame_counts'])
                self.assertEqual(pair['speed_bytes'], len(stems_bytes(20)))
                self.assertEqual(pair['bytes'], pair['quality_bytes'] + pair['speed_bytes'])
                self.assertEqual(pair['source_association'], 'unknown')
                self.assertEqual(pair['cache_state'], 'present')
                self.assertIsNone(pair['native_stems_readiness'])
                self.assertFalse(any(k.startswith('_') for k in pair))
        for name, data in members.items():
            self.assertEqual((folder / name).read_bytes(), data)
        summary, rows = self.audit(source=str(folder), max_inspect_bytes=15)
        self.assertEqual(summary['format_inspection']['recordbox_saved_stems']['recognized_bytes'], 0)
        self.assertFalse(any(r['section'] == 'recordbox_stems_pair' for r in rows))

    def test_recordbox_pairing_respects_zip_and_directory_boundaries_and_flags_different_frames(self):
        key = 'a'*24
        speed, quality = f'{key}-htdemucs.stems', f'{key}-htdemucs_ft.stems'
        second = self.root / 'second.zip'
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('stems/' + speed, stems_bytes(4))
            archive.writestr('copy/' + quality, stems_bytes(4))
        with zipfile.ZipFile(second, 'w') as archive:
            archive.writestr('stems/' + quality, stems_bytes(4))
        # Supply an alternate spelling even on runners without Windows short paths.
        sources = [str(self.archive), str(self.folder / '..' / second.name)]
        summary, rows = self.audit(source=sources)
        self.assertEqual(summary['format_inspection']['recordbox_saved_stems']['paired_keys'], 0)
        self.assertFalse(any(r['section'] == 'recordbox_stems_pair' for r in rows))
        with zipfile.ZipFile(second, 'a') as archive:
            archive.writestr('stems/' + speed, stems_bytes(5))
        summary, rows = self.audit(source=sources)
        pair, = (r for r in rows if r['section'] == 'recordbox_stems_pair')
        self.assertEqual(pair['scope'], str(second.resolve()))
        self.assertEqual((pair['speed_frames'], pair['quality_frames']), (5, 4))
        self.assertFalse(pair['matching_frame_counts'])
        self.assertEqual((pair['severity'], pair['cache_state']), ('review', 'unknown'))
        self.assertIn('frame counts differ', pair['detail'])
        self.assertEqual(summary['format_inspection']['recordbox_saved_stems']['paired_keys'], 1)

    def test_recordbox_zip_aliases_prevent_pairing_even_if_the_duplicate_is_corrupt(self):
        key = 'b'*24
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr(f'stems/{key}-htdemucs.stems', stems_bytes())
            archive.writestr(f'stems/./{key}-htdemucs.stems', b'PDSTEMS1')
            archive.writestr(f'stems/{key}-htdemucs_ft.stems', stems_bytes())
        summary, rows = self.audit(source=str(self.archive))
        inventory = summary['format_inspection']['recordbox_saved_stems']
        self.assertEqual((inventory['paired_keys'], inventory['ambiguous_keys']), (0, 1))
        self.assertEqual(inventory['recognized_bytes'], 2*len(stems_bytes()))
        files = [r for r in rows if r['section'] == 'stems_cache']
        self.assertEqual(len(files), 3)
        self.assertTrue(all(r['severity'] == 'review' and 'ambiguous' in r['detail'] for r in files))
        self.assertTrue(all(r['recordbox_pair_ambiguous'] for r in files))
        self.assertFalse(any(r['section'] == 'recordbox_stems_pair' for r in rows))

    def test_recordbox_pair_requires_final_validation_after_an_optional_hash_read_fails(self):
        speed = 'd'*24 + '-htdemucs.stems'
        quality = 'd'*24 + '-htdemucs_ft.stems'
        with zipfile.ZipFile(self.archive, 'w') as archive:
            for member in (speed, quality):
                archive.writestr(member, stems_bytes())
        open_member = zipfile.ZipFile.open
        quality_reads = 0
        def fail_second_read(archive, member):
            nonlocal quality_reads
            if member == quality:
                quality_reads += 1
                if quality_reads == 2:
                    raise OSError('Could not finish reading this member')
            return open_member(archive, member)
        with patch.object(zipfile.ZipFile, 'open', fail_second_read):
            summary, rows = self.audit(source=str(self.archive), verify=True)
        inventory = summary['format_inspection']['recordbox_saved_stems']
        self.assertEqual((inventory['speed_files'], inventory['quality_files'], inventory['paired_keys']), (1, 0, 0))
        failed, = (r for r in rows if r.get('checksum_status') == 'failed')
        self.assertEqual((failed['title'], failed['validation']), (quality, 'not_checked'))
        self.assertFalse(any(r['section'] == 'recordbox_stems_pair' for r in rows))

    def test_truncated_zip_withholds_only_its_own_apparent_recordbox_pair(self):
        key = 'e'*24
        speed = f'{key}-htdemucs.stems'
        quality = f'{key}-htdemucs_ft.stems'
        second = self.root / 'second.zip'
        for path in (self.archive, second):
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr(speed, stems_bytes())
                archive.writestr(quality, stems_bytes())
                if path == second:
                    archive.writestr('./' + quality, stems_bytes())
        sources = [str(self.archive), str(second)]
        summary, rows = self.audit(source=sources, max_files=5)
        inventory = summary['format_inspection']['recordbox_saved_stems']
        self.assertFalse(summary['inventory_complete'])
        self.assertEqual((inventory['speed_files'], inventory['quality_files']), (2, 2))
        self.assertEqual((inventory['paired_keys'], inventory['unconfirmed_pairs'], inventory['ambiguous_keys']), (1, 1, 0))
        pair, = (r for r in rows if r['section'] == 'recordbox_stems_pair')
        self.assertEqual(pair['scope'], str(self.archive.resolve()))
        summary, rows = self.audit(source=sources)
        inventory = summary['format_inspection']['recordbox_saved_stems']
        self.assertTrue(summary['inventory_complete'])
        self.assertEqual((inventory['paired_keys'], inventory['unconfirmed_pairs'], inventory['ambiguous_keys']), (1, 0, 1))

    def test_completed_verification_with_short_stream_overrides_earlier_format_evidence(self):
        speed = 'c'*24 + '-htdemucs.stems'
        quality = 'c'*24 + '-htdemucs_ft.stems'
        marker = '.rbstemsplus-cache'
        members = {speed: stems_bytes(), quality: stems_bytes(),
                   marker: b'id=11111111-2222-4333-8444-555555555555\nformat=rbstems-v1\n'}
        with zipfile.ZipFile(self.archive, 'w') as archive:
            for name, data in members.items():
                archive.writestr(name, data)
        open_member = zipfile.ZipFile.open
        opened = set()
        def read_member(archive, name):
            if name in opened and name != speed:
                return BytesIO(members[name][:-1])
            opened.add(name)
            return open_member(archive, name)
        with patch.object(zipfile.ZipFile, 'open', read_member):
            summary, rows = self.audit(source=str(self.archive), verify=True)
        inventory = summary['format_inspection']['recordbox_saved_stems']
        self.assertEqual((inventory['speed_files'], inventory['quality_files'], inventory['paired_keys']), (1, 0, 0))
        self.assertEqual(inventory['recognized_bytes'], len(members[speed]))
        short_reads = [r for r in rows if r.get('checksum_status') == 'size_mismatch']
        self.assertEqual({r['title'] for r in short_reads}, {quality, marker})
        for row in short_reads:
            self.assertEqual((row['validation'], row['severity'], row['cache_state']), ('corrupt', 'review', 'unknown'))
            self.assertIn(f'Full read returned {row["bytes"]-1} bytes', row['detail'])
            self.assertNotIn('sha256', row)

    def test_unrelated_zip_members_with_recordbox_names_do_not_create_recordbox_findings(self):
        speed = 'f'*24 + '-htdemucs.stems'
        quality = 'f'*24 + '-htdemucs_ft.stems'
        with zipfile.ZipFile(self.archive, 'w') as archive:
            for name in (speed, './' + speed, quality):
                archive.writestr(name, b'Plain text')
        summary, rows = self.audit(source=str(self.archive))
        self.assertEqual(summary['format_inspection']['unsupported'], 3)
        self.assertFalse(any(summary['format_inspection']['recordbox_saved_stems'].values()))
        self.assertFalse(any(r.get('provider') == 'recordbox' or r.get('recordbox_pair_ambiguous') for r in rows))

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

    def test_usb_catalogs_group_by_exact_device_directory_even_without_content_reads(self):
        catalog = self.folder/'drive A'/'PIONEER'/'rekordbox'
        catalog.mkdir(parents=True)
        (catalog/'export.pdb').write_bytes(b'invalid but named as a catalog')
        (catalog/'exportLibrary.db').write_bytes(b'uninspected')
        companion = self.folder/'drive B'/'PIONEER'/'rekordbox'
        companion.mkdir(parents=True)
        (companion/'exportExt.pdb').write_bytes(b'companion')
        with zipfile.ZipFile(self.archive, 'w') as z:
            for member in ('A/PIONEER/rekordbox/export.pdb', 'A/PIONEER/rekordbox/EXPORT.PDB',
                           'a/PIONEER/rekordbox/exportLibrary.db',
                           'A/./PIONEER/rekordbox/exportLibrary.db', 'orphan/exportExt.pdb'):
                z.writestr(member,b'uninspected')
        other = self.root/'separate.zip'
        with zipfile.ZipFile(other, 'w') as z:
            z.writestr('A/PIONEER/rekordbox/exportLibrary.db',b'uninspected')
        scopes = list(map(str,(self.folder, catalog, self.archive, other)))
        summary,rows = self.audit(source=scopes,max_inspect_bytes=0)
        self.assertEqual(summary['format_inspection']['bytes_inspected'],0)
        layouts = {r['path']:r for r in rows if r['section']=='usb_catalog_folder'}
        self.assertEqual({p:r['catalog_layout'] for p,r in layouts.items()}, {
            str(catalog):'mixed', str(companion):'companion',
            str(self.archive)+'!/A/PIONEER/rekordbox':'classic',
            str(self.archive)+'!/A/./PIONEER/rekordbox':'onelibrary',
            str(self.archive)+'!/a/PIONEER/rekordbox':'onelibrary',
            str(other)+'!/A/PIONEER/rekordbox':'onelibrary'})
        self.assertEqual(layouts[str(catalog)]['catalog_filenames'],{'export.pdb':1,'exportLibrary.db':1})
        self.assertEqual(layouts[str(self.archive)+'!/A/PIONEER/rekordbox']['catalog_filenames'],{'EXPORT.PDB':2})
        self.assertTrue(all(not r['records_decoded'] and r['player_compatibility'] is None
                            for r in layouts.values()))

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

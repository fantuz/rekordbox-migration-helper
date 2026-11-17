"""Synthetic structures and workflow boundaries; no songs, models or vendor binaries."""
from copy import deepcopy
from pathlib import Path
import json
import math
import os
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from analysis_audit import audit_assets
from asset_formats import inspect_format
from stems_formats import inspect_cache_file,inspect_manifest
from stems_eligibility import context,eligibility,provider,cache_profile,namespace_status,PIONEER_MODEL

MODEL='1'*64
KEY='a'*64
OTHER_KEY='b'*64


def box(tag,body=b'',extended=False):
    return struct.pack('>I4sQ',1,tag,len(body)+16)+body if extended else struct.pack('>I4s',len(body)+8,tag)+body


def ni_bytes(labels=4,tracks=5,rate=44100,channels=2,delta=0,metadata=True,edits=True,extended=False):
    info={'version':1,'stems':[{'name':'Part '+str(i)+' 日本','color':'#009E73'} for i in range(labels)]}
    mvhd=bytearray(100);struct.pack_into('>II',mvhd,12,1000,250)
    parts=[box(b'mvhd',mvhd)]
    for i in range(tracks):
        tkhd=bytearray(84);tkhd[:4]=b'\x00\x00\x00'+bytes([3 if i==0 else 2]);struct.pack_into('>I',tkhd,12,i+1)
        mdhd=bytearray(24);struct.pack_into('>II',mdhd,12,rate,rate//4)
        hdlr=bytes(8)+b'soun'+bytes(12)
        sample=bytearray(28);struct.pack_into('>HH',sample,6,1,0);struct.pack_into('>H',sample,16,channels);struct.pack_into('>I',sample,24,rate*65536)
        stsd=box(b'stsd',bytes(4)+struct.pack('>I',1)+box(b'mp4a',sample))
        mdia=box(b'mdia',box(b'mdhd',mdhd)+box(b'hdlr',hdlr)+box(b'minf',box(b'stbl',stsd)))
        edts=box(b'edts',box(b'elst',bytes(4)+struct.pack('>I',1)+struct.pack('>Iihh',250+(delta if i==1 else 0),1024,1,0))) if edits else b''
        parts.append(box(b'trak',box(b'tkhd',tkhd)+edts+mdia))
    if metadata:parts.append(box(b'udta',box(b'stem',json.dumps(info,ensure_ascii=False).encode())))
    return box(b'ftyp',b'M4A '+bytes(4))+box(b'mdat',bytes(16))+box(b'moov',b''.join(parts),extended)


def cache_flac(frames=4410,channels=8,rate=44100,bits=16):
    body=bytearray(34);packed=(rate<<44)|((channels-1)<<41)|((bits-1)<<36)|frames
    body[10:18]=packed.to_bytes(8,'big')
    return b'fLaC'+bytes([128,0,0,34])+body


def cache_desc(frames=1,version=2):
    body=b'RBD'+str(version).encode()+struct.pack('<iff',frames,0,1)+bytes(8*frames)
    return body+(bytes(8+8*frames) if version==2 else b'')


def marker():return b'id=11111111-2222-4333-8444-555555555555\nformat=rbstems-v1\n'


def manifest(path,keys=(KEY,),complete=1,model=MODEL,stamp=None):
    stamp=path.stat() if stamp is None else stamp
    return (f'rbstemsplus-manifest 1\nhelper 1.0\nmodel {model}\nplaylist synthetic\nrate 1 0.1 1\n'
            f'file {stamp.st_size} {stamp.st_mtime_ns} {complete} {len(keys)} {path}\n'+''.join(key+'\n' for key in keys)).encode()


def write_cache(root,keys=(KEY,),marker_present=True):
    root.mkdir(parents=True,exist_ok=True)
    if marker_present:(root/'.rbstemsplus-cache').write_bytes(marker())
    for key in keys:
        folder=root/MODEL/key[:2];folder.mkdir(parents=True,exist_ok=True)
        (folder/(key+'.flac')).write_bytes(cache_flac());(folder/(key+'.desc')).write_bytes(cache_desc())
    return root


class ContainerTests(unittest.TestCase):
    def inspect(self,raw):return inspect_format('synthetic.stem.m4a',raw,len(raw))

    def test_metadata_labels_flags_and_edit_timelines(self):
        raw=ni_bytes();before=bytes(raw);r=self.inspect(raw)
        self.assertEqual(r['validation'],'recognized');self.assertEqual(r['format'],'ni_stems_v1')
        self.assertEqual(r['audio_streams'],5);self.assertEqual(len(r['stem_labels']),4)
        self.assertTrue(r['timeline_consistent']);self.assertFalse(r['payload_verified']);self.assertIsNone(r['native_stems_readiness'])
        self.assertTrue(all(t['duration_seconds']==.25 for t in r['tracks']));self.assertEqual(raw,before)

    def test_generic_multistream_container_is_not_declared_ni(self):
        r=self.inspect(ni_bytes(metadata=False));self.assertEqual(r['validation'],'unsupported');self.assertEqual(r['provider'],'unknown')

    def test_wrong_labels_tracks_channels_and_timelines(self):
        for kwargs,expected in (({'labels':3},'corrupt'),({'tracks':4},'corrupt'),({'channels':1},'unsupported'),({'delta':10},'unsupported')):
            with self.subTest(kwargs=kwargs):self.assertEqual(self.inspect(ni_bytes(**kwargs))['validation'],expected)

    def test_extended_atom_sizes_and_zero_size_leaf(self):
        self.assertEqual(self.inspect(ni_bytes(extended=True))['validation'],'recognized')
        raw=ni_bytes();at=raw.index(b'moov')-4;raw=raw[:at]+bytes(4)+raw[at+4:]
        self.assertEqual(self.inspect(raw)['validation'],'recognized')

    def test_malformed_lengths_do_not_escape_parent_boxes(self):
        raw=ni_bytes()
        for tag in (b'moov',b'trak',b'mdia',b'stsd',b'mp4a',b'stem'):
            at=raw.index(tag)-4;changed=bytearray(raw);struct.pack_into('>I',changed,at,2**32-1)
            self.assertEqual(self.inspect(changed)['validation'],'corrupt',tag)

    def test_prefix_budget_is_unknown_instead_of_a_malformed_file(self):
        raw=ni_bytes();r=inspect_format('a.stem.mp4',raw[:64],len(raw))
        self.assertEqual(r['validation'],'not_checked')

    def test_duplicate_metadata_keys_and_unknown_revision(self):
        raw=ni_bytes();old=b'"version": 1'
        raw=raw.replace(old,b'"version": 2');self.assertEqual(self.inspect(raw)['validation'],'unsupported')

    def test_mutations_return_bounded_evidence(self):
        raw=ni_bytes()
        for i in range(0,len(raw),7):
            changed=bytearray(raw);changed[i]^=255
            self.assertIn(self.inspect(changed)['validation'],('recognized','corrupt','unsupported','not_checked'))


class CacheMetadataTests(unittest.TestCase):
    def test_descriptor_revisions_and_invalid_counts_floats_lengths(self):
        for version in (1,2):
            raw=cache_desc(version=version);self.assertEqual(inspect_cache_file('a.desc',raw,len(raw))['validation'],'recognized')
        for raw in (cache_desc()[:-1],b'RBD2'+struct.pack('<iff',513,0,1),b'RBD2'+struct.pack('<iff',1,float('nan'),1)+bytes(24)):
            self.assertEqual(inspect_cache_file('a.desc',raw,len(raw))['validation'],'corrupt')

    def test_flac_requires_provider_context_and_preserves_gain_policy(self):
        raw=cache_flac();self.assertIsNone(inspect_cache_file('a.flac',raw,len(raw)))
        r=inspect_cache_file('a.flac',raw,len(raw),True)
        self.assertEqual(r['validation'],'recognized');self.assertEqual(r['restore_gain'],2);self.assertEqual(r['stored_gain'],.5)
        raw=cache_flac(channels=2);self.assertEqual(inspect_cache_file('a.flac',raw,len(raw),True)['validation'],'unsupported')

    def test_marker_unknown_revision_duplicate_and_bad_uuid(self):
        raw=marker();self.assertEqual(inspect_cache_file('.rbstemsplus-cache',raw,len(raw))['validation'],'recognized')
        for bad in (raw.replace(b'11111111',b'not-uuid'),raw+b'id=other\n'):
            self.assertEqual(inspect_cache_file('.rbstemsplus-cache',bad,len(bad))['validation'],'corrupt')
        bad=raw.replace(b'rbstems-v1',b'rbstems-v2');self.assertEqual(inspect_cache_file('.rbstemsplus-cache',bad,len(bad))['validation'],'unsupported')

    def test_retention_and_preparation_are_distinct_formats(self):
        raw=f'rbstemsplus-kept 1\nuntil 1\n{MODEL} {KEY}\n'.encode()
        r=inspect_manifest(raw,len(raw),True);self.assertEqual(r['asset_family'],'retention_set');self.assertEqual(r['referenced_chunks'],1)
        self.assertIsNone(r['native_stems_readiness'])


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.audio=self.root/'selected audio';self.audio.mkdir();self.source=self.audio/'Synthetic 日本.wav';self.source.write_bytes(b'invented source bytes')
        self.cache=write_cache(self.root/'RB Stems Plus Cache.noindex')
        self.kept=self.root/'kept';self.kept.mkdir();(self.kept/'synthetic.manifest').write_bytes(manifest(self.source))

    def audit(self,roots=None,**kwargs):
        return audit_assets({},[str(p) for p in (roots or [self.cache,self.kept,self.audio])],lambda *_:None,inspect=True,**kwargs)

    def prep(self,rows):return [r for r in rows if r['section']=='stems_preparation']

    def test_consistent_source_and_chunk_metadata_are_not_native_readiness(self):
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()};summary,rows=self.audit()
        prep=self.prep(rows)[0];self.assertEqual(prep['cache_state'],'consistent');self.assertEqual(prep['source_association'],'metadata_match')
        self.assertIsNone(prep['native_stems_readiness']);self.assertIsNone(summary['stems']['prepared_tracks'])
        for p,b in before.items():self.assertEqual(p.read_bytes(),b)

    def test_missing_chunk_and_stopped_manifest_are_incomplete(self):
        (self.kept/'synthetic.manifest').write_bytes(manifest(self.source,(KEY,OTHER_KEY)))
        prep=self.prep(self.audit()[1])[0];self.assertEqual(prep['cache_state'],'incomplete');self.assertEqual(prep['missing_or_invalid_chunks'],1)
        (self.kept/'synthetic.manifest').write_bytes(manifest(self.source,complete=0))
        self.assertEqual(self.prep(self.audit()[1])[0]['cache_state'],'incomplete')

    def test_cache_sets_cannot_be_stitched_across_folders(self):
        (self.kept/'synthetic.manifest').write_bytes(manifest(self.source,(KEY,OTHER_KEY)))
        second=write_cache(self.root/'other'/'RB Stems Plus Cache.noindex',(OTHER_KEY,))
        rows=self.audit([self.cache,second,self.kept,self.audio])[1];prep=self.prep(rows)
        self.assertEqual(len(prep),2);self.assertTrue(all(r['cache_state']=='incomplete' for r in prep))

    def test_source_mutation_is_stale_even_when_all_chunks_exist(self):
        self.source.write_bytes(b'replaced source')
        self.assertEqual(self.prep(self.audit()[1])[0]['cache_state'],'stale')

    def test_manifest_paths_cannot_authorize_out_of_scope_stats(self):
        with patch('stems_cache.source_stamp',side_effect=AssertionError('out-of-scope stat')):
            prep=self.prep(self.audit([self.cache,self.kept])[1])[0]
        self.assertEqual(prep['cache_state'],'unknown');self.assertEqual(prep['source_stamp_status'],'not_in_scope')

    def test_symlink_reference_is_held_even_if_target_is_in_scope(self):
        alias=self.audio/'alias.wav'
        try:alias.symlink_to(self.source)
        except OSError:self.skipTest('Symlinks unavailable')
        (self.kept/'synthetic.manifest').write_bytes(manifest(alias))
        self.assertEqual(self.prep(self.audit()[1])[0]['source_stamp_status'],'linked_path')

    def test_declared_model_and_speed_profile_mismatches(self):
        profile=context({'target':'rbstemsplus','quality':'speed'})
        prep=self.prep(self.audit(profile=profile)[1])[0];self.assertEqual(prep['cache_state'],'profile_mismatch')
        self.assertEqual(prep['cache_profile_status'],'profile_mismatch')
        prep=self.prep(self.audit(profile=context({'model_sha256':'2'*64}))[1])[0]
        self.assertEqual(prep['model_status'],'model_mismatch')

    def test_m4a_discovery_and_inventory_are_case_insensitive(self):
        from discovery import scan_roots
        folder=self.root/'ni';folder.mkdir();(folder/'Example.STEM.M4A').write_bytes(ni_bytes())
        summary,rows=self.audit([folder]);self.assertEqual(summary['format_inspection']['recognized_ni_containers'],1)
        discovery=scan_roots([str(folder)],lambda *_:None,kind='assets')
        self.assertEqual(len(discovery['analysis_paths']),1)

    def test_local_moov_seek_skips_media_but_zip_remains_bounded(self):
        raw=ni_bytes();at=raw.index(b'moov')-4
        large=raw[:16]+box(b'mdat',bytes(3*1024**2))+raw[at:]
        folder=self.root/'large';folder.mkdir();(folder/'large.stem.m4a').write_bytes(large)
        summary,rows=self.audit([folder]);r=next(r for r in rows if r.get('format')=='ni_stems_v1')
        self.assertEqual(r['validation'],'recognized');self.assertLess(summary['format_inspection']['bytes_inspected'],65536)
        archive=self.root/'large.zip'
        with zipfile.ZipFile(archive,'w') as z:z.writestr('large.stem.m4a',large)
        summary,rows=self.audit([archive]);r=next(r for r in rows if 'validation' in r)
        self.assertEqual(r['validation'],'not_checked');self.assertLessEqual(summary['format_inspection']['bytes_inspected'],2*1024**2)


class EligibilityTests(unittest.TestCase):
    def test_known_provider_restrictions_and_unknown_service_ids(self):
        profile=context({'enabled':'enabled','mode':'performance'})
        source={'tracks':[{'id':'a','current_path':'spotify:track:synthetic'},
                          {'id':'b','current_path':'https://music.apple.com/track/synthetic'},
                          {'id':'c','current_path':'/Synthetic/a.wav'},
                          {'id':'d','source_evidence':{'service_id':42},'current_path':'/cached/a.mp3'}]}
        before=deepcopy(source);summary,rows=eligibility(source,profile)
        self.assertEqual([r['eligibility'] for r in rows],['blocked','blocked','candidate','unknown'])
        self.assertEqual(summary['unknown'],1);self.assertEqual(source,before)
        self.assertTrue(all(r['native_stems_readiness'] is None for r in rows))

    def test_incomplete_session_and_other_streaming_stay_unknown(self):
        summary,rows=eligibility({'tracks':[{'id':'x'}]},context())
        self.assertEqual(summary['unknown'],1)
        self.assertEqual(eligibility({'tracks':[{'source_provider':'other_streaming'}]},context({'enabled':'enabled','mode':'performance'}))[1][0]['eligibility'],'unknown')

    def test_invalid_session_values_and_fingerprint_are_rejected(self):
        for profile in ({'enabled':True},{'quality':'invented'},{'model_sha256':'short'},{'unexpected':1}):
            with self.assertRaises(ValueError):context(profile)

    def test_profile_versions_and_rebuilt_model_namespaces(self):
        from hashlib import sha256
        profile=context({'target':'rbstemsplus','enabled':'enabled','mode':'performance','quality':'quality',
                         'app_version':'7.2.19','engine_version':'0002','runtime_version':'1.18.0','model_sha256':PIONEER_MODEL,'platform':'macos','architecture':'arm64'})
        rebuilt=sha256(('rbstems-rebuild-1:'+PIONEER_MODEL).encode()).hexdigest()
        self.assertEqual(namespace_status(rebuilt,profile),'matches_declared_model')
        self.assertEqual(cache_profile(profile),'matches_declared_profile')
        self.assertEqual(cache_profile({**profile,'app_version':'7.2.99'}),'unverified_version')

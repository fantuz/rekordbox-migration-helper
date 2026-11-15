"""Synthetic Serato export contracts and independent malformed-input checks."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import json
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from serato_bridge import draft_package,preview_package,volume_relative
from serato_reader import read_database,read_crate,validate_export


def source():
    return {'id':'synthetic','scope_key':'synthetic:serato','tracks':[
        {'id':'a','title':'Synthetic 🎧 cafe\u0301','artist':'日本語','current_path':'C:/Music/Écho.wav','duration':125,'rating':5},
        {'id':'alias','title':'Other metadata','current_path':'c:/music/écho.wav'},
        {'id':'b','title':'Synthetic B','current_path':'C:/Music/B.wav'},
        {'id':'other','current_path':'D:/Music/C.wav'},
        {'id':'bad','current_path':'https://example.invalid/track.mp3'}],
        'playlists':[{'id':'folder','name':'Folder 🎧','folder':True},
                     {'id':'set','name':'Set','parent':'folder','tracks':['b','alias','a','b','other','missing'],'smart':True}],
        'capabilities':{'playlist_order':True}}


class SeratoValidationTests(unittest.TestCase):
    def test_case_aliases_reference_the_exact_database_spelling_and_keep_repetitions(self):
        original=source();before=deepcopy(original);payload,manifest=draft_package(original,'C:/')
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            tracks=read_database(archive.read('_Serato_/database V2'))
            self.assertEqual(tracks[0]['tsng'],'Synthetic 🎧 cafe\u0301');self.assertEqual(tracks[0]['tlen'],'2:05')
            self.assertEqual(tracks[0]['tart'],'日本語')
            crate=next(c for c in manifest['crates'] if c['id']=='set')
            self.assertEqual(read_crate(archive.read('_Serato_/Subcrates/'+crate['file'])),['Music/B.wav','Music/Écho.wav','Music/Écho.wav','Music/B.wav'])
            parent=next(c for c in manifest['crates'] if c['folder'])
            self.assertTrue(crate['file'].startswith(parent['file'][:-6]+'%%'))
            self.assertEqual(manifest['validation']['status'],'passed')
            self.assertFalse(manifest['validation']['serato_application_verified'])
            self.assertEqual(len(manifest['omitted_playlist_entries']),2)
            self.assertEqual(manifest['metadata_fields']['title'],2)
        self.assertEqual(original,before)

    def test_preview_lists_omissions_even_when_nothing_can_be_exported(self):
        report=preview_package(source(),'Z:/')
        self.assertFalse(report['export_ready']);self.assertEqual(report['tracks_written'],0)
        self.assertEqual(report['omitted_total'],5)
        with self.assertRaises(ValueError):draft_package(source(),'Z:/')

    def test_preview_is_bounded_but_zip_manifest_is_complete(self):
        data=source();data['tracks']=[{'id':str(i),'current_path':'D:/Music/'+str(i)+'.wav'} for i in range(120)]+[data['tracks'][0]]
        preview=preview_package(data,'C:/');self.assertEqual(len(preview['omitted']),100);self.assertEqual(preview['omitted_total'],120)
        _,manifest=draft_package(data,'C:/');self.assertEqual(len(manifest['omitted']),120)

    def test_posix_paths_remain_case_sensitive_and_uri_unicode_is_decoded(self):
        self.assertEqual(volume_relative('file://localhost/Volumes/DJ/Music/%C3%A9.wav','/Volumes/DJ'),'Music/é.wav')
        data=source();data['tracks']=[{'id':'a','current_path':'/Music/A.wav'},{'id':'b','current_path':'/Music/a.wav'}]
        self.assertEqual(draft_package(data,'/')[1]['tracks_written'],2)
        for path in ('//server/share/a.wav','C:/Music/../a.wav','C:/Music/a.wav:stream','C:/Music/\x00.wav'):
            with self.assertRaises(ValueError):volume_relative(path,'C:/')

    def test_invalid_unicode_metadata_is_reported_and_duplicate_ids_are_rejected(self):
        data=source();data['tracks'][0]['title']='bad\ud800'
        manifest=draft_package(data,'C:/')[1];self.assertEqual(manifest['omission_counts']['invalid_metadata'],1)
        data=source();data['tracks'].append(dict(data['tracks'][0]))
        with self.assertRaises(ValueError):draft_package(data,'C:/')

    def test_cycles_long_hierarchy_and_unknown_order_are_explicit(self):
        data=source();data['playlists'][0]['parent']='set';data['capabilities']['playlist_order']=False
        report=preview_package(data,'C:/')
        self.assertTrue(any('hierarchy' in row['reason'] for row in report['warnings']))
        self.assertTrue(any('order' in row['reason'] for row in report['warnings']))
        data=source();data['playlists'][0]['name']='日'*65;data['playlists'][1]['name']='本'*65
        report=preview_package(data,'C:/')
        self.assertTrue(any('flattened' in row['reason'] for row in report['warnings']))
        self.assertTrue(all(len(row['file'].encode())<=220 for row in report['crates']))

    def test_reader_rejects_truncation_bad_lengths_unicode_and_duplicate_fields(self):
        def field(tag,data):return tag+struct.pack('>I',len(data))+data
        header=field(b'vrsn','1.0/Serato ScratchLive Crate'.encode('utf-16-be'))
        for data in (b'vrs',header+b'otrk\0\0\0\xffshort',header+field(b'otrk',field(b'ptrk',b'\x00')),
                     header+field(b'otrk',field(b'ptrk',b'\xd8\x00')),
                     header+field(b'otrk',field(b'ptrk',b'\0a')*2),header+field(b'otrk',field(b'ptrk','../x'.encode('utf-16-be')))):
            with self.assertRaises(ValueError):read_crate(data)

    def test_validator_rejects_changed_metadata_order_and_missing_references(self):
        payload,manifest=draft_package(source(),'C:/')
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            database=archive.read('_Serato_/database V2');records=read_database(database)
            crates={row['file']:archive.read('_Serato_/Subcrates/'+row['file']) for row in manifest['crates']}
        expected={name:read_crate(data) for name,data in crates.items()}
        changed=deepcopy(records);changed[0]['tsng']='Changed'
        with self.assertRaises(ValueError):validate_export(database,crates,changed,expected)
        changed=deepcopy(expected);key=next(k for k,v in changed.items() if v);changed[key][0],changed[key][1]=changed[key][1],changed[key][0]
        with self.assertRaises(ValueError):validate_export(database,crates,records,changed)
        with self.assertRaises(ValueError):validate_export(database,crates,records,{})

    def test_preview_api_is_guarded_and_does_not_write_source_metadata(self):
        import app
        from workbench_store import Store
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'DATA',Path(tmp)):
            store=Store(Path(tmp)/'workbench-sidecar.sqlite3');sid=store.save_snapshot(source(),'Synthetic')['id'];before=store.snapshot(sid)
            client=app.app.test_client();body={'snapshot':sid,'volume_root':'C:/'}
            self.assertEqual(client.post('/api/intelligence/serato/preview',json=body).status_code,403)
            response=client.post('/api/intelligence/serato/preview',json=body,headers={'X-Workbench-Token':app.TOKEN})
            self.assertEqual(response.status_code,200);self.assertTrue(response.json['export_ready'])
            self.assertEqual(store.snapshot(sid),before)

if __name__=='__main__':unittest.main()

"""Destination path contracts with real encrypted/XML export copies."""
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote
import zipfile

import app
from audio_paths import validate as audio_mappings
from engine import export_xml,parse_xml,open_master
from export_references import target_info,validate_reference,validate_export
from file_workflow import prepare_export
from native_export import mutable_copy,export_native
from serato_paths import resolve_serato_profile
from test_support import workspace_client
from track_playback import available_audio
from workbench_store import Store


def catalog(path='D:/Music/Café.wav',target='auto'):
    uri='file://localhost/'+quote(path.lstrip('/'),safe='/:')
    return SimpleNamespace(tracks={'one':{'title':'Synthetic track','current_path':path,'xml_location':uri,'october_xml':True}},
                           metadata={'export_target':target})


class ExportReferenceTests(unittest.TestCase):
    def test_host_does_not_choose_the_reference_target(self):
        for host in ('linux','darwin','win32'):
            with patch('sys.platform',host):
                self.assertEqual(target_info(catalog())['target'],'windows')
                self.assertEqual(target_info(catalog('/Volumes/DJ/Café.wav'))['target'],'macos')
        mixed=catalog();mixed.tracks['two']={'current_path':'/Users/DJ/Music/B.wav'}
        self.assertIsNone(target_info(mixed)['target'])
        with self.assertRaisesRegex(ValueError,'mixed or unknown'):validate_export(mixed,{})
        self.assertIsNone(target_info(catalog('/Music/A.wav'))['target'])
        for root in ('/','/mnt/Windows','/media/disk'):
            with self.assertRaises(ValueError):resolve_serato_profile(root,host='linux')
        self.assertEqual(resolve_serato_profile('/',profile='macos',host='linux')['target'],'macos')

    def test_destination_validation_preserves_reviewed_uri_and_blocks_mounts(self):
        uri='file://localhost/D:/Music/Caf%C3%A9%20%23%25.wav'
        self.assertEqual(validate_reference(uri,'windows'),uri)
        self.assertEqual(validate_reference('file://server/share/Music/A.wav','windows'),'file://server/share/Music/A.wav')
        for bad in ('file:///media/disk/A.wav','file:///mnt/Windows/A.wav','file:///home/dj/A.wav',
                    'file:///D:/Music/%2e%2e/A.wav','file:///D:/Music/A.wav?download=1',
                    'file:///D:/Music/A.wav:stream','file:///D:/Music/%zz.wav'):
            for target in ('windows','macos'):
                with self.subTest(uri=bad,target=target),self.assertRaises(ValueError):
                    validate_reference(bad,target)
        with self.assertRaises(ValueError):validate_reference(uri,'macos')
        with self.assertRaisesRegex(ValueError,'playback mapping'):
            validate_reference('file:///Volumes/MountedWindows/A.wav','macos',
                [{'local_root':'/Volumes/MountedWindows','recorded_root':'D:/'}])

    def test_playback_alias_detection_uses_logical_windows_paths(self):
        aliases=[{'recorded_root':'E:/Music','local_root':'C:/MountedWindows/Music'}]
        for uri in ('file:///c:/mountedwindows/music/A.wav','file:///C:/MountedWindows/./Music/A.wav'):
            with self.subTest(uri=uri),self.assertRaisesRegex(ValueError,'playback mapping'):
                validate_reference(uri,'windows',aliases)
        self.assertEqual(validate_reference('file:///C:/MountedWindows/Music2/A.wav','windows',aliases),
                         'file:///C:/MountedWindows/Music2/A.wav')

    def test_platform_change_requires_remaining_references_to_be_reviewed(self):
        c=catalog(target='macos')
        with self.assertRaisesRegex(ValueError,'other platform'):validate_export(c,{})
        uri='file:///Volumes/DJ/Caf%C3%A9.wav'
        self.assertEqual(validate_export(c,{'one':uri}),'macos')
        with self.assertRaises(ValueError):validate_export(c,{'one':'file:///media/disk/A.wav'})
        self.assertEqual(validate_export(c,{},retired={'one'}),'macos')

    def test_manual_and_saved_inventory_actions_validate_the_current_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=catalog()
            session={'id':'a'*32,'name':'Fixture','metadata':{'name':'Fixture'},'catalog':c,
                     'decisions':{},'relocations':{},'events':[],'policy':'newest','backup_acknowledged':None}
            c.counts={}
            with patch.object(app,'DATA',root),patch.object(app,'sessions',{session['id']:session}),patch.object(app,'active',session['id']):
                client=workspace_client(app);headers={'X-Workbench-Token':app.TOKEN}
                for uri in ('file:///mnt/disk/A.wav','file:///Users/DJ/A.wav'):
                    self.assertEqual(client.post('/api/relocation',json={'track_id':'one','uri':uri},headers=headers).status_code,400)
                self.assertEqual(session['relocations'],{})
                uri='file:///D:/New/A.wav'
                self.assertEqual(client.post('/api/relocation',json={'track_id':'one','uri':uri},headers=headers).status_code,200)
                before=app.summary(session)['revision']
                self.assertEqual(client.post('/api/export-target',json={'target':'macos'},headers=headers).status_code,200)
                self.assertNotEqual(before,app.summary(session)['revision'])
                self.assertEqual(client.post('/api/relocation',json={'track_id':'one','uri':uri},headers=headers).status_code,400)
                with patch('media_recovery.stage_candidate',return_value='file:///mnt/old/A.wav'):
                    session['inventory']={'scan_id':'old','matches':{'one':{}}}
                    response=client.post('/api/inventory/stage',json={'workspace':session['id'],'scan_id':'old','track_id':'one'},headers=headers)
                    self.assertEqual(response.status_code,400)
                self.assertEqual(session['relocations'],{'one':uri})
                self.assertEqual(client.post('/api/relocation',json={'track_id':'one','uri':''},headers=headers).status_code,200)

    def test_real_xml_and_zip_exports_keep_recorded_paths_after_local_preview(self):
        for recorded in ('D:/Music/Café.wav','/Volumes/DJ/Music/Café.wav'):
            with self.subTest(recorded=recorded),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);audio=root/'Café.wav';audio.write_bytes(b'synthetic audio')
                prefix=recorded.rsplit('/',1)[0]
                aliases=audio_mappings([{'recorded_root':prefix,'local_root':str(root)}])
                c=catalog(recorded);before_tracks=deepcopy(c.tracks)
                self.assertEqual(available_audio(c.tracks['one'],aliases),audio.resolve())
                master=root/'source.db'
                with closing(mutable_copy(master)) as db:
                    db.executescript("""CREATE TABLE djmdContent(ID TEXT,FolderPath TEXT,OrgFolderPath TEXT,
                        ServiceID INTEGER,rb_local_deleted INTEGER,rb_local_usn INTEGER,rb_local_synced INTEGER,updated_at TEXT);
                        CREATE TABLE agentRegistry(registry_id TEXT,int_1 INTEGER,updated_at TEXT);
                        INSERT INTO agentRegistry VALUES('localUpdateCount',0,'old');""")
                    db.execute("INSERT INTO djmdContent VALUES('one',?,?,0,0,0,1,'old')",(recorded,recorded));db.commit()
                backup=root/'source.zip';xml=root/'source.xml'
                with zipfile.ZipFile(backup,'w') as archive:
                    archive.write(master,'master.db');archive.writestr('contents.xml','<ROOT><VALUE name="CONTENT_NUM" val="1"/></ROOT>')
                xml.write_text('<DJ_PLAYLISTS><PRODUCT Version="7.0"/><COLLECTION Entries="1"><TRACK TrackID="one" Location="'+c.tracks['one']['xml_location']+'"/></COLLECTION><PLAYLISTS/></DJ_PLAYLISTS>',encoding='utf-8')
                originals=(backup.read_bytes(),xml.read_bytes())
                c.metadata.update(zip_path=str(backup),xml_path=str(xml),version='7.0',_audio_access_mappings=aliases)
                result=prepare_export(c,{}, {},{'id':'test'},root/'exports','a'*32,'pair',lambda *_:None)
                folder=Path(result['directory'])
                self.assertEqual(parse_xml(folder/'edited-collection.xml',lambda *_:None)[0]['one']['attrs']['Location'],c.tracks['one']['xml_location'])
                with zipfile.ZipFile(folder/'edited-library.zip') as archive:
                    check=root/'check.db';check.write_bytes(archive.read('master.db'))
                with closing(open_master(check.resolve())) as db:
                    self.assertEqual(tuple(db.execute('SELECT FolderPath,OrgFolderPath FROM djmdContent').fetchone()),(recorded,recorded))
                self.assertEqual(c.tracks,before_tracks);self.assertEqual((backup.read_bytes(),xml.read_bytes()),originals)
                # Saved edits from older versions fail before either writer opens an output.
                for writer in (export_xml,export_native):
                    with self.assertRaises(ValueError):writer(c,{}, {'one':audio.resolve().as_uri()},root/'unsafe',lambda *_:None)
                self.assertFalse((root/'unsafe').exists())
                self.assertNotIn(str(root),parse_xml(folder/'edited-collection.xml',lambda *_:None)[0]['one']['attrs']['Location'])


if __name__=='__main__':unittest.main()

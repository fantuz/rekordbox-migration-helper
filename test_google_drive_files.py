"""Drive parent identities, duplicate names and explicit selected-file folders."""
from copy import deepcopy
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import google_drive_files as files


def folder(identity,name,parent=None):
    return {'id':identity,'name':name,'mimeType':files.FOLDER_MIME,
            'parents':[parent] if parent else [],'trashed':False}


def audio(identity='file-one',name='Track.mp3',parent='album-folder'):
    return {'id':identity,'name':name,'mimeType':'audio/mpeg','parents':[parent],
            'size':'12','version':'1','sha256Checksum':'a'*64,'trashed':False,
            'capabilities':{'canDownload':True}}


class GoogleDriveFileTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();self.local=self.root/'Selected files';self.local.mkdir()
        self.owner=SimpleNamespace(DATA=self.root/'work')
        self.state={'connected':True,'connection_id':'invented-connection','account':{'account_id':'invented-user'}}
        self.connection=SimpleNamespace(status=Mock(side_effect=lambda:deepcopy(self.state)),rpc=Mock(side_effect=self.rpc))
        self.entries=[folder('music-root','Music'),folder('album-folder','Album','music-root'),audio()]
        for name,value in [('cloud_attachments.allowed_roots',[self.root]),('cloud_attachments.provider_roots',[])]:
            stub=patch(name,return_value=value);stub.start();self.addCleanup(stub.stop)
        self.mapping=files.mapping_record(self.connection,str(self.local),'music-root',owner=self.owner,
                                         recorded_root='D:/Old music')
        self.connection.rpc.reset_mock()

    def rpc(self,route,payload):
        if route=='files/get':
            identity=payload['fileId']
            if identity=='root':return folder('drive-root','My Drive')
            return deepcopy(next(row for row in self.entries if row['id']==identity))
        if route!='files/list':raise AssertionError(route)
        parents=re.findall(r"'([A-Za-z0-9_-]+)' in parents",payload['q'])
        rows=[row for row in self.entries if any(parent in row['parents'] for parent in parents)]
        match=re.search(r"and name = '((?:\\.|[^'\\])*)'",payload['q'])
        if match:
            name=match.group(1).replace("\\'", "'").replace('\\\\','\\')
            rows=[row for row in rows if row['name']==name]
        if "and mimeType = '" in payload['q']:rows=[row for row in rows if row['mimeType']==files.FOLDER_MIME]
        return {'files':deepcopy(rows),'incompleteSearch':False}

    def inventory(self):return files.inventory(self.connection,self.mapping,lambda *_:None)

    def test_selected_download_folder_needs_no_provider_desktop_root(self):
        self.assertEqual(Path(self.mapping['local_root']),self.local)
        self.assertEqual(self.mapping['location_role'],'selected_download_folder')
        result=files.target({'current_path':r'D:\Old music\Album\Track.mp3'},self.mapping)
        self.assertEqual(result['relative_path'],'Album/Track.mp3')
        self.assertEqual(result['local_path'],str(self.local/'Album'/'Track.mp3'))
        self.assertIsNone(files.target({'current_path':'D:/Other/Track.mp3'},self.mapping))

    def test_inventory_uses_exact_parent_hierarchy_and_case(self):
        entries,complete=self.inventory()
        self.assertTrue(complete);self.assertEqual(files.lookup(entries,'Album/Track.mp3')[1],'present')
        # Windows references can lose case. A differently cased candidate is
        # uncertainty, never a guessed ID or a confirmed absence.
        self.assertEqual(files.lookup(entries,'album/track.mp3')[1],'unverified')
        self.assertEqual(len(self.connection.rpc.call_args_list),2)
        self.assertTrue(all(' in parents' in call.args[1]['q'] for call in self.connection.rpc.call_args_list))

    def test_duplicate_file_names_are_ambiguous_not_first_match(self):
        self.entries.append(audio('file-two'))
        entries,complete=self.inventory()
        self.assertTrue(complete);self.assertEqual(files.lookup(entries,'Album/Track.mp3'),(None,'ambiguous'))
        with self.assertRaisesRegex(ValueError,'duplicate names'):
            files.resolve_file(self.connection,self.mapping,'Album/Track.mp3')

    def test_duplicate_folder_names_hold_every_descendant(self):
        self.entries.append(folder('another-album','Album','music-root'))
        entries,complete=self.inventory()
        self.assertTrue(complete);self.assertEqual(files.lookup(entries,'Album/Track.mp3'),(None,'ambiguous'))
        self.assertEqual(self.connection.rpc.call_count,1)
        choices=files.browse_folders(self.connection,'music-root')
        self.assertEqual({row['id'] for row in choices['rows']},{'album-folder','another-album'})

    def test_shortcuts_and_cloud_documents_do_not_become_missing_or_audio(self):
        self.entries=[folder('music-root','Music'),
                      {**folder('shortcut','Album','music-root'),'mimeType':files.SHORTCUT_MIME},
                      {**audio('doc','Track.mp3','music-root'),'mimeType':'application/vnd.google-apps.document'}]
        entries,complete=self.inventory()
        self.assertTrue(complete)
        for path in ('Album/Track.mp3','Track.mp3'):
            self.assertEqual(files.lookup(entries,path),(None,'unverified'))

    def test_incomplete_search_keeps_observed_names_unverified(self):
        self.entries=[folder('music-root','Music'),audio(parent='music-root')]
        self.connection.rpc.side_effect=lambda route,payload:{'files':deepcopy(self.entries[1:]),'incompleteSearch':True}
        entries,complete=self.inventory()
        self.assertFalse(complete);self.assertEqual(files.lookup(entries,'Track.mp3'),(None,'unverified'))
        self.assertEqual(files.lookup(entries,'Anything.mp3'),(None,'unverified'))

    def test_explicit_request_limit_never_claims_complete_inventory(self):
        with patch.object(files,'MAX_PAGES',1):entries,complete=self.inventory()
        self.assertFalse(complete);self.assertNotIn('Album/Track.mp3',entries)

    def test_unicode_normalization_collisions_are_ambiguous(self):
        self.entries.extend([audio('unicode-one','cafe\u0301.mp3'),audio('unicode-two','café.mp3')])
        entries,_=self.inventory()
        self.assertEqual(files.lookup(entries,'Album/café.mp3'),(None,'ambiguous'))

    def test_malformed_outside_parent_or_cursor_loop_fails_the_scan(self):
        for response in ({'files':[audio(parent='outside')]},
                         {'files':[],'nextPageToken':'same'}):
            with self.subTest(response=response):
                self.connection.rpc.side_effect=lambda *_args,**_kwargs:deepcopy(response)
                with self.assertRaises(ValueError):self.inventory()

    def test_cyclic_folder_identity_is_rejected(self):
        self.entries.append(folder('music-root','Cycle','music-root'))
        with self.assertRaisesRegex(ValueError,'cyclic|ambiguous'):self.inventory()

    def test_folder_links_are_parsed_without_fetching_arbitrary_urls(self):
        self.assertEqual(files.folder_id('https://drive.google.com/drive/u/0/folders/music-root?usp=sharing'),'music-root')
        for value in ('https://example.invalid/drive/folders/music-root','https://drive.google.com@evil.invalid/drive/folders/music-root',
                      'https://drive.google.com/drive/folders/../private','../music-root'):
            with self.subTest(value=value),self.assertRaises(ValueError):files.folder_id(value)
        self.connection.rpc.assert_not_called()

    def test_shared_drive_and_all_files_mode_are_not_silently_supported(self):
        self.entries[0]['driveId']='shared-drive'
        with self.assertRaisesRegex(ValueError,'Shared Drive'):
            files.mapping_record(self.connection,str(self.local),'music-root',owner=self.owner)
        with self.assertRaisesRegex(ValueError,'selected-file'):
            files.mapping_record(self.connection,str(self.local),'music-root',owner=self.owner,sync_mode='all')

    def test_binding_holds_changed_account_and_replaced_local_folder(self):
        before=files.binding(self.connection,self.mapping)
        self.state['connection_id']='different-authorization'
        self.assertNotEqual(files.binding(self.connection,self.mapping),before)
        self.state['account']['account_id']='other-account'
        with self.assertRaises(ValueError):files.binding(self.connection,self.mapping)
        self.state['account']['account_id']='invented-user'
        self.local.rename(self.root/'Previous selected files');self.local.mkdir()
        with self.assertRaises(ValueError):files.binding(self.connection,self.mapping)


if __name__=='__main__':unittest.main()

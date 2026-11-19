"""Google one-file transfers use real temporary files and invented metadata."""
from copy import deepcopy
from hashlib import md5,sha256
from io import BytesIO
import errno
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import dropbox_download as common
import google_drive_download as downloads


class Response:
    def __init__(self,data,metadata,on_read=None):
        self.body=BytesIO(data);self.metadata=deepcopy(metadata)
        self.on_read=on_read;self.reads=0;self.closed=False
    def read(self,size):
        self.reads+=1
        if self.on_read:self.on_read(self.reads)
        return self.body.read(size)
    def __enter__(self):return self
    def __exit__(self,*_):self.closed=True;self.body.close()


class Connection:
    def __init__(self,response,metadata):
        self.response=response;self.metadata=deepcopy(metadata)
        self.identity='invented-google-connection';self.connected=True
        self.calls=[];self.metadata_calls=[]
    def status(self):return {'connected':self.connected,'connection_id':self.identity}
    def rpc(self,route,payload):
        self.metadata_calls.append((route,payload))
        assert route=='files/get' and payload['fileId']==self.metadata['id']
        return deepcopy(self.metadata)
    def download(self,identity,version=None):
        self.calls.append((identity,version));return self.response


class GoogleDriveDownloadTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.base=Path(temporary.name).resolve()
        self.root=self.base/'Selected cache';self.root.mkdir()
        self.album=self.root/'Album';self.album.mkdir()
        self.target=self.album/'Invented track.mp3'
        self.staging=self.base/'private-downloads'
        self.payload=b'Invented Google Drive file fixture; no music or account.'
        self.metadata={'id':'invented-file-id','name':self.target.name,'version':'12',
                       'parents':['invented-folder'],'size':str(len(self.payload)),
                       'mimeType':'audio/mpeg','sha256Checksum':sha256(self.payload).hexdigest(),
                       'md5Checksum':md5(self.payload,usedforsecurity=False).hexdigest(),
                       'modifiedTime':'2026-01-02T03:04:05Z','trashed':False,
                       'capabilities':{'canDownload':True}}
        self.response=Response(self.payload,self.metadata)
        self.connection=Connection(self.response,self.metadata)
    def download(self,**kwargs):
        return downloads.download_file(self.connection,self.metadata,self.target,self.root,
            staging_dir=self.staging,managed_root=self.root,**kwargs)
    def assert_clean(self):
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.album.iterdir()),[])
        if self.staging.exists():self.assertEqual(list(self.staging.iterdir()),[])

    def test_sha256_downloads_one_pinned_file_and_checks_before_after(self):
        result=self.download(expected_target=downloads.prepare_target(self.target,self.root))
        self.assertEqual(self.target.read_bytes(),self.payload)
        self.assertEqual(result['content_hash'],sha256(self.payload).hexdigest())
        self.assertEqual(result['checksum_algorithm'],'sha256')
        self.assertEqual(result['file_id'],self.metadata['id'])
        self.assertEqual(result['version'],'12')
        self.assertEqual(self.connection.calls,[('invented-file-id','12')])
        self.assertEqual(len(self.connection.metadata_calls),2)
        self.assertTrue(self.response.closed)
        self.assertEqual(list(self.staging.iterdir()),[])

    def test_google_md5_checksum_supported_when_sha256_not_supplied(self):
        for value in (self.metadata,self.response.metadata,self.connection.metadata):
            value.pop('sha256Checksum')
        result=self.download()
        self.assertEqual(result['checksum_algorithm'],'md5')
        self.assertEqual(result['content_hash'],md5(self.payload,usedforsecurity=False).hexdigest())

    def test_sha256_is_preferred_over_validly_shaped_legacy_md5(self):
        for value in (self.metadata,self.response.metadata,self.connection.metadata):
            value['md5Checksum']='0'*32
        self.assertEqual(self.download()['checksum_algorithm'],'sha256')

    def test_metadata_only_preparation_creates_nothing(self):
        with patch.object(Path,'open',side_effect=AssertionError('Opened existing file')):
            state=downloads.prepare_target(self.target,self.root)
        self.assertEqual(state['local_path'],str(self.target))
        self.assertEqual(self.connection.calls,[])
        self.assertEqual(self.connection.metadata_calls,[])
        self.assertFalse(self.staging.exists())

    def test_missing_checksum_never_opens_content(self):
        self.metadata.pop('md5Checksum');self.metadata.pop('sha256Checksum')
        with self.assertRaisesRegex(ValueError,'checksum'):self.download()
        self.assertEqual(self.connection.calls,[]);self.assert_clean()

    def test_invalid_and_nonbinary_metadata_never_opens_content(self):
        values=({'version':'not-a-version'},{'version':True},{'size':'no'},{'size':True},
                {'size':'0'},{'size':str(common.MAX_FILE_BYTES+1)},
                {'mimeType':'application/vnd.google-apps.document'},
                {'mimeType':'application/vnd.google-apps.shortcut'},
                {'mimeType':'application/vnd.google-apps.folder'},
                {'trashed':True},{'trashed':'true'},{'capabilities':{'canDownload':False}},
                {'capabilities':{}},{'capabilities':None},{'sha256Checksum':'bad'},
                {'parents':['duplicate','duplicate']},{'name':'bad\nname.mp3'},
                {'modifiedTime':'2026-01-01'},{'driveId':{}},{'id':'bad/id'})
        original=deepcopy(self.metadata)
        for update in values:
            with self.subTest(update=update):
                self.metadata={**original,**update}
                with self.assertRaises(ValueError):self.download()
                self.assertEqual(self.connection.calls,[]);self.assert_clean()

    def test_initial_remote_revision_or_parent_change_prevents_content(self):
        for field,value in (('version','13'),('parents',['another-folder']),
                            ('name','Renamed.mp3'),('driveId','another-drive'),
                            ('sha256Checksum','0'*64)):
            original=deepcopy(self.connection.metadata)
            with self.subTest(field=field):
                self.connection.metadata[field]=value
                with self.assertRaisesRegex(ValueError,'details changed'):self.download()
                self.assertEqual(self.connection.calls,[]);self.assert_clean()
            self.connection.metadata=original

    def test_stream_metadata_must_still_match_approval(self):
        self.response.metadata['version']='99'
        with self.assertRaisesRegex(ValueError,'details changed'):self.download()
        self.assertTrue(self.response.closed);self.assert_clean()

    def test_changed_revision_during_download_is_not_published(self):
        self.response.on_read=lambda _count:self.connection.metadata.update(version='13')
        with self.assertRaisesRegex(ValueError,'details changed'):self.download()
        self.assertTrue(self.response.closed);self.assert_clean()

    def test_changed_parent_location_during_download_is_not_published(self):
        self.response.on_read=lambda _count:self.connection.metadata.update(parents=['moved-folder'])
        with self.assertRaisesRegex(ValueError,'details changed'):self.download()
        self.assert_clean()

    def test_changed_modification_time_during_download_is_held(self):
        self.response.on_read=lambda _count:self.connection.metadata.update(modifiedTime='2026-02-02T03:04:05Z')
        with self.assertRaisesRegex(ValueError,'details changed'):self.download()
        self.assert_clean()

    def test_post_download_permission_failure_leaves_no_local_file(self):
        self.response.on_read=lambda _count:self.connection.metadata.update(capabilities={'canDownload':False})
        with self.assertRaises(ValueError):self.download()
        self.assert_clean()

    def test_interrupted_stream_cleans_staging(self):
        def interrupt(_count):raise OSError('Invented network interruption')
        self.response.on_read=interrupt
        with self.assertRaises(OSError):self.download()
        self.assertTrue(self.response.closed);self.assert_clean()

    def test_short_or_extra_content_is_rejected(self):
        for data in (self.payload[:-1],self.payload+b'x'):
            self.response=Response(data,self.metadata);self.connection.response=self.response
            with self.subTest(size=len(data)),self.assertRaises(ValueError):self.download()
            self.assertTrue(self.response.closed);self.assert_clean()

    def test_corrupt_same_length_sha256_and_md5_are_rejected(self):
        for algorithm in ('sha256','md5'):
            if algorithm=='md5':
                for value in (self.metadata,self.connection.metadata):value.pop('sha256Checksum',None)
            self.response=Response(b'X'+self.payload[1:],self.metadata);self.connection.response=self.response
            with self.subTest(algorithm=algorithm),self.assertRaisesRegex(ValueError,'does not match'):self.download()
            self.assert_clean()

    def test_existing_file_is_never_opened_or_overwritten(self):
        self.target.write_bytes(b'Keep original private file')
        with self.assertRaisesRegex(ValueError,'already exists'):self.download()
        self.assertEqual(self.target.read_bytes(),b'Keep original private file')
        self.assertEqual(self.connection.calls,[])

    def test_existing_placeholder_uses_play_instead(self):
        original=Path.lstat
        self.target.write_bytes(b'fixture')
        def attributes(path,*args,**kwargs):
            info=original(path,*args,**kwargs)
            if path==self.target:return SimpleNamespace(st_file_attributes=0x1000)
            return info
        with patch.object(Path,'lstat',attributes):
            with self.assertRaisesRegex(ValueError,'placeholder'):self.download()
        self.assertEqual(self.connection.calls,[])
        self.assertEqual(self.target.read_bytes(),b'fixture')

    def test_private_staging_is_outside_every_provider_tree(self):
        other=self.base/'Other provider';other.mkdir()
        self.staging=other/'private-looking'
        with self.assertRaisesRegex(ValueError,'every configured cloud folder'):
            self.download(excluded_roots=[str(other)])
        self.assertFalse(self.staging.exists());self.assertEqual(self.connection.calls,[])
        self.assert_clean()

    def test_discovered_other_provider_tree_excluded_even_if_caller_omits_it(self):
        other=self.base/'Other detected provider';other.mkdir()
        self.staging=other/'private-looking'
        with patch('cloud_locations.provider_roots',return_value=[{'root':str(other),'kind':'dropbox'}]):
            with self.assertRaisesRegex(ValueError,'every configured cloud folder'):self.download()
        self.assertFalse(self.staging.exists());self.assertEqual(self.connection.calls,[])

    def test_staging_under_selected_cache_is_rejected_before_content(self):
        self.staging=self.root/'private-looking'
        with self.assertRaises(ValueError):self.download()
        self.assertFalse(self.staging.exists());self.assertEqual(self.connection.calls,[])

    def test_invalid_cloud_boundaries_do_not_open_content_or_create_staging(self):
        for root in ('relative-folder','//server/share',r'\\server\share','/bad\nfolder'):
            with self.subTest(root=root),self.assertRaises(ValueError):
                self.download(excluded_roots=[root])
            self.assertFalse(self.staging.exists());self.assertEqual(self.connection.calls,[])

    def test_cross_volume_staging_is_rejected_before_content(self):
        self.staging.mkdir(mode=0o700);staging_inode=self.staging.stat().st_ino
        original=common._identity
        def identity(info):
            device,inode=original(info)
            return [device+1 if inode==staging_inode else device,inode]
        with patch.object(common,'_identity',side_effect=identity):
            with self.assertRaisesRegex(ValueError,'another volume'):self.download()
        self.assertEqual(self.connection.calls,[]);self.assert_clean()

    def test_unsupported_hardlinks_never_replace_an_existing_destination(self):
        with patch.object(common.os,'link',side_effect=OSError(errno.EXDEV,'Unsupported filesystem')):
            with self.assertRaisesRegex(ValueError,'cannot safely publish'):self.download()
        self.assert_clean()

    def test_connection_change_and_user_cancellation_leave_no_final_file(self):
        self.response.on_read=lambda _count:setattr(self.connection,'identity','changed-account')
        with self.assertRaisesRegex(ValueError,'authorization changed'):self.download()
        self.assert_clean()
        self.connection.identity='invented-google-connection'
        self.response=Response(self.payload,self.metadata);self.connection.response=self.response
        def cancel():raise InterruptedError('Cancelled by the user')
        with self.assertRaises(InterruptedError):self.download(validate=cancel)
        self.assert_clean()

    def test_changed_parent_and_new_file_during_stream_are_held(self):
        def create(_count):self.target.write_bytes(b'Another process created this')
        self.response.on_read=create
        with self.assertRaisesRegex(ValueError,'already exists'):self.download()
        self.assertEqual(self.target.read_bytes(),b'Another process created this')
        self.assertEqual(list(self.staging.iterdir()),[])

    def test_destination_and_parent_symlinks_are_not_followed(self):
        outside=self.base/'Outside';outside.mkdir();private=outside/'Private.mp3';private.write_bytes(b'Private')
        try:self.target.symlink_to(private)
        except OSError:self.skipTest('Symbolic links unavailable')
        with self.assertRaises(ValueError):self.download()
        self.assertEqual(private.read_bytes(),b'Private');self.assertEqual(self.connection.calls,[])
        self.target.unlink();self.album.rmdir();self.album.symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError):self.download()
        self.assertFalse((outside/self.target.name).exists());self.assertEqual(self.connection.calls,[])

    def test_directory_identity_binds_confirmation(self):
        approved=downloads.prepare_target(self.target,self.root)
        self.album.rename(self.root/'Old album');self.album.mkdir()
        with self.assertRaisesRegex(ValueError,'destination changed'):self.download(expected_target=approved)
        self.assertEqual(self.connection.calls,[]);self.assert_clean()

    @unittest.skipUnless(os.name=='posix','POSIX permission bits')
    def test_result_and_staging_are_private(self):
        self.download()
        self.assertEqual(self.target.stat().st_mode&0o777,0o600)
        self.assertEqual(self.staging.stat().st_mode&0o777,0o700)


if __name__=='__main__':unittest.main()

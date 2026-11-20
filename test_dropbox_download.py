"""One-track download safety: real local files, synthetic Dropbox transport."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import errno
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import dropbox_download as downloads


def content_hash(data):
    block = 4 * 1024**2
    return sha256(b''.join(sha256(data[offset:offset + block]).digest()
                           for offset in range(0, len(data), block))).hexdigest()


class SyntheticResponse:
    def __init__(self, data, metadata, on_read=None):
        self.body = BytesIO(data)
        self.metadata = deepcopy(metadata)
        self.on_read = on_read
        self.reads = 0
        self.closed = False

    def read(self, size):
        self.reads += 1
        if self.on_read:
            self.on_read(self.reads)
        return self.body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True
        self.body.close()


class SyntheticConnection:
    def __init__(self, response):
        self.response = response
        self.connected = True
        self.identity = 'synthetic-account-connection'
        self.calls = []

    def status(self):
        return {'connected': self.connected, 'connection_id': self.identity}

    def download(self, identity, rev, namespace):
        self.calls.append((identity, rev, namespace))
        return self.response


class DropboxDownloadTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / 'Dropbox (Invented team)'
        self.root.mkdir()
        self.album = self.root / 'Customer' / 'Album'
        self.album.mkdir(parents=True)
        self.target = self.album / 'Synthetic song.mp3'
        self.staging = self.base / 'private-downloads'
        self.payload = b'Synthetic audio bytes; no account, song, or network is used.'
        self.metadata = {
            '.tag': 'file', 'id': 'id:synthetic-file', 'rev': 'approved-revision',
            'size': len(self.payload), 'content_hash': content_hash(self.payload),
            'server_modified': '2025-04-03T02:01:00Z', 'is_downloadable': True,
        }
        self.response = SyntheticResponse(self.payload, self.metadata)
        self.connection = SyntheticConnection(self.response)

    def download(self, **kwargs):
        return downloads.download_file(
            self.connection, self.metadata, self.target, self.root, 'synthetic-namespace',
            staging_dir=self.staging, managed_root=self.root, **kwargs)

    def assert_clean(self):
        self.assertFalse(self.target.exists())
        if self.staging.exists():
            self.assertEqual(list(self.staging.iterdir()), [])
        self.assertEqual(list(self.album.iterdir()), [])

    def test_downloads_only_selected_revision_to_standard_path(self):
        state = downloads.prepare_target(self.target, self.root)
        result = self.download(expected_target=state)
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertEqual(result.pop('file_identity'),downloads.resident_file_identity(self.target,self.root,state))
        self.assertEqual(result, {'downloaded': True, 'local_path': str(self.target),
                                 'bytes': len(self.payload), 'content_hash': content_hash(self.payload)})
        self.assertEqual(self.connection.calls,
                         [('id:synthetic-file', 'approved-revision', 'synthetic-namespace')])
        self.assertTrue(self.response.closed)
        self.assertEqual(list(self.staging.iterdir()), [])

    def test_progress_measures_streamed_and_verified_bytes_for_one_file(self):
        state=downloads.prepare_target(self.target,self.root);steps=[];verified=[]
        with patch.object(downloads,'CHUNK_BYTES',8):
            result=self.download(expected_target=state,progress=lambda _,step:steps.append(step.detail))
            downloads.verify_downloaded_content(self.target,self.root,state,result['file_identity'],len(self.payload),
                                               self.metadata['content_hash'],byte_progress=verified.append)
        transfer=[step for step in steps if step['phase']=='Downloading audio']
        self.assertEqual({step['item'] for step in steps},{self.target.name})
        self.assertEqual({step['total'] for step in transfer},{len(self.payload)})
        self.assertEqual(sorted(set(step['completed'] for step in transfer)),[*range(0,len(self.payload),8),len(self.payload)])
        self.assertEqual(sorted(set(verified)),[*range(0,len(self.payload),8),len(self.payload)])
        self.assertEqual(steps[-1]['completed'],len(self.payload));self.assertEqual(len(self.connection.calls),1)

    def test_multiblock_hash_with_unaligned_transport_chunks(self):
        self.payload = b'abcdefg' * (4 * 1024**2 // 7 + 2)
        self.metadata.update(size=len(self.payload), content_hash=content_hash(self.payload))
        self.response = SyntheticResponse(self.payload, self.metadata)
        self.connection.response = self.response
        with patch.object(downloads, 'CHUNK_BYTES', 109001):
            result = self.download()
        self.assertGreater(self.response.reads, 30)
        self.assertEqual(result['content_hash'], content_hash(self.payload))

    def test_final_play_verification_reads_only_approved_resident_file_with_readonly_flags(self):
        state=downloads.prepare_target(self.target,self.root);result=self.download(expected_target=state)
        with patch.object(downloads.os,'open',wraps=os.open) as opened,patch.object(downloads.os,'read',wraps=os.read) as read:
            downloads.verify_downloaded_content(self.target,self.root,state,result['file_identity'],
                                                len(self.payload),content_hash(self.payload))
        opened.assert_called_once()
        self.assertEqual(opened.call_args.args[0],self.target)
        flags=opened.call_args.args[1]
        self.assertFalse(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC))
        self.assertEqual(flags&getattr(os,'O_NOFOLLOW',0),getattr(os,'O_NOFOLLOW',0))
        self.assertEqual(flags&getattr(os,'O_NONBLOCK',0),getattr(os,'O_NONBLOCK',0))
        self.assertTrue(read.called)

    def test_final_play_hash_detects_same_size_change_even_when_all_metadata_is_unchanged(self):
        state=downloads.prepare_target(self.target,self.root);result=self.download(expected_target=state)
        original=self.target.stat();self.target.write_bytes(b'X'*len(self.payload))
        os.utime(self.target,ns=(original.st_atime_ns,original.st_mtime_ns))
        with patch.object(downloads,'resident_file_identity',return_value=result['file_identity']),patch.object(downloads.os,'fstat',return_value=original):
            with self.assertRaisesRegex(ValueError,'content changed'):
                downloads.verify_downloaded_content(self.target,self.root,state,result['file_identity'],
                                                    len(self.payload),content_hash(self.payload))
        self.assertEqual(self.target.read_bytes(),b'X'*len(self.payload))

    def test_windows_fd_timestamp_precision_differences_preserve_hash_verification(self):
        state=downloads.prepare_target(self.target,self.root);result=self.download(expected_target=state)
        info=self.target.stat()
        # Windows fstat may expose coarser mtime and creation-time ctime while
        # the path query exposes a different timestamp representation. Optional
        # file-attribute fields may also be absent from that fd result.
        windows_fd=SimpleNamespace(st_mode=info.st_mode,st_dev=info.st_dev,st_ino=info.st_ino,
            st_size=info.st_size,st_mtime_ns=info.st_mtime_ns//10**9*10**9,
            st_ctime_ns=info.st_ctime_ns+20*10**9)
        with patch.object(downloads.sys,'platform','win32'),patch.object(downloads.os,'fstat',return_value=windows_fd),patch.object(downloads.os,'read',wraps=os.read) as read:
            downloads.verify_downloaded_content(self.target,self.root,state,result['file_identity'],
                                                len(self.payload),content_hash(self.payload))
            self.assertTrue(read.called)
            # Ignoring incompatible timestamps must never ignore a different
            # underlying file or an explicit placeholder flag before reading.
            for change in ({'st_ino':info.st_ino+1},{'st_file_attributes':0x1000}):
                altered=SimpleNamespace(**{**vars(windows_fd),**change})
                with self.subTest(change=change),patch.object(downloads.os,'fstat',return_value=altered),patch.object(downloads.os,'read',side_effect=AssertionError('Unapproved fd read')):
                    with self.assertRaisesRegex(ValueError,'changed'):
                        downloads.verify_downloaded_content(self.target,self.root,state,result['file_identity'],
                                                            len(self.payload),content_hash(self.payload))

    def test_final_play_verification_rejects_stale_identity_before_any_read(self):
        state=downloads.prepare_target(self.target,self.root);result=self.download(expected_target=state)
        changed=[*result['file_identity']];changed[1]+=1
        with patch.object(downloads.os,'open',side_effect=AssertionError('Unapproved file opened')):
            with self.assertRaisesRegex(ValueError,'changed'):
                downloads.verify_downloaded_content(self.target,self.root,state,changed,
                                                    len(self.payload),content_hash(self.payload))
        with patch.object(downloads.os,'fstat',return_value=SimpleNamespace(st_mode=0)),patch.object(downloads.os,'read',side_effect=AssertionError('Special file read')):
            with self.assertRaisesRegex(ValueError,'changed'):
                downloads.verify_downloaded_content(self.target,self.root,state,result['file_identity'],
                                                    len(self.payload),content_hash(self.payload))

    def test_final_play_verification_cancellation_closes_only_selected_file_and_keeps_download(self):
        from task_control import OperationCancelled
        state=downloads.prepare_target(self.target,self.root);result=self.download(expected_target=state)
        calls=0
        def checkpoint():
            nonlocal calls
            calls+=1
            if calls==3:raise OperationCancelled('Synthetic cancel during selected file verification')
        with patch.object(downloads.os,'close',wraps=os.close) as closed:
            with self.assertRaises(OperationCancelled):
                downloads.verify_downloaded_content(self.target,self.root,state,result['file_identity'],
                                                    len(self.payload),content_hash(self.payload),checkpoint)
        closed.assert_called_once();self.assertEqual(self.target.read_bytes(),self.payload)

    def test_exact_hash_block_boundary(self):
        self.payload = b'x' * (4 * 1024**2)
        self.metadata.update(size=len(self.payload), content_hash=content_hash(self.payload))
        self.connection.response = SyntheticResponse(self.payload, self.metadata)
        self.assertEqual(self.download()['content_hash'], content_hash(self.payload))

    def test_server_timestamp_preserved(self):
        self.download()
        expected = int(datetime(2025, 4, 3, 2, 1, tzinfo=timezone.utc).timestamp())
        self.assertEqual(int(self.target.stat().st_mtime), expected)

    @unittest.skipUnless(os.name == 'posix', 'POSIX permission bits')
    def test_output_and_staging_are_private(self):
        self.download()
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.staging.stat().st_mode & 0o777, 0o700)

    def test_preparation_creates_nothing_and_is_json_safe(self):
        import json
        with patch.object(Path, 'open', side_effect=AssertionError('No content opens')):
            state = downloads.prepare_target(self.target, self.root)
        self.assertEqual(json.loads(json.dumps(state)), state)
        self.assertFalse(self.staging.exists())
        self.assert_clean()

    def test_rejects_relative_path(self):
        with self.assertRaises(ValueError):
            downloads.prepare_target('Album/song.mp3', self.root)
        self.assertEqual(self.connection.calls, [])

    def test_rejects_similar_prefix_outside_root(self):
        outside = Path(str(self.root) + ' extra') / 'song.mp3'
        with self.assertRaises(ValueError):
            downloads.prepare_target(outside, self.root)

    def test_rejects_parent_traversal(self):
        with self.assertRaises(ValueError):
            downloads.prepare_target(self.album / '..' / 'song.mp3', self.root)

    def test_rejects_unc_control_and_unsupported_extensions(self):
        for value in ('//server/share/song.mp3', '\\\\server\\share\\song.mp3',
                      str(self.album / 'song\n.mp3'), str(self.album / 'document.db')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                downloads.prepare_target(value, self.root)

    def test_rejects_entire_system_drive_and_root_target(self):
        for target, root in ((self.target, Path(self.root.anchor)), (self.root, self.root)):
            with self.subTest(root=root), self.assertRaises(ValueError):
                downloads.prepare_target(target, root)

    def test_missing_parent_requires_user_action_without_creating_tree(self):
        self.target = self.album / 'Not synced' / 'song.mp3'
        with self.assertRaises(ValueError):
            self.download()
        self.assertFalse(self.target.parent.exists())
        self.assertEqual(self.connection.calls, [])

    def test_windows_ambiguous_and_reserved_names_are_rejected(self):
        for name in ('song.mp3:alternate', 'song.mp3 ', 'Album.', 'CON.mp3', 'lpt1.wav',
                     'COM¹.flac', 'bad?.mp3', 'AUX', 'CONOUT$.mp3'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                downloads._windows_parts([name])
        downloads._windows_parts(['Customer', 'Concert.mp3', 'Auxiliary.wav'])

    def test_root_symlink_is_not_followed(self):
        alias = self.base / 'Dropbox alias'
        try: alias.symlink_to(self.root, target_is_directory=True)
        except OSError: self.skipTest('Symlinks unavailable')
        with self.assertRaises(ValueError):
            downloads.prepare_target(alias / 'Customer' / 'Album' / self.target.name, alias)

    def test_parent_symlink_is_not_followed(self):
        alias = self.root / 'Album alias'
        try: alias.symlink_to(self.album, target_is_directory=True)
        except OSError: self.skipTest('Symlinks unavailable')
        with self.assertRaises(ValueError):
            downloads.prepare_target(alias / self.target.name, self.root)

    def test_existing_local_file_is_preserved_without_network(self):
        self.target.write_bytes(b'Existing local version')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.download()
        self.assertEqual(self.target.read_bytes(), b'Existing local version')
        self.assertEqual(self.connection.calls, [])

    def test_existing_target_symlink_is_preserved(self):
        real = self.base / 'unrelated.mp3'
        real.write_bytes(b'Unrelated')
        try: self.target.symlink_to(real)
        except OSError: self.skipTest('Symlinks unavailable')
        with self.assertRaises(ValueError): self.download()
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(real.read_bytes(), b'Unrelated')

    def test_cloud_placeholder_requires_existing_play_hydration(self):
        self.target.touch()
        original = Path.lstat
        def attributes(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == self.target:
                return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400000)
            return result
        with patch.object(Path, 'lstat', attributes), self.assertRaisesRegex(ValueError, 'Play'):
            self.download()
        self.assertEqual(self.target.stat().st_size, 0)
        self.assertEqual(self.connection.calls, [])

    def test_cloud_only_or_junction_directory_rejected(self):
        original = Path.lstat
        for flag in (0x400, 0x1000, 0x40000, 0x400000):
            def attributes(path, *args, **kwargs):
                result = original(path, *args, **kwargs)
                if path == self.album:
                    return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=flag)
                return result
            with self.subTest(flag=flag), patch.object(Path, 'lstat', attributes), self.assertRaises(ValueError):
                self.download()
        self.assertEqual(self.connection.calls, [])

    def test_invalid_remote_file_metadata_rejected_before_transfer(self):
        changes = ({'.tag': 'folder'}, {'is_downloadable': False}, {'size': 0}, {'size': -1},
                   {'size': True}, {'size': downloads.MAX_FILE_BYTES + 1}, {'id': 'path/file.mp3'},
                   {'rev': ''}, {'rev': 'bad\nrev'}, {'content_hash': None},
                   {'content_hash': 'abc'}, {'server_modified': '2025-01-01'})
        for change in changes:
            with self.subTest(change=change), patch.dict(self.metadata, change), self.assertRaises(ValueError):
                self.download()
        self.assertEqual(self.connection.calls, [])
        self.assertFalse(self.staging.exists())

    def test_fresh_stream_metadata_must_match_confirmation(self):
        for change in ({'id': 'id:another'}, {'rev': 'new-revision'}, {'size': 1},
                       {'content_hash': '0' * 64}):
            with self.subTest(change=change):
                self.connection.response = SyntheticResponse(self.payload, {**self.metadata, **change})
                with self.assertRaisesRegex(ValueError, 'details changed'): self.download()
                self.assertEqual(self.connection.response.reads, 0)
                self.assert_clean()

    def test_truncated_stream_leaves_no_destination(self):
        self.connection.response = SyntheticResponse(self.payload[:-1], self.metadata)
        with self.assertRaisesRegex(ValueError, 'incomplete'): self.download()
        self.assert_clean()

    def test_overlong_stream_leaves_no_destination(self):
        self.connection.response = SyntheticResponse(self.payload + b'extra', self.metadata)
        with self.assertRaisesRegex(ValueError, 'more bytes'): self.download()
        self.assert_clean()

    def test_same_length_corruption_fails_content_hash(self):
        self.connection.response = SyntheticResponse(b'X' + self.payload[1:], self.metadata)
        with self.assertRaisesRegex(ValueError, 'does not match'): self.download()
        self.assert_clean()

    def test_nonbyte_response_rejected(self):
        with patch.object(self.response, 'read', return_value='not binary'):
            with self.assertRaisesRegex(ValueError, 'invalid file content'): self.download()
        self.assert_clean()

    def test_network_interruption_closes_response_and_cleans_staging(self):
        with patch.object(self.response, 'read', side_effect=OSError('Connection interrupted')):
            with self.assertRaises(OSError): self.download()
        self.assertTrue(self.response.closed)
        self.assert_clean()

    def test_early_cancellation_does_not_open_transfer(self):
        def cancel(*_): raise RuntimeError('Cancelled')
        with self.assertRaisesRegex(RuntimeError, 'Cancelled'): self.download(progress=cancel)
        self.assertEqual(self.connection.calls, [])
        self.assertFalse(self.staging.exists())

    def test_mid_transfer_cancellation_leaves_no_file(self):
        def cancel(amount, _):
            if amount > 0: raise RuntimeError('Cancelled')
        with patch.object(downloads, 'CHUNK_BYTES', 4):
            with self.assertRaisesRegex(RuntimeError, 'Cancelled'): self.download(progress=cancel)
        self.assert_clean()

    def test_prepublication_cancellation_leaves_no_file(self):
        def cancel(amount, _):
            if amount == 99: raise RuntimeError('Cancelled')
        with self.assertRaisesRegex(RuntimeError, 'Cancelled'): self.download(progress=cancel)
        self.assert_clean()

    def test_late_cancellation_does_not_remove_completed_song(self):
        def cancel(amount, _):
            if amount == 100: raise RuntimeError('Cancelled too late')
        self.assertTrue(self.download(progress=cancel)['downloaded'])
        self.assertEqual(self.target.read_bytes(), self.payload)

    def test_disconnected_account_fails_before_transfer(self):
        self.connection.connected = False
        with self.assertRaisesRegex(ValueError, 'Reconnect'): self.download()
        self.assertEqual(self.connection.calls, [])

    def test_account_change_during_transfer_aborts(self):
        self.response.on_read = lambda _: setattr(self.connection, 'identity', 'different-account')
        with self.assertRaisesRegex(ValueError, 'authorization changed'): self.download()
        self.assert_clean()

    def test_caller_can_revalidate_source_mapping_during_transfer(self):
        self.mapping_changed = False
        def validate():
            if self.mapping_changed: raise ValueError('Mapping changed')
        self.response.on_read = lambda _: setattr(self, 'mapping_changed', True)
        with self.assertRaisesRegex(ValueError, 'Mapping changed'): self.download(validate=validate)
        self.assert_clean()

    def test_appearing_destination_is_never_replaced(self):
        self.response.on_read = lambda _: self.target.write_bytes(b'Another process')
        with self.assertRaisesRegex(ValueError, 'already exists'): self.download()
        self.assertEqual(self.target.read_bytes(), b'Another process')
        self.assertEqual(list(self.staging.iterdir()), [])

    def test_last_instant_destination_race_uses_atomic_no_clobber(self):
        original = downloads.os.link
        def raced(*args, **kwargs):
            self.target.write_bytes(b'Won publication race')
            return original(*args, **kwargs)
        with patch.object(downloads.os, 'link', side_effect=raced):
            with self.assertRaisesRegex(ValueError, 'appeared'): self.download()
        self.assertEqual(self.target.read_bytes(), b'Won publication race')
        self.assertEqual(list(self.staging.iterdir()), [])

    def test_consent_is_invalidated_by_parent_replacement(self):
        approved = downloads.prepare_target(self.target, self.root)
        previous = self.album.with_name('Old album')
        self.album.rename(previous)
        self.album.mkdir()
        with self.assertRaisesRegex(ValueError, 'destination changed'):
            self.download(expected_target=approved)
        self.assertEqual(self.connection.calls, [])

    def test_parent_move_during_stream_does_not_publish_anywhere(self):
        previous = self.album.with_name('Moved album')
        def move(count):
            if count == 1:
                self.album.rename(previous)
                self.album.mkdir()
        self.response.on_read = move
        with self.assertRaisesRegex(ValueError, 'destination changed'): self.download()
        self.assertEqual(list(previous.iterdir()), [])
        self.assert_clean()

    def test_unsupported_hardlinks_do_not_fall_back_to_overwrite(self):
        with patch.object(downloads.os, 'link', side_effect=OSError(errno.EXDEV, 'No hardlinks')):
            with self.assertRaisesRegex(ValueError, 'cannot safely publish'): self.download()
        self.assert_clean()

    def test_staging_inside_managed_root_rejected_before_network(self):
        self.staging = self.root / 'private-looking-staging'
        with self.assertRaisesRegex(ValueError, 'outside Dropbox'): self.download()
        self.assertFalse(self.staging.exists())
        self.assertEqual(self.connection.calls, [])

    def test_staging_inside_full_root_rejected_for_descendant_mapping(self):
        self.staging = self.root / 'staging'
        with self.assertRaisesRegex(ValueError, 'outside Dropbox'):
            downloads.download_file(self.connection, self.metadata, self.target, self.album,
                                    'ns', staging_dir=self.staging, managed_root=self.root)
        self.assertEqual(self.connection.calls, [])

    def test_staging_symlink_is_rejected(self):
        real = self.base / 'another-private-folder'
        real.mkdir(mode=0o700)
        try: self.staging.symlink_to(real, target_is_directory=True)
        except OSError: self.skipTest('Symlinks unavailable')
        with self.assertRaises(ValueError): self.download()
        self.assertEqual(self.connection.calls, [])
        self.assertEqual(list(real.iterdir()), [])

    @unittest.skipUnless(os.name == 'posix', 'POSIX permission bits')
    def test_public_staging_directory_rejected(self):
        self.staging.mkdir(mode=0o755)
        self.staging.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'private'): self.download()
        self.assertEqual(self.connection.calls, [])

    def test_staging_on_different_volume_rejected_before_transfer(self):
        self.staging.mkdir(mode=0o700)
        staging_inode = self.staging.stat().st_ino
        identity = downloads._identity
        def simulated_volume(info):
            device, inode = identity(info)
            return [device + 1 if inode == staging_inode else device, inode]
        with patch.object(downloads, '_identity', side_effect=simulated_volume):
            with self.assertRaisesRegex(ValueError, 'another volume'): self.download()
        self.assertEqual(self.connection.calls, [])
        self.assert_clean()

    def test_partial_download_is_never_visible_in_sync_tree(self):
        observations = []
        def inspect(_):
            observations.append(list(self.album.iterdir()))
            self.assertEqual(len(list(self.staging.iterdir())), 1)
        self.response.on_read = inspect
        with patch.object(downloads, 'CHUNK_BYTES', 8):
            self.download()
        self.assertGreater(len(observations), 2)
        self.assertTrue(all(items == [] for items in observations))

    @unittest.skipUnless(downloads._USE_DIR_FD, 'Descriptor anchored POSIX traversal')
    def test_destination_move_during_publication_cleans_anchored_inode(self):
        original = downloads.os.link
        previous = self.album.with_name('Moved at publication')
        def moved_after_link(*args, **kwargs):
            original(*args, **kwargs)
            self.album.rename(previous)
            self.album.mkdir()
        with patch.object(downloads.os, 'link', side_effect=moved_after_link):
            with self.assertRaisesRegex(ValueError, 'changed during publication'): self.download()
        self.assertEqual(list(previous.iterdir()), [])
        self.assert_clean()

    def test_insufficient_disk_space_rejected_before_network(self):
        with patch.object(downloads.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(ValueError, 'free space'): self.download()
        self.assertEqual(self.connection.calls, [])
        self.assert_clean()

    def test_write_failure_cleans_partial_file(self):
        with patch.object(downloads.os, 'write', side_effect=OSError(errno.ENOSPC, 'Disk full')):
            with self.assertRaises(OSError): self.download()
        self.assert_clean()


if __name__ == '__main__':
    unittest.main()

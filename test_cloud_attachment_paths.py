"""Cross-platform captured paths cannot reset a cloud download destination."""
from pathlib import Path,PurePosixPath,PureWindowsPath
import unittest
from unittest.mock import patch

import cloud_attachments as attachments
import dropbox_files


class CloudAttachmentPathTests(unittest.TestCase):
    def test_windows_destination_rejects_posix_embedded_drive_stream_and_reserved_names(self):
        mapping={'local_root':'D:\\Approved\\Music','recorded_root':'/old/music'}
        unsupported=('C:\\outside\\file.mp3','C:outside.mp3','\\outside\\file.mp3',
                     'safe:stream.mp3','CON.mp3','LPT\u00b9.mp3','CON .mp3','file?.mp3',
                     'bad. /file.mp3','safe\\..\\outside.mp3')
        with patch.object(Path,'lstat',side_effect=AssertionError('Captured path caused a local probe')):
            for relative in unsupported:
                with self.subTest(relative=relative):
                    self.assertIsNone(attachments.track_target({'current_path':'/old/music/'+relative},mapping))

    def test_valid_posix_reference_builds_a_confined_windows_destination_without_io(self):
        mapping={'local_root':'D:\\Approved\\Music','recorded_root':'/old/music'}
        with patch.object(Path,'lstat',side_effect=AssertionError('Captured path caused a local probe')):
            target=attachments.track_target({'current_path':'/old/music/Album/Song.mp3'},mapping)
        self.assertEqual(target['local_path'],'D:\\Approved\\Music\\Album\\Song.mp3')
        self.assertTrue(PureWindowsPath(target['local_path']).is_relative_to(PureWindowsPath(mapping['local_root'])))
        self.assertEqual(target['relative_path'],'Album/Song.mp3')

    def test_windows_recorded_reference_can_target_an_ordinary_posix_destination(self):
        mapping={'local_root':'/approved/music','recorded_root':'D:\\Old music'}
        target=attachments.track_target({'current_path':'D:\\Old music\\Album\\Song.mp3'},mapping)
        self.assertEqual(target['local_path'],'/approved/music/Album/Song.mp3')
        self.assertTrue(PurePosixPath(target['local_path']).is_relative_to(PurePosixPath(mapping['local_root'])))

    def test_final_relative_destination_guard_rejects_absolute_join_reset(self):
        self.assertIsNone(attachments._relative_destination(PurePosixPath('/approved/music'),('/outside/file.mp3',)))
        self.assertIsNone(attachments._relative_destination(PureWindowsPath('D:/Approved'),('C:\\outside\\file.mp3',)))

    def test_foreign_windows_provider_boundary_is_compared_in_the_same_flavor(self):
        mapping={'local_root':'D:\\Approved','recorded_root':'/old/music',
                 'foreign_provider_roots':['D:\\Approved\\Other provider']}
        self.assertIsNone(attachments.track_target({'current_path':'/old/music/Other provider/Song.mp3'},mapping))
        self.assertIsNotNone(attachments.track_target({'current_path':'/old/music/Album/Song.mp3'},mapping))

    def test_literal_posix_backslash_is_an_unsupported_dropbox_row(self):
        mapping={'local_root':'/approved/music','recorded_root':'/old/music','provider':'dropbox','remote_root':''}
        track={'current_path':'/old/music/Album/literal\\Song.mp3'}
        # POSIX can represent this component, but Dropbox mapping cannot. Skip
        # this one row before a caller can probe its local presence.
        with patch.object(Path,'lstat',side_effect=AssertionError('Unsupported path caused a local probe')):
            self.assertIsNone(dropbox_files.target(track,mapping))

    def test_active_audio_mapping_rejects_windows_alias_before_mapped_path_probes(self):
        mapping={'local_root':'D:\\Approved\\Music','recorded_root':'/old/music'}
        audio=[{'local_root':'D:\\Approved\\Music','recorded_root':'/old/music','device':1,'inode':2}]
        for relative in ('C:\\outside\\file.mp3','safe:stream.mp3','CON.mp3'):
            with self.subTest(relative=relative),patch.object(attachments,'mapped_path',side_effect=AssertionError('Unsafe candidate probed')):
                self.assertIsNone(attachments.track_target({'current_path':'/old/music/'+relative},mapping,audio))
        with patch.object(attachments,'mapped_path',return_value=PureWindowsPath('D:/Approved/Music/Album/Song.mp3')) as resolve:
            result=attachments.track_target({'current_path':'/old/music/Album/Song.mp3'},mapping,audio)
        resolve.assert_called_once();self.assertEqual(result['relative_path'],'Album/Song.mp3')

    def test_posix_literal_backslash_cannot_be_normalized_into_a_different_audio_file(self):
        audio=[{'local_root':'/approved/music','recorded_root':'/old/music','device':1,'inode':2}]
        track={'current_path':'/old/music/Album/literal\\Song.mp3'}
        mapping={'local_root':'/approved/music','recorded_root':'/old/music','provider':'dropbox','remote_root':''}
        with patch.object(attachments,'mapped_path',side_effect=AssertionError('Literal path normalized before probe')):
            self.assertIsNone(dropbox_files.target(track,mapping,audio))
        legacy={key:value for key,value in mapping.items() if key not in ('recorded_root','provider')}
        with patch('audio_paths.mapped_path',side_effect=AssertionError('Literal path normalized before probe')):
            self.assertIsNone(dropbox_files.target(track,legacy,audio))


if __name__=='__main__':unittest.main()

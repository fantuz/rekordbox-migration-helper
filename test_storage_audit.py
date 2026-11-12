import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from media import cloud_placeholder
from storage_audit import scan_storage,verify_group


class StorageAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.local=self.root/'originals';self.local.mkdir()
        self.cloud=self.root/'cloud';self.cloud.mkdir()
        self.roots=[{'root':str(self.local),'kind':'local','recorded_prefix':'C:/Music'},
                    {'root':str(self.cloud),'kind':'dropbox','recorded_prefix':'C:/Cloud'}]
    def scan(self,tracks=None):return scan_storage(self.roots,lambda *_:None,track_paths=tracks)

    def test_metadata_scan_does_not_read_media_bytes(self):
        (self.local/'song.mp3').write_bytes(b'abc');(self.cloud/'song.mp3').write_bytes(b'abc')
        with patch.object(Path,'open',side_effect=AssertionError('Content must not be opened by metadata scan')):
            audit=self.scan()
        self.assertEqual(audit['totals']['cloud_local_candidate_groups'],1)
        self.assertEqual(audit['totals']['potential_extra_logical_bytes'],3)
        self.assertEqual(audit['locations'][0]['logical_bytes'],3)
        self.assertEqual(audit['locations'][1]['logical_bytes'],3)
        self.assertFalse(audit['source_writes'])

    def test_same_name_size_can_be_different_content(self):
        (self.local/'song.mp3').write_bytes(b'abc');(self.cloud/'song.mp3').write_bytes(b'def')
        audit=self.scan();result=verify_group(audit,audit['groups'][0]['id'],lambda *_:None)
        self.assertFalse(result['same_file_bytes'])
        self.assertEqual(audit['totals']['last_verified_extra_logical_bytes'],0)

    def test_identical_files_are_confirmed_only_after_explicit_hashing(self):
        (self.local/'song.mp3').write_bytes(b'abc');(self.cloud/'song.mp3').write_bytes(b'abc')
        audit=self.scan()
        self.assertEqual(audit['totals']['last_verified_identical_groups'],0)
        result=verify_group(audit,audit['groups'][0]['id'],lambda *_:None)
        self.assertTrue(result['same_file_bytes'])
        self.assertEqual(audit['totals']['last_verified_extra_logical_bytes'],3)
        self.assertEqual((self.local/'song.mp3').read_bytes(),b'abc')
        self.assertEqual((self.cloud/'song.mp3').read_bytes(),b'abc')

    def test_one_database_track_can_link_two_differently_named_files(self):
        (self.local/'original.mp3').write_bytes(b'abc');(self.cloud/'cloud-uuid.mp3').write_bytes(b'abc')
        tracks=[{'id':'track-1','current_path':'C:/Cloud/cloud-uuid.mp3','original_path':'C:/Music/original.mp3','size':3}]
        audit=self.scan(tracks)
        self.assertEqual(audit['matched_database_tracks'],1)
        self.assertEqual(audit['groups'][0]['track_ids'],['track-1'])
        self.assertIn('database_paths_and_size',audit['groups'][0]['evidence'])
        self.assertEqual(audit['totals']['cloud_local_candidate_groups'],1)

    def test_multiple_database_references_do_not_imply_multiple_physical_files(self):
        (self.local/'song.mp3').write_bytes(b'abc')
        tracks=[{'id':str(i),'current_path':'C:/Music/song.mp3','size':3} for i in (1,2)]
        audit=self.scan(tracks)
        self.assertEqual(audit['totals']['database_reference_groups'],1)
        self.assertEqual(audit['totals']['candidate_groups'],0)
        with self.assertRaisesRegex(ValueError,'one physical file'):
            verify_group(audit,audit['groups'][0]['id'],lambda *_:None)

    def test_link_aliases_are_not_counted_as_extra_disk_copies(self):
        (self.local/'song.mp3').write_bytes(b'abc')
        try:os.link(self.local/'song.mp3',self.cloud/'song.mp3')
        except OSError:self.skipTest('Filesystem does not support creating hard links')
        audit=self.scan()
        self.assertEqual(audit['physical_files'],1)
        self.assertEqual(audit['totals']['potential_extra_logical_bytes'],0)

    def test_cloud_placeholder_hashing_is_held_for_user_download(self):
        (self.local/'song.mp3').write_bytes(b'abc');(self.cloud/'song.mp3').write_bytes(b'abc')
        audit=self.scan()
        with patch('storage_audit.file_record',return_value={'cloud_only':True}):
            with self.assertRaisesRegex(ValueError,'Download cloud-only'):
                verify_group(audit,audit['groups'][0]['id'],lambda *_:None)

    def test_files_changed_since_scan_are_rejected(self):
        (self.local/'song.mp3').write_bytes(b'abc');(self.cloud/'song.mp3').write_bytes(b'abc')
        audit=self.scan();(self.local/'song.mp3').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed since the audit'):
            verify_group(audit,audit['groups'][0]['id'],lambda *_:None)

    def test_cloud_flags_cover_windows_and_mac_placeholders(self):
        self.assertTrue(cloud_placeholder(SimpleNamespace(st_flags=0x40000000)))
        self.assertTrue(cloud_placeholder(SimpleNamespace(st_file_attributes=0x1000)))
        self.assertFalse(cloud_placeholder(SimpleNamespace(st_flags=0)))

    def test_unknown_policy_and_unavailable_roots_remain_explicit(self):
        audit=scan_storage([{'root':str(self.root/'unmounted'),'kind':'google_drive'}],lambda *_:None,'move')
        self.assertEqual(audit['policy_hint'],'move')
        self.assertEqual(audit['warning_count'],1)
        self.assertEqual(audit['file_locations'],0)

    def test_overlapping_roots_keep_both_prefix_maps_without_counting_files_twice(self):
        (self.local/'original.mp3').write_bytes(b'abc');(self.cloud/'renamed.mp3').write_bytes(b'abc')
        roots=[{'root':str(self.root),'kind':'local','recorded_prefix':'C:/Base'},
               {'root':str(self.cloud),'kind':'dropbox','recorded_prefix':'D:/Dropbox'}]
        tracks=[{'id':'track','current_path':'C:/Base/cloud/renamed.mp3','original_path':'C:/Base/originals/original.mp3','size':3}]
        audit=scan_storage(roots,lambda *_:None,track_paths=tracks)
        self.assertEqual(audit['file_locations'],2)
        self.assertEqual(audit['totals']['cloud_local_candidate_groups'],1)

    def test_ordinary_files_have_a_known_allocation_on_supported_platforms(self):
        (self.local/'song.mp3').write_bytes(b'abc')
        audit=self.scan()
        self.assertEqual(audit['locations'][0]['unknown_allocation_files'],0)


if __name__=='__main__':unittest.main()

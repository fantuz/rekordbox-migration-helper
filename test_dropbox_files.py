"""Adversarial Dropbox inventory and local-provider mapping evidence."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import dropbox_files as files


def entry(path='/Music/Album/Track.mp3', identity='id:file'):
    return {'.tag':'file','path_lower':path.lower(),'path_display':path,
            'id':identity,'rev':'123abc','size':12}


class DropboxFileEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        self.dropbox=self.root/'Dropbox';self.dropbox.mkdir()
        self.music=self.dropbox/'Music';self.music.mkdir()
        self.account={'account_id':'dbid:synthetic','root_namespace_id':'101'}
        self.connection=Mock()
        self.connection.status.return_value={'connected':True,'connection_id':'grant-one','account':self.account}
        self.connection.rpc.return_value={'.tag':'folder','id':'id:music','path_lower':'/music'}
        with patch.object(files,'detected_roots',return_value=[{'root':str(self.dropbox)}]):
            self.mapping=files.mapping_record(self.connection,str(self.music),'/Music')
        self.connection.rpc.reset_mock()

    def inventory(self,pages):
        self.connection.rpc.side_effect=pages
        return files.inventory(self.connection,self.mapping,lambda *_:None)

    def test_managed_boundary_preserves_full_provider_root_and_checks_identity(self):
        self.assertEqual(self.mapping['managed_root'],str(self.dropbox))
        files.validate_mapping(self.connection,self.mapping)
        self.dropbox.rename(self.root/'Old Dropbox')
        self.dropbox.mkdir();self.music.mkdir()
        with self.assertRaisesRegex(ValueError,'folder changed'):
            files.validate_mapping(self.connection,self.mapping)
        self.connection.rpc.assert_not_called()

    def test_saved_mapping_cannot_escape_managed_provider_boundary(self):
        mapping=deepcopy(self.mapping);outside=self.root/'Other';outside.mkdir()
        mapping.update(local_root=str(outside),device=outside.stat().st_dev,inode=outside.stat().st_ino)
        with self.assertRaisesRegex(ValueError,'folder changed'):
            files.validate_mapping(self.connection,mapping)

    def test_requested_mapping_cannot_use_outside_sibling_or_link_alias(self):
        outside=self.root/'Private';outside.mkdir()
        sibling=self.root/'Dropbox extra';sibling.mkdir()
        invalid=[str(outside),str(sibling),str(self.music/'..'/'Music')]
        alias=self.dropbox/'Outside alias'
        try:alias.symlink_to(outside,target_is_directory=True)
        except OSError:pass
        else:invalid.append(str(alias))
        with patch.object(files,'detected_roots',return_value=[{'root':str(self.dropbox)}]):
            for value in invalid:
                with self.subTest(path=value),self.assertRaises(ValueError):
                    files.mapping_record(self.connection,value,'/Music')
        self.connection.rpc.assert_not_called()

    def test_valid_pagination_returns_one_metadata_inventory_without_content(self):
        first=entry();second=entry('/Music/Album/Other.flac','id:other')
        values,complete=self.inventory([
            {'entries':[first],'has_more':True,'cursor':'next-page'},
            {'entries':[second],'has_more':False}])
        self.assertTrue(complete);self.assertEqual(len(values),2)
        self.assertEqual(self.connection.rpc.call_args_list[1].args,
                         ('files/list_folder/continue',{'cursor':'next-page'}))
        self.connection.download.assert_not_called()

    def test_inventory_bounds_never_turn_unseen_entries_into_missing_evidence(self):
        with patch.object(files,'MAX_PAGES',1):
            values,complete=self.inventory([{'entries':[entry()],'has_more':True,'cursor':'next'}])
        self.assertFalse(complete);self.assertEqual(len(values),1)
        with patch.object(files,'MAX_ENTRIES',1):
            values,complete=self.inventory([{'entries':[entry(),entry('/Music/Two.mp3','id:two')],'has_more':False}])
        self.assertFalse(complete);self.assertEqual(len(values),1)

    def test_malformed_metadata_does_not_produce_a_complete_missing_result(self):
        invalid=[None,{}, {'entries':[],'has_more':1},
                 {'entries':[None],'has_more':False},
                 {'entries':[entry('/Other/Track.mp3')],'has_more':False}]
        for changes in ({'size':True},{'size':-1},{'id':''},{'rev':None},
                        {'is_downloadable':'false'},{'path_lower':'/music/../track.mp3'},
                        {'path_lower':'/music//track.mp3'},{'path_lower':'/music/track.mp3/'},
                        {'path_lower':'/music/track.mp3','path_display':'/Music/Other.mp3'}):
            invalid.append({'entries':[{**entry(),**changes}],'has_more':False})
        for result in invalid:
            with self.subTest(result=result),self.assertRaises(ValueError):
                self.inventory([result])

    def test_duplicate_case_unicode_identity_and_cursor_are_rejected(self):
        pairs=[(entry(),entry('/Music/Album/TRACK.MP3','id:other')),
               (entry('/Music/Caf\u00e9.mp3'),entry('/Music/Cafe\u0301.mp3','id:other')),
               (entry(),entry('/Music/Moved.mp3'))]
        for first,second in pairs:
            with self.subTest(first=first),self.assertRaises(ValueError):
                self.inventory([{'entries':[first],'has_more':True,'cursor':'cursor'},
                                {'entries':[second],'has_more':False}])
        with self.assertRaisesRegex(ValueError,'cursor'):
            self.inventory([{'entries':[],'has_more':True,'cursor':'same'},
                            {'entries':[],'has_more':True,'cursor':'same'}])

    def test_current_path_precedes_original_and_remote_paths_remain_canonical(self):
        current=self.music/'New.mp3';old=self.music/'Old.mp3'
        target=files.target({'current_path':str(current),'original_path':str(old)},self.mapping)
        self.assertEqual(target['remote_path'],'/Music/New.mp3')
        self.assertEqual(files.remote_path('/'), '')
        for value in ('/Music//','//','/Music/../Other','/Music\\Other'):
            with self.subTest(value=value),self.assertRaises(ValueError):files.remote_path(value)

    def test_failed_active_audio_mapping_never_falls_back_to_recorded_path(self):
        from audio_paths import validate
        track={'current_path':str(self.music/'Track.mp3')}
        # Persist the same normalized separators as the real mapping API on
        # Windows as well as POSIX, then simulate replacement of that volume.
        failed=validate([{'recorded_root':str(self.music),'local_root':str(self.music)}],[self.root])
        failed[0]['inode']+=1
        self.assertIsNone(files.target(track,self.mapping,failed))


if __name__=='__main__':unittest.main()

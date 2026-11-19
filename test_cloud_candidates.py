"""Saved-path suggestions retain uncertainty and never inspect audio content."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from cloud_candidates import suggestions


class CloudCandidateTests(unittest.TestCase):
    def test_business_team_hint_is_not_account_or_sync_mode_evidence(self):
        root=r'C:\Users\DJ\Cloud Option DJ team Dropbox'
        saved={'tracks':[{'current_path':root+r'\Member\rekordbox\Album\One.mp3'},
                         {'current_path':root+r'\Member\rekordbox\Other\Two.flac'}]}
        rows=suggestions(saved,[])
        self.assertEqual(rows[0]['kind'],'dropbox')
        self.assertEqual(rows[0]['tracks'],2)
        self.assertEqual(rows[0]['evidence'],'captured_provider_hint')
        self.assertNotIn('account_id',rows[0]);self.assertNotIn('sync_mode',rows[0])
        self.assertEqual(rows[0]['foreign'],os.name!='nt')

    def test_selected_cache_and_music_folder_remain_distinct_candidates(self):
        saved={'tracks':[{'current_path':'/home/dj/Music/Album/One.mp3'},
                         {'current_path':'/home/dj/Downloads/Rekordbox/Two.mp3'}]}
        rows=suggestions(saved,[])
        self.assertGreaterEqual(len(rows),2)
        self.assertTrue(all(row['kind']=='unknown' for row in rows))
        self.assertNotIn('/home/dj',[row['path'] for row in rows])

    def test_component_boundaries_and_old_path_fallback(self):
        saved={'tracks':[{'current_path':'/mnt/Dropbox extra/One.mp3'},
                         {'current_path':'relative.mp3','xml_location':'file:///mnt/Dropbox/Album/Two.mp3'}]}
        roots=[{'kind':'dropbox','root':'/mnt/Dropbox','provider_verified':True,'availability':'available'}]
        rows=suggestions(saved,roots)
        confirmed=[row for row in rows if row['evidence']=='provider_configuration']
        self.assertTrue(confirmed)
        self.assertTrue(all(row['tracks']==1 for row in confirmed))

    def test_metadata_only_no_filesystem_calls_and_unknown_subfolder_availability(self):
        saved={'tracks':[{'current_path':'/music/Dropbox/Album/One.mp3'}]}
        roots=[{'kind':'dropbox','root':'/music/Dropbox','provider_verified':True,'availability':'available'}]
        with patch.object(Path,'open',side_effect=AssertionError('File opened')),patch.object(Path,'stat',side_effect=AssertionError('File probed')):
            rows=suggestions(saved,roots)
        album=next(row for row in rows if row['path']=='/music/Dropbox/Album')
        self.assertEqual(album['available'],False if os.name=='nt' else None)

    def test_unsafe_or_nonabsolute_references_are_not_suggestions(self):
        saved={'tracks':[{'current_path':'../private/One.mp3'},
                         {'xml_location':'file://other-host/music/Two.mp3'},
                         {'original_path':'/music/../private/Three.mp3'}]}
        self.assertEqual(suggestions(saved,[]),[])


if __name__=='__main__':unittest.main()

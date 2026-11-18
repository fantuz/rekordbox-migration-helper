"""Invented team/personal roots and opaque database bytes; never provider access."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cloud_locations import clear_cache,current_windows_sid,discover,provider_roots,relocation_evidence,small_json,windows_provider_paths
from platform_paths import discover_sources


class CloudDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.home=Path(temporary.name)/'Users'/'dj';self.home.mkdir(parents=True)
        self.env={'APPDATA':str(self.home/'AppData/Roaming'),'LOCALAPPDATA':str(self.home/'AppData/Local')}

    def dropbox(self,accounts):
        path=Path(self.env['APPDATA'])/'Dropbox/info.json';path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(accounts));return path

    def library(self,root,subfolder='rekordbox'):
        folder=root/subfolder;folder.mkdir(parents=True)
        (folder/'master.db').write_bytes(b'NOT SQL: discovery must never read these bytes')
        return folder.resolve()

    def test_custom_team_root_with_customer_namespace_is_discovered_without_sql_reads(self):
        team=self.home/'Club Option DJ team Dropbox';library=self.library(team,'Example Customer/rekordbox')
        config=self.dropbox({'business':{'path':str(team),'secret':'must-not-be-returned','email':'private@example.invalid'}})
        before=(config.read_bytes(),(library/'master.db').read_bytes())
        opened=[];original=Path.open
        def open_file(path,*args,**kwargs):
            opened.append(path)
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',open_file):
            result=discover('win32',self.env,self.home,registrations=[])
        self.assertEqual([r['path'] for r in result['libraries']],[str(library)])
        self.assertEqual(result['roots'][0]['account'],'business')
        self.assertTrue(result['roots'][0]['provider_verified'])
        self.assertNotIn('must-not-be-returned',json.dumps(result))
        self.assertNotIn('private@example.invalid',json.dumps(result))
        self.assertNotIn(library/'master.db',opened)
        self.assertEqual(before,(config.read_bytes(),(library/'master.db').read_bytes()))
        self.assertFalse(result['source_writes']);self.assertFalse(result['database_queries'])

    def test_personal_and_business_accounts_stay_separate_and_duplicate_paths_are_deduplicated(self):
        personal=self.home/'Dropbox';business=self.home/'Other DJ Dropbox'
        personal.mkdir();business.mkdir()
        self.dropbox({'personal':{'path':str(personal)},'business':{'path':str(business)},'copy':{'path':str(personal)}})
        roots=provider_roots('win32',self.env,self.home,[])
        self.assertEqual(len(roots),2)
        self.assertEqual({row['account'] for row in roots},{'personal','business'})

    def test_team_folder_name_is_a_candidate_when_provider_config_is_missing(self):
        team=self.home/'Custom Music Team Dropbox';self.library(team,'Customer/rekordbox')
        result=discover('win32',self.env,self.home,registrations=[])
        self.assertEqual(result['roots'][0]['evidence'],'folder_name')
        self.assertFalse(result['roots'][0]['provider_verified'])
        self.assertEqual(len(result['libraries']),1)

    def test_google_registered_stream_and_mirror_locations_support_multiple_roots(self):
        stream=self.home/'Virtual drive';mirror=self.home/'Mirrored music'
        one=self.library(stream,'My Drive/rekordbox');two=self.library(mirror)
        records=[{'root':str(stream),'kind':'google_drive','evidence':'windows_registration'},
                 {'root':str(mirror),'kind':'google_drive','evidence':'windows_registration'}]
        result=discover('win32',self.env,self.home,registrations=records)
        self.assertEqual({r['path'] for r in result['libraries']},{str(one),str(two)})
        self.assertTrue(all(r['provider_verified'] for r in result['roots']))
        self.assertFalse(result['cloud_login'])

    def test_macos_file_provider_accounts_are_recognized_without_account_secrets(self):
        one=self.home/'Library/CloudStorage/GoogleDrive-test-a';two=self.home/'Library/CloudStorage/Dropbox-TestTeam'
        self.library(one,'My Drive/rekordbox');self.library(two,'Customer/rekordbox')
        roots=provider_roots('darwin',{},self.home,[])
        self.assertEqual({r['kind'] for r in roots},{'dropbox','google_drive'})

    def test_matching_suffix_suggests_relocation_but_never_claims_identity(self):
        root=self.home/'DJ Team Dropbox';library=self.library(root,'Customer/rekordbox')
        self.dropbox({'business':{'path':str(root)}})
        hints=[{'kind':'database','value':r'C:\Users\old-dj\Dropbox\Customer\rekordbox'}]
        result=discover('win32',self.env,self.home,hints,registrations=[])
        self.assertEqual(result['relocations'][0]['candidate_path'],str(library))
        self.assertFalse(result['relocations'][0]['relocation_verified'])
        self.assertFalse(result['relocations'][0]['ambiguous'])
        self.assertEqual(discover('win32',self.env,self.home,registrations=[])['relocations'],[])

    def test_basename_only_match_is_insufficient_and_equal_candidates_stay_ambiguous(self):
        rows=[{'path':'D:/Team/Customer/rekordbox','kind':'dropbox'},
              {'path':'G:/My Drive/Customer/rekordbox','kind':'google_drive'}]
        self.assertEqual(relocation_evidence([{'kind':'database','value':'C:/Unknown/rekordbox'}],rows),[])
        result=relocation_evidence([{'kind':'database','value':'C:/Old/Customer/rekordbox/master.db'}],rows)
        self.assertEqual(len(result),2)
        self.assertTrue(all(r['ambiguous'] and not r['relocation_verified'] for r in result))

    def test_online_only_roots_are_reported_without_traversal_or_hydration(self):
        root=self.home/'Dropbox';self.library(root)
        from os import scandir
        def local_only(path):
            if Path(path)==root or Path(path).is_relative_to(root):raise AssertionError('Online-only root traversed')
            return scandir(path)
        with patch('cloud_locations.cloud_placeholder',return_value=True),patch('cloud_locations.os.scandir',side_effect=local_only):
            result=discover('win32',self.env,self.home,registrations=[])
        self.assertEqual(result['libraries'],[])
        self.assertEqual(result['roots'][0]['availability'],'online_only')

    def test_malformed_oversized_and_linked_configs_are_ignored(self):
        config=self.dropbox({'business':{'path':42}})
        self.assertEqual(provider_roots('win32',self.env,self.home,[]),[])
        config.write_bytes(b'x'*(1024*1024+1));self.assertIsNone(small_json(config))
        config.write_text('{broken');self.assertIsNone(small_json(config))

    def test_discovery_time_budget_is_explicitly_partial(self):
        root=self.home/'Dropbox';self.library(root)
        times=iter([0,3,4,5])
        result=discover('win32',self.env,self.home,registrations=[],clock=lambda:next(times))
        self.assertTrue(result['partial']);self.assertEqual(result['libraries'],[])

    def test_entry_budget_also_covers_database_filename_listings(self):
        root=self.home/'Dropbox';root.mkdir();(root/'master.db').write_bytes(b'opaque fixture')
        for number in range(12):(root/f'ordinary file {number}').write_bytes(b'')
        with patch('cloud_locations.MAX_ENTRIES',5):
            result=discover('win32',self.env,self.home,registrations=[])
        self.assertTrue(result['partial'])
        self.assertLessEqual(result['entries_seen'],5)
        # Exact name probes still recognize a database in an otherwise partial folder.
        self.assertEqual(len(result['libraries']),1)

    def test_redirected_provider_root_and_config_are_not_traversed_or_opened(self):
        target=self.home.parent/'Outside provider';self.library(target)
        alias=self.home/'Dropbox'
        try:alias.symlink_to(target,target_is_directory=True)
        except (OSError,NotImplementedError):self.skipTest('Directory symlinks unavailable on this host')
        config=self.dropbox({'business':{'path':str(alias)}})
        self.assertEqual(discover('win32',self.env,self.home,registrations=[])['roots'],[])
        alias.unlink()
        external=self.home.parent/'external-info.json';config.replace(external)
        config.symlink_to(external)
        with patch.object(Path,'open',side_effect=AssertionError('Redirected config was opened')):
            self.assertEqual(provider_roots('win32',self.env,self.home,[]),[])

    def test_windows_registrations_only_include_the_current_user_and_skip_network_volumes(self):
        from unittest.mock import MagicMock
        current='S-1-5-21-1234';google='GoogleDriveFS!provider';dropbox='Dropbox!provider'
        class Key:
            def __init__(self,name):self.name=name
            def __enter__(self):return self
            def __exit__(self,*args):pass
        def open_key(parent,name):return Key(name)
        def key_info(key):return (2,0,0) if key.name.endswith('SyncRootManager') else (0,2,0)
        def value(key,index):return (current if index==0 else 'S-1-5-21-another-user',r'D:\My Music' if index==0 else r'X:\Other customer',1)
        registry=SimpleNamespace(HKEY_CURRENT_USER=1,HKEY_LOCAL_MACHINE=2,REG_SZ=1,REG_EXPAND_SZ=2,
            OpenKey=open_key,QueryInfoKey=key_info,EnumKey=lambda key,index:(google,dropbox)[index],EnumValue=value)
        kernel=SimpleNamespace(GetLogicalDrives=lambda:(1<<6)|(1<<25),
            GetDriveTypeW=MagicMock(side_effect=lambda path:3 if path=='G:\\' else 4),
            GetVolumeInformationW=MagicMock())
        def volume(path,label,*args):label.value='Google Drive';return 1
        kernel.GetVolumeInformationW.side_effect=volume
        with patch('cloud_locations.os',SimpleNamespace(name='nt',path=os.path)),\
                patch('cloud_locations.current_windows_sid',return_value=current),\
                patch.dict(sys.modules,{'winreg':registry}),\
                patch('ctypes.windll',SimpleNamespace(kernel32=kernel),create=True):
            rows=windows_provider_paths()
        self.assertEqual({row['root'] for row in rows},{r'D:\My Music','G:\\'})
        self.assertEqual({row['kind'] for row in rows},{'dropbox','google_drive'})
        self.assertNotIn('Other customer',json.dumps(rows))
        self.assertEqual(kernel.GetVolumeInformationW.call_count,1)

    @unittest.skipUnless(os.name=='nt','Uses the actual Windows process token API')
    def test_actual_windows_process_sid_is_available_without_reading_other_profiles(self):
        self.assertRegex(current_windows_sid(),r'^S-1-\d+(?:-\d+)+$')

    def test_integrated_source_suggestions_include_the_customer_library(self):
        root=self.home/'Custom Team Dropbox';library=self.library(root,'Customer/rekordbox')
        self.dropbox({'business':{'path':str(root)}})
        result=discover_sources('win32',self.env,self.home)
        self.assertIn(str(library),[r['path'] for r in result['found']])
        self.assertIn('cloud_locations',result)

    def test_saved_custom_deep_location_is_probed_before_the_shallow_search(self):
        root=self.home/'Team Dropbox';library=self.library(root,'Customer/custom/music/Library renamed')
        self.dropbox({'business':{'path':str(root)}})
        recorded=root/'Customer/custom/music/Library renamed'
        result=discover('win32',self.env,self.home,[{'kind':'database','value':str(recorded)}],registrations=[])
        self.assertIn(str(library),[row['path'] for row in result['libraries']])

    def test_current_saved_location_is_not_reported_as_a_relocation_through_an_os_alias(self):
        root=self.home/'Dropbox';library=self.library(root)
        for recorded in (root/'rekordbox',root/'rekordbox/master.db'):
            result=discover('win32',self.env,self.home,[{'kind':'database','value':str(recorded)}],registrations=[])
            self.assertIn(str(library),[row['path'] for row in result['libraries']])
            self.assertEqual(result['relocations'],[])

    def test_metadata_cache_isolated_from_callers_and_explicit_refresh_discovers_changes(self):
        root=self.home/'Dropbox';first=self.library(root)
        clear_cache()
        try:
            cached=discover('win32',self.env,self.home,registrations=[],cache=True)
            cached['libraries'].clear()
            second=self.library(root,'Customer/rekordbox')
            reused=discover('win32',self.env,self.home,registrations=[],cache=True)
            self.assertEqual([row['path'] for row in reused['libraries']],[str(first)])
            clear_cache()
            refreshed=discover('win32',self.env,self.home,registrations=[],cache=True)
            self.assertEqual({row['path'] for row in refreshed['libraries']},{str(first),str(second)})
        finally:clear_cache()

    def test_excessive_nested_json_is_ignored_without_breaking_discovery(self):
        config=self.dropbox({})
        config.write_text('['*5000+']'*5000)
        self.assertIsNone(small_json(config))

    def test_relative_network_and_system_root_configuration_are_not_probed(self):
        self.dropbox({'personal':{'path':'../outside'},'business':{'path':'//remote-host/share'},
                      'other':{'path':'/'},'bad_alias':{'path':'~nonexistent-workbench-user-869104/Dropbox'}})
        self.assertEqual(provider_roots('linux',self.env,self.home,[]),[])

    def test_provider_disconnected_during_metadata_discovery_is_skipped(self):
        root=self.home/'Dropbox';root.mkdir()
        resolve=Path.resolve
        def disconnected(path,*args,**kwargs):
            if path==root:raise OSError('Provider drive was disconnected')
            return resolve(path,*args,**kwargs)
        with patch.object(Path,'resolve',disconnected):
            self.assertEqual(provider_roots('win32',self.env,self.home,[]),[])

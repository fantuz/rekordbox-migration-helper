from pathlib import Path
import json
import tempfile
import unittest
from xml.etree.ElementTree import Element,SubElement,tostring

from platform_paths import default_data_directory,discover_sources


class PlatformPathTests(unittest.TestCase):
    def test_platform_workspaces_are_separate_from_packaged_apps(self):
        home=Path('/users/example')
        self.assertEqual(default_data_directory(Path('/app'),'darwin',{},home),home/'Library/Application Support/LibraryWorkbench')
        self.assertEqual(default_data_directory(Path('/app'),'win32',{'LOCALAPPDATA':'/local'},home),Path('/local/LibraryWorkbench'))
        self.assertEqual(default_data_directory(Path('/app'),'linux',{},home),Path('/app/.data'))

    def test_windows_settings_discover_a_relocated_database_without_modification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);appdata=root/'Roaming'
            folder=appdata/'Pioneer/rekordbox6';folder.mkdir(parents=True)
            library=root/'custom cloud library';library.mkdir();(library/'master.db').write_bytes(b'fixture')
            tree=Element('PROPERTIES');SubElement(tree,'VALUE',name='masterDbDirectory',val=str(library))
            settings=folder/'rekordbox3.settings';settings.write_bytes(tostring(tree));before=settings.read_bytes()
            result=discover_sources('win32',{'APPDATA':str(appdata)},root)
            self.assertEqual(result['found'][0]['path'],str(library.resolve()))
            self.assertIn('saved',result['found'][0]['origin'])
            self.assertEqual(settings.read_bytes(),before)

    def test_mac_default_and_alternative_roots_are_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for path in ('Library/Pioneer/rekordbox','Library/Application Support/Pioneer/rekordbox6'):
                folder=root/path;folder.mkdir(parents=True);(folder/'master.db').write_bytes(b'fixture')
            result=discover_sources('darwin',{},root)
            self.assertEqual(len(result['found']),2)

    def test_linux_keeps_manual_path_selection_without_assuming_live_installation(self):
        result=discover_sources('linux',{},Path('/home/example'))
        self.assertEqual(result['found'],[])
        self.assertEqual(result['standard_locations'],[])
        self.assertIn('enter the path',result['help'])

    def test_agent_pointer_precedes_old_default_and_keeps_unrelated_options_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);appdata=root/'Roaming';base=appdata/'Pioneer'
            old=base/'rekordbox';old.mkdir(parents=True);(old/'master.db').write_bytes(b'old database')
            current=root/'Cloud library';current.mkdir();(current/'master.db').write_bytes(b'current database')
            analysis=root/'Analysis assets';analysis.mkdir()
            options=base/'rekordboxAgent/storage/options.json';options.parent.mkdir(parents=True)
            options.write_text(json.dumps({'options':[['db-path',str(current/'master.db')],['analysis-data-root-path',str(analysis)],['dp','private-device-value']]}))
            before=options.read_bytes();result=discover_sources('win32',{'APPDATA':str(appdata)},root)
            self.assertEqual(result['found'][0]['path'],str(current));self.assertEqual(len(result['found']),2)
            self.assertEqual(result['analysis_locations'][0]['path'],str(analysis))
            self.assertNotIn('private-device-value',json.dumps(result));self.assertEqual(options.read_bytes(),before)

    def test_mac_agent_dictionary_and_nested_master_location(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);external=root/'External/PIONEER/Master';external.mkdir(parents=True)
            (external/'master.db').write_bytes(b'discovery does not open SQL')
            options=root/'Library/Application Support/Pioneer/rekordboxAgent/storage/options.json';options.parent.mkdir(parents=True)
            options.write_text(json.dumps({'options':{'db-path':str(external.parent.parent)}}))
            self.assertEqual(discover_sources('darwin',{},root)['found'][0]['path'],str(external))

    def test_malformed_and_relative_agent_paths_do_not_break_other_candidates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);base=root/'Pioneer';library=base/'rekordbox';library.mkdir(parents=True)
            (library/'master.db').write_bytes(b'fixture');options=base/'rekordboxAgent/storage/options.json';options.parent.mkdir(parents=True)
            for content in ('not JSON',json.dumps({'options':[['db-path','relative/master.db']]})):
                options.write_text(content)
                result=discover_sources('win32',{'APPDATA':str(root)},root)
                self.assertEqual(result['found'][0]['path'],str(library))

    def test_linux_binary_data_uses_xdg_without_moving_source_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            user=Path(temporary).resolve();data=user/'custom data'
            self.assertEqual(default_data_directory('/application','linux',{},user,True),user/'.local/share/LibraryWorkbench')
            self.assertEqual(default_data_directory('/application','linux',{'XDG_DATA_HOME':str(data)},user,True),data/'LibraryWorkbench')
            self.assertEqual(default_data_directory('/application','linux',{'XDG_DATA_HOME':'relative'},user,True),user/'.local/share/LibraryWorkbench')
            self.assertEqual(default_data_directory('/application','linux',{},user,False),Path('/application/.data'))



if __name__=='__main__':unittest.main()

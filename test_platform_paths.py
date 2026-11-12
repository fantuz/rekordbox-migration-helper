from pathlib import Path
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


if __name__=='__main__':unittest.main()

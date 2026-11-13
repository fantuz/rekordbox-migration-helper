"""Portable applications must not inject bundled libraries into a system browser."""
import os
import unittest
from unittest.mock import patch

import desktop_launcher


class BrowserEnvironmentTests(unittest.TestCase):
    def test_frozen_linux_browser_uses_host_libraries_and_restores_application_environment(self):
        for original in (None,'/user/original/libraries'):
            environment={'LD_LIBRARY_PATH':'/synthetic/bundle/_internal'}
            if original is not None:environment['LD_LIBRARY_PATH_ORIG']=original
            seen=[]
            with patch.dict(os.environ,environment,clear=True),patch.object(desktop_launcher.sys,'frozen',True,create=True),\
                 patch.object(desktop_launcher.sys,'platform','linux'),\
                 patch.object(desktop_launcher.webbrowser,'open',side_effect=lambda url:seen.append((url,dict(os.environ)))):
                desktop_launcher.open_browser('http://127.0.0.1:8765')
                self.assertEqual(seen[0][0],'http://127.0.0.1:8765')
                self.assertEqual(seen[0][1].get('LD_LIBRARY_PATH'),original)
                self.assertEqual(dict(os.environ),environment)

    def test_browser_failure_does_not_leave_the_runtime_environment_changed(self):
        environment={'LD_LIBRARY_PATH':'/synthetic/bundle/_internal'}
        with patch.dict(os.environ,environment,clear=True),patch.object(desktop_launcher.sys,'frozen',True,create=True),\
             patch.object(desktop_launcher.sys,'platform','linux'),\
             patch.object(desktop_launcher.webbrowser,'open',side_effect=OSError('Synthetic browser failure')):
            with self.assertRaises(OSError):desktop_launcher.open_browser('http://127.0.0.1:8765')
            self.assertEqual(dict(os.environ),environment)


if __name__=='__main__':unittest.main()

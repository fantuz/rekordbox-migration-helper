from pathlib import Path
from threading import Event
from unittest.mock import patch
import json
import tempfile
import unittest
import os
import signal
import subprocess
import sys
import time
import urllib.request

from temporary_files import TemporaryWorkspace,OWNER
from shutdown_cleanup import ShutdownController
from file_workflow import pair_signature


class TemporaryFilesTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.runtime=TemporaryWorkspace(self.root);self.addCleanup(self.runtime.best_effort_cleanup)

    def test_cleanup_removes_owned_copies_only_and_keeps_reports_exports_and_originals(self):
        original=self.root/'my-original.zip';original.write_bytes(b'original')
        report=self.root/'reports/decision.json';report.parent.mkdir();report.write_text('keep')
        exported=self.root/'exports/summary.html';exported.parent.mkdir();exported.write_text('keep')
        copy=self.runtime.folder('upload')/'copy.zip';copy.write_bytes(original.read_bytes())
        try:(self.runtime.path/'source-link').symlink_to(original)
        except OSError:pass
        self.runtime.cleanup()
        self.assertFalse(copy.exists());self.assertFalse(self.runtime.path.exists())
        self.assertEqual(original.read_bytes(),b'original');self.assertEqual(report.read_text(),'keep');self.assertEqual(exported.read_text(),'keep')

    def test_running_operations_and_other_instances_are_protected(self):
        with self.runtime.operation():
            with self.assertRaises(RuntimeError):self.runtime.cleanup()
        other=TemporaryWorkspace(self.root);self.addCleanup(other.best_effort_cleanup)
        self.assertTrue(self.runtime.path.exists());self.assertNotIn(self.runtime.path.name,other.recovered)

    def test_only_marked_unlocked_stale_folders_are_recovered(self):
        old=self.runtime.path;self.runtime.lock.close();self.runtime.lock=None
        (old/'large.partial').write_bytes(b'private analysis')
        unrelated=self.runtime.parent/'unrelated';unrelated.mkdir();(unrelated/'original.db').write_bytes(b'keep')
        recovered=TemporaryWorkspace(self.root);self.addCleanup(recovered.best_effort_cleanup)
        self.assertIn(old.name,recovered.recovered);self.assertFalse(old.exists());self.assertTrue((unrelated/'original.db').exists())

    def test_shutdown_requires_acknowledgement_and_waits_for_workers(self):
        stopped=Event();cancelled=Event()
        control=ShutdownController(self.runtime,cancelled.set,lambda:None,stopped.set)
        with self.assertRaises(ValueError):control.request(False)
        self.assertFalse(control.requested.is_set());self.assertTrue(self.runtime.path.exists())
        control.request(True);control.thread.join(5)
        self.assertTrue(stopped.is_set());self.assertTrue(cancelled.is_set());self.assertEqual(control.status()['phase'],'complete')
        self.assertFalse(self.runtime.path.exists());self.assertFalse(json.loads((self.root/'cleanup-last.json').read_text())['originals_modified'])

    def test_cleanup_failure_keeps_app_open_for_retry(self):
        stopped=Event();control=ShutdownController(self.runtime,lambda:None,lambda:None,stopped.set)
        with patch.object(self.runtime,'cleanup',side_effect=OSError('file busy')):
            control.request(True);control.thread.join(5)
        self.assertEqual(control.status()['phase'],'error');self.assertFalse(stopped.is_set())
        control.request(True);control.thread.join(5);self.assertTrue(stopped.is_set())


class ResumeIdentityTests(unittest.TestCase):
    def test_reattached_pair_ignores_filename_but_detects_changed_metadata(self):
        import zipfile,shutil
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);xml=root/'first.xml';zip=root/'first.zip';xml.write_text('<collection/>')
            with zipfile.ZipFile(zip,'w') as z:z.writestr('master.db',b'native database');z.writestr('analysis',b'assets')
            identity=pair_signature(zip,xml)
            newzip=root/'renamed.zip';newxml=root/'renamed.xml';shutil.copyfile(zip,newzip);shutil.copyfile(xml,newxml)
            self.assertEqual(identity,pair_signature(newzip,newxml));newxml.write_text('<changed/>')
            self.assertNotEqual(identity,pair_signature(newzip,newxml))

    def test_reattach_preserves_workspace_identity_and_rejects_other_snapshots(self):
        import app as application
        import zipfile
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);sid='b'*32;folder=root/sid;folder.mkdir();catalog=folder/'catalog.sqlite3';catalog.write_bytes(b'saved review metadata')
            xml=root/'original.xml';xml.write_text('<collection/>');backup=root/'original.zip'
            with zipfile.ZipFile(backup,'w') as z:z.writestr('master.db',b'native database')
            state={'metadata':{'source':str(catalog),'pair_signature':pair_signature(backup,xml)},'decisions':{'pair':{'action':'merge','keeper':'one'}}}
            saved=folder/'state.json';saved.write_text(json.dumps(state))
            with patch.object(application,'DATA',root),patch.object(application,'load_session',return_value={'session':sid}) as load:
                result=application.reattach_inputs(sid,{'zip':backup,'xml':xml},lambda *_:None,'linked')
                self.assertEqual(result['session'],sid);self.assertEqual(load.call_args.args[1],sid)
                xml.write_text('<different/>')
                with self.assertRaisesRegex(ValueError,'differ'):application.reattach_inputs(sid,{'zip':backup,'xml':xml},lambda *_:None,'linked')
            self.assertEqual(json.loads(saved.read_text())['decisions'],state['decisions'])


@unittest.skipIf(sys.platform=='win32','Console signals are tested on Linux/macOS; Windows uses acknowledged HTTP shutdown')
class ConsoleShutdownTests(unittest.TestCase):
    def test_first_ctrl_c_warns_and_second_cleans_then_exits(self):
        with tempfile.TemporaryDirectory() as temp:
            data=Path(temp);report=data/'saved-report.json';report.write_text('keep')
            process=subprocess.Popen([sys.executable,str(Path(__file__).parent/'desktop_launcher.py'),'--no-browser','--port','0'],
                                     env={**os.environ,'LIBRARY_WORKBENCH_DATA_DIR':str(data)},stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            try:
                deadline=time.monotonic()+30
                while not (data/'instance.json').exists() and time.monotonic()<deadline:time.sleep(.05)
                base=json.loads((data/'instance.json').read_text())['url']
                with urllib.request.urlopen(base+'/api/cleanup',timeout=5) as response:temporary=json.load(response)['directory']
                process.send_signal(signal.SIGINT);time.sleep(.1)
                self.assertIsNone(process.poll());self.assertTrue(Path(temporary).is_dir())
                with urllib.request.urlopen(base+'/api/status',timeout=5) as response:self.assertEqual(json.load(response)['cleanup']['phase'],'running')
                process.send_signal(signal.SIGINT);output=process.communicate(timeout=15)[0]
                self.assertEqual(process.returncode,0,output);self.assertIn('Press Ctrl+C again to confirm',output)
                self.assertFalse(Path(temporary).exists());self.assertEqual(report.read_text(),'keep')
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:process.communicate(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.communicate()


if __name__=='__main__':unittest.main()

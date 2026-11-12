from pathlib import Path
from threading import Event
from unittest.mock import patch
import json
import tempfile
import unittest

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


if __name__=='__main__':unittest.main()

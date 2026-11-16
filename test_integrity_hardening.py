"""Regression cases discovered by the synthetic integrity investigation."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from hashlib import sha256
import os
import unittest

import app
import test_export_verification
from file_workflow import fingerprint_inputs,check_inputs,list_exports
from metadata_overrides import validate
from workbench_store import Store


class ContentIdentityTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_export_verification.IndependentExportTests('test_both_written_formats_pass_for_real_metadata_and_relocations')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.fixture.catalog.metadata['field_overrides']={}
        self.fixture.catalog.metadata['input_fingerprints']=fingerprint_inputs(self.fixture.catalog.metadata,content=True)
        self.fixture.catalog.metadata['xml_sha256']=sha256(self.fixture.xml.read_bytes()).hexdigest()

    def test_equal_size_xml_replacement_with_restored_time_cannot_be_exported(self):
        path=self.fixture.xml;before=path.stat();path.write_bytes(path.read_bytes().replace(b'Song b',b'Edit b'))
        os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,'changed'):self.fixture.prepare(kind='xml')
        self.assertEqual(list_exports(self.fixture.root/'exports'),[])

    def test_equal_size_backup_replacement_with_restored_time_cannot_be_exported(self):
        path=self.fixture.backup;before=path.stat()
        path.write_bytes(path.read_bytes().replace(b'original asset',b'modified asset'))
        os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,'changed'):self.fixture.prepare()
        self.assertEqual(list_exports(self.fixture.root/'exports'),[])

    def test_legacy_xml_hash_is_checked_before_upgrade(self):
        del self.fixture.catalog.metadata['input_fingerprints']
        path=self.fixture.xml;path.write_bytes(path.read_bytes().replace(b'Song b',b'Edit b'))
        with self.assertRaisesRegex(ValueError,'XML content changed'):self.fixture.prepare(kind='xml')

    def test_stats_only_checks_retain_hashes_and_content_reads_are_cancellable(self):
        meta=self.fixture.catalog.metadata
        self.assertEqual(check_inputs(meta),meta['input_fingerprints'])
        from task_control import OperationCancelled
        def cancel(*_):raise OperationCancelled('stop hashing')
        with self.assertRaises(OperationCancelled):check_inputs(meta,content=True,progress=cancel)


class TextValidationTests(unittest.TestCase):
    def test_invalid_save_preserves_value_history_and_revision_for_every_text_field(self):
        with TemporaryDirectory() as tmp,patch.object(app,'DATA',Path(tmp)):
            store=Store(Path(tmp)/'workbench-sidecar.sqlite3')
            scope='synthetic:invalid-text';source={'scope_key':scope,'tracks':[{'id':'one','title':'Before'}]}
            sid=store.save_snapshot(source,'Validation')['id'];client=app.app.test_client()
            headers={'X-Workbench-Token':app.TOKEN}
            self.assertEqual(client.post('/api/lab/unlock',json={'snapshot':sid,'unlocked':True},headers=headers).status_code,200)
            for field in ('title','artist','album','genre','comment'):
                before=store.edit_state(scope,history=True)
                for bad in ('bad\ufffe','bad\uffff','bad\ud800'):
                    response=client.post('/api/lab/overrides',json={'snapshot':sid,'track_id':'one','field':field,'value':bad,'edit_revision':before['edit_revision']},headers=headers)
                    self.assertEqual(response.status_code,400,(field,ascii(bad),response.json))
                    self.assertEqual(store.edit_state(scope,history=True),before)
                self.assertEqual(validate(field,'日本 Ελληνικά 🎧'),'日本 Ελληνικά 🎧')


class RetentionTests(unittest.TestCase):
    def test_concurrent_submission_and_completion_keep_the_terminal_bound(self):
        from concurrent.futures import ThreadPoolExecutor
        from contextlib import nullcontext
        with patch.object(app,'tasks',{}),patch.object(app,'task_controls',{}),patch.object(app,'MAX_COMPLETED_TASKS',3),\
             patch.object(app.TEMPORARY,'operation',side_effect=lambda:nullcontext()):
            with ThreadPoolExecutor(max_workers=4) as workers:
                with ThreadPoolExecutor(max_workers=4) as clients:
                    list(clients.map(lambda n:app.launch(lambda p:{'id':n},'Concurrent job',pool=workers),range(64)))
            self.assertEqual(len(app.tasks),3)
            self.assertTrue(all(t['status']=='complete' for t in app.tasks.values()))
            self.assertEqual(app.task_controls,{})

    def test_terminal_results_are_bounded_active_jobs_and_saved_outputs_are_preserved(self):
        with patch.object(app,'tasks',{}),patch.object(app,'task_controls',{}),patch.object(app,'MAX_COMPLETED_TASKS',3):
            app.tasks['active']={'status':'running'}
            for n in range(6):app.tasks[str(n)]={'status':'complete','_completed_at':n,'result':{'download':'saved-file'}}
            with patch.object(app,'monotonic',return_value=10):app.prune_tasks()
            self.assertEqual(set(app.tasks),{'active','3','4','5'})
            with patch.object(app,'monotonic',return_value=4000):app.prune_tasks()
            self.assertEqual(set(app.tasks),{'active'})

    def test_task_is_not_evicted_until_completion_callback_releases_control(self):
        with patch.object(app,'tasks',{'finishing':{'status':'complete','_completed_at':0}}),patch.object(app,'task_controls',{'finishing':object()}):
            with patch.object(app,'monotonic',return_value=4000):app.prune_tasks()
            self.assertIn('finishing',app.tasks)

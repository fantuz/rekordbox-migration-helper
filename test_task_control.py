import unittest
from unittest.mock import patch
from task_control import TaskControl, OperationCancelled
import app as application


class CancellationTests(unittest.TestCase):
    def test_checkpoints_and_published_result(self):
        control=TaskControl();control.checkpoint(0);control.cancel()
        with self.assertRaises(OperationCancelled):control.checkpoint(75)
        control.checkpoint(100)

    def test_cancel_requires_local_token_and_preserves_other_tasks(self):
        first,second=TaskControl(),TaskControl()
        with patch.object(application,'tasks',{'one':{'status':'running'},'two':{'status':'running'}}),patch.object(application,'task_controls',{'one':first,'two':second}):
            client=application.app.test_client()
            self.assertEqual(client.post('/api/tasks/one/cancel').status_code,403)
            response=client.post('/api/tasks/one/cancel',json={},headers={'X-Workbench-Token':application.TOKEN})
            self.assertTrue(response.json['cancel_requested']);self.assertTrue(first.event.is_set())
            self.assertFalse(second.event.is_set())
            self.assertEqual(application.tasks['two'],{'status':'running'})

    def test_late_cancel_reports_completion(self):
        with patch.object(application,'tasks',{'done':{'status':'complete','result':{'id':'kept'}}}),patch.object(application,'task_controls',{}):
            response=application.app.test_client().post('/api/tasks/done/cancel',json={},headers={'X-Workbench-Token':application.TOKEN})
            self.assertEqual(response.json['status'],'complete');self.assertFalse(response.json['cancel_requested'])
            self.assertEqual(application.tasks['done']['result'],{'id':'kept'})


class QueuedPool:
    def submit(self,work):self.work=work


class TaskLifecycleTests(unittest.TestCase):
    def setUp(self):
        from contextlib import nullcontext
        for patcher in (patch.object(application,'tasks',{}),patch.object(application,'task_controls',{}),
                        patch.object(application.TEMPORARY,'operation',side_effect=lambda:nullcontext())):
            patcher.start();self.addCleanup(patcher.stop)
        self.pool=QueuedPool()

    def test_cancel_queued_task_never_starts_work_and_releases_control(self):
        from unittest.mock import Mock
        work=Mock();job=application.launch(work,'Queued',self.pool)
        application.task_controls[job].cancel();self.pool.work()
        work.assert_not_called();self.assertEqual(application.tasks[job]['status'],'cancelled')
        self.assertNotIn(job,application.task_controls)

    def test_cancel_running_task_stops_at_checkpoint_and_keeps_completed_decisions(self):
        retained=[]
        def work(progress):
            retained.append('saved decision');application.task_controls[job].cancel();progress(40,'Next checkpoint')
            self.fail('Cancelled work must stop at its checkpoint')
        job=application.launch(work,'Working',self.pool);self.pool.work()
        self.assertEqual(application.tasks[job]['status'],'cancelled');self.assertEqual(retained,['saved decision'])
        self.assertNotIn(job,application.task_controls)

    def test_cancel_after_publication_keeps_completed_result_visible(self):
        def work(progress):
            application.task_controls[job].cancel();progress(100,'Published')
            return {'id':'deliberate-export'}
        job=application.launch(work,'Exporting',self.pool);self.pool.work()
        self.assertEqual(application.tasks[job]['status'],'complete')
        self.assertEqual(application.tasks[job]['result'],{'id':'deliberate-export'})
        self.assertNotIn(job,application.task_controls)

    def test_work_error_releases_only_its_own_control(self):
        other=TaskControl();application.task_controls['other']=other
        def work(progress):raise ValueError('Synthetic failure')
        job=application.launch(work,'Working',self.pool);self.pool.work()
        self.assertEqual(application.tasks[job]['status'],'error');self.assertNotIn(job,application.task_controls)
        self.assertIs(application.task_controls['other'],other);self.assertFalse(other.event.is_set())

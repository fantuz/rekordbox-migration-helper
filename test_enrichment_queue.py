from test_support import workspace_client
"""Use the real launch wrapper and serial worker; never call a provider."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import app
from musicbrainz_pilot import create_batch, batch_record
from workbench_store import Store, encoded


class EnrichmentQueueTests(unittest.TestCase):
    def setUp(self):
        context=patch('enrichment_context.source_details',return_value={'kind':'workspace','id':'queue-test'})
        context.start();self.addCleanup(context.stop)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        for p in (patch.object(app,'DATA',Path(temp.name)),patch.object(app,'tasks',{}),patch.object(app,'task_controls',{})):
            p.start();self.addCleanup(p.stop)
        self.store=Store(Path(temp.name)/'workbench-sidecar.sqlite3')
        sid=self.store.save_snapshot({'schema':1,'scope_key':'queue-test','tracks':[
            {'id':'one','title':'Test','artist':'DJ','duration':180,'genre':'Test'}],
            'playlists':[],'capabilities':{}},'Queue test')['id']
        self.store.set_setting('musicbrainz_enabled',True)
        self.batches=[create_batch(self.store,self.store.snapshot(sid),sample_size=150) for _ in range(3)]
        self.client=workspace_client(app);self.headers={'X-Workbench-Token':app.TOKEN}

    def start(self,index):
        r=self.client.post('/api/lab/musicbrainz/'+self.batches[index]['id']+'/start',json={'query_consent':True},headers=self.headers)
        self.assertEqual(r.status_code,200,r.json)
        return r.json['job']

    def test_cancel_before_worker_starts_releases_queue_reservation(self):
        pending=[]
        class Pool:
            def submit(self,function):pending.append(function)
        original=app.launch
        def launch(work,message,**kwargs):return original(work,message,Pool(),kwargs['on_finished'])
        with patch.object(app,'launch',side_effect=launch):
            job=self.start(0)
        app.task_controls[job].cancel();pending[0]()
        self.assertEqual(batch_record(self.store,self.batches[0]['id'])['status'],'cancelled')
        self.assertFalse(app.lab_jobs_active())
        with patch.object(app,'launch',side_effect=launch):
            resumed=self.start(0)
        app.task_controls[resumed].cancel();pending[1]()
        self.assertFalse(app.lab_jobs_active())

    def test_real_serial_queue_survives_polling_and_a_failed_batch(self):
        entered=threading.Event();release=threading.Event();finished=threading.Event();order=[]
        def run(saved,identity,client,progress):
            order.append(identity)
            with saved.connection() as db:db.execute("UPDATE mb_batches SET status='running' WHERE id=?",(identity,))
            if identity==self.batches[0]['id']:
                entered.set()
                if not release.wait(5):raise RuntimeError('Test did not release first batch')
                raise ValueError('Synthetic first batch failure')
            with saved.connection() as db:
                db.execute("UPDATE mb_batches SET status='complete' WHERE id=?",(identity,))
            if identity==self.batches[2]['id']:finished.set()
            return {'status':'complete'}
        with patch('lab_routes.run_batch',side_effect=run):
            jobs=[]
            try:
                jobs.append(self.start(0));self.assertTrue(entered.wait(3))
                jobs.extend([self.start(1),self.start(2)])
                for _ in range(3):
                    rows=self.client.get('/api/lab/musicbrainz/batches').json['batches']
                    self.assertEqual([r['id'] for r in rows], [b['id'] for b in self.batches])
                    self.assertEqual([r['status'] for r in rows],['running','queued','queued'])
                    self.assertEqual([r['queue_position'] for r in rows],[1,2,3])
            finally:
                release.set()
                self.assertTrue(finished.wait(5))
                deadline=time.monotonic()+3
                while any(app.tasks[j]['status']=='running' for j in jobs) and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(order,[b['id'] for b in self.batches])
        statuses={r['id']:r['status'] for r in self.client.get('/api/lab/musicbrainz/batches').json['batches']}
        self.assertEqual([statuses[b['id']] for b in self.batches],['interrupted','complete','complete'])
        self.assertFalse(app.lab_jobs_active())


if __name__=='__main__':unittest.main()

"""Exercise real catalog SQL, cancellation, same-upload retries and missing metadata."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import json
import sqlite3
import unittest
import zipfile

import app as application
from engine import analyze,Catalog
from research_capture import capture_workspace
from task_control import OperationCancelled
from temporary_files import TemporaryWorkspace
from track_flags import flags


class ImportReliabilityTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        master=self.root/'master.db'
        with closing(sqlite3.connect(master)) as db:
            db.executescript('''
              CREATE TABLE djmdArtist(ID TEXT,Name TEXT);
              CREATE TABLE djmdContent(ID TEXT,Title TEXT,ArtistID TEXT,FileSize INTEGER,Length INTEGER,
                Rating INTEGER,Commnt TEXT,DeviceID TEXT,ServiceID INTEGER,FolderPath TEXT,OrgFolderPath TEXT,
                AnalysisDataPath TEXT,ImagePath TEXT,DJPlayCount INTEGER,rb_local_deleted INTEGER);
              CREATE TABLE djmdCue(ID TEXT,ContentID TEXT,rb_local_deleted INTEGER);
              CREATE TABLE contentCue(ContentID TEXT,Cues TEXT,rb_local_deleted INTEGER);
            ''')
            for identity,size,seconds in [('known',100,240),('zero',0,0),('unknown',None,None)]:
                db.execute('INSERT INTO djmdContent VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (identity,identity,None,size,seconds,0,'',None,0,'D:/Music/'+identity+'.wav',None,'','',0,0))
            db.commit()
        self.backup=self.root/'library.zip';self.xml=self.root/'library.xml'
        with zipfile.ZipFile(self.backup,'w') as archive:archive.write(master,'master.db')
        self.xml.write_text('<DJ_PLAYLISTS><PRODUCT Version="7.2.0"/><COLLECTION Entries="3">'+
            ''.join('<TRACK TrackID="'+identity+'" Size="'+str(size)+'" Location="file://localhost/D:/Music/'+identity+'.wav"/>'
                    for identity,size in [('known',100),('zero',0),('unknown',0)])+'</COLLECTION></DJ_PLAYLISTS>',encoding='utf-8')
        # Ordinary synthetic SQLite substitutes only for source decryption; importer SQL is real.
        for p in (patch('engine.open_master',side_effect=lambda path:sqlite3.connect(path)),
                  patch.dict('sys.modules',{'sqlcipher3':SimpleNamespace(Row=sqlite3.Row)})):
            p.start();self.addCleanup(p.stop)
        self.output=self.root/'saved'

    def run_analysis(self,progress=lambda *_:None):
        return analyze(self.backup,self.xml,self.output,progress)

    def test_cancel_or_failure_after_table_creation_can_retry_and_preserves_previous_catalog(self):
        self.run_analysis();previous=(self.output/'catalog.sqlite3').read_bytes()
        for error in (OperationCancelled('Cancelled'),OSError('disk full')):
            def interrupted(amount,_text):
                if amount==80:raise error
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(type(error)):self.run_analysis(interrupted)
                self.assertEqual((self.output/'catalog.sqlite3').read_bytes(),previous)
                self.assertEqual(list(self.output.glob('.catalog-*')),[])
                self.assertEqual(len(Catalog(self.run_analysis()['source'],{}).tracks),3)

    def test_failed_catalog_replace_can_retry(self):
        self.run_analysis();previous=(self.output/'catalog.sqlite3').read_bytes()
        with patch('engine.os.replace',side_effect=OSError('publication failed')):
            with self.assertRaises(OSError):self.run_analysis()
        self.assertEqual((self.output/'catalog.sqlite3').read_bytes(),previous)
        self.assertFalse(list(self.output.glob('.catalog-*')))
        self.assertEqual(len(Catalog(self.run_analysis()['source'],{}).tracks),3)

    def test_nulls_survive_import_capture_filters_and_statistics(self):
        metadata=self.run_analysis();catalog=Catalog(metadata['source'],metadata)
        rows={t['id']:t for t in capture_workspace(catalog,'session:test')['tracks']}
        self.assertIsNone(rows['unknown']['duration']);self.assertIsNone(rows['unknown']['size'])
        self.assertEqual(flags(rows['unknown']),[])
        self.assertEqual(flags(rows['zero']),['zero_duration','zero_size'])
        session={'id':'test','catalog':catalog,'metadata':metadata,'decisions':{},'relocations':{},'events':[]}
        with patch.object(application,'DATA',self.root),patch.object(application,'active','test'),patch.object(application,'sessions',{'test':session}):
            client=application.app.test_client()
            response=client.get('/api/statistics')
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual(response.json['counters']['total'],3)
            self.assertEqual(response.json['unknown_duration'],1)
            self.assertEqual(sum(b['count'] for b in response.json['histogram']),2)
            filtered=client.get('/api/statistics?max=1')
            self.assertEqual(filtered.json['counters']['total'],1)
        self.assertTrue(application.duration_in_range(None,0,float('inf')))
        self.assertFalse(application.duration_in_range(None,0,60))

    def test_same_uploaded_pair_retries_after_state_save_failure_without_reupload(self):
        runtime=TemporaryWorkspace(self.root);self.addCleanup(runtime.best_effort_cleanup)
        old={'id':'old','decisions':{'pair':{'action':'skip'}}};tasks={}
        for name,value in [('DATA',self.root),('TEMPORARY',runtime),('active','old'),('sessions',{'old':old}),('tasks',tasks)]:
            p=patch.object(application,name,value);p.start();self.addCleanup(p.stop)
        client=application.app.test_client();headers={'X-Workbench-Token':application.TOKEN}
        sid=client.post('/api/import',json={'zip':'library.zip','xml':'library.xml'},headers=headers).json['session']
        for kind,path in [('zip',self.backup),('xml',self.xml)]:
            response=client.put('/api/upload/'+sid+'/'+kind,data=path.read_bytes(),headers=headers)
            self.assertEqual(response.status_code,200,response.json)
        def launch(work,*_args,**_kwargs):
            job=str(len(tasks));tasks[job]={'id':job,'status':'running'}
            try:tasks[job].update(status='complete',result=work(lambda *_:None))
            except OSError as error:tasks[job].update(status='error',message=str(error))
            return job
        with patch.object(application,'enrich_usage'),patch.object(application,'launch',side_effect=launch):
            with patch.object(application,'persist',side_effect=OSError('disk full')):
                first=client.post('/api/import/'+sid+'/analyze',json={},headers=headers)
            self.assertEqual(tasks[first.json['job']]['status'],'error')
            self.assertEqual(application.active,'old');self.assertIs(application.sessions['old'],old)
            self.assertTrue(all(f['complete'] for f in client.get('/api/import/'+sid).json['files'].values()))
            second=client.post('/api/import/'+sid+'/analyze',json={},headers=headers)
            self.assertEqual(tasks[second.json['job']]['status'],'complete')
            self.assertEqual(application.active,sid)
            self.assertEqual(len(application.sessions[sid]['catalog'].tracks),3)
            state=json.loads((self.root/sid/'state.json').read_text())
            self.assertEqual(state['id'],sid)

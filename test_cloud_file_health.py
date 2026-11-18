"""Invented provider paths and OS attributes; no account, daemon or audio reads."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import stat
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import app as application
from cloud_file_status import lexical_path, path_providers, track_providers
from file_status_cache import inspect as cached_inspect, fingerprint
from test_support import workspace_client
from track_playback import inspect_audio_details, available_audio
from workbench_store import Store


class CloudMetadataTests(unittest.TestCase):
    def test_provider_paths_are_component_bounded_cross_platform_and_never_filename_guesses(self):
        roots=[{'kind':'dropbox','root':r'C:\Users\tester\Shared team','provider_verified':True},
               {'kind':'google_drive','root':'G:/Custom volume','provider_verified':True},
               {'kind':'dropbox','root':'/music/Team','provider_verified':True}]
        for raw,kind in [(r'c:\users\TESTER\shared TEAM\Set\song.mp3','dropbox'),
                         ('file://localhost/C:/Users/tester/Shared%20team/Set/song.mp3','dropbox'),
                         ('G:/Custom volume/Audio/test.flac','google_drive'),
                         ('/music/Team/Audio/test.mp3','dropbox'),
                         ('/users/tester/Example team Dropbox/Customer/Music/test.mp3','dropbox'),
                         ('/users/tester/GoogleDrive-account/My Drive/test.mp3','google_drive')]:
            self.assertIn(kind,path_providers(raw,roots),raw)
        for raw in (r'C:\Users\tester\Shared teammate\song.mp3','/music/team/song.mp3',
                    '/music/Dropbox.mp3','/music/MyDropbox/song.mp3','/music/Teamwork/song.mp3',
                    'https://example.test/Dropbox/song.mp3','file://remote/Dropbox/song.mp3',
                    '../Dropbox/song.mp3',r'\\server\Dropbox\song.mp3',r'C:\Dropbox\..\song.mp3',
                    r'C:\Dropbox\song.mp3:stream','/Dropbox/song.mp3\0'):
            self.assertEqual(path_providers(raw,roots),{},raw)
        self.assertIsNone(lexical_path('file://[broken'))
        matches=track_providers({'current_path':'/music/Team/one.mp3','original_path':'G:/Custom volume/one.mp3'},[],roots)
        self.assertEqual(set(matches),{'dropbox','google_drive'})

    def test_every_recall_flag_is_metadata_only_and_never_locally_playable(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/'Dropbox'/'Synthetic.mp3';path.parent.mkdir();path.write_bytes(b'synthetic placeholder')
            before=sha256(path.read_bytes()).hexdigest();real=path.lstat()
            for field,flag in [('st_file_attributes',0x1000),('st_file_attributes',0x40000),
                               ('st_file_attributes',0x400000),('st_flags',0x40000000)]:
                values={name:getattr(real,name) for name in dir(real) if name.startswith('st_')}
                values.update({field:flag,'st_size':12345678})
                with self.subTest(field=field,flag=flag),patch.object(Path,'lstat',return_value=SimpleNamespace(**values)),patch.object(Path,'open',side_effect=AssertionError('Audio content opened')):
                    result=inspect_audio_details({'current_path':str(path)},roots=[])
                    self.assertEqual(result['status'],'unverified');self.assertEqual(result['cloud_state'],'online_only')
                    self.assertEqual(result['logical_size'],12345678);self.assertIsNone(result['path'])
                    self.assertEqual(result['open_candidate'],path);self.assertTrue(result['cloud_openable'])
                    self.assertIsNone(available_audio({'current_path':str(path)}))
            self.assertEqual(sha256(path.read_bytes()).hexdigest(),before)

    def test_missing_cloud_path_does_not_become_deleted_and_local_fallback_wins(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);drop=root/'Dropbox';drop.mkdir();local=root/'Local.mp3';local.write_bytes(b'invented')
            source={'current_path':str(drop/'absent.mp3')}
            with patch.object(Path,'open',side_effect=AssertionError('Content opened')):
                result=inspect_audio_details(source,roots=[])
                self.assertEqual(result['status'],'unverified');self.assertEqual(result['cloud_state'],'not_local')
                self.assertFalse(result['cloud_openable']);self.assertIsNone(result['open_candidate'])
                result=inspect_audio_details({**source,'original_path':str(local)},roots=[])
                self.assertEqual(result['status'],'playable');self.assertEqual(result['path'],local.resolve())
                self.assertFalse(result['playback_cloud']);self.assertEqual(result['providers'],1)

    def test_legacy_cache_and_health_rows_migrate_without_trusting_old_positive_evidence(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);dbpath=root/'workbench-sidecar.sqlite3'
            with sqlite3.connect(dbpath) as db:
                db.execute('CREATE TABLE file_status_cache (key TEXT PRIMARY KEY,status TEXT,checked_at REAL)')
                db.execute('CREATE TABLE file_health_records (source TEXT,track_id TEXT,title TEXT,artist TEXT,genre TEXT,status TEXT,checked_at REAL,search_text TEXT,PRIMARY KEY(source,track_id))')
                db.execute("INSERT INTO file_health_records VALUES ('old','one','Old','','','playable',0,'old')")
            store=Store(dbpath);audio=root/'Dropbox'/'Missing.mp3';audio.parent.mkdir()
            track={'current_path':str(audio)};key=fingerprint(track,roots=[])
            with store.connection() as db:
                db.execute("INSERT INTO file_status_cache (key,status,checked_at) VALUES (?,'playable',?)",(key,__import__('time').time()))
                row=db.execute('SELECT providers,provider_checked,cloud_state FROM file_health_records').fetchone()
                self.assertEqual(tuple(row),(0,0,'not_checked'))
            owner=SimpleNamespace(DATA=root)
            states,hits,details=cached_inspect(owner,{'one':track},details=True,roots=[])
            self.assertEqual(states['one'],'unverified');self.assertFalse(hits['one'])
            with store.connection() as db:
                raw=db.execute('SELECT key,evidence FROM file_status_cache').fetchone()
                self.assertNotIn(str(root),str(tuple(raw)));self.assertNotIn(audio.name,raw['evidence'])
            self.assertTrue(cached_inspect(owner,{'one':track},details=True,roots=[])[1]['one'])
            self.assertNotEqual(fingerprint(track,roots=[]),fingerprint(track,roots=[{'kind':'dropbox','root':str(root),'provider_verified':True}]))


class CloudHealthAPITests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.drop=self.root/'Dropbox (Example team)';self.drop.mkdir()
        self.drive=self.root/'Custom mirrored volume';self.drive.mkdir()
        self.local=self.root/'Local.mp3';self.local.write_bytes(b'fixture')
        self.resident=self.drop/'Resident.mp3';self.resident.write_bytes(b'fixture')
        self.roots=[{'kind':'google_drive','root':str(self.drive),'provider_verified':True}]
        self.store=Store(self.root/'data'/'workbench-sidecar.sqlite3')
        records=[{'id':str(i),'title':f'Invented {i:03}','artist':'Test','current_path':str(self.drop/f'absent-{i}.mp3')} for i in range(61)]
        records += [{'id':'drive','title':'Drive','current_path':str(self.drive/'absent.mp3')},
                    {'id':'local','title':'Local','current_path':str(self.local)},
                    {'id':'resident','title':'Resident','current_path':str(self.resident)},
                    {'id':'both','title':'Both','current_path':str(self.drop/'missing.mp3'),'original_path':str(self.drive/'missing.mp3')}]
        self.sid=self.store.save_snapshot({'scope_key':'synthetic:cloud','tracks':records},'Synthetic cloud evidence')['id']
        self.source='snapshot:'+self.sid;self.before=deepcopy(self.store.snapshot(self.sid))
        for name,value in [('DATA',self.root/'data'),('sessions',{}),('tasks',{}),('active',None)]:
            p=patch.object(application,name,value);p.start();self.addCleanup(p.stop)
        for module in ('cloud_file_status','file_status_cache'):
            p=patch(module+'.provider_context',return_value=self.roots);p.start();self.addCleanup(p.stop)
        def execute(work,_message):self.result=work(lambda *_:None);return 'synthetic'
        p=patch.object(application,'launch',execute);p.start();self.addCleanup(p.stop)
        self.client=workspace_client(application);self.headers={'X-Workbench-Token':application.TOKEN}

    def scan(self,**args):return self.client.post('/api/file-health/scan',json={'source':self.source,**args},headers=self.headers)
    def query(self,**args):return self.client.get('/api/file-health',query_string={'source':self.source,**args})
    def play(self,identity='resident',**args):return self.client.post('/api/playback/open',json={'snapshot':self.sid,'track_id':identity,**args},headers=self.headers)

    def test_cloud_provider_filters_cover_complete_index_before_paging_and_never_open_audio(self):
        with patch.object(Path,'open',side_effect=AssertionError('Content opened')),patch('track_playback.open_audio') as launch:
            self.assertEqual(self.scan().status_code,200)
            self.assertFalse(self.result['audio_contents_read']);self.assertFalse(self.result['cloud_api_requests'])
            first=self.query(provider='dropbox').json;second=self.query(provider='dropbox',offset=50).json
            self.assertEqual(first['total'],63);self.assertEqual(len(first['rows']),50);self.assertEqual(len(second['rows']),13)
            self.assertFalse({r['track_id'] for r in first['rows']} & {r['track_id'] for r in second['rows']})
            self.assertEqual(first['provider_counts'],{'all':65,'dropbox':63,'google_drive':2,'other':1,'unknown':0})
            self.assertEqual(self.query(provider='google_drive',status='cloud_not_local').json['total'],2)
            self.assertEqual(self.query(provider='dropbox',status='playable',q='resident').json['total'],1)
            self.assertEqual(self.query(status='missing').json['total'],0)
            self.assertEqual(self.query().json['unavailable_count'],63)
            launch.assert_not_called()
        self.assertEqual(self.store.snapshot(self.sid),self.before)
        foreign=self.store.save_snapshot({'scope_key':'synthetic:other','tracks':[{'id':'local','current_path':str(self.local)}]},'Other')['id']
        self.assertEqual(self.client.get('/api/file-health',query_string={'source':'snapshot:'+foreign}).json['checked'],0)
        self.assertEqual(self.query(provider='invalid').status_code,400)

    def test_cloud_play_requires_fresh_bound_one_use_confirmation_each_time(self):
        with patch('track_playback.open_audio') as launch:
            challenge=self.play().json
            self.assertTrue(challenge['confirmation_required']);self.assertFalse(challenge['opened']);launch.assert_not_called()
            self.assertEqual(self.play(confirm_cloud_open=True,confirmation_token='invented').status_code,400)
            token=challenge['confirmation_token']
            confirmed=self.play(confirm_cloud_open=True,confirmation_token=token)
            self.assertEqual(confirmed.status_code,200,confirmed.json);launch.assert_called_once_with(self.resident.resolve())
            self.assertEqual(self.play(confirm_cloud_open=True,confirmation_token=token).status_code,400)
            self.assertTrue(self.play().json['confirmation_required']);self.assertEqual(launch.call_count,1)
            self.assertEqual(self.play(identity='0').status_code,400);self.assertEqual(launch.call_count,1)
            self.assertEqual(self.play(identity='local').status_code,200);self.assertEqual(launch.call_count,2)
        self.assertEqual(self.store.snapshot(self.sid),self.before)

    def test_confirmation_rejects_changed_file_mapping_track_source_and_expiry(self):
        with patch('track_playback.open_audio') as launch:
            token=self.play().json['confirmation_token'];self.resident.write_bytes(b'changed contents')
            self.assertEqual(self.play(confirm_cloud_open=True,confirmation_token=token).status_code,400)
            token=self.play().json['confirmation_token']
            self.assertEqual(self.play(identity='local',confirm_cloud_open=True,confirmation_token=token).status_code,400)
            token=self.play().json['confirmation_token']
            with patch('track_playback.time.monotonic',return_value=1e20):
                self.assertEqual(self.play(confirm_cloud_open=True,confirmation_token=token).status_code,400)
            token=self.play().json['confirmation_token']
            self.store.set_setting('audio_paths:synthetic:cloud',[{'recorded_root':'/nonexistent','local_root':str(self.root),'device':self.root.stat().st_dev,'inode':self.root.stat().st_ino}])
            self.assertEqual(self.play(confirm_cloud_open=True,confirmation_token=token).status_code,400)
            self.store.set_setting('audio_paths:synthetic:cloud',[])
            token=self.play().json['confirmation_token']
            other=self.store.save_snapshot({'scope_key':'synthetic:cloud','tracks':self.before['tracks']},'Other capture')['id']
            response=self.client.post('/api/playback/open',json={'snapshot':other,'track_id':'resident','confirm_cloud_open':True,'confirmation_token':token},headers=self.headers)
            self.assertEqual(response.status_code,400);launch.assert_not_called()
            for overrides in ({'REMOTE_ADDR':'192.0.2.1'},{'HTTP_HOST':'evil.example'}):
                response=self.client.post('/api/playback/open',json={'snapshot':self.sid,'track_id':'resident'},headers=self.headers,environ_overrides=overrides)
                self.assertEqual(response.status_code,400)
            launch.assert_not_called()

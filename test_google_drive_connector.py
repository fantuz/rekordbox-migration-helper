"""Real Google connector routes/store with invented provider metadata and bytes."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock,patch

import app as application
from google_drive_http import GoogleDriveError
import google_drive_files as files
from google_drive_connector import connection,register
from test_support import workspace_client
from workbench_store import Store

if 'google_drive_status' not in application.app.view_functions:register(application)


class SyntheticDownload:
    def __init__(self,data,metadata,interrupt=False):
        self.stream=BytesIO(data);self.metadata=deepcopy(metadata);self.length=len(data)
        self.interrupt=interrupt;self.closed=False
    def read(self,size=128*1024):
        if self.interrupt:raise GoogleDriveError('Synthetic transfer interrupted',tag='interrupted')
        return self.stream.read(size)
    def close(self):self.closed=True;self.stream.close()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()


class GoogleDriveConnectorTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();self.data=self.root/'work'
        self.local=self.root/'Selected download cache';self.album=self.local/'Album';self.album.mkdir(parents=True)
        self.payload=b'Invented Google Drive file bytes, not music.'
        self.state={'configured':True,'client_id':'invented.apps.googleusercontent.com','remember':False,
                    'connected':True,'connection_id':'invented-connection','secure_storage_available':False,
                    'persistent':False,'account':{'account_id':'invented-user','name':'Invented user',
                    'email':'invented@example.invalid'}}
        self.entries=[{'id':'music-root','name':'Music','mimeType':files.FOLDER_MIME,'parents':['drive-root'],'trashed':False},
                      {'id':'album-folder','name':'Album','mimeType':files.FOLDER_MIME,'parents':['music-root'],'trashed':False}]
        tracks=[]
        for index in range(61):
            name=f'Synthetic {index:03}.mp3'
            self.entries.append({'id':'file-'+str(index),'name':name,'mimeType':'audio/mpeg','parents':['album-folder'],
                                 'size':str(len(self.payload)),'version':'1','sha256Checksum':sha256(self.payload).hexdigest(),
                                 'modifiedTime':'2026-01-01T10:00:00Z','trashed':False,'capabilities':{'canDownload':True}})
            tracks.append({'id':str(index),'title':f'Invented {index:03}','artist':'Invented artist','current_path':str(self.album/name)})
        tracks.extend([{'id':'missing','title':'Absent mapped file','current_path':str(self.album/'Absent.mp3')},
                       {'id':'outside','title':'Outside mapped root','current_path':str(self.root/'Elsewhere.mp3')}])
        self.store=Store(self.data/'workbench-sidecar.sqlite3')
        self.sid=self.store.save_snapshot({'scope_key':'invented:google','tracks':tracks,'playlists':[]},'Invented Drive collection')['id']
        self.source='snapshot:'+self.sid;self.before=deepcopy(self.store.snapshot(self.sid))
        for name,value in [('DATA',self.data),('sessions',{}),('active',None),('tasks',{})]:
            stub=patch.object(application,name,value,create=True);stub.start();self.addCleanup(stub.stop)
        for name,value in [('cloud_attachments.allowed_roots',[self.root]),('cloud_attachments.provider_roots',[]),
                           ('google_drive_files.provider_roots',[])]:
            stub=patch(name,return_value=value);stub.start();self.addCleanup(stub.stop)
        self.connection=connection(application)
        self.downloads=[];self.interrupt=False;self.corrupt=False;self.fail_listing=False;self.incomplete=False
        for name,replacement in [('status',Mock(side_effect=lambda:deepcopy(self.state))),
                                 ('rpc',Mock(side_effect=self.rpc)),('download',Mock(side_effect=self.download)),
                                 ('begin',Mock(return_value={'authorize_url':'https://accounts.google.com/o/oauth2/v2/auth?state=invented-state'})),
                                 ('callback',Mock())]:
            stub=patch.object(self.connection,name,replacement);stub.start();self.addCleanup(stub.stop)
        def execute(work,_message,**kwargs):
            state='error'
            try:self.result=work(lambda *_:None);state='complete';return 'invented-google-job'
            finally:
                if kwargs.get('on_finished'):kwargs['on_finished'](state)
        stub=patch.object(application,'launch',execute);stub.start();self.addCleanup(stub.stop)
        self.client=workspace_client(application);self.headers={'X-Workbench-Token':application.TOKEN}

    def rpc(self,route,payload):
        if route=='files/get':
            identity=payload['fileId']
            if identity=='root':return {'id':'drive-root','name':'My Drive','mimeType':files.FOLDER_MIME,'parents':[],'trashed':False}
            row=next((row for row in self.entries if row['id']==identity),None)
            if row:return deepcopy(row)
            raise GoogleDriveError('Synthetic file not found',status=404,tag='not_found')
        if route!='files/list':raise AssertionError(route)
        if self.fail_listing:raise GoogleDriveError('Synthetic metadata request failed',tag='network')
        parents=re.findall(r"'([A-Za-z0-9_-]+)' in parents",payload['q'])
        rows=[row for row in self.entries if any(parent in row['parents'] for parent in parents)]
        match=re.search(r"and name = '((?:\\.|[^'])*)'",payload['q'])
        if match:
            name=match.group(1).replace("\\'", "'").replace('\\\\','\\')
            rows=[row for row in rows if row['name']==name]
        if "and mimeType = '" in payload['q']:rows=[row for row in rows if row['mimeType']==files.FOLDER_MIME]
        return {'files':deepcopy(rows),'incompleteSearch':self.incomplete}

    def download(self,identity,version=None,**_kwargs):
        remote=next(deepcopy(row) for row in self.entries if row['id']==identity)
        data=self.payload if not self.corrupt else bytes([self.payload[0]^1])+self.payload[1:]
        response=SyntheticDownload(data,remote,self.interrupt);self.downloads.append(response);return response

    def attach(self):
        mapped=files.mapping_record(self.connection,str(self.local),'music-root',owner=application)
        self.store.set_setting('google_drive_mapping',mapped)
        return mapped
    def post(self,action,**value):return self.client.post('/api/google-drive/'+action,json=value,headers=self.headers)
    def check(self,source=None):return self.post('check',source=source or self.source)
    def rows(self,**query):
        return self.client.get('/api/google-drive/files',query_string={'source':self.source,**query})
    def prepare(self,identity='0'):
        result=self.post('download/prepare',source=self.source,track_id=identity)
        self.assertEqual(result.status_code,200,result.json)
        return result.json['confirmation_token']
    def confirm(self,token,identity='0',**extra):
        return self.post('download',source=self.source,track_id=identity,confirmation_token=token,confirm=True,**extra)

    def test_status_is_local_metadata_only_and_manual_mapping_cannot_bypass_gate(self):
        self.assertEqual(self.client.get('/api/google-drive/status').status_code,200)
        self.connection.rpc.assert_not_called();self.connection.download.assert_not_called()
        result=self.post('mapping',local_root=str(self.local),remote_folder_id='music-root')
        self.assertEqual(result.status_code,400);self.assertIsNone(self.store.setting('google_drive_mapping'))

    def test_full_source_metadata_check_filters_before_pagination_without_opening_audio(self):
        self.attach();self.connection.rpc.reset_mock()
        with patch.object(Path,'open',side_effect=AssertionError('Audio opened during metadata check')):
            result=self.check()
        self.assertEqual(result.status_code,200,result.json)
        first=self.rows().json;second=self.rows(offset=50).json
        self.assertEqual(first['total'],63);self.assertEqual(len(first['rows']),50);self.assertEqual(len(second['rows']),13)
        self.assertEqual(first['counts'],{'present':61,'not_found':1,'unmapped':1,'ambiguous':0,'unverified':0})
        self.assertEqual(self.rows(q='Invented 060').json['total'],1)
        self.assertEqual(self.rows(status='not_found').json['rows'][0]['track_id'],'missing')
        self.assertEqual(self.store.snapshot(self.sid),self.before)
        self.connection.download.assert_not_called();self.assertEqual(list(self.album.iterdir()),[])

    def test_duplicate_remote_names_and_incomplete_listings_never_become_false_missing(self):
        self.attach();duplicate=deepcopy(self.entries[2]);duplicate['id']='duplicate-file';self.entries.append(duplicate)
        self.assertEqual(self.check().status_code,200)
        self.assertEqual(self.rows(status='ambiguous').json['rows'][0]['track_id'],'0')
        self.assertEqual(self.rows(status='ambiguous').json['rows'][0]['downloadable'],False)
        self.incomplete=True;self.assertEqual(self.check().status_code,200)
        self.assertEqual(self.rows(status='not_found').json['total'],0)
        self.assertEqual(self.rows(status='unverified').json['total'],62)

    def test_failed_recheck_preserves_last_evidence_timestamp(self):
        self.attach();self.check();before=self.rows().json
        self.fail_listing=True;self.assertEqual(self.check().status_code,400)
        after=self.rows().json
        self.assertEqual(after['checked_at'],before['checked_at']);self.assertEqual(after['counts'],before['counts'])

    def test_one_confirmed_download_is_atomic_single_use_and_preserves_snapshot(self):
        self.attach();self.check();token=self.prepare()
        self.connection.download.assert_not_called()
        response=self.confirm(token);self.assertEqual(response.status_code,200,response.json)
        self.assertEqual((self.album/'Synthetic 000.mp3').read_bytes(),self.payload)
        self.assertEqual(len(self.downloads),1);self.assertTrue(self.downloads[0].closed)
        self.assertEqual(self.confirm(token).status_code,400);self.assertEqual(len(self.downloads),1)
        self.assertEqual(self.store.snapshot(self.sid),self.before)

    def test_existing_file_changed_revision_and_duplicate_names_require_new_consent(self):
        self.attach();token=self.prepare();target=self.album/'Synthetic 000.mp3';target.write_bytes(b'Keep existing bytes')
        self.assertEqual(self.confirm(token).status_code,400);self.assertEqual(target.read_bytes(),b'Keep existing bytes')
        token=self.prepare('1');self.entries[3]['version']='2'
        self.assertEqual(self.confirm(token,'1').status_code,400)
        token=self.prepare('2');duplicate=deepcopy(self.entries[4]);duplicate['id']='another-file';self.entries.append(duplicate)
        self.assertEqual(self.confirm(token,'2').status_code,400);self.connection.download.assert_not_called()

    def test_failed_or_corrupt_transfer_never_publishes_final_or_partial_file(self):
        self.attach();self.interrupt=True
        self.assertEqual(self.confirm(self.prepare()).status_code,400)
        self.assertEqual(list(self.album.iterdir()),[])
        self.interrupt=False;self.corrupt=True
        self.assertEqual(self.confirm(self.prepare()).status_code,400)
        self.assertEqual(list(self.album.iterdir()),[]);self.assertTrue(all(stream.closed for stream in self.downloads))

    def test_literal_consent_expiry_source_track_and_connection_are_bound(self):
        self.attach();token=self.prepare()
        denied=self.post('download',source=self.source,track_id='0',confirmation_token=token,confirm='true')
        self.assertEqual(denied.status_code,400)
        with patch('google_drive_connector.time.monotonic',return_value=time.monotonic()+121):
            self.assertEqual(self.confirm(token).status_code,400)
        token=self.prepare();self.assertEqual(self.confirm(token,'1').status_code,400)
        token=self.prepare();self.state['connection_id']='different-authorization'
        self.assertEqual(self.confirm(token).status_code,400);self.connection.download.assert_not_called()

    def test_source_and_audio_mapping_changes_hide_old_cached_evidence(self):
        self.attach();self.check();self.assertEqual(self.rows().json['total'],63)
        self.store.set_setting('audio_paths:invented:google',[{'recorded_root':'D:/Old','local_root':str(self.local),'device':1,'inode':2}])
        self.assertEqual(self.rows().json['total'],0)
        self.store.set_setting('audio_paths:invented:google',[])
        mapped=self.store.setting('google_drive_mapping');mapped['source']='snapshot:'+'f'*32
        self.store.set_setting('google_drive_mapping',mapped)
        self.assertEqual(self.rows().status_code,400)

    def test_new_foreign_provider_root_holds_prepare_and_consumed_consent_before_api(self):
        self.attach();token=self.prepare();self.connection.rpc.reset_mock()
        foreign=[{'kind':'dropbox','root':str(self.album),'provider_verified':True,'evidence':'dropbox_config'}]
        with patch('cloud_attachments.provider_roots',return_value=foreign):
            self.assertEqual(self.post('download/prepare',source=self.source,track_id='1').status_code,400)
            self.assertEqual(self.confirm(token).status_code,400)
        self.connection.rpc.assert_not_called();self.connection.download.assert_not_called()

    def test_browser_folder_choices_are_explicit_and_preserve_duplicate_ids(self):
        self.entries.append({'id':'other-album','name':'Album','mimeType':files.FOLDER_MIME,'parents':['music-root'],'trashed':False})
        response=self.client.get('/api/google-drive/folders',query_string={'parent':'music-root'},headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual({row['id'] for row in response.json['rows']},{'album-folder','other-album'})
        self.connection.download.assert_not_called()

    def test_callback_uses_whitelisted_gate_return_and_drops_code_from_url(self):
        response=self.post('connect',return_to='cloud-connect')
        self.assertEqual(response.status_code,200,response.json)
        callback=self.client.get('/api/google-drive/callback?state=invented-state&code=PRIVATE-CODE')
        self.assertEqual(callback.status_code,303);self.assertEqual(callback.headers['Location'],'/#cloud-connect')
        self.assertEqual(callback.headers['Cache-Control'],'no-store')
        self.assertEqual(callback.headers['Referrer-Policy'],'no-referrer')
        self.assertNotIn('PRIVATE-CODE',callback.headers['Location'])
        self.assertEqual(self.post('connect',return_to='https://evil.invalid').status_code,400)

    def test_foreign_host_peer_origin_and_missing_token_are_rejected(self):
        for overrides in ({'REMOTE_ADDR':'203.0.113.9'},{'HTTP_HOST':'evil.invalid'}):
            response=self.client.get('/api/google-drive/status',environ_overrides=overrides)
            self.assertEqual(response.status_code,400)
        self.assertEqual(self.client.post('/api/google-drive/check',json={'source':self.source}).status_code,403)
        response=self.client.post('/api/google-drive/check',json={'source':self.source},headers={**self.headers,'Origin':'https://evil.invalid'})
        self.assertEqual(response.status_code,400)
        self.connection.rpc.assert_not_called()


if __name__=='__main__':unittest.main()

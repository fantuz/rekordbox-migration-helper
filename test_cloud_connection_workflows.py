"""Both cloud providers over real routes/store/jobs with invented provider data."""
from contextlib import ExitStack
from copy import deepcopy
from hashlib import md5,sha256
from io import BytesIO
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch


class SyntheticDropbox:
    def __init__(self):
        self.body=b'Invented Dropbox transfer fixture, not real music.'
        self.calls=[];self.downloads=[]
        self.state={'configured':True,'app_key':'syntheticpublickey','remember':False,'connected':True,
                    'connection_id':'invented-dropbox-connection','secure_storage_available':False,
                    'persistent':False,'credential_cleanup_pending':False,
                    'scopes':['account_info.read','files.metadata.read','files.content.read'],
                    'account':{'account_id':'dbid:invented-cloud-workflow','name':'Invented Dropbox account',
                        'display_name':'Invented Dropbox account','email':'dropbox@example.invalid',
                        'root_namespace_id':'101','home_namespace_id':'102'}}
        digest=sha256(sha256(self.body).digest()).hexdigest()
        self.entries=[{'.tag':'file','id':'id:dropbox-'+str(i),'name':f'Dropbox {i:03}.mp3',
                       'path_display':f'/Music/Album/Dropbox {i:03}.mp3',
                       'path_lower':f'/music/album/dropbox {i:03}.mp3','rev':'rev-'+str(i),
                       'size':len(self.body),'content_hash':digest,
                       'client_modified':'2026-01-01T10:00:00Z'} for i in range(2)]

    def status(self):return deepcopy(self.state)

    def rpc(self,route,payload,**_kwargs):
        from dropbox_http import DropboxError
        self.calls.append((route,deepcopy(payload)))
        if route=='files/list_folder':return {'entries':deepcopy(self.entries),'has_more':False,'cursor':'invented'}
        if route=='files/get_metadata':
            path=payload.get('path','')
            if path.lower()=='/music':return {'.tag':'folder','id':'id:music','name':'Music'}
            for row in self.entries:
                if path in (row['id'],row['path_display'],row['path_lower']):return deepcopy(row)
            raise DropboxError('Invented path not found',status=409,tag='not_found')
        raise AssertionError('Unexpected Dropbox operation: '+route)

    def download(self,identity,rev=None,**_kwargs):
        row=next(row for row in self.entries if row['id']==identity)
        assert row['rev']==rev
        self.downloads.append(identity)
        response=BytesIO(self.body);response.metadata=deepcopy(row);response.length=len(self.body)
        return response


class SyntheticGoogleDrive:
    def __init__(self):
        self.body=b'Invented Google Drive transfer fixture, not real music.'
        self.calls=[];self.downloads=[];self.ambiguous=False;self.corrupt=False
        self.state={'configured':True,'client_id':'123456789012-invented.apps.googleusercontent.com',
                    'remember':False,'connected':True,'connection_id':'invented-google-connection',
                    'secure_storage_available':False,'persistent':False,'credential_cleanup_pending':False,
                    'scopes':['https://www.googleapis.com/auth/drive.readonly'],
                    'account':{'account_id':'invented-google-permission','name':'Invented Google account',
                        'display_name':'Invented Google account','email':'google@example.invalid'}}
        folder=lambda identity,name,parents:{'id':identity,'name':name,'parents':parents,
            'mimeType':'application/vnd.google-apps.folder','trashed':False,
            'capabilities':{'canListChildren':True,'canDownload':True},'ownedByMe':True}
        self.entries=[folder('drive-root','My Drive',[]),folder('drive-music','Music',['drive-root']),
                      folder('drive-album','Album',['drive-music']),folder('drive-empty','Empty',['drive-root'])]
        self.entries.extend({'id':'drive-'+str(i),'name':f'Drive {i:03}.mp3','parents':['drive-album'],
            'mimeType':'audio/mpeg','size':str(len(self.body)),'version':'1','headRevisionId':'revision-'+str(i),
            'md5Checksum':md5(self.body).hexdigest(),'sha256Checksum':sha256(self.body).hexdigest(),
            'trashed':False,'modifiedTime':'2026-01-01T10:00:00Z','ownedByMe':True,
            'capabilities':{'canDownload':True}} for i in range(61))

    def status(self):return deepcopy(self.state)

    def rpc(self,route,payload=None,**_kwargs):
        from google_drive_http import GoogleDriveError
        payload=payload or {};self.calls.append((route,deepcopy(payload)))
        if route=='about/get':return {'user':{'permissionId':'invented-google-permission',
            'displayName':'Invented Google account','emailAddress':'google@example.invalid'}}
        rows=deepcopy(self.entries)
        if self.ambiguous:
            row=deepcopy(next(row for row in rows if row['id']=='drive-0'));row['id']='drive-duplicate';rows.append(row)
        if route=='files/get':
            identity=payload.get('fileId',payload.get('id'))
            if identity=='root':identity='drive-root'
            for row in rows:
                if row['id']==identity:return row
            raise GoogleDriveError('Invented file not found',status=404,tag='not_found')
        if route=='files/list':
            query=payload.get('q','');parents=re.findall(r"'([^']+)'\s+in\s+parents",query)
            if parents:rows=[row for row in rows if any(parent in parents for parent in row.get('parents',[]))]
            if re.search(r"mimeType\s*=\s*'application/vnd.google-apps.folder'",query):
                rows=[row for row in rows if row['mimeType']=='application/vnd.google-apps.folder']
            offset=int(str(payload.get('pageToken') or '0').removeprefix('offset-'))
            limit=min(40,int(payload.get('pageSize') or 1000));end=offset+limit
            result={'files':rows[offset:end],'incompleteSearch':False}
            if end<len(rows):result['nextPageToken']='offset-'+str(end)
            return result
        raise AssertionError('Unexpected Google operation: '+route)

    def download(self,identity,version=None,**_kwargs):
        row=next(row for row in self.entries if row['id']==identity)
        if version is not None:assert str(row['version'])==str(version)
        self.downloads.append(identity)
        body=(bytes([self.body[0]^1])+self.body[1:]) if self.corrupt else self.body
        response=BytesIO(body);response.metadata=deepcopy(row);response.length=len(body)
        return response


class CloudConnectionWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory(prefix='cloud-workflow-');self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.data=self.root/'Workbench data'
        self.dropbox=self.root/'Cloud Option DJ team Dropbox';self.dropbox.mkdir()
        self.google_hint=self.root/'Google Drive';self.google_hint.mkdir()
        self.dropbox_cache=self.root/'Selected Dropbox cache';(self.dropbox_cache/'Album').mkdir(parents=True)
        self.google_cache=self.root/'Selected Google cache';(self.google_cache/'Album').mkdir(parents=True)
        appdata=self.root/'Provider settings';(appdata/'Dropbox').mkdir(parents=True)
        (appdata/'Dropbox'/'info.json').write_text(json.dumps({'business':{'path':str(self.dropbox)}}))
        self.patches=ExitStack();self.addCleanup(self.patches.close)
        self.patches.enter_context(patch.dict('os.environ',{'APPDATA':str(appdata),
            'LIBRARY_WORKBENCH_DATA_DIR':str(self.data),'LIBRARY_WORKBENCH_NO_BROWSER':'1',
            'LIBRARY_WORKBENCH_DISABLE_MUSICBRAINZ':'1'}))
        self.patches.enter_context(patch.object(Path,'home',return_value=self.root))
        import app as application
        from workbench_store import Store
        from test_support import workspace_client
        import dropbox_connector,google_drive_connector
        self.application=application
        for name,value in [('DATA',self.data),('sessions',{}),('active',None),('tasks',{}),('task_controls',{})]:
            self.patches.enter_context(patch.object(application,name,value))
        self.providers={'dropbox':SyntheticDropbox(),'google_drive':SyntheticGoogleDrive()}
        self.connections={'dropbox':dropbox_connector.connection(application),
                          'google_drive':google_drive_connector.connection(application)}
        self.connections['dropbox'].configure('syntheticpublickey',False)
        self.connections['google_drive'].configure('123456789012-invented.apps.googleusercontent.com',remember=False)
        for provider,connection in self.connections.items():
            for method in ('status','rpc','download'):
                self.patches.enter_context(patch.object(connection,method,getattr(self.providers[provider],method)))
        self.store=Store(self.data/'workbench-sidecar.sqlite3')
        tracks=[{'id':'db-'+str(i),'title':f'Invented Dropbox {i:03}','artist':'Invented artist',
                 'current_path':f'D:/Old Dropbox/Album/Dropbox {i:03}.mp3'} for i in range(2)]
        tracks.extend({'id':'gd-'+str(i),'title':f'Invented Google {i:03} <mix>','artist':'Invented artist',
                       'current_path':f'E:/Old Drive/Album/Drive {i:03}.mp3'} for i in range(61))
        tracks.append({'id':'outside','title':'Unmapped recording','current_path':'Z:/Elsewhere/Other.mp3'})
        self.sid=self.store.save_snapshot({'scope_key':'synthetic:cloud-connections','tracks':tracks,
                                          'playlists':[]},'Invented two-provider collection')['id']
        self.source='snapshot:'+self.sid;self.before=deepcopy(self.store.snapshot(self.sid))
        self.client=workspace_client(application);self.headers={'X-Workbench-Token':application.TOKEN}

    def post(self,path,value):return self.client.post('/api/'+path,json=value,headers=self.headers)

    def poll(self,response):
        self.assertEqual(response.status_code,200,response.json)
        value=response.json
        if 'job' not in value:return value
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            job=self.client.get('/api/tasks/'+value['job']).json
            if job['status']=='complete':return job['result']
            if job['status'] in ('error','cancelled'):self.fail(job.get('message'))
            time.sleep(0.01)
        self.fail('Cloud fixture job did not finish')

    def values(self,provider,**changes):
        value={'provider':provider,'source':self.source,'sync_mode':'selected','desktop_mode':'not_installed',
               'arrangement':'cloud_option' if provider=='dropbox' else 'own_google','default_upload':'dropbox',
               'local_root':str(self.dropbox_cache if provider=='dropbox' else self.google_cache),
               'recorded_root':'D:/Old Dropbox' if provider=='dropbox' else 'E:/Old Drive'}
        if provider=='dropbox':value.update(remote_root='/Music',namespace='101')
        else:value['remote_folder_id']='drive-music'
        return {**value,**changes}

    def attach(self,provider):
        preview=self.poll(self.post('cloud-setup/preview',self.values(provider)))
        self.assertTrue(preview['attachable'],preview)
        self.assertEqual(preview['matched'],2 if provider=='dropbox' else 61)
        result=self.post('cloud-setup/attach',{'preview_token':preview['preview_token'],'confirm':True})
        self.assertEqual(result.status_code,200,result.json)
        return preview,result.json

    def test_both_selected_cache_attachments_preserve_sources_and_detach_independently(self):
        status=self.client.get('/api/cloud-setup/status',query_string={'source':self.source})
        self.assertEqual(status.status_code,200,status.json)
        self.assertTrue(any(row['root']==str(self.dropbox) for row in status.json['roots']))
        self.assertTrue(any(row['root']==str(self.google_hint) for row in status.json['roots']))
        self.assertTrue(all(not provider.downloads and not provider.calls for provider in self.providers.values()))
        for provider in self.providers:
            preview,_=self.attach(provider)
            replay=self.post('cloud-setup/attach',{'preview_token':preview['preview_token'],'confirm':True})
            self.assertEqual(replay.status_code,400,replay.json)
        both=self.client.get('/api/cloud-setup/status',query_string={'source':self.source}).json
        self.assertTrue(all(both['attachments'][name] for name in self.providers))
        result=self.post('cloud-setup/detach',{'provider':'dropbox'})
        self.assertEqual(result.status_code,200,result.json)
        remaining=self.client.get('/api/cloud-setup/status',query_string={'source':self.source}).json
        self.assertFalse(remaining['attachments']['dropbox']);self.assertTrue(remaining['attachments']['google_drive'])
        self.assertEqual(self.store.snapshot(self.sid),self.before)
        self.assertTrue(all(not provider.downloads for provider in self.providers.values()))
        self.assertEqual(list((self.dropbox_cache/'Album').iterdir()),[])
        self.assertEqual(list((self.google_cache/'Album').iterdir()),[])

    def test_google_all_files_and_ambiguous_remote_folders_never_attach(self):
        refused=self.post('cloud-setup/preview',self.values('google_drive',sync_mode='all'))
        self.assertEqual(refused.status_code,400,refused.json)
        self.assertEqual(self.providers['google_drive'].calls,[])
        empty=self.poll(self.post('cloud-setup/preview',self.values('google_drive',remote_folder_id='drive-empty')))
        self.assertFalse(empty['attachable']);self.assertFalse(empty.get('preview_token'));self.assertEqual(empty['matched'],0)
        self.providers['google_drive'].ambiguous=True
        ambiguous=self.poll(self.post('cloud-setup/preview',self.values('google_drive')))
        self.assertFalse(ambiguous['attachable']);self.assertFalse(ambiguous.get('preview_token'))
        self.assertGreater(ambiguous['ambiguous'],0)
        status=self.client.get('/api/cloud-setup/status',query_string={'source':self.source}).json
        self.assertFalse(status['attachments']['google_drive'])
        self.assertFalse(self.providers['google_drive'].downloads)

    def test_google_account_change_after_preview_cannot_replace_dropbox_attachment(self):
        self.attach('dropbox')
        preview=self.poll(self.post('cloud-setup/preview',self.values('google_drive')))
        self.assertTrue(preview['attachable'],preview)
        google=self.providers['google_drive']
        google.state['connection_id']='different-google-authorization'
        google.state['account']['account_id']='different-google-permission'
        denied=self.post('cloud-setup/attach',{'preview_token':preview['preview_token'],'confirm':True})
        self.assertEqual(denied.status_code,400,denied.json)
        status=self.client.get('/api/cloud-setup/status',query_string={'source':self.source}).json
        self.assertTrue(status['attachments']['dropbox']);self.assertFalse(status['attachments']['google_drive'])
        self.assertEqual(self.store.snapshot(self.sid),self.before)
        self.assertTrue(all(not provider.downloads for provider in self.providers.values()))


if __name__=='__main__':unittest.main()

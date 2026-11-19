"""Real connector routes/store with an invented Dropbox account and files."""
from copy import deepcopy
from contextlib import ExitStack
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import app as application
from dropbox_http import DropboxError
from test_support import workspace_client
from workbench_store import Store


def content_hash(data):
    # Dropbox's public content-hash format: SHA256 of the 4 MiB block digests.
    return sha256(b''.join(sha256(data[start:start+4*1024*1024]).digest()
                           for start in range(0,len(data),4*1024*1024))).hexdigest()


class SyntheticDownload:
    def __init__(self,data,metadata,interrupt=False):
        self.stream=BytesIO(data);self.metadata=deepcopy(metadata);self.length=len(data)
        self.interrupt=interrupt;self.closed=False
    def read(self,size=128*1024):
        if self.interrupt:raise DropboxError('Synthetic interruption',tag='interrupted')
        return self.stream.read(size)
    def iter_chunks(self,size=128*1024):
        while chunk:=self.read(size):yield chunk
    def close(self):self.closed=True;self.stream.close()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()


class DropboxConnectorTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.data=self.root/'work'
        self.dropbox=self.root/'Dropbox (Invented team)';self.dropbox.mkdir()
        self.library=self.dropbox/'Invented customer';self.library.mkdir()
        self.album=self.library/'Album';self.album.mkdir()
        self.payload=b'Invented file bytes for download verification; not real music.'
        self.status_data={
            'configured':True,'app_key':'synthetic-public-key','remember':False,'connected':True,
            'state':'session','connection_id':'connection-one','vault_available':False,'vault_backend':'',
            'credential_cleanup_pending':False,'scopes':['account_info.read','files.metadata.read','files.content.read'],
            'account':{'account_id':'dbid:invented','display_name':'Invented account','email':'synthetic@example.invalid',
                       'root_namespace_id':'101','home_namespace_id':'102'}}
        self.entries=[];tracks=[]
        for number in range(61):
            name=f'Synthetic {number:03}.mp3';remote='/Music/Album/'+name
            self.entries.append({'.tag':'file','id':'id:invented-'+str(number),'name':name,
                'path_display':remote,'path_lower':remote.lower(),'rev':'rev-'+str(number),
                'size':len(self.payload),'content_hash':content_hash(self.payload),
                'server_modified':'2026-01-01T10:00:00Z','client_modified':'2026-01-01T10:00:00Z'})
            tracks.append({'id':str(number),'title':f'Invented {number:03}','artist':'Synthetic artist',
                           'current_path':str(self.album/name)})
        tracks.extend([
            {'id':'missing','title':'Absent mapped path','current_path':str(self.album/'Absent.mp3')},
            {'id':'outside','title':'Outside selected root','current_path':str(self.root/'Other'/'Elsewhere.mp3')},
            {'id':'boundary','title':'Similar prefix is not a root','current_path':str(self.dropbox/'Invented customer extra'/'Other.mp3')}])
        self.store=Store(self.data/'workbench-sidecar.sqlite3')
        self.sid=self.store.save_snapshot({'scope_key':'synthetic:dropbox-connector','tracks':tracks,
                                          'playlists':[]},'Invented Dropbox collection')['id']
        self.source='snapshot:'+self.sid;self.before=deepcopy(self.store.snapshot(self.sid))
        for name,value in [('DATA',self.data),('sessions',{}),('active',None),('tasks',{})]:
            stub=patch.object(application,name,value,create=True);stub.start();self.addCleanup(stub.stop)
        from dropbox_connector import connection
        self.connection=connection(application)
        for name,replacement in [('status',Mock(side_effect=lambda:deepcopy(self.status_data))),
                                 ('rpc',Mock(side_effect=self.rpc)),('download',Mock(side_effect=self.download)),
                                 ('callback',Mock())]:
            stub=patch.object(self.connection,name,replacement);stub.start();self.addCleanup(stub.stop)
        def execute(work,_message,**kwargs):
            state='error'
            try:self.result=work(lambda *_:None);state='complete';return 'synthetic-dropbox-job'
            finally:
                if kwargs.get('on_finished'):kwargs['on_finished'](state)
        stub=patch.object(application,'launch',execute);stub.start();self.addCleanup(stub.stop)
        self.client=workspace_client(application);self.headers={'X-Workbench-Token':application.TOKEN}
        self.downloads=[];self.interrupt=False;self.corrupt=False;self.partial_listing=False

    def rpc(self,route,payload,path_root=None,**_kwargs):
        route=route.strip('/').removeprefix('2/')
        if route=='files/get_metadata':
            value=payload.get('path','')
            if value.rstrip('/').lower()=='/music':
                return {'.tag':'folder','id':'id:folder','name':'Music','path_lower':'/music','path_display':'/Music'}
            for entry in self.entries:
                if value==entry['id'] or value.lower()==entry['path_lower']:return deepcopy(entry)
            raise DropboxError('Synthetic path not found',status=409,tag='not_found')
        if route=='files/list_folder':
            return {'entries':deepcopy(self.entries[:1] if self.partial_listing else self.entries),
                    'has_more':self.partial_listing,'cursor':'synthetic-cursor'}
        if route=='files/list_folder/continue':
            raise DropboxError('Synthetic metadata interruption',tag='network')
        raise AssertionError('Unexpected Dropbox operation: '+route)

    def download(self,path_or_id,rev=None,namespace=None,**_kwargs):
        metadata=next(deepcopy(entry) for entry in self.entries if path_or_id in (entry['id'],entry['path_display'],entry['path_lower']))
        body=bytes([self.payload[0]^1])+self.payload[1:] if self.corrupt else self.payload
        response=SyntheticDownload(body,metadata,interrupt=self.interrupt);self.downloads.append(response);return response

    def post(self,path,**body):
        return self.client.post('/api/dropbox/'+path,json=body,headers=self.headers)

    def files(self,**values):
        return self.client.get('/api/dropbox/files',query_string={'source':self.source,**values})

    def map_folder(self):
        roots=[{'root':str(self.dropbox),'kind':'dropbox','provider_verified':True,'availability':'local'}]
        with patch('dropbox_files.detected_roots',return_value=roots):
            result=self.post('mapping',local_root=str(self.library),remote_root='/Music')
        self.assertEqual(result.status_code,200,result.json)
        return result

    def check(self,source=None):
        result=self.post('check',source=source or self.source);self.assertEqual(result.status_code,200,result.json);return result

    def prepare(self,identity='0',play_after_download=False):
        result=self.post('download/prepare',source=self.source,track_id=identity,play_after_download=play_after_download)
        self.assertEqual(result.status_code,200,result.json)
        self.assertTrue(result.json['confirmation_required'])
        self.assertEqual(result.json['play_after_download'],play_after_download)
        return result.json['confirmation_token']

    def confirm(self,token,identity='0'):
        return self.post('download',source=self.source,track_id=identity,confirmation_token=token,confirm=True)

    def test_check_is_metadata_only_and_filters_the_complete_source_before_pagination(self):
        self.map_folder();self.connection.rpc.reset_mock()
        # Rendering/querying an unchecked source must not contact Dropbox.
        self.assertEqual(self.files().status_code,200)
        self.connection.rpc.assert_not_called();self.connection.download.assert_not_called()
        with patch.object(Path,'open',side_effect=AssertionError('Audio opened during metadata check')):
            self.check()
        first=self.files(status='present').json;second=self.files(status='present',offset=50).json
        self.assertEqual(first['total'],61);self.assertEqual(len(first['rows']),50);self.assertEqual(len(second['rows']),11)
        self.assertFalse({row['track_id'] for row in first['rows']} & {row['track_id'] for row in second['rows']})
        self.assertEqual(self.files(status='not_found').json['rows'][0]['track_id'],'missing')
        self.assertEqual(self.files(status='unmapped').json['total'],2)
        self.assertEqual(self.files(q='Invented 060').json['total'],1)
        self.connection.download.assert_not_called();self.assertEqual(list(self.album.iterdir()),[])
        self.assertEqual(self.store.snapshot(self.sid),self.before)

    def test_partial_remote_listing_does_not_label_unseen_files_as_missing(self):
        self.map_folder();self.partial_listing=True
        with patch('dropbox_files.MAX_PAGES',1):self.check()
        self.assertEqual(self.files(status='present').json['total'],1)
        self.assertEqual(self.files(status='not_found').json['total'],0)
        self.assertGreaterEqual(self.files(status='unverified').json['total'],61)
        self.connection.download.assert_not_called()

    def test_metadata_check_compares_captured_size_without_asserting_file_identity(self):
        tracks=deepcopy(self.before['tracks'])
        tracks[0]['size']=len(self.payload)
        tracks[1]['size']=len(self.payload)+1
        tracks[2]['size_bytes']=len(self.payload)
        for index,value in enumerate((0,None,True,-1,1.5),start=3):tracks[index]['size']=value
        snapshot=self.store.save_snapshot({'scope_key':'synthetic:cloud-size','tracks':tracks,'playlists':[]},'Size evidence')['id']
        source='snapshot:'+snapshot;self.map_folder()
        with patch.object(Path,'open',side_effect=AssertionError('Audio opened during metadata check')):
            self.check(source)
            rows={row['track_id']:row for row in self.files(source=source).json['rows']}
        self.assertEqual(rows['0']['size_comparison'],'match')
        self.assertEqual(rows['1']['size_comparison'],'mismatch')
        self.assertEqual(rows['2']['size_comparison'],'match')
        self.assertEqual(rows['0']['expected_size'],len(self.payload))
        self.assertEqual(rows['0']['remote_size'],len(self.payload))
        self.assertTrue(all(rows[str(i)]['size_comparison']=='unknown' for i in range(3,8)))
        self.assertTrue(all(rows[str(i)]['status']=='present' for i in range(8)))
        self.connection.download.assert_not_called()
        self.assertEqual(self.store.snapshot(snapshot)['tracks'],tracks)

    def test_prepared_download_reports_size_disagreement_and_uses_verified_local_destination(self):
        tracks=deepcopy(self.before['tracks']);tracks[0]['size']=len(self.payload)+1
        snapshot=self.store.save_snapshot({'scope_key':'synthetic:size-download','tracks':tracks,'playlists':[]},'Size warning')['id']
        self.map_folder()
        result=self.post('download/prepare',source='snapshot:'+snapshot,track_id='0')
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(Path(result.json['local_path']),self.album/'Synthetic 000.mp3')
        self.assertEqual(result.json['expected_size'],len(self.payload)+1)
        self.assertEqual(result.json['remote_size'],len(self.payload))
        self.assertEqual(result.json['size_comparison'],'mismatch')
        self.connection.download.assert_not_called()

    def test_one_unsupported_captured_path_does_not_abort_the_metadata_batch(self):
        self.map_folder()
        tracks=deepcopy(self.before['tracks'])
        tracks.append({'id':'unsupported','title':'Unsupported captured path',
                       'current_path':str(self.library/('x'*4096+'.mp3'))})
        snapshot=self.store.save_snapshot({'scope_key':'synthetic:unsupported-reference','tracks':tracks,
                                          'playlists':[]},'Unsupported captured reference')
        source='snapshot:'+snapshot['id']
        with patch.object(Path,'open',side_effect=AssertionError('Audio opened during metadata check')):
            self.check(source)
        lstat=Path.lstat
        def mapped_only(path,*args,**kwargs):
            if str(path)=='.':raise AssertionError('Unmapped row inspected the current directory')
            return lstat(path,*args,**kwargs)
        with patch.object(Path,'lstat',autospec=True,side_effect=mapped_only):
            result=self.files(source=source,status='unmapped').json
        self.assertIn('unsupported',{row['track_id'] for row in result['rows']})
        unsupported=next(row for row in result['rows'] if row['track_id']=='unsupported')
        self.assertEqual(unsupported['local_state'],'unmapped')
        self.assertFalse(unsupported['local_available']);self.assertFalse(unsupported['downloadable'])
        self.assertEqual(self.files(source=source,status='present').json['total'],61)
        self.assertEqual(self.files(source=source,status='not_found').json['total'],1)
        self.connection.download.assert_not_called()
        self.assertEqual(self.store.snapshot(snapshot['id'])['tracks'],tracks)

    def test_unsupported_provider_path_preserves_known_present_and_unseen_uncertainty(self):
        self.map_folder()
        unsupported={**self.entries[0],'id':'id:unsupported','path_lower':'/music/literal\\name.mp3',
                     'path_display':'/Music/literal\\name.mp3'}
        self.entries=[self.entries[0],unsupported]
        with patch.object(Path,'open',side_effect=AssertionError('Audio opened during metadata check')):
            self.check()
        result=self.files().json
        self.assertFalse(result['complete'])
        self.assertEqual(result['unsupported_paths'],1)
        self.assertIn('Only positive path matches are confirmed',result['scan_note'])
        self.assertEqual(self.files(status='present').json['total'],1)
        self.assertEqual(self.files(status='not_found').json['total'],0)
        self.assertGreaterEqual(self.files(status='unverified').json['total'],61)
        self.connection.download.assert_not_called();self.assertEqual(self.store.snapshot(self.sid),self.before)

    def test_sql_pages_preserve_unicode_casefold_and_full_source_counts(self):
        tracks=deepcopy(self.before['tracks'])
        tracks[59].update(title='STRASSE 東京',artist='österreich')
        tracks[60].update(title='Straße 東京',artist='ÖSTERREICH')
        snapshot=self.store.save_snapshot({'scope_key':'synthetic:unicode-search','tracks':tracks,'playlists':[]},
                                           'Invented Unicode search')['id']
        source='snapshot:'+snapshot;self.map_folder();self.check(source)
        result=self.files(source=source,status='present',q='strasse 東京').json
        self.assertEqual(result['total'],2)
        self.assertEqual([row['track_id'] for row in result['rows']],['59','60'])
        self.assertEqual(result['counts'],{'present':61,'not_found':1,'unmapped':2,'unverified':0})
        self.assertEqual(self.files(source=source,status='present',q='STRASSE 東京',offset=1).json['rows'][0]['track_id'],'60')
        with patch('dropbox_connector.json.loads',wraps=json.loads) as decode:
            response=self.files(source=source)
        self.assertEqual(response.status_code,200)
        decoded_records=[call for call in decode.call_args_list if isinstance(call.args[0],str)
                         and '"track_id":' in call.args[0] and '"remote":' in call.args[0]]
        self.assertEqual(len(decoded_records),50)
        self.connection.download.assert_not_called()

    def test_failed_recheck_keeps_prior_evidence_and_timestamp(self):
        self.map_folder();self.check();before=self.files().json
        self.partial_listing=True
        result=self.post('check',source=self.source)
        self.assertEqual(result.status_code,400,result.json)
        after=self.files().json
        self.assertEqual(after['checked_at'],before['checked_at'])
        self.assertEqual(after['counts'],before['counts']);self.connection.download.assert_not_called()

    def test_metadata_worker_cannot_write_to_a_switched_profile(self):
        self.map_folder();pending=[]
        with patch.object(application,'launch',side_effect=lambda work,*_,**__:pending.append(work) or 'delayed-job'):
            self.check()
        other=self.root/'Different profile'
        with ExitStack() as changes:
            switched=False
            def progress(*_):
                nonlocal switched
                if not switched:
                    switched=True;changes.enter_context(patch.object(application,'DATA',other))
            with self.assertRaisesRegex(ValueError,'changed'):
                pending[0](progress)
        self.assertFalse(other.exists())
        self.assertEqual(self.files().json['total'],0);self.connection.download.assert_not_called()

    def test_download_requires_explicit_one_use_confirmation_and_publishes_one_regular_file(self):
        self.map_folder();self.check();token=self.prepare()
        self.connection.download.assert_not_called();self.assertFalse((self.album/'Synthetic 000.mp3').exists())
        invalid=self.post('download',source=self.source,track_id='0',confirm=True,confirmation_token='invented')
        self.assertEqual(invalid.status_code,400);self.connection.download.assert_not_called()
        result=self.confirm(token);self.assertEqual(result.status_code,200,result.json)
        self.assertEqual((self.album/'Synthetic 000.mp3').read_bytes(),self.payload)
        self.assertEqual(len(list(self.album.iterdir())),1);self.assertEqual(len(self.downloads),1)
        self.assertTrue(self.downloads[0].closed)
        self.assertEqual(self.confirm(token).status_code,400);self.assertEqual(len(self.downloads),1)
        self.assertEqual(self.store.snapshot(self.sid),self.before)

    def test_existing_file_or_changed_remote_revision_is_never_overwritten(self):
        self.map_folder();self.check();token=self.prepare()
        existing=self.album/'Synthetic 000.mp3';existing.write_bytes(b'Existing private local bytes')
        self.assertEqual(self.confirm(token).status_code,400)
        self.assertEqual(existing.read_bytes(),b'Existing private local bytes');self.connection.download.assert_not_called()
        token=self.prepare('1');self.entries[1]['rev']='different-revision'
        self.assertEqual(self.confirm(token,'1').status_code,400);self.connection.download.assert_not_called()

    def test_one_download_enables_only_that_tracks_fresh_local_playback(self):
        self.map_folder();self.check()
        def availability():
            with patch.object(Path,'open',side_effect=AssertionError('Availability opened audio')):
                response=self.client.post('/api/playback/availability',headers=self.headers,
                    json={'snapshot':self.sid,'track_ids':['0','1'],'refresh':True})
            self.assertEqual(response.status_code,200,response.json)
            return response.json['tracks']
        self.assertEqual(availability(),{'0':False,'1':False})
        result=self.confirm(self.prepare());self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(availability(),{'0':True,'1':False})
        row=self.files(q='Invented 000').json['rows'][0]
        self.assertTrue(row['local_available']);self.assertFalse(row['downloadable'])
        self.assertEqual(len(self.downloads),1)
        self.assertEqual(self.store.snapshot(self.sid),self.before)
        # Residency is rechecked rather than trusted from transfer completion.
        (self.album/'Synthetic 000.mp3').unlink()
        self.assertEqual(availability(),{'0':False,'1':False})

    def test_play_choice_requires_literal_boolean_and_cannot_upgrade_download_consent(self):
        self.map_folder()
        with patch('track_playback.open_audio') as opened:
            for invalid in ('true',1,None,[],{}):
                response=self.post('download/prepare',source=self.source,track_id='0',play_after_download=invalid)
                self.assertEqual(response.status_code,400,response.json)
            token=self.prepare()
            response=self.post('download',source=self.source,track_id='0',confirm=True,
                confirmation_token=token,play_after_download=True)
            self.assertEqual(response.status_code,400,response.json)
            token=self.prepare(play_after_download=True)
            response=self.post('download',source=self.source,track_id='0',confirm=True,
                confirmation_token=token,play_after_download=False)
            self.assertEqual(response.status_code,400,response.json)
            opened.assert_not_called();self.connection.download.assert_not_called()

    def test_approved_download_and_play_opens_only_after_the_exact_file_is_published(self):
        self.map_folder();target=self.album/'Synthetic 000.mp3'
        def assert_published(path):
            self.assertEqual(path,target);self.assertEqual(path.read_bytes(),self.payload)
            self.assertEqual(len(self.downloads),1);self.assertEqual(list(self.album.iterdir()),[target])
        with patch('track_playback.open_audio',side_effect=assert_published) as opened:
            token=self.prepare(play_after_download=True)
            opened.assert_not_called();self.connection.download.assert_not_called()
            response=self.confirm(token)
            self.assertEqual(response.status_code,200,response.json)
            self.assertTrue(self.result['downloaded']);self.assertTrue(self.result['opened'])
            self.assertTrue(self.result['play_after_download']);opened.assert_called_once_with(target)
            self.assertEqual(self.confirm(token).status_code,400)
            self.assertEqual(opened.call_count,1);self.assertEqual(len(self.downloads),1)

    def test_download_only_consent_does_not_open_a_player(self):
        self.map_folder()
        with patch('track_playback.open_audio') as opened,patch('dropbox_download.verify_downloaded_content',side_effect=AssertionError('Download-only content reread')):
            response=self.confirm(self.prepare())
            self.assertEqual(response.status_code,200,response.json)
            self.assertTrue(self.result['downloaded']);self.assertFalse(self.result['opened'])
            self.assertFalse(self.result['play_after_download']);opened.assert_not_called()

    def test_same_size_content_change_with_unchanged_clocks_cannot_open_player(self):
        self.map_folder();target=self.album/'Synthetic 000.mp3'
        from cloud_file_evidence import refresh_download
        from dropbox_download import resident_file_identity
        def changed(*args,**kwargs):
            result=refresh_download(*args,**kwargs)
            info=target.stat();identity=resident_file_identity(target,self.library)
            target.write_bytes(b'X'*len(self.payload));os.utime(target,ns=(info.st_atime_ns,info.st_mtime_ns))
            for stub in (patch('dropbox_download.resident_file_identity',return_value=identity),
                         patch('dropbox_download.os.fstat',return_value=info)):
                stub.start();self.addCleanup(stub.stop)
            return result
        with patch('cloud_file_evidence.refresh_download',side_effect=changed),patch('track_playback.open_audio') as opened:
            response=self.confirm(self.prepare(play_after_download=True))
        self.assertEqual(response.status_code,200,response.json)
        self.assertTrue(self.result['downloaded']);self.assertFalse(self.result['opened'])
        self.assertIn('content changed',self.result['playback_error']);opened.assert_not_called()
        self.assertEqual(target.read_bytes(),b'X'*len(self.payload))

    def test_player_launch_failure_keeps_completed_download_visible(self):
        self.map_folder()
        with patch('track_playback.open_audio',side_effect=ValueError('Synthetic missing player')):
            response=self.confirm(self.prepare(play_after_download=True))
        self.assertEqual(response.status_code,200,response.json)
        self.assertTrue(self.result['downloaded']);self.assertFalse(self.result['opened'])
        self.assertEqual(self.result['playback_error'],'Synthetic missing player')
        self.assertEqual((self.album/'Synthetic 000.mp3').read_bytes(),self.payload)

    def test_removed_or_replaced_download_never_opens_another_file(self):
        self.map_folder()
        from cloud_file_evidence import refresh_download
        for identity,change in (('0','removed'),('1','replaced'),('2','modified')):
            target=self.album/f'Synthetic {int(identity):03}.mp3'
            def changed(*args,**kwargs):
                result=refresh_download(*args,**kwargs)
                if change=='removed':target.unlink()
                elif change=='replaced':
                    other=self.album/'replacement.mp3';other.write_bytes(self.payload);os.replace(other,target)
                else:
                    stamp=target.stat();target.write_bytes(b'X'*len(self.payload))
                    os.utime(target,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
                return result
            with self.subTest(change=change),patch('cloud_file_evidence.refresh_download',side_effect=changed),patch('track_playback.open_audio') as opened:
                response=self.confirm(self.prepare(identity,play_after_download=True),identity)
                self.assertEqual(response.status_code,200,response.json)
                self.assertTrue(self.result['downloaded']);self.assertFalse(self.result['opened'])
                self.assertIn('playback_error',self.result);opened.assert_not_called()

    def test_placeholder_after_publication_remains_unopened(self):
        self.map_folder();target=self.album/'Synthetic 000.mp3';placeholder=False
        from cloud_file_evidence import refresh_download
        original=Path.lstat
        def attributes(path,*args,**kwargs):
            info=original(path,*args,**kwargs)
            if path!=target or not placeholder:return info
            return SimpleNamespace(**{name:getattr(info,name) for name in
                ('st_mode','st_size','st_dev','st_ino','st_mtime_ns','st_ctime_ns')},st_file_attributes=0x1000)
        def evicted(*args,**kwargs):
            nonlocal placeholder
            result=refresh_download(*args,**kwargs);placeholder=True;return result
        with patch.object(Path,'lstat',attributes),patch('cloud_file_evidence.refresh_download',side_effect=evicted),patch('track_playback.open_audio') as opened:
            response=self.confirm(self.prepare(play_after_download=True))
            self.assertEqual(response.status_code,200,response.json)
            self.assertTrue(self.result['downloaded']);self.assertFalse(self.result['opened'])
            self.assertIn('playback_error',self.result);opened.assert_not_called()
        self.assertEqual(target.read_bytes(),self.payload)

    def test_changed_context_after_publication_prevents_play_and_keeps_download(self):
        self.map_folder()
        from cloud_file_evidence import refresh_download
        for identity,change in (('0','mapping'),('1','connection'),('2','profile')):
            self.map_folder();self.status_data['connection_id']='connection-one'
            def switched(*args,**kwargs):
                result=refresh_download(*args,**kwargs)
                if change=='mapping':
                    mapping=self.store.setting('dropbox_mapping');mapping['remote_root']='/Another folder'
                    self.store.set_setting('dropbox_mapping',mapping)
                elif change=='connection':self.status_data['connection_id']='new-authorization'
                else:
                    stub=patch.object(application,'DATA',self.root/'Another profile');stub.start();self.addCleanup(stub.stop)
                return result
            with self.subTest(change=change),patch('cloud_file_evidence.refresh_download',side_effect=switched),patch('track_playback.open_audio') as opened:
                response=self.confirm(self.prepare(identity,play_after_download=True),identity)
                self.assertEqual(response.status_code,200,response.json)
                self.assertTrue(self.result['downloaded']);self.assertFalse(self.result['opened'])
                self.assertIn('playback_error',self.result);opened.assert_not_called()
                self.assertEqual((self.album/f'Synthetic {int(identity):03}.mp3').read_bytes(),self.payload)

    def test_late_cancellation_after_publication_prevents_play_and_keeps_download(self):
        from task_control import TaskControl
        self.map_folder();control=TaskControl()
        def execute(work,_message,**_kwargs):
            def progress(amount,_text):
                if amount==100:control.cancel()
                control.checkpoint(amount)
            self.result=work(progress);return 'cancelled-after-transfer'
        with patch.object(application,'launch',execute),patch('track_playback.open_audio') as opened:
            response=self.confirm(self.prepare(play_after_download=True))
        self.assertEqual(response.status_code,200,response.json)
        self.assertTrue(self.result['downloaded']);self.assertFalse(self.result['opened'])
        self.assertIn('cancelled',self.result['playback_error'].lower());opened.assert_not_called()
        self.assertEqual((self.album/'Synthetic 000.mp3').read_bytes(),self.payload)

    def test_cancellation_during_fresh_inspection_is_checked_before_player_launch(self):
        from task_control import TaskControl
        from track_playback import inspect_audio_details
        self.map_folder();control=TaskControl()
        def execute(work,_message,**_kwargs):
            self.result=work(lambda amount,_text:control.checkpoint(amount));return 'cancelled-during-inspection'
        def inspect_then_cancel(*args,**kwargs):
            result=inspect_audio_details(*args,**kwargs);control.cancel();return result
        with patch.object(application,'launch',execute),patch('track_playback.inspect_audio_details',side_effect=inspect_then_cancel),patch('track_playback.open_audio') as opened:
            response=self.confirm(self.prepare(play_after_download=True))
        self.assertEqual(response.status_code,200,response.json)
        self.assertTrue(self.result['downloaded']);self.assertFalse(self.result['opened'])
        self.assertIn('cancelled',self.result['playback_error'].lower());opened.assert_not_called()
        self.assertEqual((self.album/'Synthetic 000.mp3').read_bytes(),self.payload)

    def test_interruption_and_hash_mismatch_leave_no_final_or_partial_file(self):
        self.map_folder();self.check();self.interrupt=True
        result=self.confirm(self.prepare())
        self.assertEqual(result.status_code,400,result.json);self.assertEqual(list(self.album.iterdir()),[])
        self.interrupt=False;self.corrupt=True
        result=self.confirm(self.prepare())
        self.assertEqual(result.status_code,400,result.json);self.assertEqual(list(self.album.iterdir()),[])
        self.assertTrue(all(stream.closed for stream in self.downloads))

    def test_source_account_and_track_identity_are_bound_to_the_confirmation(self):
        self.map_folder();self.check();token=self.prepare()
        self.assertEqual(self.confirm(token,'1').status_code,400)
        token=self.prepare();self.status_data['connection_id']='different-connection'
        self.assertEqual(self.confirm(token).status_code,400);self.connection.download.assert_not_called()

    def test_confirmation_requires_literal_consent_and_expires(self):
        self.map_folder();token=self.prepare()
        denied=self.post('download',source=self.source,track_id='0',confirmation_token=token,confirm='true')
        self.assertEqual(denied.status_code,400);self.connection.download.assert_not_called()
        with patch('dropbox_connector.time.monotonic',return_value=time.monotonic()+121):
            self.assertEqual(self.confirm(token).status_code,400)
        self.connection.download.assert_not_called()

    def test_local_origin_token_and_source_guards_reject_requests_without_transfers(self):
        self.map_folder()
        self.assertEqual(self.client.post('/api/dropbox/check',json={'source':self.source}).status_code,403)
        for overrides in ({'REMOTE_ADDR':'192.0.2.5'},{'HTTP_HOST':'evil.example'}):
            result=self.client.post('/api/dropbox/check',json={'source':self.source},headers=self.headers,environ_overrides=overrides)
            self.assertEqual(result.status_code,400)
        self.assertEqual(self.post('check',source='../not-a-source').status_code,400)
        self.connection.download.assert_not_called()

    def test_cached_evidence_is_isolated_by_source_connection_and_mapping(self):
        self.map_folder();self.check()
        other=self.store.save_snapshot({'scope_key':'synthetic:other-library','tracks':[
            {'id':'0','title':'Same ID, different collection','current_path':str(self.album/'Synthetic 000.mp3')}],
            'playlists':[]},'Other invented collection')['id']
        self.assertEqual(self.files(source='snapshot:'+other).json['total'],0)
        self.status_data['connection_id']='new-authorization'
        self.assertEqual(self.files().json['total'],0)
        self.status_data['connection_id']='connection-one'
        self.assertEqual(self.files().json['total'],64)
        mapping=self.store.setting('dropbox_mapping');mapping['remote_root']='/Different folder'
        self.store.set_setting('dropbox_mapping',mapping)
        self.assertEqual(self.files().json['total'],0)
        self.connection.download.assert_not_called()

    def test_mapping_requires_detected_root_and_a_verified_remote_folder(self):
        with patch('dropbox_files.detected_roots',return_value=[]):
            denied=self.post('mapping',local_root=str(self.library),remote_root='/Music')
        self.assertEqual(denied.status_code,400);self.connection.rpc.assert_not_called()
        self.assertIsNone(self.store.setting('dropbox_mapping'))
        roots=[{'root':str(self.dropbox),'kind':'dropbox','provider_verified':True,'availability':'local'}]
        with patch('dropbox_files.detected_roots',return_value=roots):
            denied=self.post('mapping',local_root=str(self.library),remote_root=self.entries[0]['path_display'])
        self.assertEqual(denied.status_code,400)
        self.assertIsNone(self.store.setting('dropbox_mapping'));self.connection.download.assert_not_called()

    def test_windows_original_and_xml_references_use_saved_audio_mapping_without_rewriting_snapshot(self):
        from audio_paths import validate
        snapshot=self.store.save_snapshot({'scope_key':'synthetic:windows-import','tracks':[
            {'id':'xml','title':'XML reference','xml_location':'file://localhost/D:/Album/Synthetic%20000.mp3'},
            {'id':'original','title':'Original reference','original_path':'D:/Album/Synthetic 001.mp3'},
            {'id':'current','title':'Authoritative relocated path','current_path':str(self.album/'Synthetic 002.mp3'),
             'xml_location':'file://localhost/D:/Album/Synthetic%20003.mp3','original_path':'D:/Album/Synthetic 004.mp3'}],
            'playlists':[]},'Invented Windows collection')['id']
        before=deepcopy(self.store.snapshot(snapshot));source='snapshot:'+snapshot
        mapping=validate([{'recorded_root':'D:/','local_root':str(self.library)}],[self.root])
        self.store.set_setting('audio_paths:'+before['scope_key'],mapping)
        self.map_folder();self.check(source)
        self.assertEqual(self.files(source=source,status='present').json['total'],3)
        current=self.files(source=source,q='Authoritative relocated path').json['rows'][0]
        self.assertEqual(current['remote_path'],'/Music/Album/Synthetic 002.mp3')
        self.assertEqual(self.store.snapshot(snapshot),before)
        self.connection.download.assert_not_called();self.assertEqual(list(self.album.iterdir()),[])
        self.store.set_setting('audio_paths:'+before['scope_key'],[])
        self.assertEqual(self.files(source=source).json['total'],0)

    def test_symlinked_destination_and_mapping_change_invalidate_download(self):
        self.map_folder();self.check();token=self.prepare()
        mapping=self.store.setting('dropbox_mapping');mapping['remote_root']='/Different folder'
        self.store.set_setting('dropbox_mapping',mapping)
        self.assertEqual(self.confirm(token).status_code,400);self.connection.download.assert_not_called()
        self.map_folder()
        self.album.rename(self.library/'Real album');self.album.symlink_to(self.library/'Real album',target_is_directory=True)
        denied=self.post('download/prepare',source=self.source,track_id='0')
        self.assertEqual(denied.status_code,400);self.connection.download.assert_not_called()

    def test_callback_rejects_foreign_host_and_peer_before_oauth_completion(self):
        for overrides in ({'REMOTE_ADDR':'192.0.2.5'},{'HTTP_HOST':'evil.example'}):
            result=self.client.get('/api/dropbox/callback?state=invented&code=invented',environ_overrides=overrides)
            self.assertEqual(result.status_code,400)
        self.connection.callback.assert_not_called()

    def test_status_and_callback_do_not_allow_response_caching_or_referrer_leaks(self):
        response=self.client.get('/api/dropbox/status')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertEqual(response.headers['Referrer-Policy'],'no-referrer')
        self.assertNotIn('access_token',response.json);self.assertNotIn('refresh_token',response.json)
        response=self.client.get('/api/dropbox/callback?state=invented-state&code=invented-code')
        self.assertEqual(response.status_code,303)
        self.assertEqual(response.headers['Location'],'/#dropbox')
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertEqual(response.headers['Referrer-Policy'],'no-referrer')
        self.connection.callback.assert_called_once()


if __name__=='__main__':unittest.main()

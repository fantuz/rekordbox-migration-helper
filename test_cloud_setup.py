"""Guided attachment integrity with real routes/store and invented providers."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import time
import unittest
from unittest.mock import Mock,patch

from flask import Flask,jsonify
import audio_paths
import cloud_attachments
import cloud_setup
import dropbox_files
from workbench_store import Store


class CloudSetupTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.data=self.root/'work'
        self.cache=self.root/'Selected downloads';(self.cache/'Album').mkdir(parents=True)
        self.google_cache=self.root/'Google downloads';(self.google_cache/'Album').mkdir(parents=True)
        self.saved=Store(self.data/'workbench-sidecar.sqlite3')
        self.snapshot=self.saved.save_snapshot({'scope_key':'invented:cloud-gate','tracks':[
            {'id':'d','title':'Invented Dropbox track','current_path':'D:/OldDropbox/Music/Album/Track.mp3','size':12},
            {'id':'g','title':'Invented Google track','current_path':'E:/OldDrive/Music/Album/Google.mp3','size':20}],
            'playlists':[]},'Invented cloud collection')
        self.source='snapshot:'+self.snapshot['id'];self.before=deepcopy(self.saved.snapshot(self.snapshot['id']))
        self.app=Flask(__name__);self.app.testing=False
        self.app.register_error_handler(ValueError,lambda error:(jsonify(error=str(error)),400))
        self.owner=SimpleNamespace(DATA=self.data,app=self.app)
        self.results={};self.job=0
        def launch(work,_message,**kwargs):
            self.job+=1;job='invented-'+str(self.job)
            self.results[job]=work(lambda *_:None)
            return job
        self.owner.launch=launch
        self.states={p:{'configured':True,'connected':True,'connection_id':p+'-connection',
            'account':{'account_id':p+'-account','display_name':'Invented account','root_namespace_id':'101'}}
            for p in cloud_setup.PROVIDERS}
        self.clients={p:SimpleNamespace(status=Mock(side_effect=lambda name=p:deepcopy(self.states[name])),rpc=Mock())
                      for p in cloud_setup.PROVIDERS}
        self.remote_folder='id:folder';self.dropbox_entries=[{'.tag':'file','id':'id:d','rev':'123abc','size':12,
            'path_display':'/Music/Album/Track.mp3','path_lower':'/music/album/track.mp3'}]
        def rpc(route,payload,**kwargs):
            if route=='files/get_metadata':return {'.tag':'folder','id':self.remote_folder}
            if route=='files/list_folder':return {'entries':deepcopy(self.dropbox_entries),'has_more':False}
            raise AssertionError(route)
        self.clients['dropbox'].rpc.side_effect=rpc
        self.google_entries={'Album/Google.mp3':{'id':'g1','size':'20'}}
        def google_mapping(client,local_root,folder,*,owner,sync_mode,recorded_root):
            return {**cloud_attachments.local_mapping(owner,local_root,'google_drive',sync_mode,recorded_root),
                    'remote_root':folder,'remote_folder_id':folder,'account_id':client.status()['account']['account_id']}
        def google_validate(client,mapping):
            if mapping['account_id']!=client.status()['account']['account_id']:raise ValueError('Account changed')
            cloud_attachments.validate_local(mapping);return client.status()
        def google_target(track,mapping,audio):
            value=cloud_attachments.track_target(track,mapping,audio)
            return {**value,'remote_path':value['relative_path']} if value else None
        def lookup(entries,path):
            return (entries.get(path),'present' if entries.get(path) else 'ambiguous' if path in entries else 'not_found')
        self.google=SimpleNamespace(mapping_record=google_mapping,validate_mapping=google_validate,
            target=google_target,inventory=lambda *_:(deepcopy(self.google_entries),True),lookup=lookup,
            _folder=lambda *_:{'id':'remote-google'})
        for target,value in [('cloud_attachments.allowed_roots',lambda _: [self.root]),
                             ('audio_paths.allowed_roots',lambda _: [self.root]),
                             ('cloud_attachments.provider_roots',lambda **_:[]),
                             ('cloud_setup.provider_roots',lambda **_:[]),
                             ('cloud_setup._provider',lambda _,p:(self.clients[p],dropbox_files if p=='dropbox' else self.google))]:
            stub=patch(target,value);stub.start();self.addCleanup(stub.stop)
        original=cloud_setup._remote_identity
        stub=patch('cloud_setup._remote_identity',side_effect=lambda c,p,m: original(c,p,m) if p=='dropbox' else 'remote-google')
        stub.start();self.addCleanup(stub.stop)
        cloud_setup.register(self.owner);self.client=self.app.test_client()

    def post(self,path,**body):return self.client.post('/api/cloud-setup/'+path,json=body)

    def preview(self,provider='dropbox',**overrides):
        value={'provider':provider,'source':self.source,'arrangement':'personal' if provider=='dropbox' else 'own_google',
               'sync_mode':'selected','local_root':str(self.cache if provider=='dropbox' else self.google_cache),
               'recorded_root':'D:/OldDropbox/Music' if provider=='dropbox' else 'E:/OldDrive/Music',
               'remote_root':'/Music','remote_folder_id':'remote-google',**overrides}
        response=self.post('preview',**value)
        self.assertEqual(response.status_code,200,response.json)
        return self.results[response.json['job']]

    def attach(self,preview,**fields):
        return self.post('attach',preview_token=preview['preview_token'],confirm=True,**fields)

    def test_selected_cache_outside_desktop_root_preview_does_not_attach_or_read_audio(self):
        with patch.object(Path,'open',side_effect=AssertionError('Audio opened')):
            result=self.preview()
        self.assertTrue(result['attachable']);self.assertEqual(result['matched'],1)
        self.assertEqual(result['unmapped'],1);self.assertFalse(result['content_verified'])
        self.assertIsNone(self.saved.setting('dropbox_mapping'))
        self.assertEqual(audio_paths.mappings_for(self.saved,self.before),[])
        response=self.attach(result)
        self.assertEqual(response.status_code,200,response.json)
        mapping=self.saved.setting('dropbox_mapping')
        self.assertEqual(Path(mapping['local_root']),self.cache);self.assertEqual(mapping['source'],self.source)
        self.assertEqual(len(audio_paths.mappings_for(self.saved,self.before)),1)
        self.assertEqual(self.saved.snapshot(self.snapshot['id']),self.before)
        self.assertEqual(self.attach(result).status_code,400)

    def test_zero_match_and_google_ambiguity_hold_attachment(self):
        self.dropbox_entries=[];result=self.preview()
        self.assertFalse(result['attachable']);self.assertIsNone(result['preview_token'])
        self.google_entries={'Album/Google.mp3':None};result=self.preview('google_drive')
        self.assertFalse(result['attachable']);self.assertEqual(result['ambiguous'],1)
        self.assertIsNone(self.saved.setting('google_drive_mapping'))

    def test_account_and_folder_identity_changes_invalidate_preview(self):
        result=self.preview();self.states['dropbox']['connection_id']='new-account-session'
        self.assertEqual(self.attach(result).status_code,400)
        self.states['dropbox']['connection_id']='dropbox-connection'
        result=self.preview();self.remote_folder='id:replacement'
        self.assertEqual(self.attach(result).status_code,400)
        self.assertIsNone(self.saved.setting('dropbox_mapping'))

    def test_local_folder_replacement_invalidates_preview(self):
        result=self.preview();self.cache.rename(self.root/'Old downloads');self.cache.mkdir()
        self.assertEqual(self.attach(result).status_code,400)
        self.assertIsNone(self.saved.setting('dropbox_mapping'))

    def test_changed_audio_mapping_or_source_invalidates_preview(self):
        result=self.preview()
        self.saved.set_setting('audio_paths:'+self.before['scope_key'],[{'recorded_root':'X:/Other','local_root':str(self.cache),'device':0,'inode':0}])
        self.assertEqual(self.attach(result).status_code,400)
        self.saved.set_setting('audio_paths:'+self.before['scope_key'],[])
        result=self.preview()
        with self.saved.connection() as db:db.execute('DELETE FROM snapshots WHERE id=?',(self.snapshot['id'],))
        self.assertEqual(self.attach(result).status_code,400)

    def test_preview_expiry_and_literal_consent(self):
        result=self.preview()
        denied=self.post('attach',preview_token=result['preview_token'],confirm='true')
        self.assertEqual(denied.status_code,400)
        with patch('cloud_setup.time.monotonic',return_value=time.monotonic()+121):
            self.assertEqual(self.attach(result).status_code,400)

    def test_both_providers_coexist_and_detach_preserves_other_account_and_files(self):
        self.assertEqual(self.attach(self.preview()).status_code,200)
        self.assertEqual(self.attach(self.preview('google_drive')).status_code,200)
        local=self.cache/'ordinary.txt';local.write_text('Invented local bytes')
        response=self.post('detach',provider='dropbox')
        self.assertEqual(response.status_code,200,response.json)
        self.assertIsNone(self.saved.setting('dropbox_mapping'))
        self.assertIsNotNone(self.saved.setting('google_drive_mapping'))
        self.assertTrue(self.states['dropbox']['connected']);self.assertTrue(self.states['google_drive']['connected'])
        self.assertEqual(local.read_text(),'Invented local bytes')
        self.assertEqual(len(audio_paths.mappings_for(self.saved,self.before)),2)

    def test_status_does_not_claim_a_folder_is_attached_to_another_collection(self):
        self.assertEqual(self.attach(self.preview()).status_code,200)
        first=self.client.get('/api/cloud-setup/status',query_string={'source':self.source}).json
        self.assertTrue(first['providers']['dropbox']['attachment_active'])
        other=self.saved.save_snapshot({'scope_key':'invented:other-collection','tracks':[],
                                        'playlists':[]},'Another collection')
        self.clients['dropbox'].rpc.reset_mock()
        result=self.client.get('/api/cloud-setup/status',query_string={'source':'snapshot:'+other['id']}).json
        self.assertFalse(result['providers']['dropbox']['attachment_active'])
        self.assertIsNone(result['providers']['dropbox']['mapping'])
        self.assertEqual(result['attachments']['dropbox']['source'],self.source)
        self.clients['dropbox'].rpc.assert_not_called()

        legacy=self.saved.setting('dropbox_mapping');legacy.pop('source')
        self.saved.set_setting('dropbox_mapping',legacy)
        result=self.client.get('/api/cloud-setup/status',query_string={'source':self.source}).json
        self.assertFalse(result['providers']['dropbox']['attachment_active'])

    def test_host_platform_is_coarse_context_and_never_changes_folder_authorization(self):
        for name,expected in (('Windows','windows'),('Darwin','mac'),('Linux','linux'),('Plan9 private-host-marker','unknown')):
            with self.subTest(platform=name),patch('cloud_setup.platform.system',return_value=name):
                response=self.client.get('/api/cloud-setup/status',query_string={'source':self.source})
                self.assertEqual(response.status_code,200,response.json)
                self.assertEqual(response.json['host_platform'],expected)
                self.assertNotIn('private-host-marker',str(response.json))
        for client in self.clients.values():client.rpc.assert_not_called()
        # A browser/host hint cannot grant access to a different physical folder.
        with patch('cloud_setup.platform.system',return_value='Windows'):
            refused=self.post('preview',provider='dropbox',source=self.source,arrangement='personal',
                sync_mode='selected',local_root='C:/UNAPPROVED-CLOUD-FOLDER',remote_root='/Music')
        self.assertEqual(refused.status_code,400,refused.json)
        for client in self.clients.values():client.rpc.assert_not_called()

    def test_status_is_local_only_and_does_not_call_remote_provider(self):
        response=self.client.get('/api/cloud-setup/status',query_string={'source':self.source})
        self.assertEqual(response.status_code,200,response.json)
        for client in self.clients.values():client.rpc.assert_not_called()
        foreign=self.client.get('/api/cloud-setup/status',environ_overrides={'REMOTE_ADDR':'192.0.2.10'})
        self.assertEqual(foreign.status_code,400)

    def test_refresh_reuses_path_summary_and_reads_current_account_and_settings(self):
        query={'source':self.source}
        with patch('cloud_setup.resolve',wraps=cloud_setup.resolve) as read_source:
            first=self.client.get('/api/cloud-setup/status',query_string=query).get_json()
            self.states['dropbox']['connected']=False
            cloud_setup.callback_errors(self.app,'dropbox')[str(self.data)]='Authorization cancelled'
            self.saved.set_setting('cloud_default_upload:'+self.before['scope_key'],'google_drive')
            second=self.client.get('/api/cloud-setup/status',query_string=query).get_json()
            read_source.assert_called_once_with(self.owner,self.source)
            self.assertEqual(second['source']['suggestions'],first['source']['suggestions'])
            self.assertEqual(second['source']['default_upload'],'google_drive')
            self.assertFalse(second['providers']['dropbox']['connected'])
            self.assertEqual(second['providers']['dropbox']['authorization_error'],'Authorization cancelled')
            self.assertIsNone(second['providers']['google_drive']['authorization_error'])
            # Discovering a configured root changes the evidence for the same snapshot.
            roots=[{'kind':'dropbox','root':'D:/OldDropbox/Music','provider_verified':True,'availability':'available'}]
            with patch('cloud_setup.provider_roots',return_value=roots):
                updated=self.client.get('/api/cloud-setup/status',query_string=query).get_json()
            self.assertTrue(any(row['evidence']=='provider_configuration' for row in updated['source']['suggestions']))
            self.assertEqual(read_source.call_count,2)
            with self.saved.connection() as db:
                db.execute('DELETE FROM snapshots WHERE id=?',(self.snapshot['id'],))
            self.assertEqual(self.client.get('/api/cloud-setup/status',query_string=query).status_code,400)
            self.assertEqual(read_source.call_count,2)
        for client in self.clients.values():client.rpc.assert_not_called()

    def test_google_all_mode_and_unconfined_local_folder_rejected(self):
        response=self.post('preview',provider='google_drive',source=self.source,sync_mode='all')
        self.assertEqual(response.status_code,400)
        response=self.post('preview',provider='dropbox',source=self.source,sync_mode='selected',
                           local_root=str(self.root.parent/'Unrelated'),remote_root='/Music')
        self.assertEqual(response.status_code,400)
        self.clients['dropbox'].rpc.assert_not_called()

    def test_metadata_size_warning_does_not_claim_content_identity(self):
        self.dropbox_entries[0]['size']=99
        result=self.preview()
        self.assertTrue(result['attachable']);self.assertEqual(len(result['metadata_warnings']),1)
        self.assertFalse(result['content_verified'])

    def test_other_provider_root_is_rejected_before_remote_calls_but_weak_hint_is_not(self):
        strong=[{'root':str(self.root),'kind':'dropbox','provider_verified':True},
                {'root':str(self.cache),'kind':'google_drive','provider_verified':True}]
        value={'provider':'dropbox','source':self.source,'sync_mode':'selected','local_root':str(self.cache),
               'recorded_root':'D:/OldDropbox/Music','remote_root':'/Music'}
        with patch('cloud_attachments.provider_roots',return_value=strong):
            response=self.post('preview',**value)
        self.assertEqual(response.status_code,400)
        self.clients['dropbox'].rpc.assert_not_called()
        self.assertIsNone(self.saved.setting('dropbox_mapping'))
        with patch('cloud_attachments.provider_roots',return_value=[{**strong[1],'provider_verified':False}]):
            result=self.preview()
        self.assertTrue(result['attachable'])

    def test_nested_other_provider_destination_is_held(self):
        roots=[{'root':str(self.cache/'Album'),'kind':'google_drive','provider_verified':True}]
        with patch('cloud_attachments.provider_roots',return_value=roots):
            result=self.preview()
        self.assertFalse(result['attachable']);self.assertEqual(result['matched'],0)

    def test_preview_examples_prioritize_matches_late_in_source(self):
        tracks=[{'id':str(i),'current_path':'Z:/Elsewhere/Absent'+str(i)+'.mp3'} for i in range(12)]
        tracks.append(self.before['tracks'][0])
        saved=self.saved.save_snapshot({'scope_key':'invented:late-match','tracks':tracks,'playlists':[]},'Late match')
        result=self.preview(source='snapshot:'+saved['id'])
        self.assertTrue(result['attachable']);self.assertEqual(result['examples'][0]['status'],'matched')
        self.assertEqual(result['examples'][0]['track_id'],'d')


if __name__=='__main__':unittest.main()

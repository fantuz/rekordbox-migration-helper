"""Cached cloud presence stays distinct from local access in File health."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class CloudFileEvidenceTests(unittest.TestCase):
    def setUp(self):
        from test_cloud_connection_workflows import CloudConnectionWorkflowTests
        self.fixture=CloudConnectionWorkflowTests('test_both_selected_cache_attachments_preserve_sources_and_detach_independently')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def ready(self,providers=('dropbox','google_drive')):
        f=self.fixture
        for provider in providers:f.attach(provider)
        f.poll(f.post('file-health/scan',{'source':f.source}))
        for provider in providers:
            prefix='google-drive' if provider=='google_drive' else provider
            f.poll(f.post(prefix+'/check',{'source':f.source}))

    def health(self,**values):
        f=self.fixture
        result=f.client.get('/api/file-health',query_string={'source':f.source,**values})
        self.assertEqual(result.status_code,200,result.json)
        return result.json

    def no_audio_open(self):
        original=Path.open
        def only_metadata(path,*args,**kwargs):
            if path.suffix.lower() in ('.mp3','.flac','.wav','.m4a'):
                raise AssertionError('Local audio opened')
            return original(path,*args,**kwargs)
        return patch.object(Path,'open',only_metadata)

    def test_cloud_present_does_not_turn_local_unknown_into_accessible(self):
        self.ready();f=self.fixture
        for provider in f.providers.values():provider.calls.clear()
        with patch.object(Path,'open',side_effect=AssertionError('Audio opened')),patch('file_health.resolve',side_effect=AssertionError('Snapshot decoded')):
            result=self.health()
        self.assertTrue(all(not provider.calls and not provider.downloads for provider in f.providers.values()))
        by_id={row['track_id']:row for row in result['rows']}
        row=by_id['db-0']
        self.assertEqual(row['status'],'unverified')
        remote=next(item for item in row['cloud_evidence'] if item['provider']=='dropbox')
        self.assertEqual(remote['status'],'present')
        self.assertTrue(remote['downloadable']);self.assertTrue(remote['complete'])
        self.assertGreater(remote['checked_at'],0)
        self.assertEqual(set(result['cloud_checks']),{'dropbox','google_drive'})
        self.assertTrue(all(value['state']=='checked' for value in result['cloud_checks'].values()))
        self.assertEqual(f.store.snapshot(f.sid),f.before)
        serialized=json.dumps(result)
        for private in ('dropbox@example.invalid','google@example.invalid','dbid:invented-cloud-workflow','/Music/Album/'):
            self.assertNotIn(private,serialized)

    def test_local_scan_alone_never_claims_a_cloud_check(self):
        f=self.fixture;f.attach('dropbox')
        f.poll(f.post('file-health/scan',{'source':f.source}))
        for provider in f.providers.values():provider.calls.clear()
        result=self.health()
        self.assertEqual(result['cloud_checks']['dropbox']['state'],'not_checked')
        self.assertEqual(result['cloud_checks']['google_drive']['state'],'not_attached')
        self.assertTrue(all(row['cloud_evidence']==[] for row in result['rows']))
        self.assertTrue(all(not provider.calls for provider in f.providers.values()))

    def test_account_reconnection_and_disconnection_hide_old_cloud_results(self):
        self.ready();f=self.fixture
        f.providers['dropbox'].state['connection_id']='a-new-authorization'
        f.providers['google_drive'].state['connected']=False
        result=self.health()
        self.assertEqual(result['cloud_checks']['dropbox']['state'],'not_checked')
        self.assertEqual(result['cloud_checks']['google_drive']['state'],'not_connected')
        self.assertTrue(all(row['cloud_evidence']==[] for row in result['rows']))

    def test_other_source_or_changed_audio_mapping_cannot_reuse_cached_results(self):
        self.ready();f=self.fixture
        another=f.store.save_snapshot({**deepcopy(f.before),'scope_key':'synthetic:other-evidence'},'Another collection')['id']
        other='snapshot:'+another
        f.poll(f.post('file-health/scan',{'source':other}))
        result=self.health(source=other)
        self.assertTrue(all(row['cloud_evidence']==[] for row in result['rows']))
        mapping=f.store.setting('audio_paths:'+f.before['scope_key'],[])
        mapping.append({'recorded_root':'Y:/Unrelated','local_root':str(f.root),'device':f.root.stat().st_dev,'inode':f.root.stat().st_ino})
        f.store.set_setting('audio_paths:'+f.before['scope_key'],mapping)
        result=self.health()
        self.assertTrue(all(row['cloud_evidence']==[] for row in result['rows']))

    def test_changed_or_detached_cloud_folder_does_not_show_old_presence(self):
        self.ready();f=self.fixture
        mapped=f.store.setting('dropbox_mapping');mapped['remote_root']='/Different folder'
        f.store.set_setting('dropbox_mapping',mapped)
        f.store.set_setting('google_drive_mapping',None)
        result=self.health()
        self.assertEqual(result['cloud_checks']['dropbox']['state'],'not_checked')
        self.assertEqual(result['cloud_checks']['google_drive']['state'],'not_attached')
        self.assertTrue(all(row['cloud_evidence']==[] for row in result['rows']))

    def test_partial_scan_and_missing_index_rows_remain_unverified(self):
        self.ready();f=self.fixture
        import dropbox_connector
        context=dropbox_connector.evidence_context(f.application,f.source)
        with f.store.connection() as db:
            scan=json.loads(db.execute('SELECT payload FROM dropbox_scans WHERE binding=? AND source=?',(context['key'],f.source)).fetchone()[0])
            scan['complete']=False
            db.execute('UPDATE dropbox_scans SET payload=? WHERE binding=? AND source=?',(json.dumps(scan),context['key'],f.source))
            db.execute('DELETE FROM dropbox_records WHERE binding=? AND source=? AND track_id=?',(context['key'],f.source,'db-0'))
            row=json.loads(db.execute('SELECT payload FROM dropbox_records WHERE binding=? AND source=? AND track_id=?',(context['key'],f.source,'db-1')).fetchone()[0])
            row['status']='not_found';row['remote']=None
            db.execute('UPDATE dropbox_records SET payload=? WHERE binding=? AND source=? AND track_id=?',(json.dumps(row),context['key'],f.source,'db-1'))
        result=self.health()
        for row in result['rows']:
            if row['track_id'] in ('db-0','db-1'):
                cloud=next(item for item in row['cloud_evidence'] if item['provider']=='dropbox')
                self.assertEqual(cloud['status'],'unverified');self.assertFalse(cloud['complete'])

    def test_only_displayed_rows_are_decoded_and_cloud_join_preserves_filters(self):
        self.ready()
        with patch('cloud_file_evidence.json.loads',wraps=json.loads) as decode:
            result=self.health()
        payloads=[call for call in decode.call_args_list if isinstance(call.args[0],str) and '"track_id":' in call.args[0] and '"remote":' in call.args[0]]
        self.assertEqual(len(result['rows']),50)
        self.assertEqual(len(payloads),100)
        filtered=self.health(q='Invented Dropbox')
        self.assertEqual(filtered['total'],2)
        self.assertEqual(filtered['counts'],result['counts'])
        self.assertEqual(filtered['provider_counts'],result['provider_counts'])

    def test_nonlocal_file_health_requests_do_not_expose_cloud_evidence(self):
        self.ready();f=self.fixture
        for headers,overrides in (({}, {'REMOTE_ADDR':'198.51.100.4'}),
                                   ({'Origin':'https://other.example'},{})):
            result=f.client.get('/api/file-health',query_string={'source':f.source},headers=headers,environ_overrides=overrides)
            self.assertEqual(result.status_code,200,result.json)
            self.assertEqual(result.json['cloud_checks'],{})
            self.assertTrue(all(row['cloud_evidence']==[] for row in result.json['rows']))
        untrusted=f.client.get('/api/file-health',query_string={'source':f.source},headers={'Host':'remote.example'})
        self.assertEqual(untrusted.status_code,400)
        self.assertNotIn('cloud_checks',untrusted.json)
        result=f.client.get('/api/file-health',query_string={'source':f.source})
        self.assertEqual(result.headers['Cache-Control'],'no-store')

    def test_approved_download_refreshes_only_its_existing_local_row(self):
        self.ready();f=self.fixture
        for provider,identity in (('dropbox','db-0'),('google_drive','gd-0')):
            with self.subTest(provider=provider):
                with f.store.connection() as db:
                    before={row['track_id']:dict(row) for row in db.execute('SELECT * FROM file_health_records WHERE source=?',(f.source,))}
                prefix='google-drive' if provider=='google_drive' else provider
                prepared=f.post(prefix+'/download/prepare',{'source':f.source,'track_id':identity})
                self.assertEqual(prepared.status_code,200,prepared.json)
                with self.no_audio_open():
                    result=f.poll(f.post(prefix+'/download',{'source':f.source,'track_id':identity,
                        'confirm':True,'confirmation_token':prepared.json['confirmation_token']}))
                self.assertEqual(result['local_evidence']['status'],'playable')
                self.assertTrue(result['local_evidence']['file_health_updated'])
                with f.store.connection() as db:
                    after={row['track_id']:dict(row) for row in db.execute('SELECT * FROM file_health_records WHERE source=?',(f.source,))}
                self.assertEqual(after[identity]['status'],'playable')
                self.assertEqual({key:value for key,value in before.items() if key!=identity},
                                 {key:value for key,value in after.items() if key!=identity})
                self.assertEqual(f.store.snapshot(f.sid),f.before)

    def test_download_without_a_local_scan_does_not_create_scan_rows(self):
        f=self.fixture;f.attach('google_drive')
        prepared=f.post('google-drive/download/prepare',{'source':f.source,'track_id':'gd-0'})
        result=f.poll(f.post('google-drive/download',{'source':f.source,'track_id':'gd-0',
            'confirm':True,'confirmation_token':prepared.json['confirmation_token']}))
        self.assertEqual(result['local_evidence']['status'],'playable')
        self.assertFalse(result['local_evidence']['file_health_updated'])
        with f.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM file_health_records').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM file_health_scans').fetchone()[0],0)

    def test_fresh_attributes_preserve_unknown_if_provider_makes_a_placeholder(self):
        self.ready(('dropbox',));f=self.fixture
        from audio_paths import mappings_for
        from cloud_file_evidence import refresh_download
        target=f.dropbox_cache/'Album'/'Dropbox 000.mp3';target.write_bytes(f.providers['dropbox'].body)
        original=Path.lstat
        def attributes(path,*args,**kwargs):
            info=original(path,*args,**kwargs)
            return SimpleNamespace(st_mode=info.st_mode,st_size=info.st_size,st_file_attributes=0x1000) if path==target else info
        track=f.before['tracks'][0]
        with patch.object(Path,'lstat',attributes),self.no_audio_open():
            result=refresh_download(f.data,f.source,'db-0',track,mappings_for(f.store,f.before))
        self.assertEqual(result['status'],'unverified')
        with f.store.connection() as db:
            row=db.execute('SELECT status,cloud_state FROM file_health_records WHERE source=? AND track_id=?',(f.source,'db-0')).fetchone()
        self.assertEqual(tuple(row),('unverified','online_only'))

    def test_local_refresh_stays_bound_to_the_completed_download_profile(self):
        self.ready(('dropbox',));f=self.fixture
        from audio_paths import mappings_for
        from cloud_file_evidence import refresh_download
        target=f.dropbox_cache/'Album'/'Dropbox 000.mp3';target.write_bytes(f.providers['dropbox'].body)
        other=f.root/'Another profile'
        with patch.object(f.application,'DATA',other):
            result=refresh_download(f.data,f.source,'db-0',f.before['tracks'][0],mappings_for(f.store,f.before))
        self.assertEqual(result['status'],'playable');self.assertFalse(other.exists())

    def test_refresh_failure_does_not_report_the_completed_transfer_as_failed(self):
        f=self.fixture;f.attach('dropbox')
        prepared=f.post('dropbox/download/prepare',{'source':f.source,'track_id':'db-0'})
        with patch('cloud_file_evidence.refresh_download',side_effect=OSError('Synthetic local evidence failure')):
            result=f.poll(f.post('dropbox/download',{'source':f.source,'track_id':'db-0',
                'confirm':True,'confirmation_token':prepared.json['confirmation_token']}))
        self.assertFalse(result['local_evidence_refreshed'])
        self.assertEqual((f.dropbox_cache/'Album'/'Dropbox 000.mp3').read_bytes(),f.providers['dropbox'].body)


if __name__=='__main__':unittest.main()

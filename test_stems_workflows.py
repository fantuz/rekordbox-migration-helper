"""STEMS workflow boundaries, saved reports and API contracts on synthetic data."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import os
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from analysis_audit import audit_assets
from metadata_export import capture_catalog,capture_database,payload
from stems_cache import provider_report,source_stamp
from stems_eligibility import context,cache_profile
from stems_report import stems_report
from task_control import OperationCancelled
from test_stems_followup import MODEL,KEY,OTHER_KEY,ni_bytes,manifest,write_cache
from test_support import workspace_client
from workbench_store import Store


class ScopeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.audio=self.root/'audio';self.audio.mkdir();self.source=self.audio/'invented.wav';self.source.write_bytes(b'synthetic source')
        self.cache=write_cache(self.root/'RB Stems Plus Cache.noindex')
        self.meta=self.root/'metadata';self.meta.mkdir();(self.meta/'test.manifest').write_bytes(manifest(self.source))

    def audit(self,**kwargs):
        return audit_assets({},[str(p) for p in (self.cache,self.meta,self.audio)],lambda *_:None,inspect=True,**kwargs)

    def preparation(self,rows):return next(r for r in rows if r['section']=='stems_preparation')

    def test_zip_provider_cache_has_folder_parity_and_distinct_identity(self):
        archive=self.root/'cache.zip'
        with zipfile.ZipFile(archive,'w') as z:
            for path in self.cache.rglob('*'):
                if path.is_file():z.write(path,'RB Stems Plus Cache.noindex/'+path.relative_to(self.cache).as_posix())
        summary,rows=audit_assets({},[str(archive),str(self.meta),str(self.audio)],lambda *_:None,inspect=True)
        prep=self.preparation(rows);self.assertEqual(prep['cache_state'],'consistent');self.assertIn(str(archive.resolve())+'!/',prep['cache_root'])
        self.assertEqual(summary['format_inspection']['provider_cache']['chunk_sets_present'],1)
        self.assertTrue(all(not any(k.startswith('_') for k in row) for row in rows))

    def test_identical_external_location_ids_cannot_join_split_zip_caches(self):
        (self.meta/'test.manifest').write_bytes(manifest(self.source,(KEY,OTHER_KEY)))
        second=write_cache(self.root/'other-cache',(OTHER_KEY,));archives=[]
        for i,folder in enumerate((self.cache,second)):
            archive=self.root/f'cache-{i}.zip';archives.append(str(archive))
            with zipfile.ZipFile(archive,'w') as z:
                for path in folder.rglob('*'):
                    if path.is_file():z.write(path,'cache/'+path.relative_to(folder).as_posix())
        _,rows=audit_assets({},[*archives,str(self.meta),str(self.audio)],lambda *_:None,inspect=True)
        prep=[r for r in rows if r['section']=='stems_preparation']
        self.assertEqual(len(prep),2);self.assertTrue(all(r['cache_state']=='incomplete' for r in prep))

    def test_descriptor_disagreement_is_incomplete(self):
        from test_stems_followup import cache_desc
        (self.cache/MODEL/KEY[:2]/(KEY+'.desc')).write_bytes(cache_desc(frames=2))
        self.assertEqual(self.preparation(self.audit()[1])['cache_state'],'incomplete')

    def test_expired_retention_does_not_make_complete_audio_stale(self):
        (self.meta/'test.kept').write_bytes(f'rbstemsplus-kept 1\nuntil 1\n{MODEL} {KEY}\n'.encode())
        _,rows=self.audit();self.assertEqual(self.preparation(rows)['cache_state'],'consistent')
        retained=next(r for r in rows if r.get('format')=='rbstems_kept');self.assertEqual(retained['retention_status'],'expired')
        chunk=next(r for r in rows if r['section']=='stems_cache_chunk');self.assertEqual(chunk['retention_status'],'expired')

    def test_missing_marker_empty_keys_and_duplicate_sources_are_inconclusive(self):
        (self.cache/'.rbstemsplus-cache').unlink()
        self.assertEqual(self.preparation(self.audit()[1])['cache_state'],'unknown')
        write_cache(self.cache)
        (self.meta/'test.manifest').write_bytes(manifest(self.source,()))
        self.assertEqual(self.preparation(self.audit()[1])['cache_state'],'unknown')
        raw=manifest(self.source);(self.meta/'test.manifest').write_bytes(raw+raw[raw.index(b'file '):])
        self.assertEqual(self.preparation(self.audit()[1])['cache_state'],'unknown')

    def test_same_size_and_mtime_edit_is_only_a_metadata_match(self):
        original=self.source.stat();self.source.write_bytes(b'x'*original.st_size)
        os.utime(self.source,ns=(original.st_atime_ns,original.st_mtime_ns))
        prep=self.preparation(self.audit()[1]);self.assertEqual(prep['source_association'],'metadata_match')
        self.assertIsNone(prep['native_stems_readiness']);self.assertIn('audio identity',prep['detail'])

    def test_source_change_during_audit_aborts_publication(self):
        real_stamp=source_stamp;calls=[]
        def changing(path):
            calls.append(path)
            if len(calls)==2:path.write_bytes(b'changed during check')
            return real_stamp(path)
        with patch('stems_cache.source_stamp',side_effect=changing):
            with self.assertRaisesRegex(ValueError,'changed'):self.audit()

    def test_renamed_source_and_temporary_cache_output_do_not_establish_readiness(self):
        self.source.rename(self.source.with_name('renamed.wav'))
        summary,rows=self.audit();prep=self.preparation(rows)
        self.assertEqual(prep['cache_state'],'unknown');self.assertEqual(prep['source_stamp_status'],'unavailable')
        temporary=self.cache/MODEL/KEY[:2]/(KEY+'.flac.tmp');temporary.write_bytes(b'partial write')
        _,rows=self.audit();partial=next(r for r in rows if r.get('format')=='rbstems_partial')
        self.assertEqual(partial['cache_state'],'incomplete');self.assertIsNone(partial['native_stems_readiness'])

    def test_explicit_selected_root_alias_is_allowed_but_not_a_manifest_only_alias(self):
        alias=self.root/'selected-root-alias'
        try:alias.symlink_to(self.audio,target_is_directory=True)
        except OSError:self.skipTest('Directory symlinks unavailable')
        (self.meta/'test.manifest').write_bytes(manifest(alias/self.source.name))
        _,rows=audit_assets({},list(map(str,(self.cache,self.meta,alias))),lambda *_:None,inspect=True)
        self.assertEqual(self.preparation(rows)['cache_state'],'consistent')
        # Merely mentioning the same alias in a manifest grants no extra scope.
        self.assertEqual(self.preparation(self.audit()[1])['source_stamp_status'],'not_in_scope')

    def test_metadata_budget_and_expired_deadline_do_not_prove_completeness(self):
        for budget in (3,16,64):
            summary,rows=self.audit(max_inspect_bytes=budget)
            self.assertLessEqual(summary['format_inspection']['bytes_inspected'],budget)
            self.assertEqual(summary['format_inspection']['corrupt'],0)
            self.assertEqual(summary['format_inspection']['provider_cache']['manifest_associations_consistent'],0)
            self.assertFalse(any(r.get('cache_state')=='consistent' for r in rows))
        rows,summary=provider_report([],[],context(),lambda *_:None,time.monotonic()-1)
        self.assertEqual(rows,[]);self.assertEqual(summary['manifest_associations_consistent'],0)

    def test_provider_inspection_is_cooperatively_cancellable(self):
        def stop(*_):raise OperationCancelled('Synthetic cancellation')
        with self.assertRaises(OperationCancelled):provider_report([{}],[],context(),stop,time.monotonic()+1)

    def test_unread_chunk_metadata_is_unknown_not_an_absent_chunk(self):
        budget=(self.meta/'test.manifest').stat().st_size+(self.cache/'.rbstemsplus-cache').stat().st_size
        summary,rows=audit_assets({},list(map(str,(self.meta,self.cache,self.audio))),lambda *_:None,
                                 inspect=True,max_inspect_bytes=budget)
        self.assertEqual(self.preparation(rows)['cache_state'],'unknown')
        self.assertEqual(summary['format_inspection']['provider_cache']['manifest_associations_incomplete'],0)

    def test_native_target_does_not_claim_third_party_profile_compatibility(self):
        self.assertEqual(cache_profile(context({'target':'native','quality':'speed'})),'unknown')
        self.assertEqual(cache_profile(context({'target':'rbstemsplus','platform':'windows'})),'profile_mismatch')
        self.assertEqual(cache_profile(context({'target':'rbstemsplus','architecture':'x86_64'})),'unverified_version')

    def test_unavailable_cache_scope_and_reconnect_are_distinct_from_missing_chunks(self):
        detached=self.cache.with_name('detached-cache');self.cache.rename(detached)
        paths=list(map(str,(self.cache,self.meta,self.audio)))
        summary,rows=stems_report({},paths,{},lambda *_:None)
        self.assertEqual(summary['unavailable_scopes'],1)
        self.assertEqual(self.preparation(rows)['cache_state'],'unknown')
        self.assertTrue(any(r.get('cache_state')=='unavailable' for r in rows))
        detached.rename(self.cache)
        summary,rows=stems_report({},paths,{},lambda *_:None)
        self.assertEqual(summary['unavailable_scopes'],0);self.assertEqual(self.preparation(rows)['cache_state'],'consistent')

    def test_empty_scopes_and_relative_scope_validation(self):
        empty=self.root/'empty';empty.mkdir()
        summary,_=stems_report({},[str(empty)],{},lambda *_:None)
        self.assertEqual(summary['format_inspection']['files'],0)
        summary,rows=stems_report({},[str(self.root/'disconnected')],{},lambda *_:None)
        self.assertEqual(summary['unavailable_scopes'],1);self.assertEqual(rows[0]['cache_state'],'unavailable')
        self.assertIsNone(summary['stems']['prepared_tracks'])
        for paths in (['relative/cache'],[str(empty)]*21,[42]):
            with self.assertRaises(ValueError):stems_report({},paths,{},lambda *_:None)


class SourceEvidenceTests(unittest.TestCase):
    def test_service_identifiers_are_private_and_capture_presence_is_explicit(self):
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.execute('CREATE TABLE djmdContent(ID TEXT,Title TEXT,ServiceID TEXT,FolderPath TEXT)')
        db.execute('INSERT INTO djmdContent VALUES (?,?,?,?)',('1','Invented','spotify','/provider/cache.mp3'))
        columns={'djmdContent':{'ID','Title','ServiceID','FolderPath'}}
        captured=capture_database(db,columns);evidence=captured['tracks'][0]['source_evidence']
        self.assertTrue(evidence['service_id_captured']);self.assertEqual(evidence['service_id'],'spotify')
        summary,rows=stems_report(captured,[],{'enabled':'enabled','mode':'performance'},lambda *_:None)
        self.assertEqual(summary['stems_eligibility']['blocked'],1);self.assertEqual(rows[0]['source_provider'],'spotify')
        public=json.dumps(payload(captured,'Synthetic'))
        self.assertNotIn('source_evidence',public);self.assertNotIn('service_id',public)
        without=capture_database(db,{'djmdContent':{'ID','Title','FolderPath'}})
        self.assertFalse(without['tracks'][0]['source_evidence']['service_id_captured'])

    def test_catalog_evidence_and_source_only_audit_preserve_snapshot(self):
        catalog=SimpleNamespace(metadata={},tracks={'one':{'track_id':'one','title':'Invented','service_id':42}},cue_summary=lambda _:dict(other=0,auto=0))
        captured=capture_catalog(catalog);before=deepcopy(captured)
        summary,rows=stems_report(captured,[],{},lambda *_:None)
        self.assertEqual(summary['stems_eligibility']['unknown'],1);self.assertIsNone(summary['stems']['prepared_tracks'])
        self.assertIn('Unmapped',rows[0]['provider_basis']);self.assertEqual(captured,before)


class ApiTests(unittest.TestCase):
    def setUp(self):
        import app as application
        self.application=application;tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        for name,value in [('DATA',self.root),('sessions',{}),('active',None)]:
            p=patch.object(application,name,value);p.start();self.addCleanup(p.stop)
        self.store=Store(self.root/'workbench-sidecar.sqlite3')
        source={'scope_key':'synthetic:stems','capabilities':{},'tracks':[
            {'id':str(i),'title':f'Synthetic {i:03}','current_path':'/synthetic/track.wav' if i%2 else 'spotify:track:synthetic'} for i in range(125)]}
        self.sid=self.store.save_snapshot(source,'Synthetic STEMS')['id'];self.captured=self.store.snapshot(self.sid)
        self.client=workspace_client(application);self.headers={'X-Workbench-Token':application.TOKEN}

    def run_report(self,**extra):
        result={}
        def launch(work,*_):result.update(work(lambda *_:None));return 'synthetic-stems-job'
        with patch.object(self.application,'launch',side_effect=launch):
            response=self.client.post('/api/lab/check',headers=self.headers,json={
                'kind':'stems','snapshot':self.sid,'profile':{'enabled':'enabled','mode':'performance'},**extra})
        self.assertEqual(response.status_code,200,response.data);return result['id']

    def test_source_only_api_save_reload_and_global_filters_download(self):
        identity=self.run_report();endpoint='/api/lab/reports/'+identity
        filters={'asset_family':'source_eligibility','provider':'rekordbox','eligibility':'blocked','source_provider':'spotify'}
        first=self.client.get(endpoint,query_string=filters).json
        second=self.client.get(endpoint,query_string={**filters,'offset':50}).json
        self.assertEqual(first['total'],63);self.assertEqual(len(first['rows']),50);self.assertEqual(len(second['rows']),13)
        downloaded=self.client.get(endpoint+'/download',query_string={**filters,'sort':'title','direction':'desc'})
        self.assertEqual(downloaded.status_code,200);self.assertIn('attachment',downloaded.headers['Content-Disposition'])
        self.assertEqual(len(downloaded.json['rows']),63);self.assertEqual(downloaded.json['rows'][0]['title'],'Synthetic 124')
        self.assertTrue(all(r['eligibility']=='blocked' and r['source_provider']=='spotify' for r in downloaded.json['rows']))
        self.assertEqual(first['filter_facets']['eligibility'],[{'value':'blocked','count':63},{'value':'candidate','count':62}])
        restored=Store(self.root/'workbench-sidecar.sqlite3').report(identity,all_rows=True)
        self.assertEqual(restored['total'],125);self.assertEqual(self.store.snapshot(self.sid),self.captured)

    def test_profile_and_filter_validation_rejects_untrusted_values(self):
        with patch.object(self.application,'launch',side_effect=AssertionError('Invalid profile launched')):
            response=self.client.post('/api/lab/check',headers=self.headers,json={
                'kind':'stems','snapshot':self.sid,'profile':{'model_sha256':'short'}})
        self.assertEqual(response.status_code,400)
        identity=self.run_report();endpoint='/api/lab/reports/'+identity
        for field in ('asset_family','provider','cache_state','eligibility','source_provider'):
            self.assertEqual(self.client.get(endpoint,query_string={field:"' OR 1=1"}).status_code,400)
        self.assertEqual(self.client.post('/api/lab/check',json={'kind':'stems','snapshot':self.sid}).status_code,403)

    def test_combined_cache_filters_and_legacy_report_facets(self):
        rows=[{'section':'stems_preparation','title':'Invented','detail':'metadata only','asset_family':'preparation_manifest',
               'provider':'rbstemsplus','cache_state':'stale','severity':'review','validation':'not_checked'}]
        identity=self.store.save_report('stems',[],{},rows+[{**rows[0],'provider':'legacy-unmapped'}])['id']
        response=self.client.get('/api/lab/reports/'+identity+'/download',query_string={
            'asset_family':'preparation_manifest','provider':'rbstemsplus','cache_state':'stale','severity':'review','validation':'not_checked','q':'Invented'})
        self.assertEqual(response.status_code,200);self.assertEqual(response.json['total'],1)
        self.assertEqual(response.json['filter_facets']['provider'],[{'value':'rbstemsplus','count':1}])


if __name__=='__main__':unittest.main()

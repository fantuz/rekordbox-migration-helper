from test_support import workspace_client
"""No current collection means no new provider batch, even through the API."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import app
from enrichment_context import context, prepare, require_snapshot
from musicbrainz_pilot import create_batch
from workbench_store import Store


class CurrentLibraryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.store=Store(self.root/'workbench-sidecar.sqlite3')
        self.zip=self.root/'input.zip';self.zip.write_bytes(b'untouched')
        self.xml=self.root/'input.xml';self.xml.write_bytes(b'untouched')
        self.metadata={'zip_path':str(self.zip),'xml_path':str(self.xml)}
        self.tracks=[{'id':'one','title':'Test','artist':'DJ','genre':'House','duration':180}]
        self.payload={'schema':1,'scope_key':'session:current','tracks':self.tracks,'playlists':[],'capabilities':{}}
        self.session={'id':'current','name':'Current library','metadata':self.metadata,'catalog':SimpleNamespace(tracks={'one':self.tracks[0]})}
        for p in (patch.object(app,'DATA',self.root),patch.object(app,'sessions',{'current':self.session}),patch.object(app,'active','current')):
            p.start();self.addCleanup(p.stop)
        self.sid=self.store.save_snapshot(self.payload,'Current')['id']
        self.store.set_setting('musicbrainz_enabled',True)
        self.client=workspace_client(app);self.headers={'X-Workbench-Token':app.TOKEN}

    def test_loaded_pair_is_default_and_metadata_preparation_stays_local(self):
        info=self.client.get('/api/lab/musicbrainz/context').json
        self.assertEqual(info['sources'][0]['id'],'session:current')
        with patch('enrichment_context.capture_workspace',return_value=self.payload),patch('lab_routes.MusicBrainzClient') as provider:
            result=prepare(app,self.store,'session:current',lambda *_:None)
        provider.assert_not_called();self.assertEqual(result['tracks'],1)
        self.assertEqual(self.zip.read_bytes(),b'untouched');self.assertEqual(self.xml.read_bytes(),b'untouched')
        def launch(work,*args):work(lambda *_:None);return 'synthetic-preview'
        with patch.object(app,'launch',side_effect=launch):
            preview=self.client.post('/api/lab/musicbrainz/preview',json={'snapshot':result['id'],'include_unavailable':True},headers=self.headers)
        self.assertEqual(preview.status_code,200,preview.json)

    def test_playable_only_default_opt_in_and_worker_recheck(self):
        from musicbrainz_pilot import run_batch
        from test_media_recovery import tagged_wave
        audio=self.root/'Play.wav';tagged_wave(audio)
        tracks=[{**self.tracks[0],'id':'play','title':'Playable test','current_path':str(audio)},
                {**self.tracks[0],'id':'missing','title':'Missing test','current_path':str(self.root/'Absent.wav')},
                {**self.tracks[0],'id':'unknown','title':'Unknown test','current_path':None}]
        sid=self.store.save_snapshot({**self.payload,'tracks':tracks},'Availability')['id']
        result={}
        def launch(work,*args):result.clear();result.update(work(lambda *_:None));return 'synthetic-preview'
        with patch.object(app,'launch',side_effect=launch):
            response=self.client.post('/api/lab/musicbrainz/preview',json={'snapshot':sid},headers=self.headers)
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual([t['id'] for t in result['sample']],['play'])
            self.assertEqual(result['summary']['excluded_unplayable'],2)
            identity=result['id'];audio.unlink()
            provider=SimpleNamespace(requests=0,cache_hits=0,get=lambda *_:self.fail('Unavailable audio must not query the provider'))
            done=run_batch(self.store,identity,provider,lambda *_:None)
            self.assertEqual(done['summary']['skipped_unplayable'],1)
            self.assertEqual(done['status'],'complete_with_skips')
            response=self.client.post('/api/lab/musicbrainz/preview',json={'snapshot':sid,'include_unavailable':True},headers=self.headers)
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual(len(result['sample']),3)
            self.assertFalse(result['summary']['playable_only'])
            self.assertEqual(self.client.post('/api/lab/musicbrainz/preview',json={'snapshot':sid,'include_unavailable':'yes'},headers=self.headers).status_code,400)

    def test_detached_past_samples_remain_reviewable_but_cannot_start(self):
        batch=create_batch(self.store,self.store.snapshot(self.sid))
        for missing in ('session','input'):
            with self.subTest(missing=missing):
                if missing=='session':app.active=None
                else:app.active='current';self.xml.unlink()
                self.assertEqual(self.client.get('/api/lab/musicbrainz/context').json['sources'],[])
                with patch('lab_routes.MusicBrainzClient') as provider:
                    self.assertEqual(self.client.post('/api/lab/musicbrainz/preview',json={'snapshot':self.sid},headers=self.headers).status_code,400)
                    self.assertEqual(self.client.post('/api/lab/musicbrainz/'+batch['id']+'/start',json={'query_consent':True},headers=self.headers).status_code,400)
                provider.assert_not_called()
                self.assertEqual(self.client.get('/api/lab/musicbrainz/'+batch['id']).status_code,200)

    def test_wrong_collection_and_empty_metadata_are_rejected(self):
        for payload in ({**self.payload,'scope_key':'session:other'},{**self.payload,'tracks':[]}):
            with self.assertRaises(ValueError):require_snapshot(app,payload)

    def test_live_source_is_recaptured_and_disconnected_source_is_blocked(self):
        source=self.root/'rekordbox';source.mkdir();(source/'master.db').write_bytes(b'synthetic')
        identity='a'*32;folder=self.root/'analyzers'/identity;folder.mkdir(parents=True)
        (folder/'report.json').write_text(json.dumps({'source':str(source),'created':'2026-11-15'}))
        def recapture(path,output,progress,**kwargs):
            self.assertEqual(path,str(source));output.mkdir(parents=True)
            (output/'report.json').write_text(json.dumps({'source':path,'created':'2026-11-15'}))
            (output/'comparison.json').write_text(json.dumps(self.payload))
            return {'read_status':'checked'}
        with patch('analyzer.analyze_folder',side_effect=recapture) as capture:
            result=prepare(app,self.store,'capture:'+identity,lambda *_:None)
        capture.assert_called_once();self.assertNotEqual(result['source'],'capture:'+identity)
        require_snapshot(app,self.store.snapshot(result['id']))
        (source/'master.db').unlink()
        with self.assertRaises(ValueError):require_snapshot(app,self.store.snapshot(result['id']))


if __name__=='__main__':unittest.main()

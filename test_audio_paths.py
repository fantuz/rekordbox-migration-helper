"""Mounted Windows audio is resolved locally without rewriting source metadata."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import io
import json
import os
import unittest

import app
from audio_paths import inherit, mappings_for, mapped_path, recorded, signature, validate
from enrichment_context import playable_collection
from file_status_cache import inspect
from musicbrainz_pilot import create_batch, run_batch
from track_playback import available_audio, inspect_audio
from workbench_store import Store


class MountedAudioTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.volume=self.root/'Mounted NTFS';self.volume.mkdir()
        music=self.volume/'Music 日本';music.mkdir()
        self.audio=music/'Café.wav';self.audio.write_bytes(b'RIFF synthetic availability fixture')
        self.track={'id':'1','title':'Café','artist':'DJ','genre':'House','duration':180,
                    'current_path':'D:/MUSIC 日本/CAFÉ.wav','xml_location':'file://localhost/D:/Music%20%E6%97%A5%E6%9C%AC/Caf%C3%A9.wav'}
        self.maps=validate([{'recorded_root':'D:/','local_root':str(self.volume)}])
        self.store=Store(self.root/'workbench-sidecar.sqlite3')
        self.snapshot={'scope_key':'capture:'+'a'*32,'tracks':[self.track],'playlists':[]}
        self.sid=self.store.save_snapshot(self.snapshot,'Mounted collection')['id']
        self.snapshot=self.store.snapshot(self.sid)
        self.store.set_setting('audio_paths:'+self.snapshot['scope_key'],self.maps)

    def test_windows_drive_uri_case_unicode_and_cache_use_the_same_mapping(self):
        original=deepcopy(self.track)
        self.assertTrue(mapped_path(self.track['xml_location'],self.maps).samefile(self.audio))
        self.assertEqual(inspect_audio(self.track,self.maps)[0],'playable')
        self.assertTrue(available_audio(self.track,self.maps).samefile(self.audio))
        owner=SimpleNamespace(DATA=self.root)
        first,hits=inspect(owner,{'1':self.track},mappings=self.maps)
        self.assertEqual(first,{'1':'playable'});self.assertFalse(hits['1'])
        self.assertTrue(inspect(owner,{'1':self.track},mappings=self.maps)[1]['1'])
        changed=[{**self.maps[0],'inode':-1}]
        self.assertEqual(inspect(owner,{'1':self.track},mappings=changed)[0]['1'],'unverified')
        self.assertEqual(self.track,original)

    def test_traversal_network_paths_prefix_boundary_and_replaced_mount_are_rejected(self):
        for path in ('D:/Music/../secret.wav','file://other/D:/Music/a.wav','//server/share/a.wav',
                     'file://localhost/D:/Music/%2e%2e/secret.wav','D:/Music/a.wav:stream'):
            self.assertIsNone(mapped_path(path,self.maps),path)
        specific=validate([{'recorded_root':'D:/Music','local_root':str(self.volume)}])
        self.assertIsNone(mapped_path('D:/Musical/a.wav',specific))
        changed=[{**self.maps[0],'device':-1}]
        self.assertIsNone(mapped_path(self.track['current_path'],changed))
        outside=self.root/'Outside';outside.mkdir();(outside/'outside.wav').write_bytes(b'a')
        try:(self.volume/'link').symlink_to(outside,target_is_directory=True)
        except OSError:return
        self.assertIsNone(mapped_path('D:/link/outside.wav',self.maps))

    @unittest.skipIf(os.name=='nt','Case-sensitive directory ambiguity is a Linux/macOS fixture')
    def test_ambiguous_case_matches_are_held(self):
        (self.volume/'one.wav').write_bytes(b'a');(self.volume/'ONE.WAV').write_bytes(b'b')
        if len([p for p in self.volume.iterdir() if p.name.casefold()=='one.wav'])<2:self.skipTest('Case-insensitive volume')
        self.assertIsNone(mapped_path('D:/One.wav',self.maps))

    def test_musicbrainz_preview_worker_and_recapture_keep_mapping_scope(self):
        eligible,excluded=playable_collection(self.snapshot,False,lambda *_:None,self.maps)
        self.assertEqual(excluded,0);self.assertEqual(len(eligible['tracks']),1)
        eligible['audio_mapping_revision']=signature(self.maps)
        batch=create_batch(self.store,eligible)
        calls=[]
        def get(*args):calls.append(args);return {'recordings':[]}
        client=SimpleNamespace(requests=0,cache_hits=0,get=get)
        result=run_batch(self.store,batch['id'],client,lambda *_:None)
        self.assertEqual(result['status'],'complete');self.assertTrue(calls)
        inherit(self.store,self.snapshot['scope_key'],'capture:'+'b'*32)
        self.assertEqual(mappings_for(self.store,{'scope_key':'capture:'+'b'*32}),self.maps)
        self.assertEqual(self.store.snapshot(self.sid)['tracks'][0],self.track)

    def test_api_preview_save_playback_and_invalidation(self):
        headers={'X-Workbench-Token':app.TOKEN};source='snapshot:'+self.sid
        with patch.object(app,'DATA',self.root),patch.object(app,'tasks',{}):
            client=app.app.test_client()
            info=client.get('/api/audio-paths',query_string={'source':source}).json
            response=client.post('/api/audio-paths/preview',json={'source':source,'mappings':self.maps},headers=headers)
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual(response.json['examples'][0]['status'],'playable')
            with patch('track_playback.open_audio') as launch:
                response=client.post('/api/playback/open',json={'snapshot':self.sid,'track_id':'1'},headers=headers)
                self.assertEqual(response.status_code,200,response.json);launch.assert_called_once();self.assertTrue(launch.call_args.args[0].samefile(self.audio))
            with self.store.connection() as db:
                db.execute('INSERT INTO file_health_scans VALUES (?,?,?,?,?)',(source,1,1,1,'complete'))
                db.execute('INSERT INTO file_health_records VALUES (?,?,?,?,?,?,?,?)',(source,'1','Title','DJ','House','playable',1,'title'))
            response=client.post('/api/audio-paths',json={'source':source,'revision':info['revision'],'mappings':[]},headers=headers)
            self.assertEqual(response.status_code,200,response.json)
            with self.store.connection() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM file_health_records').fetchone()[0],0)
            self.assertEqual(client.post('/api/audio-paths',json={'source':source,'revision':info['revision'],'mappings':[]},headers=headers).status_code,409)

if __name__=='__main__':unittest.main()

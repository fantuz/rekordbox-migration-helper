"""Playback boundaries are tested with synthetic files and mocked OS dispatch."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch,MagicMock
from types import SimpleNamespace
import os
import subprocess

from track_playback import available_audio,recorded_path,open_audio,inspect_audio
from file_status_cache import inspect as cached_inspect
from workbench_store import Store


class PlaybackTests(TestCase):
    def test_only_recorded_existing_audio_is_resolved_without_writes(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);audio=root/'Café & remix.mp3';audio.write_bytes(b'synthetic')
            original={'current_path':str(root/'missing.mp3'),'original_path':audio.as_uri()}
            self.assertEqual(available_audio(original),audio.resolve())
            self.assertEqual(audio.read_bytes(),b'synthetic')
            for value in ['https://example.com/test.mp3','file://remote/music/a.mp3','file://[broken/a.mp3',str(root/'code.py'),'../track.mp3',str(audio)+'\0']:
                self.assertIsNone(recorded_path(value))
            self.assertIsNone(available_audio({'current_path':str(root/'missing.mp3')}))
            executable=root/'script.py';executable.write_text('raise Exception')
            link=root/'alias.mp3'
            try:link.symlink_to(executable)
            except OSError:return
            self.assertIsNone(available_audio({'current_path':str(link)}))

    def test_four_file_states_and_recorded_fallbacks(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            audio=root/'present.mp3'
            audio.write_bytes(b'synthetic')
            missing=root/'absent.mp3'
            self.assertEqual(inspect_audio({'current_path':str(audio)})[0],'playable')
            self.assertEqual(inspect_audio({'current_path':str(missing)})[0],'missing')
            self.assertEqual(inspect_audio({'current_path':str(root/'not-mounted'/'song.mp3')})[0],'unverified')
            self.assertEqual(inspect_audio({'current_path':'C:\\\\elsewhere\\\\song.mp3'})[0],'unverified' if os.name!='nt' else 'unverified')
            self.assertEqual(inspect_audio({})[0],'unverified')
            self.assertEqual(inspect_audio({'current_path':str(missing),'original_path':str(audio)})[0],'playable')
            # A permissions error takes precedence over a missing alternative.
            original_access=os.access
            with patch('track_playback.os.access',side_effect=lambda p,mode: False if str(p)==str(audio.resolve()) else original_access(p,mode)):
                self.assertEqual(inspect_audio({'current_path':str(audio)})[0],'inaccessible')

    def test_persistent_cache_freshness_refresh_and_path_privacy(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            audio=root/'private - artist.mp3';audio.write_bytes(b'synthetic')
            owner=SimpleNamespace(DATA=root)
            tracks={'one':{'current_path':str(audio)},'two':{'current_path':str(audio)}}
            states,hits=cached_inspect(owner,tracks)
            self.assertEqual(states,{'one':'playable','two':'playable'})
            self.assertEqual(hits,{'one':False,'two':False})
            states,hits=cached_inspect(owner,tracks)
            self.assertTrue(all(hits.values()))
            with Store(root/'workbench-sidecar.sqlite3').connection() as db:
                rows=db.execute('SELECT key,status,checked_at FROM file_status_cache').fetchall()
                self.assertEqual(len(rows),1)
                self.assertNotIn(str(audio),str(tuple(rows[0])))
            audio.unlink()
            self.assertEqual(cached_inspect(owner,tracks)[0]['one'],'playable')  # cached, advisory only
            self.assertEqual(cached_inspect(owner,tracks,refresh=True)[0]['one'],'missing')
            with Store(root/'workbench-sidecar.sqlite3').connection() as db:
                db.execute('UPDATE file_status_cache SET checked_at=0')
            self.assertEqual(cached_inspect(owner,tracks)[0]['one'],'missing')
            self.assertEqual(cached_inspect(owner,{'none':{}})[0]['none'],'unverified')

    def test_os_dispatch_uses_argument_array_and_reaps_children(self):
        path=Path('/music/$(not a command); remix.mp3')
        for platform,command in [('darwin',['/usr/bin/open',str(path)]),('linux',['xdg-open',str(path)])]:
            with patch('track_playback.sys.platform',platform),patch('track_playback.subprocess.Popen') as launch:
                launch.return_value.wait.return_value=0
                open_audio(path);self.assertEqual(launch.call_args.args[0],command)
                self.assertNotIn('shell',launch.call_args.kwargs)
        with patch('track_playback.sys.platform','win32'),patch('track_playback.os.startfile',create=True) as launch:
            open_audio(path);launch.assert_called_once_with(str(path),'open')
        with patch('track_playback.sys.platform','linux'),patch('track_playback.subprocess.Popen') as launch:
            launch.return_value.wait.return_value=1
            with self.assertRaises(ValueError):open_audio(path)

    def test_api_uses_snapshot_identity_and_requires_local_token(self):
        import app
        with TemporaryDirectory() as temp,patch.object(app,'DATA',Path(temp)):
            audio=Path(temp)/'synthetic.mp3';audio.write_bytes(b'fixture')
            saved=Store(Path(temp)/'workbench-sidecar.sqlite3')
            sid=saved.save_snapshot({'scope_key':'synthetic','tracks':[{'id':'a','current_path':str(audio)}]},'Synthetic')['id']
            before=saved.snapshot(sid);client=app.app.test_client();headers={'X-Workbench-Token':app.TOKEN}
            data={'snapshot':sid,'track_id':'a'}
            self.assertEqual(client.post('/api/playback/open',json=data).status_code,403)
            with patch('track_playback.open_audio') as launch:
                self.assertEqual(client.post('/api/playback/open',json=data,headers=headers,environ_overrides={'REMOTE_ADDR':'192.0.2.1'}).status_code,400)
                self.assertEqual(client.post('/api/playback/open',json={**data,'track_id':'missing','path':str(audio)},headers=headers).status_code,400)
                launch.assert_not_called()
                result=client.post('/api/playback/open',json=data,headers=headers)
                self.assertEqual(result.status_code,200,result.json);launch.assert_called_once_with(audio.resolve())
            evidence=client.post('/api/playback/availability',json={'snapshot':sid,'track_ids':['a','missing']},headers=headers).json
            self.assertEqual(evidence['tracks'],{'a':True,'missing':False})
            self.assertEqual(evidence['statuses'],{'a':'playable','missing':'unverified'})
            audio.unlink()
            with patch('track_playback.open_audio') as launch:
                self.assertEqual(client.post('/api/playback/open',json=data,headers=headers).status_code,400);launch.assert_not_called()
            self.assertEqual(saved.snapshot(sid),before)

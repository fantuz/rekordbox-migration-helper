"""Playback boundaries are tested with synthetic files and mocked OS dispatch."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch,MagicMock
import subprocess

from track_playback import available_audio,recorded_path,open_audio
from workbench_store import Store


class PlaybackTests(TestCase):
    def test_only_recorded_existing_audio_is_resolved_without_writes(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);audio=root/'Café & remix.mp3';audio.write_bytes(b'synthetic')
            original={'current_path':str(root/'missing.mp3'),'original_path':audio.as_uri()}
            self.assertEqual(available_audio(original),audio.resolve())
            self.assertEqual(audio.read_bytes(),b'synthetic')
            for value in ['https://example.com/test.mp3','file://remote/music/a.mp3',str(root/'code.py'),'../track.mp3',str(audio)+'\0']:
                self.assertIsNone(recorded_path(value))
            self.assertIsNone(available_audio({'current_path':str(root/'missing.mp3')}))
            executable=root/'script.py';executable.write_text('raise Exception')
            link=root/'alias.mp3'
            try:link.symlink_to(executable)
            except OSError:return
            self.assertIsNone(available_audio({'current_path':str(link)}))

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
            self.assertEqual(client.post('/api/playback/availability',json={'snapshot':sid,'track_ids':['a','missing']},headers=headers).json['tracks'],{'a':True,'missing':False})
            audio.unlink()
            with patch('track_playback.open_audio') as launch:
                self.assertEqual(client.post('/api/playback/open',json=data,headers=headers).status_code,400);launch.assert_not_called()
            self.assertEqual(saved.snapshot(sid),before)

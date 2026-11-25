"""Synthetic native and cross-platform cleanup evidence; never inspect an actual collection."""
import hashlib
import os
from pathlib import Path, PureWindowsPath
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cleanup_paths import PathInspector, _os_path, _stamp, _windows_music, _windows_volume


class RecordedPaths(unittest.TestCase):
    def test_windows_path_and_handle_stamps_use_the_same_creation_time(self):
        common = dict(st_dev=2, st_ino=33, st_size=11, st_mtime_ns=100, st_birthtime_ns=90)
        path = SimpleNamespace(st_ctime_ns=90, **common)
        handle = SimpleNamespace(st_ctime_ns=105, **common)
        with patch('cleanup_paths.os', SimpleNamespace(name='nt')):
            self.assertEqual(_stamp(path), _stamp(handle))

    def test_linux_census_never_probes_files_or_providers(self):
        with patch('cleanup_paths.sys.platform', 'linux'), patch('cleanup_paths.Path.home', side_effect=AssertionError), \
             patch('cleanup_paths.Path.lstat', side_effect=AssertionError), patch('cleanup_paths._open_for_hash', side_effect=AssertionError):
            inspector = PathInspector.current()
            self.assertEqual(inspector.host, 'Linux')
            self.assertFalse(inspector.can_apply)
            cases = [
                (r'C:\Users\example\Music\one.wav', 'Windows', 'C:', 'foreign'),
                ('file://localhost/E:/DJ%20Music/other.wav', 'Windows', 'E:', 'foreign'),
                (r'\\Studio\sets\track.wav', 'Windows', '//studio/sets', 'external'),
                ('file://Studio/sets/track.wav', 'Windows', '//studio/sets', 'external'),
                ('/Volumes/DJ SSD/two.wav', 'macOS', '/Volumes/DJ SSD', 'external'),
                ('/Users/example/Music/third.wav', 'macOS', '/', 'foreign'),
                ('/mnt/c/Users/example/Music/one.wav', 'Unclassified', 'Unclassified', 'unclassified'),
                ('/contents_111/audio.wav', 'Unclassified', 'Unclassified', 'cloud'),
                ('/Users/example/Music/._audio.wav', 'macOS', '/', 'sidecar'),
                (r'\\?\C:\Music\test.wav', 'Windows', 'Device namespace', 'unclassified'),
                ('file://localhost/C:/Music/test%2fwrong.wav', 'Unclassified', 'Unclassified', 'unclassified'),
                ('file://localhost/%00bad', 'Unclassified', 'Unclassified', 'unclassified'),
                ('file://localhost/C:/Music/demo%E2%80%AE.wav', 'Unclassified', 'Unclassified', 'unclassified'),
                ('smb://studio/set/a.wav', 'Unclassified', 'smb:', 'external'),
                ('https://example.test/a.wav', 'Unclassified', 'https:', 'cloud'),
            ]
            for path, system, volume, status in cases:
                with self.subTest(path=path):
                    result = inspector.inspect(path)
                    self.assertEqual((result['os'], result['volume'], result['status']), (system, volume, status))
                    self.assertEqual(inspector.digest(path, result, 64000), (None, 0))

    def test_host_scope_and_custom_cloud_roots_are_checked_before_any_probe(self):
        inspector = PathInspector('Windows', 'C:/Users/example/Music', 'C:', [9], ['c:/users/example/music/Café'])
        with patch.object(inspector, '_probe', side_effect=AssertionError):
            for path, status in [
                ('D:/Users/example/Music/track.mp3', 'external'),
                ('C:/Users/example/Music-old/track.mp3', 'outside'),
                ('C:/Users/other/Music/track.mp3', 'outside'),
                ('C:/Users/example/Music/cafe\u0301/Track.mp3', 'cloud'),
                ('C:/Users/example/Music/Team Dropbox/one.mp3', 'cloud'),
                ('C:/Users/example/Music/contents_391/data.wav', 'cloud'),
                ('C:/Users/example/Music/OneDrive - Team/temp.wav', 'cloud'),
                ('C:/Users/example/Music/local/desktop.ini', 'sidecar'),
                ('C:/Users/example/Music/path/../track.mp3', 'unclassified'),
                ('C:/Users/example/Music/clip.mp3:data.wav', 'unclassified'),
                ('C:/Users/example/Music/CON.wav', 'unclassified'),
                ('C:/Users/example/Music/FOLDER~1/music.wav', 'unclassified'),
                ('C:/Users/example/Music/Demo. /music.wav', 'unclassified'),
                ('C:/Users/example/Music/a/ANLZ0000.DAT', 'unclassified'),
            ]:
                with self.subTest(path=path):
                    self.assertEqual(inspector.inspect(path)['status'], status)
            self.assertEqual(inspector.inspect('C:/Users/example/Music/track.wav', cloud_hint=True)['status'], 'cloud')
            inspector.roots_known = False
            self.assertEqual(inspector.inspect('C:/Users/example/Music/track.wav')['status'], 'unavailable')

    def test_reachable_parent_regular_audio_or_protected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            music = root / 'Music'
            music.mkdir()
            os_name = 'Windows' if os.name == 'nt' else 'macOS'
            # A macOS temporary profile can traverse the startup and Data volumes.
            devices = {root.stat().st_dev, Path(root.anchor).stat().st_dev}
            inspector = PathInspector(os_name, _os_path(music), music.drive, devices)
            audio = music / 'sample.wav'
            # Isolate the on-disk proof from the platform-specific /Users lexical convention.
            def observe():
                result = dict(os=os_name, volume=music.drive or '/', status='unavailable', size=None, identity=None, stamp=None)
                inspector._probe(audio, result)
                return result
            self.assertEqual(observe()['status'], 'missing')
            payload = b'review-test' * 1024
            audio.write_bytes(payload)
            seen = observe()
            self.assertEqual(seen['status'], 'present')
            self.assertEqual(seen['size'], len(payload))
            with patch.object(inspector, 'inspect', side_effect=lambda raw: observe()):
                self.assertEqual(inspector.digest(str(audio), seen, len(payload) - 1), (None, 0))
                observed = []
                self.assertEqual(inspector.digest(str(audio), seen, len(payload), observed.append), (hashlib.sha256(payload).hexdigest(), len(payload)))
                self.assertEqual(observed, [len(payload)])
                # Keep identity, size and write time identical across both
                # handle samples. A change event during hashing must still count.
                with audio.open('rb') as stream:
                    first = os.fstat(stream.fileno())
                changed = SimpleNamespace(**{k: getattr(first, k) for k in dir(first) if k.startswith('st_')})
                changed.st_ctime_ns += 100
                with patch('cleanup_paths.os.fstat', side_effect=[first, changed]):
                    self.assertEqual(inspector.digest(str(audio), seen, len(payload)), (None, len(payload)))
                with self.assertRaises(InterruptedError):
                    inspector.digest(str(audio), seen, len(payload), lambda n: self._cancel())
                audio.write_bytes(payload * 2)
                self.assertEqual(inspector.digest(str(audio), seen, len(payload) * 2), (None, 0))
            audio.unlink()
            if os_name == 'macOS':
                (music / '.sample.wav.icloud').touch()
                self.assertEqual(observe()['status'], 'cloud')
                (music / '.sample.wav.icloud').unlink()
            if os.name != 'nt':
                alias = music / 'alias'
                alias.symlink_to(root)
                audio = alias / 'sample.wav'
                self.assertEqual(observe()['status'], 'unavailable')
            audio = music / 'offline' / 'absent.mp3'
            self.assertEqual(observe()['status'], 'unavailable')

    @staticmethod
    def _cancel():
        raise InterruptedError('cancelled')

    @unittest.skipUnless(sys.platform == 'win32', 'native Windows volume APIs')
    def test_windows_local_startup_drive(self):
        self.assertEqual(_windows_volume(), PureWindowsPath(os.environ['SystemRoot']).drive.upper())
        self.assertTrue(PureWindowsPath(_windows_music()).is_absolute())

    @unittest.skipUnless(sys.platform == 'darwin', 'native Darwin File Provider metadata')
    def test_macos_finderinfo_and_startup_data_volume(self):
        from cleanup_paths import _finder_alias
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            audio = root / 'regular.wav'
            audio.touch()
            self.assertFalse(_finder_alias(audio))
            self.assertIn(Path('/Users').stat().st_dev, PathInspector.current().devices)

    @unittest.skipUnless(sys.platform in ('win32', 'darwin'), 'native local Music path')
    def test_native_current_handles_an_isolated_on_disk_music_tree_and_custom_cloud_config(self):
        # Keep both the generated profile and its media on the startup filesystem.
        if os.name == 'nt':
            base = Path(tempfile.gettempdir())
            if base.drive.upper() != _windows_volume():
                base = Path(os.environ['SystemRoot']) / 'Temp'
        else:
            base = Path('/System/Volumes/Data/private/tmp')
        with tempfile.TemporaryDirectory(dir=base) as folder:
            home = Path(folder)
            music = home / 'Music'
            music.mkdir()
            custom = music / 'Archive'
            custom.mkdir()
            import json
            if os.name == 'nt':
                config = home / 'Dropbox/info.json'
            else:
                config = home / '.dropbox/info.json'
            config.parent.mkdir()
            config.write_text(json.dumps({'business': {'path': str(custom)}}), encoding='utf-8')
            env = {'APPDATA': str(home), 'LOCALAPPDATA': str(home)}
            with patch.object(Path, 'home', return_value=home), patch.dict(os.environ, env), \
                 patch('cleanup_paths._windows_music', return_value=str(home / 'Music')), \
                 patch('cleanup_paths._registered_roots', return_value=[]):
                inspector = PathInspector.current()
                self.assertTrue(inspector.can_apply)
                audio = music / 'One.wav'
                self.assertEqual(inspector.inspect(audio.as_uri())['status'], 'missing')
                self.assertEqual(inspector.inspect(str(custom / 'Online.wav'))['status'], 'cloud')
                audio.write_bytes(b'local bytes')
                # Use an old last-write timestamp as on newly imported DJ files.
                os.utime(audio, (946684800, 946684800))
                info = inspector.inspect(audio.as_uri())
                self.assertEqual(info['status'], 'present')
                self.assertEqual(inspector.digest(audio.as_uri(), info, 40), (hashlib.sha256(b'local bytes').hexdigest(), 11))
                if os.name == 'nt':
                    with patch('cleanup_paths._windows_music', return_value=str(custom)):
                        self.assertFalse(PathInspector.current().can_apply)
                config.write_text('broken', encoding='utf-8')
                inspector = PathInspector.current()
                self.assertFalse(inspector.can_apply)
                self.assertEqual(inspector.inspect(str(audio))['status'], 'unavailable')

"""Exercise POSIX startup against real, disposable virtual environments."""
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv


@unittest.skipUnless(os.name=='posix' and shutil.which('bash'),'POSIX source launcher')
class SourceBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='Source bootstrap 日本 ')
        self.root=Path(self.temporary.name).resolve()
        shutil.copyfile(Path(__file__).with_name('start.sh'),self.root/'start.sh')
        (self.root/'requirements.txt').write_text('')
        (self.root/'desktop_launcher.py').write_text(
            'import json,sys\nfrom pathlib import Path\n'
            'Path("started.json").write_text(json.dumps({"args":sys.argv[1:],"prefix":sys.prefix}))\n')
        self.environment={**os.environ,'PIP_NO_INDEX':'1','PIP_DISABLE_PIP_VERSION_CHECK':'1'}
        self.environment.pop('PYTHONHOME',None)
        self.environment.pop('PYTHONPATH',None)

    def tearDown(self):self.temporary.cleanup()

    def virtual_environment(self):
        venv.EnvBuilder(with_pip=False,symlinks=False).create(self.root/'.venv')
        (self.root/'.venv'/'keep-user-state.txt').write_text('preserve this')
        return self.root/'.venv'/'bin'/'python'

    def launch(self):
        return subprocess.run(['bash','start.sh','--no-browser','--port','9876'],cwd=self.root,
            env=self.environment,text=True,capture_output=True,timeout=90)

    def assert_started(self,result):
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        started=json.loads((self.root/'started.json').read_text())
        self.assertEqual(started['args'],['--no-browser','--port','9876'])
        self.assertEqual(Path(started['prefix']).resolve(),self.root/'.venv')

    def test_existing_python_without_pip_is_repaired_before_installation(self):
        python=self.virtual_environment()
        self.assertNotEqual(subprocess.run([str(python),'-m','pip','--version'],capture_output=True).returncode,0)
        self.assert_started(self.launch())
        self.assertEqual(subprocess.run([str(python),'-m','pip','--version'],capture_output=True).returncode,0)
        self.assertEqual((self.root/'.venv'/'keep-user-state.txt').read_text(),'preserve this')
        self.assertEqual((self.root/'.venv'/'requirements.sha256').read_text().strip(),sha256(b'').hexdigest())

    def test_matching_dependency_fingerprint_does_not_skip_missing_pip_repair(self):
        python=self.virtual_environment()
        (self.root/'.venv'/'requirements.sha256').write_text(sha256(b'').hexdigest()+'\n')
        self.assert_started(self.launch())
        self.assertEqual(subprocess.run([str(python),'-m','pip','--version'],capture_output=True).returncode,0)

    def test_missing_ensurepip_preserves_environment_and_explains_matching_debian_package(self):
        python=self.virtual_environment();python.rename(python.with_name('python-real'))
        python.write_text('#!/bin/sh\n'
            'if [ "$1" = -m ] && [ "$2" = ensurepip ]; then\n'
            '  printf "%s\\n" "No module named ensurepip" >&2\n  exit 1\nfi\n'
            'exec "$(dirname -- "$0")/python-real" "$@"\n')
        python.chmod(0o755)
        marker=self.root/'.venv'/'requirements.sha256';marker.write_text('previous fingerprint\n')
        result=self.launch()
        self.assertNotEqual(result.returncode,0)
        self.assertIn(f'python{sys.version_info.major}.{sys.version_info.minor}-venv',result.stderr)
        self.assertIn('ensurepip --upgrade',result.stderr)
        self.assertFalse((self.root/'started.json').exists())
        self.assertEqual(marker.read_text(),'previous fingerprint\n')
        self.assertEqual((self.root/'.venv'/'keep-user-state.txt').read_text(),'preserve this')

    def test_python_executable_without_venv_identity_never_runs_pip(self):
        directory=self.root/'.venv'/'bin';directory.mkdir(parents=True)
        (directory/'python').symlink_to(sys.executable)
        result=self.launch()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('does not identify this virtual environment',result.stderr)
        self.assertFalse((self.root/'started.json').exists())
        self.assertFalse((self.root/'.venv'/'requirements.sha256').exists())

    def test_versioned_supported_python_is_selected_when_default_python_is_too_old(self):
        binaries=self.root/'interpreters';binaries.mkdir()
        older=binaries/'python3';older.write_text('#!/bin/sh\nexit 1\n');older.chmod(0o755)
        supported=binaries/f'python{sys.version_info.major}.{sys.version_info.minor}'
        supported.symlink_to(sys.executable)
        self.environment['PATH']=str(binaries)+os.pathsep+self.environment.get('PATH','')
        self.assert_started(self.launch())


if __name__=='__main__':unittest.main()

"""Build a portable Linux x86-64 folder in the pinned manylinux container."""
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import sysconfig
import tarfile
from release_tools import build_version, archive_name

ROOT=Path(__file__).resolve().parents[1]


def pack(folder, output, version):
    output.mkdir(parents=True, exist_ok=True)
    destination=output/archive_name(version, 'linux-x86_64')
    # PyInstaller's shared-library symlinks and executable permissions are required.
    with tarfile.open(destination, 'w:gz', dereference=False) as archive:
        archive.add(folder, arcname='Library Workbench')
    destination.with_suffix('.gz.sha256').write_text(
        sha256(destination.read_bytes()).hexdigest()+'  '+destination.name+'\n', encoding='utf-8')
    return destination


def main():
    if sys.platform!='linux' or platform.machine()!='x86_64':
        raise RuntimeError('Build on Linux x86-64 in the pinned manylinux_2_28 container')
    if platform.libc_ver()!=('glibc','2.28'):
        raise RuntimeError('Use the pinned glibc 2.28 build image to preserve the portability baseline')
    version=build_version()
    build=ROOT/'.build/linux-x86_64'; build.mkdir(parents=True, exist_ok=True)
    (build/'VERSION').write_text(version+'\n', encoding='utf-8')
    command=[sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
             '--name', 'Library Workbench', '--distpath', str(build/'dist'),
             '--workpath', str(build/'work'), '--specpath', str(build),
             '--add-data', str(ROOT/'static')+':static', '--add-data', str(ROOT/'docs')+':docs',
             '--add-data', str(build/'VERSION')+':.', '--collect-all', 'markdown_it',
             '--collect-all', 'pyrekordbox', '--collect-all', 'sqlcipher3',
             '--copy-metadata', 'sqlcipher3-wheels', '--hidden-import', 'sqlcipher3.dbapi2',
             '--collect-all', 'tinytag']
    for name in ('LICENSE', 'THIRD-PARTY-NOTICES.txt', 'README.md', 'CHANGELOG.md', 'SECURITY.md', 'CONTRIBUTING.md'):
        command.extend(['--add-data', str(ROOT/name)+':.'])
    command.extend(['--add-data',str(Path(sysconfig.get_path('stdlib'))/'LICENSE.txt')+':licenses'])
    command.append(str(ROOT/'desktop_launcher.py'))
    subprocess.run(command, cwd=ROOT, check=True)
    folder=build/'dist/Library Workbench'
    validation=build/'LINUX-BUILD-VALIDATION.json'
    subprocess.run([sys.executable, str(ROOT/'packaging/smoke_desktop.py'),
                    '--linux-application', str(folder), '--report', str(validation)], cwd=ROOT, check=True)
    paths=[*ROOT.glob('*.py'), *(ROOT/'static').glob('*'), *(ROOT/'docs').glob('*'),
           *[ROOT/name for name in ('README.md', 'CHANGELOG.md', 'SECURITY.md', 'CONTRIBUTING.md')]]
    manifest={'application':'Library Workbench', 'version':version, 'platform':'linux-x86_64',
              'python':platform.python_version(), 'libc_build':platform.libc_ver(), 'minimum_glibc':'2.28',
              'build_image':os.environ.get('LIBRARY_WORKBENCH_BUILD_IMAGE'),
              'python_source':json.loads((ROOT/'.build/linux-python-source.json').read_text(encoding='utf-8')),
              'linux_runtime_test':'pending', 'commit':os.environ.get('GITHUB_SHA'),
              'rekordbox_restore':'not exercised',
              'build_runtime_validation':json.loads(validation.read_text(encoding='utf-8')),
              'dependencies':[{'name':d.metadata['Name'], 'version':d.version} for d in importlib.metadata.distributions()],
              'application_sources':{str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest()
                                     for p in paths if p.is_file() and not p.name.startswith('test_')}}
    (folder/'BUILD-MANIFEST.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (folder/'START HERE.txt').write_text(
        'LIBRARY WORKBENCH '+version+' — Linux x86-64\n\n'
        'Extract the complete TAR.GZ archive. Open the extracted Library Workbench\n'
        'folder and double-click Library Workbench. Keep _internal beside it.\n'
        'If your file manager asks, choose Run. The interface opens in your browser.\n'
        'Python and application dependencies are bundled; no installation is needed.\n\n'
        'Requires a standard desktop Linux system with glibc 2.28 or newer and a\n'
        'browser. This is not an ARM or Alpine/musl package. Some systems require\n'
        'permission to execute downloaded programs. Terminal fallback: enter the\n'
        'extracted folder and run ./"Library Workbench".\n\n'
        'Use Stop and clean up in the browser before exiting. Small reports, decisions\n'
        'and completed exports are kept in $XDG_DATA_HOME/LibraryWorkbench, or\n'
        '~/.local/share/LibraryWorkbench when XDG_DATA_HOME is not set.\n'
        'Keep a fresh untouched rekordbox backup and separate audio backup before\n'
        'transformation. This utility never modifies your source library directly.\n', encoding='utf-8')
    print(pack(folder, ROOT/'releases', version))


if __name__=='__main__':main()

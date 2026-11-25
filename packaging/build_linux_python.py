"""Build shared CPython for PyInstaller; manylinux's wheel interpreter is static."""
import argparse
from hashlib import sha256
import json
import os
import platform
import posixpath
import shutil
from pathlib import Path
import subprocess
import tarfile
import urllib.request

VERSION='3.13.18'
SOURCE_URL='https://www.python.org/ftp/python/'+VERSION+'/Python-'+VERSION+'.tar.xz'
SOURCE_SHA256='abb0102e6d4ae027509bcb82327d9dd85515b44a3ba8ad538cfc5e9847029f68'
PREFIX=Path('/opt/workbench-python')


def runtime_context():
    packages=('bzip2-devel','libffi-devel','xz-devel','openssl-devel','sqlite-devel','zlib-devel')
    return {'source_sha256':SOURCE_SHA256,'builder_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
            'version':VERSION,'architecture':platform.machine(),
            'image':os.environ.get('LIBRARY_WORKBENCH_BUILD_IMAGE'),
            'compiler':subprocess.check_output(['gcc','--version'],text=True).splitlines()[0],
            'development_packages':subprocess.check_output(
                ['rpm','-q','--qf','%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\\n',*packages],
                text=True).splitlines()}


def cache_key(context):
    return sha256(json.dumps(context, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_runtime():
    subprocess.run([str(PREFIX/'bin/python3.13'),'-c',
                    'import bz2,ctypes,hashlib,lzma,sqlite3,ssl,sys,sysconfig; '
                    'assert sys.version.split()[0]=="'+VERSION+'"; '
                    'assert sysconfig.get_config_var("Py_ENABLE_SHARED"); print(ssl.OPENSSL_VERSION)'],check=True)


def restore_runtime(cache,context):
    archive=cache/'python-runtime.tar.gz';manifest=cache/'runtime.json'
    if not archive.is_file() or not manifest.is_file():
        print('No complete shared CPython checkpoint available')
        return False
    extracting=False
    try:
        record=json.loads(manifest.read_text(encoding='utf-8'))
        if not isinstance(record,dict) or record.get('context')!=context:
            raise ValueError('runtime build context changed')
        if record.get('sha256')!=sha256(archive.read_bytes()).hexdigest():
            raise ValueError('archive checksum mismatch')
        with tarfile.open(archive) as package:
            members=package.getmembers()
            for member in members:
                name=member.name
                parts=name.split('/')
                if not name or name.startswith('/') or '\\' in name or '..' in parts or parts[0]!=PREFIX.name:
                    raise ValueError('archive member outside the runtime prefix')
                if member.issym() or member.islnk():
                    target=member.linkname
                    if not target or target.startswith('/') or '\\' in target:
                        raise ValueError('invalid archive link target')
                    resolved=posixpath.normpath(posixpath.join(posixpath.dirname(name),target) if member.issym() else target)
                    if resolved.split('/')[0]!=PREFIX.name:
                        raise ValueError('archive link outside the runtime prefix')
            if sum(m.size for m in members)>1024**3:
                raise ValueError('runtime archive exceeds the size limit')
            extracting=True
            package.extractall(PREFIX.parent,filter='data')
        validate_runtime()
        print('Restored and validated shared CPython runtime cache')
        return True
    except (OSError,ValueError,KeyError,tarfile.TarError,subprocess.CalledProcessError) as error:
        print(f'Compiling pinned CPython after checkpoint validation failed ({error})')
        if extracting and PREFIX.exists():shutil.rmtree(PREFIX)
        return False


def save_runtime(cache,context):
    cache.mkdir(parents=True,exist_ok=True);archive=cache/'python-runtime.tar.gz'
    with tarfile.open(archive,'w:gz',dereference=False) as package:package.add(PREFIX,arcname=PREFIX.name)
    (cache/'runtime.json').write_text(json.dumps({'context':context,'sha256':sha256(archive.read_bytes()).hexdigest()},indent=2),encoding='utf-8')


def main():
    root=Path(__file__).resolve().parents[1]
    build=root/'.build/linux-python';build.mkdir(parents=True,exist_ok=True)
    cache=root/'.build/runtime-cache';context=runtime_context()
    source_record={'version':VERSION,'url':SOURCE_URL,'sha256':SOURCE_SHA256,'shared_library':True}
    source_manifest=root/'.build/linux-python-source.json'
    if restore_runtime(cache,context):
        source_manifest.write_text(json.dumps(source_record,indent=2),encoding='utf-8')
        return 'restored'
    archive=build/('Python-'+VERSION+'.tar.xz')
    with urllib.request.urlopen(SOURCE_URL,timeout=90) as response,archive.open('wb') as output:
        while block:=response.read(2*1024**2):output.write(block)
    if sha256(archive.read_bytes()).hexdigest()!=SOURCE_SHA256:
        raise RuntimeError('Official CPython source checksum mismatch')
    with tarfile.open(archive) as package:package.extractall(build,filter='data')
    source=build/('Python-'+VERSION)
    env={**os.environ,'CC':'gcc','CXX':'g++'}
    # No PGO/LTO cycle: this is a build tool/runtime, not a benchmark build.
    subprocess.run(['./configure','--prefix='+str(PREFIX),'--enable-shared','--without-static-libpython',
                    '--with-ensurepip=install','LDFLAGS=-Wl,-rpath,'+str(PREFIX/'lib')],cwd=source,env=env,check=True)
    subprocess.run(['make','-j2'],cwd=source,env=env,check=True)
    subprocess.run(['make','install'],cwd=source,env=env,check=True)
    validate_runtime()
    save_runtime(cache,context)
    source_manifest.write_text(json.dumps(source_record,indent=2),encoding='utf-8')
    return 'built'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    options=parser.add_mutually_exclusive_group()
    options.add_argument('--cache-key',action='store_true',help='print a key for the installed build environment')
    options.add_argument('--status-file',type=Path,help='write restored or built on success')
    args=parser.parse_args()
    if args.cache_key:
        print(cache_key(runtime_context()))
    else:
        status=main()
        if args.status_file:args.status_file.write_text(status+'\n',encoding='utf-8')

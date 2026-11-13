"""Build shared CPython for PyInstaller; manylinux's wheel interpreter is static."""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request

VERSION='3.13.18'
SOURCE_URL='https://www.python.org/ftp/python/'+VERSION+'/Python-'+VERSION+'.tar.xz'
SOURCE_SHA256='abb0102e6d4ae027509bcb82327d9dd85515b44a3ba8ad538cfc5e9847029f68'
PREFIX=Path('/opt/workbench-python')


def main():
    root=Path(__file__).resolve().parents[1]
    build=root/'.build/linux-python';build.mkdir(parents=True,exist_ok=True)
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
    subprocess.run([str(PREFIX/'bin/python3.13'),'-c',
                    'import bz2,ctypes,hashlib,lzma,sqlite3,ssl,sysconfig; assert sysconfig.get_config_var("Py_ENABLE_SHARED"); print(ssl.OPENSSL_VERSION)'],check=True)
    (root/'.build/linux-python-source.json').write_text(json.dumps(
        {'version':VERSION,'url':SOURCE_URL,'sha256':SOURCE_SHA256,'shared_library':True},indent=2),encoding='utf-8')


if __name__=='__main__':main()

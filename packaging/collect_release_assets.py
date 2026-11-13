"""Flatten only expected archives and checksums from native CI artifact folders."""
from pathlib import Path
import argparse
import shutil
from release_tools import normalized_version


def collect(source,destination,version):
    source,destination=Path(source),Path(destination);version=normalized_version(version)
    names=['Library-Workbench-'+version+'-'+suffix for suffix in ('windows-x64-preview.zip','macos-arm64-preview.zip','macos-x86_64-preview.zip','linux-source.tar.gz')]
    names += [str(Path(n).with_suffix('.sha256')) if n.endswith('.zip') else n+'.sha256' for n in names[:]]
    found={}
    for path in source.rglob('*'):
        if path.is_file() and path.name in names:
            if path.is_symlink() or path.name in found:raise ValueError('Ambiguous release artifact: '+path.name)
            found[path.name]=path
    if set(found)!=set(names):raise ValueError('Missing release archives or checksums: '+', '.join(sorted(set(names)-set(found))))
    destination.mkdir(parents=True,exist_ok=True)
    for name,path in found.items():shutil.copyfile(path,destination/name)
    return names


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source');parser.add_argument('destination');parser.add_argument('version')
    args=parser.parse_args();collect(args.source,args.destination,args.version)

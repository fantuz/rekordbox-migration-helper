"""Release planning and artifact verification, also used by the web-run workflow."""
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-(?:alpha|beta|rc)\.(?:0|[1-9]\d*))?")
PACKAGE_FORMATS = {'windows-x64': '.zip', 'macos-x86_64': '.zip', 'macos-arm64': '.zip', 'linux-x86_64': '.tar.gz', 'linux-source': '.tar.gz'}


def normalized_version(value):
    value = str(value).strip().removeprefix("v")
    if not VERSION_PATTERN.fullmatch(value):
        raise ValueError("Use a version such as 0.4.0 or 0.4.0-rc.1")
    return value


def build_version():
    return normalized_version(os.environ.get("LIBRARY_WORKBENCH_VERSION") or (ROOT/"VERSION").read_text(encoding="utf-8"))


def release_is_preview(version, requested=False):
    return bool(requested) or '-' in normalized_version(version)


def archive_name(version, platform):
    return 'Library-Workbench-'+normalized_version(version)+'-'+platform+PACKAGE_FORMATS[platform]


def archive_names(version):
    return [archive_name(version, platform) for platform in PACKAGE_FORMATS]


def release_plan(requested, ref, default_branch="main"):
    if ref.startswith("refs/tags/"):
        tag=ref.removeprefix("refs/tags/")
        version=normalized_version(tag)
        if tag!="v"+version:
            raise ValueError("Release tags must use the canonical v<version> form")
        if requested and normalized_version(requested)!=version:
            raise ValueError("Requested version does not match the release tag")
    elif ref == "refs/heads/"+default_branch:
        version = normalized_version(requested or (ROOT/"VERSION").read_text(encoding="utf-8"))
    else:
        raise ValueError("Start releases from the default branch or its version tags; merge the reviewed changes first")
    return {"version": version, "tag": "v"+version}


def commit_history(commit, root=ROOT):
    """Read every reachable commit, including merged branches and full messages."""
    if not re.fullmatch(r'[0-9a-f]{40}',commit):raise ValueError('Use the checked release commit SHA')
    def git(*args):
        return subprocess.run(['git',*args],cwd=root,check=True,capture_output=True,
                              text=True,encoding='utf-8',timeout=30).stdout
    if git('rev-parse','--is-shallow-repository').strip()!='false':
        raise ValueError('Full commit history requires a complete checkout')
    values=git('log','--reverse','--topo-order','-z','--format=%H%x00%aI%x00%an%x00%B',commit,'--').split('\0')
    if values[-1]!='' or (len(values)-1)%4:raise ValueError('Incomplete release commit history')
    records=[dict(zip(('sha','date','author','message'),values[i:i+4])) for i in range(0,len(values)-1,4)]
    if not records or records[-1]['sha']!=commit:raise ValueError('Commit history does not end at the release source')
    return records


def full_commit_log(version,commit,history):
    header='Library Workbench '+normalized_version(version)+' — full commit log\nSource commit: '+commit+'\nCommits: '+str(len(history))+'\nOrder: oldest to newest, including merges and full messages.\n\n'
    return header+'\n'.join('commit '+r['sha']+'\nAuthor: '+r['author']+'\nDate: '+r['date']+'\n\n'+r['message'] for r in history)


def release_notes(version, commit, changelog="", history=None, previous_tag=None):
    version=normalized_version(version)
    match=re.search(r"(?m)^## "+re.escape(version)+r"(?:[ \t].*)?$",changelog)
    changes=""
    if match:
        tail=changelog[match.end():]
        changes=re.split(r"(?m)^## ",tail,maxsplit=1)[0].strip()
    intro=changes or "A local library analyzer, duplicate-review utility and offline metadata explorer."
    repository=os.environ.get('GITHUB_REPOSITORY','fantuz/rekordbox-migration-helper')
    base='https://github.com/'+repository
    asset=base+'/releases/download/v'+version+'/'
    downloads='| Platform / file | Direct download | Start here |\n| --- | --- | --- |\n'+''.join(
        '| '+label+' | [Download now]('+asset+archive_name(version,platform)+') | '+instruction+' |\n'
        for platform,label,instruction in (
            ('windows-x64','Windows x64','Extract ZIP; open **Library Workbench.exe**'),
            ('macos-x86_64','Mac Intel','Extract ZIP; open **Library Workbench.app**'),
            ('macos-arm64','Mac Apple Silicon / ARM64','Extract ZIP; open **Library Workbench.app**'),
            ('linux-x86_64','Linux x86-64 portable','Extract TAR.GZ; open **Library Workbench** (Python included)'),
            ('linux-source','Linux source','Extract TAR.GZ; run **start.sh** with Python 3.13+')))
    downloads+='| Checksums | [SHA256SUMS]('+asset+'SHA256SUMS) | Verify the five archives |\n'
    history_notes=''
    if history is not None:
        downloads+='| Complete commit history | [COMMIT-LOG.txt]('+asset+'COMMIT-LOG.txt) | All '+str(len(history))+' commits and full messages |\n'
        def subject(record):
            value=escape(record['message'].split('\n',1)[0],quote=False).replace('@','&#64;')
            return re.sub(r'([\\\[\]_*`])',r'\\\1',value)
        history_notes='\n### Full commit log\n\nAll '+str(len(history))+' commits reachable from this release, oldest first. The attached [COMMIT-LOG.txt]('+asset+'COMMIT-LOG.txt) includes author, date and complete messages.\n\n'
        if previous_tag:
            from urllib.parse import quote
            history_notes+='[Changes since '+escape(previous_tag)+']('+base+'/compare/'+quote(previous_tag,safe='')+'...v'+version+')\n\n'
        history_notes+='<details>\n<summary>Show all '+str(len(history))+' commits</summary>\n\n'
        history_notes+=''.join('- [`'+r['sha'][:7]+'`]('+base+'/commit/'+r['sha']+') '+subject(r)+'\n' for r in history)
        history_notes+='\n</details>\n'
    return ("Library Workbench "+version+"\n\n"+intro+"\n\n"
            "### Downloads\n\n"+downloads+"\n"
            "- Windows x64: extract the complete ZIP and open Library Workbench.exe. Python and dependencies are bundled.\n"
            "- macOS: choose arm64 (Apple Silicon) or x86_64 (Intel), extract and open Library Workbench.app. These applications are ad-hoc signed, not notarized.\n"
            "- Linux x86-64: extract the complete portable TAR.GZ and open Library Workbench. Requires glibc 2.28+ and a browser; Python is bundled. Tested on Ubuntu 22.04. ARM and Alpine/musl need the source version.\n"
            "- Linux source: extract the source archive and run start.sh with Python 3.13 or newer.\n\n"
            "All packages passed their native CI runtime checks and share the release source. SHA256SUMS lists the five archives.\n\n"
            "Keep an untouched rekordbox Backup Library backup before transformation. Native ZIP restore inside rekordbox remains experimental; validate in an isolated library first.\n\n"
            "Source commit: [`"+commit[:7]+"`]("+base+"/commit/"+commit+")\n"+history_notes)


def verify_assets(directory, version, commit):
    directory=Path(directory)
    version=normalized_version(version)
    # Native source digests must be established before the Linux archive is checked.
    names=archive_names(version)
    sources={}
    checksums=[]
    present={p.name for p in directory.glob("Library-Workbench-*") if p.name.endswith((".zip",".tar.gz"))}
    if present!=set(names):raise ValueError("The release must contain exactly the five expected archives")
    def validate_manifest(manifest, runtime_key):
        built_commit=manifest.get('commit') or manifest.get('windows_validation',{}).get('commit')
        if manifest.get('version')!=version or manifest.get(runtime_key)!='passed' or built_commit!=commit:
            raise ValueError('Package version, commit or runtime validation does not match this release')
        if not manifest.get('application_sources'):raise ValueError('Package has no source digests')
        for source,digest_value in manifest['application_sources'].items():
            if source in sources and sources[source]!=digest_value:raise ValueError('Package source mismatch: '+source)
            sources[source]=digest_value
    for name in names:
        path=directory/name
        if not path.is_file() or path.is_symlink():raise ValueError("Missing release artifact: "+name)
        digest=sha256(path.read_bytes()).hexdigest()
        checksum=path.with_suffix(".sha256") if name.endswith(".zip") else path.with_suffix(".gz.sha256")
        if checksum.read_text(encoding="utf-8").strip()!=digest+"  "+name:
            raise ValueError("Release checksum mismatch: "+name)
        checksums.append(digest+"  "+name)
        if name.endswith(".zip"):
            with zipfile.ZipFile(path) as archive:
                if archive.testzip() is not None:raise ValueError("Corrupt package: "+name)
                manifest_names=[n for n in archive.namelist() if n.endswith("/BUILD-MANIFEST.json")]
                if len(manifest_names)!=1:raise ValueError("Missing or ambiguous build manifest")
                manifest=json.loads(archive.read(manifest_names[0]))
                validate_manifest(manifest,'windows_runtime_test' if name.endswith('-windows-x64.zip') else 'macos_runtime_test')
        elif name.endswith('-linux-x86_64.tar.gz'):
            with tarfile.open(path) as archive:
                manifests=[m for m in archive.getmembers() if m.name.endswith('/BUILD-MANIFEST.json')]
                if len(manifests)!=1 or not manifests[0].isfile():raise ValueError('Missing or ambiguous build manifest')
                manifest=json.load(archive.extractfile(manifests[0]))
                if manifest.get('platform')!='linux-x86_64':raise ValueError('Unexpected Linux package platform')
                validate_manifest(manifest,'linux_runtime_test')
        else:
            with tarfile.open(path) as archive:
                available={}
                for member in archive.getmembers():
                    parts=Path(member.name).parts
                    relative="/".join(parts[1:])
                    hidden=any(p.startswith(".") for p in parts[1:]) and relative!=".gitattributes"
                    if not member.isfile() or not parts or parts[0]!="library-workbench" or ".." in parts or hidden:
                        raise ValueError("Unexpected source archive entry: "+member.name)
                    if relative.endswith((".db",".sqlite3",".xml",".zip")):
                        raise ValueError("Private library data is not a release input")
                    available[relative]=archive.extractfile(member).read()
                if available.get("VERSION",b"").decode().strip()!=version:raise ValueError("Source archive version mismatch")
                for source,digest_value in sources.items():
                    if source not in available or sha256(available[source]).hexdigest()!=digest_value:
                        raise ValueError("Source archive differs from packaged application: "+source)
    (directory/"SHA256SUMS").write_text("\n".join(checksums)+"\n",encoding="utf-8")
    return names

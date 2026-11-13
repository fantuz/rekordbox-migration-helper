"""Release planning and artifact verification, also used by the web-run workflow."""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-(?:alpha|beta|rc)\.(?:0|[1-9]\d*))?")


def normalized_version(value):
    value = str(value).strip().removeprefix("v")
    if not VERSION_PATTERN.fullmatch(value):
        raise ValueError("Use a version such as 0.4.0 or 0.4.0-rc.1")
    return value


def build_version():
    return normalized_version(os.environ.get("LIBRARY_WORKBENCH_VERSION") or (ROOT/"VERSION").read_text(encoding="utf-8"))


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


def release_notes(version, commit, changelog=""):
    version=normalized_version(version)
    match=re.search(r"(?m)^## "+re.escape(version)+r"(?:[ \t].*)?$",changelog)
    changes=""
    if match:
        tail=changelog[match.end():]
        changes=re.split(r"(?m)^## ",tail,maxsplit=1)[0].strip()
    intro=changes or "A local library analyzer, duplicate-review utility and offline metadata explorer."
    return ("Library Workbench "+version+"\n\n"+intro+"\n\n"
            "### Downloads\n\n"
            "- Windows x64: extract the complete ZIP and open Library Workbench.exe. Python and dependencies are bundled.\n"
            "- macOS: choose arm64 (Apple Silicon) or x86_64 (Intel), extract and open Library Workbench.app. These previews are ad-hoc signed, not notarized.\n"
            "- Linux: extract the source archive and run start.sh with Python 3.13 or newer.\n\n"
            "All packages passed their native CI runtime checks and share the release source. SHA256SUMS lists the four archives.\n\n"
            "Keep an untouched rekordbox Backup Library backup before transformation. Native ZIP restore inside rekordbox remains experimental; validate in an isolated library first.\n\n"
            "Source commit: "+commit+"\n")


def verify_assets(directory, version, commit):
    directory=Path(directory)
    version=normalized_version(version)
    names=["Library-Workbench-"+version+"-"+suffix for suffix in
           ("windows-x64-preview.zip","macos-arm64-preview.zip","macos-x86_64-preview.zip","linux-source.tar.gz")]
    sources={}
    checksums=[]
    present={p.name for p in directory.glob("Library-Workbench-*") if p.name.endswith((".zip",".tar.gz"))}
    if present!=set(names):raise ValueError("The release must contain exactly the four expected archives")
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
                runtime=manifest.get("windows_runtime_test") or manifest.get("macos_runtime_test")
                built_commit=manifest.get("commit") or manifest.get("windows_validation",{}).get("commit")
                if manifest["version"]!=version or runtime!="passed" or built_commit!=commit:
                    raise ValueError("Package version, commit or runtime validation does not match this release")
                if not manifest.get("application_sources"):raise ValueError("Package has no source digests")
                for source,digest_value in manifest["application_sources"].items():
                    if source in sources and sources[source]!=digest_value:raise ValueError("Package source mismatch: "+source)
                    sources[source]=digest_value
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

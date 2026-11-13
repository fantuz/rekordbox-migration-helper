"""Package application source from an explicit allowlist, excluding user data."""
from hashlib import sha256
from pathlib import Path
import tarfile
from io import BytesIO
from release_tools import build_version,archive_name

ROOT=Path(__file__).resolve().parents[1]
VERSION=build_version()


def main():
    destination=ROOT/"releases"/archive_name(VERSION,'linux-source')
    destination.parent.mkdir(exist_ok=True)
    files=list(ROOT.glob("*.py"))
    files+=[ROOT/name for name in (".gitattributes","start.sh","requirements.txt","requirements-build.txt","requirements-test.txt","requirements-browser.txt","README.md","CHANGELOG.md","CONTRIBUTING.md","LICENSE","SECURITY.md","THIRD-PARTY-NOTICES.txt")]
    files+=list((ROOT/"static").glob("*"))
    files+=list((ROOT/"packaging").glob("*.py"))+list((ROOT/"packaging").glob("*.c"))
    files+=list((ROOT/"docs").glob("*.md"))
    files+=list((ROOT/"docs").glob("*.json"))
    with tarfile.open(destination,"w:gz") as archive:
        for file in sorted(files):
            if file.is_file():archive.add(file,arcname="library-workbench/"+str(file.relative_to(ROOT)),recursive=False)
        content=(VERSION+"\n").encode()
        info=tarfile.TarInfo("library-workbench/VERSION");info.size=len(content);info.mode=0o644
        archive.addfile(info,BytesIO(content))
    digest=sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".gz.sha256").write_text(digest+"  "+destination.name+"\n",encoding="utf-8")
    print(destination)


if __name__=="__main__":main()

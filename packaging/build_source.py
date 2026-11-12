"""Package application source from an explicit allowlist, excluding user data."""
from hashlib import sha256
from pathlib import Path
import tarfile

ROOT=Path(__file__).resolve().parents[1]
VERSION="0.3.0"


def main():
    destination=ROOT/"releases"/("Library-Workbench-"+VERSION+"-linux-source.tar.gz")
    destination.parent.mkdir(exist_ok=True)
    files=list(ROOT.glob("*.py"))
    files+=[ROOT/name for name in ("start.sh","requirements.txt","requirements-build.txt","README.md","LICENSE","THIRD-PARTY-NOTICES.txt")]
    files+=list((ROOT/"static").glob("*"))
    files+=list((ROOT/"packaging").glob("*.py"))+list((ROOT/"packaging").glob("*.c"))
    files+=list((ROOT/"docs").glob("*.md"))
    with tarfile.open(destination,"w:gz") as archive:
        for file in sorted(files):
            if file.is_file():archive.add(file,arcname="library-workbench/"+str(file.relative_to(ROOT)),recursive=False)
    digest=sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".gz.sha256").write_text(digest+"  "+destination.name+"\n",encoding="utf-8")
    print(destination)


if __name__=="__main__":main()

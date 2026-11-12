"""Build and smoke-test an architecture-specific, self-contained macOS app."""
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


ROOT=Path(__file__).resolve().parents[1]
VERSION="0.3.0"


def main():
    if sys.platform!="darwin":raise RuntimeError("Build this application on a macOS runner")
    architecture=platform.machine()
    if architecture not in ("arm64","x86_64"):raise RuntimeError("Unsupported macOS architecture")
    build=ROOT/".build/macos"/architecture
    dist=build/"dist"
    command=[sys.executable,"-m","PyInstaller","--noconfirm","--clean","--windowed","--onedir",
             "--name","Library Workbench","--distpath",str(dist),"--workpath",str(build/"work"),
             "--specpath",str(build),"--target-architecture",architecture,
             "--osx-bundle-identifier","org.fantuz.rekordbox-migration-helper",
             "--add-data",str(ROOT/"static")+":static","--collect-all","pyrekordbox",
             "--collect-all","sqlcipher3","--copy-metadata","sqlcipher3-wheels",
             "--hidden-import","sqlcipher3.dbapi2",str(ROOT/"desktop_launcher.py")]
    # Insert data arguments before the entry point; Python's -m invocation stays intact.
    for name in ("LICENSE","THIRD-PARTY-NOTICES.txt"):
        if (ROOT/name).is_file():command[-1:-1]=["--add-data",str(ROOT/name)+":."]
    subprocess.run(command,cwd=ROOT,check=True)
    app=dist/"Library Workbench.app"
    validation=build/"MACOS-VALIDATION.json"
    subprocess.run([sys.executable,str(ROOT/"packaging/smoke_desktop.py"),"--macos-app",str(app),"--report",str(validation)],cwd=ROOT,check=True)
    manifest={"application":"Library Workbench","version":VERSION,"platform":"macos-"+architecture,
              "python":platform.python_version(),"macos_build":platform.mac_ver()[0],"macos_runtime_test":"passed",
              "signing":"ad-hoc; not Apple Developer ID signed or notarized","rekordbox_restore":"not exercised",
              "commit":os.environ.get("GITHUB_SHA"),"runtime_validation":json.loads(validation.read_text(encoding="utf-8")),
              "dependencies":[{"name":d.metadata["Name"],"version":d.version} for d in importlib.metadata.distributions()],
              "application_sources":{str(path.relative_to(ROOT)):sha256(path.read_bytes()).hexdigest() for path in [*ROOT.glob("*.py"),*list((ROOT/"static").glob("*"))] if path.is_file() and not path.name.startswith("test_")}}
    resources=app/"Contents/Resources"
    (resources/"BUILD-MANIFEST.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    (resources/"START HERE.txt").write_text(
        "LIBRARY WORKBENCH "+VERSION+" — macOS "+architecture+" PREVIEW\n\n"
        "Extract the ZIP and open Library Workbench.app. The interface opens in\n"
        "your default browser. Python and application dependencies are bundled.\n"
        "Workspaces are saved under ~/Library/Application Support/LibraryWorkbench.\n"
        "Use Stop local application in the browser footer when finished.\n\n"
        "This preview passed automated native macOS runtime checks. It is ad-hoc\n"
        "signed, not Developer ID signed or notarized. macOS may restrict opening it.\n"
        "No rekordbox restore compatibility is claimed. Keep a separate untouched\n"
        "backup before generating transformed files and test restores in isolation.\n",encoding="utf-8")
    subprocess.run(["codesign","--force","--deep","--sign","-",str(app)],check=True)
    subprocess.run(["codesign","--verify","--deep","--strict",str(app)],check=True)
    output=ROOT/"releases";output.mkdir(exist_ok=True)
    destination=output/("Library-Workbench-"+VERSION+"-macos-"+architecture+"-preview.zip")
    subprocess.run(["ditto","-c","-k","--sequesterRsrc","--keepParent",str(app),str(destination)],check=True)
    destination.with_suffix(".sha256").write_text(sha256(destination.read_bytes()).hexdigest()+"  "+destination.name+"\n",encoding="utf-8")
    print(destination)


if __name__=="__main__":main()

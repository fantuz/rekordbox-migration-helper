"""Build a portable Windows x64 folder from official CPython and PyPI wheels.

Can assemble on Linux using MinGW. Actual Windows execution is a separate gate.
"""
import argparse
import base64
from email.parser import BytesParser
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from release_tools import build_version

APP=Path(__file__).resolve().parents[1]
VERSION=build_version()


def fetch(url,path):
    if not path.exists():
        with urllib.request.urlopen(url,timeout=90) as response,path.open("wb") as out:
            shutil.copyfileobj(response,out)
    return sha256(path.read_bytes()).hexdigest()


def unpack(archive,target):
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            relative=Path(info.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe archive member")
            z.extract(info,target)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--python-version",default="3.13.17")
    parser.add_argument("--output",type=Path,default=APP/"releases")
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    cache=APP/".build"/"windows"
    wheels=cache/"resolved-wheels"
    if wheels.exists():shutil.rmtree(wheels)
    wheels.mkdir(parents=True,exist_ok=True)
    version=args.python_version
    runtime_zip=cache/("python-"+version+"-embed-amd64.zip")
    runtime_url="https://www.python.org/ftp/python/"+version+"/"+runtime_zip.name
    runtime_hash=fetch(runtime_url,runtime_zip)
    manifest={"application":"Library Workbench","version":VERSION,"platform":"windows-x86_64",
              "windows_runtime_test":"pending","python":{"version":version,"url":runtime_url,"sha256":runtime_hash},
              "dependencies":[]}
    # The publisher bundle embeds the release artifact digest. HTTPS and the
    # digest are checked here; this is not a replacement for Sigstore verification.
    try:
        bundle=json.load(urllib.request.urlopen(runtime_url+".sigstore",timeout=30))
        digest=bundle["messageSignature"]["messageDigest"]["digest"]
        if base64.b64decode(digest).hex()!=runtime_hash:
            raise ValueError("Publisher digest mismatch")
        manifest["python"]["publisher_digest_checked"]=True
    except (urllib.error.HTTPError,KeyError):
        manifest["python"]["publisher_digest_checked"]=False
    minor=".".join(version.split(".")[:2])
    abi="cp"+"".join(version.split(".")[:2])
    command=[sys.executable,"-m","pip","download","--disable-pip-version-check","--only-binary=:all:",
             "--platform","win_amd64","--python-version",minor,"--implementation","cp","--abi",abi,
             "--dest",str(wheels),"-r",str(APP/"requirements.txt"),"tzdata"]
    subprocess.run(command,check=True)
    # pip's cross-platform download markers can reflect the build host. Resolve
    # Windows-only requirements explicitly rather than omitting e.g. colorama.
    from packaging.requirements import Requirement
    from packaging.markers import default_environment
    from packaging.utils import canonicalize_name
    environment=default_environment()
    environment.update(sys_platform="win32",os_name="nt",platform_system="Windows",platform_machine="AMD64",
                       python_version=minor,python_full_version=version,implementation_name="cpython",
                       platform_python_implementation="CPython",extra="")
    for attempt in range(4):
        installed={}
        requirement_rows=[]
        for wheel in wheels.glob("*.whl"):
            with zipfile.ZipFile(wheel) as z:
                meta=next(n for n in z.namelist() if n.endswith(".dist-info/METADATA"))
                values=BytesParser().parsebytes(z.read(meta))
            installed[canonicalize_name(values["Name"])]=values["Version"]
            requirement_rows.extend(values.get_all("Requires-Dist",[]))
        missing=[]
        for text in requirement_rows:
            requirement=Requirement(text)
            if requirement.marker and not requirement.marker.evaluate(environment):continue
            found=installed.get(canonicalize_name(requirement.name))
            if found is None:
                missing.append(requirement.name+str(requirement.specifier))
            elif not requirement.specifier.contains(found):
                raise ValueError("Dependency version conflict for "+requirement.name)
        if not missing:break
        subprocess.run(command[:command.index("-r")]+sorted(set(missing)),check=True)
    else:raise ValueError("Windows dependency closure did not resolve")
    manifest["windows_dependency_markers_checked"]=True
    folder=cache/"Library Workbench"
    if folder.exists():shutil.rmtree(folder)
    runtime=folder/"runtime"
    app_folder=folder/"app"
    runtime.mkdir(parents=True)
    app_folder.mkdir()
    unpack(runtime_zip,runtime)
    site=runtime/"Lib"/"site-packages"
    site.mkdir(parents=True)
    for wheel in sorted(wheels.glob("*.whl")):
        with zipfile.ZipFile(wheel) as z:
            meta=next(n for n in z.namelist() if n.endswith(".dist-info/METADATA"))
            metadata=BytesParser().parsebytes(z.read(meta))
        info=json.load(urllib.request.urlopen("https://pypi.org/pypi/"+metadata["Name"]+"/"+metadata["Version"]+"/json"))
        release=next(f for f in info["urls"] if f["filename"]==wheel.name)
        digest=sha256(wheel.read_bytes()).hexdigest()
        if digest!=release["digests"]["sha256"]:raise ValueError("Wheel digest mismatch")
        manifest["dependencies"].append({"name":metadata["Name"],"version":metadata["Version"],
                                         "filename":wheel.name,"sha256":digest,"url":release["url"]})
        unpack(wheel,site)
    # Embedded Python's isolated path includes the application's modules.
    pth=runtime/("python"+abi[2:]+"._pth")
    pth.write_text("python"+abi[2:]+".zip\n.\nLib/site-packages\n../app\nimport site\n",encoding="utf-8")
    for file in APP.glob("*.py"):
        if not file.name.startswith("test_"):shutil.copy2(file,app_folder/file.name)
    shutil.copytree(APP/"static",app_folder/"static")
    (folder/"VERSION").write_text(VERSION+"\n",encoding="utf-8")
    for name in ("LICENSE","THIRD-PARTY-NOTICES.txt"):
        if (APP/name).is_file():shutil.copy2(APP/name,folder/name)
    exe=folder/"Library Workbench.exe"
    compiler=shutil.which("x86_64-w64-mingw32-gcc")
    if not compiler:raise RuntimeError("MinGW x64 compiler is required to assemble the launcher on Linux")
    subprocess.run([compiler,"-Os","-municode","-mwindows","-static-libgcc","-Wl,--nxcompat,--dynamicbase",
                    "-o",str(exe),str(APP/"packaging/windows_launcher.c")],check=True)
    manifest["application_sources"]={str(p.relative_to(app_folder)).replace("\\","/"):sha256(p.read_bytes()).hexdigest()
                                     for p in app_folder.rglob("*") if p.is_file()}
    (folder/"BUILD-MANIFEST.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    (folder/"START HERE.txt").write_text(
        "LIBRARY WORKBENCH "+VERSION+" — WINDOWS x64 PREVIEW\n\n"
        "1. Extract this entire ZIP to a folder.\n"
        "2. Double-click Library Workbench.exe.\n"
        "3. The application opens in your default browser.\n"
        "4. Use Source analyzer for a read-only folder report, or import a\n"
        "   matching rekordbox library ZIP and collection XML to prepare copies.\n\n"
        "Python and all application dependencies are bundled.\n"
        "No Python installation, administrator access, shell or package setup is required.\n"
        "Use Stop local application in the page footer to close the local server.\n"
        "Workspaces and logs are stored under %LOCALAPPDATA%\\LibraryWorkbench.\n\n"
        "This Windows preview has been assembled and checked on Linux, but has not\n"
        "been run on Windows. Validate startup and an isolated rekordbox restore\n"
        "before using generated native library backups on a working collection.\n\n"
        "BUILD-MANIFEST.json records source URLs, versions and hashes.\n",
        encoding="utf-8")
    destination=args.output/("Library-Workbench-"+VERSION+"-windows-x64-preview.zip")
    with zipfile.ZipFile(destination,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as out:
        for file in sorted(folder.rglob("*")):
            if file.is_file():out.write(file,file.relative_to(folder.parent))
    result={"archive":str(destination),"bytes":destination.stat().st_size,
            "sha256":sha256(destination.read_bytes()).hexdigest(),"windows_execution":"not tested"}
    destination.with_suffix(".sha256").write_text(result["sha256"]+"  "+destination.name+"\n")
    print(json.dumps(result,indent=2),flush=True)


if __name__=="__main__":main()

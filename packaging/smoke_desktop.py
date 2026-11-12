"""Exercise source startup or an extracted Windows portable application."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import urllib.request


FIXTURE='''
import sys
from pathlib import Path
from native_export import mutable_copy
path=Path(sys.argv[1])
db=mutable_copy(path)
db.executescript("""
CREATE TABLE djmdContent(ID TEXT,Title TEXT,FolderPath TEXT,Rating INTEGER,DJPlayCount INTEGER,Analysed INTEGER,rb_local_deleted INTEGER);
CREATE TABLE djmdCue(ID TEXT,ContentID TEXT,Comment TEXT,rb_local_deleted INTEGER);
INSERT INTO djmdContent VALUES ('synthetic-1','Synthetic CI track','C:/Smoke/track.mp3',3,0,1,0);
INSERT INTO djmdCue VALUES ('synthetic-cue','synthetic-1','CUE(Auto)',0);
""")
db.commit()
db.close()
'''


def main():
    parser=argparse.ArgumentParser()
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--application",type=Path,help="Extracted Windows portable application folder")
    group.add_argument("--macos-app",type=Path,help="Self-contained macOS .app bundle")
    group.add_argument("--source",type=Path,help="Application source folder")
    parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args()
    root=(args.application or args.macos_app or args.source).resolve()
    runtime=root/"runtime/python.exe" if args.application else Path(sys.executable)
    app_dir=root/"app" if args.application else Path(__file__).resolve().parents[1] if args.macos_app else root
    mac_binary=root/"Contents/MacOS/Library Workbench"
    launcher=([str(root/"Library Workbench.exe")] if args.application else [str(mac_binary),"--no-browser","--port","0"] if args.macos_app else [str(runtime),str(app_dir/"desktop_launcher.py"),"--no-browser","--port","0"])
    with tempfile.TemporaryDirectory(prefix="Workbench smoke 日本 é ") as temporary:
        work=Path(temporary)
        data=work/"workspace"
        source=work/"source library"
        source.mkdir()
        subprocess.run([str(runtime),"-c",FIXTURE,str(source/"master.db")],cwd=app_dir,check=True)
        original=sha256((source/"master.db").read_bytes()).hexdigest()
        env={**os.environ,"LIBRARY_WORKBENCH_DATA_DIR":str(data),"LIBRARY_WORKBENCH_NO_BROWSER":"1"}
        if args.application or args.macos_app:
            for name in ("PYTHONPATH","PYTHONHOME","DYLD_LIBRARY_PATH"):env.pop(name,None)
            env["PATH"]=os.pathsep.join([str(Path(os.environ.get("SystemRoot","C:/Windows"))/"System32"),os.environ.get("SystemRoot","C:/Windows")]) if args.application else "/usr/bin:/bin:/usr/sbin:/sbin"
        smoke=[str(mac_binary),"--smoke-test"] if args.macos_app else [str(runtime),str(app_dir/"desktop_launcher.py"),"--smoke-test"]
        subprocess.run(smoke,cwd=app_dir,env=env,check=True)
        token=base=None
        process=None
        def request(path,body=None):
            headers={"Content-Type":"application/json"}
            if token:headers["X-Workbench-Token"]=token
            payload=json.dumps(body).encode() if body is not None else None
            req=urllib.request.Request(base+path,data=payload,headers=headers)
            with urllib.request.urlopen(req,timeout=10) as response:return json.load(response)
        with (work/"process.log").open("w",encoding="utf-8") as log:
            process=subprocess.Popen(launcher,cwd=root,env=env,stdout=log,stderr=log)
            try:
                deadline=time.monotonic()+60
                while time.monotonic()<deadline:
                    try:
                        info=json.loads((data/"instance.json").read_text())
                        base=info["url"]
                        status=request("/api/status")
                        if status["app_id"]=="library-workbench":break
                    except (OSError,ValueError,KeyError):pass
                    time.sleep(.2)
                else:raise RuntimeError("Desktop startup timed out: "+(work/"process.log").read_text())
                token=status["token"]
                workspace=request("/api/workspace")
                assert Path(workspace["root"])==data
                with urllib.request.urlopen(base,timeout=10) as response:
                    assert b"Source analyzer" in response.read()
                if args.application or args.macos_app:
                    subprocess.run(launcher,cwd=root,env=env,check=True,timeout=20)
                    assert json.loads((data/"instance.json").read_text())["pid"]==info["pid"]
                started=request("/api/analyzer",{"path":str(source),"version":"7.0.0"})
                deadline=time.monotonic()+60
                while time.monotonic()<deadline:
                    job=request("/api/tasks/"+started["job"])
                    if job["status"]=="error":raise RuntimeError(job["message"])
                    if job["status"]=="complete":break
                    time.sleep(.2)
                else:raise RuntimeError("Source analyzer timed out")
                result=job["result"]
                assert result["read_status"]=="checked",result["messages"]
                assert result["database"]["counters"]["tracks"]==1
                assert result["database"]["integrity_ok"]
                assert result["source_writes"] is False
                assert sha256((source/"master.db").read_bytes()).hexdigest()==original
                saved=request("/api/analyzer/"+result["id"]+"/report")
                assert saved["database"]["counters"]["tracks"]==1
                checks={"status":"passed","platform":platform.platform(),"launcher":"portable executable" if args.application else "macOS app bundle" if args.macos_app else "Python source",
                        "encrypted_sqlcipher_read_write":"passed","http_startup":"passed","unicode_workspace_path":"passed",
                        "read_only_analyzer":"passed","source_sha256_unchanged":True,"json_report_download":"passed",
                        "repeat_launch":"passed" if args.application or args.macos_app else "not exercised","rekordbox_restore":"not exercised"}
            finally:
                if base and token:
                    try:request("/api/desktop/stop",{})
                    except OSError:pass
                if process:
                    try:process.wait(timeout=15)
                    except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)
                deadline=time.monotonic()+15
                while (data/"instance.json").exists() and time.monotonic()<deadline:time.sleep(.2)
                if (data/"instance.json").exists():raise RuntimeError("Desktop did not stop cleanly")
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(checks,indent=2),encoding="utf-8")
        print(json.dumps(checks,indent=2))


if __name__=="__main__":main()

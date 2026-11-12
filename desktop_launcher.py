"""Desktop entry point shared by Linux and the portable Windows application."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import time
import urllib.request
import webbrowser
from platform_paths import default_data_directory


def acquire_lock(path):
    stream=path.open("a+b")
    if stream.seek(0,2)==0:
        stream.write(b"0")
        stream.flush()
    stream.seek(0)
    try:
        if os.name=="nt":
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        stream.close()
        return None
    return stream


def existing_instance(path):
    try:
        info=json.loads(path.read_text(encoding="utf-8"))
        with urllib.request.urlopen(info["url"]+"/api/status",timeout=2) as response:
            if json.load(response).get("app_id")=="library-workbench":
                return info["url"]
    except (OSError,ValueError,KeyError):
        pass
    return None


def alert(text):
    if os.name=="nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,text,"Library Workbench",0x10)
    else:
        print(text,file=sys.stderr)


def smoke_test():
    import tempfile
    import lxml.etree
    from engine import open_master
    from native_export import mutable_copy
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/"smoke.db"
        db=mutable_copy(path)
        db.execute("CREATE TABLE smoke(value TEXT)")
        db.execute("INSERT INTO smoke VALUES ('ready')")
        db.commit()
        db.close()
        check=open_master(path.resolve())
        assert check.execute("SELECT value FROM smoke").fetchone()==("ready",)
        check.close()
    print(json.dumps({"status":"passed","python":sys.version.split()[0],"sqlcipher":"encrypted read/write passed","lxml":lxml.etree.LXML_VERSION}))


def main():
    parser=argparse.ArgumentParser(description="Library Workbench desktop application")
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--no-browser",action="store_true",default=os.environ.get("LIBRARY_WORKBENCH_NO_BROWSER")=="1")
    parser.add_argument("--smoke-test",action="store_true")
    args=parser.parse_args()
    if args.smoke_test:
        smoke_test()
        return
    default=default_data_directory(Path(__file__).parent)
    data=Path(os.environ.get("LIBRARY_WORKBENCH_DATA_DIR",default)).expanduser().resolve()
    data.mkdir(parents=True,exist_ok=True)
    os.environ["LIBRARY_WORKBENCH_DATA_DIR"]=str(data)
    file_lock=acquire_lock(data/"desktop.lock")
    instance=data/"instance.json"
    if file_lock is None:
        for _ in range(30):
            url=existing_instance(instance)
            if url:
                if not args.no_browser:webbrowser.open(url)
                print("Library Workbench is already running at "+url)
                return
            time.sleep(.1)
        alert("Another Library Workbench instance is starting. Try again shortly.")
        return
    handler=RotatingFileHandler(data/"application.log",maxBytes=2*1024**2,backupCount=2,encoding="utf-8")
    logging.basicConfig(level=logging.INFO,handlers=[handler])
    from app import app
    from werkzeug.serving import make_server
    try:
        server=make_server("127.0.0.1",args.port,app,threaded=True)
    except SystemExit:
        server=make_server("127.0.0.1",0,app,threaded=True)
    url="http://127.0.0.1:"+str(server.server_port)
    instance.write_text(json.dumps({"url":url,"pid":os.getpid()}),encoding="utf-8")
    app.config["SHUTDOWN_CALLBACK"]=server.shutdown
    print("Library Workbench is running at "+url,flush=True)
    if not args.no_browser:webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        instance.unlink(missing_ok=True)
        file_lock.close()


if __name__=="__main__":
    try:
        main()
    except Exception:
        logging.exception("Application startup failed")
        alert("Library Workbench could not start. See application.log in the LibraryWorkbench data folder for details.")
        raise

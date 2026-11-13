"""Own only marked temporary directories; never delete user-selected sources."""
from contextlib import contextmanager
from pathlib import Path
from threading import Condition
from uuid import uuid4
import atexit
import json
import os
import shutil
import time

OWNER='LibraryWorkbench temporary analysis v1'


def file_lock(path):
    if path.is_symlink():return None
    stream=path.open('a+b')
    if stream.seek(0,2)==0:stream.write(b'0');stream.flush()
    stream.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:stream.close();return None
    return stream


class TemporaryWorkspace:
    def __init__(self,base):
        self.base=Path(base).resolve();self.parent=self.base/'.temporary'
        if self.parent.is_symlink():raise ValueError('The managed temporary folder cannot be a symbolic link')
        self.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.recovered=self.recover_stale();self.path=self.parent/uuid4().hex
        self.path.mkdir(mode=0o700)
        (self.path/'owner.json').write_text(json.dumps({'owner':OWNER,'id':self.path.name}),encoding='utf-8')
        self.lock=file_lock(self.path/'.lock');self.condition=Condition();self.active=0;self.closing=False;self.cleaned=False
        atexit.register(self.best_effort_cleanup)

    def recover_stale(self):
        recovered=[]
        for path in self.parent.iterdir():
            if path.is_symlink() or not path.is_dir() or len(path.name)!=32 or any(c not in '0123456789abcdef' for c in path.name):continue
            marker=path/'owner.json'
            if marker.is_symlink() or not (path/'.lock').is_file():continue
            try:
                identity=json.loads(marker.read_text(encoding='utf-8'))
                if identity!={'owner':OWNER,'id':path.name}:continue
                lock=file_lock(path/'.lock')
                if lock is None:continue
                lock.close();shutil.rmtree(path);recovered.append(path.name)
            except (OSError,ValueError):continue
        return recovered

    def folder(self,*parts):
        path=self.path.joinpath(*parts)
        if path.is_symlink() or not path.resolve().is_relative_to(self.path):raise ValueError('Temporary path escaped its owned directory')
        path.mkdir(parents=True,exist_ok=True)
        return path

    @contextmanager
    def operation(self):
        with self.condition:
            if self.closing:raise InterruptedError('Shutdown is cleaning temporary analysis copies')
            self.active+=1
        try:yield
        finally:
            with self.condition:self.active-=1;self.condition.notify_all()

    def summary(self):
        count=size=0
        for root,dirs,files in os.walk(self.path,followlinks=False):
            dirs[:]=[d for d in dirs if not (Path(root)/d).is_symlink() and not (Path(root)/d).is_junction()]
            for name in files:
                path=Path(root)/name
                if path.is_symlink():continue
                try:size+=path.stat().st_size;count+=1
                except OSError:pass
        return {'files':count,'bytes':size,'directory':str(self.path),'recovered_stale_runs':len(self.recovered)}

    def wait_idle(self,timeout=30):
        with self.condition:
            self.closing=True
            return self.condition.wait_for(lambda:self.active==0,timeout)

    def cleanup(self):
        if self.cleaned:return
        with self.condition:
            if self.active:raise RuntimeError('Analysis is still using temporary copies; wait before cleanup')
            self.closing=True
        if self.lock:self.lock.close();self.lock=None
        for attempt in range(4):
            try:shutil.rmtree(self.path);self.cleaned=True;return
            except FileNotFoundError:self.cleaned=True;return
            except OSError:
                if attempt==3:raise
                time.sleep(.1*(attempt+1))

    def best_effort_cleanup(self):
        if not self.active:
            try:self.cleanup()
            except OSError:pass  # The marked directory is retried at the next start.

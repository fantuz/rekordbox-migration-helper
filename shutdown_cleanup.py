"""Acknowledged shutdown waits for workers before removing owned copies."""
from datetime import datetime,timezone
from threading import Event,RLock,Thread
import json
import time


class ShutdownController:
    def __init__(self,temporary,cancel,clean_cache,stop):
        self.temporary=temporary;self.cancel=cancel;self.clean_cache=clean_cache;self.stop=stop
        self.requested=Event();self.lock=RLock();self.thread=None
        self.state={'phase':'running','message':'Temporary analysis copies are removed on acknowledged shutdown.'}

    def status(self,inventory=False):
        with self.lock:result=dict(self.state)
        if inventory and not self.temporary.cleaned:result.update(self.temporary.summary())
        return result

    def request(self,acknowledged,reason='application exit'):
        if acknowledged is not True:raise ValueError('Acknowledge deletion of temporary analysis copies before stopping. Originals, reports, decisions and completed exports are kept.')
        with self.lock:
            if self.thread and self.thread.is_alive():return self.status()
            self.requested.set();self.state.update(phase='stopping',message='Cancelling work and waiting for temporary files to close.')
            self.thread=Thread(target=self.run,args=(reason,),daemon=True);self.thread.start()
        return self.status()

    def run(self,reason):
        try:
            self.cancel()
            if not self.temporary.wait_idle():raise RuntimeError('Work is still closing temporary files. Wait, then retry Stop and clean up.')
            summary=self.temporary.summary()
            self.clean_cache()
            self.temporary.cleanup()
            record={**summary,'phase':'complete','message':'Temporary analysis copies removed. Originals, reports, decisions and completed exports were kept.',
                    'reason':reason,'created':datetime.now(timezone.utc).isoformat(),'originals_modified':False}
            path=self.temporary.base/'cleanup-last.json';pending=path.with_suffix('.tmp')
            pending.write_text(json.dumps(record,indent=2),encoding='utf-8');pending.replace(path)
            with self.lock:self.state=record
            time.sleep(.8)  # Let the local page observe successful cleanup before closing HTTP.
            self.stop()
        except Exception as error:
            with self.lock:self.state.update(phase='error',message='Cleanup did not finish: '+str(error)+'. The app remains open; retry cleanup.')

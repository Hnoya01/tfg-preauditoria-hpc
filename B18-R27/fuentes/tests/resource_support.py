"""P01 diagnostics record ownership only, never SQL, cookies or account data."""
import json
from pathlib import Path
import sqlite3
import sys
import threading
import weakref
from unittest.mock import patch


class ConnectionTracker:
    def __init__(self,root):
        self.database=(Path(root)/'app.sqlite3').resolve()
        self.records={};self.lock=threading.Lock();self.patcher=None

    def start(self):
        original=sqlite3.connect;tracker=self
        class TrackedConnection(sqlite3.Connection):
            def close(self):
                super().close()
                with tracker.lock:tracker.records[self._tracker_identity]['closed']=True
        def opening(*args,**kwargs):
            database=args[0] if args else kwargs['database']
            if Path(database).resolve()!=tracker.database:return original(*args,**kwargs)
            connection=original(*args,**kwargs,factory=TrackedConnection)
            callers=[];frame=sys._getframe(1)
            try:
                for _ in range(3):
                    if frame is None:break
                    callers.append({'file':Path(frame.f_code.co_filename).name,'function':frame.f_code.co_name})
                    frame=frame.f_back
            finally:del frame
            with tracker.lock:
                # Sequence numbers avoid address reuse and disclose no handles.
                identity=len(tracker.records)+1
                connection._tracker_identity=identity
                tracker.records[identity]={'sequence':identity,'closed':False,
                    'thread':threading.current_thread().name,'callers':callers,'reference':weakref.ref(connection)}
            return connection
        self.patcher=patch('sqlite3.connect',side_effect=opening);self.patcher.start()

    def stop(self):
        if self.patcher is not None:self.patcher.stop();self.patcher=None

    def report(self,test,phase,managers,error=None):
        with self.lock:
            records=[{k:v for k,v in item.items() if k!='reference'}|{'object_alive':item['reference']() is not None}
                     for item in self.records.values()]
        record={'test':test,'phase':phase,'connections_created':len(records),
            'connections_explicitly_closed':sum(r['closed'] for r in records),
            'unclosed_connections':[r for r in records if not r['closed']],
            'managers':[{'sequence':i+1,'stop_requested':m.stop.is_set(),'coordinator_alive':m.thread.is_alive(),
                         'worker_alive':bool(m.worker and m.worker.is_alive())} for i,m in enumerate(managers)]}
        if error is not None:
            record['error']={'type':type(error).__name__,'winerror':getattr(error,'winerror',None),
                             'file':Path(error.filename).name if getattr(error,'filename',None) else None}
        output=Path('.test-results');output.mkdir(exist_ok=True)
        with (output/'p01-resources.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(record)+'\n')
        return record

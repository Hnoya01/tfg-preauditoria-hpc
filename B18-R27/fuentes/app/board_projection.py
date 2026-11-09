"""Keep one invoice's base rows between filters in a running web application."""
import sqlite3
from threading import Lock
from time import monotonic
from .db import database_path


class BoardProjection:
    def __init__(self,root,min_rows=3000):
        self.root=root
        self.min_rows=min_rows
        self.lock=Lock()
        self.observer=None
        self.entry=None

    def _epoch(self):
        # SQLite's data_version is comparable only on the same connection.
        if self.observer is None:
            self.observer=sqlite3.connect(database_path(self.root).as_uri()+'?mode=ro',uri=True,
                                          isolation_level=None,check_same_thread=False)
        return self.observer.execute('PRAGMA data_version').fetchone()[0]

    def stamp(self):
        with self.lock:return self._epoch()

    def get(self,stamp,key):
        with self.lock:
            if self.entry and self.entry[0]==(stamp,key) and self.entry[1]>monotonic() and self._epoch()==stamp:
                rows,counts,context=self.entry[2]
                return {n:r.copy() for n,r in rows.items()},counts.copy(),context.copy()

    def put(self,stamp,key,rows,counts,context):
        if not self.min_rows<=len(rows)<=50000:return
        with self.lock:
            if self._epoch()==stamp:
                self.entry=((stamp,key),monotonic()+50,({n:r.copy() for n,r in rows.items()},dict(counts),context.copy()))

    def close(self):
        with self.lock:
            self.entry=None
            if self.observer:self.observer.close()
            self.observer=None

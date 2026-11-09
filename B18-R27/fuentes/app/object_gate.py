"""Bounded cross-process exclusion for publishing objects and recovery snapshots.

Backup acquires the SQLite writer before this gate. A publisher holds only this
gate while writing bytes; its later SQLite registration never holds this gate.
Unregistered bytes are preserved, including producers awaiting their DB commit.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import threading
import time

_locks = {}
_guard = threading.Lock()
LOCK_NAME = '.objects.lock'


@contextmanager
def object_gate(root, timeout=10):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    with _guard:lock=_locks.setdefault(str(root),threading.Lock())
    if not lock.acquire(timeout=timeout):raise _busy()
    stream=None;acquired=False;deadline=time.monotonic()+timeout
    try:
        stream=os.fdopen(os.open(root/LOCK_NAME,os.O_RDWR|os.O_CREAT,0o600),'r+b',buffering=0)
        if os.fstat(stream.fileno()).st_size==0:stream.write(b'0')
        while True:
            try:
                if os.name=='nt':
                    import msvcrt
                    stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                acquired=True;break
            except OSError:
                if time.monotonic()>=deadline:raise _busy()
                time.sleep(.02)
        yield
    finally:
        if acquired:
            if os.name=='nt':
                stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
        if stream is not None:stream.close()
        lock.release()


def _busy():
    error=sqlite3.OperationalError('Private object storage busy; retry')
    error.sqlite_errorcode=sqlite3.SQLITE_BUSY
    return error


@contextmanager
def recovery_snapshot(root):
    """Exclude DB commits and physical publications without changing DB rows."""
    root=Path(root).resolve()
    conn=sqlite3.connect((root/'app.sqlite3').as_uri()+'?mode=rw',uri=True,isolation_level=None,timeout=10)
    try:
        conn.execute('BEGIN IMMEDIATE')
        with object_gate(root):yield
    finally:
        conn.rollback();conn.close()

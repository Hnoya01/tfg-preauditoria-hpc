"""Separate worker used only by fictional crash/publication tests."""
from pathlib import Path
import sqlite3
from app.db import connect
from app.processing import claim,execute,retry


def worker_stage_diagnostic(root, identity, worker):
    """Report safe state on a missing signal without replacing the assertion."""
    result={'worker_alive':worker.is_alive(),'worker_exitcode':worker.exitcode}
    conn=None
    try:
        conn=connect(Path(root),timeout=.1)
        row=conn.execute('SELECT state,stage,error_code,error_type,processed_rows '
                         'FROM processing_attempts WHERE id=?',(identity,)).fetchone()
        result.update(dict(row) if row else {'attempt_missing':True})
    except sqlite3.Error as exc:
        result['diagnostic_error']=getattr(exc,'sqlite_errorname',type(exc).__name__)
    finally:
        if conn is not None:conn.close()
    return result


def pre_execution_worker(root, claimed, proceed, evaluated):
    """Let the parent expire a claimed job before its first execution guard."""
    conn=connect(Path(root))
    try:job=claim(conn,'fictional-pre-execution-worker',lease_seconds=.6)
    finally:conn.close()
    claimed.set()
    if not proceed.wait(10):
        raise RuntimeError('Parent did not release the pre-execution fixture')
    def progress(stage,done,total):
        if stage=='evaluating':evaluated.set()
    execute(Path(root),job,lease_seconds=.6,publish_lease_seconds=.6,
            heartbeat_interval=.05,progress_hook=progress)


def hold_object_gate(root,ready,release):
    from app.object_gate import object_gate
    with object_gate(Path(root)):
        ready.set()
        if not release.wait(10):raise RuntimeError('FICTICIO missing object-gate release')


def racing_claim(root,ready,start,output,owner):
    conn=connect(Path(root))
    try:
        ready.set();start.wait(10);job=claim(conn,owner);output.send(job['id'] if job else None)
    finally:output.close();conn.close()


def racing_retry(root,ready,start,output,arguments):
    conn=connect(Path(root))
    try:
        ready.set();start.wait(10);job,created=retry(conn,**arguments);output.send((job['id'],created))
    finally:output.close();conn.close()


def gated_worker(root, ready, release, phase):
    conn=connect(Path(root));job=claim(conn,'fictional-separate-worker',lease_seconds=.6);conn.close()
    def progress(stage,done,total):
        if phase=='preparation' and stage=='evaluating' and done==0:
            ready.set();release.wait(20)
    def publishing(conn,run_id):
        if phase=='publication':
            assert conn.in_transaction
            assert conn.execute('SELECT count(*) FROM control_results WHERE run_id=?',(run_id,)).fetchone()[0]>0
            ready.set();release.wait(20)
    execute(Path(root),job,lease_seconds=.6,publish_lease_seconds=.6,heartbeat_interval=.05,
            progress_hook=progress,publication_hook=publishing)

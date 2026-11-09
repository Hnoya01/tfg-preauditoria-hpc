"""Persistent local control attempts with leases, explicit retries and atomic publication."""

from .revision_scope import revision_table

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import sqlite3
import threading
import time
from uuid import uuid4

from .controls import _json, _snapshot, run_controls
from .db import connect, transaction
from .review import _batch
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event


LEASE_SECONDS = 15
PUBLISH_LEASE_SECONDS = 90
ACTIVE = ('queued', 'running')
RETRYABLE = ('failed', 'interrupted')
ERROR_LABELS = {
    'activity_lost': 'Se perdió la confirmación de actividad. No se publicó una captura parcial.',
    'server_stopped': 'El servidor se detuvo antes de completar el intento.',
    'inputs_changed': 'La revisión o sus datos cambiaron. Iniciá un análisis nuevo.',
    'permission_changed': 'La sesión o los permisos cambiaron. Revisá el acceso antes de iniciar otro análisis.',
    'storage_busy': 'Otra escritura impidió terminar. Se puede reintentar si los datos siguen iguales.',
    'processing_error': 'El intento no pudo completarse. Se conservó la captura anterior.',
}


def _stamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def _inputs(conn, dataset_id, batch_id):
    batch = dict(_batch(conn, dataset_id, batch_id))
    if batch['state'] == 'cerrada':
        raise Problem(409, 'La revisión está cerrada')
    invoice = conn.execute(f'SELECT i.*,b.source_sha256 FROM {revision_table(conn, "invoice_imports")} i JOIN batches b ON b.id=i.batch_id '
                           'WHERE b.id=? AND b.dataset_id=?', (batch_id, dataset_id)).fetchone()
    snapshot = _snapshot(conn, dataset_id, invoice)
    digest = hashlib.sha256(_json(snapshot).encode('utf-8')).hexdigest()
    total = conn.execute('SELECT count(*) FROM invoice_rows WHERE import_id=?', (invoice['id'],)).fetchone()[0]
    return batch, digest, total


def _attempt(conn, dataset_id, batch_id, attempt_id):
    row = conn.execute('SELECT a.*,u.username AS actor_username FROM processing_attempts a JOIN users u ON u.id=a.actor_id '
                       'WHERE a.id=? AND a.dataset_id=? AND a.batch_id=?',
                       (attempt_id, dataset_id, batch_id)).fetchone()
    if row is None:
        raise Problem(404, 'Intento inexistente')
    return row


def _expired(row):
    return row['state'] == 'running' and (row['lease_until'] or 0) <= time.time()


def _recover(conn, row):
    if _expired(row):
        conn.execute("UPDATE processing_attempts SET state='interrupted',finished_at=?,error_code='activity_lost',"
                     "version=version+1,lease_until=NULL WHERE id=? AND state='running' AND lease_until<=?",
                     (_stamp(), row['id'], time.time()))


def _public(row, dataset_version, batch):
    result = {k: row[k] for k in ('id','batch_id','previous_id','state','stage','processed_rows','total_rows',
              'created_at','started_at','heartbeat_at','finished_at','version','result_run_id','result_created','error_code')}
    if _expired(row):
        result.update(state='interrupted', error_code='activity_lost')
    result['error_message'] = ERROR_LABELS.get(result['error_code'])
    result['can_retry'] = (result['state'] in RETRYABLE and dataset_version == row['expected_dataset_version'] and
                           batch['revision_version'] == row['expected_revision_version'] and batch['state'] != 'cerrada')
    result['technical_only'] = True
    result['actor_username'] = row['actor_username'] if 'actor_username' in row.keys() else None
    return result


def attempts(conn, token_hash, dataset_id, batch_id, attempt_id=None):
    conn.execute('BEGIN')
    try:
        _, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
        batch = dict(_batch(conn, dataset_id, batch_id))
        if attempt_id:
            response = _public(_attempt(conn,dataset_id,batch_id,attempt_id), dataset['version'], batch)
        else:
            rows = conn.execute('SELECT a.*,u.username AS actor_username FROM processing_attempts a JOIN users u ON u.id=a.actor_id '
                                'WHERE a.dataset_id=? AND a.batch_id=? ORDER BY a.created_at DESC,a.rowid DESC LIMIT 51',(dataset_id,batch_id)).fetchall()
            response = {'items': [_public(row,dataset['version'],batch) for row in rows[:50]], 'has_more': len(rows)>50,
                        'dataset_version': dataset['version'], 'revision_version': batch['revision_version'],
                        'revision_state': batch['state']}
        from .authorization_controls import synthetic_batch
        response['synthetic_data']=synthetic_batch(conn,batch_id)
    finally:
        conn.rollback()
    authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    return response


def enqueue(conn, token_hash, dataset_id, batch_id, expected_dataset_version, expected_revision_version,
            request_key, *, previous_id=None, expected_attempt_version=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', request_key):
        raise Problem(422, 'Identificador de solicitud inválido')
    with transaction(conn):
        user, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
        old = _attempt(conn,dataset_id,batch_id,previous_id) if previous_id else None
        if old:
            expected_dataset_version, expected_revision_version = old['expected_dataset_version'], old['expected_revision_version']
        repeated = conn.execute('SELECT * FROM processing_attempts WHERE dataset_id=? AND request_key=?',
                                (dataset_id,request_key)).fetchone()
        if repeated:
            if (repeated['actor_id'],repeated['batch_id'],repeated['previous_id'],repeated['expected_dataset_version'],repeated['expected_revision_version']) != (
                    user['id'],batch_id,previous_id,expected_dataset_version,expected_revision_version):
                raise Problem(409, 'Ese identificador corresponde a otra solicitud')
            batch = dict(_batch(conn,dataset_id,batch_id))
            return _public(repeated,dataset['version'],batch), False
        if old:
            child = conn.execute('SELECT * FROM processing_attempts WHERE previous_id=?',(old['id'],)).fetchone()
            if child:
                batch = dict(_batch(conn,dataset_id,batch_id))
                return _public(child,dataset['version'],batch), False
            if old['version'] != expected_attempt_version:
                raise Problem(409, 'El intento cambió; actualizá su estado antes de reintentar')
            _recover(conn,old)
            if not (_expired(old) or old['state'] in RETRYABLE):
                raise Problem(409, 'Ese intento no admite reintento; consultar su estado o iniciar otro análisis')
        check_version(dataset,expected_dataset_version)
        batch, input_sha, total = _inputs(conn,dataset_id,batch_id)
        if batch['revision_version'] != expected_revision_version or (old and old['input_sha256'] != input_sha):
            raise Problem(409, 'Los datos cambiaron. Iniciá un análisis nuevo, no un reintento')
        active = conn.execute("SELECT * FROM processing_attempts WHERE batch_id=? AND state IN ('queued','running')",(batch_id,)).fetchone()
        if active:
            _recover(conn,active)
            if not _expired(active):
                raise Problem(409, 'Ya hay un intento en espera o ejecutándose para este lote. Consultá Procesamiento')
        identity, stamp = str(uuid4()), _stamp()
        conn.execute("INSERT INTO processing_attempts(id,dataset_id,batch_id,actor_id,session_hash,request_key,previous_id,"
                     "expected_dataset_version,expected_revision_version,input_sha256,state,stage,total_rows,created_at) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?,'queued','queued',?,?)",(identity,dataset_id,batch_id,user['id'],token_hash,
                     request_key,previous_id,expected_dataset_version,expected_revision_version,input_sha,total,stamp))
        event(conn,user['id'],'processing_requested','processing_attempt',identity)
        row = _attempt(conn,dataset_id,batch_id,identity)
        return _public(row,dataset['version'],batch), True


def retry(conn, token_hash, dataset_id, batch_id, attempt_id, request_key, expected_attempt_version):
    return enqueue(conn,token_hash,dataset_id,batch_id,None,None,request_key,
                   previous_id=attempt_id,expected_attempt_version=expected_attempt_version)


def recover_expired(conn):
    ids = conn.execute("SELECT id FROM processing_attempts WHERE state='running' AND lease_until<=?",(time.time(),)).fetchall()
    if ids:
        with transaction(conn):
            for (identity,) in ids:
                row = conn.execute('SELECT * FROM processing_attempts WHERE id=?',(identity,)).fetchone()
                _recover(conn,row)


def claim(conn, owner, *, lease_seconds=LEASE_SECONDS):
    if not conn.execute("SELECT 1 FROM processing_attempts WHERE state='queued' LIMIT 1").fetchone():
        return None
    with transaction(conn):
        row = conn.execute("SELECT * FROM processing_attempts WHERE state='queued' ORDER BY created_at,rowid LIMIT 1").fetchone()
        if row is None:
            return None
        conn.execute("UPDATE processing_attempts SET state='running',stage='validating',owner_id=?,lease_until=?,"
                     "started_at=?,heartbeat_at=?,version=version+1 WHERE id=? AND state='queued'",
                     (owner,time.time()+lease_seconds,_stamp(),_stamp(),row['id']))
        return dict(conn.execute('SELECT * FROM processing_attempts WHERE id=?',(row['id'],)).fetchone())


class AttemptInterrupted(Exception):
    pass


class Monitor:
    def __init__(self, root, job, stop, *, lease_seconds=LEASE_SECONDS, heartbeat_interval=1, publish_lease_seconds=PUBLISH_LEASE_SECONDS):
        self.root,self.job,self.stop = Path(root),job,stop
        self.lease_seconds,self.interval = lease_seconds,heartbeat_interval
        self.publish_lease_seconds=publish_lease_seconds
        self.done = threading.Event()

    def check(self, conn):
        row = conn.execute('SELECT * FROM processing_attempts WHERE id=?',(self.job['id'],)).fetchone()
        if self.stop.is_set() or row is None or row['owner_id'] != self.job['owner_id'] or row['state'] != 'running' or _expired(row):
            raise AttemptInterrupted()

    def publication_guard(self, conn):
        self.check(conn)
        batch = _batch(conn,self.job['dataset_id'],self.job['batch_id'])
        if batch['revision_version'] != self.job['expected_revision_version']:
            raise Problem(409, 'La revisión cambió desde la solicitud')

    def pulse(self, stage=None, processed=None, total=None):
        if self.stop.is_set():
            raise AttemptInterrupted()
        conn = connect(self.root,timeout=.1)
        try:
            self.check(conn)
            with transaction(conn):
                self.check(conn)
                row = conn.execute('SELECT stage FROM processing_attempts WHERE id=?',(self.job['id'],)).fetchone()
                duration = self.publish_lease_seconds if (stage or row['stage'])=='publishing' else self.lease_seconds
                conn.execute('UPDATE processing_attempts SET stage=COALESCE(?,stage),processed_rows=MAX(processed_rows,COALESCE(?,processed_rows)),'
                             'total_rows=COALESCE(?,total_rows),heartbeat_at=?,lease_until=? WHERE id=?',
                             (stage,processed,total,_stamp(),time.time()+duration,self.job['id']))
        except sqlite3.OperationalError as exc:
            if getattr(exc,'sqlite_errorcode',0) & 0xff not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):
                raise
        finally:
            conn.close()

    def heartbeat(self):
        while not self.done.wait(self.interval):
            try:
                self.pulse()
            except (AttemptInterrupted,sqlite3.Error):
                return

    def complete(self, conn, run_id, created):
        self.check(conn)
        authorized_dataset(conn,self.job['session_hash'],self.job['dataset_id'],'reviewer')
        conn.execute("UPDATE processing_attempts SET state='completed',stage='completed',processed_rows=CASE WHEN ? THEN COALESCE(total_rows,processed_rows) ELSE processed_rows END,"
                     "finished_at=?,heartbeat_at=?,result_run_id=?,result_created=?,lease_until=NULL,version=version+1 WHERE id=?",
                     (int(created),_stamp(),_stamp(),run_id,int(created),self.job['id']))


def execute(root, job, stop=None, *, lease_seconds=LEASE_SECONDS, heartbeat_interval=1, publish_lease_seconds=PUBLISH_LEASE_SECONDS, progress_hook=None, publication_hook=None):
    """Hooks are for deterministic process/crash tests, never configured by HTTP input."""
    stop = stop or threading.Event()
    monitor = Monitor(root,job,stop,lease_seconds=lease_seconds,heartbeat_interval=heartbeat_interval,publish_lease_seconds=publish_lease_seconds)
    heartbeat = threading.Thread(target=monitor.heartbeat,daemon=True);heartbeat.start()
    conn = None
    try:
        conn = connect(Path(root))
        monitor.publication_guard(conn)
        def progress(stage,done,total):
            monitor.pulse(stage,done,total)
            if progress_hook:
                progress_hook(stage,done,total)
        def published(connection,run_id,created):
            if publication_hook:
                publication_hook(connection,run_id)
            monitor.complete(connection,run_id,created)
        run_controls(conn,job['session_hash'],job['dataset_id'],job['batch_id'],job['expected_dataset_version'],
                     progress=progress,before_publish=monitor.publication_guard,published=published,expected_input_sha256=job['input_sha256'])
    except Exception as exc:
        if conn is not None and conn.in_transaction:
            conn.rollback()
        state,code = 'failed','processing_error'
        if isinstance(exc,AttemptInterrupted):
            state,code = 'interrupted','server_stopped' if stop.is_set() else 'activity_lost'
        elif isinstance(exc,Problem):
            state,code = 'blocked','permission_changed' if exc.status in (401,403) else 'inputs_changed'
        elif isinstance(exc,sqlite3.OperationalError):
            code = 'storage_busy'
        if conn is not None:
            try:
                with transaction(conn):
                    conn.execute("UPDATE processing_attempts SET state=?,error_code=?,error_type=?,finished_at=?,lease_until=NULL,version=version+1 "
                                 "WHERE id=? AND state='running' AND owner_id=?",(state,code,type(exc).__name__,_stamp(),job['id'],job['owner_id']))
            except sqlite3.Error:
                pass  # Without storage, lease expiry exposes interruption; never print raw exception data.
    finally:
        monitor.done.set();heartbeat.join(2)
        if conn is not None:
            conn.close()


class ProcessingManager:
    def __init__(self, root):
        self.root = Path(root)
        self.owner = str(uuid4())
        self.stop = threading.Event()
        self.worker = None
        self.thread = threading.Thread(target=self.loop,daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set();self.thread.join(5)
        if self.worker:
            self.worker.join(5)
        coordinator_alive=self.thread.is_alive()
        worker_alive=bool(self.worker and self.worker.is_alive())
        if coordinator_alive or worker_alive:
            raise RuntimeError(f'Processing shutdown incomplete: coordinator_alive={coordinator_alive}, worker_alive={worker_alive}')

    def loop(self):
        while not self.stop.wait(.2):
            conn = None
            try:
                conn = connect(self.root,timeout=.1)
                recover_expired(conn)
                if self.worker is None or not self.worker.is_alive():
                    job = claim(conn,self.owner)
                    if job:
                        self.worker = threading.Thread(target=execute,args=(self.root,job,self.stop),daemon=True)
                        self.worker.start()
            except sqlite3.Error:
                pass  # Temporary contention: the next bounded poll retries the queue, not a failed attempt.
            finally:
                if conn is not None:
                    conn.close()

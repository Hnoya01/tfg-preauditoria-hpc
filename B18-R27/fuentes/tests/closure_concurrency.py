"""Fictional concurrency probe, contained as a process tree (never product code)."""
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
import traceback

# Operational budget for this one integration probe, including backup/ACL helpers.
# Correctness uses events only. The supervisor can kill the whole tree at this cap.
BUDGET_SECONDS = 60
CLEANUP_SECONDS = 5


class ProbeFailure(AssertionError):
    pass


class ProcessTree:
    """Attach before the stdin handshake permits any work or descendants."""
    def __init__(self, process):
        self.process = process
        self.job = None
        if os.name != 'nt':
            return
        import ctypes
        from ctypes import wintypes as w
        class Limits(ctypes.Structure):
            _fields_ = [('per_process', ctypes.c_longlong), ('per_job', ctypes.c_longlong),
                        ('flags', w.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t),
                        ('active', w.DWORD), ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Limits), ('io', ctypes.c_ulonglong * 6),
                        ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, args, result in (
            ('CreateJobObjectW', [w.LPVOID, w.LPCWSTR], w.HANDLE),
            ('SetInformationJobObject', [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD], w.BOOL),
            ('AssignProcessToJobObject', [w.HANDLE, w.HANDLE], w.BOOL),
            ('TerminateJobObject', [w.HANDLE, w.UINT], w.BOOL),
            ('QueryInformationJobObject', [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, w.LPVOID], w.BOOL),
            ('CloseHandle', [w.HANDLE], w.BOOL)):
            fn = getattr(self.api, name); fn.argtypes = args; fn.restype = result
        self.job = self.api.CreateJobObjectW(None, None)
        try:
            if not self.job:
                raise ctypes.WinError(ctypes.get_last_error())
            limits = Extended(); limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE
            if not self.api.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not self.api.AssignProcessToJobObject(self.job, w.HANDLE(process._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            if self.job:
                self.api.CloseHandle(self.job); self.job = None
            raise

    def stop(self):
        if os.name == 'nt':
            # Closing the job also kills native descendants, including PowerShell.
            if self.job:
                import ctypes
                from ctypes import wintypes as w
                class Accounting(ctypes.Structure):
                    _fields_ = [('times', ctypes.c_longlong * 4), ('faults', w.DWORD),
                                ('total', w.DWORD), ('active', w.DWORD), ('terminated', w.DWORD)]
                try:
                    if not self.api.TerminateJobObject(self.job, 1):
                        raise ctypes.WinError(ctypes.get_last_error())
                    end = time.monotonic() + CLEANUP_SECONDS
                    while True:
                        info = Accounting()
                        if not self.api.QueryInformationJobObject(self.job, 1, ctypes.byref(info), ctypes.sizeof(info), None):
                            raise ctypes.WinError(ctypes.get_last_error())
                        if not info.active:
                            break
                        if time.monotonic() >= end:
                            raise TimeoutError('job descendants did not terminate')
                        time.sleep(0.01)
                finally:
                    self.api.CloseHandle(self.job); self.job = None
        else:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.process.wait(timeout=CLEANUP_SECONDS)


def supervise(payload, directory, *, budget=BUDGET_SECONDS, expired=None):
    """Persist diagnostics, bound the complete probe, and reap before caller cleanup.

    expired is a regression-only trigger evaluated alongside the real deadline;
    it can shorten the budget after an observed checkpoint, never disable it.
    """
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=True)
    trace = directory / 'trace.jsonl'; result = directory / 'result.json'
    trace.write_text('', encoding='utf-8'); result.unlink(missing_ok=True)
    payload = {**payload, 'trace': str(trace), 'result': str(result)}
    config = directory / 'input.json'
    config.write_text(json.dumps(payload), encoding='utf-8')
    code = 'import sys;sys.path.insert(0,sys.argv[1]);from tests.closure_concurrency import child_main;child_main(sys.argv[2])'
    started = time.monotonic(); process = None; tree = None; failure = None
    with (directory / 'stderr.log').open('w', encoding='utf-8') as log:
        try:
            process = subprocess.Popen([sys.executable, '-I', '-B', '-c', code, str(Path.cwd()), str(config)],
                stdin=subprocess.PIPE, stdout=log, stderr=log, text=True,
                start_new_session=os.name != 'nt')
            tree = ProcessTree(process)
            process.stdin.write('1'); process.stdin.close()
            while process.poll() is None:
                if time.monotonic() - started >= budget or (expired and expired(trace)):
                    raise TimeoutError('global concurrency probe budget exhausted')
                try:
                    process.wait(timeout=0.02)
                except subprocess.TimeoutExpired:
                    pass
            if process.returncode:
                raise ProbeFailure(f'probe exit {process.returncode}')
            return json.loads(result.read_text(encoding='utf-8'))
        except BaseException as error:
            failure = error
            raise
        finally:
            cleanup = None
            if process is not None:
                try:
                    if tree is not None:
                        tree.stop()
                    else:
                        process.kill(); process.wait(timeout=CLEANUP_SECONDS)
                except BaseException as error:
                    cleanup = error
            try:
                if process is not None and process.stdin is not None:
                    process.stdin.close()
                config.unlink(missing_ok=True)
            except BaseException as error:
                cleanup = cleanup or error
            if failure is not None or cleanup is not None:
                # The first recorded worker/backup exception takes precedence over
                # a subsequent watchdog expiration or cleanup exception.
                diagnostic = trace.read_text(encoding='utf-8')
                log.flush()
                stderr = (directory / 'stderr.log').read_text(encoding='utf-8')
                raise ProbeFailure(f'{diagnostic}\n{stderr}\nSupervisor: {failure!r}; cleanup: {cleanup!r}; evidence: {directory}') from failure


def concurrent_probe(identities, close_one, backup, emit):
    """No local deadlines: release only after backup; cancellation never commits."""
    ready = queue.Queue(); proceed = threading.Event(); cancelled = threading.Event()
    results = []; errors = []; lock = threading.Lock()
    def report(error):
        with lock:
            if not errors:
                errors.append(error)
                emit('first_error', detail=''.join(traceback.format_exception(error)))
    def worker(identity):
        def prepared():
            emit('prepared', identity=identity); ready.put(('ready', identity))
            proceed.wait()
            if cancelled.is_set():
                raise RuntimeError('FICTICIO cancelled after probe failure')
        try:
            status = close_one(identity, prepared)
            with lock:
                results.append((identity, status))
            emit('closed', identity=identity, status=status)
        except BaseException as error:
            report(error); ready.put(('error', identity))
    workers = [threading.Thread(target=worker, args=(i,)) for i in identities]
    for thread in workers:
        thread.start()
    try:
        seen = set()
        while len(seen) != len(identities):
            kind, identity = ready.get()
            if kind == 'error':
                raise errors[0]
            seen.add(identity)
        if seen != set(identities):
            raise AssertionError('unexpected prepared identities')
        emit('backup_started')
        snapshot = backup()
        emit('backup_finished')
    except BaseException as error:
        report(error); cancelled.set()
    finally:
        emit('release', cancelled=cancelled.is_set()); proceed.set()
        for thread in workers:
            thread.join()  # Entire process tree has the independent global cap.
    if errors:
        raise errors[0]
    return {'results': results, **snapshot}


def child_main(config):
    if sys.stdin.read(1) != '1':
        raise RuntimeError('probe containment handshake absent')
    payload = json.loads(Path(config).read_text(encoding='utf-8'))
    root = Path.cwd().resolve()
    # Same Python file boundary as the official runner, inherited by worker threads.
    def inside(value, roots):
        if isinstance(value, (str, bytes, os.PathLike)):
            return any(Path(os.fsdecode(value)).resolve().is_relative_to(r) for r in roots)
        return True
    def audit(event, args):
        if event == 'open':
            path, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if not inside(path, (root,) if writing else (root, Path(sys.base_prefix).resolve())):
                raise PermissionError('Synthetic probe attempted external file access')
        elif event in ('os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod'):
            if not inside(args[0], (root,)):
                raise PermissionError('Synthetic probe attempted external mutation')
        elif event in ('os.rename', 'os.replace'):
            if not all(inside(p, (root,)) for p in args[:2]):
                raise PermissionError('Synthetic probe attempted external move')
    sys.addaudithook(audit)
    if sys.platform == 'linux':
        import mimetypes
        mimetypes.knownfiles = []; mimetypes.init()
    lock = threading.Lock()
    def emit(stage, **fields):
        with lock, open(payload['trace'], 'a', encoding='utf-8') as stream:
            stream.write(json.dumps({'stage': stage, 'monotonic': time.monotonic(), **fields}) + '\n'); stream.flush()
    if payload.get('mode'):
        outcome = synthetic_probe(payload, emit)
    else:
        from app.closure import close
        from app.db import connect
        from app.service import Problem
        from scripts.recovery_data import make_backup
        data = Path(payload['root'])
        def close_one(identity, prepared):
            c = connect(data); p = payload['pages'][identity]
            try:
                close(c, data, payload['digest'], payload['dataset'], identity,
                    p['dataset_version'], p['revision_version'], p['preview_sha256'],
                    [g['justification']['id'] for g in p['limitations']], after_prepare=prepared)
                return 'closed'
            except Problem as error:
                return error.status
            finally:
                c.close()
        def backup():
            manifest, sha = make_backup(data, data/'backups'/'concurrent', Path(payload['release']), data_kind='synthetic')
            assert len(manifest['logical_state']['unregistered_objects']) == 2
            assert manifest['logical_state']['tables']['revision_closures']['count'] == 0
            return {'manifest': manifest, 'sha': sha}
        outcome = concurrent_probe(list(payload['pages']), close_one, backup, emit)
    Path(payload['result']).write_text(json.dumps(outcome), encoding='utf-8')


def synthetic_probe(payload, emit):
    """Controlled fault injection; these modes never touch application data."""
    mode = payload['mode']
    def close_one(identity, prepared):
        if mode == 'worker_error' and identity == 'a':
            raise ValueError('FICTICIO original worker failure')
        if mode == 'missing_signal' and identity == 'a':
            emit('blocked_worker'); threading.Event().wait()
        try:
            prepared()
        finally:
            if mode == 'backup_error_blocked_cleanup':
                emit('cleanup_blocked'); threading.Event().wait()
        return 'closed' if identity == 'a' else 409
    def backup():
        if mode in ('blocked_backup', 'backup_error_blocked_cleanup'):
            # A native descendant exercises process-tree cleanup as well as threads.
            descendant = subprocess.Popen([sys.executable, '-I', '-c',
                'import sys,time,sqlite3;from pathlib import Path;'
                'c=sqlite3.connect(sys.argv[1]);c.execute("CREATE TABLE held (id)");'
                'c.execute("BEGIN EXCLUSIVE");Path(sys.argv[1]+".ready").touch();time.sleep(300)', payload['held']])
            while not Path(payload['held']+'.ready').exists():
                if descendant.poll() is not None:
                    raise RuntimeError('FICTICIO descendant failed before lock')
                time.sleep(0.01)
            emit('descendant', pid=descendant.pid)
            if mode == 'backup_error_blocked_cleanup':
                raise ValueError('FICTICIO original backup failure')
            emit('blocked_backup'); threading.Event().wait()
        if mode == 'backup_error':
            raise ValueError('FICTICIO original backup failure')
        return {}
    return concurrent_probe(['a', 'b'], close_one, backup, emit)

"""Run from the extracted application with -I; only fictional recovery fixtures."""
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
import uvicorn


def main():
    from app.api import create_app
    from app.db import connect
    from scripts.recovery_data import activate_quarantined
    source=Path(__file__).resolve().parents[1]
    root=Path(sys.argv[1]);instructions=json.loads(Path(sys.argv[2]).read_text());output=Path(sys.argv[3])
    before=hashlib.sha256((root/'app.sqlite3').read_bytes()).hexdigest()
    try:
        with TestClient(create_app(root)):pass
    except RuntimeError as error:
        if 'recuperaci' not in str(error):raise
    else:raise AssertionError('Quarantine did not block startup')
    assert hashlib.sha256((root/'app.sqlite3').read_bytes()).hexdigest()==before
    with patch('scripts.recovery_data.os.replace',side_effect=OSError('FICTICIO interrupted activation receipt')):
        try:activate_quarantined(root)
        except OSError:pass
        else:raise AssertionError('Interrupted receipt was not injected')
    try:connect(root)
    except RuntimeError:pass
    else:raise AssertionError('Missing activation receipt accepted')
    receipt=activate_quarantined(root);assert activate_quarantined(root)==receipt
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    origin=f'http://127.0.0.1:{port}'
    app=create_app(root,public_origin=origin,local_http=True)
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    try:
        deadline=time.monotonic()+10
        while not server.started:
            if not thread.is_alive() or time.monotonic()>=deadline:raise AssertionError('Restored loopback API did not start')
            time.sleep(.02)
        with httpx.Client(base_url=origin,trust_env=False) as client:
            client.cookies.set('tfg_session',os.environ['TFG_PROBE_OLD_COOKIE'])
            assert client.get('/api/me').status_code==401
            response=client.post('/api/session',headers={'Origin':origin},json={'username':'owner','password':os.environ['TFG_PROBE_PASSWORD']})
            assert response.status_code==200
            base=f'/api/datasets/{instructions["dataset_id"]}/batches/{instructions["batch_id"]}'
            history=client.get(base+'/revisions');assert history.status_code==200
            assert len(history.json()['items'])==2
            for record in instructions['closures']:
                response=client.get(base+'/export-closed',params={'revision_id':record['revision_id']})
                assert response.status_code==200
                assert hashlib.sha256(response.content).hexdigest()==record['sha256']
                summary=client.get(base+'/closure-summary',params={'revision_id':record['revision_id']})
                assert summary.status_code==200 and summary.json()['frozen'] and summary.json()['limitations']
            assert app.state.processing_manager is None
        with httpx.Client(base_url=origin,trust_env=False) as viewer:
            assert viewer.post('/api/session',headers={'Origin':origin},json={'username':'viewer','password':os.environ['TFG_PROBE_PASSWORD']}).status_code==200
            assert viewer.get(base+'/export-closed').status_code==403
        modules={name:str(Path(module.__file__).resolve()) for name,module in sys.modules.items()
                 if name.split('.')[0] in ('app','scripts') and getattr(module,'__file__',None)}
        assert all(Path(value).is_relative_to(source) for value in modules.values()),modules
        output.write_text(json.dumps({'application_root':str(source),'module_paths':modules,
            'quarantine_blocked':True,'interrupted_activation_retried':True,'old_session_revoked':True,
            'new_login':True,'loopback_api':True,'workers_disabled':True,'two_closed_hashes_intact':True,
            'viewer_denied':True,'same_machine_drill_not_disaster_recovery':True},indent=2))
    finally:
        server.should_exit=True;thread.join(10);sock.close()
        assert not thread.is_alive()


if __name__=='__main__':main()

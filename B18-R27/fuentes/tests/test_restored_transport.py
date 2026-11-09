"""Exercise the extracted recovery probe with local-only proxy sentinels."""
import json
import os
from pathlib import Path
import socket
import subprocess
import unittest
from unittest.mock import patch

from tests import test_audit_fixes as fixtures


PROXY_KEYS=('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY',
            'http_proxy','https_proxy','all_proxy','no_proxy')
NETWORK_GUARD='''import sys
def local_network_only(event,args):
    if event in ('socket.connect','socket.bind'):
        address=args[1]
        if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1'):
            raise AssertionError('Recovery transport regression attempted non-loopback networking')
    elif event=='socket.getaddrinfo' and args[0] not in ('127.0.0.1','::1',b'127.0.0.1',b'::1'):
        raise AssertionError('Recovery transport regression attempted external name resolution')
sys.addaudithook(local_network_only)
'''


class RestoredTransportTests(unittest.TestCase):
    def exercise(self,with_proxy):
        original_run=subprocess.run;guarded=[]
        def run(command,*args,**kwargs):
            command=list(command)
            if len(command)>4 and command[1:4]==['-I','-B','-c'] and 'from tests.restored_probe import main;main()' in command[4]:
                command[4]=NETWORK_GUARD+command[4];guarded.append(True)
            return original_run(command,*args,**kwargs)
        with socket.socket() as sentinel:
            sentinel.bind(('127.0.0.1',0));sentinel.listen(1);sentinel.setblocking(False)
            proxy=f'socks5://127.0.0.1:{sentinel.getsockname()[1]}'
            case=fixtures.AuditWorkflowTests();case.setUp()
            try:
                with patch.dict(os.environ):
                    for key in PROXY_KEYS:os.environ.pop(key,None)
                    if with_proxy:
                        for key in PROXY_KEYS:
                            os.environ[key]='' if key.lower()=='no_proxy' else proxy
                    with patch('tests.test_audit_fixes.subprocess.run',side_effect=run):
                        case.test_integrated_conflict_two_reviews_backup_and_own_restored_application()
                    self.assertEqual(os.environ.get('ALL_PROXY'),proxy if with_proxy else None)
                self.assertEqual(len(guarded),1,'The extracted application must run behind the network guard')
                try:connection,_=sentinel.accept()
                except BlockingIOError:pass
                else:
                    connection.close();self.fail('The recovery probe attempted to use the inherited proxy')
                result=json.loads(Path('.test-results/audit-restored-application.json').read_text())
                self.assertTrue(result['two_closed_hashes_intact']);self.assertTrue(result['viewer_denied'])
                result.update(inherited_proxy=with_proxy,external_network_rejected_by_test_guard=True,proxy_connections=0)
                target=Path('.test-results')/('n1-restored-with-proxy.json' if with_proxy else 'n1-restored-without-proxy.json')
                target.write_text(json.dumps(result,indent=2))
            finally:case.tearDown()

    def test_restored_application_ignores_inherited_socks_proxies(self):self.exercise(True)

    def test_restored_application_works_without_proxy_environment(self):self.exercise(False)

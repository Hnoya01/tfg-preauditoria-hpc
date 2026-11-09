"""Abre la demo ficticia indicada por nombre, en un puerto local libre por defecto."""
from pathlib import Path
import socket
import argparse
import sqlite3
from contextlib import closing
import uvicorn
from app.api import create_app

ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('port',type=int,nargs='?',default=0)
    parser.add_argument('--name',default='presentacion-HPC')
    parser.add_argument('--abrir',action='store_true',help='Abrir la demo ficticia en el navegador local')
    args=parser.parse_args()
    if not args.name.replace('-','').replace('_','').isalnum():raise SystemExit('Nombre ficticio inválido.')
    directory=(ROOT/'.tmp'/args.name).resolve()
    if directory.parent!=(ROOT/'.tmp').resolve():raise SystemExit('Destino inválido.')
    db=directory/'app.sqlite3'
    if not db.is_file():raise SystemExit('Falta la demo preparada.')
    with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as conn:
        labels=[r[0] for r in conn.execute('SELECT label FROM datasets')]
        if not labels or any(not s.startswith('DEMO FICTICIO') for s in labels):
            raise SystemExit('Esta no es la base ficticia de presentación.')
    sock=socket.socket()
    port=args.port
    sock.bind(('127.0.0.1',port));sock.listen()
    url='http://127.0.0.1:'+str(sock.getsockname()[1])
    print(url,flush=True)
    class DemoServer(uvicorn.Server):
        async def startup(self,sockets=None):
            await super().startup(sockets=sockets)
            if self.started and args.abrir:
                import webbrowser
                webbrowser.open(url)
    try:
        DemoServer(uvicorn.Config(create_app(directory,public_origin=url,local_http=True),log_level='warning')).run(sockets=[sock])
    finally:sock.close()
if __name__=='__main__':main()

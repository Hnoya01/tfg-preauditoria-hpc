"""Generate a fresh presentation with independent TAC and mixed-order datasets."""
import argparse,sys
from pathlib import Path
from unittest.mock import patch
from scripts import create_review_journey_demo as base
from scripts.create_r22_mixed import prepare
from app.db import connect
from app.security import token_digest,issue_session

def confirm_demo_coverage(c,root,token):
    from app.authorization_matching import save_scope
    from app.controls import run_controls
    row=c.execute("SELECT b.dataset_id,b.id FROM batches b WHERE original_name='FICTICIO_presupuesto_TAC.xlsx'").fetchone()
    ds,bid=row
    def version():return c.execute('SELECT version FROM datasets WHERE id=?',(ds,)).fetchone()[0]
    cap=c.execute('SELECT id FROM authorization_captures WHERE dataset_id=?',(ds,)).fetchone()[0]
    save_scope(c,root,token,ds,bid,version(),[cap],'real_unvalidated','El generador ficticio incluye la única orden de esta factura para todo el período.',
               csv_complete_from='2026-06-03',csv_complete_until='2026-08-04')
    run_controls(c,token,ds,bid,version())


def main():
    p=argparse.ArgumentParser();p.add_argument('--name',default='presentacion-HPC');args=p.parse_args()
    with patch.object(sys,'argv',['demo','--presupuesto','--name',args.name]):base.main()
    root=Path(__file__).resolve().parents[1]/'.tmp'/args.name
    c=connect(root)
    try:
        u=c.execute("SELECT id FROM users WHERE username='demo-admin'").fetchone()[0]
        token=token_digest(issue_session(c,u)[0])
        confirm_demo_coverage(c,root,token)
        prepare(c,root,token);c.execute('DELETE FROM sessions')
        print('Dos conjuntos ficticios preparados. Sin decisiones administrativas o cierres.')
    finally:c.close()
if __name__=='__main__':main()

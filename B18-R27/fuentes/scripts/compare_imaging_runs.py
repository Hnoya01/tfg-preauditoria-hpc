"""Compare two local runs, each with its own engine, exposing only aggregate counts."""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

READ = """
from pathlib import Path
import json, sqlite3, sys
from app.authorization_matching import _index,_context
from app.csv_coverage import coverage
from app.practice_families import catalog_families,classify_family
root=Path(sys.argv[1]).resolve()/'datos'
conn=sqlite3.connect((root/'app.sqlite3').as_uri()+'?mode=ro',uri=True)
conn.row_factory=sqlite3.Row
conn.execute('PRAGMA query_only=ON')
try:
 b=conn.execute('select b.id,b.dataset_id,b.source_sha256,i.id as imp from batches b join current_invoice_imports i on i.batch_id=b.id').fetchone()
 _,caps,issues=_context(conn,root,b['dataset_id'],b['id'],budgets=True)
 assert not issues and caps
 areas,names,_=catalog_families(conn,root,b['dataset_id'])
 nums=set()
 for r in conn.execute("select source_row,permitted_json from invoice_rows where import_id=? and disposition='included'",(b['imp'],)):
  fields=json.loads(r['permitted_json'])
  if classify_family(fields['E'],areas,fields['K'],names)[0]=='images':nums.add(r['source_row'])
 signals=coverage(conn,b['dataset_id'],b['id'],nums,_index(caps),captures=caps,root=root,image_numbers=nums)
 print(json.dumps([b['source_sha256'],sorted(c['source_sha256'] for c in caps),
                   {n:signals.get((b['imp'],n),{}).get('status','unresolved') for n in nums}]))
finally:conn.close()
"""


def read(source,private):
    result=subprocess.run([sys.executable,'-B','-c',READ,str(private.resolve())],
                          cwd=source.resolve(),capture_output=True,check=True,encoding='utf-8')
    return json.loads(result.stdout)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-r24',required=True,type=Path)
    parser.add_argument('--run-r24',required=True,type=Path)
    parser.add_argument('--run-r25',required=True,type=Path)
    args=parser.parse_args()
    invoice,auth,old=read(args.source_r24,args.run_r24)
    current_invoice,current_auth,new=read(Path(__file__).resolve().parents[1],args.run_r25)
    assert invoice==current_invoice and auth==current_auth and set(old)==set(new)
    recorded=json.loads((args.run_r25/'resultado-agregado.json').read_text(encoding='utf-8'))
    assert Counter(new.values())==recorded['estados_motor']
    supported={'units_supported','one_unit_supported','component_supported'}
    transitions=Counter((old[n],new[n]) for n in old)
    print(json.dumps(dict(filas=len(old),ganaron_aval=sum(v for (a,b),v in transitions.items() if a not in supported and b in supported),
          perdieron_aval=sum(v for (a,b),v in transitions.items() if a in supported and b not in supported),
          transiciones=[{'antes':a,'ahora':b,'cantidad':v} for (a,b),v in sorted(transitions.items())]),ensure_ascii=True))


if __name__=='__main__':
    main()


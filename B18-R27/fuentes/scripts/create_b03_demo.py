"""Generate deterministic invented B03 source pairs, without reading real data."""
import argparse
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from scripts.create_b02_demo import capture
from tests.test_p02 import book


def sources():
    data=deepcopy(capture())
    data['source'].update(system='demo-b03',capture_id='FICT-B03-1')
    for day in (19,20,21):
        order=deepcopy(data['orders'][0]);item=order['items'][0];r=order['resolutions'][0]
        order['order_id']=f'FICT-ORD-{day}'
        item.update(item_id=f'FICT-{day}-1',service_date=f'2026-08-{day}')
        r.update(resolution_id=f'FICT-R-{day}',item_ids=[item['item_id']],authorized_quantity='2',decided_at=f'2026-08-{day}T18:00:00-03:00')
        if day==19:r.update(scope='explicit_general',authorized_quantity=None,unit=None)
        if day==21:r['decided_at']='2026-08-21'
        data['orders'].append(order)
    original=book([(f'{d}/08/2026',10,20,30,'I' if d==18 else 'A') for d in range(15,22)])
    out=BytesIO()
    with ZipFile(BytesIO(original)) as src,ZipFile(out,'w') as dst:
        for name in sorted(src.namelist()):
            info=ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=ZIP_DEFLATED
            dst.writestr(info,src.read(name))
    examples={'data_origin':'synthetic','warning':'FICTICIO. Guía de declaraciones manuales; no es una captura A1 ni se importa por B01.',
        'rows':[{'source_row':row,'quantity_unit':'practica','incorporation':timestamp,'provenance':'Registro de incorporación totalmente ficticio B03.', 'locator':f'FICTICIO-B03!fila{row}'} for row,timestamp in
                [(2,'2026-08-15T19:00:00-03:00'),(6,'2026-08-19T19:00:00-03:00'),(7,'2026-08-20T17:00:00-03:00'),(8,'2026-08-21')]]}
    return {'B03_FICTICIO.xlsx':out.getvalue(),
            'B03_FICTICIO.json':(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode(),
            'B03_DATOS_COMPLEMENTARIOS_FICTICIOS.json':(json.dumps(examples,ensure_ascii=False,indent=2)+'\n').encode()}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,default=Path('.tmp/b03-demo-fixtures'));args=p.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    for name,content in sources().items():
        path=args.output_dir/name
        if path.exists() and path.read_bytes()!=content:raise SystemExit('No se sobrescribe un archivo distinto; elegir otro directorio')
        if not path.exists():path.write_bytes(content)
    print('B03 FICTICIO: fila 2 parcial; 3 contradictoria; 4 ambigua; 5 internación; 6 general expresa; 7 autorización posterior a incorporación; 8 mismo día sin hora. Complementarios: guía manual, no importable por A1.')


if __name__=='__main__':main()

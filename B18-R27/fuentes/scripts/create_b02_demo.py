"""Generate an invented X1 and canonical authorizations; never copy private sources."""

import argparse
import json
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from tests.test_p02 import book


def capture():
    orders = []
    for day in (15, 16, 17, 18):
        items = [{'item_id': f'FICT-{day}-1', 'full_code': '123456', 'description': 'Práctica ficticia',
                  'service_date': f'2026-08-{day}', 'requested_quantity': '2', 'unit': 'practica'}]
        if day == 17:
            items.append({**items[0], 'item_id': 'FICT-17-2'})
        resolutions = [{'resolution_id': f'FICT-R-{day}', 'scope': 'item', 'item_ids': [items[0]['item_id']],
                        'status': 'authorized', 'authorized_quantity': '1', 'unit': 'practica',
                        'decided_at': f'2026-08-{day}T18:00:00-03:00'}]
        if day == 16:
            resolutions.append({**resolutions[0], 'resolution_id': 'FICT-R-16-RECHAZO', 'status': 'rejected', 'authorized_quantity': '0'})
        orders.append({'order_id': f'FICT-ORD-{day}', 'affiliate_id': '1234', 'provider': 'HPC',
                       'global_status': 'authorized', 'items': items, 'resolutions': resolutions})
    return {'schema_version': 'A1-canonical-v1', 'data_origin': 'synthetic',
            'source': {'system': 'demo-b02', 'stream_id': 'agosto', 'capture_id': 'FICT-B02-1', 'captured_at': '2026-08-22'},
            'coverage': {'declared': 'partial', 'description': 'Casos enteramente inventados; cobertura real no validada.',
                         'period': '2026-08', 'limitations': ['Solo demostración ficticia B02.']}, 'orders': orders}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('.tmp/b02-demo-fixtures'))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    original=book([(f'{d}/08/2026', 10, 20, 30, 'I' if d == 18 else 'A') for d in (15, 16, 17, 18, 19)])
    output=BytesIO()
    with ZipFile(BytesIO(original)) as source, ZipFile(output,'w') as target:
        for name in sorted(source.namelist()):
            info=ZipInfo(name,date_time=(1980,1,1,0,0,0)); info.compress_type=ZIP_DEFLATED
            target.writestr(info,source.read(name))
    sources = {'B02_FICTICIO.xlsx': output.getvalue(),
               'B02_FICTICIO.json': (json.dumps(capture(), ensure_ascii=False, indent=2) + '\n').encode()}
    for name, data in sources.items():
        path = args.output_dir / name
        if path.exists() and path.read_bytes() != data:
            raise SystemExit('No se sobrescribe un archivo distinto; elegir otro directorio')
        if not path.exists():
            path.write_bytes(data)
    print('Fixtures B02 ficticios: filas 2 unívoca/parcial; 3 contradictoria; 4 ambigua; 5 internación; 6 sin coincidencia.')


if __name__ == '__main__':
    main()

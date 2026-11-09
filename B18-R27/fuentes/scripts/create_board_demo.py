"""Generate deterministic X1 fixtures for the workbench; no private source inputs."""

import argparse
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from tests.test_p02 import book


def canonical_book(rows):
    output=BytesIO()
    with ZipFile(BytesIO(book(rows))) as source, ZipFile(output,'w') as target:
        for name in sorted(source.namelist()):
            info=ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=ZIP_DEFLATED
            target.writestr(info,source.read(name))
    return output.getvalue()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=Path('.tmp/board-fixtures'))
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    rows=[('17/08/2026',10,20,39 if i in (80,990) else 30,'A') for i in range(1200)]
    rows += [('17/08/2026',10,20,30,'C'),('17/08/2026',10,20,30,'I'),('17/08/2026',10,20,30,'I'),
             ('01/09/2026',10,20,30,'A'),('17/08/2026',10,20,30,'X')]
    files={'DEMO_1205_FICTICIO.xlsx':canonical_book(rows),
           'DEMO_OTRAS_FICTICIO.xlsx':canonical_book([('17/08/2026',11,20,31)]*3)}
    for name,data in files.items():
        path=args.output_dir/name
        if path.exists() and path.read_bytes()!=data:
            raise SystemExit('No se sobrescribe un archivo distinto; elegir otro directorio')
        if not path.exists():
            path.write_bytes(data)
    print('Dos Excel enteramente ficticios: lote grande 1205 filas, 1201 elegibles, 3 excluidas, 1 indeterminada; lote comparador 3 filas.')
    print('Tras importar ambos y analizar explícitamente el grande: RN13 señala filas 82/992; RN17 candidatos filas 2/3/4. No son débitos.')


if __name__=='__main__':
    main()

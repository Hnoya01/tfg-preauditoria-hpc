"""Generate a bounded, deterministic, entirely fictional processing workbook."""
import argparse
from pathlib import Path
from scripts.create_board_demo import canonical_book


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rows',type=int,default=15000)
    parser.add_argument('--output-dir',type=Path,default=Path('.tmp/processing-fixtures'))
    args=parser.parse_args()
    if not 1<=args.rows<=100000:raise SystemExit('Usar entre 1 y 100000 filas ficticias')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    path=args.output_dir/f'PROCESAMIENTO_{args.rows}_FICTICIO.xlsx'
    content=canonical_book([('17/08/2026',10,20,30,'A')]*args.rows)
    if path.exists() and path.read_bytes()!=content:raise SystemExit('No se sobrescribe un archivo distinto')
    if not path.exists():path.write_bytes(content)
    print(f'Excel enteramente ficticio: {args.rows} filas. Importar en conjunto DEMO separado con agosto 2026. Analizar requiere una acción explícita.')


if __name__=='__main__':main()

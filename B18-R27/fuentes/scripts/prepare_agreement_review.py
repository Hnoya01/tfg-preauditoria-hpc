"""Cross-check public HPC/NBU values against original PDFs; no invoice input.

Install requirements-documentary.txt for extraction; not a core app dependency.
The output belongs in the private data directory. It is an automated source
observation, never an individual human decision or economic approval.
"""

from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from app.document_links import DOCUMENT_LINKS, REAL_V1_SHA


VERSION = 'P06-general-agreement-v1'
FILES = {'NBU-Version-2012-Act.-2016(1).pdf': 'NBU-Version-2012-Act.-2016.pdf',
         'Anexo-11.2023-NBU-2012-16-Final.pdf': 'Anexo-Noviembre-2023-de-Practicas-normas-e-interpretaciones.pdf',
         'Anexo-01.2024-NBU-2012.pdf': 'Anexo-01.2024-NBU-2012.pdf'}
AGREEMENT = 'IF-2026-82616470-APN-DCS_IOSFA-1.pdf'


def observe_factor(page_text: str, code: str, expected_milliunits: int) -> dict | None:
    """Require an exact code block ending in one unambiguous printed UB value."""
    matches = list(re.finditer(r'(?m)^\s*' + re.escape(code) + r'\s+(.+?)(?=\n\s*\d{6}\s|\Z)', page_text, re.S))
    if len(matches) != 1:
        return None
    block = matches[0].group(1).strip()
    block = re.split(r'\n\s*REFERENCIAS\b', block, maxsplit=1)[0].strip()
    end = re.search(r'(\d+,\d+)\s*(?:PMO|PE)?\s*$', block)
    if not end or Decimal(end.group(1).replace(',', '.')) * 1000 != expected_milliunits:
        return None
    return {'observed_factor_ub': end.group(1).replace(',', '.'),
            'specific_norm': bool(re.search(r'\bN\b', block[:end.start()])),
            'code_fragment': code + ' ' + ' '.join(block.split())}


def build_review(folder: Path) -> dict:
    from pypdf import PdfReader
    database = folder / 'Valores_Convenios_BASE_2026-10-09' / 'valores_convenios_base_2026-10-09.sqlite'
    if hashlib.sha256(database.read_bytes()).hexdigest() != REAL_V1_SHA:
        raise ValueError('La fuente no es el V1 inventariado')
    readers = {}
    for cited_name, name in {**FILES, AGREEMENT: AGREEMENT}.items():
        path = folder / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != DOCUMENT_LINKS[cited_name]:
            raise ValueError('Un PDF no coincide con el original inventariado')
        readers[cited_name] = PdfReader(path)
    page1 = readers[AGREEMENT].pages[0].extract_text()
    if not all(text in page1 for text in ('897,40', '01/06/2026', 'HOSPITAL PRIVADO', 'UNIDAD BIOQUIMICA')):
        raise ValueError('No se pudo verificar la cláusula de tarifa de U.B.')
    intro = readers['NBU-Version-2012-Act.-2016(1).pdf'].pages[2].extract_text()
    if not all(text in intro for text in ('Unidad Bioqu', 'cada pr', 'precio')):
        raise ValueError('No se pudo verificar la base por práctica del nomenclador')
    report = {'version': VERSION, 'producer': 'automated_pdf_text_crosscheck', 'economic_approval': False,
        'source_sha256': REAL_V1_SHA, 'cut_label': 'BASE_2026-10-09',
        'document_sha256s': sorted(set(DOCUMENT_LINKS.values())),
        'agreement': {'sha256': DOCUMENT_LINKS[AGREEMENT], 'page': 1, 'valid_from': '2026-06-01',
                      'ub_rate_cents': 89740, 'currency_basis': 'ARS_interpretation_from_Argentine_IOSFA_agreement_context',
                      'practice_unit_basis': {'sha256': DOCUMENT_LINKS['NBU-Version-2012-Act.-2016(1).pdf'], 'page': 3},
                      'scope': 'base_tariff_only_no_case_or_urgency_approval'},
        'references': [], 'unresolved': []}
    source = sqlite3.connect(f'file:{database.resolve().as_posix()}?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    pages = {}
    try:
        for tariff in source.execute("SELECT * FROM hpc_catalog_tariffs WHERE provider = 'HPC' ORDER BY seq"):
            data = json.loads(tariff['data_json'])
            calc = data.get('calculation', {})
            if calc.get('kind') != 'nbu':
                continue
            name, page = calc.get('catalogueSource'), calc.get('cataloguePage')
            key = (name, page)
            observation = None
            if name in readers and type(page) is int and 1 <= page <= len(readers[name].pages):
                if key not in pages:
                    pages[key] = readers[name].pages[page - 1].extract_text() or ''
                observation = observe_factor(pages[key], tariff['code'], calc.get('ubMilliunits'))
            if (observation is None or calc.get('rateCents') != 89740 or calc.get('rateSource') != AGREEMENT or
                    calc.get('ratePage') != 1 or calc.get('reviewRequired') is True or
                    Decimal(calc.get('ubMilliunits', 0)) * 89740 / 1000 != tariff['amount_cents'] or
                    tariff['valid_from'] != '2026-06-01'):
                report['unresolved'].append({'tariff_seq': tariff['seq'], 'code_complete': tariff['code'],
                                             'reason': 'factor_or_formula_not_unambiguously_crosschecked'})
                continue
            report['references'].append({'tariff_seq': tariff['seq'], 'code_complete': tariff['code'],
                'amount_cents': tariff['amount_cents'], 'document_sha256': DOCUMENT_LINKS[name], 'page': page,
                'ub_milliunits': calc['ubMilliunits'], 'urgency_marker_is_not_case_evidence': calc.get('urgent', False),
                **observation})
    finally:
        source.close()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = build_review(args.source_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2).encode()
    with args.output.open('xb') as output:
        output.write(content)
    counts = Counter('specific_norm' if r['specific_norm'] else 'base_reference' for r in report['references'])
    print(f"Cotejo documental automatizado: {len(report['references'])} factores reproducidos, "
          f"{len(report['unresolved'])} sin comprobación unívoca; grupos {dict(counts)}. "
          f"Informe privado SHA-256 {hashlib.sha256(content).hexdigest()}; sin aprobaciones económicas.")


if __name__ == '__main__':
    main()

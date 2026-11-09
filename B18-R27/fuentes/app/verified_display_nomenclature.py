"""Reviewed exact-code display evidence. Never supplies prices or equivalences.

Codes and families reviewed against Nomenclador.xlsx, Hoja1; labels are not
full clinical/normative transcriptions. Source hash identifies the original
shared document. No invoice or patient data is bundled here.
"""
SOURCE = {'source_id': 'reviewed-nomenclador-xlsx-v1',
          'source_file': 'Nomenclador.xlsx', 'sheet': 'Hoja1',
          'source_sha256': 'e50d52ee7d0329f8753e7c72d83e6554a11c410b979bb4947f1bad6819f410a2',
          'kind': 'reviewed_display_nomenclature', 'table': 'reviewed_document_excerpt'}
ENTRIES = (
    ('420101', 'Consultas', 1462, 'Consulta médica.'),
    ('420103', 'Consultas', 1463, 'Consulta médica en horario nocturno y/o días feriados.'),
    ('180109', 'Imágenes', 834, 'Ecografía oftalmológica uni o bilateral.'),
)
# Explicit reviewed modality/specialty overlap, not a blanket priority rule.
MODALITY = {'180109': {'allowed_areas': {'Imágenes', 'Oftalmología'},
                       'specialty': 'Oftalmología'}}
# Review shortlist only: invoice terminology suggests imaging but independent
# exact-code documentary support is absent. These codes never enter the index.
CANDIDATES = frozenset(('183004', '183007', '182002', '187010', '341053'))


def suggestion(code, family):
    if family != 'unclassified' or code not in CANDIDATES:
        return None
    return {'family': 'images', 'status': 'requires_manual_review',
            'reason': 'invoice_terminology_pending_exact_code_documentation',
            'label': 'Posible imagen: verificar código y documentación; no clasificada',
            'display_only': True, 'economic_equivalence_established': False}

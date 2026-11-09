"""Source-backed general tariff references, separate from individual approvals."""

import json
from decimal import Decimal
from pathlib import Path
import sqlite3
from uuid import uuid4

from .db import transaction
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event
from .storage import publish_bytes, read_verified
from .values_v1 import source_db


REVIEW_VERSION = 'P06-general-agreement-v1'


def _basis(conn, dataset_id, source_id, report):
    source = conn.execute("SELECT id, kind, status, source_sha256, cut_label, metadata_json FROM source_registry "
                          "WHERE dataset_id = ? AND id = ? AND kind = 'values' AND status = 'registered'",
                          (dataset_id, source_id)).fetchone()
    if source is None:
        raise Problem(404, 'Fuente de valores inexistente')
    if source['source_sha256'] != report['source_sha256'] or source['cut_label'] != report['cut_label']:
        raise Problem(409, 'El informe corresponde a otra fuente o corte')
    documents = []
    for sha in sorted(report['document_sha256s']):
        doc = conn.execute('SELECT * FROM evidence_documents WHERE dataset_id = ? AND source_id = ? AND sha256 = ?',
                            (dataset_id, source_id, sha)).fetchone()
        if doc is None:
            raise Problem(409, 'Falta un documento del cotejo en el conjunto')
        documents.append(dict(doc))
    return {'source': dict(source), 'documents': documents}


def register_agreement_review(conn: sqlite3.Connection, root: Path, token_hash: str, dataset_id: str,
                              source_id: str, expected_dataset_version: int, report: dict) -> dict:
    """Internal collector only; initiator is recorded, never a human approval."""
    if (report.get('version') != REVIEW_VERSION or report.get('producer') != 'automated_pdf_text_crosscheck' or
            report.get('economic_approval') is not False):
        raise Problem(422, 'Formato de cotejo documental no admitido')
    with transaction(conn):
        user, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
        check_version(dataset, expected_dataset_version)
        basis = _basis(conn, dataset_id, source_id, report)
        for sha in report['document_sha256s']:
            read_verified(root, sha)
        catalog = source_db(read_verified(root, report['source_sha256']))
        try:
            seen = set()
            for ref in report['references']:
                tariff = catalog.execute("SELECT code, amount_cents, data_json FROM hpc_catalog_tariffs WHERE provider = 'HPC' AND seq = ?",
                                          (ref['tariff_seq'],)).fetchone()
                if (tariff is None or tariff['code'] != ref['code_complete'] or tariff['amount_cents'] != ref['amount_cents'] or
                        ref['tariff_seq'] in seen or ref['document_sha256'] not in report['document_sha256s'] or
                        type(ref['specific_norm']) is not bool or type(ref['page']) is not int or ref['page'] < 1):
                    raise Problem(409, 'El informe no coincide con el arancel original')
                calculation = json.loads(tariff['data_json']).get('calculation', {})
                if (calculation.get('ubMilliunits') != ref['ub_milliunits'] or
                        Decimal(ref['observed_factor_ub']) * 1000 != ref['ub_milliunits'] or
                        Decimal(ref['ub_milliunits']) * report['agreement']['ub_rate_cents'] / 1000 != ref['amount_cents']):
                    raise Problem(409, 'El factor o la fórmula del informe no coinciden')
                seen.add(ref['tariff_seq'])
        finally:
            catalog.close()
        content = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        sha, size, relative = publish_bytes(root, content)
        prior = conn.execute('SELECT id, ordinal, report_sha256, basis_json FROM agreement_document_reviews WHERE source_id = ? '
                              'ORDER BY ordinal DESC LIMIT 1', (source_id,)).fetchone()
        if prior and prior['report_sha256'] == sha and json.loads(prior['basis_json']) == basis:
            return {'id': prior['id'], 'ordinal': prior['ordinal'], 'dataset_version': expected_dataset_version, 'created': False}
        conn.execute('INSERT OR IGNORE INTO stored_files VALUES (?, ?, ?, ?)', (sha, size, relative, now_utc()))
        ordinal = conn.execute('SELECT coalesce(max(ordinal), 0) + 1 FROM agreement_document_reviews WHERE source_id = ?',
                                (source_id,)).fetchone()[0]
        identity = str(uuid4())
        conn.execute('INSERT INTO agreement_document_reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                      (identity, dataset_id, source_id, ordinal, sha, json.dumps(basis, sort_keys=True), user['id'], now_utc()))
        conn.execute('UPDATE datasets SET version = version + 1 WHERE id = ?', (dataset_id,))
        event(conn, user['id'], 'automated_agreement_review_registered', 'agreement_document_review', identity)
    return {'id': identity, 'ordinal': ordinal, 'dataset_version': expected_dataset_version + 1, 'created': True}


def load_agreement_review(conn: sqlite3.Connection, root: Path, dataset_id: str, source_id: str) -> dict | None:
    record = conn.execute('SELECT * FROM agreement_document_reviews WHERE dataset_id = ? AND source_id = ? '
                          'ORDER BY ordinal DESC LIMIT 1', (dataset_id, source_id)).fetchone()
    if record is None:
        return None
    try:
        report = json.loads(read_verified(root, record['report_sha256']))
        saved = json.loads(record['basis_json'])
        source = conn.execute("SELECT id, kind, status, source_sha256, cut_label, metadata_json FROM source_registry WHERE dataset_id = ? AND id = ?",
                              (dataset_id, source_id)).fetchone()
        if source is None or dict(source) != saved['source']:
            raise Problem(409, 'La base documental cambió')
        read_verified(root, report['source_sha256'])
        affected = []
        for doc in saved['documents']:
            current = conn.execute('SELECT * FROM evidence_documents WHERE dataset_id = ? AND source_id = ? AND id = ?',
                                   (dataset_id, source_id, doc['id'])).fetchone()
            try:
                if current is None or dict(current) != doc:
                    raise ValueError('document changed')
                read_verified(root, doc['sha256'])
            except (ValueError, OSError, RuntimeError):
                affected.append(doc['sha256'])
        if report['version'] != REVIEW_VERSION or report['economic_approval'] is not False:
            raise ValueError('format')
        return {'id': record['id'], 'report_sha256': record['report_sha256'], 'freshness': 'current',
                'report': report, 'affected_document_sha256s': affected, 'economic_approval': False}
    except (Problem, OSError, ValueError, RuntimeError, KeyError, TypeError):
        return {'id': record['id'], 'freshness': 'requires_update', 'economic_approval': False, 'report': None}


def general_reference(item: dict, review: dict | None, cotejo: dict | None) -> dict:
    result = {'status': 'not_documented', 'economic_approval': False, 'proposal_amount_ars': None,
              'case_applicability_confirmed': False}
    if not review or review['freshness'] != 'current':
        return {**result, 'status': 'requires_update' if review else 'not_documented'}
    result['review_id'] = review['id']
    report = review['report']
    shared_documents = {report['agreement']['sha256'], report['agreement']['practice_unit_basis']['sha256']}
    shared_supported = (item['provider'] == 'HPC' and item['source_sha256'] == report['source_sha256'] and
                        item['value_cut'] == report['cut_label'] and item['practice_date'] is not None and
                        item['practice_date'] >= report['agreement']['valid_from'] and
                        not shared_documents.intersection(review.get('affected_document_sha256s', [])))
    result.update(shared_agreement_supported=shared_supported,
                  currency_basis=report['agreement']['currency_basis'], agreement=report['agreement'])
    tariff = item.get('tariff')
    ref = next((r for r in report['references'] if tariff and
                f"hpc_catalog_tariffs.seq={r['tariff_seq']}" == tariff['source_locator'] and
                r['code_complete'] == item['code_complete']), None)
    if not ref or item['disposition'] != 'included' or item['status'] not in {
            'numeric_equal', 'numeric_above_candidate', 'numeric_below_candidate'}:
        return result
    required_documents = {report['agreement']['sha256'], report['agreement']['practice_unit_basis']['sha256'], ref['document_sha256']}
    if required_documents.intersection(review.get('affected_document_sha256s', [])):
        return {**result, 'status': 'requires_update', 'reason': 'dependent_document_changed'}
    if cotejo and not cotejo['usable_match']:
        return {**result, 'status': 'requires_update', 'reason': 'individual_observation_conflicts_or_affected'}
    if (item['source_sha256'] != report['source_sha256'] or item['value_cut'] != report['cut_label'] or
            item['practice_date'] < report['agreement']['valid_from'] or tariff['amount_cents'] != ref['amount_cents']):
        return result
    return {**result, 'status': 'requires_case_interpretation' if ref['specific_norm'] else 'supported_base_reference',
            'rate_per_practice_ars': format(Decimal(ref['amount_cents']) / 100, '.2f'),
            'general_row_value_ars': item['candidate_total_if_ars_and_same_unit'],
            'currency': 'ARS', 'currency_basis': report['agreement']['currency_basis'],
            'quantity_basis': 'G_as_count_of_exact_NBU_practice_for_base_reference',
            'valid_from': report['agreement']['valid_from'], 'valid_until': tariff['valid_until'],
            'validity_basis': 'available_agreement_at_explicit_source_cut',
            'no_end_date_is_not_expiry': tariff['valid_until'] is None,
            'factor_observation': ref, 'agreement': report['agreement'],
            'warnings': ['Specific applicable accepted agreements prevail; none is presumed absent.',
                         'No urgency or other additions are included in this base value.']}

"""Versioned human code/page/factor observations, separate from economic approval."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import re
from pathlib import Path
import sqlite3
from uuid import uuid4

from .db import transaction
from .document_links import _document
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event
from .storage import read_verified
from .values_v1 import source_db


def _factor(value: object) -> str:
    if not isinstance(value, str) or len(value) > 32:
        raise Problem(422, "El factor debe ser un decimal en texto, con hasta tres decimales")
    try:
        amount = Decimal(value)
        if (not amount.is_finite() or amount < 0 or amount > Decimal('1000000000') or
                amount.quantize(Decimal('0.001')) != amount):
            raise InvalidOperation
        return format(amount.quantize(Decimal('0.001')), 'f')
    except InvalidOperation as exc:
        raise Problem(422, "Factor U.B. inválido") from exc


def _context(conn: sqlite3.Connection, root: Path, dataset_id: str, source_id: str,
             provider: str, code: str, tariff_seq: int) -> dict:
    source = conn.execute("SELECT id, kind, status, source_sha256, manifest_sha256, cut_label, "
                          "source_version, captured_at, coverage_json, metadata_json FROM source_registry "
                          "WHERE id = ? AND dataset_id = ? AND kind = 'values' AND status = 'registered'",
                          (source_id, dataset_id)).fetchone()
    if source is None:
        raise Problem(404, "Fuente de valores registrada inexistente")
    try:
        catalog = source_db(read_verified(root, source['source_sha256']))
        try:
            tariff = catalog.execute("SELECT * FROM hpc_catalog_tariffs WHERE seq = ? AND provider = ? AND code = ?",
                                     (tariff_seq, provider, code)).fetchone()
            if tariff is None:
                raise Problem(404, "Arancel exacto inexistente en esa fuente")
            tariff = dict(tariff)
        finally:
            catalog.close()
        calculation = json.loads(tariff['data_json']).get('calculation', {})
        if calculation.get('kind') != 'nbu':
            raise Problem(422, "El arancel no declara un factor NBU interpretable")
        milliunits = calculation.get('ubMilliunits')
        if not isinstance(milliunits, int) or isinstance(milliunits, bool):
            raise Problem(422, "La fuente no declara unidades NBU precisas")
        expected_factor = _factor(str(Decimal(milliunits) / 1000))
        documents = [dict(row) for row in conn.execute(
            "SELECT * FROM evidence_documents WHERE dataset_id = ? AND source_id = ?",
            (dataset_id, source_id))]
        linked = _document(calculation.get('catalogueSource'), source['source_sha256'], documents, 'nomenclator')
        document = next((doc for doc in documents if doc['id'] == linked.get('document_id')), None)
        if document is None:
            raise Problem(409, "Falta el anexo NBU registrado y vinculado a esta edición del catálogo")
        content = read_verified(root, document['sha256'])
        if not content.startswith(b'%PDF-'):
            raise Problem(409, "El original registrado no es un PDF")
    except (OSError, RuntimeError, ValueError, sqlite3.Error, TypeError, AttributeError) as exc:
        raise Problem(409, "No se pudo comprobar la fuente o el PDF original") from exc
    return {'version': 'P06-documentary-basis-v1', 'source': dict(source), 'tariff': tariff,
            'document': document, 'catalogue_factor': expected_factor, 'factor_unit': 'UB',
            'catalogue_document': calculation.get('catalogueSource'),
            'catalogue_page': calculation.get('cataloguePage'), 'link_basis': linked['link_basis']}


class DocumentaryEvaluator:
    """Cache source/document checks within an authorized read snapshot."""

    def __init__(self, conn: sqlite3.Connection, root: Path, dataset_id: str):
        self.conn, self.root, self.dataset_id = conn, root, dataset_id
        self.contexts: dict[tuple, dict | None] = {}

    def evaluate(self, record: sqlite3.Row | dict) -> dict:
        basis = json.loads(record['basis_json'])
        key = (record['source_id'], record['provider'], record['code_complete'], record['tariff_seq'])
        if key not in self.contexts:
            try:
                self.contexts[key] = _context(self.conn, self.root, self.dataset_id, *key)
            except Problem:
                self.contexts[key] = None
        context = self.contexts[key]
        reasons = []
        if context is None:
            reasons.append('source_or_document_unavailable')
        elif context != basis:
            reasons.append('documentary_basis_changed')
        result = dict(record)
        result.pop('basis_json')
        result.update(basis_at_save=basis, freshness='requires_update' if reasons else 'current',
                      invalid_reasons=reasons, economic_approval=False,
                      usable_match=not reasons and record['conclusion'] == 'matches')
        return result


def latest_assessment(conn: sqlite3.Connection, source_id: str, provider: str, code: str, tariff_seq: int):
    return conn.execute("SELECT * FROM documentary_assessments WHERE source_id = ? AND provider = ? "
                        "AND code_complete = ? AND tariff_seq = ? ORDER BY ordinal DESC LIMIT 1",
                        (source_id, provider, code, tariff_seq)).fetchone()


def reference_documentary_dependency(conn: sqlite3.Connection, root: Path, dataset_id: str,
                                     verification: dict, evaluator: DocumentaryEvaluator | None = None) -> dict | None:
    locator = re.fullmatch(r'hpc_catalog_tariffs\.seq=(\d+)', verification['tariff_locator'])
    if not locator:
        return None
    record = latest_assessment(conn, verification['source_id'], verification['provider'],
                               verification['code_complete'], int(locator.group(1)))
    if record is None:
        return None
    return (evaluator or DocumentaryEvaluator(conn, root, dataset_id)).evaluate(record)


def save_documentary_assessment(conn: sqlite3.Connection, root: Path, token_hash: str,
                                dataset_id: str, source_id: str, expected_dataset_version: int,
                                provider: str, code_complete: str, tariff_seq: int, document_id: str,
                                edition: str, page_number: int, fragment: str,
                                observed_factor: str | None, conclusion: str, note: str) -> dict:
    if (not provider or len(provider) > 80 or not code_complete or len(code_complete) > 64 or
            not 1 <= len(edition.strip()) <= 200 or not 10 <= len(fragment.strip()) <= 2000 or
            not 10 <= len(note.strip()) <= 2000 or type(page_number) is not int or not 1 <= page_number <= 10000 or
            type(tariff_seq) is not int or tariff_seq < 1 or conclusion not in {'matches', 'differs', 'inconclusive'}):
        raise Problem(422, "Código, edición, página, fragmento, conclusión o fundamento inválido")
    observed = _factor(observed_factor) if observed_factor is not None else None
    if conclusion != 'inconclusive' and observed is None:
        raise Problem(422, "Se requiere el factor observado para concluir coincidencia o diferencia")
    with transaction(conn):
        user, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
        check_version(dataset, expected_dataset_version)
        basis = _context(conn, root, dataset_id, source_id, provider, code_complete, tariff_seq)
        if document_id != basis['document']['id']:
            raise Problem(422, "El PDF seleccionado no es el anexo vinculado a este código y edición")
        if ((conclusion == 'matches' and observed != basis['catalogue_factor']) or
                (conclusion == 'differs' and observed == basis['catalogue_factor'])):
            raise Problem(422, "La conclusión contradice el factor observado y el del catálogo")
        previous = latest_assessment(conn, source_id, provider, code_complete, tariff_seq)
        identity, ordinal = str(uuid4()), previous['ordinal'] + 1 if previous else 1
        conn.execute("INSERT INTO documentary_assessments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (identity, dataset_id, source_id, provider, code_complete, tariff_seq, ordinal,
             previous['id'] if previous else None, document_id, edition.strip(), page_number,
             fragment.strip(), observed, 'UB', conclusion, note.strip(),
             json.dumps(basis, ensure_ascii=False, sort_keys=True), user['id'], now_utc()))
        conn.execute('UPDATE datasets SET version = version + 1 WHERE id = ?', (dataset_id,))
        event(conn, user['id'], 'documentary_assessment_saved', 'documentary_assessment', identity)
    return {'id': identity, 'ordinal': ordinal, 'dataset_version': expected_dataset_version + 1,
            'conclusion': conclusion, 'economic_approval': False}


def documentary_history(conn: sqlite3.Connection, root: Path, token_hash: str, dataset_id: str,
                        source_id: str, provider: str, code: str, tariff_seq: int) -> dict:
    authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    conn.execute('BEGIN')
    try:
        _, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
        source = conn.execute('SELECT id FROM source_registry WHERE id = ? AND dataset_id = ?',
                              (source_id, dataset_id)).fetchone()
        if source is None:
            raise Problem(404, 'Fuente inexistente en el conjunto')
        records = conn.execute('SELECT d.*, u.username AS actor_username FROM documentary_assessments d '
                               'JOIN users u ON u.id = d.actor_id WHERE d.dataset_id = ? AND d.source_id = ? '
                               'AND d.provider = ? AND d.code_complete = ? AND d.tariff_seq = ? ORDER BY d.ordinal',
                               (dataset_id, source_id, provider, code, tariff_seq)).fetchall()
        evaluator = DocumentaryEvaluator(conn, root, dataset_id)
        # The last observation replaces all earlier conclusions, even when inconclusive.
        latest = evaluator.evaluate(records[-1]) if records else None
        history = [{**dict(row), 'basis_at_save': json.loads(row['basis_json'])} for row in records]
        for record in history:
            record.pop('basis_json')
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    _, current = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    check_version(current, dataset['version'])
    return {'history': history, 'latest': latest, 'dataset_version': dataset['version'],
            'economic_approval': False}

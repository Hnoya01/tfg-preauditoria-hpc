"""RN14/RN15: documented row applicability, separate from proposals and analysis.

A catalogue match is only a candidate. A reviewer must record the agreement
page, currency/unit/quantity and scope of that reference. Neither operation
creates a finding, decision or monetary proposal; controls consume a durable
capture only on explicit analysis. Historical references are never overwritten.
"""
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from .agreement_review import load_agreement_review
from .consistent_reads import consistent_read
from .db import transaction
from .documentary_assessments import DocumentaryEvaluator, latest_assessment
from .eligibility import effective_row
from .effective_hpc_values import EffectiveHpcValues
from .revision_scope import revision_table
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event
from .storage import read_verified
from .values_v1 import CUT, source_db, json_safe_catalog_amount, catalog_amount_literal

VERSION = 'HPC-row-reference-v1'
CENT = Decimal('0.01')


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _sha(value):
    return hashlib.sha256(_dump(value).encode()).hexdigest()


def data_root(conn):
    return Path(next(r[2] for r in conn.execute('PRAGMA database_list') if r[1] == 'main')).parent


def _batch(conn, dataset_id, batch_id):
    from .review import _batch as current_batch
    return current_batch(conn, dataset_id, batch_id)


class Evaluator:
    """Caches verified originals within one caller-owned SQLite read snapshot."""
    def __init__(self, conn, root, dataset_id, batch_id):
        self.conn, self.root, self.dataset_id = conn, root, dataset_id
        self.batch = _batch(conn, dataset_id, batch_id)
        self.catalogs, self.reviews, self.effective_values, self.exact_catalogs = {}, {}, {}, {}
        self.documentary = DocumentaryEvaluator(conn, root, dataset_id)
        self.scope = conn.execute(
            f'SELECT id,source_id,provider,billing_unit FROM {revision_table(conn, "batch_provider_scope_history")} '
            'WHERE batch_id=? ORDER BY ordinal DESC LIMIT 1', (batch_id,)).fetchone()

    def _catalog(self, source):
        key = source['id']
        if key not in self.catalogs:
            catalog = source_db(read_verified(self.root, source['source_sha256']))
            try:
                groups = {}
                for r in catalog.execute("SELECT * FROM hpc_catalog_tariffs WHERE provider='HPC' ORDER BY seq"):
                    tariff = dict(r)
                    tariff['amount_cents'] = json_safe_catalog_amount(tariff['amount_cents'])
                    if re.match(r'^[0-9]{6}', tariff['code']):
                        groups.setdefault(tariff['code'][:6], []).append(tariff)
                self.catalogs[key] = groups
            finally:
                catalog.close()
        return self.catalogs[key]

    def _exact_catalog(self, source, code):
        key=(source['id'],code)
        if key not in self.exact_catalogs:
            catalog=source_db(read_verified(self.root,source['source_sha256']))
            try:
                records=[]
                for row in catalog.execute("SELECT * FROM hpc_catalog_tariffs WHERE provider='HPC' AND code=? ORDER BY seq",(code,)):
                    tariff=dict(row);tariff['amount_cents']=json_safe_catalog_amount(tariff['amount_cents']);records.append(tariff)
                self.exact_catalogs[key]=records
            finally:catalog.close()
        return self.exact_catalogs[key]

    def basis(self, source_row, source_id):
        original = self.conn.execute('SELECT * FROM invoice_rows WHERE import_id=? AND source_row=?',
                                     (self.batch['import_id'], source_row)).fetchone()
        if original is None:
            raise Problem(404, 'Fila inexistente en esta revisión')
        row = effective_row(original, self.batch['period'])
        fields = json.loads(row['permitted_json'])
        work = {}
        for change in self.conn.execute('SELECT field,value_json,latest_change_id FROM work_fields '
                                         'WHERE import_id=? AND source_row=? AND field IN (\'E\',\'G\',\'K\')',
                                         (self.batch['import_id'], source_row)):
            fields[change['field']] = json.loads(change['value_json'])
            work[change['field']] = change['latest_change_id']
        code = str(fields.get('E') or '')
        basis = {'format': VERSION, 'revision_id': self.batch['revision_id'],
                 'import_id': self.batch['import_id'], 'source_row': source_row,
                 'disposition': row['disposition'], 'code_complete': code,
                 'value_code': code[:6] if re.match(r'^[0-9]{6}', code) else None,
                 'practice_date': row['practice_date'], 'quantity': str(fields.get('G')),
                 'description': fields.get('K'), 'work': work,
                 'billed_total_ars': row['total_ars'],
                 'provider_scope': dict(self.scope) if self.scope else None,
                 'source': None, 'candidate': None, 'status': 'reference_source_unavailable'}
        source = self.conn.execute(
            "SELECT id,source_sha256,cut_label,source_version,status FROM source_registry "
            "WHERE id=? AND dataset_id=? AND kind='values' AND status='registered'",
            (source_id, self.dataset_id)).fetchone()
        if source is None:
            return basis
        basis['source'] = dict(source)
        if row['disposition'] != 'included':
            return {**basis, 'status': 'outside_scope'}
        if (not self.scope or self.scope['provider'] != 'HPC' or self.scope['source_id'] != source_id):
            return {**basis, 'status': 'hpc_provider_scope_missing'}
        from .local_hpc import tariffs as local_tariffs
        if source_id not in self.effective_values:
            self.effective_values[source_id] = EffectiveHpcValues(self.conn,self.root,self.dataset_id,source_id)
        local_resolver=self.effective_values[source_id]
        local_matches=[t for t in local_tariffs(self.conn,self.dataset_id,source_id)
                       if t['code']==code and local_resolver.resolve(t,row['practice_date'])['selected']]
        if source['cut_label'] != CUT or (not basis['value_code'] and not local_matches):
            return {**basis, 'status': 'unsupported_value_identity_or_cut'}
        try:
            tariffs = (self._exact_catalog(source,code) if local_matches else self._catalog(source).get(basis['value_code'], [])) + local_matches
            if source_id not in self.effective_values:
                self.effective_values[source_id] = EffectiveHpcValues(self.conn, self.root, self.dataset_id, source_id)
            resolver = self.effective_values[source_id]
            matches, withdrawn = [], []
            for tariff in tariffs:
                resolved = resolver.resolve(tariff, row['practice_date'])
                if resolved['status'] == 'withdrawn_reference':
                    withdrawn.append((tariff, resolved))
                elif resolved['selected']:
                    matches.append((tariff, resolved))
            if not matches and withdrawn:
                return {**basis, 'status':'withdrawn_reference',
                        'withdrawn_references':[r['status_version'] for _,r in withdrawn]}
            if len(matches) != 1:
                return {**basis, 'status': 'ambiguous_reference' if matches else 'no_reference_for_code_and_date',
                        'candidate_locators': [(t.get('source_locator') or f"hpc_catalog_tariffs.seq={t['seq']}") if local_matches else t['seq'] for t, _ in matches]}
            tariff, resolved = matches[0]
            if tariff.get('local_id'):
                basis['value_code']=code
                basis['identity_method']='local_exact_code'
            value = resolved['value_version']
            raw = json.loads(tariff['data_json'])
            calculation = raw.get('calculation') or {}
            candidate = {'tariff': tariff, 'value_version': value, 'factor_evidence': None}
            basis['candidate'] = candidate
            if resolved.get('status_version'):
                candidate['status_version'] = resolved['status_version']
            if resolved['status'] in ('withdrawn_reference','status_evidence_unverifiable'):
                return {**basis, 'status': resolved['status']}
            if value:
                # Retain previously captured optional factor provenance for history
                # compatibility; it is not a prerequisite for a documented fixed price.
                observation = (latest_assessment(self.conn, source_id, 'HPC', tariff['code'], tariff['seq']) if not tariff.get('local_id') else None)
                if observation:
                    candidate['factor_evidence'] = self.documentary.evaluate(observation)
                candidate['value_document'] = resolved['document']
                if resolved['status'] != 'documented_version_candidate':
                    return {**basis, 'status': 'source_or_evidence_unverifiable'}
                if value['unit_label'] != 'por práctica':
                    return {**basis, 'status': 'value_version_unit_or_document_incompatible'}
            else:
                if type(tariff.get('amount_cents')) is not int or tariff['amount_cents'] < 0:
                    return {**basis, 'status': 'catalogue_amount_not_interpretable'}
                if calculation.get('reviewRequired') is not False or calculation.get('kind') != 'nbu':
                    return {**basis, 'status': 'special_norm_or_calculation_requires_review'}
                milli, rate = calculation.get('ubMilliunits'), calculation.get('rateCents')
                if (type(milli) is not int or type(rate) is not int or milli <= 0 or rate <= 0 or
                        Decimal(milli) * rate / 1000 != tariff['amount_cents']):
                    return {**basis, 'status': 'inconsistent_catalogue_formula'}
                if source_id not in self.reviews:
                    self.reviews[source_id] = load_agreement_review(self.conn, self.root, self.dataset_id, source_id)
                review = self.reviews[source_id]
                ref = None
                if review and review['freshness'] == 'current':
                    ref = next((r for r in review['report']['references'] if r['tariff_seq'] == tariff['seq']), None)
                    if ref and ref['specific_norm']:
                        return {**basis, 'status': 'special_norm_or_calculation_requires_review'}
                observation = latest_assessment(self.conn, source_id, 'HPC', tariff['code'], tariff['seq'])
                if observation:
                    assessed = self.documentary.evaluate(observation)
                    candidate['factor_evidence'] = assessed
                    if not assessed['usable_match']:
                        return {**basis, 'status': 'factor_observation_not_current_or_matching'}
                elif ref and not value:
                    agreement = review['report']['agreement']
                    relevant = {ref['document_sha256'], agreement['sha256'], agreement['practice_unit_basis']['sha256']}
                    if not relevant.intersection(review['affected_document_sha256s']):
                        # Do not depend on unrelated references or the global report ID.
                        candidate['factor_evidence'] = {'reference': ref, 'agreement': agreement}
                if not candidate['factor_evidence']:
                    return {**basis, 'status': 'factor_evidence_missing'}
                if row['practice_date'] > CUT.removeprefix('BASE_'):
                    return {**basis, 'status': 'date_beyond_source_cut_without_version'}
            quantity = Decimal(basis['quantity'])
            if not quantity.is_finite() or quantity <= 0 or quantity > Decimal('1000000000'):
                return {**basis, 'status': 'invalid_covered_quantity'}
            amount = Decimal(value['amount_ars']) if value else Decimal(tariff['amount_cents']) / 100
            if amount * quantity * 100 != (amount * quantity * 100).to_integral_value():
                return {**basis, 'status': 'fractional_cent_needs_rounding_rule'}
            candidate.update(rate_ars=format(amount, '.2f'), effective_from=value['effective_from'] if value else tariff['valid_from'])
            return {**basis, 'status': 'ready_for_applicability'}
        except (OSError, RuntimeError, ValueError, InvalidOperation, TypeError, KeyError, sqlite3.Error):
            return {**basis, 'status': 'source_or_evidence_unverifiable'}

    def evaluate(self, record):
        current = self.basis(record['source_row'], record['source_id'])
        saved = json.loads(record['basis_json'])
        confirmation = json.loads(record['confirmation_json'])
        document = self.conn.execute('SELECT * FROM evidence_documents WHERE id=? AND dataset_id=? AND source_id=?',
                                     (confirmation.get('document_id'), self.dataset_id, record['source_id'])).fetchone()
        current['agreement_document'] = dict(document) if document else None
        if document:
            try:
                read_verified(self.root, document['sha256'])
            except (OSError, RuntimeError):
                current['agreement_document'] = None
        valid = record['state'] == 'confirmed' and current == saved and current['status'] == 'ready_for_applicability'
        return {'id': record['id'], 'ordinal': record['ordinal'], 'state': record['state'],
                'current': valid, 'basis': current, 'confirmation': confirmation,
                'basis_sha256': _sha(current), 'saved_basis_sha256': _sha(saved)}


def _latest(conn, revision_id):
    return conn.execute('SELECT r.* FROM row_economic_references r WHERE revision_id=? AND NOT EXISTS '
                        '(SELECT 1 FROM row_economic_references n WHERE n.revision_id=r.revision_id '
                        'AND n.source_row=r.source_row AND n.ordinal>r.ordinal) ORDER BY source_row', (revision_id,)).fetchall()


def dependency_snapshot(conn, dataset_id, batch_id):
    if conn.execute('PRAGMA user_version').fetchone()[0] < 23:
        return {'version': VERSION, 'rows': {}}
    evaluator = Evaluator(conn, data_root(conn), dataset_id, batch_id)
    from .authorization_controls import synthetic_batch
    return {'version': VERSION, 'simulation_only': synthetic_batch(conn, batch_id),
            'rows': {str(r['source_row']): evaluator.evaluate(r) for r in _latest(conn, evaluator.batch['revision_id'])}}


def preview(conn, root, token, dataset_id, batch_id, source_row, source_id, *, after_read=None):
    def read():
        _, dataset = authorized_dataset(conn, token, dataset_id, 'reviewer')
        evaluator = Evaluator(conn, root, dataset_id, batch_id)
        records = conn.execute('SELECT r.*,u.username AS actor_username FROM row_economic_references r '
                               'JOIN users u ON u.id=r.actor_id WHERE revision_id=? AND source_row=? ORDER BY ordinal',
                               (evaluator.batch['revision_id'], source_row)).fetchall()
        history = [{**{k: r[k] for k in ('id','ordinal','state','source_id','actor_username','created_at')},
                    'basis_at_save': json.loads(r['basis_json']), 'confirmation': json.loads(r['confirmation_json'])} for r in records]
        if evaluator.batch['state'] == 'cerrada':
            original = conn.execute('SELECT * FROM invoice_rows WHERE import_id=? AND source_row=?',
                                     (evaluator.batch['import_id'], source_row)).fetchone()
            if original is None:
                raise Problem(404, 'Fila inexistente en esta revisión')
            basis = (json.loads(records[-1]['basis_json']) if records else
                     {'status': 'closed_reference_not_recorded', 'code_complete': json.loads(original['permitted_json']).get('E'),
                      'value_code': None, 'practice_date': original['practice_date'], 'quantity': None, 'candidate': None})
            latest = ({'id': records[-1]['id'], 'ordinal': records[-1]['ordinal'], 'state': records[-1]['state'],
                       'current': False, 'historical': True, 'source_id': records[-1]['source_id'],
                       'confirmation': json.loads(records[-1]['confirmation_json'])} if records else None)
            documents = []
        else:
            basis = evaluator.basis(source_row, source_id)
            latest = evaluator.evaluate(records[-1]) if records else None
            documents = [dict(d) for d in conn.execute("SELECT id,original_name,sha256 FROM evidence_documents "
                          "WHERE dataset_id=? AND source_id=? AND category='agreement' ORDER BY id", (dataset_id, source_id))]
        reference_display = None
        candidate = basis.get('candidate')
        if candidate:
            tariff = candidate.get('tariff') or {}
            version = candidate.get('value_version')
            amount_literal = version.get('amount_ars') if version else tariff.get('amount_cents')
            amount = None
            try:
                if version:
                    parsed = Decimal(str(amount_literal))
                    if parsed.is_finite() and parsed >= 0:
                        amount = parsed
                elif type(amount_literal) is int and amount_literal >= 0:
                    amount = Decimal(amount_literal) / 100
            except (InvalidOperation, ValueError, TypeError):
                pass  # Legacy originals remain visible; never coerce unknown into zero.
            basis_source_id = (basis.get('source') or {}).get('id')
            latest_source_id = ((latest.get('basis', {}).get('source') or {}).get('id') or latest.get('source_id')) if latest else None
            source_matches = bool(basis_source_id and basis_source_id == latest_source_id)
            if latest is not None:
                latest['matches_selected_source'] = source_matches
            explicit_confirmation = (latest and source_matches and latest.get('state') == 'confirmed'
                                     and (latest.get('current') or latest.get('historical')))
            confirmed = latest.get('confirmation', {}) if explicit_confirmation else {}
            declaration_state = ('documented_value_version' if version else
                                 'historical_confirmation' if confirmed and latest.get('historical') else
                                 'current_confirmation' if confirmed else 'unverified')
            declared_unit = version.get('unit_label') if version else ('por práctica' if confirmed.get('billing_unit') == 'practice' else None)
            declared_currency = 'ARS' if version else confirmed.get('currency')

            display_source = basis.get('source') or {}
            reference_display = {
                'recorded_amount': format(amount, '.2f') if amount is not None else None,
                'recorded_amount_literal': catalog_amount_literal(amount_literal),
                'amount_status': 'interpretable' if amount is not None else 'not_interpretable',
                'declared_unit': declared_unit,
                'declared_currency': declared_currency,
                'declaration_state': declaration_state,
                'source_id': display_source.get('id'),
                'source_cut': display_source.get('cut_label'),
                'source_sha256': display_source.get('source_sha256'),
                'provider': tariff.get('provider', 'HPC'),
                'code': tariff.get('code'),
                'source_locator': tariff.get('source_locator') or f"hpc_catalog_tariffs.seq={tariff.get('seq')}",
                'value_version_id': version['id'] if version else None,
                'effective_from': version['effective_from'] if version else tariff.get('valid_from'),
                'valid_until': None if version else tariff.get('valid_until'),
                'application_status': basis['status'],
                'use_limit': ('Importe registrado. La tarifa evaluada y su aplicación se indican por separado; no confirma un débito.'
                              if candidate.get('rate_ars') is not None else
                              'Importe registrado, no importe aplicable confirmado ni débito. '
                              'Moneda, unidad y condiciones requieren comprobación para esta fila.')}
        return {'dataset_version': dataset['version'], 'revision_version': evaluator.batch['revision_version'],
                'revision_id': evaluator.batch['revision_id'], 'revision_state': evaluator.batch['state'],
                'basis': basis, 'basis_sha256': _sha(basis), 'history': history,
                'latest': latest, 'documents': documents, 'reference_display': reference_display,
                'use_limit': 'Aplicabilidad documentada; guardar no ejecuta análisis ni confirma propuestas o débitos.'}
    return consistent_read(conn, token, dataset_id, read, after_read=after_read)


def save_reference(conn, root, token, dataset_id, batch_id, source_row, *, expected_dataset_version,
                   expected_revision_version, source_id, basis_sha256, state, document_id=None,
                   page_number=None, excerpt='', covered_quantity='', currency='ARS', billing_unit='practice',
                   coverage_through=None, note='', reference_kind='general_hpc_base_no_additions'):
    if state not in ('confirmed', 'withdrawn', 'unresolved') or not 10 <= len(note.strip()) <= 2000:
        raise Problem(422, 'Estado o fundamento de aplicabilidad inválido')
    if reference_kind not in ('general_hpc_base_no_additions', 'specific_accepted_reference'):
        raise Problem(422, 'Tipo de referencia no admitido')
    if (state == 'confirmed' and reference_kind != 'general_hpc_base_no_additions') or (state == 'unresolved' and reference_kind != 'specific_accepted_reference'):
        raise Problem(422, 'La referencia específica identificada se conserva sin cuantificar en este incremento')
    with transaction(conn):
        user, dataset = authorized_dataset(conn, token, dataset_id, 'reviewer')
        check_version(dataset, expected_dataset_version)
        evaluator = Evaluator(conn, root, dataset_id, batch_id)
        batch = evaluator.batch
        if batch['revision_version'] != expected_revision_version or batch['state'] == 'cerrada':
            raise Problem(409, 'La revisión cambió o está cerrada')
        basis = evaluator.basis(source_row, source_id)
        if _sha(basis) != basis_sha256:
            raise Problem(409, 'La referencia o la fila cambió; actualizá la vista')
        if basis['source'] is None:
            raise Problem(404, 'Fuente de valores registrada inexistente en este conjunto')
        previous = conn.execute('SELECT * FROM row_economic_references WHERE revision_id=? AND source_row=? ORDER BY ordinal DESC LIMIT 1',
                                 (batch['revision_id'], source_row)).fetchone()
        if state == 'confirmed' and previous and previous['state'] == 'unresolved':
            old_basis = json.loads(previous['basis_json'])
            if (old_basis['code_complete'], old_basis['practice_date']) == (basis['code_complete'], basis['practice_date']):
                raise Problem(422, 'Hay una referencia específica identificada; no se sustituye por la general. Revisá su aplicabilidad o documentá su retiro')
        confirmation = {'note': note.strip(), 'reference_kind': reference_kind}
        if state == 'confirmed':
            if basis['status'] != 'ready_for_applicability':
                raise Problem(422, 'La referencia no es suficiente para este caso: ' + basis['status'])
            try:
                covered = Decimal(covered_quantity)
                through = date.fromisoformat(coverage_through)
                if (not covered.is_finite() or covered != Decimal(basis['quantity']) or
                        through.isoformat() != coverage_through or coverage_through < basis['practice_date'] or
                        (not basis['candidate']['value_version'] and coverage_through > CUT.removeprefix('BASE_'))):
                    raise ValueError()
            except (ValueError, TypeError, InvalidOperation):
                raise Problem(422, 'Cantidad o cobertura temporal incompatible con la fila y el corte') from None
            if currency != 'ARS' or billing_unit != 'practice':
                raise Problem(422, 'Se requiere evidencia de ARS por práctica, página y fragmento')
            confirmation.update(covered_quantity=str(covered), currency=currency, billing_unit=billing_unit,
                                coverage_through=coverage_through)
        if state in ('confirmed', 'unresolved'):
            if type(page_number) is not int or not 1 <= page_number <= 10000 or not 10 <= len(excerpt.strip()) <= 2000:
                raise Problem(422, 'Se requiere página y fragmento del convenio')
            doc = conn.execute("SELECT * FROM evidence_documents WHERE id=? AND dataset_id=? AND source_id=? AND category='agreement'",
                               (document_id, dataset_id, source_id)).fetchone()
            if doc is None:
                raise Problem(422, 'Seleccioná el convenio registrado de esta fuente')
            try:
                read_verified(root, doc['sha256'])
            except (OSError, RuntimeError) as exc:
                raise Problem(409, 'No se pudo verificar el PDF del convenio') from exc
            basis['agreement_document'] = dict(doc)
            confirmation.update(document_id=document_id, page_number=page_number, excerpt=excerpt.strip())
        identity, ordinal = str(uuid4()), previous['ordinal'] + 1 if previous else 1
        conn.execute('INSERT INTO row_economic_references VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                     (identity, dataset_id, batch['revision_id'], batch['import_id'], source_row, ordinal,
                      previous['id'] if previous else None, state, source_id, _dump(confirmation), _dump(basis), user['id'], now_utc()))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?', (dataset_id,))
        conn.execute('UPDATE revisions SET version=version+1 WHERE id=?', (batch['revision_id'],))
        event(conn, user['id'], 'economic_applicability_' + state, 'row_economic_reference', identity)
    return {'id': identity, 'ordinal': ordinal, 'dataset_version': expected_dataset_version + 1,
            'revision_version': expected_revision_version + 1, 'analysis_started': False, 'proposal_created': False}


def control_results(dependency, base, *, synthetic=False):
    evidence = {**base, 'reference_format': VERSION, 'proposal_amount_ars': None, 'simulation_only': synthetic}
    if not dependency or not dependency['current']:
        reason = ('specific_accepted_reference_pending' if dependency and dependency['state'] == 'unresolved' else
                  'economic_applicability_not_current' if dependency else 'economic_applicability_not_recorded')
        evidence.update(applicability_id=dependency['id'] if dependency else None,
                        status=dependency['basis']['status'] if dependency else 'not_recorded')
        return {rule: (rule, 'no_concluyente', reason, evidence, None, None) for rule in ('RN14','RN15')}
    basis, confirmation = dependency['basis'], dependency['confirmation']
    rate = Decimal(basis['candidate']['rate_ars'])
    quantity = Decimal(confirmation['covered_quantity'])
    comparable = rate * quantity
    billed = Decimal(basis['billed_total_ars'])
    difference = billed - comparable
    evidence.update(applicability_id=dependency['id'], source=basis['source'],
                    code_complete=basis['code_complete'], value_code=basis['value_code'],
                    reference=basis['candidate'], agreement_document=basis['agreement_document'],
                    confirmation=confirmation, practice_date=basis['practice_date'],
                    rate_ars=format(rate, '.2f'), covered_quantity=str(quantity),
                    comparable_total_ars=format(comparable, '.2f'), billed_total_ars=format(billed, '.2f'),
                    difference_ars=format(difference, '.2f'), currency='ARS', economic_unit='practice',
                    tolerance_ars='0.01', billed_quantity_not_reapplied=True,
                    formula='total facturado de fila - (arancel por práctica × cantidad cubierta)')
    reason = ('tariff_above_applicable_reference' if difference > CENT else
              'tariff_below_applicable_reference' if difference < -CENT else 'tariff_within_tolerance')
    return {'RN14': ('RN14', 'con_indicios' if abs(difference) > CENT else 'sin_observaciones', reason, evidence, format(difference, '.2f'), 'ARS'),
            'RN15': ('RN15', 'sin_observaciones', 'economic_reference_sufficient_for_row', evidence, None, None)}

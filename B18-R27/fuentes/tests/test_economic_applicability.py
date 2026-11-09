"""Economic integration uses exclusively invented invoices/catalogues/PDFs."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient

from app.api import create_app
from app.controls import run_controls, run_summary
from app.db import MIGRATIONS, backup_before_upgrade, connect, migrate
from app.economic_applicability import Evaluator, control_results, preview, save_reference
from app.hpc_values import save_value_version
from app.service import Problem
from app.storage import object_path
from tests import test_documentary_assessments as fixture
from tests.test_p02 import ORIGIN, PASSWORD, book
from tests.temp_support import TemporaryDirectory


class EconomicApplicabilityTests(unittest.TestCase):
    tearDown = fixture.DocumentaryAssessmentTests.tearDown
    headers = fixture.DocumentaryAssessmentTests.headers
    import_book = fixture.DocumentaryAssessmentTests.import_book
    run_url = fixture.DocumentaryAssessmentTests.run_url
    register_fictional_hpc = fixture.DocumentaryAssessmentTests.register_fictional_hpc
    url = fixture.DocumentaryAssessmentTests.url
    body = fixture.DocumentaryAssessmentTests.body
    save = fixture.DocumentaryAssessmentTests.save

    def setUp(self):
        fixture.DocumentaryAssessmentTests.setUp(self)
        self.save()
        pdf = b'%PDF-1.4\n% Convenio exclusivamente ficticio: ARS por practica\n%%EOF'
        r = self.client.post(f'/api/datasets/{self.dataset["id"]}/evidence-pdfs', content=pdf,
            headers=self.headers(**{'X-Expected-Version': str(self.dataset['version']), 'X-Source-Id': self.source_id,
                'X-Source-Filename': 'convenio-ficticio.pdf', 'X-Evidence-Category': 'agreement',
                'X-Provenance-Note': 'Convenio inventado para probar aplicabilidad por fila.',
                'X-Expected-SHA256': hashlib.sha256(pdf).hexdigest()}))
        self.assertEqual(r.status_code, 201, r.text)
        self.agreement_id = r.json()['id']
        self.dataset['version'] = r.json()['dataset_version']
        self.set_scope()

    def base(self):
        return f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}'

    def set_scope(self):
        page = self.client.get(self.base() + '/alerts').json()
        r = self.client.post(self.base() + '/provider-scope', headers=self.headers(), json={
            'expected_dataset_version': self.dataset['version'], 'expected_revision_version': page['revision_version'],
            'source_id': self.source_id, 'provider': 'HPC', 'billing_unit': 'unverified',
            'confirmation_note': 'Prestador HPC ficticio; la unidad se confirma por fila.'})
        self.assertEqual(r.status_code, 200, r.text)
        self.dataset['version'] = r.json()['dataset_version']

    def reference_url(self, row=3):
        return self.base() + f'/rows/{row}/economic-applicability'

    def reference(self, row=3):
        r = self.client.get(self.reference_url(row), params={'source_id': self.source_id})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def reference_body(self, row=3, **changes):
        p = self.reference(row)
        return {'expected_dataset_version': p['dataset_version'], 'expected_revision_version': p['revision_version'],
                'source_id': self.source_id, 'basis_sha256': p['basis_sha256'], 'state': 'confirmed',
                'document_id': self.agreement_id, 'page_number': 1,
                'excerpt': 'Convenio ficticio: ARS por práctica, dos prácticas completas, sin adicionales.',
                'covered_quantity': '2', 'currency': 'ARS', 'billing_unit': 'practice',
                'coverage_through': '2026-08-31', 'note': 'Aplicabilidad ficticia comprobada para esta fila sin norma especial.', **changes}

    def confirm(self, row=3, **changes):
        r = self.client.post(self.reference_url(row), json=self.reference_body(row, **changes), headers=self.headers())
        self.assertEqual(r.status_code, 201, r.text)
        self.dataset['version'] = r.json()['dataset_version']
        return r.json()

    def analyze(self):
        r = self.client.post(self.run_url(), headers=self.headers(), json={'expected_version': self.dataset['version']})
        self.assertEqual(r.status_code, 201, r.text)
        self.dataset['version'] += 1
        self.run = r.json()
        return self.results(self.run['id'])

    def results(self, run_id, row=3):
        r = self.client.get(f'/api/datasets/{self.dataset["id"]}/control-runs/{run_id}/rows/{row}')
        self.assertEqual(r.status_code, 200, r.text)
        return {item['rule_code']: item for item in r.json()}

    def test_nbu_factor_does_not_declare_currency_or_unit_before_confirmation(self):
        page = self.reference()
        self.assertEqual(page['basis']['status'], 'ready_for_applicability')
        self.assertIsNone(page['reference_display']['declared_currency'])
        self.assertIsNone(page['reference_display']['declared_unit'])
        self.confirm()
        confirmed = self.reference()
        self.assertTrue(confirmed['latest']['current'])
        self.assertEqual(confirmed['reference_display']['declared_currency'], 'ARS')
        self.assertEqual(confirmed['reference_display']['declared_unit'], 'por práctica')

    def test_frozen_original_preserves_explicit_historical_declarations(self):
        self.confirm()
        import app.economic_applicability as economic
        original_batch=economic._batch
        def frozen(*args):
            return {**dict(original_batch(*args)), 'state':'cerrada'}
        with patch('app.economic_applicability._batch', side_effect=frozen):
            page=self.reference()
        self.assertTrue(page['latest']['historical'])
        self.assertFalse(page['latest']['current'])
        self.assertEqual(page['reference_display']['declared_currency'],'ARS')
        self.assertEqual(page['reference_display']['declared_unit'],'por práctica')
        self.assertEqual(page['reference_display']['declaration_state'],'historical_confirmation')

    def test_another_sources_confirmation_cannot_declare_selected_original(self):
        self.confirm()
        original_evaluate=Evaluator.evaluate
        def other_source(evaluator,record):
            value=original_evaluate(evaluator,record)
            value['basis']['source']['id']='another-fictional-source'
            return value
        with patch.object(Evaluator,'evaluate',other_source):
            page=self.reference()
        self.assertFalse(page['latest']['matches_selected_source'])
        self.assertIsNone(page['reference_display']['declared_currency'])
        self.assertIsNone(page['reference_display']['declared_unit'])

    def test_legacy_non_numeric_amount_stays_readable_unquantified_and_immutable(self):
        from app.values_v1 import validate_values, register_values, SOURCE_NAME
        conn = connect(self.root)
        original_source = conn.execute('SELECT * FROM source_registry WHERE id=?', (self.source_id,)).fetchone()
        original_bytes = object_path(self.root, original_source['source_sha256']).read_bytes()
        original_manifest = object_path(self.root, original_source['manifest_sha256']).read_bytes()
        details = validate_values(original_bytes, original_manifest, original_source['source_sha256'])
        legacy_db = sqlite3.connect(':memory:');legacy_db.deserialize(original_bytes)
        legacy_bad=getattr(self,'legacy_bad','S/D')
        legacy_db.execute('UPDATE hpc_catalog_tariffs SET amount_cents=? WHERE seq=1',(legacy_bad,))
        legacy_db.commit();legacy_bytes=legacy_db.serialize();legacy_db.close()
        legacy_sha=hashlib.sha256(legacy_bytes).hexdigest()
        manifest=json.loads(original_manifest)
        manifest['files'][SOURCE_NAME]={'sha256':legacy_sha,'bytes':len(legacy_bytes)}
        manifest_bytes=json.dumps(manifest).encode()
        details['metadata']['manifest_sha256']=hashlib.sha256(manifest_bytes).hexdigest()
        # Simulate a catalog registered by the former validator, not a production mutation.
        with patch('app.values_v1.validate_values', return_value=details):
            source,_=register_values(conn,self.root,self.digest,self.dataset['id'],self.dataset['version'],
                                     legacy_bytes,manifest_bytes,legacy_sha)
        conn.close();self.source_id=source['id'];self.dataset['version']=source['dataset_version'];self.set_scope()
        before_version=self.dataset['version']
        page=self.reference()
        self.assertIsNone(page['reference_display']['recorded_amount'])
        self.assertEqual(page['reference_display']['amount_status'],'not_interpretable')
        if isinstance(legacy_bad,bytes):
            self.assertIn('BLOB (3 bytes;',page['reference_display']['recorded_amount_literal'])
        else:
            self.assertEqual(page['reference_display']['recorded_amount_literal'],str(legacy_bad))
        self.assertEqual(page['reference_display']['source_locator'],'hpc_catalog_tariffs.seq=1')
        self.assertNotEqual(page['basis']['status'],'ready_for_applicability')
        self.assertIsNone(page['reference_display']['declared_currency'])
        self.assertEqual(page['dataset_version'],before_version)
        base=f'/api/datasets/{self.dataset["id"]}'
        for path in (f'/sources/{self.source_id}/value-candidates?code=123456&provider=HPC',
                     f'/sources/{self.source_id}/hpc-values/1',
                     f'/batches/{self.batch}/hpc-comparison?source_id={self.source_id}'):
            response=self.client.get(base+path)
            self.assertEqual(response.status_code,200,response.text)
            json.dumps(response.json(),allow_nan=False)
        self.assertEqual(object_path(self.root,legacy_sha).read_bytes(),legacy_bytes)
        self.assertEqual(object_path(self.root,original_source['source_sha256']).read_bytes(),original_bytes)
        conn=connect(self.root)
        self.assertEqual(conn.execute('SELECT count(*) FROM row_economic_references').fetchone()[0],0)
        self.assertEqual(conn.execute('SELECT count(*) FROM proposal_versions').fetchone()[0],0)
        conn.close()

    def test_legacy_blob_amount_remains_json_safe_and_unquantified(self):
        self.legacy_bad=b'S/D'
        self.test_legacy_non_numeric_amount_stays_readable_unquantified_and_immutable()

    def test_legacy_nonfinite_amount_remains_json_safe_and_unquantified(self):
        self.legacy_bad=float('inf')
        self.test_legacy_non_numeric_amount_stays_readable_unquantified_and_immutable()

    def test_registration_rejects_non_integer_or_negative_catalog_amounts(self):
        from app.values_v1 import validate_values, register_values, SOURCE_NAME
        conn=connect(self.root)
        source=conn.execute('SELECT * FROM source_registry WHERE id=?',(self.source_id,)).fetchone();conn.close()
        original=object_path(self.root,source['source_sha256']).read_bytes()
        manifest=json.loads(object_path(self.root,source['manifest_sha256']).read_bytes())
        for bad in ('S/D',None,1.5,-1,b'S/D',float('inf')):
            with self.subTest(value=bad):
                db=sqlite3.connect(':memory:');db.deserialize(original)
                db.execute('UPDATE hpc_catalog_tariffs SET amount_cents=? WHERE seq=1',(bad,));db.commit()
                content=db.serialize();db.close();sha=hashlib.sha256(content).hexdigest()
                manifest['files'][SOURCE_NAME]={'sha256':sha,'bytes':len(content)}
                with self.assertRaisesRegex(ValueError,'amount_cents.*seq=1'):
                    validate_values(content,json.dumps(manifest).encode(),sha)
                conn=connect(self.root)
                before_sources=conn.execute('SELECT count(*) FROM source_registry').fetchone()[0]
                before_files=conn.execute('SELECT count(*) FROM stored_files').fetchone()[0]
                with self.assertRaises(Problem) as rejected:
                    register_values(conn,self.root,self.digest,self.dataset['id'],self.dataset['version'],
                                    content,json.dumps(manifest).encode(),sha)
                self.assertEqual(rejected.exception.status,422)
                self.assertEqual(conn.execute('SELECT count(*) FROM source_registry').fetchone()[0],before_sources)
                self.assertEqual(conn.execute('SELECT count(*) FROM stored_files').fetchone()[0],before_files)
                conn.close()


    def test_found_amount_is_visible_without_documentary_applicability(self):
        with patch('app.economic_applicability.latest_assessment', return_value=None), \
             patch('app.economic_applicability.load_agreement_review', return_value=None):
            page = self.reference()
            self.assertEqual(page['basis']['status'], 'factor_evidence_missing')
            self.assertNotIn('rate_ars', page['basis']['candidate'])
            self.assertEqual(page['reference_display']['recorded_amount'], '15.00')
            self.assertEqual(page['reference_display']['provider'], 'HPC')
            self.assertIn('no importe aplicable', page['reference_display']['use_limit'])
            body = self.reference_body()
            response = self.client.post(self.reference_url(), json=body, headers=self.headers())
            self.assertNotEqual(response.status_code, 201)
        conn = connect(self.root)
        self.assertEqual(conn.execute('SELECT count(*) FROM row_economic_references').fetchone()[0], 0)
        self.assertEqual(conn.execute('SELECT count(*) FROM proposal_versions').fetchone()[0], 0)
        conn.close()

    def test_reference_save_does_not_analyze_and_explicit_control_explains_two_pesos(self):
        p = self.reference()
        self.assertEqual(p['basis']['status'], 'ready_for_applicability')
        conn = connect(self.root)
        before = conn.execute('SELECT count(*) FROM control_runs').fetchone()[0]
        conn.close()
        saved = self.confirm()
        self.assertFalse(saved['analysis_started'])
        self.assertFalse(saved['proposal_created'])
        conn = connect(self.root)
        self.assertEqual(conn.execute('SELECT count(*) FROM control_runs').fetchone()[0], before)
        self.assertEqual(conn.execute('SELECT count(*) FROM proposal_versions').fetchone()[0], 0)
        conn.close()
        result = self.analyze()
        r = result['RN14']
        self.assertEqual((r['result'], r['difference_ars'], r['currency']), ('con_indicios', '2.00', 'ARS'))
        self.assertEqual(result['RN15']['result'], 'sin_observaciones')
        e = r['evidence']
        self.assertEqual((e['billed_total_ars'], e['rate_ars'], e['covered_quantity'], e['comparable_total_ars']), ('32.00','15.00','2','30.00'))
        self.assertTrue(e['billed_quantity_not_reapplied'])
        self.assertIsNone(e['proposal_amount_ars'])
        self.assertEqual(e['applicability_id'], saved['id'])
        self.assertEqual(e['agreement_document']['id'], self.agreement_id)

    def test_documented_cent_tolerance_and_signed_difference(self):
        self.confirm()
        conn = connect(self.root)
        evaluator = Evaluator(conn, self.root, self.dataset['id'], self.batch)
        record = conn.execute('SELECT * FROM row_economic_references').fetchone()
        dep = evaluator.evaluate(record)
        conn.close()
        for total, expected, difference in [('30.00','sin_observaciones','0.00'),('30.01','sin_observaciones','0.01'),
                                            ('29.99','sin_observaciones','-0.01'),('30.02','con_indicios','0.02'),('29.98','con_indicios','-0.02')]:
            with self.subTest(total=total):
                item = copy.deepcopy(dep)
                item['basis']['billed_total_ars'] = total
                result = control_results(item, {})['RN14']
                self.assertEqual((result[1], result[4]), (expected, difference))

    def test_code_prefix_applies_only_to_values_and_keeps_full_code_in_capture(self):
        p = self.reference()
        r = self.client.post(self.base() + '/rows/3/work-fields', headers=self.headers(), json={
            'expected_dataset_version': p['dataset_version'], 'expected_revision_version': p['revision_version'],
            'field':'E', 'value':'123456789', 'reason':'Código completo ficticio con equivalencia económica de seis dígitos.'})
        self.assertEqual(r.status_code, 200, r.text)
        self.dataset['version'] = r.json()['dataset_version']
        self.confirm()
        results = self.analyze()
        self.assertEqual(results['RN14']['difference_ars'], '2.00')
        self.assertEqual(results['RN14']['evidence']['code_complete'], '123456789')
        self.assertEqual(results['RN14']['evidence']['value_code'], '123456')
        self.assertNotEqual(results['RN09']['result'], 'sin_observaciones')
        self.assertEqual(results['RN09']['difference_ars'], None)

    def test_incompatible_dimensions_and_missing_evidence_cannot_be_confirmed(self):
        for changes in ({'billing_unit':'hour'}, {'currency':'USD'}, {'covered_quantity':'1'},
                        {'coverage_through':'2026-08-01'}, {'coverage_through':'2026-10-10'},
                        {'document_id':self.document_id}, {'excerpt':'short'}):
            with self.subTest(changes=changes):
                r = self.client.post(self.reference_url(), headers=self.headers(), json=self.reference_body(**changes))
                self.assertEqual(r.status_code, 422, r.text)
        self.save(conclusion='inconclusive', observed_factor=None)
        self.assertEqual(self.reference()['basis']['status'], 'factor_observation_not_current_or_matching')
        r = self.client.post(self.reference_url(), headers=self.headers(), json=self.reference_body())
        self.assertEqual(r.status_code, 422)
        results = self.analyze()
        self.assertEqual(results['RN14']['result'], 'no_concluyente')
        self.assertIsNone(results['RN14']['difference_ars'])

    def test_ambiguous_or_special_candidates_never_receive_amounts(self):
        original = Evaluator._catalog
        def altered(evaluator, source):
            groups = copy.deepcopy(original(evaluator, source))
            groups['123456'].append(copy.deepcopy(groups['123456'][0]))
            return groups
        with patch.object(Evaluator, '_catalog', altered):
            self.assertEqual(self.reference()['basis']['status'], 'ambiguous_reference')
            self.assertEqual(self.client.post(self.reference_url(), headers=self.headers(), json=self.reference_body()).status_code, 422)
        def special(evaluator, source):
            groups = copy.deepcopy(original(evaluator, source))
            groups['123456'][0]['data_json'] = json.dumps({'calculation': {'kind':'nbu','reviewRequired':True}})
            return groups
        with patch.object(Evaluator, '_catalog', special):
            self.assertEqual(self.reference()['basis']['status'], 'special_norm_or_calculation_requires_review')
            self.assertEqual(self.client.post(self.reference_url(), headers=self.headers(), json=self.reference_body()).status_code, 422)

    def test_stale_permissions_csrf_and_foreign_sources_rejected_without_history(self):
        body = self.reference_body()
        self.assertEqual(self.client.post(self.reference_url(), json=body, headers={'Origin':ORIGIN}).status_code, 403)
        self.confirm(2)
        self.assertEqual(self.client.post(self.reference_url(), json=body, headers=self.headers()).status_code, 409)
        body = self.reference_body(source_id='foreign-source')
        self.assertEqual(self.client.post(self.reference_url(), json=body, headers=self.headers()).status_code, 409)
        foreign = self.client.get(self.reference_url(), params={'source_id':'foreign-source'})
        self.assertEqual(foreign.status_code, 200)
        # Even a fresh hash of an unavailable source cannot create a withdrawal.
        body.update(basis_sha256=foreign.json()['basis_sha256'], state='withdrawn')
        self.assertEqual(self.client.post(self.reference_url(), json=body, headers=self.headers()).status_code, 404)
        with TestClient(create_app(self.root, public_origin=ORIGIN), base_url=ORIGIN) as viewer:
            login = viewer.post('/api/session', json={'username':'viewer','password':PASSWORD}, headers={'Origin':ORIGIN})
            self.assertEqual(viewer.get(self.reference_url(), params={'source_id':self.source_id}).status_code, 403)
            self.assertEqual(viewer.post(self.reference_url(), json=self.reference_body(), headers={'Origin':ORIGIN,'X-CSRF-Token':login.json()['csrf_token']}).status_code, 403)
        conn = connect(self.root)
        self.assertEqual(conn.execute('SELECT count(*) FROM row_economic_references').fetchone()[0], 1)
        conn.close()

    def test_withdrawal_invalidates_only_its_row_and_rules_without_resurrecting_history(self):
        self.confirm(2)
        self.confirm(3)
        self.analyze()
        run = self.run['id']
        self.confirm(3, state='withdrawn', document_id=None)
        self.assertEqual(self.results(run, 2)['RN14']['freshness'], 'current')
        result = self.results(run)
        self.assertEqual(result['RN14']['freshness'], 'requires_update')
        self.assertEqual(result['RN15']['freshness'], 'requires_update')
        self.assertEqual(result['RN13']['freshness'], 'current')
        self.assertFalse(self.reference()['latest']['current'])
        self.assertEqual(len(self.reference()['history']), 2)
        fresh = self.analyze()
        self.assertIsNone(fresh['RN14']['difference_ars'])
        self.assertEqual(fresh['RN14']['result'], 'no_concluyente')

    def test_value_version_is_selected_by_date_and_changes_only_dependent_results(self):
        self.confirm()
        self.analyze()
        run = self.run['id']
        conn = connect(self.root)
        value = save_value_version(conn, self.root, self.digest, self.dataset['id'], self.source_id,
                    expected_dataset_version=self.dataset['version'], tariff_seq=1, code='123456', amount_ars='14.00',
                    unit_label='por práctica', effective_from='2026-08-16', document_id=self.agreement_id, page_number=1,
                    excerpt='Nuevo importe ficticio exacto ARS14 por práctica desde 16 agosto.', reason='Cambio ficticio respaldado para probar dependencia temporal.')
        conn.close()
        self.dataset['version'] = value['dataset_version']
        self.assertFalse(self.reference()['latest']['current'])
        self.assertEqual(self.results(run)['RN14']['freshness'], 'requires_update')
        self.assertEqual(self.results(run)['RN13']['freshness'], 'current')
        self.assertEqual(self.reference(2)['basis']['candidate']['rate_ars'], '15.00')
        self.assertEqual(self.reference()['basis']['candidate']['rate_ars'], '14.00')
        self.confirm()
        self.assertEqual(self.analyze()['RN14']['difference_ars'], '4.00')
        self.assertEqual(len(self.reference()['history']), 2)

    def test_tariff_logical_withdrawal_invalidates_economic_results_but_not_arithmetic(self):
        from app.hpc_value_status import save_status
        self.confirm()
        self.analyze()
        run = self.run['id']
        conn = connect(self.root)
        try:
            changed = save_status(conn, self.root, self.digest, self.dataset['id'], self.source_id,
                expected_dataset_version=self.dataset['version'], tariff_seq=1, active=False,
                effective_from='2026-08-16', document_id=self.agreement_id, page_number=1,
                excerpt='Baja ficticia de esta práctica desde el 16 de agosto.',
                reason='Retiro ficticio respaldado para probar dependencias económicas.')
        finally:
            conn.close()
        self.dataset['version'] = changed['dataset_version']
        self.assertEqual(self.reference()['basis']['status'], 'withdrawn_reference')
        self.assertFalse(self.reference()['latest']['current'])
        self.assertEqual(self.results(run)['RN14']['freshness'], 'requires_update')
        self.assertEqual(self.results(run)['RN13']['freshness'], 'current')
        self.assertEqual(self.reference(2)['basis']['candidate']['rate_ars'], '15.00')
        fresh = self.analyze()
        self.assertIsNone(fresh['RN14']['difference_ars'])
        self.assertEqual(fresh['RN14']['result'], 'no_concluyente')

    def test_two_simultaneous_writers_save_once_and_reject_the_stale_copy(self):
        body = self.reference_body()
        barrier = Barrier(2)
        def write():
            conn = connect(self.root)
            try:
                barrier.wait(timeout=10)
                try:
                    save_reference(conn, self.root, self.digest, self.dataset['id'], self.batch, 3, **body)
                    return 201
                except Problem as exc:
                    return exc.status
            finally:
                conn.close()
        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = [f.result(timeout=15) for f in [workers.submit(write), workers.submit(write)]]
        self.assertEqual(sorted(outcomes), [201,409])
        self.assertEqual(len(self.reference()['history']), 1)

    def test_identified_specific_reference_prevents_general_calculation_without_silent_fallback(self):
        self.confirm()
        self.analyze()
        self.confirm(state='unresolved', reference_kind='specific_accepted_reference',
                     note='Se identifica un acuerdo específico aceptado ficticio; requiere tratamiento del caso.')
        self.assertEqual(self.analyze()['RN14']['reason_code'], 'specific_accepted_reference_pending')
        self.assertIsNone(self.results(self.run['id'])['RN14']['difference_ars'])
        r = self.client.post(self.reference_url(), headers=self.headers(), json=self.reference_body())
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(len(self.reference()['history']), 2)

    def test_unrelated_document_and_future_value_do_not_invalidate_existing_reference(self):
        self.confirm()
        self.analyze()
        run = self.run['id']
        pdf = b'%PDF-1.4\n% Otro documento ficticio independiente\n%%EOF'
        r = self.client.post(f'/api/datasets/{self.dataset["id"]}/evidence-pdfs', content=pdf,
            headers=self.headers(**{'X-Expected-Version': str(self.dataset['version']), 'X-Source-Id': self.source_id,
                'X-Source-Filename': 'otro-ficticio.pdf', 'X-Evidence-Category': 'agreement',
                'X-Provenance-Note': 'Documento ficticio que no respalda esta referencia.',
                'X-Expected-SHA256': hashlib.sha256(pdf).hexdigest()}))
        self.assertEqual(r.status_code, 201, r.text)
        self.dataset['version'] = r.json()['dataset_version']
        conn = connect(self.root)
        try:
            value = save_value_version(conn, self.root, self.digest, self.dataset['id'], self.source_id,
                        expected_dataset_version=self.dataset['version'], tariff_seq=1, code='123456', amount_ars='18.00',
                        unit_label='por práctica', effective_from='2026-11-01', document_id=self.agreement_id, page_number=1,
                        excerpt='Valor ficticio para noviembre, sin aplicación a agosto.', reason='Cambio ficticio futuro respaldado.')
        finally:
            conn.close()
        self.dataset['version'] = value['dataset_version']
        self.assertTrue(self.reference()['latest']['current'])
        self.assertEqual(self.results(run)['RN14']['freshness'], 'current')
        self.assertEqual(self.results(run)['RN14']['difference_ars'], '2.00')

    def test_incompatible_new_value_cannot_fall_back_to_old_confirmed_reference(self):
        self.confirm()
        self.analyze()
        run = self.run['id']
        conn = connect(self.root)
        try:
            value = save_value_version(conn, self.root, self.digest, self.dataset['id'], self.source_id,
                        expected_dataset_version=self.dataset['version'], tariff_seq=1, code='123456', amount_ars='14.00',
                        unit_label='por hora', effective_from='2026-08-16', document_id=self.agreement_id, page_number=1,
                        excerpt='Valor ficticio por hora, incompatible con cantidad por práctica.', reason='Cambio ficticio de unidad para ensayo negativo.')
        finally:
            conn.close()
        self.dataset['version'] = value['dataset_version']
        p = self.reference()
        self.assertEqual(p['basis']['status'], 'value_version_unit_or_document_incompatible')
        self.assertEqual(p['reference_display']['recorded_amount'], '14.00')
        self.assertEqual(p['reference_display']['declared_unit'], 'por hora')
        self.assertEqual(p['reference_display']['declared_currency'], 'ARS')
        self.assertEqual(p['reference_display']['source_id'], self.source_id)
        self.assertEqual(p['reference_display']['source_cut'], 'BASE_2026-10-09')
        self.assertEqual(len(p['reference_display']['source_sha256']), 64)
        self.assertFalse(p['latest']['current'])
        self.assertEqual(self.results(run)['RN14']['freshness'], 'requires_update')
        self.assertIsNone(self.analyze()['RN14']['difference_ars'])

    def test_changed_backing_object_invalidates_reference_but_preserves_saved_calculation(self):
        self.confirm()
        results = self.analyze()
        e = results['RN14']['evidence']
        path = object_path(self.root, e['agreement_document']['sha256'])
        original = path.read_bytes()
        try:
            path.write_bytes(original + b'fictional corruption')
            r = self.results(self.run['id'])['RN14']
            self.assertEqual(r['freshness'], 'requires_update')
            self.assertEqual(r['difference_ars'], '2.00')
            self.assertEqual(r['evidence'], e)
        finally:
            path.write_bytes(original)

    def test_permission_revocation_during_read_or_analysis_rejects_and_retains_history(self):
        self.confirm()
        def revoke():
            c = connect(self.root)
            c.execute("UPDATE users SET active=0 WHERE username='owner'")
            c.close()
        conn = connect(self.root)
        try:
            with self.assertRaises(Problem) as denied:
                preview(conn, self.root, self.digest, self.dataset['id'], self.batch, 3, self.source_id, after_read=revoke)
            self.assertEqual(denied.exception.status, 401)
            conn.execute("UPDATE users SET active=1 WHERE username='owner'")
            with self.assertRaises(Problem) as conflict:
                run_controls(conn, self.digest, self.dataset['id'], self.batch, self.dataset['version'], after_prepare=revoke)
            self.assertEqual(conflict.exception.status, 401)
            self.assertEqual(conn.execute('SELECT state FROM analysis_history ORDER BY rowid DESC LIMIT 1').fetchone()[0], 'historical')
            self.assertGreater(conn.execute('SELECT count(*) FROM analysis_history_results WHERE run_id=(SELECT id FROM analysis_history ORDER BY rowid DESC LIMIT 1)').fetchone()[0], 0)
        finally:
            conn.close()

    def test_analysis_concurrent_change_rejects_publication_and_keeps_prepared_amount(self):
        self.confirm()
        count = len(self.client.get(self.base() + '/control-runs').json())
        def withdraw():
            self.confirm(state='withdrawn')
        conn = connect(self.root)
        try:
            with self.assertRaises(Problem) as stale:
                run_controls(conn, self.digest, self.dataset['id'], self.batch, self.dataset['version'], after_prepare=withdraw)
            self.assertEqual(stale.exception.status, 409)
            self.assertEqual(conn.execute('SELECT state FROM analysis_history ORDER BY rowid DESC LIMIT 1').fetchone()[0], 'historical')
            stored = conn.execute("SELECT difference_ars FROM analysis_history_results WHERE source_row=3 AND rule_code='RN14' ORDER BY rowid DESC LIMIT 1").fetchone()[0]
            self.assertEqual(stored, '2.00')
        finally:
            conn.close()
        self.assertEqual(len(self.client.get(self.base() + '/control-runs').json()), count)

    def test_closed_zip_is_unchanged_and_successor_does_not_inherit_applicability(self):
        from tests.test_closure import ClosureTests
        from tests.test_p05 import P05Tests
        self.alerts = lambda: self.client.get(self.base() + '/alerts').json()
        self.decide = lambda *args, **kwargs: P05Tests.decide(self, *args, **kwargs)
        self.preview = lambda: ClosureTests.preview(self)
        self.confirm()
        self.analyze()
        ClosureTests.resolve_alerts(self)
        page = ClosureTests.justify(self)
        r = ClosureTests.close(self, page)
        self.assertEqual(r.status_code, 201, r.text)
        closed = r.json()
        frozen = self.client.get(self.base() + '/export-closed').content
        self.assertEqual(self.client.post(self.reference_url(), headers=self.headers(), json=self.reference_body()).status_code, 409)
        conn = connect(self.root)
        try:
            value = save_value_version(conn, self.root, self.digest, self.dataset['id'], self.source_id,
                        expected_dataset_version=closed['dataset_version'], tariff_seq=1, code='123456', amount_ars='14.00',
                        unit_label='por práctica', effective_from='2026-08-16', document_id=self.agreement_id, page_number=1,
                        excerpt='Referencia ficticia posterior al cierre; no reescribe la historia.', reason='Cambio ficticio posterior al cierre congelado.')
        finally:
            conn.close()
        with patch.object(Evaluator, 'basis', side_effect=AssertionError('Closed reads must not evaluate current references')):
            historical = self.reference()
        self.assertEqual(historical['basis']['candidate']['rate_ars'], '15.00')
        self.assertTrue(historical['latest']['historical'])
        self.assertEqual(self.client.get(self.base() + '/export-closed').content, frozen)
        r = self.client.post(self.base() + '/revisions', headers=self.headers(), json={
            'previous_revision_id':closed['revision_id'], 'expected_dataset_version':value['dataset_version'],
            'expected_revision_version':closed['revision_version'], 'reason':'Nueva revisión ficticia para conservar cierre económico.'})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(self.reference()['history'], [])
        self.assertIsNone(self.reference()['latest'])
        self.assertEqual(self.client.get(self.base() + '/export-closed').content, frozen)
        # Exercise recovery with a populated new table and an actual frozen ZIP.
        from scripts.release_snapshot import build_release
        from scripts.recovery_data import make_backup, bundle_backup, restore_archive, fingerprint
        from app.storage import read_verified
        release = self.root / 'economic-source.zip'
        build_release(Path.cwd(), release, synthetic=True)
        backup = self.root / 'backups' / 'economic'
        manifest, digest = make_backup(self.root, backup, release, data_kind='synthetic')
        self.assertEqual(manifest['logical_state']['tables']['row_economic_references']['count'], 1)
        bundle = self.root / 'economic-backup.zip'
        bundle_backup(backup, bundle)
        restored = self.root / 'economic-restored'
        restore_archive(bundle, restored, digest, self.root)
        self.assertEqual(fingerprint(restored), manifest['logical_state'])
        self.assertEqual(read_verified(restored, closed['archive_sha256']), frozen)


class EconomicMigrationTests(unittest.TestCase):
    def test_schema_22_upgrade_is_additive_backed_up_and_atomic_on_failure(self):
        with TemporaryDirectory(dir='.tmp') as directory:
            root = Path(directory)
            conn = connect(root)
            try:
                old = tuple(m for m in MIGRATIONS if m[0] <= 22)
                migrate(conn, migrations=old)
                from app.security import create_user
                user = create_user(conn, 'fictional-owner', PASSWORD, 'admin')
                backup = backup_before_upgrade(conn, root)
                broken = old + ((23, dict(MIGRATIONS)[23] + ('INVALID SQL',)),)
                with self.assertRaises(sqlite3.Error):
                    migrate(conn, migrations=broken, allow_existing_upgrade=True)
                self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 22)
                self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='row_economic_references'").fetchone())
                self.assertEqual(migrate(conn, migrations=tuple(m for m in MIGRATIONS if m[0]<=23), allow_existing_upgrade=True), 23)
                self.assertEqual(conn.execute('SELECT id FROM users').fetchone()[0], user)
                self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])
                restored = sqlite3.connect(backup / 'app.sqlite3')
                try:
                    self.assertEqual(restored.execute('PRAGMA user_version').fetchone()[0], 22)
                    self.assertEqual(restored.execute('SELECT id FROM users').fetchone()[0], user)
                finally:
                    restored.close()
            finally:
                conn.close()

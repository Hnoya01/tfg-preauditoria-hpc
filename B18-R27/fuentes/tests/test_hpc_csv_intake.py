"""Invented records only. Real platform exports must never be test fixtures."""
import csv
import io
import json
import unittest
from copy import deepcopy
from unittest.mock import patch
from app.hpc_csv_adapter import HEADERS
from app.authorization_source import parse_authorization_source
from app.authorization_json import AuthorizationFormatError
from tests import test_sync_intake as sync_tests


def row(**changes):
    result = dict.fromkeys(HEADERS, '')
    result.update(total_ordenes_periodo='1', orden_hpc='TEST-1', categoria='orden.imagen',
                  fecha_orden='2026-08-10', fecha_orden_original='10/08/2026', afiliado='TEST-A',
                  practicas='0000123456  --  Estudio ficticio, con coma $ 123.45,',
                  movimientos='10/08/2026 12:00 | OPERADOR FICTICIO | Autorizado | Texto ficticio',
                  calidad='usable', advertencias='[]', captura_actual_aceptada='Si',
                  captura_id='TEST-C', fecha_captura_utc='2026-11-07 12:00:00')
    result.update(changes)
    return result


def encode(rows, quoting=csv.QUOTE_MINIMAL):
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=HEADERS,quoting=quoting)
    writer.writeheader()
    for value in rows:
        writer.writerow(dict(value,total_ordenes_periodo=str(len(rows))))
    return stream.getvalue().encode('utf-8-sig')


class CsvContractTests(unittest.TestCase):
    def test_preserves_codes_text_and_recognizes_listed_item_decision(self):
        p=parse_authorization_source(encode([row()]))
        o=p.canonical['orders'][0]; i=o['items'][0];r=o['resolutions'][0]
        self.assertEqual(i['full_code'],'0000123456')
        self.assertIn(', con coma $ 123.45',i['description'])
        self.assertIsNone(i['requested_quantity']);self.assertIsNone(i['service_date'])
        self.assertEqual(r['status'],'authorized');self.assertEqual(r['scope'],'item');self.assertEqual(r['item_ids'],['csv-item:0'])
        self.assertEqual(r['authorized_quantity'],'1');self.assertFalse(p.summary['analysis_started'])
        self.assertEqual(p.canonical['coverage']['declared'],'partial')

    def test_quarantine_explicit_record_locator(self):
        p=parse_authorization_source(encode([row(),row(orden_hpc='TEST-2',afiliado='',calidad='needs_review',captura_actual_aceptada='No',advertencias='["identity_fields_incomplete"]')]))
        self.assertEqual(p.summary['orders'],1)
        q=p.summary['adapter_provenance']['quarantine'];self.assertEqual(q[0]['csv_record'],3)
        self.assertIn('missing_affiliate',q[0]['codes'])
        self.assertEqual(p.observations[0]['code'],'csv_record_quarantined')
        self.assertEqual(json.loads(p.manifest)['observations'][0],p.observations[0])
        self.assertEqual(p.summary['adapter_provenance']['row_locators'],[{'order_position':0,'csv_record':2}])

    def test_missing_practices_not_missing_authorization_conclusion(self):
        p=parse_authorization_source(encode([row(practicas='')]))
        self.assertEqual(p.summary['orders'],1);self.assertEqual(p.summary['items'],0)
        self.assertFalse(p.summary['controls_evaluated'])

    def test_repeated_codes_not_deduplicated(self):
        p=parse_authorization_source(encode([row(practicas='0000123456  --  Uno,0000123456  --  Dos,')]))
        self.assertEqual(p.summary['items'],2);self.assertEqual(p.summary['potentially_ambiguous_orders'],1)

    def test_bad_date_and_flattening_are_quarantined(self):
        for changes in [{'fecha_orden_original':'11/08/2026'}, {'fecha_captura_utc':'invalid'}, {'practicas':'123456 -- Sin contrato,'}, {'practicas':'0000123456  --  Falta delimitador'}, {'categoria':'otro'}]:
            p=parse_authorization_source(encode([row(),row(orden_hpc='TEST-2',**changes)]))
            self.assertEqual(p.summary['orders'],1)
            self.assertEqual(p.summary['adapter_provenance']['unrepresented_rows'],1)

    def test_duplicate_orders_invalid_header_count_and_warning_fail(self):
        raw=encode([row()])
        for content in [encode([row(),row()]),raw.replace(b'categoria',b'otra_columna'),raw.replace(b'\r\n1,',b'\r\n9,'),encode([row(advertencias='{}')]),raw+b'extra\r\n',b'\xff']:
            with self.assertRaises(AuthorizationFormatError):parse_authorization_source(content)

    def test_code_like_unparsed_second_practice_is_quarantined(self):
        for practices in ['0000123456  --  Uno,123456 -- Dos,',
                          '0000123456  --  Uno, 0000123457 -- Dos,',
                          '0000123456  --  Uno,0000123457--Dos,']:
            p=parse_authorization_source(encode([row(),row(orden_hpc='TEST-2',practicas=practices)]))
            self.assertEqual(p.summary['orders'],1)
            self.assertEqual(p.summary['adapter_provenance']['unrepresented_rows'],1)
            self.assertIn('practice_separator_requires_review',p.summary['adapter_provenance']['quarantine'][0]['codes'])

    def test_quoted_header_is_standard_csv(self):
        p=parse_authorization_source(encode([row()],quoting=csv.QUOTE_ALL))
        self.assertEqual(p.summary['orders'],1)

    def test_blank_and_whitespace_duplicate_order_ids_rejected(self):
        for rows in [[row(orden_hpc='   ')], [row(), row(orden_hpc=' TEST-1 ')]]:
            with self.assertRaises(AuthorizationFormatError):parse_authorization_source(encode(rows))

    def test_no_usable_rows_is_not_empty_valid_capture(self):
        with self.assertRaises(AuthorizationFormatError):parse_authorization_source(encode([row(afiliado='')]))


class CsvApiTests(unittest.TestCase):
    setUp=sync_tests.SyncIntakeTests.setUp
    tearDown=sync_tests.SyncIntakeTests.tearDown
    headers=sync_tests.SyncIntakeTests.headers
    import_book=sync_tests.SyncIntakeTests.import_book
    run_url=sync_tests.SyncIntakeTests.run_url
    url=sync_tests.SyncIntakeTests.url
    stage=sync_tests.SyncIntakeTests.stage
    preview=sync_tests.SyncIntakeTests.preview
    confirm=sync_tests.SyncIntakeTests.confirm

    def test_csv_original_preview_confirm_and_duplicate(self):
        raw=encode([row()])
        with patch('socket.socket.connect',side_effect=AssertionError('network forbidden')):
            u=self.stage(raw,name='platform.csv').json();p=self.preview(u)
            self.assertTrue(p['can_import']); self.assertEqual(p['summary']['adapter_provenance']['adapter'],'hpc-platform-csv-v6')
            result=self.confirm(u,p);self.assertEqual(result.status_code,201,result.text)
            self.assertFalse(result.json()['analysis_started'])
            self.assertEqual(self.client.get(self.url(f'uploads/{u["id"]}/file')).content,raw)
            self.assertEqual(self.stage(raw,name='renamed.csv').status_code,200)
            self.assertEqual(self.confirm(u).status_code,200)

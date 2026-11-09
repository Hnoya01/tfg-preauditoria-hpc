"""Cantidades expresas en fuentes ficticias HPC, desde el CSV hasta la planilla."""
import contextlib
import io
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from app.authorization_source import parse_authorization_source
from app.csv_coverage import assess_group
from scripts.create_review_journey_demo import main
from tests import test_row_decisions as base
from tests.test_hpc_csv_intake import encode,row


class OrderUnitsTests(unittest.TestCase):
    setUp=base.RowDecisionTests.setUp
    login=base.RowDecisionTests.login
    info=base.RowDecisionTests.info
    board=base.RowDecisionTests.board

    @classmethod
    def setUpClass(cls):
        name='r21-units-'+uuid4().hex
        with patch.object(sys,'argv',['demo','--dos-tac','--name',name]),contextlib.redirect_stdout(io.StringIO()):
            main()
        cls.sample=Path(__file__).resolve().parents[1]/'.tmp'/name
        cls.passwords=dict(line.split(': ',1) for line in (cls.sample/'credenciales-demo.txt').read_text().splitlines())

    def test_invoice_and_later_tac_across_board_pages(self):
        def get_row(offset):
            page=self.board('all',scope='all',limit=1,offset=offset)
            return page['items'][0]
        # Reading the later row first must not change which units it sees.
        later=get_row(1)
        full=get_row(0)
        covered=full['authorization']['panel_signal']['csv_coverage']
        self.assertEqual((covered['status'],covered['covered_units'],covered['billed_units']),('units_supported',2,2))
        self.assertIsNone((full.get('administrative_decision') or {}).get('proposal'))
        consumed=later['authorization']['panel_signal']['csv_coverage']
        self.assertEqual(consumed['status'],'already_used')
        self.assertEqual([(r['source_row'],r['units']) for r in consumed['previous_rows']],[(2,2)])
        self.assertEqual(self.info(3)['proposal']['amount_ars'],'100000.00')
        self.assertEqual(self.c.execute('SELECT count(*) FROM invoice_row_decisions').fetchone()[0],0)

    def test_explicit_item_quantities_and_no_guess_from_prices_or_other_codes(self):
        code='1234567890';other='8888888888'
        def parse(clause,listed='TAC ficticia',status='AUTORIZADO'):
            csv=encode([row(afiliado='000111/1',practicas=f'{code} -- {listed},{other} -- Eco ficticia,',
                            movimientos=f'02/07/2026 10:00 | Operador ficticio | {status} | Resolución por ítems - '+clause)])
            return parse_authorization_source(csv)
        for clause,listed in [(f'AUTORIZAR: {code} x2','TAC ficticia'),
                               (f'AUTORIZAR: {code} - TAC ficticia cantidad autorizada: dos','TAC ficticia'),
                               (f'AUTORIZAR: {code} - TAC ficticia (x2)','TAC ficticia'),
                               (f'AUTORIZAR: {code} - dos TAC ficticia','TAC ficticia'),
                               (f'AUTORIZAR: {code} - TAC ficticia cantidad autorizada: 2','TAC ficticia'),
                               (f'AUTORIZAR: {code}','TAC ficticia x2')]:
            p=parse(clause,listed);o=p.canonical['orders'][0]
            self.assertEqual(p.summary['adapter_provenance']['adapter'],'hpc-platform-csv-v4')
            self.assertEqual([(r['authorized_quantity'],r['item_ids']) for r in o['resolutions']],[('2',['csv-item:0'])])
        p=parse(f'AUTORIZAR: {code} x1','TAC ficticia x2')
        self.assertEqual(p.canonical['orders'][0]['resolutions'][0]['authorized_quantity'],'1')
        for tail in ['x0','x2 o x3','x2 si se presenta informe','x2 de contraste',
                     'x2.5','cantidad autorizada: -2']:
            p=parse(f'AUTORIZAR: {code} - TAC ficticia '+tail)
            self.assertFalse(any(r['status']=='authorized' for r in p.canonical['orders'][0]['resolutions']))
        p=parse(f'AUTORIZAR: {code} - TAC ficticia x2','TAC ficticia','DERIVADO')
        self.assertFalse(any(r['status']=='authorized' for r in p.canonical['orders'][0]['resolutions']))
        p=parse(f'AUTORIZAR: {code} - TAC ficticia por un total autorizado de ARS 200.000')
        self.assertIsNone(p.canonical['orders'][0]['resolutions'][0]['authorized_quantity'])

    def test_units_consumed_once_across_lots_and_order_by_service_date(self):
        item=dict(reference=('cap',0,0),locator='item',sha256='fixture',day=date(2026,7,2),
                  authorized=True,rejected=False,unique=True,description='TAC',provider='HPC',authorized_units=2)
        def line(lot,day,qty):
            return dict(day=date(2026,8,day),key=(lot,2),batch_id=lot,quantity=qty,description='TAC',uncertain=False)
        for lines,expected in [
            ([line('C',4,1),line('A',2,1),line('B',3,1)],['already_used','units_supported','already_used']),
            ([line('C',4,1),line('A',2,1),line('B',2,1)],['already_used','units_supported','units_supported']),
            ([line('A',2,3),line('B',3,1)],['units_partial','already_used']),
            ([line('A',2,2),line('B',2,1),line('C',3,1)],['needs_review']*3)]:
            signals=assess_group(lines,[item])
            self.assertEqual([signals[r['key']]['status'] for r in lines],expected)
            self.assertLessEqual(sum(s.get('covered_units',0) for s in signals.values()),2)


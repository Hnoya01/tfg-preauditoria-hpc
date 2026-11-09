"""End-to-end synthetic HPC orders, incorporation and reassignment."""
from decimal import Decimal
import unittest
from tests.test_r24 import R24 as fixture, base
from app.csv_actions import record_group,reassign
from app.review import _batch
from app.row_decisions import authorization_shortfall
from app.service import Problem


class Journey(unittest.TestCase):
    setUp=fixture.setUp
    invoice=fixture.invoice
    source_csv=fixture.source_csv
    signals=fixture.signals
    register=fixture.register

    def versions(self):
        return dict(expected_version=self.f.version(),expected_revision_version=_batch(self.c,self.ds,self.bid)['revision_version'])

    def test_posterior_candidate_and_atomic_transfer(self):
        self.source_csv(base.CSV+' -- TAC ficticia,',movement='03/08/2026 12:00 | Ficticio | AUTORIZADO | ')
        self.invoice([dict(code=base.INVOICE),dict(code=base.INVOICE,date='04/08/2026')])
        self.register([[base.INVOICE,base.CSV]])
        earlier,later=self.signals().values()
        self.assertEqual((earlier['status'],later['status']),('posterior_candidate','one_unit_supported'))
        self.assertEqual(authorization_shortfall(Decimal(100000),earlier)['amount_ars'],'100000.00')
        versions=self.versions()
        kwargs=dict(**versions,source_sha256=earlier['source_sha256'],locator=earlier['locator'],reason='Orden ficticia cotejada para la prestación del día dos.')
        reassign(self.c,self.root,self.token,self.ds,self.bid,2,**kwargs)
        revised=self.signals()
        self.assertEqual(revised[2]['covered_units'],1)
        self.assertEqual(revised[3]['status'],'already_used')
        self.assertEqual(revised[3]['previous_rows'][0]['source_row'],2)
        with self.assertRaises(Problem):
            reassign(self.c,self.root,self.token,self.ds,self.bid,2,**kwargs)
        self.assertEqual(self.c.execute('SELECT count(*) FROM csv_verified_assignments').fetchone()[0],1)

    def test_group_document_checks_rows_and_rolls_back(self):
        self.source_csv(base.CSV+' -- TAC ficticia,')
        self.invoice([dict(code=base.INVOICE),dict(code=base.INVOICE)])
        self.register([[base.INVOICE,base.CSV]])
        args=(self.c,self.root,self.token,self.ds,self.bid)
        opts=dict(**self.versions(),incorporation='2026-08-18',locator='Comprobante ficticio, hoja uno')
        with self.assertRaises(Problem):
            record_group(*args,rows=[2,99999],**opts)
        self.assertEqual(self.c.execute('SELECT count(*) FROM current_authorization_input_versions').fetchone()[0],0)
        record_group(*args,rows=[2,3],**opts)
        self.assertEqual(self.c.execute('SELECT count(*) FROM current_authorization_input_versions WHERE value=?',('2026-08-18',)).fetchone()[0],2)
        with self.assertRaises(Problem):
            record_group(*args,rows=[2],**opts)

    def test_grouped_different_studies_one_order(self):
        self.source_csv(base.CSV+' -- TAC ficticia,6543210200 -- TAC con contraste ficticia,',movement=
            '02/07/2026 12:00 | Ficticio | AUTORIZADO | AUTORIZADO DR. FICTICIO')
        self.invoice([dict(code=base.INVOICE,qty=2),dict(code=base.INVOICE,date='04/08/2026')])
        self.register([[base.INVOICE,base.CSV],[base.INVOICE,'6543210200']])
        first,repeat=self.signals().values()
        self.assertEqual((first['covered_units'],first['billed_units'],len(first['allocations'])),(2,2,2))
        self.assertEqual(repeat['status'],'already_used')

    def test_duplicate_request_with_complete_and_partial_export(self):
        from app.authorization_matching import save_scope
        self.source_csv(base.CSV+' -- TAC ficticia,',movement='02/07/2026 12:00 | Ficticio | RECHAZADO | Ya se autorizó en orden 7788')
        self.invoice([dict(code=base.INVOICE)])
        self.register([[base.INVOICE,base.CSV]])
        sig=self.signals()[2]
        self.assertEqual((sig['status'],sig['prior_order_id']),('prior_not_found','7788'))
        self.assertEqual(authorization_shortfall(Decimal(100000),sig)['amount_ars'],'100000.00')
        save_scope(self.c,self.root,self.token,self.ds,self.bid,self.f.version(),[self.cap],'real_unvalidated','Exportación parcial de prueba sin declaración de cobertura.')
        self.assertIsNone(authorization_shortfall(Decimal(100000),self.signals()[2]))

    def test_expiry_uses_two_distinct_orders_once(self):
        from tests.test_hpc_csv_intake import row,encode
        from app.authorization_imports import stage_authorization,preview_authorization,confirm_authorization
        orders=[row(orden_hpc=ident,afiliado='000222/1',practicas=base.CSV+' -- TAC ficticia,',
            movimientos=stamp+' 12:00 | Ficticio | AUTORIZADO | ') for ident,stamp in [('NEW','15/07/2026'),('OLD','01/07/2026')]]
        up,_=stage_authorization(self.c,self.root,self.token,self.ds,self.f.version(),'FICTICIO.csv',encode(orders))
        pre=preview_authorization(self.c,self.root,self.token,self.ds,up['id'])
        cap,_=confirm_authorization(self.c,self.root,self.token,self.ds,up['id'],self.f.version(),pre['preview_sha256'],'Órdenes de prueba ficticias.')
        self.cap=cap['id']
        self.invoice([dict(code=base.INVOICE,date=d) for d in ('02/08/2026','04/08/2026','06/08/2026')])
        self.register([[base.INVOICE,base.CSV]])
        signals=self.signals()
        self.assertEqual([signals[n].get('order_id') for n in (2,3)],['OLD','NEW'])
        self.assertEqual(signals[4]['status'],'already_used')

    def test_renegotiated_amount_and_period(self):
        from app.csv_coverage import csv_sequence
        from datetime import date
        self.source_csv(base.CSV+' -- TAC ficticia,',movement='02/07/2026 12:00 | Ficticio | AUTORIZADO | Valor renegociado ARS 20.000')
        self.invoice([dict(code=base.INVOICE)])
        self.register([[base.INVOICE,base.CSV]])
        sig=self.signals()[2]
        self.assertEqual(sig['budget']['excess_ars'],'80000.00')
        item={'day':date(2026,7,2),'origin':'synthetic','decided_at':'2026-07-02T12:00'}
        for inc,expected in [('2026-08-31','sin_observaciones'),('2026-09-01','con_indicios')]:
            self.assertEqual(csv_sequence(item,{'incorporation':{'value':inc,'origin':'synthetic'}})['state'],expected)

    def test_destination_annotation_is_not_always_an_external_provider(self):
        self.source_csv(base.CSV+' -- TAC ficticia,6543210200 -- Otro estudio ficticio,',
            movement='02/07/2026 12:00 | Ficticio | RECHAZADO | Se deriva a auditoría. [DER:FICTICIO]')
        self.invoice([dict(code=base.INVOICE)])
        self.register([[base.INVOICE,base.CSV],[base.INVOICE,'6543210200']])
        sig=self.signals()[2]
        self.assertEqual(sig['status'],'referral_pending')
        self.assertIsNone(authorization_shortfall(Decimal(100000),sig))

    def test_rejection_last_movement_and_missing_affiliate(self):
        self.source_csv(base.CSV+' -- TAC ficticia,',movement='01/07/2026 12:00 | Ficticio | AUTORIZADO | \n02/07/2026 12:00 | Ficticio | RECHAZADO | Se deriva a otro prestador.')
        self.invoice([dict(code=base.INVOICE),dict(code=base.INVOICE,affiliate=None)])
        self.register([[base.INVOICE,base.CSV]])
        declined,missing=self.signals().values()
        self.assertEqual((declined['status'],missing['status']),('referred_elsewhere','unidentified'))
        for signal in (declined,missing):
            self.assertEqual(authorization_shortfall(Decimal(100000),signal)['amount_ars'],'100000.00')


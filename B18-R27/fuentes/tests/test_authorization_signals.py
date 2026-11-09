import unittest
from app.authorization_signals import panel_signal, csv_order_history

class PanelSignalTests(unittest.TestCase):
    def evidence(self, candidates=None):
        return {'disposition':'included','issues':[],'state':'needs_review','basis_sha256':'basis','candidates':candidates or []}
    def candidate(self, state='declared_authorized', **changes):
        return dict({'key':'C:0:0','compatibility':'compatible','capture_id':'C','locator':'$.orders[0].items[0]',
                     'source_sha256':'a'*64,'item_resolution_state':state,'csv_order_history':[]},**changes)
    def signal(self, ev, related=None, link=None):
        return panel_signal(ev, {'candidates':related or []}, link)
    def test_explicit_item_statuses_and_no_decision(self):
        for state in ('authorized','rejected','pending','referred'):
            s=self.signal(self.evidence([self.candidate('declared_'+state)]))
            self.assertEqual(s['presence'],'found');self.assertEqual(s['item_authorization'],state)
            self.assertFalse(s['is_audit_decision']);self.assertIsNotNone(s['decision_basis'])
    def test_absence_not_rejection_and_unselected_sources_not_absence(self):
        s=self.signal(self.evidence());self.assertEqual(s['presence'],'not_located');self.assertEqual(s['item_authorization'],'not_determinable')
        for state in ('scope_missing','requires_update','identity_or_code_unresolved','candidate_limit'):
            s=self.signal(dict(self.evidence(),state=state));self.assertEqual(s['presence'],'not_evaluated')
    def test_csv_history_is_not_item_authorization_even_when_approved(self):
        c=self.candidate('no_concluyente',compatibility='needs_review',csv_order_history=['autorizado'])
        s=self.signal(self.evidence([c]));self.assertEqual(s['presence'],'found');self.assertEqual(s['item_authorization'],'not_determinable')
        s=self.signal(self.evidence(),[c]);self.assertEqual(s['presence'],'candidate');self.assertEqual(s['item_authorization'],'not_determinable')
        self.assertEqual(s['order_history_states'],['autorizado'])
    def test_ambiguity_stale_and_unresolved_link_do_not_approve(self):
        candidates=[self.candidate(),self.candidate('declared_rejected',key='C:0:1')]
        e=self.evidence(candidates);self.assertEqual(self.signal(e)['item_authorization'],'not_determinable')
        link={'state':'selected','basis_sha256':'basis','candidate_key':'C:0:0'}
        self.assertEqual(self.signal(e,link=link)['item_authorization'],'authorized')
        for changes in ({'state':'unresolved'},{'basis_sha256':'old'},{'candidate_key':'missing'}):
            self.assertEqual(self.signal(e,link=dict(link,**changes))['item_authorization'],'not_determinable')
    def test_incompatible_not_authorized_and_unknown_resolution(self):
        self.assertEqual(self.signal(self.evidence([self.candidate(compatibility='incompatible')]))['presence'],'incompatible')
        self.assertEqual(self.signal(self.evidence([self.candidate('no_concluyente')]))['item_authorization'],'not_determinable')
    def test_csv_parser_only_status_column_and_preserves_mixed_history(self):
        order={'resolutions':[{'reason':'01/08/2026 10:00 | Operador ficticio | AUTORIZADO | Motivo ficticio\n02/08/2026 10:00 | Operador ficticio | RECHAZADO | Corrección'}]}
        self.assertEqual(csv_order_history(order,{'source_system':'HPC-CSV'}),['autorizado','rechazado'])
        self.assertEqual(csv_order_history(order,{'source_system':'other'}),[])
        order['resolutions'][0]['reason']='La descripción dice AUTORIZADO pero no es columna de estado'
        self.assertEqual(csv_order_history(order,{'source_system':'HPC-CSV'}),[])

    def test_reason_cannot_forge_status_column_and_bad_layout_is_unknown(self):
        capture={'source_system':'HPC-CSV'}
        for text in (
            '01/08/2026 10:00 | Operador ficticio | PENDIENTE | Nota literal: | AUTORIZADO | se refiere a antecedente',
            '01/08/2026 10:00 | Operador ficticio | PENDIENTE | AUTORIZADO',
            '31/02/2026 10:00 | Operador ficticio | AUTORIZADO | Fecha inválida',
            '01/08/2026 10:00 |  | AUTORIZADO | Falta actor',
            '01/08/2026 10:00 | Operador ficticio | AUTORIZADO | Un motivo\ncontinuación sin estructura',
            '| AUTORIZADO | sin evento',
        ):
            self.assertEqual(csv_order_history({'resolutions':[{'reason':text}]},capture),[],text)
        text='01/08/2026 10:00 | Operador ficticio | RECHAZADO | Nota literal: | AUTORIZADO | antecedente'
        self.assertEqual(csv_order_history({'resolutions':[{'reason':text}]},capture),['rechazado'])

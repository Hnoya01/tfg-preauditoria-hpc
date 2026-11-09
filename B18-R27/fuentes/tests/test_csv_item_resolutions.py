"""Fictitious source declarations; no real patient/source excerpts."""
import unittest
from app.authorization_source import parse_authorization_source
from app.authorization_assessment import applicable_resolution
from app.authorization_signals import panel_signal, csv_order_history
from tests.test_hpc_csv_intake import row, encode

A, B = '0000123456', '0000654321'
PRACTICES = f'{A} -- Estudio ficticio A,{B} -- Estudio ficticio B,'
HEADER = 'Resolucion por items - AUTORIZAR: 1) Autorizar: '
EVENT = '10/08/2026 12:00 | Operador ficticio | AUTORIZADO | '


def parse(reason, practices=PRACTICES):
    return parse_authorization_source(encode([row(practicas=practices, movimientos=reason)]))


def states(parsed):
    o = parsed.canonical['orders'][0]
    return [applicable_resolution(o, i)['state'] for i in o['items']]


class ExplicitCsvTests(unittest.TestCase):
    def test_two_different_individual_decisions_not_global(self):
        text = EVENT + HEADER + A + ' - Texto ficticio.; 2) No autorizar: ' + B + ' - Otro texto.'
        p = parse(text)
        self.assertEqual(states(p), ['declared_authorized', 'declared_rejected'])
        ev = p.summary['adapter_provenance']['item_resolution_evidence'][0]['evidence']
        for e in ev:
            self.assertEqual(text[e['start']:e['end']], e['excerpt'])
            self.assertEqual(text[e['code_start']:e['code_end']], e['full_code'])
            self.assertEqual(e['csv_record'], 2)
            self.assertEqual(len(e['source_sha256']), 64)
        self.assertEqual(csv_order_history(p.canonical['orders'][0], {'source_system':'HPC-CSV'}), ['autorizado'])

    def test_no_header_free_prose_and_prefix_not_decisions(self):
        for reason in [f'Autorizar: {A}', f'Resolucion por items - Autorizar: {A}/12', f'Resolucion por items - Autorizar: {A}-12', f'Resolucion por items - NO AUTORIZAR: 1) Autorizar: {A}', f'Resolucion por items - No se debe 1) Autorizar: {A}', f'Ejemplo Resolucion por items - Autorizar: {A}', f'Resolucion por items - No se debe Autorizar: {A}', f'Se autoriza {A}', f'Resolucion por items - Autorizar: {A[:-1]}',
                       f'Resolucion por items - Autorizar: x{A}', f'Resolucion por items - Autorizar: {A}9']:
            self.assertEqual(states(parse(EVENT + reason)), ['no_concluyente']*2)

    def test_unparsed_correction_and_conditional_remain_indeterminate(self):
        approved = EVENT + HEADER + A
        for text in [approved + '\n' + EVENT + 'Resolución por ítems - NO AUTORIZAR ' + A,
                     approved + ' solo si se presenta informe; pendiente de confirmación']:
            result = parse(text)
            self.assertEqual(states(result)[0], 'no_concluyente')
            self.assertTrue(result.summary['adapter_provenance']['item_resolution_evidence'][0]['warnings'])

    def test_csv_declaration_is_separate_from_unverified_correspondence(self):
        for label in ('authorized', 'rejected'):
            candidate = dict(source_system='HPC-CSV', key='ficticio', compatibility='needs_review',
                             item_resolution_state='declared_' + label)
            evidence = dict(disposition='included', issues=[], state='needs_review',
                            candidates=[candidate], basis_sha256='test')
            signal = panel_signal(evidence, {'candidates': []})
            self.assertEqual(signal['csv_item_declaration'], label)
            self.assertEqual(signal['item_authorization'], 'not_determinable')
            evidence['candidates'] = [candidate, candidate]
            self.assertNotIn('csv_item_declaration', panel_signal(evidence, {'candidates': []}))

    def test_duplicate_code_blocks_assignment(self):
        p=parse(EVENT+HEADER+A, f'{A} -- Uno,{A} -- Dos,')
        self.assertEqual(states(p), ['no_concluyente']*2)

    def test_contradiction_same_event(self):
        p=parse(EVENT+HEADER+A+'; No autorizar: '+A)
        self.assertEqual(states(p), ['no_concluyente']*2)
        self.assertTrue(p.summary['adapter_provenance']['item_resolution_evidence'][0]['warnings'])

    def test_conflicting_events_and_duplicate_events_not_latest_wins(self):
        for tail in ['No autorizar: ', 'Autorizar: ']:
            p=parse(EVENT+HEADER+A+'\n'+EVENT+'Resolucion por items - '+tail+A)
            self.assertEqual(states(p), ['no_concluyente']*2)

    def test_unknown_code_incomplete_clause_and_bad_event_block(self):
        for suffix in ['; No autorizar: 9999999999', '; No autorizar: sin detalle', '\nSin evento interpretable']:
            self.assertEqual(states(parse(EVENT+HEADER+A+suffix)), ['no_concluyente']*2)

    def test_referral_is_not_authorization(self):
        p=parse(EVENT+f'[DER:TEST] CORRESPONDEN: {A}; NO CORRESPONDE: {B}')
        self.assertEqual(states(p), ['no_concluyente']*2)
        ev=p.summary['adapter_provenance']['item_resolution_evidence'][0]['evidence']
        self.assertEqual([e['state'] for e in ev], ['included','excluded'])
        self.assertEqual({e['kind'] for e in ev}, {'referral'})

    def test_referral_contradiction_remains_indeterminate(self):
        p=parse(EVENT+f'[DER:TEST] CORRESPONDEN: {A}; NO CORRESPONDE: {A}')
        ev=p.summary['adapter_provenance']['item_resolution_evidence'][0]['evidence']
        self.assertEqual([e['state'] for e in ev], ['indeterminate']*2)

    def test_status_does_not_reach_unaccredited_invoice_match(self):
        p=parse(EVENT+HEADER+A)
        state=states(p)[0]
        c={'compatibility':'unknown','key':'one','item_resolution_state':state,
           'capture_id':'synthetic','locator':'item:0','source_sha256':'0'*64}
        evidence={'disposition':'included','issues':[], 'state':'candidate','candidates':[c], 'basis_sha256':'x'}
        self.assertEqual(panel_signal(evidence,{'candidates':[]})['item_authorization'],'not_determinable')
        c['compatibility']='compatible'
        self.assertEqual(panel_signal(evidence,{'candidates':[]})['item_authorization'],'authorized')
        self.assertEqual(panel_signal(evidence,{'candidates':[]}, {'state':'selected','basis_sha256':'stale'})['item_authorization'],'not_determinable')

    def test_authorization_does_not_assign_quantity_or_price(self):
        p=parse(EVENT+HEADER+A)
        r=p.canonical['orders'][0]['resolutions'][0]
        self.assertIsNone(r['authorized_quantity']); self.assertIsNone(r['unit'])
        self.assertFalse(p.summary['controls_evaluated'])

if __name__ == '__main__': unittest.main()

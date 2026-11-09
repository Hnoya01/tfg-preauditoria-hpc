"""One administrative decision per invoice row. Amounts are never posted to an institutional system."""
import hashlib
import json
import re
from decimal import Decimal
from .db import transaction
from .review import _batch
from .service import authorized_dataset, check_version, event, Problem
from .security import now_utc

ACTIONS = {'accept', 'partial', 'total', 'none'}
FINAL_COLUMNS = 'ordinal,action,amount_ars,reason,reference,correction_note,created_at'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def money(value):
    text = str(value)
    return Decimal(text) if re.fullmatch(r'[0-9]{1,18}(?:\.[0-9]{1,2})?',text) else None


def label(amount):
    return format(amount, ',.2f').translate(str.maketrans(',.','.,')).removesuffix(',00')


def has_duty(conn, user, dataset_id):
    return user['role'] == 'admin' or user['role'] == 'reviewer' and bool(conn.execute(
        "SELECT 1 FROM invoice_review_duties WHERE dataset_id=? AND user_id=? AND duty='administrative'",
        (dataset_id,user['id'])).fetchone())


def latest_records(conn, revision):
    return {r['source_row']: dict(r) for r in conn.execute(
        'SELECT d.* FROM invoice_row_decisions d JOIN '
        '(SELECT source_row,max(ordinal) AS ordinal FROM invoice_row_decisions WHERE revision_id=? GROUP BY source_row) v '
        'USING(source_row,ordinal) WHERE d.revision_id=?',(revision,revision))}


def unit_gap(billed, csv):
    """Amount of identical billed units not explained by the identified item(s)."""
    if billed is None or billed <= 0:
        return None
    status = csv.get('status')
    if status not in ('one_unit_only', 'units_partial', 'component_pending'):
        return None
    units, covered = csv.get('billed_units'), csv.get('covered_units', 1)
    if status == 'component_pending' and ('component_capacity' not in csv or not csv.get('parent_row')):
        return None
    if not isinstance(units, int) or not isinstance(covered, int) or not 0 <= covered < units:
        return None
    # El total ya incluye todas las unidades. Solo se prorratea la parte sin aval.
    amount = billed * (units - covered) / units
    if amount != amount.quantize(Decimal('.01')):
        return None
    return {'amount_ars': format(amount, '.2f'), 'covered': covered, 'units': units}


def advisory_gap(billed, csv):
    gap = unit_gap(billed, csv)
    if not gap or (csv.get('budget') or {}).get('authorized_ars') is not None:
        return None
    if csv.get('export_scope') and not csv.get('coverage_note'):
        return None
    return {**gap, 'reason': f"La fuente respalda {gap['covered']} de {gap['units']} unidades. "
            f"Quedan ${label(Decimal(gap['amount_ars']))} a verificar. Comprobá si otra orden cubre la cantidad restante."}


def authorization_shortfall(billed,csv):
    if csv.get('status')=='unidentified' and billed is not None and billed>0:
        return {'amount_ars':format(billed,'.2f'),'reason':'Afiliado no identificable · débito total propuesto.'}
    if not csv.get('export_scope') or csv.get('coverage_note') or billed is None or billed<=0:
        return None
    status=csv.get('status')
    if status in ('one_unit_only','units_partial'):
        gap = unit_gap(billed, csv)
        if not gap:
            return None
        units, covered = gap['units'], gap['covered']
        portion = Decimal(gap['amount_ars'])
        reason=f'{covered} de {units} autorizada{"s" if covered!=1 else ""}. Facturado por {units} unidades iguales: ${label(billed)}. Se propone ${label(portion)} por la cantidad sin aval.'
        return {'amount_ars':format(portion,'.2f'),'reason':reason}
    reasons={'posterior_candidate':'Posible débito · verificar orden.',
             'referred_elsewhere':'Derivada a otro prestador.',
             'prior_not_found':'Débito total propuesto · aval anterior no localizado.',
             'no_aval':'Sin aval localizado en el CSV completo.',
             'already_used':'El aval ya respaldó otra prestación.',
             'declared_rejected':'El CSV declara rechazada la práctica.',
             'outside_window':'El aval localizado está fuera del plazo de 60 días.'}
    if status in reasons:
        return {'amount_ars':format(billed,'.2f'),'reason':reasons[status]+' Se propone revisar el total facturado.'}
    return None


def candidates(billed,csv,ref,agreement,legacy):
    if csv.get('status') in ('unidentified','posterior_candidate','prior_not_found','referred_elsewhere','coverage_pending','no_aval','one_unit_only','units_partial','already_used','outside_window','declared_rejected','needs_review','component_pending'):
        return {},False,authorization_shortfall(billed,csv)

    if csv.get('status') in ('referral_pending','later_movement'):
        return {},False,None
    budget = csv.get('budget') or {}
    cap = money(budget.get('authorized_ars')) if budget.get('status') in ('over','within') else None
    compared = ref.get('related_comparison') or ref
    shown = money(compared.get('candidate_total_if_ars_and_same_unit'))
    tariff = None
    if agreement and agreement['current']:
        tariff = Decimal(agreement['basis']['candidate']['rate_ars']) * Decimal(agreement['confirmation']['covered_quantity'])
    choices = {}
    if billed is not None:
        for key,value in [('budget',cap),('agreement',tariff)]:
            if value is None:
                continue
            difference = max(Decimal('0'), billed-value)
            if difference != difference.quantize(Decimal('.01')):
                continue
            source = ('presupuesto de la orden '+str(budget.get('order_id','')) if key=='budget' else 'convenio HPC aplicable')
            choices[key] = {'reference_ars':format(value,'.2f'), 'amount_ars':format(difference,'.2f'),
                            'reason':f'Facturado ${label(billed)}. El {source} cubre ${label(value)}. Diferencia ${label(difference)}.'}
    conflict = cap is not None and (tariff if tariff is not None else shown) not in (None,cap)
    default = None
    if not conflict and billed is not None:
        if 'budget' in choices:
            default = choices['budget']
        elif 'agreement' in choices:
            default = choices['agreement']
        elif legacy and legacy['state']=='current' and money(legacy['amount_ars']) is not None:
            default = {'amount_ars':legacy['amount_ars'],'reason':'Propuesta vigente registrada para esta prestación.'}
    if default and (money(default['amount_ars']) is None or not 0 < Decimal(default['amount_ars']) <= billed):
        default = None
    return choices,conflict,default


class DecisionContext:
    def __init__(self,conn,root,dataset_id,batch,context):
        self.conn,self.root,self.dataset_id,self.batch,self.context = conn,root,dataset_id,batch,context
        self.latest = latest_records(conn,batch['revision_id'])
        from .economic_applicability import _latest
        self.agreements = {r['source_row']:r for r in _latest(conn,batch['revision_id'])}
        self.legacy = {r['source_row']:r for r in conn.execute(
            'SELECT p.* FROM proposal_versions p JOIN (SELECT source_row,max(ordinal) AS ordinal FROM proposal_versions '
            'WHERE revision_id=? GROUP BY source_row) v USING(source_row,ordinal) WHERE p.revision_id=?',
            (batch['revision_id'],batch['revision_id']))}
        self.economic = self.proposals = None
        self.checked_agreements={}

    def agreement(self,number):
        if number not in self.agreements:return None
        if number not in self.checked_agreements:
            from .economic_applicability import Evaluator
            if self.economic is None:self.economic=Evaluator(self.conn,self.root,self.dataset_id,self.context['id'])
            self.checked_agreements[number]=self.economic.evaluate(self.agreements[number])
        return self.checked_agreements[number]

    def describe(self,row,csv,ref,reasons,source_context):
        number=row['source_row']
        if row['family']!='images' or row['disposition']!='included' or self.context['provider']!='HPC':
            return None
        agreement=self.agreement(number)
        legacy=None
        if number in self.legacy:
            from .proposal_freshness import ProposalEvaluator
            if self.proposals is None:
                self.proposals=ProposalEvaluator(self.conn,self.root,self.dataset_id,self.context['id'],self.batch,None)
            legacy=self.proposals.evaluate(self.legacy[number])
        billed=money(row['total_ars'])
        late = row.get('late_billing_reason')
        if late:
            # The full row is proposed once even if a budget or an authorization also falls short.
            choices,conflict,proposal = {}, False, None
            if billed is not None and billed > 0:
                proposal = {'amount_ars':format(billed, '.2f'), 'reason':late + ' Se propone revisar el total facturado.'}
        else:
            choices,conflict,proposal=candidates(billed,csv,ref,agreement,legacy)
        scope,captures,issues=source_context or (None,[],[])
        dependencies={
            'row':{k:row[k] for k in ('source_row','practice_date','code','description','affiliate_id','order_number',
                 'quantity','family','honorarios_ars','derechos_ars','total_ars','documents','alerts')},
            'controls':row['_facets'], 'reasons':sorted(reasons), 'coverage':csv,
            'sources':[scope and scope['id'],[c['source_sha256'] for c in captures],issues],
            'reference':ref, 'agreement':agreement and [agreement['id'],agreement['basis_sha256'],agreement['current']],
            'legacy_proposal':legacy and [legacy['proposal_id'],legacy['state'],legacy['amount_ars']],
            'rules':'row-decision-v1'}
        if late:
            dependencies['billing_window'] = row['billing_window']
        # Confirmations concern evidence for this row, including controls without an alert.
        if self.context['latest_run_id']:
            dependencies['control_evidence']=[tuple(r) for r in self.conn.execute(
                'SELECT rule_code,evidence_json,difference_ars FROM control_results WHERE run_id=? AND source_row=? ORDER BY rule_code',
                (self.context['latest_run_id'],number))]
        signature=digest(dependencies)
        previous=self.latest.get(number)
        current=bool(previous and previous['evidence_hash']==signature)
        return {'evidence_hash':signature,'current':current,'previous':{k:previous[k] for k in FINAL_COLUMNS.split(',')} if previous else None,
                'choices':choices,'conflict':conflict,'proposal':proposal,'billed_ars':row['total_ars'],
                'quantity_advisory':advisory_gap(billed,csv) if not late and not proposal and not conflict and not (agreement and agreement['current']) else None,
                'budget':csv.get('budget'),'blocked':self.batch['state']=='cerrada' or not self.context['latest_run_id']
                  or bool(row['control_counts'].get('requires_update'))}


def detail(conn,root,token,dataset_id,batch_id,number):
    from .practice_board import practice_search
    from .consistent_reads import consistent_read
    def read():
        user,_=authorized_dataset(conn,token,dataset_id,'reviewer')
        page=practice_search(conn,token,dataset_id,batch_id,{'view':'row_detail','_number':number},root=root)
        if not page['items'] or not page['items'][0].get('administrative_decision'):
            raise Problem(409,'La prestación debe ser una imagen HPC con una observación o una decisión anterior.')
        row=page['items'][0]
        revision=_batch(conn,dataset_id,batch_id)['revision_id']
        return page_detail(conn,user,dataset_id,revision,page['dataset_version'],page['batch']['revision_version'],row)
    return consistent_read(conn,token,dataset_id,read)


def page_detail(conn,user,dataset_id,revision,dataset_version,revision_version,row):
    number=row['source_row']
    history=[dict(r) for r in conn.execute(
        f'SELECT {",".join("d."+c for c in FINAL_COLUMNS.split(","))},u.username AS actor FROM invoice_row_decisions d JOIN users u ON u.id=d.actor_id '
        'WHERE revision_id=? AND source_row=? ORDER BY ordinal DESC',(revision,number))]
    return {**row['administrative_decision'],'revision_id':revision,'dataset_version':dataset_version,
            'revision_version':revision_version,'can_write':has_duty(conn,user,dataset_id) and not conn.execute(
                'SELECT 1 FROM invoice_handoffs WHERE revision_id=?',(revision,)).fetchone(),
            'history':history,'reasons':row['exception_details'] or row['exception_reasons']}


def resolve(info,body):
    billed=money(info['billed_ars'])
    action,reference=body['action'],body.get('reference')
    reason=body.get('reason','').strip()
    if billed is None or info['blocked']:
        raise Problem(409,'La prestación requiere datos vigentes y un importe facturado legible.')
    if action not in ACTIONS or (not reason and (action!='accept' or info['previous'])):
        raise Problem(422,'Indicá el motivo de la decisión o de su corrección.')
    if info['conflict'] and not reason:
        raise Problem(422,'Indicá por qué corresponde la referencia elegida.')
    if info['conflict'] and reference not in info['choices']:
        raise Problem(422,'Elegí un presupuesto individual o un convenio HPC con aplicabilidad acreditada.')
    if not info['conflict'] and reference:
        raise Problem(422,'La prestación no requiere elegir referencia.')
    selected=info['choices'].get(reference) if info['conflict'] else info['proposal']
    if action!='partial' and body.get('partial_ars') is not None:
        raise Problem(422,'Un importe editable solo corresponde a débito parcial.')
    if action=='accept':
        amount=money(selected['amount_ars']) if selected else None
        if amount is None or not 0 < amount <= billed:
            raise Problem(422,'No hay un débito propuesto vigente para aceptar.')
        return amount,selected['reason']+(' Referencia elegida: '+reason if info['conflict'] else '')
    if action=='partial':
        amount=money(body.get('partial_ars'))
        if amount is None or not 0 < amount < billed:
            raise Problem(422,'El débito parcial debe ser mayor a cero y menor al total facturado, con hasta dos decimales.')
        return amount,reason
    return (billed if action=='total' else Decimal('0')),reason


def save(conn,root,token,dataset_id,batch_id,number,body):
    request_hash=digest([dataset_id,batch_id,number,body])
    with transaction(conn):
        user,dataset=authorized_dataset(conn,token,dataset_id,'reviewer')
        if not has_duty(conn,user,dataset_id):
            raise Problem(403,'Se requiere la función administrativa para decidir.')
        batch=_batch(conn,dataset_id,batch_id)
        from .invoice_handoff import receipt, LOCK_MESSAGE
        if receipt(conn,batch['revision_id']):
            raise Problem(409,LOCK_MESSAGE)
        prior=conn.execute('SELECT request_hash,ordinal,amount_ars FROM invoice_row_decisions WHERE actor_id=? AND request_id=?',
                           (user['id'],body['request_id'])).fetchone()
        result={'dataset_version':dataset['version'],'revision_version':batch['revision_version']}
        if prior:
            if prior['request_hash']!=request_hash:
                raise Problem(409,'Esta operación ya identifica otra decisión.')
            return {**result,'ordinal':prior['ordinal'],'amount_ars':prior['amount_ars'],'replayed':True}
        check_version(dataset,body['expected_dataset_version'])
        if batch['state']=='cerrada' or batch['revision_id']!=body['revision_id'] or batch['revision_version']!=body['expected_revision_version']:
            raise Problem(409,'La factura cambió o está cerrada. Actualizá la planilla.')
        info=detail(conn,root,token,dataset_id,batch_id,number)
        if info['evidence_hash']!=body['evidence_hash']:
            raise Problem(409,'Cambió la evidencia de la prestación. Volvé a revisarla.')
        amount,reason=resolve(info,body)
        ordinal=1+len(info['history'])
        basis={k:info[k] for k in ('billed_ars','budget','choices','conflict','proposal','reasons','evidence_hash')}
        correction=body['reason'].strip() if ordinal>1 else None
        conn.execute('INSERT INTO invoice_row_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (batch['revision_id'],number,ordinal,body['action'],format(amount,'.2f'),reason,correction,
             body.get('reference'),info['evidence_hash'],json.dumps(basis,sort_keys=True),user['id'],now_utc(),body['request_id'],request_hash))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(dataset_id,))
        conn.execute('UPDATE revisions SET version=version+1 WHERE id=?',(batch['revision_id'],))
        event(conn,user['id'],'administrative_row_decided','revision',batch['revision_id'])
        return {'dataset_version':dataset['version']+1,'revision_version':batch['revision_version']+1,'ordinal':ordinal,'amount_ars':format(amount,'.2f')}


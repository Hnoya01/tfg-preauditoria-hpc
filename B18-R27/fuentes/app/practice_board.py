"""B-UI1: read-only server-side workbench, never a new analysis or decision."""

from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import json

from .controls import RULES, _run_summary
from .dependencies import result_affected
from .eligibility import LATE_REASON, classify, late_reason
from .practice_families import catalog_families, classify_family, classification_evidence
from .review import _batch, _decision_status, _latest_run, _result, selection_basis, selection_record
from .authorization_matching import page_correspondence
from .service import Problem, authorized_dataset, check_version


STATES = ('requires_update', 'con_indicios', 'no_concluyente', 'no_evaluado', 'sin_indicios', 'no_aplicable')
DECISIONS = ('pendiente', 'confirmada', 'descartada', 'no_concluyente')
REASONS = {
    'specific_accepted_reference_pending':'Referencia específica aceptada identificada; sin cálculo general hasta resolver su aplicación',
    'economic_applicability_not_recorded':'Falta documentar la referencia aplicable a esta fila',
    'economic_applicability_not_current':'La referencia se retiró o sus dependencias cambiaron; requiere actualización',
    'tariff_above_applicable_reference':'El total facturado supera la referencia aplicable; revisar la diferencia',
    'tariff_below_applicable_reference':'El total facturado es inferior a la referencia aplicable; revisar la diferencia',
    'tariff_within_tolerance':'El total y la referencia aplicable concilian dentro de $0,01',
    'economic_reference_sufficient_for_row':'Referencia suficiente para esta fila, fecha, unidad y cantidad',
    'demo_autorizacion_declarada':'FICTICIO · autorización declarada compatible',
    'demo_rechazo_declarado':'FICTICIO · la resolución declara rechazo de esta práctica',
    'demo_resolucion_sin_conclusion':'FICTICIO · resolución o vínculo por aclarar',
    'demo_autorizacion_previa_incorporacion':'FICTICIO · autorización anterior a incorporación',
    'demo_autorizacion_posterior_incorporacion':'FICTICIO · autorización posterior a incorporación',
    'demo_secuencia_temporal_incompleta':'FICTICIO · falta evidencia para ordenar autorización e incorporación',
    'demo_cantidad_dentro_declarado':'FICTICIO · cantidad conjunta dentro de lo declarado',
    'demo_cantidad_supera_declarado':'FICTICIO · cantidad conjunta mayor que la declarada',
    'demo_cantidad_sin_conclusion':'FICTICIO · cantidad, cobertura o asociación pendiente',
    'autorizaciones_reales_sin_validar':'La fuente real de autorizaciones todavía no está validada',
    'evidencia_temporal_real_sin_validar':'Las fechas declaradas todavía no acreditan la secuencia real',
    'cobertura_real_sin_validar':'La cobertura real y sus unidades todavía no están validadas',
    'autorizaciones_sin_adaptador_validado': 'Las autorizaciones todavía no se conciliaron con esta factura',
    'falta_fecha_incorporacion_por_practica': 'Falta la fecha de incorporación de esta práctica al Excel',
    'cantidad_autorizada_no_acreditada': 'Falta comprobar cuántas unidades fueron autorizadas',
    'diferencia_supera_tolerancia': 'Honorarios + derechos no coinciden con el total',
    'suma_concilia': 'La suma O + P concilia con Q',
    'posible_duplicacion_literal': 'Posible coincidencia con otra facturación; revisar',
    'analysis_missing': 'Análisis todavía no ejecutado',
    'control_not_recorded': 'Control sin resultado registrado',
    'coincidencia_estricta_candidata': 'Orden, afiliado, código y fecha repetidos en otra facturación',
    'sin_coincidencia_estricta': 'Sin otra fila con la misma orden, afiliado, código y fecha',
    'referencia_economica_no_aplicable_aun': 'Falta validar el valor del convenio para esta práctica',
    'referencia_arancelaria_insuficiente': 'Falta una referencia arancelaria aplicable',
    'ordenes_validas_no_verificadas': 'Control de órdenes todavía sin ejecutar',
    'importes_de_fila_sin_multiplicar': 'Importes tomados de la fila, sin multiplicar por cantidad',
    'total_no_cero': 'Este control sólo corresponde a importes cero',
    'fecha_en_periodo_confirmado': 'Realizada dentro del mes de la factura',
    'facturacion_en_termino': 'Facturación en término (hasta 45 días)',
    'facturacion_fuera_de_termino': LATE_REASON,
    'cero_requiere_referencia_aplicable': 'Importe cero: falta comprobar si corresponde',
    'codigo_no_valorizado_admite_cero': 'El código admite importe cero según la regla declarada',
}


CSV_QUEUE_REASON = {
    'later_movement':'Movimiento posterior en la orden. Comprobar si corresponde a esta prestación.',
    'unidentified':'Afiliado no identificable · débito total propuesto',
    'posterior_candidate':'Posible débito · verificar orden',
    'referred_elsewhere':'Derivada a otro prestador',
    'referral_pending':'Verificar prestador de la derivación',
    'prior_not_found':'Aval anterior no localizado',
    'temporal_pending': 'Pendiente de verificar la incorporación al consolidado.',
    'temporal_late': 'Autorización posterior a la incorporación al consolidado.',
    'no_aval': 'Sin aval localizado en el CSV completo.',
    'coverage_pending': 'Pendiente de cotejo: cobertura del CSV incompleta.',
    'already_used': 'CSV: el aval disponible ya respalda otra prestación.',
    'units_partial': 'La cantidad facturada supera las unidades disponibles.',
    'one_unit_only': 'CSV: el aval respalda una unidad; la cantidad facturada es mayor.',
    'outside_window': 'CSV: ninguna resolución localizada está dentro de los 60 días previos a la prestación.',
    'declared_rejected': 'CSV: consta un rechazo explícito para esta práctica.',
    'needs_review': 'CSV: hay coincidencia, pero no se puede atribuir un aval individual a esta fila.',
    'component_pending': 'Adicional: comprobar el estudio principal y sus unidades.',
}


def reason_label(code):
    return REASONS.get(code, code.replace('_', ' ').capitalize())


@contextmanager
def _snapshot(conn):
    if conn.in_transaction:
        yield
        return
    conn.execute('BEGIN')
    try:
        yield
    finally:
        conn.rollback()  # Close the read snapshot; never acquire the writer.


def _validate(filters):
    if filters.get('view')=='row_detail' and '_number' not in filters and not filters.get('_report'):
        raise Problem(422,'Elegí una prestación para ver su decisión.')
    if filters.get('reference_comparison_state', 'all') not in ('all','differences','equal','undetermined'):
        raise Problem(422, 'Filtro de comparación exploratoria inválido')
    if filters.get('csv_review_state','all') not in ('all','supported','review','rejected','undetermined','budget'):
        raise Problem(422,'Estado de aval CSV inválido')
    for key in ('report_document_state', 'authorization_document_state'):
        if filters.get(key, 'all') not in ('all','no_aportado','aportado_sin_revisar','revisado_manualmente'):
            raise Problem(422, 'Estado documental inválido')
    if filters.get('family', 'all') not in ('all', 'images', 'images_and_candidates', 'image_candidates', 'other', 'unclassified'):
        raise Problem(422, 'Familia de prácticas inválida')
    if filters.get('scope', 'included') not in ('all', 'included', 'excluded', 'indeterminate'):
        raise Problem(422, 'Ámbito de consulta inválido')
    if filters.get('state') not in (None, *STATES) or filters.get('decision') not in (None, *DECISIONS):
        raise Problem(422, 'Estado o decisión inválidos')
    if filters.get('rule') not in (None, *RULES) or filters.get('view', 'all') not in ('all', 'pending', 'information', 'reviewed', 'exceptions', 'referred', 'row_reviewed', 'row_detail'):
        raise Problem(422, 'Regla o vista inválida')
    rules = filters.get('rules', [])
    if not isinstance(rules, list) or len(rules) > len(RULES) or any(rule not in RULES for rule in rules):
        raise Problem(422, 'Selección de controles inválida')
    if filters.get('rules_match', 'any') not in ('any', 'all'):
        raise Problem(422, 'Usar any o all para combinar controles')
    if filters.get('rule') and rules:
        raise Problem(422, 'Usar rule o rules, no ambos')
    if filters.get('sort', 'source_row') not in ('priority', 'source_row', 'affiliate_id', 'practice_date', 'code', 'total_ars') or filters.get('direction', 'asc') not in ('asc', 'desc'):
        raise Problem(422, 'Orden inválido')
    if not 0 <= filters.get('offset', 0) <= 100000 or not 1 <= filters.get('limit', 50) <= 100:
        raise Problem(422, 'Paginación inválida')
    for field in ('date_from', 'date_to'):
        value = filters.get(field)
        try:
            if value is not None and date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        except (ValueError, TypeError):
            raise Problem(422, 'Usar fecha AAAA-MM-DD') from None
    if filters.get('date_from') and filters.get('date_to') and filters['date_from'] > filters['date_to']:
        raise Problem(422, 'El inicio no puede superar el fin')
    for field, maximum in (('code', 80), ('text', 100), ('search', 100), ('reason', 200)):
        if filters.get(field) is not None and (not isinstance(filters[field], str) or len(filters[field]) > maximum):
            raise Problem(422, 'Filtro demasiado largo')


def _model(conn, dataset_id, batch_id, scope, *, saved_number=None, only_number=None, projection=None, stamp=None, actor=None):
    batch = dict(_batch(conn, dataset_id, batch_id))
    original = conn.execute('SELECT original_name, source_sha256 FROM batches WHERE id=?', (batch_id,)).fetchone()
    latest = conn.execute('SELECT id FROM control_runs WHERE revision_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(batch['revision_id'],)).fetchone()
    summary = _run_summary(conn, dataset_id, latest['id']) if latest else None
    cache_key=None
    if projection is not None:
        # Source integrity and dependencies are evaluated on each read. Only the
        # database-derived row layout can be reused. Decisions and money are computed below.
        cache_key=(actor,dataset_id,batch_id,scope,batch['revision_id'],batch['revision_version'],latest['id'] if latest else None,
            (summary['freshness'],summary['technical_state'],tuple(summary['global_affected_rules']),
             tuple((n,tuple(rules)) for n,rules in summary['affected_rows'].items())) if summary else None)
        found=projection.get(stamp,cache_key)
        if found:
            rows,counts,context=found
            return batch,rows,counts,context,summary,latest
    overlay = defaultdict(dict)
    restrict = ' AND source_row=?' if only_number is not None else ''
    row_args = (batch['import_id'],only_number) if only_number is not None else (batch['import_id'],)
    for edit in conn.execute('SELECT source_row,field,value_json FROM work_fields WHERE import_id=?'+restrict, row_args):
        overlay[edit['source_row']][edit['field']] = json.loads(edit['value_json'])
    rows, scope_counts = {}, Counter()
    eligibility={}
    for source in conn.execute('SELECT source_row,practice_date,permitted_json,total_ars,honorarios_ars,derechos_ars FROM invoice_rows WHERE import_id=?'+restrict+' ORDER BY source_row', row_args):
        fields = json.loads(source['permitted_json'])
        ek=source['practice_date'],fields.get('F')
        if ek not in eligibility:eligibility[ek]=classify(*ek,batch['period'])
        eligible=eligibility[ek]
        scope_counts[eligible['disposition']] += 1
        include_saved = source['source_row']==saved_number and eligible['disposition']=='included'
        if scope != 'all' and eligible['disposition'] != scope and not include_saved:
            continue
        fields.update(overlay.get(source['source_row'], {}))
        rows[source['source_row']] = {
            'source_row': source['source_row'], 'locator': f'{batch.get("sheet_name", "Hoja1")}!{source["source_row"]}',
            'practice_date': source['practice_date'], 'code': fields.get('E'), 'description': fields.get('K'),
            'order_number': fields.get('B'), 'affiliate_id': fields.get('C'), 'affiliate_name': fields.get('H'),
            'quantity': fields.get('G'), 'setting': fields.get('F'),
            'corrected_fields': sorted(overlay.get(source['source_row'], {})),
            'honorarios_ars': source['honorarios_ars'], 'derechos_ars': source['derechos_ars'],
            'total_ars': source['total_ars'], 'currency': 'ARS', 'disposition': eligible['disposition'],
            'eligibility_reasons': eligible['eligibility_reasons'], 'scope_type': eligible['scope_type'],
            'billing_window': eligible['billing_window'],
            'alerts': [],
        }
    # Identical control results are common. Decode each distinct pattern once per
    # query; individual invalidations must participate in the key.
    patterns = {}
    if latest:
        query = ('SELECT source_row,json_group_array(json_array(rule_code,result,reason_code)) AS pattern FROM '
                 '(SELECT source_row,rule_code,result,reason_code FROM control_results WHERE run_id=?'+restrict+
                 ' ORDER BY source_row,rule_code) GROUP BY source_row')
        args=(latest['id'],only_number) if only_number is not None else (latest['id'],)
        patterns = {r['source_row']:r['pattern'] for r in conn.execute(query,args)}
    layouts = {}
    global_changes = set(summary['global_affected_rules']) if summary else set()
    row_changes = summary['affected_rows'] if summary else {}
    for number,row in rows.items():
        pattern = patterns.get(number,'[]')
        changes = tuple(row_changes.get(str(number),()))
        key = (pattern,changes)
        if key not in layouts:
            affected = global_changes.union(changes)
            facets = [(rule,'requires_update' if rule in affected else
                       'sin_indicios' if result=='sin_observaciones' else result,reason)
                      for rule,result,reason in json.loads(pattern)]
            remaining = sorted(set(RULES).difference(rule for rule,_,_ in facets))
            facets.extend((rule,'no_evaluado','control_not_recorded' if latest else 'analysis_missing') for rule in remaining)
            layouts[key] = (facets,Counter(state for _,state,_ in facets))
        row['_facets'],counts = layouts[key]
        row['control_counts'] = counts if row['disposition']=='included' else Counter()
        row['state'] = ('outside_scope' if row['disposition'] == 'excluded' else
                        'scope_indeterminate' if row['disposition'] == 'indeterminate' else
                        next((state for state in STATES if row['control_counts'][state]), 'no_evaluado'))
    if latest:
        for alert in conn.execute('SELECT a.id,a.source_row,a.rule_code,a.version,c.result,c.reason_code FROM alerts a '
                'LEFT JOIN control_results c ON c.run_id=? AND c.import_id=a.import_id AND c.source_row=a.source_row '
                'AND c.rule_code=a.rule_code WHERE a.revision_id=? ORDER BY a.source_row,a.rule_code', (latest['id'], batch['revision_id'])):
            row = rows.get(alert['source_row'])
            if row is None:
                continue
            current = (row['disposition'] == 'included' and alert['result'] == 'con_indicios' and
                       not result_affected(summary, alert['source_row'], alert['rule_code']))
            decision, decision_id = _decision_status(conn, alert['id'], latest['id']) if current else ('pendiente', None)
            row['alerts'].append({'id': alert['id'], 'rule_code': alert['rule_code'], 'version': alert['version'],
                'reason_code': alert['reason_code'], 'decision': decision, 'decision_id': decision_id,
                'current': current, 'history_only': not current})
    for row in rows.values():
        if not row['alerts']:
            row['decision_counts']={}
            row['decision']='sin_indicios_vigentes'
            row['indication_count']=row['control_counts']['con_indicios']
            row['pending_count']=0
            continue
        active = [a for a in row['alerts'] if a['current']]
        decisions = Counter(a['decision'] for a in active)
        row['decision_counts'] = dict(decisions)
        row['decision'] = next(iter(decisions)) if len(decisions) == 1 else 'mixta' if decisions else 'sin_indicios_vigentes'
        row['indication_count'] = row['control_counts']['con_indicios']
        row['pending_count'] = decisions['pendiente']
        row['control_counts'] = dict(row['control_counts'])
    context = {'id': batch_id, 'original_name': original['original_name'], 'source_sha256': original['source_sha256'],
               'period': batch['period'], 'revision_version': batch['revision_version'], 'revision_state': batch['state'],
               'latest_run_id': latest['id'] if latest else None,
               'run_freshness': summary['freshness'] if summary else 'not_analyzed',
               'run_technical_state': summary['technical_state'] if summary else 'not_started'}
    from .proposal_freshness import provider_basis
    provider=provider_basis(conn,batch_id)
    context['provider']=provider['provider'] if provider else None
    from .authorization_controls import synthetic_batch
    context['synthetic_data']=synthetic_batch(conn,batch_id)
    if projection is not None:projection.put(stamp,cache_key,rows,scope_counts,context)
    return batch, rows, dict(scope_counts), context, summary, latest


def _image_candidate(row):
    """Review shortlist, not a change to the classified family or equivalence."""
    suggestion = row.get('family_suggestion') or {}
    return (row['family'] == 'unclassified' and suggestion.get('family') == 'images'
            and suggestion.get('status') == 'requires_manual_review')


def _matches(row, filters):
    if filters.get('scope') != 'all' and row['disposition'] != filters.get('scope', 'included'):
        return False
    family = filters.get('family', 'all')
    if family == 'images_and_candidates':
        if row['family'] != 'images' and not _image_candidate(row):
            return False
    elif family == 'image_candidates':
        if not _image_candidate(row):
            return False
    elif family != 'all' and row['family'] != family:
        return False
    for key, category in (('report_document_state','informe'), ('authorization_document_state','autorizacion')):
        requested = filters.get(key, 'all')
        if requested != 'all' and row['documents'][category]['state'] != requested:
            return False
    if filters.get('search') and not any(filters['search'].casefold() in str(row.get(field) if row.get(field) is not None else '').casefold()
            for field in ('source_row','order_number','affiliate_id','affiliate_name','code','description','practice_date')):
        return False
    if filters.get('code') is not None and str(row['code'] or '') != filters['code']:
        return False
    if filters.get('text') and filters['text'].casefold() not in str(row['description'] or '').casefold():
        return False
    if filters.get('date_from') and (not row['practice_date'] or row['practice_date'] < filters['date_from']):
        return False
    if filters.get('date_to') and (not row['practice_date'] or row['practice_date'] > filters['date_to']):
        return False
    # Rule, result and reason must belong to the SAME control, never cross-match dimensions.
    selected_rules = filters.get('rules') or ([filters['rule']] if filters.get('rule') else [])
    matching_rules = {rule for rule, state, reason in row['_facets']
                      if (not filters.get('state') or state == filters['state']) and
                         (not filters.get('reason') or reason == filters['reason'])}
    # ALL is within one invoice row, never across different practices of a patient.
    # With no selected rules preserve the existing result/reason filter semantics.
    if selected_rules:
        matches = [rule in matching_rules for rule in selected_rules]
        if not (all(matches) if filters.get('rules_match', 'any') == 'all' else any(matches)):
            return False
    elif not matching_rules:
        return False
    if filters.get('decision') and not row['decision_counts'].get(filters['decision']):
        return False
    view, counts = filters.get('view', 'all'), row['control_counts']
    if view == 'pending' and not (row['pending_count'] or counts.get('requires_update') or counts.get('no_evaluado')):
        return False
    if view == 'information' and not (counts.get('no_concluyente') or counts.get('no_evaluado') or counts.get('requires_update')):
        return False
    if view == 'reviewed' and not (row['decision_counts'] and not row['pending_count'] and not counts.get('requires_update')):
        return False
    return True


def _public(row):
    return {k: v for k, v in row.items() if not k.startswith('_')}


def _exception_reasons(row,csv,comparison,referred):
    reasons = []
    if row.get('late_billing_reason'):
        reasons.append(LATE_REASON)
    if row['pending_count']: reasons.append('Aviso pendiente de decisión')
    if row['control_counts'].get('requires_update'): reasons.append('Requiere actualización')
    if referred: reasons.append('Derivación en curso')
    if (csv.get('temporal') or {}).get('state') in ('no_concluyente','con_indicios'):
        reasons.append('Verificar incorporación al consolidado')
    if (csv.get('status') in CSV_QUEUE_REASON and (not csv.get('reviewed') or csv.get('coverage_note'))
            and (csv['status'] not in ('coverage_pending','no_aval') or row['family']=='images')):
        reasons.append('Revisar aval CSV')
    if (csv.get('budget') or {}).get('status') in ('over','por_verificar'):
        reasons.append('Revisar presupuesto CSV')
    if (comparison.get('related_comparison') or comparison)['status'] in ('numeric_above_candidate','numeric_below_candidate'):
        reasons.append('Diferencia exploratoria a revisar')
    return reasons


def _receipt(row,reasons):
    pending = []
    for reason in reasons:
        if reason=='Aviso pendiente de decisión':
            pending.extend(reason_label(a['reason_code']) for a in row['alerts'] if a['current'] and a['decision']=='pendiente')
        else:
            pending.append({LATE_REASON:row.get('late_billing_reason'),
                            'Verificar incorporación al consolidado':'Verificar incorporación al consolidado',
                            'Revisar aval CSV':'Revisar el aval CSV',
                            'Actualizar decisión':'Volver a revisar la decisión administrativa','Diferencia exploratoria a revisar':'Contrastar el importe con la referencia HPC',
                            'Revisar presupuesto CSV':'Contrastar el presupuesto de la orden',
                            'Verificar convenio HPC':'Verificar el valor aplicable del convenio HPC',
                            'Requiere actualización':'Actualizar controles',
                            'Derivación en curso':'Dar seguimiento a la derivación'}[reason])
    return {'source_row':row['source_row'],'practice':row['description'],'in_exceptions':bool(reasons),
            'pending':list(dict.fromkeys(pending)),
            'inconclusive':row['control_counts'].get('no_concluyente',0),
            'unevaluated':row['control_counts'].get('no_evaluado',0)}


def review_priority(row, csv, comparison):
    from .row_decisions import authorization_shortfall, money
    budget = csv.get('budget') or {}
    shortfall = authorization_shortfall(money(row['total_ars']), csv)
    amounts = []
    if row.get('late_billing_reason') and money(row['total_ars']) is not None:
        amounts.append(money(row['total_ars']))
    if shortfall:
        amounts.append(Decimal(shortfall['amount_ars']))
    if budget.get('status')=='over':
        amounts.append(Decimal(budget['excess_ars']))
    active = [a for a in row['alerts'] if a['current']]
    strong = bool(shortfall or amounts or any(a['rule_code'] in ('RN09','RN11','RN13','RN14') for a in active))
    if any(a['rule_code']=='RN13' for a in active):
        h,d,b = (money(row[k]) for k in ('honorarios_ars','derechos_ars','total_ars'))
        if None not in (h,d,b):
            amounts.append(abs(h+d-b))
    ref = comparison.get('related_comparison') or comparison
    delta = ref.get('difference_ars_if_comparable')
    if delta is not None:
        amounts.append(abs(Decimal(str(delta))))
    technical = any(s=='requires_update' for _,s,_ in row['_facets'])
    level = 0 if strong or technical else 1 if active or csv or delta is not None else 2
    return (level, not bool(amounts), -max(amounts) if amounts else 0, row['source_row'])


def practice_search(conn, token_hash, dataset_id, batch_id, filters, *, root=None, after_read=None, projection=None):
    _validate(filters)
    if conn.in_transaction or filters.get('_number') or filters.get('saved_source_row'):projection=None
    stamp=projection.stamp() if projection is not None else None
    with _snapshot(conn):
        user, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
        scope_name = filters.get('scope','included')
        batch, rows, counts, context, summary, latest = _model(conn,dataset_id,batch_id,scope_name,
                                                               saved_number=filters.get('saved_source_row'), only_number=filters.get('_number'),projection=projection,stamp=stamp,actor=user['id'])
        saved_row = rows.get(filters.get('saved_source_row'))
        if scope_name != 'all' and saved_row and saved_row['disposition'] != scope_name:
            rows.pop(saved_row['source_row'])
        from .row_documents import batch_summary, empty_summary
        documents = batch_summary(conn, batch['import_id'], batch['revision_id'])
        areas, names, classification = catalog_families(conn, root, dataset_id)
        if root and not classification['source_unavailable'] and context['provider']=='HPC':
            from .display_categories import add_categories
            add_categories(conn,root,dataset_id,{**batch,'batch_id':batch_id},areas)
        from .verified_display_nomenclature import suggestion
        families={}
        empty_docs=empty_summary()
        for row in rows.values():
            row['documents'] = {**empty_docs, **documents.get(row['source_row'], {})}
            k=row['code'],row['description']
            if k not in families:
                family,basis=classify_family(k[0],areas,k[1],names)
                families[k]=family,basis,suggestion(k[0],family) if classification['available'] else None
            row['family'],row['family_basis'],row['family_suggestion']=families[k]
            if (row['family']=='images' and context['provider']=='HPC' and row['disposition']=='included'
                    and row['billing_window']['status']=='late'):
                row['late_billing_reason'] = late_reason(row['billing_window'], row['practice_date'])
        family_counts = Counter(row['family'] for row in rows.values())
        selected = [row for row in rows.values() if
                    (filters.get('_number') is None or row['source_row']==filters['_number']) and _matches(row, filters)]
        saved_number = saved_row['source_row'] if saved_row and saved_row['disposition']=='included' else None
        receipt = None
        from .board_values import page_comparisons
        comparison_filter=filters.get('reference_comparison_state','all')
        comparisons=None
        queue = filters.get('view')
        reason_counts = Counter()
        administrative_views = ('exceptions','row_reviewed','row_detail')
        decision_context = None
        if conn.execute('PRAGMA user_version').fetchone()[0]>=35:
            from .row_decisions import DecisionContext
            decision_context=DecisionContext(conn,root,dataset_id,batch,context)
        queue_counts = {'pending':0,'reviewed':0}
        handoff_members = None
        if comparison_filter!='all' or queue in administrative_views:
            comparisons=page_comparisons(conn,root,dataset_id,batch_id,selected,
                batch.get('sheet_name','Hoja1'),closed=batch['state']=='cerrada')
            def comparison_matches(row):
                comparison=comparisons[row['source_row']]
                state=(comparison.get('related_comparison') or comparison)['status']
                return (state in ('numeric_above_candidate','numeric_below_candidate') if comparison_filter=='differences'
                    else state=='numeric_equal' if comparison_filter=='equal'
                    else state not in ('numeric_above_candidate','numeric_below_candidate','numeric_equal'))
            if comparison_filter!='all':
                selected=[row for row in selected if comparison_matches(row)]
        from .authorization_matching import _context
        source_context = _context(conn,root,dataset_id,batch_id,budgets=batch['state'] != 'cerrada') if root else None
        notices = []
        if source_context and batch['state'] != 'cerrada':
            scope, captures, issues = source_context
            if scope and issues:
                notices.append('Autorizaciones: revisá la selección y la integridad de las fuentes de esta factura.')
            elif not any(c['source_system']=='HPC-CSV' for c in captures):
                notices.append('Autorizaciones: falta seleccionar un CSV HPC para cotejar esta factura.')
            if not issues:
                omitted = sum(sum(note.get('code') == 'csv_record_quarantined'
                                  for note in json.loads(capture['observations_json']))
                              for capture in captures if capture['source_system'] == 'HPC-CSV')
                if omitted:
                    records = '1 registro quedó fuera' if omitted == 1 else f'{omitted} registros quedaron fuera'
                    notices.append(f'CSV parcial: {records} del cotejo. Revisá la importación en Autorizaciones.')
            from .proposal_freshness import provider_basis
            basis = provider_basis(conn,batch_id)
            if not basis or basis['provider']!='HPC':
                notices.append('Valores: falta confirmar el alcance HPC y su fuente para esta factura.')
            elif not conn.execute("SELECT 1 FROM source_registry WHERE id=? AND dataset_id=? AND kind='values' AND status='registered'",(basis['source_id'],dataset_id)).fetchone():
                notices.append('Valores: el catálogo seleccionado ya no está disponible para esta factura.')
        queue_coverage = None
        csv_filter = filters.get('csv_review_state','all')
        if csv_filter != 'all':
            from .authorization_matching import csv_queue_coverage
            queue_coverage = csv_queue_coverage(conn,root,dataset_id,batch_id,selected,source_context=source_context)
            def csv_matches(row):
                signal = queue_coverage.get((batch['import_id'],row['source_row']),{})
                status = signal.get('status')
                wanted = {'supported':('one_unit_supported','units_supported','component_supported'),'rejected':('declared_rejected',),
                          'review':tuple(CSV_QUEUE_REASON),'undetermined':(None,)}
                check_budget = (signal.get('budget') or {}).get('status') in ('over','por_verificar')
                if csv_filter=='budget': return check_budget
                if csv_filter=='review' and check_budget: return True
                if csv_filter=='review' and signal.get('reviewed'):
                    return False
                return status in wanted[csv_filter]
            selected = [row for row in selected if csv_matches(row)]
        if queue=='referred' or queue in administrative_views:
            from .observation_workflow import records, observations
            history = records(conn, batch['revision_id'])
            review_context = (latest, summary, history)
            referred = {number for number in {e['source_row'] for e in history if e['action'] in ('refer','provide_info','request_info')}
                        if any(o['state'] in ('referred','waiting_information')
                               for o in observations(conn,dataset_id,batch,number,context=review_context))}
            if queue == 'referred':
                selected = [row for row in selected if row['source_row'] in referred]
            else:
                from .authorization_matching import csv_queue_coverage
                if queue_coverage is None:
                    queue_coverage = csv_queue_coverage(conn,root,dataset_id,batch_id,selected,source_context=source_context)
                for row in selected:
                    number = row['source_row']
                    csv = queue_coverage.get((batch['import_id'],number),{})
                    reasons = _exception_reasons(row,csv,comparisons[number],number in referred)
                    if (row['family']=='images' and context['provider']=='HPC'
                            and csv.get('status') in ('one_unit_supported','units_supported','component_supported')
                            and (csv.get('budget') or {}).get('status') not in ('over','within')
                            and decision_context and not (decision_context.agreement(number) or {}).get('current')):
                        reasons.append('Verificar convenio HPC')
                    if ('Revisar presupuesto CSV' in reasons and (csv.get('budget') or {}).get('status')=='por_verificar'
                            and decision_context and (decision_context.agreement(number) or {}).get('current')):
                        reasons.remove('Revisar presupuesto CSV')
                    row['_priority_key'] = review_priority(row,csv,comparisons[number])
                    row['exception_reasons'] = reasons
                    if decision_context and (number in decision_context.latest or filters.get('_number')==number):
                        review=decision_context.describe(row,csv,comparisons[number],reasons,source_context)
                        row['administrative_decision']=review
                        if review and review['previous'] and not review['current']:
                            reasons.append('Actualizar decisión')
                pending=[]; reviewed=[]
                for row in selected:
                    decision=row.get('administrative_decision') or {}
                    if decision.get('current'):
                        reviewed.append(row)
                    elif row['exception_reasons']:
                        pending.append(row)
                queue_counts={'pending':len(pending),'reviewed':len(reviewed)}
                if filters.get('_handoff_members'):
                    handoff_members=[{**{k:r[k] for k in ('source_row','practice_date','order_number','code','description','total_ars')},
                                      'ordinal':r['administrative_decision']['previous']['ordinal'],
                                      'amount_ars':r['administrative_decision']['previous']['amount_ars']} for r in reviewed]
                reason_counts.update(reason for row in pending for reason in set(row['exception_reasons']))
                if queue=='row_reviewed':
                    selected=reviewed
                elif queue=='row_detail':
                    selected=pending+reviewed
                else:
                    reason = filters.get('exception_reason')
                    selected=[row for row in pending if not reason or reason in row['exception_reasons']]
        if saved_number is not None:
            # The receipt describes the invoice's Exceptions queue, even when the
            # user's current filter or page no longer contains this practice.
            if 'exception_reasons' in saved_row:
                remaining = saved_row['exception_reasons']
            else:
                from .authorization_matching import csv_queue_coverage
                from .observation_workflow import observations, records
                ref = (comparisons or {}).get(saved_number)
                if ref is None:
                    ref = page_comparisons(conn,root,dataset_id,batch_id,[saved_row],
                        batch.get('sheet_name','Hoja1'),closed=batch['state']=='cerrada')[saved_number]
                coverage = csv_queue_coverage(conn,root,dataset_id,batch_id,[saved_row],source_context=source_context)
                if queue in ('exceptions','referred'):
                    is_referred = saved_number in referred
                else:
                    ctx = (latest,summary,records(conn,batch['revision_id'],saved_number))
                    is_referred = any(ob['state'] in ('referred','waiting_information')
                                      for ob in observations(conn,dataset_id,batch,saved_number,context=ctx))
                remaining = _exception_reasons(saved_row,coverage.get((batch['import_id'],saved_number),{}),ref,is_referred)
            if (saved_row.get('administrative_decision') or {}).get('current'):
                remaining=[]
            receipt = _receipt(saved_row,remaining)
        field = filters.get('sort', 'source_row')
        def key(row):
            value = row[field]
            if field == 'affiliate_id':
                return (str(value), row['practice_date'] is None, row['practice_date'] or '', row['source_row'])
            return (Decimal(value) if field == 'total_ars' else str(value) if field in ('code','affiliate_id') else value, row['source_row'])
        if field=='priority':
            def priority(row):
                return row.get('_priority_key',(2,True,0,row['source_row']))
            selected.sort(key=priority)
        else:
            populated = [row for row in selected if row[field] is not None]
            populated.sort(key=key, reverse=filters.get('direction', 'asc') == 'desc')
            selected = populated + [row for row in selected if row[field] is None]
        offset, limit = filters.get('offset', 0), filters.get('limit', 50)
        # Counts/positions are computed across the entire filtered result, not just this page.
        patient_totals = Counter(row['affiliate_id'] for row in selected if row['affiliate_id'])
        patient_positions = Counter()
        for row in selected:
            affiliate = row['affiliate_id']
            if affiliate:
                patient_positions[affiliate] += 1
                row['patient_group_total'] = patient_totals[affiliate]
                row['patient_group_position'] = patient_positions[affiliate]
            else:
                row['patient_group_total'] = 1
                row['patient_group_position'] = 1
        next_row = None
        if 'after_source_row' in filters:
            anchor = rows.get(filters['after_source_row'])
            if anchor:
                def follows(row):
                    if field=='priority':
                        return priority(row)>priority(anchor)
                    if anchor[field] is None:
                        return row[field] is None and row['source_row'] > anchor['source_row']
                    if row[field] is None:
                        return True
                    return key(row) < key(anchor) if filters.get('direction')=='desc' else key(row) > key(anchor)
                for position,row in enumerate(selected):
                    if follows(row):
                        next_row = row['source_row']
                        offset = position // limit * limit
                        break
        page_rows = selected[offset:offset+limit]
        # Workflow details are presentation-only: hydrate the returned page, not
        # every invoice row. Reuse the same snapshot's summary so freshness is
        # computed once; do not cache it across requests or source changes.
        next_review = None
        if page_rows and conn.execute('PRAGMA user_version').fetchone()[0]>=27:
            from .observation_workflow import observations, records, review_page
            workflow_context = (latest, summary, records(conn, batch['revision_id']))
            for row in page_rows:
                number = row['source_row']
                items = observations(conn,dataset_id,batch,number,context=workflow_context)
                row['observations'] = [{k:v for k,v in item.items()
                    if k not in ('history','decision_history','evidence')} for item in items]
                if number == next_row:
                    original = conn.execute('SELECT * FROM invoice_rows WHERE import_id=? AND source_row=?',
                                            (batch['import_id'],number)).fetchone()
                    next_review = review_page(conn,dataset,batch,original,context['original_name'],latest,items)
        if root is not None:
            authorizations = page_correspondence(conn, root, dataset_id, batch_id, [r['source_row'] for r in page_rows], indexed_coverage=queue_coverage,source_context=source_context)
            for row in page_rows:
                row['authorization'] = authorizations[row['source_row']]
        proposal_rows = {}
        if root and page_rows:
            from .proposal_freshness import ProposalEvaluator
            proposals = conn.execute(
                'SELECT p.* FROM proposal_versions p WHERE revision_id=? AND source_row IN '
                '(SELECT CAST(value AS INTEGER) FROM json_each(?)) AND ordinal='
                '(SELECT max(q.ordinal) FROM proposal_versions q WHERE q.revision_id=p.revision_id AND q.source_row=p.source_row)',
                (batch['revision_id'],json.dumps([r['source_row'] for r in page_rows]))).fetchall()
            if proposals:
                evaluator = ProposalEvaluator(conn,root,dataset_id,batch_id,batch,summary)
                proposal_rows = {p['source_row']:evaluator.evaluate(p) for p in proposals}
        if comparisons is None:
            comparisons = page_comparisons(conn, root, dataset_id, batch_id, page_rows,
                                           batch.get('sheet_name', 'Hoja1'), closed=batch['state']=='cerrada')
        for row in page_rows:
            row['motives'] = [{'rule': rule, 'state': state, 'reason': reason, 'label': reason_label(reason)}
                             for rule, state, reason in row['_facets'] if state in ('con_indicios', 'requires_update')]
            row['checks'] = [{'rule': rule, 'state': state, 'reason': reason, 'label': reason_label(reason)}
                             for rule, state, reason in row['_facets']]
            row['family_evidence'] = classification_evidence(row['code'], areas, row['description'], names)
            row['debit_proposal'] = proposal_rows.get(row['source_row'])
            ref = comparisons[row['source_row']]
            row['reference_comparison'] = ref
            confirmed=decision_context.agreement(row['source_row']) if decision_context and batch['state']!='cerrada' else None
            if confirmed and confirmed['current']:
                basis=confirmed['basis'];candidate=basis['candidate'];tariff=candidate['tariff']
                row['applicable_tariff']={'total_ars':format(Decimal(candidate['rate_ars'])*Decimal(confirmed['confirmation']['covered_quantity']),'.2f'),
                    'unit':'por práctica','from':candidate['effective_from'],'through':confirmed['confirmation']['coverage_through'],
                    'source_id':basis['source']['id'],'locator':tariff.get('source_locator') or f"hpc_catalog_tariffs.seq={tariff['seq']}"}
            csv = (row.get('authorization',{}).get('panel_signal') or {}).get('csv_coverage') or {}
            if decision_context and 'administrative_decision' not in row:
                referred_in_row=any(o['state'] in ('referred','waiting_information') for o in row.get('observations',[]))
                reasons=_exception_reasons(row,csv,ref,referred_in_row)
                if reasons or row['source_row'] in decision_context.latest:
                    row['administrative_decision']=decision_context.describe(row,csv,ref,reasons,source_context)
            details = [a['rule_code']+' · '+reason_label(a['reason_code']) for a in row['alerts']
                       if a['current'] and a['decision']=='pendiente'
                       and not (a['reason_code']=='facturacion_fuera_de_termino' and row.get('late_billing_reason'))]
            if row.get('late_billing_reason'):
                details.insert(0, row['late_billing_reason'])
            details.extend(m['rule']+' · Cambió la evidencia: volver a analizar' for m in row['motives'] if m['state']=='requires_update')
            if 'Verificar convenio HPC' in row.get('exception_reasons',[]):
                details.append('Práctica autorizada. Falta acreditar el valor aplicable del convenio HPC.')
            csv_reason = CSV_QUEUE_REASON.get(csv.get('status'))
            if csv.get('status')=='component_pending':csv_reason=csv.get('reason') or csv_reason
            if (csv.get('temporal') or {}).get('state') in ('con_indicios','no_concluyente'):
                details.append(csv['temporal']['reason'])
            previous = csv.get('previous_rows') or []
            if csv.get('status')=='already_used' and len(previous)==1:
                def date_label(value):
                    return date.fromisoformat(value).strftime('%d/%m')
                prior = previous[0]
                csv_reason = ('El aval del '+date_label(prior['authorization_date'])+
                              ' ya respalda la prestación del '+date_label(prior['performed_on'])+'.')
            if csv.get('status') in ('one_unit_only','units_partial'):
                covered=csv.get('covered_units',1)
                csv_reason=f"{covered} de {csv['billed_units']} autorizada{'s' if covered!=1 else ''}."
            signal = (row.get('authorization') or {}).get('panel_signal') or {}
            if (csv.get('status') in (None,'needs_review') and signal.get('presence')=='found'
                    and signal.get('item_authorization')=='not_determinable' and not signal.get('csv_item_declaration')):
                csv_reason = 'Práctica localizada. Autorización individual sin confirmar.'
            budget = csv.get('budget') or {}
            if budget.get('status')=='over':
                amount = f"{Decimal(budget['excess_ars']):,.2f}".translate(str.maketrans(',.','.,')).removesuffix(',00')
                details.append('Supera el presupuesto de la orden en $'+amount+' ARS.')
            elif budget.get('status')=='por_verificar' and not row.get('applicable_tariff'):
                details.append('Presupuesto por verificar: '+budget['reason'])
            if csv_reason:
                details.append(('Aval ya revisado. ' if csv.get('reviewed') else '') + csv_reason)
            if csv.get('coverage_note'):
                details.append('Pendiente de cotejo. '+csv['coverage_note'])
            comparison = ref.get('related_comparison') or ref
            state = comparison['status']
            if state in ('numeric_above_candidate','numeric_below_candidate'):
                direction = 'supera' if state=='numeric_above_candidate' else 'es inferior a'
                dimensions = []
                if not ref.get('declared_unit'): dimensions.append('unidad')
                if not ref.get('declared_currency'): dimensions.append('moneda')
                condition = 'Falta verificar '+' y '.join(dimensions)+'.' if dimensions else 'Verificar su aplicabilidad.'
                details.append('El total facturado '+direction+' la referencia candidata HPC. '+condition)
            for obs in row.get('observations',[]):
                if obs['state'] in ('referred','waiting_information'):
                    status = 'Consulta derivada al auditor' if obs['state']=='referred' else 'El auditor pidió información'
                    details.append(obs['rule_code']+' · '+status)
            row['exception_details'] = list(dict.fromkeys(details))
        layouts={}
        for row in rows.values():
            if scope_name=='all' or row['disposition']==scope_name:
                entry=layouts.setdefault(id(row['_facets']),[row['_facets'],0])
                entry[1]+=1
        facets=Counter()
        for members,n in layouts.values():
            for facet in members:facets[facet]+=n
        pending_requests=0
        if conn.execute('PRAGMA user_version').fetchone()[0]>=33:
            pending_requests=conn.execute('SELECT count(*) FROM practice_requests r WHERE dataset_id=? '
                'AND NOT EXISTS(SELECT 1 FROM practice_request_outcomes o WHERE o.request_id=r.id)',(dataset_id,)).fetchone()[0]
        response = {'pending_requests':pending_requests,'items': [_public(row) for row in page_rows], 'filtered_total': len(selected),
                    'row_decision_counts':queue_counts,'exception_counts': dict(sorted(reason_counts.items())), 'source_notices': notices, 'physical_total': sum(counts.values()), 'scope_counts': {s: counts.get(s, 0) for s in ('included','excluded','indeterminate')},
                    'scope_total': sum(counts.values()) if scope_name == 'all' else counts.get(scope_name, 0), 'offset': offset, 'limit': limit,
                    'dataset_version': dataset['version'], 'batch': context, 'filters': filters, 'next_source_row': next_row, 'next_review': next_review, 'saved_row_status': receipt,
                    'image_candidate_count': sum(_image_candidate(row) for row in rows.values()),
                    'classification': classification, 'family_counts': {f: family_counts[f] for f in ('images','other','unclassified')},
                    'facets': [{'rule': rule, 'state': state, 'reason': reason, 'label': reason_label(reason), 'count': count}
                               for (rule, state, reason), count in sorted(facets.items())],
                    'analysis_started': False, 'decision_written': False}
        if conn.execute('PRAGMA user_version').fetchone()[0]>=36:
            from .invoice_handoff import board_status
            response['handoff']=board_status(conn,user,dataset_id,batch_id,batch,response)
        if next_row is not None:
            next_item=next((r for r in page_rows if r['source_row']==next_row and r.get('administrative_decision')),None)
            if next_item:
                from .row_decisions import page_detail
                response['next_decision']=page_detail(conn,user,dataset_id,batch['revision_id'],dataset['version'],batch['revision_version'],next_item)
        if handoff_members is not None:
            response['_handoff_members']=handoff_members
            from .invoice_audit import scope_snapshot
            response['_audit_scope']=scope_snapshot(conn,batch['import_id'],rows.values())
    if after_read:
        after_read()
    _, current = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    check_version(current, dataset['version'])
    current_batch = _batch(conn, dataset_id, batch_id)
    if current_batch['revision_version'] != batch['revision_version']:
        raise Problem(409, 'La revisión cambió durante la consulta; actualizar')
    return response


def decision_preview(conn, token_hash, dataset_id, batch_id, expected_dataset_version,
                     expected_revision_version, items, *, after_read=None):
    if not 1 <= len(items) <= 100 or len({i['id'] for i in items}) != len(items):
        raise Problem(422, 'Elegí entre 1 y 100 avisos distintos')
    with _snapshot(conn):
        _, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
        check_version(dataset, expected_dataset_version)
        batch = dict(_batch(conn, dataset_id, batch_id))
        if batch['revision_version'] != expected_revision_version or batch['state'] == 'cerrada':
            raise Problem(409, 'La revisión cambió o está cerrada')
        latest = _latest_run(conn, batch['revision_id'])
        if not latest:
            raise Problem(409, 'Primero ejecutá el análisis')
        summary = _run_summary(conn, dataset_id, latest['id'])
        records, cases = [], []
        for selected in items:
            alert = conn.execute('SELECT * FROM alerts WHERE id=? AND revision_id=?',
                                 (selected['id'], batch['revision_id'])).fetchone()
            if not alert:
                raise Problem(404, 'Aviso seleccionado inexistente')
            row = conn.execute('SELECT * FROM invoice_rows WHERE import_id=? AND source_row=?',
                               (batch['import_id'], alert['source_row'])).fetchone()
            result = _result(conn, latest['id'], alert['source_row'], alert['rule_code'])
            if (alert['version'] != selected['expected_version'] or
                classify(row['practice_date'], json.loads(row['permitted_json']).get('F'), batch['period'])['disposition'] != 'included' or
                result is None or result['result'] != 'con_indicios' or result_affected(summary,alert['source_row'],alert['rule_code'])):
                raise Problem(409, 'Un aviso cambió o requiere actualizar el análisis')
            records.append(selection_record(alert,result))
            cases.append({'id': alert['id'], 'expected_version': alert['version'], 'source_row': alert['source_row'],
                'locator': f'Hoja1!{alert["source_row"]}', 'rule_code': alert['rule_code'],
                'reason_label': reason_label(result['reason_code']), 'evidence': json.loads(result['evidence_json']),
                'decision': _decision_status(conn,alert['id'],latest['id'])[0]})
        basis = selection_basis(dataset_id,batch_id,expected_dataset_version,expected_revision_version,latest['id'],records)
        response = {'items': cases, 'count': len(cases), 'preview_sha256': basis,
                    'dataset_version': expected_dataset_version, 'revision_version': expected_revision_version,
                    'analysis_started': False, 'decision_written': False, 'proposal_amount_ars': None}
    if after_read:
        after_read()
    _, current = authorized_dataset(conn,token_hash,dataset_id,'reviewer')
    check_version(current,expected_dataset_version)
    if _batch(conn,dataset_id,batch_id)['revision_version'] != expected_revision_version:
        raise Problem(409, 'La revisión cambió durante la consulta')
    return response


def practice_detail(conn, token_hash, dataset_id, batch_id, source_row, *, after_read=None):
    # Detail is independently protected, including rows without any alert.
    with _snapshot(conn):
        _, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
        batch = dict(_batch(conn, dataset_id, batch_id))
        row = conn.execute('SELECT * FROM invoice_rows WHERE import_id=? AND source_row=?', (batch['import_id'],source_row)).fetchone()
        if row is None:
            raise Problem(404, 'Práctica inexistente')
        original = json.loads(row['permitted_json'])
        eligible = classify(row['practice_date'], original.get('F'), batch['period'])
        effective = dict(original)
        for edit in conn.execute('SELECT field,value_json FROM work_fields WHERE import_id=? AND source_row=?', (batch['import_id'],source_row)):
            effective[edit['field']] = json.loads(edit['value_json'])
        latest = _latest_run(conn,batch['revision_id'])
        summary = _run_summary(conn,dataset_id,latest['id']) if latest else None
        controls = []
        if latest:
            for control in conn.execute('SELECT * FROM control_results WHERE run_id=? AND source_row=? ORDER BY rule_code', (latest['id'],source_row)):
                record = dict(control)
                record['evidence'] = json.loads(record.pop('evidence_json'))
                record['freshness'] = 'outside_scope' if eligible['disposition'] != 'included' else 'requires_update' if result_affected(summary,source_row,record['rule_code']) else 'current'
                record['reason_label'] = reason_label(record['reason_code'])
                controls.append(record)
        present = {c['rule_code'] for c in controls}
        for rule in RULES:
            if rule not in present:
                controls.append({'rule_code':rule,'result':'no_evaluado','freshness':'outside_scope' if eligible['disposition']!='included' else 'current',
                                 'reason_code':'control_not_recorded' if latest else 'analysis_missing',
                                 'reason_label':reason_label('control_not_recorded' if latest else 'analysis_missing'),'evidence':None})
        history = [dict(r) for r in conn.execute('SELECT d.*,a.rule_code,u.username AS actor_username,a.revision_id AS origin_revision_id, '
            'r.ordinal AS origin_revision_ordinal,r.state AS origin_revision_state,c.id AS origin_closure_id FROM review_decisions d '
            'JOIN alerts a ON a.id=d.alert_id JOIN users u ON u.id=d.actor_id '
            'LEFT JOIN revisions r ON r.id=a.revision_id LEFT JOIN revision_closures c ON c.revision_id=r.id '
            'WHERE a.import_id=? AND a.source_row=? '
            'ORDER BY d.created_at,d.rowid',(batch['import_id'],source_row))]
        interpretations = [dict(r) for r in conn.execute('SELECT w.field,w.previous_json,w.new_json,w.reason,u.username AS actor_username,w.created_at, '
            'w.revision_id AS origin_revision_id,r.ordinal AS origin_revision_ordinal,r.state AS origin_revision_state,c.id AS origin_closure_id '
            'FROM work_changes w JOIN users u ON u.id=w.actor_id '
            'LEFT JOIN revisions r ON r.id=w.revision_id LEFT JOIN revision_closures c ON c.revision_id=r.id '
            'WHERE w.import_id=? AND w.source_row=? ORDER BY w.created_at,w.rowid',(batch['import_id'],source_row))]
        for entry in history+interpretations:
            entry['origin_is_current_revision']=entry['origin_revision_id']==batch['revision_id']
            entry['record_kind']='historical_record_not_an_assessment_of_current_validity'
        invoice = conn.execute('SELECT original_name,source_sha256 FROM batches WHERE id=?',(batch_id,)).fetchone()
        values = [dict(r) for r in conn.execute("SELECT id,cut_label,source_sha256 FROM source_registry WHERE dataset_id=? AND kind='values' AND status='registered'",(dataset_id,))]
        response = {'source_row':source_row,'locator':f'Hoja1!{source_row}', 'original_fields':original,'effective_fields':effective,
                    'amounts_original_ars':{k:row[k] for k in ('honorarios_ars','derechos_ars','total_ars')},
                    'disposition':eligible['disposition'],'eligibility_reasons':eligible['eligibility_reasons'],
                    'practice_date':row['practice_date'],'invoice':dict(invoice),'controls':sorted(controls,key=lambda c:c['rule_code']),
                    'decision_history':history,'interpretation_history':interpretations,'value_sources':values,
                    'dataset_version':dataset['version'],'revision_version':batch['revision_version'],
                    'latest_run_id':latest['id'] if latest else None,'analysis_started':False}
    if after_read:
        after_read()
    _, current = authorized_dataset(conn,token_hash,dataset_id,'reviewer')
    check_version(current,dataset['version'])
    if _batch(conn,dataset_id,batch_id)['revision_version'] != batch['revision_version']:
        raise Problem(409,'La revisión cambió durante la consulta; actualizar')
    return response

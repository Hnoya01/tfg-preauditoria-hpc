"""Allocate available units once, with a verifiable receipt for each source item."""
from collections import defaultdict
from decimal import Decimal
from .csv_allocation import compatible, factor_for, projection_count
from .csv_coverage import billed_quantity, covered_status, csv_sequence, VALID_DAYS


def source_basis(item, row):
    data = dict(locator=item['locator'],source_sha256=item['sha256'],order_id=item['order_id'],
                authorization_date=item['day'].isoformat(),performed_on=row['day'].isoformat(),
                elapsed_days=(row['day']-item['day']).days,valid_days=VALID_DAYS)
    if item.get('movement_actor'):
        data['movement_actor']=item['movement_actor']
    if item.get('prior_order_id'):
        data['prior_order_id']=item['prior_order_id']
    budget=item.get('budget') or {}
    if budget.get('amount_ars') and not budget.get('reason'):
        data['candidate_budget_ars']=budget['amount_ars']
    return data


def conditions(item):
    budget=item.get('budget') or {}
    qualifiers=tuple(sorted(q['code'] for q in item.get('qualifiers',[])))
    return (item['full_code'],qualifiers,budget.get('amount_ars'),budget.get('budget_units'),budget.get('reason'))


def plan(row, pool, remaining):
    qty=billed_quantity(row)
    if not qty or not pool:
        return []
    pool=sorted(pool,key=lambda i:(i['day'],i['order_id'],i['locator']))
    from .csv_export import description_key
    exact=[i for i in pool if description_key(row['description'])==description_key(i['description'])]
    if exact and len({i['full_code'] for i in exact})==1 and qty==1:
        pool=exact
    if len(pool)>1 and any((i.get('budget') or {}).get('reason') for i in pool):
        return []
    if len({conditions(i) for i in pool})==1:
        need=Decimal(qty)/factor_for(row,pool[0])
        parts=[]
        for item in pool:
            units=min(need,remaining(item))
            parts.append((item,units))
            need-=units
            if not need:
                break
        return parts
    # Para vincular una fila agrupada deben coincidir todos los estudios y sus unidades.
    # Un presupuesto individual no se reparte entre prácticas.
    if (len({i['reference'][:2] for i in pool})==1 and len({i['full_code'] for i in pool})==len(pool)
            and all(not i.get('budget') and factor_for(row,i)==1 for i in pool)
            and sum(remaining(i) for i in pool)==qty and qty>1):
        return [(i,remaining(i)) for i in pool]
    return []


def allocate(rows, items):
    by_day=defaultdict(list)
    for row in rows:
        by_day[row['day']].append(row)
    spent=defaultdict(Decimal)
    receipts=defaultdict(list)
    reserved={}
    for row in rows:
        pin=row.get('verified_link')
        if pin:
            reserved[(pin['source_sha256'],pin['locator'])]=row['key']
    results={}
    unresolved_uses=set()
    for day, peers in sorted(by_day.items()):
        for row in peers:
            key=row['key']
            matches=[i for i in items if compatible(row,i)]
            valid=[i for i in matches if i['unique'] and i['provider']=='HPC' and i['day']]
            if row['uncertain'] or not row['hpc'] or not matches:
                results[key]={'status':'needs_review','reason':'Verificar correspondencia de la prestación.'}
                continue
            candidates=[i for i in valid if (day-i['day']).days<=VALID_DAYS]
            def remaining(i):
                uses=receipts[i['reference']]
                if uses and uses[0]['performed_on']!=day.isoformat():
                    return Decimal(0)
                return Decimal(i.get('authorized_units') or 0)-spent[i['reference']]
            def owner(i):
                return reserved.get((i['sha256'],i['locator']))
            positives=[i for i in candidates if i['authorized'] and (i['day']<=day or owner(i)==key)]
            pool=[i for i in positives if owner(i) in (None,key) and remaining(i)>0]
            pinned=[i for i in pool if owner(i)==key]
            if row.get('verified_link') and not pinned:
                results[key]={'status':'needs_review','reason':'Volver a verificar el vínculo de la orden.'}
                continue
            chosen=plan(row,pinned or pool,remaining)
            if any(other['uncertain'] and other['day']<=day and compatible(other,i)
                   and i['day']<=other['day'] for i in pool for other in rows if other['key']!=key):
                results[key]={'status':'needs_review','reason':'Otra prestación con alcance sin confirmar podría necesitar la misma orden.'}
                continue
            if pool and (not chosen or any(i['reference'] in unresolved_uses for i,_ in chosen if owner(i)!=key)):
                unresolved_uses.update(i['reference'] for i in pool)
                results[key]={'status':'needs_review','reason':'Verificar qué prácticas y cantidades cubren las órdenes.'}
                continue
            if chosen:
                conflict=False
                for i,units in chosen:
                    rivals=[r for r in peers if r['key']!=key and compatible(r,i) and owner(i) is None]
                    if not rivals:
                        continue
                    total=sum((Decimal(billed_quantity(r) or 0)/factor_for(r,i) for r in [row,*rivals]),Decimal(0))
                    if (not row['billed_order'] or any(r['billed_order']!=row['billed_order'] or not billed_quantity(r) or r['uncertain'] for r in rivals)
                            or total>Decimal(i['authorized_units'])):
                        conflict=True
                covered=sum(units*factor_for(row,i) for i,units in chosen)
                if conflict or covered!=covered.to_integral_value():
                    unresolved_uses.update(i['reference'] for i,_ in chosen)
                    results[key]={'status':'needs_review','reason':'Hay filas que compiten por unidades o unidades no comparables.'}
                    continue
                first=chosen[0][0]
                allocations=[]
                for i,units in chosen:
                    spent[i['reference']]+=units
                    receipts[i['reference']].append(dict(batch_id=row['batch_id'],source_row=key[1],performed_on=day.isoformat(),authorization_date=i['day'].isoformat(),units=int(units*factor_for(row,i)),authorized_studies=str(units)))
                    allocations.append(dict(**source_basis(i,row),assigned_studies=str(units),capacity=i['authorized_units']))
                factor=factor_for(row,first)
                capacity=sum(Decimal(i['authorized_units'])*factor_for(row,i) for i,_ in chosen)
                signal=dict(**source_basis(first,row),status=covered_status(int(covered),billed_quantity(row),int(capacity)),
                    billed_units=billed_quantity(row),covered_units=int(covered),order_units=sum(i['authorized_units'] for i,_ in chosen),
                    normalized_studies=str(Decimal(billed_quantity(row))/factor),assigned_studies=str(sum(u for _,u in chosen)),allocations=allocations)
                if factor!=1:
                    signal['unit_conversion']={'factor':str(factor),'billed_unit':row['directed_rules'][first['full_code']]['billing_unit'],'authorized_unit':'practice','authorized_studies':signal['assigned_studies']}
                if len(chosen)==1 and first.get('qualifiers'):
                    signal.update(qualifier_rule_ids=[q['rule_id'] for q in first['qualifiers']],projection_count=projection_count(first))
                if row.get('incorporation') or pinned:
                    checks=[csv_sequence(i,row) for i,_ in chosen]
                    signal['temporal']=next((t for t in checks if t['state']!='sin_observaciones'),checks[0])
                if pinned:
                    signal['verified_link']=row['verified_link']['id']
                results[key]=signal
                continue
            future=[i for i in candidates if i['authorized'] and i['day']>day and owner(i) is None]
            if future:
                first=min(future,key=lambda i:(i['day'],i['order_id'],i['locator']))
                results[key]=dict(**source_basis(first,row),status='posterior_candidate',temporal=csv_sequence(first,row),
                    alternatives=[source_basis(i,row) for i in future],reason='Posible débito · verificar orden')
                continue
            if positives:
                previous=[v for i in positives for v in receipts[i['reference']]]
                if previous:
                    results[key]={'status':'already_used','previous_rows':previous}
                else:
                    results[key]={'status':'needs_review','reason':'La orden está asignada a otra prestación o su cantidad requiere cotejo.'}
                continue
            if candidates and len(valid)==len(matches) and all(i['rejected'] or i.get('outcome') in ('referral','check_referral') for i in candidates):
                prior = [i for i in candidates if i['day'] <= day]
                if not prior:
                    later = min(candidates, key=lambda i: (i['day'], i['order_id'], i['locator']))
                    movement = 'rechazo' if later['rejected'] else 'derivación'
                    results[key] = dict(**source_basis(later,row), status='later_movement', movement=movement)
                    continue
                candidates = prior
                last=max(candidates,key=lambda i:i['decided_at'] or '')
                kind=last.get('outcome')
                if any(i.get('outcome')=='check_referral' for i in candidates):
                    last=next(i for i in candidates if i.get('outcome')=='check_referral')
                    status='referral_pending'
                else:
                    status={'referral':'referred_elsewhere','prior_claim':'prior_not_found'}.get(kind,'declared_rejected')
                results[key]=dict(**source_basis(last,row),status=status)
                continue
            results[key]={'status':'outside_window'} if valid and len(matches)==len(valid) and not candidates else {'status':'needs_review','reason':'Verificar la resolución individual o su alcance.'}
    from .csv_actions import row_basis
    lookup={(i['sha256'],i['locator']):i for i in items}
    for row in rows:
        sig=results[row['key']]
        if sig['status']=='posterior_candidate':
            sig['row_basis']=row_basis(row)
            for choice in sig['alternatives']:
                source=lookup[choice['source_sha256'],choice['locator']]
                choice['cross_batch']=any(use['batch_id']!=row['batch_id'] for use in receipts[source['reference']])
    return results


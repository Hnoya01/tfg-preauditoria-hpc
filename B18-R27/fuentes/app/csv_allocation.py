"""Directed code matching with a shared ledger in authorized study units."""
from collections import defaultdict
from decimal import Decimal
from .csv_coverage import billed_quantity,csv_sequence,VALID_DAYS,covered_status
from .authorization_matching import _description


def rule_for(row,item):
    return row.get('directed_rules',{}).get(item.get('full_code'))


def compatible(row,item):
    if rule_for(row,item):return True
    return row.get('original_code')==item.get('full_code') and _description(row['description'])==_description(item['description'])


def factor_for(row,item):
    rule=rule_for(row,item)
    return Decimal(rule['factor']) if rule else Decimal(1)


def projection_count(item):
    qualifiers=item.get('qualifiers',[])
    projections=[q for q in qualifiers if q['kind']=='projections']
    if not projections:return None
    codes=[q['code'] for q in projections]
    values=[int(q['value']) for q in projections]
    # A combined "front and profile" plus separate projections could duplicate views.
    if len(set(codes))!=len(codes) or (len(values)>1 and any(v>1 for v in values)):return None
    return sum(values)


def assess(rows,items):
    usage=defaultdict(list);spent=defaultdict(Decimal);uncertain=set();result={}
    by_day=defaultdict(list)
    for row in rows:by_day[row['day']].append(row)
    for day,group in sorted(by_day.items()):
        opening=dict(spent)
        compatible_items={r['key']:[i for i in items if compatible(r,i)] for r in group}
        eligible={r['key']:[i for i in compatible_items[r['key']] if i['day'] is None or (day-i['day']).days<=VALID_DAYS] for r in group}
        for row in group:
            key=row['key'];matches=compatible_items[key];within=eligible[key]
            if not matches:
                result[key]={'status':'needs_review','reason':'Las órdenes localizadas corresponden a otra variante o técnica.'};continue
            if not within:
                result[key]={'status':'outside_window','valid_days':VALID_DAYS};continue
            available=[i for i in within if not usage[i['reference']] or
                (usage[i['reference']][0]['performed_on']==day.isoformat() and spent[i['reference']]<(i.get('authorized_units') or 0))]
            earlier=[i for i in available if i['day'] is None or i['day']<=day]
            if earlier:
                available=earlier+[i for i in available if i not in earlier and csv_sequence(i,row)['state']=='sin_observaciones']
            if not available:
                result[key]={'status':'needs_review'} if row['uncertain'] else {
                    'status':'already_used','previous_rows':[p for i in within for p in usage[i['reference']]]}
                continue
            if len(available)!=1:
                uncertain.update(i['reference'] for i in available)
                result[key]={'status':'needs_review','reason':'Hay varias autorizaciones compatibles para la prestación.'};continue
            item=available[0];reference=item['reference'];capacity=item.get('authorized_units')
            factor=factor_for(row,item)
            peers=[r for r in group if item in eligible[r['key']]]
            if len(peers)>1:
                same_occasion=(len({r.get('billed_order') for r in peers})==1 and all(r.get('billed_order') for r in peers))
                demands=[billed_quantity(r) for r in peers]
                demand=sum(Decimal(q)/factor_for(r,item) for r,q in zip(peers,demands)) if None not in demands else None
                peers_certain=(same_occasion and capacity and demand is not None and demand<=Decimal(capacity)-opening.get(reference,0)
                    and all(not r['uncertain'] and r['hpc'] and len(eligible[r['key']])==1 for r in peers))
            else:peers_certain=True
            if (not peers_certain or row['uncertain'] or not item['unique'] or item['provider']!='HPC' or not item['day']
                    or not row['hpc'] or reference in uncertain):
                uncertain.add(reference);result[key]={'status':'needs_review'};continue
            basis={'authorization_date':item['day'].isoformat(),'performed_on':day.isoformat(),
                   'elapsed_days':(day-item['day']).days,'valid_days':VALID_DAYS,'locator':item['locator'],
                   'source_sha256':item['sha256'],'order_id':item.get('order_id'),
                   'code_correspondence_ids':[rule_for(row,item)['id']] if rule_for(row,item) else []}
            if item.get('movement_actor'):basis['movement_actor']=item['movement_actor']
            if item['day']>day or row.get('incorporation'):
                temporal=csv_sequence(item,row);basis['temporal']=temporal
                if temporal['state']!='sin_observaciones':
                    if temporal['state']=='no_concluyente':uncertain.add(reference)
                    result[key]={**basis,'status':'temporal_late' if temporal['state']=='con_indicios' else 'temporal_pending'};continue
            if item['rejected']:
                result[key]={**basis,'status':'declared_rejected'};continue
            if not item['authorized']:
                result[key]={'status':'needs_review','reason':'La resolución individual requiere aclaración.'};continue
            billed=billed_quantity(row)
            if not billed or not capacity or capacity<1:
                uncertain.add(reference);result[key]={'status':'needs_review'};continue
            covered=min(Decimal(billed),(Decimal(capacity)-spent[reference])*factor)
            if covered<=0 or covered!=covered.to_integral_value():
                uncertain.add(reference);result[key]={'status':'needs_review','reason':'No se pueden repartir fracciones de la unidad facturada.'};continue
            studies=covered/factor
            spent[reference]+=studies
            receipt={'batch_id':row['batch_id'],'source_row':key[1],'performed_on':day.isoformat(),'authorization_date':item['day'].isoformat(),
                     'units':int(covered),'authorized_studies':str(studies)}
            usage[reference].append(receipt)
            status=covered_status(int(covered),billed,int(Decimal(capacity)*factor))
            signal={**basis,'status':status,'billed_units':billed,'covered_units':int(covered),'order_units':capacity,
                    'normalized_studies':str(Decimal(billed)/factor),'assigned_studies':str(studies)}
            if factor!=1:
                signal['unit_conversion']={'factor':str(factor),'billed_unit':rule_for(row,item)['billing_unit'],
                                           'authorized_unit':'practice','authorized_studies':str(studies)}
            if item.get('qualifiers'):
                signal['qualifier_rule_ids']=sorted(q['rule_id'] for q in item['qualifiers'])
                signal['projection_count']=projection_count(item)
            result[key]=signal
    return result

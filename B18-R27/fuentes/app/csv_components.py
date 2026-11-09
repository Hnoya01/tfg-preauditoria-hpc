"""Authorization evidence for invoice components in the same patient/order/occasion."""
from collections import defaultdict
from decimal import Decimal
from .csv_coverage import billed_quantity,csv_sequence


def attach(component_rows,main_rows,signals,items,rules):
    by_order=defaultdict(list)
    for row in main_rows.values():
        by_order[(row['key'][0],row['affiliate_key'],row['day'],row['billed_order'],row['original_code'])].append(row)
    total_components=defaultdict(list)
    for row in component_rows:
        rule=rules[row['original_code']]
        group=(row['key'][0],row['affiliate_key'],row['day'],row['billed_order'],rule['id'])
        total_components[group].append(row)
    for row in component_rows:
        rule=rules[row['original_code']]
        base={'status':'component_pending','component_rule_id':rule['id'],'parent_code':rule['parent_code'],
              'component_unit':rule['billing_unit'],'reason':'Falta identificar un único estudio principal de la misma orden.'}
        signals[row['key']]=base
        if not row['affiliate_key'] and row['hpc']:
            signals[row['key']]={'status':'unidentified','reason':'Afiliado no identificable · débito total propuesto'}
            continue
        if not row['billed_order'] or row['uncertain'] or not row['hpc']:continue
        group=(row['key'][0],row['affiliate_key'],row['day'],row['billed_order'],rule['parent_code'])
        parents=by_order.get(group,[])
        if len(parents)!=1:continue
        parent=parents[0];parent_signal=signals.get(parent['key'],{})
        base['parent_row']=parent['key'][1]
        base['parent_status']=parent_signal.get('status','unresolved')
        if parent_signal.get('status') not in ('one_unit_supported','units_supported'):
            base['reason']='El aval del estudio principal requiere revisión.'
            continue
        selected=items.get((parent_signal.get('source_sha256'),parent_signal.get('locator')))
        if not selected:
            base['reason']='Falta localizar la evidencia del estudio principal.';continue
        base.update(source_sha256=parent_signal['source_sha256'],locator=parent_signal['locator'],
                    order_id=parent_signal.get('order_id'),authorization_date=parent_signal.get('authorization_date'),
                    movement_actor=parent_signal.get('movement_actor'),authorization_path='parent_component',
                    code_correspondence_ids=[rule['id']]+parent_signal.get('code_correspondence_ids',[]))
        if selected['day']>row['day'] or row.get('incorporation'):
            temporal=csv_sequence(selected,row)
            if temporal['state']!='sin_observaciones':
                base.update(reason=temporal['reason'],temporal=temporal);continue
        related=total_components[row['key'][0],row['affiliate_key'],row['day'],row['billed_order'],rule['id']]
        quantities=[billed_quantity(r) for r in related]
        if None in quantities:
            base['reason']='La cantidad del adicional requiere aclaración.';continue
        demand=sum(quantities)
        if rule['billing_unit']=='exposure':
            views=parent_signal.get('projection_count')
            parent_quantity=billed_quantity(parent)
            if views is None or parent_quantity is None:
                base['reason']='Verificar segunda proyección';continue
            limit=max(0,views-1)*parent_quantity
            base.update(documented_projections=views,component_capacity=limit,qualifier_rule_ids=parent_signal.get('qualifier_rule_ids',[]))
        elif rule['billing_unit']=='side' and rule.get('related_code'):
            from .authorization_assessment import applicable_resolution
            order=selected['order']
            target=[i for i in order['items'] if i['full_code']==rule['related_code']]
            if len(target)!=1:
                base['reason']='Falta un aval individual para la proyección adicional.';continue
            resolution=applicable_resolution(order,target[0])
            if resolution['state']!='declared_authorized':
                base['reason']='La proyección adicional requiere comprobar su autorización individual.';continue
            conversion=parent_signal.get('unit_conversion',{})
            if conversion.get('billed_unit')!='side':
                base['reason']='Falta acreditar los lados del estudio principal.';continue
            qty=resolution['quantity']
            if qty is None or Decimal(qty)!=Decimal(1):
                base['reason']='La cantidad de proyecciones por lado requiere aclaración.';continue
            limit=int(Decimal(conversion['factor']))
            base['component_capacity']=limit
        else:
            base['reason']='Aval del principal localizado. Falta una regla documentada para la cantidad de este componente.';continue
        if demand>limit:
            base['reason']=f'Se facturan {demand} unidades adicionales y la fuente acredita {limit}. Revisar el componente.'
            if len(related) == 1:
                base.update(billed_units=demand, covered_units=limit)
            continue
        base.update(status='component_supported',covered_units=billed_quantity(row),billed_units=billed_quantity(row),
                    reason='Adicional vinculado al aval del principal y a su cantidad documentada.')

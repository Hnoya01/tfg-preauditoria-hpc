"""Read-only budget signals; never produce a tariff, allocation or debit proposal."""
import csv
import io
import re
from decimal import Decimal, InvalidOperation
from .hpc_csv_resolutions import EVENT, HEADER

MENTION = re.compile(r'presupuest\w*|cotiza\w*|total autorizado|monto autorizado|importe autorizado|\$\s*\d|\b(?:ARS|USD|pesos)\s+\d', re.I)
MONEY = r'(?:[1-9]\d{0,2}(?:\.\d{3})+|0|[1-9]\d{0,12})(?:,\d{1,2})?'
ARS = r'(?:ARS|pesos(?: argentinos)?)'
LITERAL = rf'(?:{ARS}\s*\$?\s*(?P<before>{MONEY})|\$?\s*(?P<after>{MONEY})\s+{ARS})'
TOTAL = r'(?:por un total autorizado de|(?:presupuesto|importe|monto|total) autorizado(?: por (?:una|1) realizaci[oó]n)?(?: de)?\s*:?)'
INTENT = re.compile(r'\b(?:presupuest\w*|cotiza\w*|valor renegociado|(?:importe|monto|total)(?: total)? (?:autorizad[oa]|aprobad[oa]))\b', re.I)
PENDING = 'por_verificar'
CAVEAT = re.compile(r'\b(?:rectific\w*|revoc\w*|anulad\w*|rechaz\w*|condicionad\w*|sujeto a|salvo|excepto|no autoriza\w*|pendiente)\b', re.I)


def pending(reason):
    return {'status': PENDING, 'reason': reason}


def source_budgets(original, orders):
    """Called only for a verified CSV v3, using accepted orders in its frozen interpretation."""
    accepted = {order['order_id']: order for order in orders}
    by_order = {}
    for csv_row, row in enumerate(csv.DictReader(io.StringIO(original.decode('utf-8-sig'), newline='')), 2):
        order = accepted.get(row['orden_hpc'].strip())
        if not order:
            continue
        mov = row['movimientos'].strip()
        rest = [row[k].strip() for k in ('practicas','historial_original','observacion','justificacion','orientacion')]
        # A price in the nomenclature/description alone is not a budget signal.
        # Ignore the general order status in the movement header.
        movements = [(m[4] if (m := EVENT.fullmatch(line)) else line) for line in mov.splitlines()]
        if not (any(INTENT.search(x) for x in [*movements, *rest]) or
                any(MENTION.search(x) and re.search(r'\bautoriza\w*',x,re.I) for x in movements)):
            continue
        info = dict(order_id=order['order_id'], csv_row=csv_row)
        def unclear(reason):
            by_order[order['order_id']] = {**info, **pending(reason)}
        if len(order['items']) != 1:
            unclear('La orden tiene varias prácticas; no se puede asignar el importe a esta fila.')
            continue
        item = order['items'][0]
        from .authorization_assessment import applicable_resolution
        resolution=applicable_resolution(order,item)
        record=resolution.get('resolution') or {}
        parts=str(record.get('resolution_id','')).split(':')
        event=None
        if resolution['state']=='declared_authorized' and 'event' in parts:
            try:
                event=EVENT.fullmatch(mov.splitlines()[int(parts[parts.index('event')+1])])
            except (ValueError,IndexError):
                pass
        if not event:
            unclear('El historial no contiene una única resolución inequívoca de importe.')
            continue
        # A copy of the same movement is not a second budget. Other monetary
        # statements or conditions must be reconciled before calculating.
        if any(x and x not in (mov, event[4]) and (MENTION.search(x) or CAVEAT.search(x)) for x in rest):
            unclear('Hay otro importe, condición o movimiento que debe contrastarse con la resolución.')
            continue
        reason = event[4]
        header = HEADER.match(reason)
        description = re.escape(item['description'].strip())
        code = re.escape(item['full_code'])
        # Full match prevents attaching an amount from a different clause,
        # a subsequent correction, a condition, or an order-level total.
        m = re.fullmatch(rf'\s*AUTORIZAR\s*:\s*{code}\s*-\s*(?:{description}\s*(?:[x×]\s*(?P<units>\d{{1,6}}|dos)\s*)?(?:[-·;:]\s*)?)?{TOTAL}\s*{LITERAL}\s*\.?\s*',
                         reason[header.end():] if header else '', re.I)
        if not m and not header and event[3].strip().casefold()=='autorizado':
            m=re.fullmatch(rf'\s*(?:se autoriza a valor|valor renegociado|monto autorizado|presupuesto autorizado)(?: de)?\s*:?\s*{LITERAL}\s*\.?\s*',reason,re.I)
        if not m or event[3].strip().casefold() != 'autorizado':
            unclear('No hay un total individual aprobado en ARS que se pueda verificar sin interpretar el texto.')
            continue
        value = Decimal((m['before'] or m['after']).replace('.', '').replace(',', '.'))
        quantity=m.groupdict().get('units') or item.get('requested_quantity') or '1'
        units = 2 if str(quantity).lower()=='dos' else int(quantity)
        if units!=1 and ('realización' in m[0].casefold() or 'realizacion' in m[0].casefold()):
            unclear('La cantidad y el alcance del presupuesto requieren aclaración.')
            continue
        by_order[order['order_id']] = {**info,'budget_units':units, 'movement_actor': event[2].strip(), 'amount_ars': format(value,'.2f')}
    return by_order


def assess_budgets(rows, items, coverage):
    """Use the existing one-use assignment. Never spend a second unit or choose among competing items."""
    candidates = [i for i in items if i.get('budget')]
    if not candidates:
        return
    for row in rows:
        signal = coverage[row['key']]
        from .csv_coverage import VALID_DAYS
        eligible = [i for i in items if i['day'] is None or (row['day'] - i['day']).days <= VALID_DAYS]
        if signal.get('locator'):
            eligible = [i for i in eligible if (i['sha256'],i['locator']) == (signal['source_sha256'],signal['locator'])]
        choices = eligible or items
        if len(signal.get('allocations',[]))>1:
            signal['budget']=pending('Hay varios ítems asignados. Verificar el monto de cada práctica sin repartir importes.')
            continue
        if not any(i.get('budget') for i in choices):
            continue
        if len(choices) != 1:
            signal['budget'] = pending('Hay varias coincidencias para el mismo código y afiliado.')
            continue
        item = choices[0]
        source = item['budget']
        common = {'order_id': source['order_id'], 'csv_row': source['csv_row']}
        def hold(reason):
            signal['budget'] = {**common, **pending(reason)}
        if source.get('reason'):
            hold(source['reason'])
        elif not row.get('hpc'):
            hold('Falta confirmar que esta factura corresponde a HPC.')
        elif row.get('affiliate') != item.get('affiliate'):
            hold('La identificación del afiliado requiere cotejo.')
        elif (signal['status'] not in ('one_unit_supported','units_supported') or
              source.get('budget_units',1)!=signal.get('order_units',1) or
              Decimal(signal.get('normalized_studies',str(signal.get('billed_units',1))))!=source.get('budget_units',1)):
            reasons = {'already_used':'El aval ya respalda otra prestación.', 'outside_window':'La prestación está fuera del plazo de 60 días.',
                       'one_unit_only':'El importe no puede repartirse entre varias unidades facturadas.'}
            hold(reasons.get(signal['status'],'La autorización individual y su vínculo con esta prestación no son inequívocos.'))
        else:
            try:
                billed = Decimal(row['billed'] or '')
                if not billed.is_finite() or billed < 0 or billed.as_tuple().exponent < -2:
                    raise InvalidOperation()
            except (InvalidOperation, TypeError):
                hold('El total facturado no es comparable.')
                continue
            difference = billed - Decimal(source['amount_ars'])
            signal['budget'] = {**common, 'status':'over' if difference > 0 else 'within',
                                'authorized_ars':source['amount_ars'], 'billed_ars':format(billed,'.2f'),
                                'excess_ars':format(max(difference, Decimal('0.00')),'.2f'),
                                'movement_actor':source.get('movement_actor'), 'authorized_on':signal['authorization_date'], 'performed_on':signal['performed_on']}


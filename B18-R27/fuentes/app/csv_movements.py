"""Chronological item decisions from the movements of a single HPC CSV order."""
from datetime import datetime
import re
import unicodedata


def key(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFD', value.upper())
                            if not unicodedata.combining(c)).split())


def rejection_kind(comment):
    value = key(comment)
    if re.search(r'\b(?:SE DERIVA|DERIVAD[AO]|DERIVACION)\b', value):
        return 'referral'
    if re.search(r'\b(?:YA (?:SE )?(?:AUTORIZ|TIENE.{0,18}(?:ORDEN|AUTORIZ))|YA AUTORIZAD)', value):
        return 'prior_claim'
    return 'rejected'


def generic_status(state, comment, item, items):
    value = key(comment)
    restricted = re.search(r'\b(?:SOLO|SOLAMENTE|UNICAMENTE)\s+(.*)', value)
    if restricted:
        # A restricted phrase can identify one listed practice uniquely.
        stop = {'DE','DEL','LA','EL','SE','AUTORIZA','TOMOGRAFIA','COMPUTADA'}
        words = set(re.findall(r'[A-Z0-9]+', restricted[1])) - stop
        matches = [i for i in items if words and words <= set(re.findall(r'[A-Z0-9]+', key(i['description'])))]
        return 'authorized' if state=='AUTORIZADO' and len(matches)==1 and matches[0]==item else 'unknown'
    if re.search(r'CONDICION|PENDIENTE|EXCEP|SALVO|PARCIAL|\bSI\b|SUJETO|NO AUTORIZ|SOLICITA ACLAR|RECTIFIC|\bX\s*\d|\b\d+\s+DE\s+\d+',value):
        return 'unknown'
    if state == 'RECHAZADO':
        return 'referred' if rejection_kind(comment)=='referral' else 'rejected'
    if re.fullmatch(r'SE AUTORIZA A VALOR (?:CONVENIO|NOMENCLADOR)\.?',value):
        return 'authorized'
    # An order may explicitly approve its list at a quoted price. Allocation of
    # that quote to individual studies is an independent, stricter control.
    if re.fullmatch(r'SE AUTORIZA A VALOR (?:[A-Z]+\s+)?(?:ARS\s*|PESOS\s*|\$\s*){1,2}[0-9][\d.,]*',value):
        return 'authorized'
    if len(items)==1 and re.fullmatch(r'(?:MONTO|PRESUPUESTO|VALOR RENEGOCIADO)(?: AUTORIZADO)?(?: DE)?\s*:?\s*(?:ARS|PESOS)\s+\$?[\d.,]+',value):
        return 'authorized'
    if rejection_kind(comment)=='referral' or re.search(r'ANULA|REVOC',value):
        return 'unknown'
    # Names after DR/DRA are evidence of who decided, not an item restriction.
    if not value or re.fullmatch(r'(?:AUTORIZA(?:DO|DA)?\s*(?:POR\s+)?)?(?:DR[A]?\.?\s+[\w .,/()-]+|AUTORIZAD[AO])\.?',value) or value in ('AUTORIZADO','AUTORIZADA','AUTORIZA'):
        return 'authorized'
    return 'unknown'


def read(text, items, record, sha, legacy, event_regex):
    previous, previous_meta = legacy(text,items,record,sha)
    lines = text.splitlines()
    if not lines:
        return previous, previous_meta
    history = {}
    evidence = []
    for position,line in enumerate(lines):
        event = event_regex.fullmatch(line)
        if not event:
            return previous, previous_meta
        try:
            when = datetime.strptime(event[1],'%d/%m/%Y %H:%M').isoformat(timespec='minutes')
        except ValueError:
            return previous,previous_meta
        state = key(event[3])
        if state in ('INGRESADO','SOLICITADO','PENDIENTE','EN AUDITORIA'):
            continue
        if state not in ('AUTORIZADO','RECHAZADO'):
            return [], {**previous_meta,'warnings':[{'code':'unknown_movement'}]}
        parsed, meta = legacy(line,items,record,sha)
        by_item={r['item_ids'][0]:r for r in parsed}
        explicit=bool(re.search(r'Resoluci[oó]n por [ií]tems|AUTORIZAR\s*:|\bCORRESPONDE(?:N)?\s*:',event[4],re.I))
        # A destination annotation alone does not name individual items. It may
        # explain a rejection, but never establish an HPC approval.
        if '[DER:' in event[4] and state!='RECHAZADO':
            explicit=True
        for item in items:
            ident=item['item_id']
            if sum(j['full_code']==item['full_code'] for j in items)!=1:
                continue
            resolution=by_item.get(ident)
            if resolution:
                resolution=dict(resolution)
            elif explicit:
                if meta['warnings']:
                    resolution={'status':'unknown'}
                else:
                    continue
            else:
                status=generic_status(state,event[4],item,items)
                resolution={'status':status}
            qty=resolution.get('authorized_quantity') or item.get('requested_quantity') or '1'
            resolution.update(resolution_id=f"csv:{record}:event:{position}:item:{item['position']}",scope='item',
                item_ids=[ident],decided_at=when,reason=text,
                authorized_quantity=qty if resolution['status']=='authorized' else None,
                unit='práctica' if resolution['status']=='authorized' else None)
            history.setdefault(ident,[]).append(resolution)
            evidence.append({'kind':'authorization','basis':'latest_listed_movement','event':position,'decided_at':when,
                'state':resolution['status'],'full_code':item['full_code'],'item_position':item['position'],
                'csv_record':record,'source_sha256':sha})
    if len(lines)==1 and previous:
        return previous,previous_meta
    if len(lines)==1 and not any(e['state']!='unknown' for e in evidence):
        return previous,previous_meta
    selected=[]
    for records in history.values():
        stamp=max(r['decided_at'] for r in records)
        latest=[r for r in records if r['decided_at']==stamp]
        choice=dict(latest[-1])
        repeated_generic=(all(not re.search(r'AUTORIZAR\s*:|Resoluci[oó]n por',lines[int(r['resolution_id'].split(':')[3])],re.I) for r in latest)
                          and len({(r['status'],r['authorized_quantity']) for r in latest})==1)
        if (len(latest)==1 or repeated_generic) and choice['status']!='unknown':
            selected.append(choice)
    if not selected:
        return [],previous_meta
    return selected,{'csv_record':record,'evidence':evidence,'warnings':[]}


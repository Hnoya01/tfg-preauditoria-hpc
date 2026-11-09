"""Administrative CSV assignments and documented incorporation for selected rows."""
from datetime import date
from uuid import uuid4
from .db import transaction
from .row_decisions import digest,has_duty
from .authorization_matching import _context,_hash,csv_queue_coverage
from .review import _batch
from .service import Problem,authorized_dataset,check_version,event
from .security import now_utc
from .revision_scope import next_ordinal,revision_table


def row_basis(row):
    return digest([row['affiliate_key'],row['original_code'],row['description'],row['quantity'],row['day'],row['billed_order'],row['edits']])


def active_links(conn,revision,scope):
    if conn.execute('PRAGMA user_version').fetchone()[0]<42:
        return {}
    pins={}
    for raw in conn.execute('SELECT * FROM csv_verified_assignments WHERE revision_id=? AND scope_id=? ORDER BY id',(revision,scope)):
        r=dict(raw)
        for n in [n for n,p in pins.items() if (p['source_sha256'],p['locator'])==(r['source_sha256'],r['locator'])]:
            del pins[n]
        pins[r['source_row']]=r
    return pins


def writable(conn,root,token,ds,lot,version,revision_version):
    actor,dataset=authorized_dataset(conn,token,ds,'reviewer')
    check_version(dataset,version)
    if not has_duty(conn,actor,ds):
        raise Problem(403,'Se requiere la función administrativa.')
    batch=_batch(conn,ds,lot)
    if (batch['state']=='cerrada' or batch['revision_version']!=revision_version or
        conn.execute('SELECT 1 FROM invoice_handoffs WHERE revision_id=?',(batch['revision_id'],)).fetchone()):
        raise Problem(409,'La factura cambió o pasó al auditor.')
    scope,caps,issues=_context(conn,root,ds,lot,budgets=True)
    if not scope or issues:
        raise Problem(409,'Actualizá las fuentes de autorización.')
    return actor,batch,(scope,caps,issues)


def bump(conn,ds,revision):
    conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(ds,))
    conn.execute('UPDATE revisions SET version=version+1 WHERE id=?',(revision,))


def reassign(conn,root,token,ds,lot,n,*,expected_version,expected_revision_version,source_sha256,locator,reason):
    if not 10<=len(reason.strip())<=2000:
        raise Problem(422,'Indicá dónde verificaste la orden.')
    with transaction(conn):
        actor,b,ctx=writable(conn,root,token,ds,lot,expected_version,expected_revision_version)
        def signal():
            return csv_queue_coverage(conn,root,ds,lot,[{'source_row':n}],source_context=ctx).get((b['import_id'],n),{})
        before=signal()
        choice=next((p for p in before.get('alternatives',[]) if (p['source_sha256'],p['locator'])==(source_sha256,locator)),None)
        if before.get('status')!='posterior_candidate' or not choice or choice.get('cross_batch'):
            raise Problem(409,'La orden cambió o corresponde a otra factura.')
        conn.execute('INSERT INTO csv_verified_assignments(dataset_id,revision_id,scope_id,source_row,source_sha256,locator,row_basis,reason,actor_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (ds,b['revision_id'],ctx[0]['id'],n,source_sha256,locator,before['row_basis'],reason.strip(),actor['id'],now_utc()))
        after=signal()
        if not after.get('verified_link'):
            raise Problem(409,'El aval ya no se puede asignar de forma inequívoca.')
        bump(conn,ds,b['revision_id'])
        event(conn,actor['id'],'csv_assignment_verified','revision',b['revision_id'])
    return {'dataset_version':expected_version+1,'revision_version':expected_revision_version+1}


def record_group(conn,root,token,ds,lot,*,expected_version,expected_revision_version,rows,incorporation,locator):
    from .practice_families import catalog_families,classify_family
    from .display_categories import add_categories
    from .eligibility import effective_row
    import json
    try:
        if date.fromisoformat(incorporation).isoformat()!=incorporation:
            raise ValueError()
    except (TypeError,ValueError):
        raise Problem(422,'Indicá la fecha de incorporación del comprobante.') from None
    if not rows or len(rows)>2000 or len(set(rows))!=len(rows) or not 3<=len(locator.strip())<=300:
        raise Problem(422,'Indicá el comprobante y sus filas, sin repetirlas.')
    with transaction(conn):
        actor,b,ctx=writable(conn,root,token,ds,lot,expected_version,expected_revision_version)
        areas,names,classification=catalog_families(conn,root,ds)
        if not classification['source_unavailable']:
            add_categories(conn,root,ds,{**b,'batch_id':lot},areas)
        origin='synthetic' if ctx[0]['mode']=='synthetic_demo' else 'real_unvalidated'
        for n in rows:
            raw=conn.execute('SELECT * FROM invoice_rows WHERE import_id=? AND source_row=?',(b['import_id'],n)).fetchone()
            if not raw or effective_row(raw,b['period'])['disposition']!='included':
                raise Problem(422,'Hay filas fuera de esta factura.')
            fields=json.loads(raw['permitted_json'])
            if classify_family(fields['E'],areas,fields['K'],names)[0]!='images':
                raise Problem(422,'El comprobante incluye una fila fuera de Imágenes.')
            previous=conn.execute(f'SELECT id FROM {revision_table(conn,"authorization_input_versions")} WHERE import_id=? AND source_row=? AND kind=? ORDER BY ordinal DESC LIMIT 1',(b['import_id'],n,'incorporation')).fetchone()
            identity,stamp=str(uuid4()),now_utc()
            content=dict(id=identity,import_id=b['import_id'],source_row=n,kind='incorporation',state='declared',value=incorporation,
                         provenance='Comprobante de incorporación al consolidado',locator=locator.strip(),data_origin=origin,
                         previous_id=previous['id'] if previous else None,actor_id=actor['id'],created_at=stamp)
            ordinal=next_ordinal(conn,'authorization_input_versions','import_id=? AND source_row=? AND kind=?',(b['import_id'],n,'incorporation'))
            conn.execute('INSERT INTO authorization_input_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (identity,ds,lot,b['import_id'],n,'incorporation',ordinal,content['previous_id'],'declared',incorporation,content['provenance'],content['locator'],origin,_hash(content),actor['id'],stamp))
        bump(conn,ds,b['revision_id'])
        event(conn,actor['id'],'csv_incorporation_group','revision',b['revision_id'])
    return {'rows':len(rows),'dataset_version':expected_version+1,'revision_version':expected_revision_version+1}


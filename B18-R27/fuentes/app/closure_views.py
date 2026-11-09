"""Exact paginated limitation scopes and immutable closed summaries."""
from collections import Counter
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

from .consistent_reads import consistent_read
from .service import Problem
from .storage import read_verified


def root_path(conn):
    return Path(next(r['file'] for r in conn.execute('PRAGMA database_list') if r['name']=='main')).parent


def frozen(conn,dataset_id,batch_id,revision_id=None):
    from .closure import _sha
    row=conn.execute('SELECT c.* FROM revision_closures c JOIN revisions r ON r.id=c.revision_id '
                     'WHERE c.dataset_id=? AND r.batch_id=? AND (? IS NULL OR r.id=?) ORDER BY r.ordinal DESC LIMIT 1',
                     (dataset_id,batch_id,revision_id,revision_id)).fetchone()
    if row is None:raise Problem(404,'Cierre inexistente')
    with ZipFile(BytesIO(read_verified(root_path(conn),row['archive_sha256']))) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        if _sha(manifest)!=row['manifest_sha256']:raise RuntimeError('Manifest integrity check failed')
        groups=[json.loads(line) for line in archive.read('closure_limitations.jsonl').splitlines()]
        controls=[json.loads(line) for line in archive.read('closure_controls.jsonl').splitlines()]
    page={'state':'cerrada','frozen':True,'revision_id':row['revision_id'],'closure_id':row['id'],
          'archive_sha256':row['archive_sha256'],'manifest_sha256':row['manifest_sha256'],
          'dataset_version':manifest['dataset']['version'],'revision_version':manifest['batch']['revision_version'],
          'ordinal':manifest['batch']['ordinal'],'closed_at':manifest['closure']['closed_at'],
          'basis_format':manifest['closure'].get('basis_format','legacy-v1'),
          'pending_alert_count':0,'processing_active':False,'can_close':False,
          'control_count':manifest['closure']['control_count'],'coverage_note':manifest['closure']['coverage_note'],
          'coverage_counts':dict(Counter(c['result'] for c in controls)),
          'decision_count':len(manifest['closure']['decision_ids']),
          'proposal_version_count':len(manifest['closure']['proposal_version_ids']),
          'current_proposal_total_ars':manifest.get('current_proposal_total_ars'),
          'rn14_simulations':manifest.get('rn14_simulations'),
          'medical_consultations':manifest.get('medical_consultations'),
          'limitations':[{'group_key':g['limitation']['group_key'],'scope_sha256':g['limitation']['scope_sha256'],
                         'reason_code':g['limitation']['reason_code'],'rule_codes':json.loads(g['limitation']['rule_codes_json']),
                         'control_count':len(g['members']),'justification':g['limitation']} for g in groups]}
    return page,groups


def closed_summary(conn,token,dataset_id,batch_id,revision_id=None):
    return consistent_read(conn,token,dataset_id,lambda:frozen(conn,dataset_id,batch_id,revision_id)[0])


def members(conn,token,dataset_id,batch_id,group_key,scope_sha256,offset=0,limit=50,
            revision_id=None,expected_dataset_version=None,expected_revision_version=None):
    if not 0<=offset<=2**63-1 or not 1<=limit<=100:raise Problem(422,'Paginación inválida')
    def read():
        from .closure import _context
        from .review import _batch
        batch=_batch(conn,dataset_id,batch_id)
        if revision_id is not None or batch['state']=='cerrada':
            page,stored=frozen(conn,dataset_id,batch_id,revision_id or batch['revision_id'])
            groups={g['limitation']['group_key']:{'scope_sha256':g['limitation']['scope_sha256'],'members':g['members']} for g in stored}
        else:
            page,groups,_,_=_context(conn,token,dataset_id,batch_id)
        for expected,key in ((expected_dataset_version,'dataset_version'),(expected_revision_version,'revision_version')):
            if expected is not None and page[key]!=expected:raise Problem(409,'La captura cambió; consultar nuevamente')
        group=groups.get(group_key)
        if group is None or group['scope_sha256']!=scope_sha256:raise Problem(409,'Cambió el alcance de la limitación')
        return {'items':group['members'][offset:offset+limit],'total':len(group['members']),'offset':offset,'limit':limit,
                'group_key':group_key,'scope_sha256':scope_sha256,'revision_id':page['revision_id'],
                'dataset_version':page['dataset_version'],'revision_version':page['revision_version'],'frozen':page.get('frozen',False)}
    return consistent_read(conn,token,dataset_id,read)

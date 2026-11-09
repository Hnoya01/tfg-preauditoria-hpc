"""Strict local intake dispatcher; raw Sync sources remain authoritative originals."""
import hashlib
import json
from .authorization_json import (parse_authorization, AuthorizationFormatError,
                                 _unique_object, _reject_constant)
from .hpc_sync_adapter import adapt_sync_day, SyncFormatError
from .storage import MAX_SOURCE_BYTES
from .hpc_csv_adapter import adapt_platform_csv, CsvFormatError


def canonical_bytes(parsed):
    return json.dumps(parsed.canonical, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def parse_authorization_source(content):
    if not 0 < len(content) <= MAX_SOURCE_BYTES:
        raise AuthorizationFormatError([{'path': '$', 'code': 'file_size'}])
    try:
        is_csv = content.decode('utf-8-sig').startswith(('total_ordenes_periodo,', '"total_ordenes_periodo",'))
        raw = {} if is_csv else json.loads(content.decode('utf-8-sig'), object_pairs_hook=_unique_object,
                         parse_constant=_reject_constant)
        stack, count = [(raw, 0)], 0
        while stack:
            value, depth = stack.pop(); count += 1
            if depth > 60 or count > 250000:
                raise AuthorizationFormatError([{'path': '$', 'code': 'document_complexity'}])
            if isinstance(value, dict):
                for key in value: key.encode('utf-8')
                stack.extend((v, depth + 1) for v in value.values())
            elif isinstance(value, list): stack.extend((v, depth + 1) for v in value)
            elif isinstance(value, str): value.encode('utf-8')
        if not isinstance(raw, dict) or 'schema_version' in raw:
            return parse_authorization(content)
        converted, provenance = adapt_platform_csv(content) if is_csv else adapt_sync_day(content)
        parsed = parse_authorization(converted)
        derived = canonical_bytes(parsed)
        provenance.update(output_sha256=hashlib.sha256(derived).hexdigest(),
                          requires_raw_source=True, live_contract_verified=False)
        quarantine_notes = [{'code': 'csv_record_quarantined',
                             'path': '$csv.records[' + str(q['csv_record']) + ']',
                             'message': 'Registro conservado solo en el original; no participa en correspondencias: ' + ', '.join(q['codes']),
                             'level': 'warning'} for q in provenance.get('quarantine', [])]
        parsed.observations = quarantine_notes + parsed.observations
        parsed.summary['observation_count'] = len(parsed.observations)
        parsed.summary['adapter_provenance'] = provenance
        manifest = json.loads(parsed.manifest)
        manifest.update(source_sha256=hashlib.sha256(content).hexdigest(),
                        derived_a1_sha256=provenance['output_sha256'], summary=parsed.summary,
                        observations=parsed.observations)
        parsed.manifest = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')
        if len(parsed.manifest) > MAX_SOURCE_BYTES:
            raise AuthorizationFormatError([{'path': '$', 'code': 'intake_manifest_size_limit'}])
        parsed.preview_sha256 = hashlib.sha256(parsed.manifest).hexdigest()
        return parsed
    except CsvFormatError as exc:
        raise AuthorizationFormatError([{'path': '$', 'code': 'csv_' + str(exc)}]) from None
    except SyncFormatError as exc:
        raise AuthorizationFormatError([{'path': '$', 'code': 'sync_' + str(exc)}]) from None
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, AuthorizationFormatError): raise
        raise AuthorizationFormatError([{'path': '$', 'code': 'invalid_utf8_or_json'}]) from None

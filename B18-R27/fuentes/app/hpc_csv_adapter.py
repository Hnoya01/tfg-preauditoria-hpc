"""Offline intake for the observed HPC platform CSV. Explicit item blocks only; no global approval inference."""
import csv
import hashlib
import io
import json
import re
from datetime import date, datetime
from .storage import MAX_SOURCE_BYTES
from .hpc_csv_resolutions import extract_item_resolutions
from .csv_item_quantity import split_units,quantity_with_total

HEADERS = ('total_ordenes_periodo,orden_hpc,categoria,fecha_orden,fecha_orden_original,'
           'afiliado,nombre,medico,cobertura,practicas,movimientos,diagnostico,justificacion,'
           'orientacion,observacion,historial_original,calidad,advertencias,'
           'captura_actual_aceptada,captura_id,fecha_captura_utc').split(',')
# Commas inside descriptions are not item separators. Codes are never truncated.
ITEM_START = re.compile(r'(?:^|,)([0-9]{10})\s+--\s+')
# A code-like delimiter not recognized above must not become description text.
CODE_LIKE_START = re.compile(r'(?:^|,)\s*[0-9][0-9A-Za-z. /-]*?\s*--')

class CsvFormatError(ValueError):
    pass


def adapt_platform_csv(content):
    def require(ok, code):
        if not ok:
            raise CsvFormatError(code)
    require(0 < len(content) <= MAX_SOURCE_BYTES, 'size')
    try:
        text = content.decode('utf-8-sig')
        require('\x00' not in text, 'nul_character')
        reader = csv.reader(io.StringIO(text, newline=''), strict=True)
        require(next(reader, None) == HEADERS, 'headers')
        rows = list(reader)
        require(0 < len(rows) <= 5000, 'row_count')
        require(all(len(row) == len(HEADERS) for row in rows), 'column_count')
        seen, orders, quarantine, locators, dates, captures = set(), [], [], [], [], []
        item_evidence = []
        quantity_format = False
        source_hash = hashlib.sha256(content).hexdigest()
        for number, values in enumerate(rows, 2):
            row = dict(zip(HEADERS, values))
            require(row['total_ordenes_periodo'] == str(len(rows)), 'declared_total_mismatch')
            order_identity = row['orden_hpc'].strip()
            require(bool(order_identity) and order_identity not in seen, 'duplicate_or_missing_order')
            seen.add(order_identity)
            issues = []
            if row['categoria'] not in ('orden.imagen', 'orden.imagen.digital'):
                issues.append('not_images')
            if row['calidad'] != 'usable' or row['captura_actual_aceptada'] != 'Si':
                issues.append('capture_not_accepted')
            if not row['afiliado'].strip():
                issues.append('missing_affiliate')
            warnings = json.loads(row['advertencias'])
            require(isinstance(warnings, list) and all(isinstance(v, str) for v in warnings), 'warnings_format')
            if warnings:
                issues.append('source_warnings')
            try:
                require(bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', row['fecha_orden'])), 'order_date')
                ordered = date.fromisoformat(row['fecha_orden'])
                require(datetime.strptime(row['fecha_orden_original'], '%d/%m/%Y').date() == ordered, 'order_date_conflict')
                require(bool(re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', row['fecha_captura_utc'])), 'capture_date')
                captured = datetime.strptime(row['fecha_captura_utc'], '%Y-%m-%d %H:%M:%S')
                dates.append(ordered.isoformat()); captures.append(captured.isoformat() + 'Z')
            except (ValueError, CsvFormatError):
                issues.append('date_requires_review')
            practice_text = row['practicas']
            starts = list(ITEM_START.finditer(practice_text))
            if practice_text and (not starts or starts[0].start() != 0 or not practice_text.endswith(',')):
                issues.append('practice_format_requires_review')
            if {m.start() for m in CODE_LIKE_START.finditer(practice_text)} != {m.start() for m in starts}:
                issues.append('practice_separator_requires_review')
            items = []
            for i, match in enumerate(starts):
                end = starts[i + 1].start() if i + 1 < len(starts) else len(practice_text) - 1
                description = practice_text[match.end():end]
                if not description or len(description) > 4000:
                    issues.append('practice_description_requires_review')
                description,units,marked=split_units(description)
                quantity_format |= marked
                if marked and (units is None or not description):
                    issues.append('practice_quantity_requires_review')
                item={'item_id': f'csv-item:{i}', 'position': i, 'full_code': match.group(1), 'description':description}
                if units is not None:
                    item.update(requested_quantity=str(units),unit='práctica')
                items.append(item)
            if issues:
                quarantine.append({'csv_record': number, 'codes': sorted(set(issues))})
                continue
            resolutions, evidence = extract_item_resolutions(row['movimientos'], items, number, source_hash)
            quantity_format |= any('quantity_text' in e for e in evidence['evidence'])
            if evidence['evidence'] or evidence['warnings']:
                item_evidence.append(evidence)
            orders.append({'order_id': row['orden_hpc'], 'affiliate_id': row['afiliado'],
                           'provider': 'HPC', 'ordered_at': row['fecha_orden'], 'items': items,
                           'resolutions': resolutions or ([{'scope': 'unknown', 'item_ids': [],
                                            'reason': row['movimientos']}]
                                           if row['movimientos'] else [])})
            locators.append({'order_position': len(orders) - 1, 'csv_record': number})
        require(bool(orders), 'no_usable_orders')
        source_hash = hashlib.sha256(content).hexdigest()
        limitations = [
            'Exportación observada de imágenes HPC; exhaustividad y autorización individual no acreditadas.',
            'Solo bloques explícitos de resolución por ítems y códigos completos únicos generan estados individuales; sin inferir cantidades ni precios.',
            'Códigos completos de diez dígitos: no se recortan ni se equiparan por prefijo al Excel.',
            'La fecha de orden no es fecha de prestación, autorización ni incorporación al consolidado.',
            'Las filas en cuarentena permanecen en el CSV original y no participan en correspondencias.',
            'Fecha de captura es la última del archivo, según columna UTC; no acredita una captura única.',
            'Descripciones, importes textuales e historial original permanecen en el CSV; no se infieren importes.',
        ]
        budget_units = any(quantity_with_total(e.get('quantity_text','')) is not None for group in item_evidence for e in group['evidence'])
        if quantity_format:
            limitations[1]='Cantidades por práctica solo con resolución individual y cantidad expresamente delimitadas.'
        canonical = {'schema_version': 'A1-canonical-v1', 'data_origin': 'real_unvalidated',
                     'source': {'system': 'HPC-CSV', 'stream_id': 'images:' + min(dates) + ':' + max(dates),
                                'capture_id': source_hash, 'captured_at': max(captures)},
                     'coverage': {'declared': 'partial', 'description': 'CSV de plataforma aportado por el operador.',
                                  'limitations': limitations}, 'orders': orders}
        result = json.dumps(canonical, ensure_ascii=False).encode()
        listed_decision = any(e.get('basis') == 'platform_decision_for_listed_items' for g in item_evidence for e in g['evidence'])
        latest = any(e.get('basis') == 'latest_listed_movement' for g in item_evidence for e in g['evidence'])
        return result, {'adapter': 'hpc-platform-csv-v7' if latest else 'hpc-platform-csv-v6' if listed_decision else 'hpc-platform-csv-v5' if budget_units else 'hpc-platform-csv-v4' if quantity_format else 'hpc-platform-csv-v3', 'source_sha256': source_hash,
                        'output_sha256': hashlib.sha256(result).hexdigest(), 'orders': len(orders),
                        'source_rows': len(rows), 'unrepresented_rows': len(quarantine),
                        'item_resolution_evidence': item_evidence, 'quarantine': quarantine, 'row_locators': locators, 'requires_raw_source': True}
    except CsvFormatError:
        raise
    except (UnicodeError, csv.Error, ValueError, TypeError, OverflowError):
        raise CsvFormatError('invalid_csv') from None

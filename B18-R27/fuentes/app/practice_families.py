"""Read-only display families; nomenclature is never economic applicability."""

from collections import defaultdict
import json
import sqlite3
import re
import unicodedata

from .storage import read_verified
from .values_v1 import source_db


class FamilyIndex(defaultdict):
    def __init__(self):
        super().__init__(set)
        self.origins = defaultdict(list)
        self.invalid_codes = set()


def _add(areas, names, code, area, descriptions, origin):
    # Codes are opaque, complete strings: no prefix, padding or punctuation guesses.
    if not isinstance(code, str) or not code or not isinstance(area, str) or not area:
        raise ValueError('Invalid nomenclature classification entry')
    areas[code].add(area)
    areas.origins[code].append(dict(origin, area=area))
    for name in descriptions:
        if not isinstance(name, str):
            raise ValueError('Invalid nomenclature description')
        normalized = normalized_name(name)
        if normalized:
            names[normalized].add(area)
            item = dict(origin, area=area)
            if item not in names.origins[normalized]:
                names.origins[normalized].append(item)


def catalog_families(conn, root, dataset_id):
    areas, names = FamilyIndex(), FamilyIndex()
    sources = []
    unavailable = False
    for row in conn.execute("SELECT id,source_sha256,cut_label FROM source_registry WHERE dataset_id=? "
                            "AND kind='values' AND status='registered' ORDER BY id", (dataset_id,)):
        source = None
        if root is None:
            unavailable = True
            continue
        try:
            source = source_db(read_verified(root, row['source_sha256']))
            entries = source.execute("SELECT c.seq,c.code,p.area,p.name,c.description,c.provider FROM hpc_catalog_codes c "
                "JOIN hpc_catalog_practices p ON p.seq=c.practice_seq WHERE "
                "(c.provider='HPC' AND c.kind='orden') OR "
                "(c.provider='NOMENCLADOR' AND c.kind='nomenclador') ORDER BY c.seq").fetchall()
            for seq, code, area, practice_name, description, provider in entries:
                origin = {'source_id': row['id'], 'source_sha256': row['source_sha256'],
                          'table': 'hpc_catalog_codes', 'seq': seq,
                          'kind': 'hpc_order' if provider == 'HPC' else 'neutral_nomenclature'}
                _add(areas, names, code, area, (practice_name, description), origin)
            # Optional structured nomenclature, also retained by exported catalogs.
            # It supplies display categories only, even if it includes prices or
            # pending equivalences. Never read amount/practiceIds/equivalence.
            if source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hpc_catalog_components'").fetchone():
                parts = source.execute("SELECT text_data FROM hpc_catalog_components "
                    "WHERE component='seed.nomencladorImagenes' ORDER BY part").fetchall()
                if parts:
                    document = json.loads(''.join(part[0] for part in parts))
                    if not isinstance(document, dict) or document.get('area') != 'Imágenes' or not isinstance(document.get('rows'), list):
                        raise ValueError('Invalid imaging nomenclature component')
                    for position, entry in enumerate(document['rows']):
                        if not isinstance(entry, dict):
                            raise ValueError('Invalid imaging nomenclature row')
                        origin = {'source_id': row['id'], 'source_sha256': row['source_sha256'],
                                  'table': 'hpc_catalog_components', 'component': 'seed.nomencladorImagenes',
                                  'row_index': position, 'source_row': entry.get('sourceRow'),
                                  'source_file': document.get('sourceFile'), 'kind': 'neutral_nomenclature'}
                        _add(areas, names, entry.get('nomencladorCode'), 'Imágenes', (entry.get('description'),), origin)
            from .local_hpc import practices as local_practices
            for practice in local_practices(conn,dataset_id,row['id']):
                if practice['family']=='unclassified':continue
                area='Imágenes' if practice['family']=='images' else 'Otras prácticas'
                _add(areas,names,practice['code'],area,(practice['description'],),
                    {'source_id':row['id'],'source_sha256':row['source_sha256'],'table':'local_hpc_practices',
                     'local_id':practice['id'],'kind':'local_hpc_declared','actor_id':practice['actor_id']})
            sources.append(dict(row))
        except (ValueError, TypeError, OSError, RuntimeError, sqlite3.Error):
            unavailable = True
        finally:
            if source is not None:
                source.close()
    # Independently reviewed documentary excerpts; exact codes only, no aliases.
    if sources and areas and not unavailable:
        from .verified_display_nomenclature import ENTRIES, SOURCE
        for code, area, source_row, description in ENTRIES:
            _add(areas, names, code, area, (),
                 dict(SOURCE, source_row=source_row, display_label=description))
    # A failed registered source can contain a conflicting classification.
    if unavailable:
        areas.clear()
        names.clear()
        areas.origins.clear()
        names.origins.clear()
    return areas, names, {'method': 'HPC-order-and-neutral-nomenclature-exact-v4', 'sources': sources,
                   'available': bool(sources) and not unavailable,
                   'source_unavailable': unavailable, 'coverage': 'partial_unverified',
                   'purpose': 'display_family_only', 'economic_equivalence_established': False}


def normalized_name(value):
    """Presentation-only spelling normalization, never clinical equivalence."""
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', text.upper()).strip()


def _family(declared):
    if declared == {'Imágenes'}:
        return 'images'
    if len(declared) == 1 and 'Imágenes' not in declared and all(declared):
        return 'other'
    return 'unclassified'


def classification_evidence(code, areas, description=None, names=None):
    """Expose matching source locators, including contradictory evidence."""
    from .verified_display_nomenclature import MODALITY
    modality = MODALITY.get(code)
    details = ({'modality': 'Imágenes', 'specialty': modality['specialty'],
                'interpretation': 'documented_modality_specialty_overlap'}
               if modality and classify_family(code, areas, description, names)[1] == 'documented_modality_specialty_overlap' else {})
    return {**details, 'code': getattr(areas, 'origins', {}).get(code, []),
            'name': getattr(names, 'origins', {}).get(normalized_name(description), []),
            'display_only': True}


def classify_family(code, areas, description=None, names=None):
    if code in getattr(areas,'invalid_codes',()):return 'unclassified','category_evidence_unavailable'
    declared = areas.get(code, set())
    named = (names or {}).get(normalized_name(description), set())
    from .verified_display_nomenclature import MODALITY
    overlap = MODALITY.get(code)
    reviewed = any(o.get('kind') == 'reviewed_display_nomenclature'
                   for o in getattr(areas, 'origins', {}).get(code, []))
    if overlap and reviewed and 'Imágenes' in declared and declared <= overlap['allowed_areas'] and named <= overlap['allowed_areas']:
        return 'images', 'documented_modality_specialty_overlap'
    if declared:
        family = _family(declared)
        if family == 'unclassified' or (named and named != declared):
            return 'unclassified', 'conflicting_catalog_evidence'
        origins = getattr(areas, 'origins', {}).get(code, [])
        basis = ('registered_hpc_category' if any(o.get('kind')=='registered_hpc_category' for o in origins) else 'exact_local_hpc_code' if any(o['kind']=='local_hpc_declared' for o in origins) else 'exact_reviewed_nomenclature_code' if reviewed else 'exact_nomenclature_code' if origins and not any(o['kind'] == 'hpc_order' for o in origins)
                 else 'exact_hpc_order_code')
        return family, basis
    if named:
        family = _family(named)
        return family, 'exact_normalized_catalog_name' if family != 'unclassified' else 'conflicting_catalog_evidence'
    return 'unclassified', 'not_found_in_catalog'


def family_for(code, areas, description=None, names=None):
    return classify_family(code, areas, description, names)[0]

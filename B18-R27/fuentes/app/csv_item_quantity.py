"""Cantidades expresas de prácticas. El movimiento y la fila originales permanecen en el CSV."""
import re

# Only an entire item-scoped suffix may supply a quantity. Money, dimensions
# and the general state of an order do not supply units.
NUMBER = r'(?:\d{1,6}|dos)'
MARKER = re.compile(r'(?<!\w)[x×]\s*(?=[+-]?\d|dos\b|varias\b)|\bcant(?:idad(?:\s+autorizada)?|\.)\b|\b(?:\d+|dos|varias)\s+(?:unidades|realizaciones)\b|\bcant\.(?=\s*[\d:])', re.I)
SUFFIX = re.compile(rf'(?:\(\s*)?(?:[x×]\s*({NUMBER})|cant(?:idad(?:\s+autorizada)?|\.)\s*[:=]?\s*({NUMBER})|({NUMBER})\s+(?:unidades|realizaciones))(?:\s*\))?\s*\.?\s*$',re.I)
LEADING_COUNT = re.compile(r'-\s*(\d{1,6}|dos)\s+(.+)',re.I)
LEADING_HINT = re.compile(r'-\s*(?:\d{1,6}|dos)\s+[A-Za-zÁÉÍÓÚÑ]',re.I)


def split_units(text):
    """Return the item text, count, and whether a quantity marker was present."""
    markers=list(MARKER.finditer(text))
    if not markers:
        return text.strip(),None,False
    if len(markers)!=1:
        return text,None,True
    start=markers[0].start()
    if start and text[start-1]=='(':
        start-=1
    tail=text[start:].strip()
    match=SUFFIX.fullmatch(tail)
    if not match or tail.startswith('(')!=tail.rstrip('. ').endswith(')'):
        return text,None,True
    literal=next(n for n in match.groups() if n is not None)
    units=2 if literal.casefold()=='dos' else int(literal)
    if units<1:
        return text,None,True
    description=text[:start].rstrip(' -·;,')
    if description and description[-1].isdigit() and text[start:][:1].lower() in ('x','×'):
        return text,None,True
    return description,units,True


TOTAL_PRICE = r'(?:por un total autorizado de|(?:presupuesto|importe|monto|total) autorizado(?: por (?:una|1) realizaci[oó]n)?(?: de)?\s*:?)'
CURRENCY_AMOUNT = r'(?:[1-9]\d{0,2}(?:\.\d{3})+|0|[1-9]\d{0,12})(?:,\d{1,2})?'
PESO = r'(?:ARS|pesos(?: argentinos)?)'
QUANTITY_TOTAL=re.compile(rf'\s+{TOTAL_PRICE}\s*(?:{PESO}\s*\$?\s*{CURRENCY_AMOUNT}|\$?\s*{CURRENCY_AMOUNT}\s+{PESO})\s*\.?\s*$',re.I)


def quantity_with_total(tail):
    """Return a quantity clause only when the separate ARS total has explicit scope."""
    match=QUANTITY_TOTAL.search(tail)
    if not match:return None
    prefix=tail[:match.start()]
    if not MARKER.search(prefix) or re.search(r'por (?:una|1) realizaci[oó]n',match[0],re.I):
        return None
    return prefix

def clause_units(tail,item):
    # A trailing semicolon may delimit the next numbered clause.
    tail=re.sub(r'(?:;\s*(?:\d+[).])?|\s+\d+[).])\s*$','',tail).strip()
    prefix=quantity_with_total(tail)
    description,units,marked=split_units(prefix if prefix is not None else tail)
    if not marked:
        leading=LEADING_COUNT.fullmatch(tail)
        if leading:
            expected=' '.join(item['description'].split()).casefold()
            if tail.removeprefix('-').strip().casefold()==expected:
                return None,False
            if ' '.join(leading[2].split()).casefold()==expected:
                n=2 if leading[1].casefold()=='dos' else int(leading[1])
                return (n or None),True
            return None,True
        return None,False
    if units is None:
        return None,True
    subject=' '.join(description.removeprefix('-').split()).casefold()
    expected=' '.join(item['description'].split()).casefold()
    if subject and subject!=expected:
        return None,True
    return units,True


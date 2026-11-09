"""Printable local preaudit reports: A4, repeated headers and page numbers."""
from decimal import Decimal
from textwrap import wrap


def ars(value):
    if value is None:
        return 'Por determinar'
    return '$' + format(Decimal(str(value)), ',.2f').translate(str.maketrans(',.','.,'))


def _literal(text):
    return (str(text).replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
            .replace('\r',' ').replace('\n',' ').encode('cp1252','replace'))


def make_pdf(title, lines):
    wrapped = [s for line in lines for s in (wrap(str(line), width=82) or [''])]
    pages = [wrapped[i:i+44] for i in range(0,len(wrapped),44)] or [[]]
    objs = [b'<< /Type /Catalog /Pages 2 0 R >>',b'',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>']
    ids = []
    for i, page in enumerate(pages,1):
        number = len(objs)+1
        ids.append(number)
        command = b'BT /F1 15 Tf 45 790 Td ('+_literal(title)+b') Tj /F1 10 Tf 0 -28 Td 15 TL\n'
        for line in page:
            command += b'('+_literal(line)+b") Tj T*\n"
        command += b'ET\nBT /F1 9 Tf 45 35 Td ('+_literal(f'HPC | Preauditoría | Página {i} de {len(pages)}')+b') Tj ET'
        objs.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {number+1} 0 R >>'.encode())
        objs.append(f'<< /Length {len(command)} >>\nstream\n'.encode()+command+b'\nendstream')
    objs[1]=f"<< /Type /Pages /Count {len(ids)} /Kids [{' '.join(f'{n} 0 R' for n in ids)}] >>".encode()
    output=bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets=[0]
    for n,obj in enumerate(objs,1):
        offsets.append(len(output))
        output.extend(f'{n} 0 obj\n'.encode()+obj+b'\nendobj\n')
    start=len(output)
    output.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for pos in offsets[1:]:
        output.extend(f'{pos:010d} 00000 n \n'.encode())
    output.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode())
    return bytes(output)

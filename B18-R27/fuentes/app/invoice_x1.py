"""Strict, source-located X1 interpretation. Never reads historical debit labels."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from io import BytesIO
import json
import re
import unicodedata

from openpyxl import load_workbook
from .eligibility import POLICY_VERSION, classify


LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
PERMITTED = (0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15, 16, 20)
HEADERS = (
    "R.I.", "Nro. Orden", "Nro.Afiliado", "P/M", "Práctica", "Tipo", "Cant.",
    "Nombre Afiliado", "Fecha Práct.", None, "Desc. Práctica", "Cod.Auto",
    "Médico", "Matrícula", "Hono.", "Dere", "Total", "Coseguro",
    "Total original", "Total Convenido", "URL", "Hono. Debit.", "Dere. Debit",
    "Total Debit.", "Motivo débito", "Desc. Motivo", "Devuelve Comprob?",
)
MAX_ROWS = 100_000
CENT = Decimal("0.01")


def normalized_header(value):
    if value is None:
        return None
    text = unicodedata.normalize("NFKD", str(value).strip())
    return "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()


def source_value(value):
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return format(Decimal(str(value)), "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def numeric_literal(value):
    return format(Decimal(str(value)).normalize(), "f")


def amount(value):
    if isinstance(value, bool) or value is None or not isinstance(value, (int, float, Decimal)):
        raise ValueError("importe no numérico")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("importe inválido") from exc
    if not number.is_finite() or number.as_tuple().exponent < -2:
        raise ValueError("importe sin precisión de centavos")
    return number.quantize(CENT)


def practice_date_iso(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):
        return None
    try:
        parsed = datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError:
        return None
    return parsed.isoformat()


@dataclass
class ParsedX1:
    summary: dict
    rows: list[tuple]


def parse_x1(content: bytes, period: str) -> ParsedX1:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
        raise ValueError("Período inválido; usar AAAA-MM")
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=False, keep_links=False)
    except Exception as exc:
        raise ValueError("No se pudo leer el libro X1") from exc
    try:
        if "Hoja1" not in workbook.sheetnames:
            raise ValueError("Falta la hoja Hoja1 de X1")
        sheet = workbook["Hoja1"]
        if sheet.max_column < 21 or sheet.max_row < 2 or sheet.max_row - 1 > MAX_ROWS:
            raise ValueError("Dimensiones de X1 fuera del contrato")
        iterator = sheet.iter_rows(min_row=1, max_col=27)
        headers = next(iterator)
        wrong = [LETTERS[i] if i < 26 else "AA" for i, (cell, expected) in
                 enumerate(zip(headers, HEADERS)) if i in PERMITTED and
                 normalized_header(cell.value) != normalized_header(expected)]
        if wrong:
            raise ValueError("Encabezados X1 incompatibles en " + ", ".join(wrong))
        rows = []
        counts = {"included": 0, "excluded": 0, "indeterminate": 0}
        totals = [Decimal("0.00") for _ in range(3)]
        blockers = []
        tolerance_count = 0
        source_difference_locators = []
        pending_blank = []
        last_data_row = 1
        for cells in iterator:
            row_no = cells[0].row
            if all(cells[i].value is None for i in PERMITTED):
                pending_blank.append(row_no)
                continue
            blockers.extend(f"Hoja1!{empty}: fila vacía entre datos" for empty in pending_blank)
            pending_blank.clear()
            last_data_row = row_no
            # Only cells in the input allowlist may affect interpretation.
            if any(cells[i].data_type == "f" for i in PERMITTED):
                blockers.append(f"Hoja1!{row_no}: fórmula en entrada permitida")
                continue
            try:
                amounts = tuple(amount(cells[i].value) for i in (14, 15, 16))
            except ValueError as exc:
                blockers.append(f"Hoja1!O{row_no}: {exc}")
                continue
            difference = amounts[0] + amounts[1] - amounts[2]
            if abs(difference) > CENT:
                source_difference_locators.append(f"Hoja1!O{row_no}:Q{row_no}")
            elif difference != 0:
                tolerance_count += 1
            practice_date = practice_date_iso(cells[8].value)
            eligibility = classify(practice_date, cells[5].value, period)
            disposition, reason = eligibility["disposition"], eligibility["disposition_reason"]
            counts[disposition] += 1
            for i, value in enumerate(amounts):
                totals[i] += value
            permitted = {LETTERS[i] if i < 26 else "AA": source_value(cells[i].value) for i in PERMITTED}
            # Preserve the complete practice code as text, without padding.
            if isinstance(cells[4].value, (int, float)) and not isinstance(cells[4].value, bool):
                permitted["E"] = numeric_literal(cells[4].value)
            rows.append((row_no, disposition, reason, practice_date,
                         json.dumps(permitted, ensure_ascii=False, separators=(",", ":")),
                         *(format(value, ".2f") for value in amounts),
                         "consistent" if difference == 0 else "difference_within_tolerance"
                         if abs(difference) <= CENT else "difference_exceeds_tolerance"))
        summary = {
            "sheet": "Hoja1", "period": period, "physical_rows": last_data_row - 1,
            "eligibility_version": POLICY_VERSION,
            "headers": {LETTERS[i] if i < 26 else "AA": headers[i].value for i in PERMITTED},
            "interpreted_rows": len(rows), "included": counts["included"],
            "excluded": counts["excluded"], "indeterminate": counts["indeterminate"],
            "honorarios_ars": format(totals[0], ".2f"),
            "derechos_ars": format(totals[1], ".2f"),
            "total_ars": format(totals[2], ".2f"),
            "within_tolerance": tolerance_count,
            "source_arithmetic_difference_count": len(source_difference_locators),
            "source_arithmetic_difference_locators": source_difference_locators[:20],
            "blocker_count": len(blockers), "blocker_locators": blockers[:20],
            "can_confirm": not blockers and len(rows) == last_data_row - 1 and last_data_row > 1,
        }
        return ParsedX1(summary, rows)
    finally:
        workbook.close()

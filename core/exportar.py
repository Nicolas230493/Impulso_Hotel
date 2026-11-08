"""Exportación de reportes a Excel (openpyxl) y PDF (WeasyPrint)."""

from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _valor(v):
    if isinstance(v, datetime):
        return timezone.localtime(v).replace(tzinfo=None) if timezone.is_aware(v) else v
    if isinstance(v, Decimal):
        return float(v)
    return v


def libro_excel(hojas):
    """hojas: lista de (titulo, encabezados, filas). Devuelve bytes del .xlsx."""
    wb = Workbook()
    wb.remove(wb.active)
    for titulo, encabezados, filas in hojas:
        ws = wb.create_sheet(titulo[:31])
        ws.append(encabezados)
        for celda in ws[1]:
            celda.font = Font(bold=True, color="FFFFFF")
            celda.fill = PatternFill("solid", fgColor="0B3D5C")
            celda.alignment = Alignment(horizontal="center")
        for fila in filas:
            ws.append([_valor(v) for v in fila])
        for i, enc in enumerate(encabezados, start=1):
            ancho = max([len(str(enc))] + [len(str(f[i - 1])) for f in filas if i - 1 < len(f)] or [10])
            ws.column_dimensions[get_column_letter(i)].width = min(max(ancho + 2, 10), 60)
            for fila in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                for c in fila:
                    if isinstance(c.value, float):
                        c.number_format = "#,##0.00"
                    elif isinstance(c.value, (date, datetime)):
                        c.number_format = (
                            "DD/MM/YYYY"
                            if isinstance(c.value, date) and not isinstance(c.value, datetime)
                            else "DD/MM/YYYY HH:MM"
                        )
        ws.freeze_panes = "A2"
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def respuesta_excel(nombre, hojas):
    resp = HttpResponse(libro_excel(hojas), content_type=XLSX)
    resp["Content-Disposition"] = f'attachment; filename="{nombre}.xlsx"'
    return resp


def pdf_bytes(plantilla, contexto, request=None):
    from weasyprint import HTML

    html = render_to_string(plantilla, contexto, request=request)
    base = request.build_absolute_uri("/") if request else None
    return HTML(string=html, base_url=base).write_pdf()


def respuesta_pdf(nombre, plantilla, contexto, request=None, inline=True):
    resp = HttpResponse(pdf_bytes(plantilla, contexto, request), content_type="application/pdf")
    modo = "inline" if inline else "attachment"
    resp["Content-Disposition"] = f'{modo}; filename="{nombre}.pdf"'
    return resp

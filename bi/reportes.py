"""Exportación del dashboard y envío programado por email."""

from datetime import timedelta

from django.utils import timezone

from core.exportar import libro_excel, pdf_bytes

from . import services
from .models import ReporteProgramado


def hojas_kpis(actual, anterior):
    filas = [
        ["Ocupación %", actual["ocupacion"], anterior["ocupacion"]],
        ["ADR", actual["adr"], anterior["adr"]],
        ["RevPAR", actual["revpar"], anterior["revpar"]],
        ["Ingresos alojamiento", actual["ingresos_alojamiento"], anterior["ingresos_alojamiento"]],
        ["Ingresos totales", actual["ingresos_totales"], anterior["ingresos_totales"]],
        ["Estadía promedio (noches)", actual["estadia_promedio"], anterior["estadia_promedio"]],
        ["Antelación promedio (días)", actual["antelacion_promedio"], anterior["antelacion_promedio"]],
        ["Tasa de cancelación %", actual["tasa_cancelacion"], anterior["tasa_cancelacion"]],
        ["Tasa de no-show %", actual["tasa_no_show"], anterior["tasa_no_show"]],
        ["Gastos operativos", actual["gastos_operativos"], anterior["gastos_operativos"]],
        ["Rentabilidad", actual["rentabilidad"], anterior["rentabilidad"]],
        ["Noches disponibles", actual["noches_disponibles"], anterior["noches_disponibles"]],
        ["Noches ocupadas", actual["noches_ocupadas"], anterior["noches_ocupadas"]],
    ]
    return [
        ("Indicadores", ["Indicador", "Período", "Mismo período año anterior"], filas),
        (
            "Ocupación diaria",
            ["Fecha", "Ocupación %"],
            [[s["fecha"], s["ocupacion"]] for s in actual["serie_ocupacion"]],
        ),
        ("Ingresos por canal", ["Canal", "Ingresos"], list(actual["ingresos_por_canal"].items())),
        ("Ingresos por tipo", ["Tipo de habitación", "Ingresos"], list(actual["ingresos_por_tipo"].items())),
        ("Mant. por habitación", ["Habitación", "Costo"], list(actual["costo_mant_por_habitacion"].items())),
        ("Mant. por activo", ["Activo", "Costo"], list(actual["costo_mant_por_activo"].items())),
        ("Mant. por mes", ["Mes", "Costo"], list(actual["costo_mant_por_mes"].items())),
    ]


def generar(hotel, desde, hasta, formato="pdf"):
    actual, anterior, variaciones = services.comparar_anio_anterior(hotel, desde, hasta)
    if formato == "xlsx":
        return libro_excel(hojas_kpis(actual, anterior)), "xlsx"
    ctx = {"hotel": hotel, "k": actual, "ant": anterior, "var": variaciones, "desde": desde, "hasta": hasta}
    return pdf_bytes("bi/dashboard_pdf.html", ctx), "pdf"


def enviar_programados(hoy=None):
    from notificaciones.services import enviar_email

    hoy = hoy or timezone.localdate()
    enviados = 0
    for rep in ReporteProgramado.objects.filter(activo=True).select_related("hotel"):
        if rep.ultimo_envio == hoy:
            continue
        if rep.frecuencia == "semanal" and hoy.weekday() != 0:
            continue
        if rep.frecuencia == "mensual" and hoy.day != 1:
            continue
        dias = {"diario": 1, "semanal": 7, "mensual": 30}[rep.frecuencia]
        desde, hasta = hoy - timedelta(days=dias), hoy - timedelta(days=1)
        if rep.frecuencia == "mensual":
            hasta = hoy - timedelta(days=1)
            desde = hasta.replace(day=1)
        contenido, ext = generar(rep.hotel, desde, hasta, rep.formato)
        mime = (
            "application/pdf" if ext == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        k = services.kpis(rep.hotel, desde, hasta)
        cuerpo = (
            f"{rep.nombre} – {rep.hotel}\nPeríodo {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}\n\n"
            f"Ocupación: {k['ocupacion']} %\nADR: $ {k['adr']}\nRevPAR: $ {k['revpar']}\n"
            f"Ingresos totales: $ {k['ingresos_totales']}\nRentabilidad: $ {k['rentabilidad']}\n"
        )
        for dest in [d.strip() for d in rep.destinatarios.split(",") if d.strip()]:
            enviar_email(
                rep.hotel,
                dest,
                f"{rep.nombre} – {rep.hotel}",
                cuerpo,
                adjuntos=[(f"resumen_{desde}_{hasta}.{ext}", contenido, mime)],
            )
            enviados += 1
        rep.ultimo_envio = hoy
        rep.save(update_fields=["ultimo_envio"])
    return enviados

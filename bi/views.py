from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.exportar import XLSX

from . import reportes, services
from .models import Alerta, Prediccion, RecomendacionTarifa


@login_required
@permission_required("bi.ver_dashboard", raise_exception=True)
def dashboard(request):
    vista = request.GET.get("vista", "mensual")
    ref = parse_date(request.GET.get("fecha", "") or "") or timezone.localdate()
    desde, hasta = services.periodo(vista, ref, a_la_fecha=True)
    formato = request.GET.get("formato")
    if formato in ("pdf", "xlsx"):
        contenido, ext = reportes.generar(request.hotel, desde, hasta, formato)
        resp = HttpResponse(contenido, content_type="application/pdf" if ext == "pdf" else XLSX)
        resp["Content-Disposition"] = f'attachment; filename="dashboard_{desde}_{hasta}.{ext}"'
        return resp
    actual, anterior, variaciones = services.comparar_anio_anterior(request.hotel, desde, hasta)
    graficos = {
        "ocupacion": {
            "labels": [f"{s['fecha']:%d/%m}" for s in actual["serie_ocupacion"]],
            "data": [s["ocupacion"] for s in actual["serie_ocupacion"]],
            "anterior": [s["ocupacion"] for s in anterior["serie_ocupacion"]],
        },
        "canal": {
            "labels": list(actual["ingresos_por_canal"]),
            "data": [float(v) for v in actual["ingresos_por_canal"].values()],
        },
        "tipo": {
            "labels": list(actual["ingresos_por_tipo"]),
            "data": [float(v) for v in actual["ingresos_por_tipo"].values()],
        },
        "mant_mes": {
            "labels": list(actual["costo_mant_por_mes"]),
            "data": [float(v) for v in actual["costo_mant_por_mes"].values()],
        },
    }
    alertas = Alerta.objects.filter(hotel=request.hotel, resuelta=False)[:5]
    salto = {"diaria": 1, "mensual": 31, "anual": 366}.get(vista, 31)
    return render(
        request,
        "bi/dashboard.html",
        {
            "k": actual,
            "ant": anterior,
            "var": variaciones,
            "vista": vista,
            "ref": ref,
            "hoy": timezone.localdate(),
            "desde": desde,
            "hasta": hasta,
            "graficos": graficos,
            "alertas": alertas,
            "anterior_ref": ref - timedelta(days=salto),
            "siguiente_ref": ref + timedelta(days=salto),
        },
    )


@login_required
@permission_required("bi.ver_dashboard", raise_exception=True)
def prediccion(request):
    hoy = timezone.localdate()
    if request.method == "POST" and request.user.has_perm("bi.aprobar_tarifa"):
        resumen = services.predecir_demanda(request.hotel)
        messages.success(request, f"Predicción recalculada con el modelo «{resumen['modelo']}».")
        return redirect("bi_prediccion")
    preds = list(
        Prediccion.objects.filter(hotel=request.hotel, fecha_objetivo__gte=hoy).order_by("fecha_objetivo")[:90]
    )
    hist = services.serie_historica(request.hotel, hoy - timedelta(days=60), hoy - timedelta(days=1))
    graf = {
        "labels": [f"{d:%d/%m}" for d in hist["fecha"]] + [f"{p.fecha_objetivo:%d/%m}" for p in preds],
        "real": [round(v, 1) for v in hist["ocupacion"]] + [None] * len(preds),
        "pred": [None] * len(hist) + [float(p.valor) for p in preds],
        "cartera": [None] * len(hist) + [p.datos_base.get("en_cartera") for p in preds],
    }
    return render(
        request, "bi/prediccion.html", {"preds": preds, "graficos": graf, "modelo": preds[0] if preds else None}
    )


@login_required
@permission_required("bi.ver_dashboard", raise_exception=True)
def tarifas(request):
    if request.method == "POST":
        if not request.user.has_perm("bi.aprobar_tarifa"):
            raise PermissionDenied
        if request.POST.get("accion") == "recalcular":
            n = services.recomendar_tarifas(request.hotel)
            messages.success(request, f"{n} recomendación/es generada/s.")
        else:
            rec = get_object_or_404(RecomendacionTarifa, pk=request.POST.get("rec"), hotel=request.hotel)
            try:
                services.decidir_recomendacion(rec, request.POST.get("accion") == "aprobar", request.user)
                messages.success(request, "Recomendación " + rec.get_estado_display().lower() + ".")
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
        return redirect("bi_tarifas")
    pendientes = RecomendacionTarifa.objects.filter(
        hotel=request.hotel, estado="pendiente", fecha__gte=timezone.localdate()
    ).select_related("tipo_habitacion")
    decididas = (
        RecomendacionTarifa.objects.filter(hotel=request.hotel)
        .exclude(estado="pendiente")
        .select_related("tipo_habitacion", "decidida_por")
        .order_by("-decidida_en")[:30]
    )
    return render(request, "bi/tarifas.html", {"pendientes": pendientes, "decididas": decididas})


@login_required
@permission_required("bi.ver_dashboard", raise_exception=True)
def mant_predictivo(request):
    return render(
        request,
        "bi/mant_predictivo.html",
        {
            "activos": services.ranking_riesgo(request.hotel),
            "habitaciones": services.ranking_habitaciones(request.hotel)[:20],
        },
    )


@login_required
@permission_required("bi.view_alerta", raise_exception=True)
def alertas(request):
    ver = request.GET.get("ver", "abiertas")
    qs = Alerta.objects.filter(hotel=request.hotel)
    if ver == "abiertas":
        qs = qs.filter(resuelta=False)
    return render(request, "bi/alertas.html", {"alertas": qs[:200], "ver": ver})


@login_required
@permission_required("bi.view_alerta", raise_exception=True)
@require_POST
def alerta_resolver(request, pk):
    a = get_object_or_404(Alerta, pk=pk, hotel=request.hotel)
    a.resuelta = True
    a.resuelta_por = request.user
    a.save()
    return redirect("bi_alertas")


@login_required
@permission_required("bi.ver_dashboard", raise_exception=True)
def consolidado(request):
    """Consolidado de cadena: indicadores por hotel de la empresa a los que el usuario tiene acceso."""
    vista = request.GET.get("vista", "mensual")
    desde, hasta = services.periodo(
        vista, parse_date(request.GET.get("fecha", "") or "") or timezone.localdate(), a_la_fecha=True
    )
    hoteles = request.user.hoteles.filter(activo=True)
    if request.hotel and request.hotel.empresa_id:
        hoteles = hoteles.filter(empresa_id=request.hotel.empresa_id)
    filas = [{"hotel": h, "k": services.kpis(h, desde, hasta)} for h in hoteles]
    disp = sum(f["k"]["noches_disponibles"] for f in filas)
    ocup = sum(f["k"]["noches_ocupadas"] for f in filas)
    ingresos = sum((f["k"]["ingresos_alojamiento"] for f in filas), 0)
    total = {
        "ocupacion": round(ocup / disp * 100, 2) if disp else 0,
        "adr": round(ingresos / ocup, 2) if ocup else 0,
        "revpar": round(ingresos / disp, 2) if disp else 0,
        "ingresos_totales": sum((f["k"]["ingresos_totales"] for f in filas), 0),
        "rentabilidad": sum((f["k"]["rentabilidad"] for f in filas), 0),
    }
    return render(
        request, "bi/consolidado.html", {"filas": filas, "total": total, "desde": desde, "hasta": hasta, "vista": vista}
    )

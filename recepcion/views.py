from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from habitaciones import services as hab_services
from habitaciones.models import BloqueoHabitacion, Habitacion
from reservas import services as res_services
from reservas.models import DetalleReserva, Reserva


@login_required
@permission_required("reservas.view_reserva", raise_exception=True)
def panel(request):
    hotel = request.hotel
    hoy = timezone.localdate()
    habs = Habitacion.objects.filter(hotel=hotel, activo=True)
    total = habs.count()
    ocupadas = habs.filter(estado=Habitacion.Estado.OCUPADA).count()
    conteo = {e: habs.filter(estado=e).count() for e, _ in Habitacion.Estado.choices}
    ctx = {
        "hoy": hoy,
        "llegadas": res_services.llegadas_del_dia(hotel, hoy),
        "salidas": res_services.salidas_del_dia(hotel, hoy),
        "en_casa": res_services.en_casa(hotel),
        "total_habitaciones": total,
        "ocupadas": ocupadas,
        "ocupacion": round(ocupadas / total * 100) if total else 0,
        "conteo": conteo,
        "llegadas_manana": res_services.llegadas_del_dia(hotel, hoy + timedelta(days=1)).count(),
    }
    return render(request, "recepcion/panel.html", ctx)


@login_required
@permission_required("reservas.view_reserva", raise_exception=True)
def rack(request):
    hotel = request.hotel
    hoy = timezone.localdate()
    desde = parse_date(request.GET.get("desde", "") or "") or hoy - timedelta(days=1)
    dias = min(max(int(request.GET.get("dias", 14) or 14), 7), 62)
    hasta = desde + timedelta(days=dias)
    fechas = [desde + timedelta(days=i) for i in range(dias)]
    habs = list(Habitacion.objects.filter(hotel=hotel, activo=True).select_related("tipo"))
    detalles = DetalleReserva.objects.filter(
        hotel=hotel, activo=True, vigente=True, fecha_entrada__lt=hasta, fecha_salida__gt=desde
    ).select_related("reserva__titular")
    bloqueos = BloqueoHabitacion.objects.filter(hab_services.bloqueos_en_rango(desde, hasta), hotel=hotel)
    ocup = {}
    for d in detalles:
        for f in fechas:
            if d.fecha_entrada <= f < d.fecha_salida:
                ocup[(d.habitacion_id, f)] = d
    bloq = {
        (b.habitacion_id, f)
        for b in bloqueos
        for f in fechas
        if b.fecha_desde <= f and (b.fecha_hasta is None or f <= b.fecha_hasta)
    }
    filas = []
    for h in habs:
        celdas, i = [], 0
        while i < len(fechas):
            f = fechas[i]
            d = ocup.get((h.pk, f))
            if d:
                span = 1
                while i + span < len(fechas) and ocup.get((h.pk, fechas[i + span])) is d:
                    span += 1
                celdas.append({"tipo": "ocup", "detalle": d, "span": span, "fecha": f})
                i += span
                continue
            celdas.append({"tipo": "bloq" if (h.pk, f) in bloq else "libre", "fecha": f, "span": 1})
            i += 1
        filas.append({"habitacion": h, "celdas": celdas})
    return render(
        request,
        "recepcion/rack.html",
        {
            "fechas": fechas,
            "filas": filas,
            "desde": desde,
            "dias": dias,
            "hoy": hoy,
            "anterior": desde - timedelta(days=dias // 2),
            "siguiente": desde + timedelta(days=dias // 2),
        },
    )


def _contexto_mapa(hotel):
    hoy = timezone.localdate()
    habs = Habitacion.objects.filter(hotel=hotel, activo=True).select_related("tipo").order_by("piso", "numero")
    llegadas = set(
        DetalleReserva.objects.filter(
            hotel=hotel,
            vigente=True,
            activo=True,
            fecha_entrada=hoy,
            reserva__estado__in=[Reserva.Estado.CONFIRMADA, Reserva.Estado.PENDIENTE],
        ).values_list("habitacion_id", flat=True)
    )
    en_casa = {
        d.habitacion_id: d
        for d in DetalleReserva.objects.filter(
            hotel=hotel, vigente=True, activo=True, reserva__estado=Reserva.Estado.EN_CURSO
        ).select_related("reserva__titular")
    }
    pisos = {}
    for h in habs:
        h.estado_visual = hab_services.estado_visual(h, llegadas)
        h.detalle_actual = en_casa.get(h.pk)
        pisos.setdefault(h.piso, []).append(h)
    return {"pisos": sorted(pisos.items()), "estados": Habitacion.Estado.choices, "actualizado": timezone.localtime()}


@login_required
@permission_required("habitaciones.view_habitacion", raise_exception=True)
def mapa(request):
    ctx = _contexto_mapa(request.hotel)
    if request.headers.get("HX-Request"):
        return render(request, "recepcion/_mapa.html", ctx)
    return render(request, "recepcion/mapa.html", ctx)


@login_required
@require_POST
def cambiar_estado_habitacion(request, pk):
    hab = get_object_or_404(Habitacion, pk=pk, hotel=request.hotel, activo=True)
    nuevo = request.POST.get("estado")
    if nuevo not in Habitacion.Estado.values or nuevo in (Habitacion.Estado.OCUPADA, Habitacion.Estado.RESERVADA):
        messages.error(request, "Estado no válido.")
        return redirect("mapa_habitaciones")
    try:
        hab_services.cambiar_estado(hab, nuevo, request.user, motivo=request.POST.get("motivo", ""))
        messages.success(request, f"Habitación {hab}: {hab.get_estado_display()}.")
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, " ".join(getattr(exc, "messages", [str(exc)])))
    return redirect(request.POST.get("volver") or "mapa_habitaciones")

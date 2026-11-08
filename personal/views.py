from datetime import timedelta

from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date

from .models import Empleado, Licencia, Turno


@login_required
@permission_required("personal.view_turno", raise_exception=True)
def planilla(request):
    """Planilla semanal de turnos y licencias."""
    hoy = timezone.localdate()
    inicio = parse_date(request.GET.get("semana", "") or "") or hoy - timedelta(days=hoy.weekday())
    dias = [inicio + timedelta(days=i) for i in range(7)]
    empleados = Empleado.objects.filter(hotel=request.hotel, activo=True)
    turnos = Turno.objects.filter(hotel=request.hotel, activo=True, fecha__gte=dias[0], fecha__lte=dias[-1])
    licencias = Licencia.objects.filter(hotel=request.hotel, activo=True, desde__lte=dias[-1], hasta__gte=dias[0])
    filas = []
    for e in empleados:
        celdas = []
        for d in dias:
            lic = next((x for x in licencias if x.empleado_id == e.pk and x.desde <= d <= x.hasta), None)
            ts = [t for t in turnos if t.empleado_id == e.pk and t.fecha == d]
            celdas.append({"licencia": lic, "turnos": ts})
        filas.append({"empleado": e, "celdas": celdas})
    return render(
        request,
        "personal/planilla.html",
        {"dias": dias, "filas": filas, "anterior": inicio - timedelta(days=7), "siguiente": inicio + timedelta(days=7)},
    )

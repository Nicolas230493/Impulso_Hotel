from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core import roles
from core.models import Usuario
from mantenimiento import services as mant
from mantenimiento.models import Incidencia

from . import services
from .models import ObjetoOlvidado, TareaLimpieza


def _err(exc):
    return " ".join(getattr(exc, "messages", [str(exc)]))


@login_required
@permission_required("limpieza.add_tarealimpieza", raise_exception=True)
def tablero(request):
    fecha = parse_date(request.GET.get("fecha", "") or "") or timezone.localdate()
    tareas = TareaLimpieza.objects.filter(hotel=request.hotel, activo=True, fecha=fecha).select_related(
        "habitacion", "asignada_a"
    )
    mucamas = Usuario.objects.filter(hoteles=request.hotel, is_active=True, groups__name=roles.LIMPIEZA)
    resumen = {e: tareas.filter(estado=e).count() for e, _ in TareaLimpieza.Estado.choices}
    return render(
        request, "limpieza/tablero.html", {"tareas": tareas, "fecha": fecha, "mucamas": mucamas, "resumen": resumen}
    )


@login_required
@permission_required("limpieza.add_tarealimpieza", raise_exception=True)
@require_POST
def generar(request):
    n = services.generar_tareas(request.hotel, parse_date(request.POST.get("fecha", "")) or timezone.localdate())
    messages.success(request, f"{n} tarea/s generada/s.")
    return redirect("limpieza_tablero")


@login_required
@permission_required("limpieza.add_tarealimpieza", raise_exception=True)
@require_POST
def asignar(request, pk):
    t = get_object_or_404(TareaLimpieza, pk=pk, hotel=request.hotel)
    u = Usuario.objects.filter(pk=request.POST.get("usuario"), hoteles=request.hotel).first()
    if u:
        services.asignar(t, u)
    else:
        t.asignada_a = None
        t.save(update_fields=["asignada_a", "actualizado_en"])
    return redirect(f"/limpieza/?fecha={t.fecha:%Y-%m-%d}")


@login_required
@permission_required("limpieza.change_tarealimpieza", raise_exception=True)
def mis_tareas(request):
    hoy = timezone.localdate()
    tareas = (
        TareaLimpieza.objects.filter(hotel=request.hotel, activo=True, fecha=hoy)
        .filter(Q(asignada_a=request.user) | Q(asignada_a__isnull=True))
        .select_related("habitacion__tipo")
    )
    return render(request, "limpieza/mis_tareas.html", {"tareas": tareas, "hoy": hoy})


@login_required
@permission_required("limpieza.change_tarealimpieza", raise_exception=True)
def tarea(request, pk):
    t = get_object_or_404(TareaLimpieza.objects.select_related("habitacion__tipo"), pk=pk, hotel=request.hotel)
    if request.method == "POST":
        accion = request.POST.get("accion")
        try:
            if accion == "iniciar":
                services.iniciar(t, request.user)
                messages.success(request, "Tarea iniciada.")
            elif accion == "terminar":
                checklist = {k[3:]: True for k in request.POST if k.startswith("ck_")}
                services.terminar(t, request.user, checklist, request.POST.get("observaciones", ""))
                messages.success(request, f"Habitación {t.habitacion} lista.")
                return redirect("limpieza_mis_tareas")
            elif accion == "omitir":
                t.estado = TareaLimpieza.Estado.OMITIDA
                t.observaciones = request.POST.get("observaciones", "") or "No molestar"
                t.save()
                return redirect("limpieza_mis_tareas")
            elif accion == "incidencia":
                mant.reportar(
                    request.hotel,
                    request.user,
                    request.POST.get("titulo") or "Incidencia de limpieza",
                    habitacion=t.habitacion,
                    descripcion=request.POST.get("descripcion", ""),
                    origen=Incidencia.Origen.LIMPIEZA,
                    categoria=request.POST.get("categoria") or Incidencia.Categoria.OTRA,
                    bloqueante=bool(request.POST.get("bloqueante")),
                    fotos=request.FILES.getlist("fotos"),
                )
                messages.success(request, "Incidencia reportada a mantenimiento.")
            elif accion == "objeto":
                ObjetoOlvidado.objects.create(
                    hotel=request.hotel,
                    habitacion=t.habitacion,
                    descripcion=request.POST.get("descripcion_objeto", "")[:250],
                    lugar_guardado=request.POST.get("lugar", ""),
                    creado_por=request.user,
                )
                messages.success(request, "Objeto olvidado registrado.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _err(exc))
        return redirect("limpieza_tarea", pk)
    return render(
        request,
        "limpieza/tarea.html",
        {"t": t, "checklist": services.checklist_para(t), "categorias": Incidencia.Categoria.choices},
    )

from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core import roles
from core.forms import FormHotel
from core.models import Usuario
from inventario.models import Deposito, Producto

from . import services
from .models import Incidencia, Mantenimiento


def _err(exc):
    if hasattr(exc, "message_dict"):
        return " ".join(m for ms in exc.message_dict.values() for m in ms)
    return " ".join(getattr(exc, "messages", [str(exc)]))


class VariosArchivos(forms.ClearableFileInput):
    allow_multiple_selected = True


class IncidenciaForm(FormHotel):
    fotos = forms.FileField(
        required=False, widget=VariosArchivos(attrs={"accept": "image/*"}), help_text="Puede adjuntar varias fotos"
    )

    def clean_fotos(self):
        return None  # se leen con request.FILES.getlist("fotos")

    class Meta:
        model = Incidencia
        fields = [
            "habitacion",
            "activo_relacionado",
            "titulo",
            "descripcion",
            "origen",
            "categoria",
            "prioridad",
            "bloqueante",
        ]


def _tecnicos(hotel):
    return Usuario.objects.filter(hoteles=hotel, is_active=True, groups__name=roles.MANTENIMIENTO)


@login_required
@permission_required("mantenimiento.view_incidencia", raise_exception=True)
def tablero(request):
    qs = Incidencia.objects.filter(hotel=request.hotel, activo=True).select_related(
        "habitacion", "activo_relacionado", "asignada_a"
    )
    ver = request.GET.get("ver", "abiertas")
    if ver == "abiertas":
        qs = qs.exclude(estado=Incidencia.Estado.CERRADA)
    elif ver == "mias":
        qs = qs.filter(asignada_a=request.user).exclude(estado=Incidencia.Estado.CERRADA)
    columnas = [
        (e, n, [i for i in qs if i.estado == e])
        for e, n in Incidencia.Estado.choices
        if ver != "abiertas" or e != Incidencia.Estado.CERRADA
    ]
    return render(request, "mantenimiento/tablero.html", {"columnas": columnas, "ver": ver})


@login_required
@permission_required("mantenimiento.add_incidencia", raise_exception=True)
def nueva(request):
    inicial = {}
    if request.GET.get("habitacion"):
        inicial["habitacion"] = request.GET["habitacion"]
    if request.user.tiene_rol(roles.LIMPIEZA):
        inicial["origen"] = Incidencia.Origen.LIMPIEZA
    elif request.user.tiene_rol(roles.MANTENIMIENTO):
        inicial["origen"] = Incidencia.Origen.MANTENIMIENTO
    form = IncidenciaForm(request.POST or None, request.FILES or None, initial=inicial, hotel=request.hotel)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            inc = services.reportar(
                request.hotel,
                request.user,
                d["titulo"],
                habitacion=d["habitacion"],
                activo=d["activo_relacionado"],
                descripcion=d["descripcion"],
                origen=d["origen"],
                categoria=d["categoria"],
                prioridad=d["prioridad"],
                bloqueante=d["bloqueante"],
                fotos=request.FILES.getlist("fotos"),
            )
            messages.success(request, f"Incidencia #{inc.pk} reportada. Mantenimiento ya fue notificado.")
            return redirect("incidencia_detalle", inc.pk)
        except ValidationError as exc:
            form.add_error(None, _err(exc))
    return render(
        request,
        "crud/form.html",
        {"form": form, "titulo": "Reportar incidencia", "url_lista": "/mantenimiento/incidencias/"},
    )


@login_required
@permission_required("mantenimiento.view_incidencia", raise_exception=True)
def detalle(request, pk):
    inc = get_object_or_404(
        Incidencia.objects.select_related("habitacion", "activo_relacionado", "asignada_a"), pk=pk, hotel=request.hotel
    )
    return render(
        request,
        "mantenimiento/detalle.html",
        {
            "inc": inc,
            "tecnicos": _tecnicos(request.hotel),
            "trabajos": inc.mantenimientos.filter(activo=True),
            "fotos": inc.fotos.filter(activo=True),
            "siguientes": Incidencia.TRANSICIONES.get(inc.estado, []),
            "estados": dict(Incidencia.Estado.choices),
            "productos": Producto.objects.filter(hotel=request.hotel, activo=True),
            "depositos": Deposito.objects.filter(hotel=request.hotel, activo=True),
            "filas": range(4),
        },
    )


def _leer_repuestos(post, hotel):
    repuestos = []
    for i in range(4):
        pid, cant = post.get(f"rep_{i}"), post.get(f"rep_cant_{i}")
        if not pid or not cant:
            continue
        try:
            cant = Decimal(cant)
        except InvalidOperation:
            continue
        prod = Producto.objects.filter(pk=pid, hotel=hotel).first()
        dep = Deposito.objects.filter(pk=post.get(f"rep_dep_{i}"), hotel=hotel).first()
        if prod and cant > 0:
            repuestos.append((prod, dep, cant))
    return repuestos


@login_required
@permission_required("mantenimiento.change_incidencia", raise_exception=True)
@require_POST
def accion(request, pk):
    inc = get_object_or_404(Incidencia, pk=pk, hotel=request.hotel)
    a = request.POST.get("accion")
    try:
        if a == "asignar":
            tecnico = get_object_or_404(_tecnicos(request.hotel), pk=request.POST.get("tecnico"))
            services.asignar(inc, tecnico)
            messages.success(request, f"Asignada a {tecnico}.")
        elif a == "estado":
            services.cambiar_estado(inc, request.POST.get("estado"), request.user, request.POST.get("solucion", ""))
            messages.success(request, "Estado actualizado.")
        elif a == "trabajo":
            services.registrar_trabajo(
                request.hotel,
                request.user,
                request.POST.get("descripcion", ""),
                incidencia=inc,
                horas=request.POST.get("horas") or 0,
                costo_mano_obra=request.POST.get("costo_mano_obra") or 0,
                costo_externo=request.POST.get("costo_externo") or 0,
                repuestos=_leer_repuestos(request.POST, request.hotel),
            )
            messages.success(request, "Trabajo registrado (repuestos descontados del stock).")
    except ValidationError as exc:
        messages.error(request, _err(exc))
    return redirect("incidencia_detalle", pk)


@login_required
@permission_required("mantenimiento.view_mantenimiento", raise_exception=True)
def ordenes(request):
    qs = Mantenimiento.objects.filter(hotel=request.hotel, activo=True).select_related(
        "plan", "incidencia", "activo_relacionado", "habitacion", "tecnico"
    )
    pendientes = qs.filter(estado=Mantenimiento.Estado.PENDIENTE).order_by("fecha_programada")
    realizados = qs.filter(estado=Mantenimiento.Estado.REALIZADO).order_by("-fecha_realizado")[:50]
    return render(
        request,
        "mantenimiento/ordenes.html",
        {
            "pendientes": pendientes,
            "realizados": realizados,
            "filas": range(4),
            "productos": Producto.objects.filter(hotel=request.hotel, activo=True),
            "depositos": Deposito.objects.filter(hotel=request.hotel, activo=True),
        },
    )


@login_required
@permission_required("mantenimiento.change_mantenimiento", raise_exception=True)
@require_POST
def orden_registrar(request, pk):
    orden = get_object_or_404(Mantenimiento, pk=pk, hotel=request.hotel)
    try:
        services.registrar_trabajo(
            request.hotel,
            request.user,
            request.POST.get("descripcion", ""),
            orden=orden,
            horas=request.POST.get("horas") or 0,
            costo_mano_obra=request.POST.get("costo_mano_obra") or 0,
            costo_externo=request.POST.get("costo_externo") or 0,
            repuestos=_leer_repuestos(request.POST, request.hotel),
        )
        messages.success(request, "Orden registrada como realizada.")
    except ValidationError as exc:
        messages.error(request, _err(exc))
    return redirect("orden_preventiva_lista")


@login_required
@permission_required("mantenimiento.add_mantenimiento", raise_exception=True)
@require_POST
def generar_preventivas(request):
    n = services.generar_ordenes_preventivas()
    messages.success(request, f"{n} orden/es preventiva/s generada/s.")
    return redirect("orden_preventiva_lista")

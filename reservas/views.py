from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from caja import services as caja_services
from core.models import Auditoria
from habitaciones import services as hab_services
from habitaciones.models import Habitacion
from huespedes.models import Huesped

from . import services
from .forms import CancelarForm, CargoForm, PagoForm, ReservaForm, habitaciones_elegidas
from .models import Reserva


def _errores(exc):
    if hasattr(exc, "message_dict"):
        return " ".join(m for ms in exc.message_dict.values() for m in ms)
    return " ".join(getattr(exc, "messages", [str(exc)]))


def _reserva(request, pk):
    return get_object_or_404(
        Reserva.objects.select_related("titular", "cuenta_corriente"), pk=pk, hotel=request.hotel, activo=True
    )


@login_required
@permission_required("reservas.view_reserva", raise_exception=True)
def lista(request):
    qs = Reserva.objects.filter(hotel=request.hotel, activo=True).select_related("titular")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(codigo__iexact=q)
            | Q(titular__apellido__icontains=q)
            | Q(titular__nombre__icontains=q)
            | Q(titular__nro_doc__icontains=q)
            | Q(referencia_canal__icontains=q)
        )
    estado = request.GET.get("estado", "")
    if estado:
        qs = qs.filter(estado=estado)
    desde = parse_date(request.GET.get("desde", "") or "")
    hasta = parse_date(request.GET.get("hasta", "") or "")
    if desde:
        qs = qs.filter(fecha_salida__gt=desde)
    if hasta:
        qs = qs.filter(fecha_entrada__lte=hasta)
    pagina = Paginator(qs.order_by("-fecha_entrada", "-id"), 30).get_page(request.GET.get("page"))
    return render(
        request,
        "reservas/lista.html",
        {
            "page_obj": pagina,
            "q": q,
            "estado": estado,
            "estados": Reserva.Estado.choices,
            "desde": desde,
            "hasta": hasta,
        },
    )


def _form_reserva(request, reserva=None, walk_in=False):
    hotel = request.hotel
    inicial = {}
    if reserva:
        t = reserva.titular
        inicial = {
            "tipo_doc": t.tipo_doc,
            "nro_doc": t.nro_doc,
            "nombre": t.nombre,
            "apellido": t.apellido,
            "telefono": t.telefono,
            "email": t.email,
            "nacionalidad": t.nacionalidad,
            "consentimiento_datos": t.consentimiento_datos,
            "consentimiento_whatsapp": t.consentimiento_whatsapp,
            "fecha_entrada": reserva.fecha_entrada,
            "fecha_salida": reserva.fecha_salida,
            "canal": reserva.canal,
            "referencia_canal": reserva.referencia_canal,
            "sena": reserva.sena,
            "cuenta_corriente": reserva.cuenta_corriente,
            "observaciones": reserva.observaciones,
            "confirmar": reserva.estado == Reserva.Estado.CONFIRMADA,
        }
        seleccion = {d.habitacion_id: d.cantidad_huespedes for d in reserva.detalles.filter(activo=True, vigente=True)}
    else:
        entrada = parse_date(request.GET.get("entrada", "") or "") or timezone.localdate()
        inicial = {"fecha_entrada": entrada, "fecha_salida": entrada + timezone.timedelta(days=1)}
        hab = request.GET.get("habitacion")
        seleccion = {int(hab): 1} if hab and hab.isdigit() else {}
        huesped_id = request.GET.get("huesped")
        if huesped_id and huesped_id.isdigit():
            t = Huesped.objects.filter(pk=huesped_id, hotel=hotel, activo=True).first()
            if t:
                inicial.update(
                    {
                        "tipo_doc": t.tipo_doc,
                        "nro_doc": t.nro_doc,
                        "nombre": t.nombre,
                        "apellido": t.apellido,
                        "telefono": t.telefono,
                        "email": t.email,
                        "nacionalidad": t.nacionalidad,
                        "consentimiento_datos": t.consentimiento_datos,
                        "consentimiento_whatsapp": t.consentimiento_whatsapp,
                    }
                )
    form = ReservaForm(request.POST or None, initial=inicial, hotel=hotel, walk_in=walk_in)
    if request.method == "POST":
        seleccion = {i["habitacion"].pk: i["cantidad_huespedes"] for i in habitaciones_elegidas(request.POST, hotel)}
        if form.is_valid():
            d = form.cleaned_data
            items = habitaciones_elegidas(request.POST, hotel)
            try:
                titular = form.obtener_huesped(hotel, request.user)
                if walk_in:
                    r = services.walk_in(
                        hotel,
                        titular,
                        d["fecha_salida"],
                        items,
                        usuario=request.user,
                        canal=d["canal"],
                        observaciones=d["observaciones"],
                        confirmar_sucia=bool(request.POST.get("confirmar_sucia")),
                    )
                    messages.success(request, f"Walk-in registrado: reserva {r.codigo} en curso.")
                elif reserva:
                    r = services.modificar_reserva(
                        reserva,
                        d["fecha_entrada"],
                        d["fecha_salida"],
                        items,
                        usuario=request.user,
                        titular=titular,
                        canal=d["canal"],
                        referencia_canal=d["referencia_canal"],
                        sena=d["sena"] or Decimal("0"),
                        cuenta_corriente=d["cuenta_corriente"],
                        observaciones=d["observaciones"],
                    )
                    if d.get("confirmar") and r.estado == Reserva.Estado.PENDIENTE:
                        services.confirmar(r, request.user)
                    messages.success(request, f"Reserva {r.codigo} modificada.")
                else:
                    r = services.crear_reserva(
                        hotel,
                        titular,
                        d["fecha_entrada"],
                        d["fecha_salida"],
                        items,
                        canal=d["canal"],
                        sena=d["sena"] or Decimal("0"),
                        observaciones=d["observaciones"],
                        usuario=request.user,
                        estado=Reserva.Estado.CONFIRMADA if d.get("confirmar") else Reserva.Estado.PENDIENTE,
                        referencia_canal=d["referencia_canal"],
                        cuenta_corriente=d["cuenta_corriente"],
                    )
                    messages.success(request, f"Reserva {r.codigo} creada por $ {r.total:,.2f}.")
                return redirect("reserva_detalle", r.pk)
            except ValidationError as exc:
                if getattr(exc, "code", None) == "habitacion_sucia" or "sucia" in _errores(exc):
                    form.add_error(None, _errores(exc))
                    return render(
                        request,
                        "reservas/form.html",
                        {
                            "form": form,
                            "reserva": reserva,
                            "walk_in": walk_in,
                            "seleccion": seleccion,
                            "pedir_confirmar_sucia": True,
                        },
                    )
                form.add_error(None, _errores(exc))
    return render(
        request, "reservas/form.html", {"form": form, "reserva": reserva, "walk_in": walk_in, "seleccion": seleccion}
    )


@login_required
@permission_required("reservas.add_reserva", raise_exception=True)
def nueva(request):
    return _form_reserva(request)


@login_required
@permission_required("reservas.change_reserva", raise_exception=True)
def editar(request, pk):
    reserva = _reserva(request, pk)
    if reserva.estado not in (Reserva.Estado.PENDIENTE, Reserva.Estado.CONFIRMADA):
        messages.error(request, "Solo se pueden modificar reservas pendientes o confirmadas.")
        return redirect("reserva_detalle", pk)
    return _form_reserva(request, reserva)


@login_required
@permission_required("reservas.checkin_reserva", raise_exception=True)
def walk_in(request):
    return _form_reserva(request, walk_in=True)


@login_required
@permission_required("reservas.view_reserva", raise_exception=True)
def disponibilidad(request):
    """Parcial HTMX: habitaciones disponibles para las fechas, con el precio cotizado."""
    hotel = request.hotel
    entrada = parse_date(request.GET.get("fecha_entrada", "") or "") or timezone.localdate()
    salida = parse_date(request.GET.get("fecha_salida", "") or "")
    excluir = request.GET.get("reserva")
    excluir = Reserva.objects.filter(pk=excluir, hotel=hotel).first() if excluir and excluir.isdigit() else None
    seleccion = {}
    for k, v in request.GET.items():
        if k.startswith("hab_") and k[4:].isdigit():
            seleccion[int(k[4:])] = int(request.GET.get(f"cant_{k[4:]}") or 1)
    if not salida or salida <= entrada:
        return render(request, "reservas/_disponibilidad.html", {"error": "Elija fechas válidas."})
    habs = list(hab_services.habitaciones_disponibles(hotel, entrada, salida, excluir_reserva=excluir))
    cotizaciones = {}
    filas = []
    for h in habs:
        if h.tipo_id not in cotizaciones:
            cotizaciones[h.tipo_id] = hab_services.cotizar(h.tipo, entrada, salida)[0]
        filas.append(
            {
                "hab": h,
                "total": cotizaciones[h.tipo_id],
                "marcada": h.pk in seleccion,
                "cant": seleccion.get(h.pk, 1),
                "rango": range(1, h.tipo.capacidad + 1),
            }
        )
    return render(request, "reservas/_disponibilidad.html", {"filas": filas, "noches": (salida - entrada).days})


@login_required
@permission_required("huespedes.view_huesped", raise_exception=True)
def buscar_huesped_doc(request):
    nro = (request.GET.get("nro_doc") or "").replace(".", "").replace(" ", "").upper()
    tipo = request.GET.get("tipo_doc") or "DNI"
    h = Huesped.objects.filter(hotel=request.hotel, activo=True, tipo_doc=tipo, nro_doc=nro).first() if nro else None
    return render(request, "reservas/_huesped_encontrado.html", {"h": h})


@login_required
@permission_required("reservas.view_reserva", raise_exception=True)
def detalle(request, pk):
    r = _reserva(request, pk)
    from facturacion.models import Factura

    ctx = {
        "r": r,
        "detalles": r.detalles.filter(activo=True).select_related("habitacion", "tipo_habitacion"),
        "estadias": r.estadias.select_related("habitacion").prefetch_related("acompanantes"),
        "cargos": r.cargos.filter(activo=True).select_related("factura"),
        "pagos": r.pagos.filter(activo=True).select_related("creado_por"),
        "total_cargos": caja_services.total_cargos(r),
        "total_pagos": caja_services.total_pagos(r),
        "saldo": caja_services.saldo(r),
        "saldo_estimado": caja_services.saldo_estimado(r),
        "facturas": Factura.objects.filter(reserva=r, activo=True).select_related("punto_venta"),
        "pendientes_facturar": r.cargos.filter(activo=True, factura__isnull=True).exists(),
        "mensajes": r.mensajes.all()[:20],
        "pago_form": PagoForm(),
        "cargo_form": CargoForm(hotel=request.hotel),
        "cancelar_form": CancelarForm(),
        "historial": Auditoria.objects.filter(modelo="reservas.Reserva", objeto_id=str(r.pk))[:30],
        "caja_abierta": caja_services.caja_abierta(request.user, request.hotel),
        "hoy": timezone.localdate(),
    }
    return render(request, "reservas/detalle.html", ctx)


def _accion(request, pk, funcion, ok):
    r = _reserva(request, pk)
    try:
        funcion(r)
        messages.success(request, ok)
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _errores(exc))
    return redirect("reserva_detalle", pk)


@login_required
@permission_required("reservas.change_reserva", raise_exception=True)
@require_POST
def confirmar(request, pk):
    return _accion(request, pk, lambda r: services.confirmar(r, request.user), "Reserva confirmada.")


@login_required
@permission_required("reservas.cancelar_reserva", raise_exception=True)
@require_POST
def cancelar(request, pk):
    motivo = request.POST.get("motivo", "")
    return _accion(request, pk, lambda r: services.cancelar(r, motivo, request.user), "Reserva cancelada.")


@login_required
@permission_required("reservas.checkin_reserva", raise_exception=True)
def checkin(request, pk):
    r = _reserva(request, pk)
    detalles = list(
        r.detalles.filter(activo=True, vigente=True, estadia__isnull=True).select_related(
            "habitacion", "tipo_habitacion"
        )
    )
    if request.method == "POST":
        acompanantes = {}
        try:
            for det in detalles:
                lista = []
                for i in range(det.tipo_habitacion.capacidad):
                    pref = f"a_{det.pk}_{i}_"
                    nro = (request.POST.get(pref + "nro_doc") or "").strip()
                    if not nro:
                        continue
                    nombre, apellido = (
                        request.POST.get(pref + "nombre", "").strip(),
                        request.POST.get(pref + "apellido", "").strip(),
                    )
                    tipo = request.POST.get(pref + "tipo_doc") or "DNI"
                    nro = nro.replace(".", "").replace(" ", "").upper()
                    h = Huesped.objects.filter(hotel=r.hotel, activo=True, tipo_doc=tipo, nro_doc=nro).first()
                    if h is None:
                        if not (nombre and apellido):
                            raise ValidationError(f"Complete nombre y apellido del acompañante con doc. {nro}.")
                        h = Huesped.objects.create(
                            hotel=r.hotel,
                            tipo_doc=tipo,
                            nro_doc=nro,
                            nombre=nombre,
                            apellido=apellido,
                            creado_por=request.user,
                        )
                    if h.pk != r.titular_id:
                        lista.append(h)
                acompanantes[det.pk] = lista
            elegidos = [d for d in detalles if request.POST.get(f"det_{d.pk}")] or detalles
            services.checkin(
                r,
                usuario=request.user,
                detalles=elegidos,
                acompanantes=acompanantes,
                confirmar_sucia=bool(request.POST.get("confirmar_sucia")),
            )
            messages.success(request, "Check-in registrado. ¡Bienvenidos!")
            return redirect("reserva_detalle", pk)
        except ValidationError as exc:
            messages.error(request, _errores(exc))
            if getattr(exc, "code", None) == "habitacion_sucia" or "sucia" in _errores(exc):
                return render(
                    request,
                    "reservas/checkin.html",
                    {"r": r, "detalles": detalles, "pedir_confirmar_sucia": True, "post": request.POST},
                )
    return render(request, "reservas/checkin.html", {"r": r, "detalles": detalles, "post": {}})


@login_required
@permission_required("reservas.checkout_reserva", raise_exception=True)
@require_POST
def checkout(request, pk):
    autorizar = bool(request.POST.get("autorizar_saldo"))
    facturar = bool(request.POST.get("facturar"))
    return _accion(
        request,
        pk,
        lambda r: services.checkout(r, request.user, autorizar_saldo=autorizar, facturar=facturar),
        "Check-out registrado. La habitación pasó a «sucia».",
    )


@login_required
@permission_required("caja.add_pago", raise_exception=True)
@require_POST
def registrar_pago(request, pk):
    r = _reserva(request, pk)
    form = PagoForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        try:
            caja_services.registrar_pago(
                r,
                d["medio"],
                d["importe"],
                request.user,
                moneda=d["moneda"],
                tipo_cambio=d["tipo_cambio"] or 1,
                tipo=d["tipo"],
                referencia=d["referencia"],
            )
            messages.success(request, "Movimiento registrado.")
        except ValidationError as exc:
            messages.error(request, _errores(exc))
    else:
        messages.error(request, "Revise los datos del pago: " + form.errors.as_text())
    return redirect(f"/reservas/{pk}/#cuenta")


@login_required
@permission_required("caja.add_cargo", raise_exception=True)
@require_POST
def registrar_cargo(request, pk):
    r = _reserva(request, pk)
    form = CargoForm(request.POST, hotel=request.hotel)
    if form.is_valid():
        d = form.cleaned_data
        prod = d.get("producto")
        try:
            caja_services.registrar_cargo(
                r,
                d["concepto"] or prod.nombre,
                d["precio_unitario"] if d["precio_unitario"] is not None else prod.precio_venta,
                cantidad=d["cantidad"],
                origen=d["origen"],
                producto=prod,
                usuario=request.user,
                alicuota_iva=prod.alicuota_iva if prod else Decimal("21"),
            )
            messages.success(request, "Cargo agregado a la cuenta.")
        except ValidationError as exc:
            messages.error(request, _errores(exc))
    else:
        messages.error(request, "Revise el cargo: " + form.errors.as_text())
    return redirect(f"/reservas/{pk}/#cuenta")


@login_required
@permission_required("facturacion.emitir_factura", raise_exception=True)
@require_POST
def facturar(request, pk):
    from facturacion import services as fact

    r = _reserva(request, pk)
    try:
        f = fact.facturar_reserva(r, extranjero_exento=bool(request.POST.get("extranjero_exento")))
        messages.success(request, f"Comprobante {f.get_tipo_display()} generado y enviado a ARCA.")
        return redirect("factura_detalle", f.pk)
    except ValidationError as exc:
        messages.error(request, _errores(exc))
    return redirect("reserva_detalle", pk)


@login_required
@permission_required("habitaciones.view_habitacion", raise_exception=True)
def habitaciones_json(request):
    """Utilidad para el formulario: tipos y capacidades."""
    from django.http import JsonResponse

    habs = Habitacion.objects.filter(hotel=request.hotel, activo=True).select_related("tipo")
    return JsonResponse(
        [{"id": h.pk, "numero": h.numero, "tipo": h.tipo.nombre, "capacidad": h.tipo.capacidad} for h in habs],
        safe=False,
    )

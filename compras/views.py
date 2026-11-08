from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.exportar import respuesta_excel
from core.forms import FormHotel
from inventario.models import Deposito, Producto

from . import services
from .models import Gasto, ItemCompra, ItemSolicitud, OrdenCompra, Proveedor, SolicitudCompra

FILAS_ITEMS = 8


def _err(exc):
    return " ".join(getattr(exc, "messages", [str(exc)]))


def _dec(valor):
    try:
        return Decimal(str(valor).replace(",", "."))
    except (InvalidOperation, TypeError):
        return None


def _leer_items(post, hotel, con_precio=True):
    items = []
    for i in range(FILAS_ITEMS):
        pid = post.get(f"prod_{i}")
        cant = _dec(post.get(f"cant_{i}"))
        if not pid or not cant or cant <= 0:
            continue
        prod = Producto.objects.filter(hotel=hotel, activo=True, pk=pid).first()
        if prod is None:
            continue
        precio = _dec(post.get(f"precio_{i}")) if con_precio else None
        items.append((prod, cant, precio if precio is not None else prod.costo))
    return items


# ----------------------------------------------------------------- Gastos


class GastoForm(FormHotel):
    class Meta:
        model = Gasto
        fields = [
            "fecha",
            "categoria",
            "proveedor",
            "descripcion",
            "importe",
            "moneda",
            "medio_pago",
            "nro_comprobante",
            "comprobante",
        ]


@login_required
@permission_required("compras.view_gasto", raise_exception=True)
def gasto_lista(request):
    hoy = timezone.localdate()
    desde = parse_date(request.GET.get("desde", "") or "") or hoy.replace(day=1)
    hasta = parse_date(request.GET.get("hasta", "") or "") or hoy
    qs = Gasto.objects.filter(hotel=request.hotel, activo=True, fecha__gte=desde, fecha__lte=hasta).select_related(
        "categoria", "proveedor"
    )
    por_categoria = qs.values("categoria__nombre").annotate(total=Sum("importe")).order_by("-total")
    if request.GET.get("formato") == "xlsx":
        return respuesta_excel(
            f"gastos_{desde}_{hasta}",
            [
                (
                    "Gastos",
                    ["Fecha", "Categoría", "Proveedor", "Descripción", "Medio", "Comprobante", "Moneda", "Importe"],
                    [
                        [
                            g.fecha,
                            str(g.categoria),
                            str(g.proveedor or ""),
                            g.descripcion,
                            g.get_medio_pago_display(),
                            g.nro_comprobante,
                            g.moneda,
                            g.importe,
                        ]
                        for g in qs
                    ],
                )
            ],
        )
    pagina = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(
        request,
        "compras/gastos.html",
        {
            "page_obj": pagina,
            "desde": desde,
            "hasta": hasta,
            "por_categoria": por_categoria,
            "total": qs.aggregate(t=Sum("importe"))["t"] or 0,
        },
    )


@login_required
@permission_required("compras.add_gasto", raise_exception=True)
def gasto_nuevo(request):
    form = GastoForm(request.POST or None, request.FILES or None, hotel=request.hotel)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            services.registrar_gasto(
                request.hotel,
                request.user,
                d["categoria"],
                d["descripcion"],
                d["importe"],
                medio_pago=d["medio_pago"],
                proveedor=d["proveedor"],
                fecha=d["fecha"],
                moneda=d["moneda"],
                nro_comprobante=d["nro_comprobante"],
                comprobante=d.get("comprobante"),
            )
            messages.success(request, "Gasto registrado.")
            return redirect("gasto_lista")
        except ValidationError as exc:
            form.add_error(None, _err(exc))
    return render(
        request, "crud/form.html", {"form": form, "titulo": "Registrar gasto", "url_lista": "/compras/gastos/"}
    )


# ----------------------------------------------------------------- Solicitudes


@login_required
@permission_required("compras.view_solicitudcompra", raise_exception=True)
def solicitud_lista(request):
    qs = SolicitudCompra.objects.filter(hotel=request.hotel, activo=True).select_related("solicitante")
    return render(
        request,
        "compras/solicitudes.html",
        {"solicitudes": qs[:100], "proveedores": Proveedor.objects.filter(hotel=request.hotel, activo=True)},
    )


@login_required
@permission_required("compras.add_solicitudcompra", raise_exception=True)
def solicitud_nueva(request):
    if request.method == "POST":
        items = _leer_items(request.POST, request.hotel, con_precio=False)
        if not items:
            messages.error(request, "Agregue al menos un producto.")
        else:
            with transaction.atomic():
                s = SolicitudCompra.objects.create(
                    hotel=request.hotel,
                    solicitante=request.user,
                    area=request.POST.get("area", ""),
                    motivo=request.POST.get("motivo", ""),
                )
                for prod, cant, _ in items:
                    ItemSolicitud.objects.create(hotel=request.hotel, solicitud=s, producto=prod, cantidad=cant)
            messages.success(request, f"Solicitud #{s.pk} creada.")
            return redirect("solicitud_lista")
    return render(
        request,
        "compras/items_form.html",
        {
            "titulo": "Nueva solicitud de compra",
            "productos": Producto.objects.filter(hotel=request.hotel, activo=True),
            "filas": range(FILAS_ITEMS),
            "con_precio": False,
            "solicitud": True,
        },
    )


@login_required
@permission_required("compras.change_solicitudcompra", raise_exception=True)
@require_POST
def solicitud_accion(request, pk):
    s = get_object_or_404(SolicitudCompra, pk=pk, hotel=request.hotel)
    accion = request.POST.get("accion")
    try:
        if accion in ("aprobar", "rechazar"):
            services.aprobar_solicitud(s, aprobar=accion == "aprobar")
            messages.success(request, "Solicitud actualizada.")
        elif accion == "orden":
            prov = get_object_or_404(Proveedor, pk=request.POST.get("proveedor"), hotel=request.hotel)
            oc = services.orden_desde_solicitud(s, prov, request.user)
            messages.success(request, f"Orden de compra #{oc.pk} generada.")
            return redirect("orden_detalle", oc.pk)
    except ValidationError as exc:
        messages.error(request, _err(exc))
    return redirect("solicitud_lista")


# ----------------------------------------------------------------- Órdenes de compra


@login_required
@permission_required("compras.view_ordencompra", raise_exception=True)
def orden_lista(request):
    qs = OrdenCompra.objects.filter(hotel=request.hotel, activo=True).select_related("proveedor")
    estado = request.GET.get("estado", "")
    if estado:
        qs = qs.filter(estado=estado)
    pagina = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(
        request, "compras/ordenes.html", {"page_obj": pagina, "estado": estado, "estados": OrdenCompra.Estado.choices}
    )


@login_required
@permission_required("compras.add_ordencompra", raise_exception=True)
def orden_nueva(request):
    hotel = request.hotel
    if request.method == "POST":
        prov = Proveedor.objects.filter(hotel=hotel, activo=True, pk=request.POST.get("proveedor")).first()
        dep = Deposito.objects.filter(hotel=hotel, activo=True, pk=request.POST.get("deposito")).first()
        items = _leer_items(request.POST, hotel)
        if not prov or not dep or not items:
            messages.error(request, "Indique proveedor, depósito y al menos un ítem.")
        else:
            with transaction.atomic():
                oc = OrdenCompra.objects.create(
                    hotel=hotel,
                    proveedor=prov,
                    deposito=dep,
                    creado_por=request.user,
                    observaciones=request.POST.get("observaciones", ""),
                )
                for prod, cant, precio in items:
                    ItemCompra.objects.create(
                        hotel=hotel, orden=oc, producto=prod, cantidad=cant, precio_unitario=precio
                    )
            messages.success(request, f"Orden #{oc.pk} creada.")
            return redirect("orden_detalle", oc.pk)
    return render(
        request,
        "compras/items_form.html",
        {
            "titulo": "Nueva orden de compra",
            "productos": Producto.objects.filter(hotel=hotel, activo=True),
            "proveedores": Proveedor.objects.filter(hotel=hotel, activo=True),
            "depositos": Deposito.objects.filter(hotel=hotel, activo=True),
            "filas": range(FILAS_ITEMS),
            "con_precio": True,
        },
    )


@login_required
@permission_required("compras.view_ordencompra", raise_exception=True)
def orden_detalle(request, pk):
    oc = get_object_or_404(OrdenCompra.objects.select_related("proveedor", "deposito"), pk=pk, hotel=request.hotel)
    items = oc.items.filter(activo=True).select_related("producto")
    comparacion = {i.producto_id: services.comparar_precios(i.producto) for i in items}
    return render(
        request,
        "compras/orden_detalle.html",
        {
            "oc": oc,
            "items": items,
            "comparacion": comparacion,
            "pagos": oc.pagos.filter(activo=True),
            "hoy": timezone.localdate(),
        },
    )


@login_required
@permission_required("compras.change_ordencompra", raise_exception=True)
@require_POST
def orden_accion(request, pk):
    oc = get_object_or_404(OrdenCompra, pk=pk, hotel=request.hotel)
    accion = request.POST.get("accion")
    try:
        if accion == "enviar":
            services.enviar_orden(oc)
            messages.success(request, "Orden enviada al proveedor.")
        elif accion == "recibir":
            cantidades = {i.pk: _dec(request.POST.get(f"recibir_{i.pk}")) for i in oc.items.filter(activo=True)}
            services.recibir(oc, cantidades, request.user)
            messages.success(request, "Recepción registrada: el stock se actualizó.")
        elif accion == "factura":
            services.registrar_factura_proveedor(
                oc,
                request.POST.get("numero", ""),
                parse_date(request.POST.get("fecha", "")) or timezone.localdate(),
                _dec(request.POST.get("importe")) or oc.total,
                request.FILES.get("archivo"),
            )
            messages.success(request, "Factura del proveedor registrada.")
        elif accion == "pagar":
            services.pagar_orden(
                oc,
                request.user,
                request.POST.get("medio_pago", "transferencia"),
                _dec(request.POST.get("importe")) if request.POST.get("importe") else None,
            )
            messages.success(request, "Pago registrado como egreso.")
        elif accion == "anular" and oc.estado in (OrdenCompra.Estado.BORRADOR, OrdenCompra.Estado.ENVIADA):
            oc.estado = OrdenCompra.Estado.ANULADA
            oc.save()
            messages.success(request, "Orden anulada.")
    except ValidationError as exc:
        messages.error(request, _err(exc))
    return redirect("orden_detalle", pk)


@login_required
@permission_required("compras.view_ordencompra", raise_exception=True)
def comparar_precios(request):
    productos = Producto.objects.filter(hotel=request.hotel, activo=True)
    producto = productos.filter(pk=request.GET.get("producto") or 0).first()
    filas = services.comparar_precios(producto) if producto else []
    return render(request, "compras/comparar.html", {"productos": productos, "producto": producto, "filas": filas})

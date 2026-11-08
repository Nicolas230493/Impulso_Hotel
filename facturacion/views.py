import base64
from io import BytesIO

import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.exportar import respuesta_pdf

from . import services
from .models import Factura


def _err(exc):
    return " ".join(getattr(exc, "messages", [str(exc)]))


@login_required
@permission_required("facturacion.view_factura", raise_exception=True)
def lista(request):
    qs = Factura.objects.filter(hotel=request.hotel, activo=True).select_related("punto_venta", "reserva")
    estado = request.GET.get("estado", "")
    if estado:
        qs = qs.filter(estado=estado)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(receptor_nombre__icontains=q) | qs.filter(receptor_doc_nro__icontains=q)
    pagina = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(
        request,
        "facturacion/lista.html",
        {
            "page_obj": pagina,
            "estado": estado,
            "q": q,
            "estados": Factura.Estado.choices,
            "pendientes": Factura.objects.filter(hotel=request.hotel, estado=Factura.Estado.PENDIENTE).count(),
            "modo": settings.ARCA_MODO,
        },
    )


def _qr_base64(factura):
    img = qrcode.make(services.qr_arca(factura), box_size=4, border=1)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


@login_required
@permission_required("facturacion.view_factura", raise_exception=True)
def detalle(request, pk):
    f = get_object_or_404(
        Factura.objects.select_related("punto_venta", "reserva", "factura_asociada"), pk=pk, hotel=request.hotel
    )
    ctx = {
        "f": f,
        "items": f.items.filter(activo=True),
        "hotel": request.hotel,
        "qr": _qr_base64(f) if f.cae else None,
        "notas": f.notas_credito.all(),
        "modo": settings.ARCA_MODO,
    }
    if request.GET.get("formato") == "pdf":
        return respuesta_pdf(
            f"{f.get_tipo_display()}_{f.numero_formateado}".replace(" ", "_"),
            "facturacion/factura_pdf.html",
            ctx,
            request,
        )
    return render(request, "facturacion/detalle.html", ctx)


@login_required
@permission_required("facturacion.emitir_factura", raise_exception=True)
@require_POST
def emitir(request, pk):
    f = get_object_or_404(Factura, pk=pk, hotel=request.hotel)
    try:
        f = services.emitir(f)
        if f.estado == Factura.Estado.AUTORIZADA:
            messages.success(request, f"Comprobante autorizado. CAE {f.cae}.")
        else:
            messages.warning(request, f"{f.get_estado_display()}: {f.observaciones_arca}")
    except ValidationError as exc:
        messages.error(request, _err(exc))
    return redirect("factura_detalle", pk)


@login_required
@permission_required("facturacion.emitir_factura", raise_exception=True)
@require_POST
def nota_credito(request, pk):
    f = get_object_or_404(Factura, pk=pk, hotel=request.hotel)
    try:
        nc = services.nota_credito(f, request.POST.get("motivo", ""), request.POST.get("importe") or None)
        messages.success(request, "Nota de crédito generada y enviada a ARCA.")
        return redirect("factura_detalle", nc.pk)
    except ValidationError as exc:
        messages.error(request, _err(exc))
    return redirect("factura_detalle", pk)


@login_required
@permission_required("facturacion.emitir_factura", raise_exception=True)
@require_POST
def anular(request, pk):
    f = get_object_or_404(Factura, pk=pk, hotel=request.hotel)
    try:
        services.anular_borrador(f)
        messages.success(request, "Borrador anulado: los cargos quedaron disponibles para facturar.")
    except ValidationError as exc:
        messages.error(request, _err(exc))
    return redirect("factura_detalle", pk)


@login_required
@permission_required("facturacion.emitir_factura", raise_exception=True)
@require_POST
def reintentar_todas(request):
    n = services.reintentar_pendientes()
    messages.info(request, f"Reintento ejecutado: {n} comprobante/s autorizados.")
    return redirect("factura_lista")

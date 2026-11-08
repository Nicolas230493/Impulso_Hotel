from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Avg, Count, Max, Min

from inventario import services as inv

from .models import CategoriaGasto, Gasto, ItemCompra, OrdenCompra, SolicitudCompra

OC = OrdenCompra.Estado


@transaction.atomic
def registrar_gasto(
    hotel,
    usuario,
    categoria,
    descripcion,
    importe,
    medio_pago="transferencia",
    proveedor=None,
    fecha=None,
    moneda="ARS",
    nro_comprobante="",
    comprobante=None,
    orden_compra=None,
):
    """Registra un egreso. Si es en efectivo, sale de la caja abierta del usuario."""
    from caja import services as caja_services
    from caja.models import MovimientoCaja

    importe = Decimal(importe)
    if importe <= 0:
        raise ValidationError("El importe debe ser mayor a cero.")
    caja = None
    if medio_pago == "efectivo":
        caja = caja_services.caja_abierta(usuario, hotel)
        if caja is None:
            raise ValidationError("Para registrar un gasto en efectivo debe tener una caja abierta.")
    kwargs = {"fecha": fecha} if fecha else {}
    gasto = Gasto.objects.create(
        hotel=hotel,
        categoria=categoria,
        descripcion=descripcion,
        importe=importe,
        medio_pago=medio_pago,
        proveedor=proveedor,
        moneda=moneda,
        nro_comprobante=nro_comprobante,
        orden_compra=orden_compra,
        creado_por=usuario,
        **kwargs,
    )
    if comprobante:
        gasto.comprobante = comprobante
        gasto.save(update_fields=["comprobante"])
    if caja is not None:
        caja_services.registrar_movimiento(
            caja,
            MovimientoCaja.Tipo.EGRESO,
            importe,
            f"Gasto: {descripcion}",
            moneda=moneda,
            gasto=gasto,
            usuario=usuario,
        )
    return gasto


def aprobar_solicitud(solicitud, aprobar=True):
    if solicitud.estado != SolicitudCompra.Estado.PENDIENTE:
        raise ValidationError("La solicitud ya fue procesada.")
    solicitud.estado = SolicitudCompra.Estado.APROBADA if aprobar else SolicitudCompra.Estado.RECHAZADA
    solicitud.save(update_fields=["estado", "actualizado_en"])
    return solicitud


@transaction.atomic
def orden_desde_solicitud(solicitud, proveedor, usuario=None):
    if solicitud.estado != SolicitudCompra.Estado.APROBADA:
        raise ValidationError("Solo se generan órdenes desde solicitudes aprobadas.")
    orden = OrdenCompra.objects.create(
        hotel=solicitud.hotel,
        proveedor=proveedor,
        solicitud=solicitud,
        deposito=inv.deposito_por_defecto(solicitud.hotel),
        creado_por=usuario,
    )
    for item in solicitud.items.filter(activo=True):
        ultimo = ultimo_precio(item.producto, proveedor)
        ItemCompra.objects.create(
            hotel=orden.hotel,
            orden=orden,
            producto=item.producto,
            cantidad=item.cantidad,
            precio_unitario=ultimo if ultimo is not None else item.producto.costo,
        )
    solicitud.estado = SolicitudCompra.Estado.CONVERTIDA
    solicitud.save(update_fields=["estado", "actualizado_en"])
    return orden


def enviar_orden(orden):
    if orden.estado != OC.BORRADOR:
        raise ValidationError("Solo se envían órdenes en borrador.")
    if not orden.items.filter(activo=True).exists():
        raise ValidationError("La orden no tiene ítems.")
    orden.estado = OC.ENVIADA
    orden.save(update_fields=["estado", "actualizado_en"])
    return orden


@transaction.atomic
def recibir(orden, cantidades, usuario=None):
    """cantidades: {item_id: cantidad_recibida_ahora}. Ingresa el stock automáticamente."""
    orden = OrdenCompra.objects.select_for_update().get(pk=orden.pk)
    if orden.estado not in (OC.ENVIADA, OC.RECIBIDA_PARCIAL):
        raise ValidationError("La orden debe estar enviada para registrar la recepción.")
    recibido_algo = False
    for item in orden.items.filter(activo=True):
        cant = Decimal(cantidades.get(item.pk) or 0)
        if cant <= 0:
            continue
        if cant > item.pendiente:
            raise ValidationError(f"Se reciben {cant} de {item.producto} pero quedan {item.pendiente} pendientes.")
        inv.registrar_movimiento(
            item.producto,
            orden.deposito,
            "entrada",
            cant,
            motivo=f"Recepción OC #{orden.pk}",
            usuario=usuario,
            referencia=f"oc:{orden.pk}",
            costo_unitario=item.precio_unitario,
        )
        item.cantidad_recibida += cant
        item.save(update_fields=["cantidad_recibida", "actualizado_en"])
        recibido_algo = True
    if not recibido_algo:
        raise ValidationError("Indique al menos una cantidad recibida.")
    completa = all(i.pendiente <= 0 for i in orden.items.filter(activo=True))
    orden.estado = OC.RECIBIDA if completa else OC.RECIBIDA_PARCIAL
    orden.save(update_fields=["estado", "actualizado_en"])
    return orden


def registrar_factura_proveedor(orden, numero, fecha, importe, archivo=None):
    if orden.estado not in (OC.RECIBIDA, OC.RECIBIDA_PARCIAL):
        raise ValidationError("Registre la recepción antes de la factura del proveedor.")
    orden.factura_numero = numero
    orden.factura_fecha = fecha
    orden.factura_importe = Decimal(importe)
    if archivo:
        orden.factura_archivo = archivo
    orden.estado = OC.FACTURADA
    orden.save()
    return orden


@transaction.atomic
def pagar_orden(orden, usuario, medio_pago="transferencia", importe=None):
    if orden.estado != OC.FACTURADA:
        raise ValidationError("Solo se pagan órdenes con factura del proveedor registrada.")
    importe = Decimal(importe) if importe else orden.factura_importe - orden.total_pagado
    if importe <= 0:
        raise ValidationError("No hay saldo pendiente de pago.")
    categoria, _ = CategoriaGasto.objects.get_or_create(
        hotel=orden.hotel, nombre="Compras de insumos", defaults={"activo": True}
    )
    gasto = registrar_gasto(
        orden.hotel,
        usuario,
        categoria,
        f"Pago OC #{orden.pk} – factura {orden.factura_numero}",
        importe,
        medio_pago=medio_pago,
        proveedor=orden.proveedor,
        nro_comprobante=orden.factura_numero,
        orden_compra=orden,
    )
    if orden.total_pagado >= orden.factura_importe:
        orden.estado = OC.PAGADA
        orden.save(update_fields=["estado", "actualizado_en"])
    return gasto


def ultimo_precio(producto, proveedor):
    item = (
        ItemCompra.objects.filter(producto=producto, orden__proveedor=proveedor, activo=True)
        .exclude(orden__estado=OC.ANULADA)
        .order_by("-orden__fecha", "-id")
        .first()
    )
    return item.precio_unitario if item else None


def comparar_precios(producto):
    """Precio mínimo, máximo, promedio y último por proveedor para un producto."""
    filas = (
        ItemCompra.objects.filter(producto=producto, activo=True)
        .exclude(orden__estado=OC.ANULADA)
        .values("orden__proveedor__id", "orden__proveedor__razon_social")
        .annotate(
            minimo=Min("precio_unitario"),
            maximo=Max("precio_unitario"),
            promedio=Avg("precio_unitario"),
            compras=Count("id"),
            ultima=Max("orden__fecha"),
        )
    )
    resultado = []
    for f in filas:
        prov_id = f["orden__proveedor__id"]
        ultimo = (
            ItemCompra.objects.filter(producto=producto, orden__proveedor_id=prov_id, activo=True)
            .order_by("-orden__fecha", "-id")
            .first()
        )
        resultado.append({**f, "ultimo": ultimo.precio_unitario if ultimo else None})
    return sorted(resultado, key=lambda r: r["ultimo"] or Decimal("0"))

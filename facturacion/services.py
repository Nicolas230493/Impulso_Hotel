"""Emisión de comprobantes electrónicos, notas de crédito, cola de reintentos e informes de IVA."""

import base64
import json
import logging
from collections import defaultdict
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from . import arca
from .models import (
    NOTAS_CREDITO,
    CondicionIVAReceptor,
    Factura,
    ItemFactura,
    PuntoVenta,
    TipoComprobante,
    TipoDocumentoARCA,
)

logger = logging.getLogger(__name__)
CENT = Decimal("0.01")
MAX_INTENTOS = 20
LIMITE_CF_SIN_IDENTIFICAR = Decimal("10000000")  # monto a partir del cual ARCA exige identificar al consumidor final


def q(valor):
    return Decimal(valor).quantize(CENT, rounding=ROUND_HALF_UP)


def tipo_comprobante(hotel, condicion_receptor):
    """Letra según la condición fiscal del hotel y del receptor."""
    if hotel.condicion_iva != "RI":
        return TipoComprobante.FACTURA_C
    if condicion_receptor == CondicionIVAReceptor.RESPONSABLE_INSCRIPTO:
        return TipoComprobante.FACTURA_A
    if condicion_receptor == CondicionIVAReceptor.MONOTRIBUTO:
        return TipoComprobante.FACTURA_A
    return TipoComprobante.FACTURA_B


def punto_venta_para(hotel, tipo):
    qs = PuntoVenta.objects.filter(hotel=hotel, activo=True)
    for pv in qs.order_by("-por_defecto", "numero"):
        if not pv.tipos_habilitados or int(tipo) in [int(t) for t in pv.tipos_habilitados]:
            return pv
    raise ValidationError(f"No hay un punto de venta habilitado para {TipoComprobante(tipo).label}.")


_COND_HUESPED = {
    "RI": CondicionIVAReceptor.RESPONSABLE_INSCRIPTO,
    "MT": CondicionIVAReceptor.MONOTRIBUTO,
    "EX": CondicionIVAReceptor.EXENTO,
    "CF": CondicionIVAReceptor.CONSUMIDOR_FINAL,
    "EXT": CondicionIVAReceptor.CLIENTE_EXTERIOR,
}
_DOC_HUESPED = {
    "DNI": TipoDocumentoARCA.DNI,
    "PAS": TipoDocumentoARCA.PASAPORTE,
    "CUIT": TipoDocumentoARCA.CUIT,
    "CUIL": TipoDocumentoARCA.CUIL,
}


def receptor_de_reserva(reserva):
    """Datos del receptor: la cuenta corriente de la empresa si existe; si no, el titular."""
    cc = reserva.cuenta_corriente
    if cc is not None:
        return {
            "nombre": cc.razon_social,
            "doc_tipo": TipoDocumentoARCA.CUIT,
            "doc_nro": cc.cuit.replace("-", ""),
            "condicion": _COND_HUESPED.get(cc.condicion_iva, CondicionIVAReceptor.CONSUMIDOR_FINAL),
            "domicilio": cc.direccion,
        }
    h = reserva.titular
    if h.cuit:
        return {
            "nombre": h.razon_social or str(h),
            "doc_tipo": TipoDocumentoARCA.CUIT,
            "doc_nro": h.cuit.replace("-", ""),
            "condicion": _COND_HUESPED.get(h.condicion_iva, CondicionIVAReceptor.CONSUMIDOR_FINAL),
            "domicilio": h.direccion,
        }
    return {
        "nombre": h.nombre_completo,
        "doc_tipo": _DOC_HUESPED.get(h.tipo_doc, TipoDocumentoARCA.SIN_IDENTIFICAR),
        "doc_nro": h.nro_doc if h.tipo_doc in _DOC_HUESPED else "0",
        "condicion": _COND_HUESPED.get(h.condicion_iva, CondicionIVAReceptor.CONSUMIDOR_FINAL),
        "domicilio": h.direccion,
    }


def _desglosar(total, alicuota, discrimina_iva):
    total = q(total)
    if not discrimina_iva or alicuota == 0:
        return total, Decimal("0"), total
    neto = q(total / (1 + alicuota / 100))
    return neto, total - neto, total


def recalcular_totales(factura):
    discrimina = factura.letra in ("A", "B")
    neto = iva = exento = total = Decimal("0")
    for item in factura.items.filter(activo=True):
        total += item.total
        if not discrimina:
            neto += item.total
        elif item.alicuota_iva == 0:
            exento += item.total
        else:
            neto += item.neto
            iva += item.iva
    factura.neto_gravado, factura.iva, factura.exento, factura.total = neto, iva, exento, total
    factura.save()
    return factura


def agregar_item(factura, descripcion, cantidad, precio_unitario, alicuota_iva=Decimal("21")):
    total = q(Decimal(cantidad) * Decimal(precio_unitario))
    neto, iva, total = _desglosar(total, Decimal(alicuota_iva), factura.letra in ("A", "B"))
    return ItemFactura.objects.create(
        hotel=factura.hotel,
        factura=factura,
        descripcion=descripcion,
        cantidad=cantidad,
        precio_unitario=precio_unitario,
        alicuota_iva=alicuota_iva,
        neto=neto,
        iva=iva,
        total=total,
    )


@transaction.atomic
def facturar_reserva(reserva, cargos=None, emitir_ahora=True, extranjero_exento=False, receptor=None):
    """Crea la factura con los cargos aún no facturados y la envía a ARCA.

    extranjero_exento: aplica alícuota 0 al alojamiento de turistas extranjeros cuando corresponda
    (régimen de reintegro/exención vigente; validar con el contador del hotel).
    """
    from caja.models import Cargo

    hotel = reserva.hotel
    cargos = list(
        cargos
        if cargos is not None
        else reserva.cargos.filter(activo=True, factura__isnull=True).order_by("fecha", "id")
    )
    if not cargos:
        raise ValidationError("No hay cargos pendientes de facturar en esta reserva.")
    receptor = receptor or receptor_de_reserva(reserva)
    tipo = tipo_comprobante(hotel, receptor["condicion"])
    pv = punto_venta_para(hotel, tipo)
    fechas = [c.fecha for c in cargos]
    factura = Factura.objects.create(
        hotel=hotel,
        punto_venta=pv,
        tipo=tipo,
        reserva=reserva,
        receptor_nombre=receptor["nombre"],
        receptor_doc_tipo=receptor["doc_tipo"],
        receptor_doc_nro=receptor["doc_nro"] or "0",
        receptor_condicion_iva=receptor["condicion"],
        receptor_domicilio=receptor.get("domicilio", ""),
        servicio_desde=min(fechas),
        servicio_hasta=max(fechas),
    )
    # Agrupa las noches por habitación y tarifa para que la factura sea legible.
    agrupados = defaultdict(lambda: {"cantidad": Decimal("0"), "precio": None, "alicuota": None, "cargos": []})
    for c in cargos:
        if c.factura_id:
            raise ValidationError(f"El cargo «{c.concepto}» ya fue facturado.")
        alicuota = Decimal("0") if (extranjero_exento and c.origen == Cargo.Origen.NOCHE) else c.alicuota_iva
        if c.origen == Cargo.Origen.NOCHE:
            clave = (
                f"Alojamiento hab. {c.detalle.habitacion}" if c.detalle_id else "Alojamiento",
                c.precio_unitario,
                alicuota,
            )
        else:
            clave = (c.concepto, c.precio_unitario, alicuota, c.pk)
        g = agrupados[clave]
        g["cantidad"] += c.cantidad
        g["precio"], g["alicuota"] = c.precio_unitario, alicuota
        g["cargos"].append(c)
    for clave, g in agrupados.items():
        descripcion = clave[0] + (f" ({int(g['cantidad'])} noches)" if clave[0].startswith("Alojamiento") else "")
        agregar_item(factura, descripcion, g["cantidad"], g["precio"], g["alicuota"])
        Cargo.objects.filter(pk__in=[c.pk for c in g["cargos"]]).update(factura=factura)
    recalcular_totales(factura)
    if factura.total <= 0:
        raise ValidationError("El total a facturar debe ser mayor a cero.")
    if receptor["doc_tipo"] == TipoDocumentoARCA.SIN_IDENTIFICAR and factura.total >= LIMITE_CF_SIN_IDENTIFICAR:
        raise ValidationError("Para este importe ARCA exige identificar al receptor (DNI o CUIT).")
    if emitir_ahora:
        transaction.on_commit(lambda: emitir(Factura.objects.get(pk=factura.pk)))
    return factura


@transaction.atomic
def nota_credito(factura, motivo, importe=None, emitir_ahora=True):
    """Anula total o parcialmente una factura autorizada."""
    if factura.estado != Factura.Estado.AUTORIZADA or factura.es_nota_credito:
        raise ValidationError("Solo se puede emitir nota de crédito sobre facturas autorizadas.")
    if not (motivo or "").strip():
        raise ValidationError("Indique el motivo de la nota de crédito.")
    acreditado = sum(
        (nc.total for nc in factura.notas_credito.exclude(estado__in=["anulada", "rechazada"])), Decimal("0")
    )
    disponible = factura.total - acreditado
    importe = q(importe) if importe else disponible
    if importe <= 0 or importe > disponible:
        raise ValidationError(f"El importe de la nota de crédito debe estar entre 0 y {disponible}.")
    nc = Factura.objects.create(
        hotel=factura.hotel,
        punto_venta=factura.punto_venta,
        tipo=NOTAS_CREDITO[TipoComprobante(factura.tipo)],
        reserva=factura.reserva,
        factura_asociada=factura,
        motivo=motivo.strip(),
        receptor_nombre=factura.receptor_nombre,
        receptor_doc_tipo=factura.receptor_doc_tipo,
        receptor_doc_nro=factura.receptor_doc_nro,
        receptor_condicion_iva=factura.receptor_condicion_iva,
        receptor_domicilio=factura.receptor_domicilio,
        servicio_desde=factura.servicio_desde,
        servicio_hasta=factura.servicio_hasta,
        moneda=factura.moneda,
        cotizacion=factura.cotizacion,
    )
    proporcion = importe / factura.total
    for item in factura.items.filter(activo=True):
        agregar_item(
            nc, f"{item.descripcion} (NC)", item.cantidad, q(item.precio_unitario * proporcion), item.alicuota_iva
        )
    recalcular_totales(nc)
    if emitir_ahora:
        transaction.on_commit(lambda: emitir(Factura.objects.get(pk=nc.pk)))
    return nc


def _datos_arca(factura, numero):
    alicuotas = defaultdict(lambda: {"base": Decimal("0"), "importe": Decimal("0")})
    if factura.letra in ("A", "B"):
        for item in factura.items.filter(activo=True).exclude(alicuota_iva=0):
            a = alicuotas[item.alicuota_iva]
            a["base"] += item.neto
            a["importe"] += item.iva
    datos = {
        "punto_venta": factura.punto_venta.numero,
        "tipo": factura.tipo,
        "numero": numero,
        "concepto": factura.concepto,
        "doc_tipo": factura.receptor_doc_tipo,
        "doc_nro": factura.receptor_doc_nro or "0",
        "fecha": factura.fecha,
        "total": factura.total,
        "neto": factura.neto_gravado,
        "exento": factura.exento,
        "iva": factura.iva,
        "moneda": "PES" if factura.moneda == "ARS" else "DOL",
        "cotizacion": factura.cotizacion,
        "condicion_iva_receptor": factura.receptor_condicion_iva,
        "servicio_desde": factura.servicio_desde or factura.fecha,
        "servicio_hasta": factura.servicio_hasta or factura.fecha,
        "vencimiento_pago": factura.fecha,
        "alicuotas": [{"alicuota": k, **v} for k, v in alicuotas.items()],
    }
    if factura.factura_asociada_id:
        a = factura.factura_asociada
        datos["asociado"] = {"tipo": a.tipo, "punto_venta": a.punto_venta.numero, "numero": a.numero, "fecha": a.fecha}
    return datos


def emitir(factura):
    """Pide el CAE a ARCA. Si ARCA no responde, deja el comprobante en cola con reintento y alerta."""
    if factura.estado == Factura.Estado.AUTORIZADA:
        return factura
    if factura.estado == Factura.Estado.ANULADA:
        raise ValidationError("El comprobante fue anulado.")
    try:
        with transaction.atomic():
            pv = PuntoVenta.objects.select_for_update().get(pk=factura.punto_venta_id)
            factura = Factura.objects.select_for_update().get(pk=factura.pk)
            cli = arca.cliente(factura.hotel)
            # La numeración se sincroniza con ARCA (último comprobante autorizado + 1).
            numero = cli.ultimo_autorizado(pv.numero, factura.tipo) + 1
            if factura.fecha < timezone.localdate() - timedelta(days=5):
                factura.fecha = timezone.localdate()
            respuesta = cli.solicitar_cae(_datos_arca(factura, numero))
            factura.numero = numero
            factura.cae = respuesta["cae"]
            factura.cae_vencimiento = respuesta["vencimiento"]
            factura.observaciones_arca = respuesta.get("observaciones", "")
            factura.estado = Factura.Estado.AUTORIZADA
            factura.simulada = cli.modo == "simulado"
            factura.intentos += 1
            factura.proximo_intento = None
            factura.save()
            return factura
    except arca.ArcaRechazo as exc:
        Factura.objects.filter(pk=factura.pk).update(
            estado=Factura.Estado.RECHAZADA, observaciones_arca=str(exc), intentos=factura.intentos + 1
        )
        _alertar(factura, f"ARCA rechazó {factura}: {exc}")
    except (arca.ArcaError, OSError, ValueError) as exc:
        intentos = factura.intentos + 1
        espera = min(2**intentos, 240)
        Factura.objects.filter(pk=factura.pk).update(
            estado=Factura.Estado.PENDIENTE,
            observaciones_arca=str(exc)[:1000],
            intentos=intentos,
            proximo_intento=timezone.now() + timedelta(minutes=espera),
        )
        logger.warning("Factura %s en cola: %s", factura.pk, exc)
        if intentos == 1 or intentos % 5 == 0:
            _alertar(factura, f"ARCA no respondió al emitir {factura}. Queda en cola (intento {intentos}).")
    factura.refresh_from_db()
    return factura


def _alertar(factura, mensaje):
    from core import roles
    from notificaciones import services as notif

    notif.notificar_roles(
        factura.hotel,
        [roles.ADMIN, roles.COMPRAS],
        "Facturación electrónica",
        mensaje,
        url=f"/facturacion/{factura.pk}/",
    )


def reintentar_pendientes():
    ahora = timezone.now()
    qs = Factura.objects.filter(estado=Factura.Estado.PENDIENTE, activo=True, intentos__lt=MAX_INTENTOS).filter(
        proximo_intento__lte=ahora
    ) | Factura.objects.filter(estado=Factura.Estado.PENDIENTE, activo=True, proximo_intento__isnull=True)
    resultados = [emitir(f) for f in qs.distinct()]
    return sum(1 for f in resultados if f.estado == Factura.Estado.AUTORIZADA)


@transaction.atomic
def anular_borrador(factura):
    if factura.cae:
        raise ValidationError("Una factura con CAE solo se anula con nota de crédito.")
    if factura.estado == Factura.Estado.PENDIENTE:
        raise ValidationError("El comprobante está en cola de ARCA: espere el resultado antes de anularlo.")
    factura.cargos.update(factura=None)
    factura.estado = Factura.Estado.ANULADA
    factura.save()
    return factura


def qr_arca(factura):
    """URL del código QR exigido por ARCA en los comprobantes impresos."""
    datos = {
        "ver": 1,
        "fecha": factura.fecha.isoformat(),
        "cuit": int((factura.hotel.cuit or "0").replace("-", "") or 0),
        "ptoVta": factura.punto_venta.numero,
        "tipoCmp": factura.tipo,
        "nroCmp": factura.numero or 0,
        "importe": float(factura.total),
        "moneda": "PES" if factura.moneda == "ARS" else "DOL",
        "ctz": float(factura.cotizacion),
        "tipoDocRec": factura.receptor_doc_tipo,
        "nroDocRec": int(factura.receptor_doc_nro or 0) if str(factura.receptor_doc_nro).isdigit() else 0,
        "tipoCodAut": "E",
        "codAut": int(factura.cae or 0),
    }
    payload = base64.b64encode(json.dumps(datos).encode()).decode()
    return f"https://www.afip.gob.ar/fe/qr/?p={payload}"


def libro_iva_ventas(hotel, desde, hasta):
    qs = (
        Factura.objects.filter(hotel=hotel, estado=Factura.Estado.AUTORIZADA, fecha__gte=desde, fecha__lte=hasta)
        .select_related("punto_venta")
        .order_by("fecha", "tipo", "numero")
    )
    filas, totales = [], defaultdict(lambda: Decimal("0"))
    for f in qs:
        signo = -1 if f.es_nota_credito else 1
        fila = {
            "factura": f,
            "neto": f.neto_gravado * signo,
            "iva": f.iva * signo,
            "exento": f.exento * signo,
            "total": f.total * signo,
        }
        filas.append(fila)
        for k in ("neto", "iva", "exento", "total"):
            totales[k] += fila[k]
    return filas, dict(totales)

"""Cuenta del huésped, pagos y caja (apertura, movimientos y cierre con arqueo)."""

from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core import auditoria
from core.models import Auditoria
from habitaciones import services as hab_services

from .models import Caja, Cargo, MovimientoCaja, Pago

CERO = Decimal("0")


# --- Cuenta del huésped ---


def cargar_noches_reserva(reserva, hasta=None):
    """Genera (idempotente) un cargo por cada noche transcurrida de cada habitación de la reserva."""
    from reservas.models import Reserva

    if reserva.estado not in (Reserva.Estado.EN_CURSO, Reserva.Estado.FINALIZADA):
        return 0
    creados = 0
    for det in reserva.detalles.filter(activo=True, vigente=True).select_related("habitacion", "tipo_habitacion"):
        limite = min(hasta or det.fecha_salida, det.fecha_salida)
        for fecha in hab_services.noches(det.fecha_entrada, limite):
            if Cargo.objects.filter(detalle=det, fecha=fecha, origen=Cargo.Origen.NOCHE, activo=True).exists():
                continue
            precio, _ = hab_services.precio_noche(det.tipo_habitacion, fecha)
            Cargo.objects.create(
                hotel=reserva.hotel,
                reserva=reserva,
                detalle=det,
                fecha=fecha,
                origen=Cargo.Origen.NOCHE,
                concepto=f"Alojamiento hab. {det.habitacion} – noche {fecha:%d/%m/%Y}",
                cantidad=Decimal("1"),
                precio_unitario=precio,
            )
            creados += 1
    return creados


def cargar_noches(fecha=None):
    """Proceso nocturno: carga la noche en curso a todas las estadías activas."""
    from reservas.models import Reserva

    fecha = fecha or timezone.localdate()
    total = 0
    for r in Reserva.objects.filter(estado=Reserva.Estado.EN_CURSO, activo=True):
        total += cargar_noches_reserva(r, hasta=fecha + timezone.timedelta(days=1))
    return total


def total_cargos(reserva):
    return reserva.cargos.filter(activo=True).aggregate(t=Sum("importe"))["t"] or CERO


def total_pagos(reserva):
    total = CERO
    for p in reserva.pagos.filter(activo=True):
        total += p.importe_ars * p.signo
    return total


def saldo(reserva):
    """Saldo real: cargos devengados menos pagos (en ARS)."""
    return total_cargos(reserva) - total_pagos(reserva)


def saldo_estimado(reserva):
    """Saldo proyectado: el mayor entre el total de la reserva y lo cargado, menos lo pagado."""
    cargos_extra = (
        reserva.cargos.filter(activo=True).exclude(origen=Cargo.Origen.NOCHE).aggregate(t=Sum("importe"))["t"] or CERO
    )
    noches = reserva.cargos.filter(activo=True, origen=Cargo.Origen.NOCHE).aggregate(t=Sum("importe"))["t"] or CERO
    return max(reserva.total, noches) + cargos_extra - total_pagos(reserva)


@transaction.atomic
def registrar_cargo(
    reserva,
    concepto,
    precio_unitario,
    cantidad=Decimal("1"),
    origen=Cargo.Origen.EXTRA,
    producto=None,
    deposito=None,
    usuario=None,
    alicuota_iva=Decimal("21"),
):
    from reservas.models import Reserva

    if reserva.estado not in (Reserva.Estado.CONFIRMADA, Reserva.Estado.EN_CURSO):
        raise ValidationError("Solo se pueden cargar consumos a reservas confirmadas o en curso.")
    cantidad = Decimal(cantidad)
    if cantidad <= 0:
        raise ValidationError("La cantidad debe ser mayor a cero.")
    if origen != Cargo.Origen.AJUSTE and Decimal(precio_unitario) < 0:
        raise ValidationError("El precio no puede ser negativo (use un ajuste).")
    cargo = Cargo.objects.create(
        hotel=reserva.hotel,
        reserva=reserva,
        concepto=concepto,
        cantidad=cantidad,
        precio_unitario=Decimal(precio_unitario),
        origen=origen,
        producto=producto,
        alicuota_iva=alicuota_iva,
        creado_por=usuario,
    )
    if producto is not None:
        from inventario import services as inv

        inv.registrar_movimiento(
            producto,
            deposito,
            "salida",
            cantidad,
            motivo=f"Consumo reserva {reserva.codigo}",
            usuario=usuario,
            referencia=f"cargo:{cargo.pk}",
        )
    return cargo


# --- Caja ---


def caja_abierta(usuario, hotel):
    return Caja.objects.filter(hotel=hotel, usuario=usuario, estado=Caja.Estado.ABIERTA, activo=True).first()


@transaction.atomic
def abrir_caja(hotel, usuario, monto_inicial=CERO, monto_inicial_usd=CERO, turno="", es_general=False):
    if es_general and not usuario.has_perm("caja.ver_caja_general"):
        raise PermissionDenied("Solo administración puede abrir la caja general.")
    if caja_abierta(usuario, hotel):
        raise ValidationError("Ya tiene una caja abierta. Ciérrela antes de abrir otra.")
    if Decimal(monto_inicial) < 0 or Decimal(monto_inicial_usd) < 0:
        raise ValidationError("El monto inicial no puede ser negativo.")
    return Caja.objects.create(
        hotel=hotel,
        usuario=usuario,
        monto_inicial=monto_inicial,
        monto_inicial_usd=monto_inicial_usd,
        turno=turno,
        es_general=es_general,
        creado_por=usuario,
    )


def _validar_caja_abierta(caja):
    if caja.estado != Caja.Estado.ABIERTA:
        raise ValidationError("La caja está cerrada: no admite movimientos.")


@transaction.atomic
def registrar_movimiento(
    caja,
    tipo,
    importe,
    concepto,
    moneda="ARS",
    medio=Pago.Medio.EFECTIVO,
    referencia="",
    pago=None,
    gasto=None,
    usuario=None,
):
    caja = Caja.objects.select_for_update().get(pk=caja.pk)
    _validar_caja_abierta(caja)
    if Decimal(importe) <= 0:
        raise ValidationError("El importe debe ser mayor a cero.")
    return MovimientoCaja.objects.create(
        hotel=caja.hotel,
        caja=caja,
        tipo=tipo,
        importe=importe,
        moneda=moneda,
        medio=medio,
        concepto=concepto,
        referencia=referencia,
        pago=pago,
        gasto=gasto,
        creado_por=usuario,
    )


@transaction.atomic
def registrar_pago(
    reserva, medio, importe, usuario, moneda="ARS", tipo_cambio=Decimal("1"), tipo=Pago.Tipo.PAGO, referencia=""
):
    importe = Decimal(importe)
    tipo_cambio = Decimal(tipo_cambio or 1)
    if importe <= 0:
        raise ValidationError("El importe debe ser mayor a cero.")
    if moneda not in ("ARS", "USD"):
        raise ValidationError("Moneda no admitida.")
    if moneda == "USD" and tipo_cambio <= 1:
        raise ValidationError("Indique el tipo de cambio del día para pagos en USD.")
    if medio == Pago.Medio.CUENTA_CORRIENTE:
        raise ValidationError("La cuenta corriente no es un medio de cobro: se factura a la empresa.")
    caja = caja_abierta(usuario, reserva.hotel)
    if medio == Pago.Medio.EFECTIVO and caja is None:
        raise ValidationError("Debe abrir su caja antes de registrar cobros o devoluciones en efectivo.")
    if tipo == Pago.Tipo.DEVOLUCION and importe * tipo_cambio > total_pagos(reserva) + Decimal("0.01"):
        raise ValidationError("La devolución no puede superar lo pagado.")
    pago = Pago.objects.create(
        hotel=reserva.hotel,
        reserva=reserva,
        medio=medio,
        tipo=tipo,
        importe=importe,
        moneda=moneda,
        tipo_cambio=tipo_cambio,
        referencia=referencia,
        caja=caja,
        creado_por=usuario,
    )
    if caja is not None:
        mov_tipo = MovimientoCaja.Tipo.EGRESO if tipo == Pago.Tipo.DEVOLUCION else MovimientoCaja.Tipo.INGRESO
        registrar_movimiento(
            caja,
            mov_tipo,
            importe,
            f"{pago.get_tipo_display()} reserva {reserva.codigo}",
            moneda=moneda,
            medio=medio,
            referencia=referencia,
            pago=pago,
            usuario=usuario,
        )
    return pago


def esperado_efectivo(caja):
    """Efectivo que debería haber en la caja, por moneda."""
    esperado = {"ARS": caja.monto_inicial, "USD": caja.monto_inicial_usd}
    for m in caja.movimientos.filter(activo=True, medio=Pago.Medio.EFECTIVO):
        signo = 1 if m.tipo == MovimientoCaja.Tipo.INGRESO else -1
        esperado[m.moneda] = esperado.get(m.moneda, CERO) + signo * m.importe
    return esperado


def resumen(caja):
    """Totales de la caja por medio de pago y moneda (ingresos − egresos)."""
    por_medio = defaultdict(lambda: CERO)
    ingresos = defaultdict(lambda: CERO)
    egresos = defaultdict(lambda: CERO)
    for m in caja.movimientos.filter(activo=True):
        clave = (m.get_medio_display(), m.moneda)
        if m.tipo == MovimientoCaja.Tipo.INGRESO:
            por_medio[clave] += m.importe
            ingresos[m.moneda] += m.importe
        else:
            por_medio[clave] -= m.importe
            egresos[m.moneda] += m.importe
    return {
        "por_medio": [{"medio": k[0], "moneda": k[1], "total": v} for k, v in sorted(por_medio.items())],
        "ingresos": dict(ingresos),
        "egresos": dict(egresos),
        "esperado": esperado_efectivo(caja),
    }


@transaction.atomic
def cerrar_caja(caja, monto_contado, usuario, monto_contado_usd=CERO, observaciones=""):
    caja = Caja.objects.select_for_update().get(pk=caja.pk)
    _validar_caja_abierta(caja)
    if caja.usuario_id != usuario.pk and not usuario.has_perm("caja.ver_caja_general"):
        raise PermissionDenied("Solo el titular o administración pueden cerrar esta caja.")
    esperado = esperado_efectivo(caja)
    caja.monto_esperado = esperado.get("ARS", CERO)
    caja.monto_esperado_usd = esperado.get("USD", CERO)
    caja.monto_contado = Decimal(monto_contado)
    caja.monto_contado_usd = Decimal(monto_contado_usd or 0)
    caja.diferencia = caja.monto_contado - caja.monto_esperado
    caja.diferencia_usd = caja.monto_contado_usd - caja.monto_esperado_usd
    caja.estado = Caja.Estado.CERRADA
    caja.cierre = timezone.now()
    caja.observaciones = observaciones
    caja.save()
    auditoria.registrar(
        Auditoria.Accion.ACCION,
        caja,
        f"Cierre de caja: esperado {caja.monto_esperado}, contado {caja.monto_contado}, "
        f"diferencia {caja.diferencia}",
    )
    if caja.diferencia != 0 or caja.diferencia_usd != 0:
        from bi import services as bi

        bi.alerta_diferencia_caja(caja)
    return caja

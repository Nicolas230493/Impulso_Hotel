"""Reglas de negocio de reservas: alta, modificación, cancelación, check-in, check-out, walk-in y no-show."""

from datetime import datetime, timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core import auditoria
from core.models import Auditoria
from habitaciones import services as hab_services
from habitaciones.models import Habitacion

from .models import DetalleReserva, Estadia, Reserva

E = Reserva.Estado


def _validar_items(hotel, entrada, salida, items, excluir_reserva=None):
    if not entrada or not salida or salida <= entrada:
        raise ValidationError("La fecha de salida debe ser posterior a la de entrada.")
    if not items:
        raise ValidationError("La reserva debe incluir al menos una habitación.")
    vistas = set()
    ocupadas = hab_services.habitaciones_ocupadas_ids(hotel, entrada, salida, excluir_reserva)
    for item in items:
        hab = item["habitacion"]
        cant = int(item.get("cantidad_huespedes") or 1)
        if hab.hotel_id != hotel.id or not hab.activo:
            raise ValidationError(f"La habitación {hab} no pertenece a este hotel.")
        if hab.pk in vistas:
            raise ValidationError(f"La habitación {hab} está repetida en la reserva.")
        vistas.add(hab.pk)
        if cant < 1:
            raise ValidationError("Cada habitación debe tener al menos un huésped.")
        if cant > hab.tipo.capacidad:
            raise ValidationError(
                f"La habitación {hab} ({hab.tipo}) admite hasta {hab.tipo.capacidad} huéspedes; se indicaron {cant}."
            )
        if hab_services.esta_bloqueada(hab, entrada, salida):
            raise ValidationError(f"La habitación {hab} está fuera de servicio en ese período.")
        if hab.pk in ocupadas:
            raise ValidationError(
                f"La habitación {hab} ya está reservada entre el {entrada:%d/%m/%Y} y el {salida:%d/%m/%Y}."
            )


def _crear_detalles(reserva, items):
    total = Decimal("0")
    for item in items:
        hab = item["habitacion"]
        subtotal, _ = hab_services.cotizar(hab.tipo, reserva.fecha_entrada, reserva.fecha_salida)
        noches = reserva.noches
        try:
            with transaction.atomic():
                DetalleReserva.objects.create(
                    hotel=reserva.hotel,
                    reserva=reserva,
                    habitacion=hab,
                    tipo_habitacion=hab.tipo,
                    fecha_entrada=reserva.fecha_entrada,
                    fecha_salida=reserva.fecha_salida,
                    tarifa_aplicada=(subtotal / noches).quantize(Decimal("0.01")),
                    subtotal=subtotal,
                    cantidad_huespedes=int(item.get("cantidad_huespedes") or 1),
                )
        except IntegrityError as exc:
            if "sin_superposicion_habitacion" in str(exc):
                raise ValidationError(f"Sobre-reserva: la habitación {hab} ya está reservada en esas fechas.") from exc
            raise
        total += subtotal
    return total


@transaction.atomic
def crear_reserva(
    hotel,
    titular,
    fecha_entrada,
    fecha_salida,
    habitaciones,
    canal=Reserva.Canal.DIRECTO,
    sena=Decimal("0"),
    observaciones="",
    estado=E.PENDIENTE,
    usuario=None,
    referencia_canal="",
    cuenta_corriente=None,
    moneda="ARS",
    permitir_pasado=False,
):
    """habitaciones: lista de dicts {"habitacion": Habitacion, "cantidad_huespedes": int}."""
    if titular.hotel_id != hotel.id:
        raise ValidationError("El huésped no pertenece a este hotel.")
    if not permitir_pasado and fecha_entrada < timezone.localdate():
        raise ValidationError("La fecha de entrada no puede ser anterior a hoy.")
    if estado not in (E.PENDIENTE, E.CONFIRMADA):
        raise ValidationError("Una reserva nueva solo puede estar pendiente o confirmada.")
    _validar_items(hotel, fecha_entrada, fecha_salida, habitaciones)
    reserva = Reserva.objects.create(
        hotel=hotel,
        titular=titular,
        fecha_entrada=fecha_entrada,
        fecha_salida=fecha_salida,
        estado=estado,
        canal=canal,
        sena=sena or Decimal("0"),
        observaciones=observaciones,
        creado_por=usuario,
        referencia_canal=referencia_canal,
        cuenta_corriente=cuenta_corriente,
        moneda=moneda,
    )
    reserva.total = _crear_detalles(reserva, habitaciones)
    if reserva.sena < 0 or reserva.sena > reserva.total:
        raise ValidationError("La seña debe estar entre 0 y el total de la reserva.")
    reserva.save(update_fields=["total", "actualizado_en"])
    if estado == E.CONFIRMADA:
        transaction.on_commit(lambda: _al_confirmar(reserva.pk))
    return reserva


@transaction.atomic
def modificar_reserva(reserva, fecha_entrada, fecha_salida, habitaciones, usuario=None, **otros):
    reserva = Reserva.objects.select_for_update().get(pk=reserva.pk)
    if reserva.estado not in (E.PENDIENTE, E.CONFIRMADA):
        raise ValidationError("Solo se pueden modificar reservas pendientes o confirmadas.")
    if fecha_entrada < timezone.localdate() and fecha_entrada != reserva.fecha_entrada:
        raise ValidationError("La fecha de entrada no puede ser anterior a hoy.")
    _validar_items(reserva.hotel, fecha_entrada, fecha_salida, habitaciones, excluir_reserva=reserva)
    reserva.detalles.filter(activo=True).update(activo=False, vigente=False)
    reserva.fecha_entrada = fecha_entrada
    reserva.fecha_salida = fecha_salida
    for campo, valor in otros.items():
        setattr(reserva, campo, valor)
    reserva.save()
    reserva.total = _crear_detalles(reserva, habitaciones)
    if reserva.sena > reserva.total:
        raise ValidationError("La seña no puede superar el total de la reserva.")
    reserva.save(update_fields=["total", "actualizado_en"])
    return reserva


def confirmar(reserva, usuario=None):
    if reserva.estado != E.PENDIENTE:
        raise ValidationError("Solo se pueden confirmar reservas pendientes.")
    reserva.estado = E.CONFIRMADA
    reserva.save(update_fields=["estado", "actualizado_en"])
    transaction.on_commit(lambda: _al_confirmar(reserva.pk))
    return reserva


def _al_confirmar(reserva_id):
    from notificaciones import services as notif

    notif.reserva_confirmada(Reserva.objects.get(pk=reserva_id))


@transaction.atomic
def cancelar(reserva, motivo, usuario=None):
    if reserva.estado not in (E.PENDIENTE, E.CONFIRMADA):
        raise ValidationError("Solo se pueden cancelar reservas pendientes o confirmadas.")
    if not (motivo or "").strip():
        raise ValidationError({"motivo": "Debe indicar el motivo de la cancelación."})
    if usuario is not None and not usuario.has_perm("reservas.cancelar_reserva"):
        raise PermissionDenied("No tiene permiso para cancelar reservas.")
    reserva.estado = E.CANCELADA
    reserva.motivo_cancelacion = motivo.strip()
    reserva.cancelada_por = usuario
    reserva.cancelada_en = timezone.now()
    reserva.save()
    reserva.detalles.update(vigente=False)
    return reserva


def _validar_fecha_checkin(reserva, hoy):
    tol = timedelta(days=reserva.hotel.tolerancia_checkin_dias)
    if hoy < reserva.fecha_entrada - tol or hoy > reserva.fecha_entrada + tol:
        raise ValidationError(
            f"El check-in de esta reserva corresponde al {reserva.fecha_entrada:%d/%m/%Y} "
            f"(tolerancia de {reserva.hotel.tolerancia_checkin_dias} día/s)."
        )
    if hoy >= reserva.fecha_salida:
        raise ValidationError("La fecha de salida de la reserva ya pasó.")


@transaction.atomic
def checkin(reserva, usuario=None, detalles=None, acompanantes=None, confirmar_sucia=False, ahora=None):
    """Registra el ingreso. acompanantes: {detalle_id: [Huesped, ...]}."""
    ahora = ahora or timezone.now()
    hoy = timezone.localdate(ahora)
    reserva = Reserva.objects.select_for_update().get(pk=reserva.pk)
    if reserva.estado not in (E.CONFIRMADA, E.EN_CURSO):
        raise ValidationError("El check-in exige una reserva confirmada.")
    _validar_fecha_checkin(reserva, hoy)
    pendientes = reserva.detalles.filter(activo=True, vigente=True, estadia__isnull=True).select_related("habitacion")
    if detalles is not None:
        pendientes = pendientes.filter(pk__in=[d.pk for d in detalles])
    pendientes = list(pendientes)
    if not pendientes:
        raise ValidationError("No hay habitaciones pendientes de check-in en esta reserva.")
    acompanantes = acompanantes or {}
    for det in pendientes:
        hab = Habitacion.objects.select_for_update().get(pk=det.habitacion_id)
        if hab.estado == Habitacion.Estado.FUERA_SERVICIO:
            raise ValidationError(f"La habitación {hab} está fuera de servicio.")
        if hab.estado == Habitacion.Estado.OCUPADA:
            raise ValidationError(f"La habitación {hab} figura ocupada.")
        if hab.estado == Habitacion.Estado.SUCIA and not confirmar_sucia:
            raise ValidationError(
                f"Atención: la habitación {hab} está sucia. Confirme para continuar igualmente.",
                code="habitacion_sucia",
            )
        extra = list(acompanantes.get(det.pk, []))
        if 1 + len(extra) > hab.tipo.capacidad:
            raise ValidationError(f"La habitación {hab} admite hasta {hab.tipo.capacidad} huéspedes.")
        estadia = Estadia.objects.create(
            hotel=reserva.hotel,
            reserva=reserva,
            detalle=det,
            habitacion=hab,
            hora_real_entrada=ahora,
            registrado_entrada_por=usuario,
        )
        if extra:
            estadia.acompanantes.set(extra)
        hab.estado = Habitacion.Estado.OCUPADA
        hab.save(update_fields=["estado", "actualizado_en"])
    reserva.estado = E.EN_CURSO
    reserva.save(update_fields=["estado", "actualizado_en"])
    auditoria.registrar(Auditoria.Accion.ACCION, reserva, f"Check-in de {len(pendientes)} habitación/es")
    from caja import services as caja_services

    caja_services.cargar_noches_reserva(reserva, hasta=hoy + timedelta(days=1))
    return reserva


@transaction.atomic
def checkout(reserva, usuario=None, autorizar_saldo=False, facturar=False, ahora=None):
    from caja import services as caja_services

    ahora = ahora or timezone.now()
    hoy = timezone.localdate(ahora)
    reserva = Reserva.objects.select_for_update().get(pk=reserva.pk)
    if reserva.estado != E.EN_CURSO:
        raise ValidationError("Solo se puede hacer check-out de una reserva en curso.")
    # Salida anticipada: se acorta la reserva y se libera la habitación desde hoy.
    if hoy < reserva.fecha_salida:
        nueva_salida = max(hoy, reserva.fecha_entrada + timedelta(days=1))
        if nueva_salida < reserva.fecha_salida:
            reserva.fecha_salida = nueva_salida
            total = Decimal("0")
            for det in reserva.detalles.filter(activo=True, vigente=True):
                det.fecha_salida = nueva_salida
                det.subtotal, _ = hab_services.cotizar(det.tipo_habitacion, det.fecha_entrada, nueva_salida)
                det.save()
                total += det.subtotal
            reserva.total = total
    caja_services.cargar_noches_reserva(reserva, hasta=reserva.fecha_salida)
    saldo = caja_services.saldo(reserva)
    if saldo > Decimal("0.009") and reserva.cuenta_corriente_id is None:
        if not autorizar_saldo:
            raise ValidationError(
                f"La cuenta tiene un saldo pendiente de $ {saldo:,.2f}. Cobre o autorice la salida.",
                code="saldo_pendiente",
            )
        if usuario is not None and not usuario.has_perm("reservas.autorizar_checkout_con_saldo"):
            raise PermissionDenied("No tiene permiso para autorizar un check-out con saldo pendiente.")
        reserva.checkout_autorizado_por = usuario
    for estadia in reserva.estadias.filter(hora_real_salida__isnull=True).select_related("habitacion"):
        estadia.hora_real_salida = ahora
        estadia.registrado_salida_por = usuario
        estadia.save(update_fields=["hora_real_salida", "registrado_salida_por", "actualizado_en"])
        hab = estadia.habitacion
        hab.estado = Habitacion.Estado.SUCIA
        hab.save(update_fields=["estado", "actualizado_en"])
        from limpieza.services import crear_tarea_por_checkout

        crear_tarea_por_checkout(hab)
    reserva.estado = E.FINALIZADA
    reserva.save()
    auditoria.registrar(Auditoria.Accion.ACCION, reserva, f"Check-out (saldo {saldo:.2f})")
    if facturar:
        transaction.on_commit(lambda: _facturar_al_salir(reserva.pk))
    return reserva


def _facturar_al_salir(reserva_id):
    from facturacion import services as fact

    fact.facturar_reserva(Reserva.objects.get(pk=reserva_id))


@transaction.atomic
def walk_in(
    hotel,
    titular,
    fecha_salida,
    habitaciones,
    usuario=None,
    canal=Reserva.Canal.DIRECTO,
    acompanantes=None,
    confirmar_sucia=False,
    observaciones="",
):
    """Reserva + check-in en un solo paso."""
    hoy = timezone.localdate()
    reserva = crear_reserva(
        hotel,
        titular,
        hoy,
        fecha_salida,
        habitaciones,
        canal=canal,
        estado=E.CONFIRMADA,
        usuario=usuario,
        observaciones=observaciones,
    )
    return checkin(reserva, usuario=usuario, acompanantes=acompanantes, confirmar_sucia=confirmar_sucia)


def marcar_no_shows(ahora=None):
    """Marca no-show las reservas confirmadas sin check-in pasada la hora límite; vence las pendientes."""
    from core.models import Hotel

    ahora = ahora or timezone.now()
    local = timezone.localtime(ahora)
    hoy = local.date()
    total = 0
    for hotel in Hotel.objects.filter(activo=True):
        limite_hoy = local.time() >= hotel.hora_limite_noshow
        qs = Reserva.objects.filter(hotel=hotel, activo=True, estado__in=[E.CONFIRMADA, E.PENDIENTE])
        candidatas = qs.filter(fecha_entrada__lt=hoy) | (qs.filter(fecha_entrada=hoy) if limite_hoy else qs.none())
        for r in candidatas.distinct():
            if r.estadias.exists():
                continue
            if r.estado == E.CONFIRMADA:
                r.estado = E.NO_SHOW
            else:
                r.estado = E.CANCELADA
                r.motivo_cancelacion = "Vencida sin confirmar (proceso automático)."
                r.cancelada_en = ahora
            r.save()
            r.detalles.update(vigente=False)
            total += 1
    return total


def llegadas_del_dia(hotel, fecha=None):
    fecha = fecha or timezone.localdate()
    return (
        Reserva.objects.filter(hotel=hotel, activo=True, fecha_entrada=fecha, estado__in=[E.PENDIENTE, E.CONFIRMADA])
        .select_related("titular")
        .prefetch_related("detalles__habitacion")
    )


def salidas_del_dia(hotel, fecha=None):
    fecha = fecha or timezone.localdate()
    return (
        Reserva.objects.filter(hotel=hotel, activo=True, fecha_salida__lte=fecha, estado=E.EN_CURSO)
        .select_related("titular")
        .prefetch_related("detalles__habitacion")
    )


def en_casa(hotel):
    return Reserva.objects.filter(hotel=hotel, activo=True, estado=E.EN_CURSO).select_related("titular")


def combinar(fecha, hora):
    return timezone.make_aware(datetime.combine(fecha, hora))

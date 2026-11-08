"""Precios, disponibilidad y cambios de estado de habitaciones."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.utils import timezone

from core import auditoria
from core.models import Auditoria

from .models import BloqueoHabitacion, Habitacion, Tarifa


def noches(desde, hasta):
    """Fechas de cada noche entre desde (inclusive) y hasta (exclusiva)."""
    return [desde + timedelta(days=i) for i in range((hasta - desde).days)]


def precio_noche(tipo, fecha):
    """Tarifa vigente para la fecha: la de temporada más específica (rango más corto); si no, el precio base."""
    tarifas = Tarifa.objects.filter(tipo_habitacion=tipo, activo=True, fecha_desde__lte=fecha, fecha_hasta__gte=fecha)
    mejor = None
    for t in tarifas:
        if mejor is None or (t.fecha_hasta - t.fecha_desde) < (mejor.fecha_hasta - mejor.fecha_desde):
            mejor = t
    if mejor is not None:
        return mejor.precio_noche, mejor
    return tipo.precio_base, None


def cotizar(tipo, desde, hasta):
    """Devuelve (total, detalle por noche) para un tipo de habitación en el rango."""
    if hasta <= desde:
        raise ValidationError("La fecha de salida debe ser posterior a la de entrada.")
    detalle = []
    total = Decimal("0")
    for fecha in noches(desde, hasta):
        precio, tarifa = precio_noche(tipo, fecha)
        detalle.append({"fecha": fecha, "precio": precio, "tarifa": tarifa})
        total += precio
    return total, detalle


def bloqueos_en_rango(desde, hasta):
    """Filtro Q de bloqueos que se superponen con las noches [desde, hasta)."""
    return Q(activo=True, fecha_desde__lt=hasta) & (Q(fecha_hasta__isnull=True) | Q(fecha_hasta__gte=desde))


def esta_bloqueada(habitacion, desde, hasta):
    return BloqueoHabitacion.objects.filter(bloqueos_en_rango(desde, hasta), habitacion=habitacion).exists()


def habitaciones_ocupadas_ids(hotel, desde, hasta, excluir_reserva=None):
    from reservas.models import DetalleReserva

    qs = DetalleReserva.objects.filter(hotel=hotel, vigente=True, fecha_entrada__lt=hasta, fecha_salida__gt=desde)
    if excluir_reserva is not None:
        qs = qs.exclude(reserva=excluir_reserva)
    return set(qs.values_list("habitacion_id", flat=True))


def habitaciones_disponibles(hotel, desde, hasta, tipo=None, excluir_reserva=None, huespedes=None):
    if hasta <= desde:
        raise ValidationError("La fecha de salida debe ser posterior a la de entrada.")
    qs = Habitacion.objects.filter(hotel=hotel, activo=True).select_related("tipo")
    if tipo is not None:
        qs = qs.filter(tipo=tipo)
    if huespedes:
        qs = qs.filter(tipo__capacidad__gte=huespedes)
    ocupadas = habitaciones_ocupadas_ids(hotel, desde, hasta, excluir_reserva)
    bloqueadas = set(
        BloqueoHabitacion.objects.filter(bloqueos_en_rango(desde, hasta), hotel=hotel).values_list(
            "habitacion_id", flat=True
        )
    )
    return qs.exclude(pk__in=ocupadas | bloqueadas)


def cambiar_estado(habitacion, nuevo, usuario=None, motivo=""):
    """Cambio manual de estado con control de permisos por rol."""
    E = Habitacion.Estado
    anterior = habitacion.estado
    if usuario is not None:
        if nuevo == E.LIMPIA and not usuario.has_perm("habitaciones.marcar_limpia"):
            raise PermissionDenied("No tiene permiso para marcar habitaciones como limpias.")
        if E.FUERA_SERVICIO in (nuevo, anterior) and not usuario.has_perm("habitaciones.cambiar_fuera_servicio"):
            raise PermissionDenied("No tiene permiso para cambiar el estado fuera de servicio.")
        if (
            nuevo not in (E.LIMPIA, E.FUERA_SERVICIO)
            and anterior != E.FUERA_SERVICIO
            and not usuario.has_perm("habitaciones.change_habitacion")
        ):
            raise PermissionDenied("No tiene permiso para cambiar el estado de la habitación.")
    if nuevo == E.LIMPIA and anterior == E.OCUPADA:
        raise ValidationError("La habitación está ocupada: se mantiene ocupada aunque se haya repasado.")
    hoy = timezone.localdate()
    if nuevo == E.FUERA_SERVICIO and anterior != E.FUERA_SERVICIO:
        if anterior == E.OCUPADA:
            raise ValidationError("No se puede poner fuera de servicio una habitación ocupada.")
        BloqueoHabitacion.objects.create(
            hotel=habitacion.hotel, habitacion=habitacion, fecha_desde=hoy, motivo=motivo or "Fuera de servicio"
        )
    elif anterior == E.FUERA_SERVICIO and nuevo != E.FUERA_SERVICIO:
        liberar_bloqueos(habitacion)
    habitacion.estado = nuevo
    habitacion.save(update_fields=["estado", "actualizado_en"])
    auditoria.registrar(Auditoria.Accion.ACCION, habitacion, f"Estado {anterior} → {nuevo}. {motivo}".strip())
    return habitacion


def liberar_bloqueos(habitacion, incidencia=None):
    """Cierra los bloqueos vigentes de la habitación a partir de hoy."""
    hoy = timezone.localdate()
    qs = BloqueoHabitacion.objects.filter(
        Q(fecha_hasta__isnull=True) | Q(fecha_hasta__gte=hoy),
        habitacion=habitacion,
        activo=True,
        fecha_desde__lte=hoy,
    )
    if incidencia is not None:
        qs = qs.filter(incidencia=incidencia)
    for b in qs:
        if b.fecha_desde >= hoy:
            b.activo = False
            b.save(update_fields=["activo", "actualizado_en"])
        else:
            b.fecha_hasta = hoy - timedelta(days=1)
            b.save(update_fields=["fecha_hasta", "actualizado_en"])


def estado_visual(habitacion, llegadas_hoy_ids):
    """Estado para el mapa: muestra 'reservada' si hay una llegada hoy a una habitación libre o limpia."""
    E = Habitacion.Estado
    if habitacion.estado in (E.LIBRE, E.LIMPIA) and habitacion.pk in llegadas_hoy_ids:
        return E.RESERVADA
    return habitacion.estado

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from habitaciones.models import Habitacion
from reservas.models import Reserva

from .models import ChecklistItem, TareaLimpieza

T = TareaLimpieza


def generar_tareas(hotel, fecha=None):
    """Salida del día → limpieza completa; habitación ocupada que sigue → repaso. Idempotente."""
    fecha = fecha or timezone.localdate()
    creadas = 0
    llegadas = set(
        Reserva.objects.filter(
            hotel=hotel,
            fecha_entrada=fecha,
            activo=True,
            estado__in=[Reserva.Estado.CONFIRMADA, Reserva.Estado.PENDIENTE],
        ).values_list("detalles__habitacion_id", flat=True)
    )
    salidas = set(
        Reserva.objects.filter(
            hotel=hotel,
            fecha_salida=fecha,
            activo=True,
            estado__in=[Reserva.Estado.EN_CURSO, Reserva.Estado.FINALIZADA],
        ).values_list("detalles__habitacion_id", flat=True)
    )
    for hab in Habitacion.objects.filter(hotel=hotel, activo=True).exclude(estado=Habitacion.Estado.FUERA_SERVICIO):
        tipo = None
        if hab.pk in salidas or hab.estado == Habitacion.Estado.SUCIA:
            tipo = T.Tipo.COMPLETA
        elif hab.estado == Habitacion.Estado.OCUPADA:
            tipo = T.Tipo.REPASO
        if tipo is None:
            continue
        if TareaLimpieza.objects.filter(habitacion=hab, fecha=fecha, activo=True).exists():
            continue
        try:
            with transaction.atomic():
                TareaLimpieza.objects.create(
                    hotel=hotel, habitacion=hab, fecha=fecha, tipo=tipo, prioridad=1 if hab.pk in llegadas else 2
                )
                creadas += 1
        except IntegrityError:
            continue
    return creadas


def crear_tarea_por_checkout(habitacion):
    """Al hacer check-out se genera de inmediato la limpieza completa."""
    hoy = timezone.localdate()
    if TareaLimpieza.objects.filter(habitacion=habitacion, fecha=hoy, tipo=T.Tipo.COMPLETA, activo=True).exists():
        return None
    TareaLimpieza.objects.filter(
        habitacion=habitacion, fecha=hoy, tipo=T.Tipo.REPASO, activo=True, estado=T.Estado.PENDIENTE
    ).update(activo=False)
    return TareaLimpieza.objects.create(
        hotel=habitacion.hotel, habitacion=habitacion, fecha=hoy, tipo=T.Tipo.COMPLETA, prioridad=1
    )


def checklist_para(tarea):
    return ChecklistItem.objects.filter(
        Q(tipo_habitacion=tarea.habitacion.tipo) | Q(tipo_habitacion__isnull=True),
        Q(tipo_tarea="") | Q(tipo_tarea=tarea.tipo),
        hotel=tarea.hotel,
        activo=True,
    )


def _validar_responsable(tarea, usuario):
    if tarea.asignada_a_id and tarea.asignada_a_id != usuario.pk and not usuario.has_perm("limpieza.add_tarealimpieza"):
        raise PermissionDenied("Esta tarea está asignada a otra persona.")


def iniciar(tarea, usuario):
    _validar_responsable(tarea, usuario)
    if tarea.estado != T.Estado.PENDIENTE:
        raise ValidationError("La tarea ya fue iniciada.")
    tarea.estado = T.Estado.EN_CURSO
    tarea.inicio = timezone.now()
    if tarea.asignada_a_id is None:
        tarea.asignada_a = usuario
    tarea.save()
    return tarea


@transaction.atomic
def terminar(tarea, usuario, checklist=None, observaciones=""):
    _validar_responsable(tarea, usuario)
    if tarea.estado != T.Estado.EN_CURSO:
        raise ValidationError("La tarea debe estar en curso para terminarla.")
    items = list(checklist_para(tarea))
    checklist = checklist or {}
    faltantes = [i.descripcion for i in items if not checklist.get(str(i.pk))]
    if faltantes:
        raise ValidationError("Complete el checklist: " + ", ".join(faltantes))
    tarea.checklist = {str(i.pk): {"item": i.descripcion, "ok": True} for i in items}
    tarea.estado = T.Estado.TERMINADA
    tarea.fin = timezone.now()
    tarea.observaciones = observaciones
    tarea.save()
    hab = Habitacion.objects.select_for_update().get(pk=tarea.habitacion_id)
    if hab.estado == Habitacion.Estado.SUCIA:
        hab.estado = Habitacion.Estado.LIMPIA
        hab.save(update_fields=["estado", "actualizado_en"])
    return tarea


def asignar(tarea, usuario_destino):
    tarea.asignada_a = usuario_destino
    tarea.save(update_fields=["asignada_a", "actualizado_en"])
    from notificaciones import services as notif

    notif.notificar_usuario(usuario_destino, "Nueva tarea de limpieza", str(tarea), url="/limpieza/mis-tareas/")
    return tarea

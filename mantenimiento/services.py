from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core import roles
from habitaciones.models import BloqueoHabitacion, Habitacion
from habitaciones import services as hab_services
from inventario import services as inv

from .models import FotoIncidencia, Incidencia, Mantenimiento, PlanPreventivo, RepuestoUsado

EI = Incidencia.Estado


def _notificar_tecnicos(incidencia, titulo):
    from notificaciones import services as notif

    url = f"/mantenimiento/incidencias/{incidencia.pk}/"
    if incidencia.asignada_a_id:
        notif.notificar_usuario(incidencia.asignada_a, titulo, str(incidencia), url=url)
    else:
        notif.notificar_roles(incidencia.hotel, [roles.MANTENIMIENTO], titulo, str(incidencia), url=url)


def _bloquear(incidencia):
    hab = incidencia.habitacion_afectada
    if hab is None:
        return
    hoy = timezone.localdate()
    BloqueoHabitacion.objects.create(
        hotel=incidencia.hotel,
        habitacion=hab,
        fecha_desde=hoy,
        motivo=f"Incidencia #{incidencia.pk}: {incidencia.titulo}",
        incidencia=incidencia,
    )
    if hab.estado != Habitacion.Estado.OCUPADA:
        hab.estado = Habitacion.Estado.FUERA_SERVICIO
        hab.save(update_fields=["estado", "actualizado_en"])


@transaction.atomic
def reportar(
    hotel,
    usuario,
    titulo,
    habitacion=None,
    activo=None,
    descripcion="",
    origen=Incidencia.Origen.RECEPCION,
    categoria=Incidencia.Categoria.OTRA,
    prioridad=Incidencia.Prioridad.MEDIA,
    bloqueante=False,
    fotos=(),
):
    inc = Incidencia(
        hotel=hotel,
        creado_por=usuario,
        titulo=titulo,
        habitacion=habitacion,
        activo_relacionado=activo,
        descripcion=descripcion,
        origen=origen,
        categoria=categoria,
        prioridad=prioridad,
        bloqueante=bloqueante,
    )
    inc.full_clean(exclude=["hotel", "creado_por"])
    inc.save()
    for foto in fotos:
        FotoIncidencia.objects.create(hotel=hotel, incidencia=inc, imagen=foto)
    if bloqueante:
        _bloquear(inc)
    transaction.on_commit(lambda: _post_reporte(inc.pk))
    return inc


def _post_reporte(incidencia_id):
    inc = Incidencia.objects.get(pk=incidencia_id)
    _notificar_tecnicos(inc, "Nueva incidencia" + (" URGENTE" if inc.prioridad == 1 else ""))
    from bi import services as bi

    bi.alerta_incidencias_repetidas(inc)


def asignar(incidencia, tecnico):
    if incidencia.estado in (EI.RESUELTA, EI.CERRADA):
        raise ValidationError("La incidencia ya está resuelta.")
    incidencia.asignada_a = tecnico
    incidencia.estado = EI.ASIGNADA
    incidencia.save()
    _notificar_tecnicos(incidencia, "Incidencia asignada")
    return incidencia


@transaction.atomic
def cambiar_estado(incidencia, nuevo, usuario=None, solucion=""):
    incidencia = Incidencia.objects.select_for_update().get(pk=incidencia.pk)
    if nuevo not in Incidencia.TRANSICIONES.get(incidencia.estado, []):
        raise ValidationError(f"No se puede pasar de «{incidencia.get_estado_display()}» a «{EI(nuevo).label}».")
    ahora = timezone.now()
    if nuevo == EI.EN_CURSO and incidencia.asignada_a_id is None and usuario is not None:
        incidencia.asignada_a = usuario
    if nuevo == EI.RESUELTA:
        incidencia.resuelta_en = ahora
        if solucion:
            incidencia.solucion = solucion
    if nuevo == EI.CERRADA:
        incidencia.cerrada_en = ahora
        if incidencia.bloqueante:
            hab = incidencia.habitacion_afectada
            hab_services.liberar_bloqueos(hab, incidencia=incidencia)
            hab.refresh_from_db()
            otros = BloqueoHabitacion.objects.filter(
                hab_services.bloqueos_en_rango(timezone.localdate(), timezone.localdate() + timedelta(days=1)),
                habitacion=hab,
            ).exists()
            if hab.estado == Habitacion.Estado.FUERA_SERVICIO and not otros:
                hab.estado = Habitacion.Estado.SUCIA  # requiere limpieza antes de volver a venderse
                hab.save(update_fields=["estado", "actualizado_en"])
    incidencia.estado = nuevo
    incidencia.save()
    return incidencia


@transaction.atomic
def registrar_trabajo(
    hotel,
    usuario,
    descripcion,
    incidencia=None,
    orden=None,
    horas=0,
    costo_mano_obra=0,
    costo_externo=0,
    repuestos=(),
    fecha=None,
):
    """Registra un trabajo realizado. Los repuestos descuentan stock; el costo se imputa a habitación y activo."""
    if orden is None:
        if incidencia is None:
            raise ValidationError("Indique la incidencia o la orden preventiva.")
        orden = Mantenimiento(
            hotel=hotel,
            tipo=Mantenimiento.Tipo.CORRECTIVO,
            incidencia=incidencia,
            activo_relacionado=incidencia.activo_relacionado,
            habitacion=incidencia.habitacion_afectada,
        )
    elif orden.estado != Mantenimiento.Estado.PENDIENTE:
        raise ValidationError("La orden ya fue registrada.")
    orden.tecnico = usuario
    orden.descripcion = descripcion
    orden.horas = Decimal(horas or 0)
    orden.costo_mano_obra = Decimal(costo_mano_obra or 0)
    orden.costo_externo = Decimal(costo_externo or 0)
    orden.fecha_realizado = fecha or timezone.localdate()
    orden.estado = Mantenimiento.Estado.REALIZADO
    orden.save()
    for producto, deposito, cantidad in repuestos:
        deposito = deposito or inv.deposito_por_defecto(hotel)
        inv.registrar_movimiento(
            producto,
            deposito,
            "salida",
            cantidad,
            motivo=f"Mantenimiento #{orden.pk}",
            usuario=usuario,
            referencia=f"mant:{orden.pk}",
        )
        RepuestoUsado.objects.create(
            hotel=hotel,
            mantenimiento=orden,
            producto=producto,
            deposito=deposito,
            cantidad=cantidad,
            costo_unitario=producto.costo,
        )
    if orden.activo_relacionado_id:
        transaction.on_commit(lambda: _post_trabajo(orden.pk))
    return orden


def _post_trabajo(orden_id):
    from bi import services as bi

    bi.alerta_reemplazo_activo(Mantenimiento.objects.get(pk=orden_id).activo_relacionado)


def generar_ordenes_preventivas(fecha=None):
    fecha = fecha or timezone.localdate()
    creadas = 0
    for plan in PlanPreventivo.objects.filter(activo=True, proxima_fecha__lte=fecha).select_related(
        "activo_relacionado"
    ):
        with transaction.atomic():
            if not plan.ordenes.filter(estado=Mantenimiento.Estado.PENDIENTE, activo=True).exists():
                orden = Mantenimiento.objects.create(
                    hotel=plan.hotel,
                    tipo=Mantenimiento.Tipo.PREVENTIVO,
                    plan=plan,
                    activo_relacionado=plan.activo_relacionado,
                    habitacion=plan.activo_relacionado.habitacion,
                    tecnico=plan.responsable,
                    fecha_programada=plan.proxima_fecha,
                )
                creadas += 1
                from notificaciones import services as notif

                titulo = "Mantenimiento preventivo programado"
                if plan.responsable:
                    notif.notificar_usuario(plan.responsable, titulo, str(orden), url="/mantenimiento/ordenes/")
                else:
                    notif.notificar_roles(
                        plan.hotel, [roles.MANTENIMIENTO], titulo, str(orden), url="/mantenimiento/ordenes/"
                    )
            while plan.proxima_fecha <= fecha:
                plan.proxima_fecha += timedelta(days=plan.frecuencia_dias)
            plan.save(update_fields=["proxima_fecha", "actualizado_en"])
    return creadas

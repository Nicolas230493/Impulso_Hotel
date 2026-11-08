"""Notificaciones internas (campana), email y WhatsApp a huéspedes (solo con consentimiento registrado)."""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from core.models import Usuario
from integraciones import whatsapp

from .models import Notificacion, PlantillaMensaje

logger = logging.getLogger(__name__)
N = Notificacion

TEXTOS_POR_DEFECTO = {
    "confirmacion": "Hola {nombre}, tu reserva {codigo} en {hotel} está confirmada: ingreso {entrada}, "
    "salida {salida}. ¡Te esperamos!",
    "recordatorio": "Hola {nombre}, te recordamos que mañana {entrada} te esperamos en {hotel}. "
    "Check-in desde las {checkin}.",
    "info_ingreso": "¡Bienvenido/a {nombre}! Hoy es tu ingreso a {hotel} ({direccion}). Check-in desde las "
    "{checkin}, check-out hasta las {checkout}.",
    "encuesta": "Gracias por elegir {hotel}, {nombre}. ¿Nos contás cómo fue tu estadía? {encuesta_url}",
}


def notificar_usuario(usuario, titulo, mensaje, url="", email=False):
    hotel = usuario.hotel_activo or usuario.hoteles.first()
    if hotel is None:
        return None
    n = Notificacion.objects.create(
        hotel=hotel,
        usuario=usuario,
        canal=N.Canal.INTERNA,
        titulo=titulo[:200],
        mensaje=mensaje,
        url=url,
        estado_envio=N.EstadoEnvio.ENVIADO,
        enviado_en=timezone.now(),
    )
    if email and usuario.email:
        enviar_email(hotel, usuario.email, titulo, mensaje)
    return n


def notificar_roles(hotel, nombres_roles, titulo, mensaje, url="", email=False):
    usuarios = Usuario.objects.filter(hoteles=hotel, is_active=True, groups__name__in=nombres_roles).distinct()
    creadas = []
    for u in usuarios:
        creadas.append(
            Notificacion.objects.create(
                hotel=hotel,
                usuario=u,
                canal=N.Canal.INTERNA,
                titulo=titulo[:200],
                mensaje=mensaje,
                url=url,
                estado_envio=N.EstadoEnvio.ENVIADO,
                enviado_en=timezone.now(),
            )
        )
        if email and u.email:
            enviar_email(hotel, u.email, titulo, mensaje)
    return creadas


def enviar_email(hotel, destinatario, asunto, cuerpo, adjuntos=None, reserva=None, huesped=None):
    from django.core.mail import EmailMessage

    n = Notificacion.objects.create(
        hotel=hotel,
        canal=N.Canal.EMAIL,
        destinatario=destinatario,
        titulo=asunto[:200],
        mensaje=cuerpo,
        reserva=reserva,
        huesped=huesped,
    )
    try:
        if adjuntos:
            msg = EmailMessage(asunto, cuerpo, settings.DEFAULT_FROM_EMAIL, [destinatario])
            for nombre, contenido, mime in adjuntos:
                msg.attach(nombre, contenido, mime)
            msg.send()
        else:
            send_mail(asunto, cuerpo, settings.DEFAULT_FROM_EMAIL, [destinatario])
        n.estado_envio, n.enviado_en = N.EstadoEnvio.ENVIADO, timezone.now()
    except Exception as exc:  # noqa: BLE001 - se registra cualquier falla del servidor de correo
        n.estado_envio, n.error = N.EstadoEnvio.ERROR, str(exc)[:1000]
        logger.exception("Error enviando email a %s", destinatario)
    n.save()
    return n


def _variables(reserva):
    h = reserva.hotel
    return {
        "nombre": reserva.titular.nombre,
        "hotel": h.nombre,
        "codigo": reserva.codigo,
        "entrada": f"{reserva.fecha_entrada:%d/%m/%Y}",
        "salida": f"{reserva.fecha_salida:%d/%m/%Y}",
        "checkin": f"{h.hora_checkin:%H:%M}",
        "checkout": f"{h.hora_checkout:%H:%M}",
        "direccion": h.direccion,
        "encuesta_url": f"{h.sitio_web or ''}/encuesta/{reserva.codigo}".lstrip("/"),
    }


def enviar_whatsapp(reserva, codigo):
    """Envía un mensaje de WhatsApp al titular. Nunca sale sin consentimiento registrado. Idempotente."""
    huesped = reserva.titular
    plantilla = PlantillaMensaje.objects.filter(
        hotel=reserva.hotel, codigo=codigo, canal="whatsapp", activo=True
    ).first()
    texto = (plantilla.cuerpo if plantilla else TEXTOS_POR_DEFECTO[codigo]).format(**_variables(reserva))
    titulo = f"WhatsApp: {PlantillaMensaje.Codigo(codigo).label}"
    previo = Notificacion.objects.filter(
        reserva=reserva, canal=N.Canal.WHATSAPP, titulo=titulo, estado_envio=N.EstadoEnvio.ENVIADO
    ).first()
    if previo:
        return previo
    n = Notificacion(
        hotel=reserva.hotel,
        canal=N.Canal.WHATSAPP,
        huesped=huesped,
        reserva=reserva,
        destinatario=huesped.telefono,
        plantilla=plantilla,
        titulo=titulo,
        mensaje=texto,
    )
    if not huesped.consentimiento_whatsapp:
        n.estado_envio = N.EstadoEnvio.BLOQUEADO
        n.error = "El huésped no registró consentimiento para recibir WhatsApp."
        n.save()
        return n
    if plantilla is None or not plantilla.aprobada or not plantilla.nombre_plantilla_meta:
        if settings.WHATSAPP_MODO == "real":
            n.estado_envio = N.EstadoEnvio.ERROR
            n.error = "No hay una plantilla aprobada por Meta para este mensaje."
            n.save()
            return n
    try:
        variables = _variables(reserva)
        nombre_meta = plantilla.nombre_plantilla_meta if plantilla else codigo
        idioma = plantilla.idioma if plantilla else "es_AR"
        n.id_externo = whatsapp.enviar_plantilla(
            huesped.telefono,
            nombre_meta,
            idioma,
            [variables["nombre"], variables["hotel"], variables["entrada"], variables["salida"], variables["codigo"]],
        )
        n.estado_envio, n.enviado_en = N.EstadoEnvio.ENVIADO, timezone.now()
    except whatsapp.WhatsAppError as exc:
        n.estado_envio, n.error = N.EstadoEnvio.ERROR, str(exc)[:1000]
    n.save()
    return n


def reserva_confirmada(reserva):
    enviar_whatsapp(reserva, "confirmacion")
    if reserva.titular.email and reserva.titular.consentimiento_datos:
        v = _variables(reserva)
        enviar_email(
            reserva.hotel,
            reserva.titular.email,
            f"Reserva {reserva.codigo} confirmada – {v['hotel']}",
            TEXTOS_POR_DEFECTO["confirmacion"].format(**v),
            reserva=reserva,
            huesped=reserva.titular,
        )


def mensajes_programados(hoy=None):
    """Recordatorio (día previo), información de ingreso (día de llegada) y encuesta (día posterior a la salida)."""
    from reservas.models import Reserva

    hoy = hoy or timezone.localdate()
    enviados = 0
    for r in Reserva.objects.filter(
        activo=True, estado=Reserva.Estado.CONFIRMADA, fecha_entrada=hoy + timedelta(days=1)
    ):
        enviados += enviar_whatsapp(r, "recordatorio").estado_envio == N.EstadoEnvio.ENVIADO
    for r in Reserva.objects.filter(activo=True, estado=Reserva.Estado.CONFIRMADA, fecha_entrada=hoy):
        enviados += enviar_whatsapp(r, "info_ingreso").estado_envio == N.EstadoEnvio.ENVIADO
    for r in Reserva.objects.filter(
        activo=True, estado=Reserva.Estado.FINALIZADA, fecha_salida=hoy - timedelta(days=1)
    ):
        enviados += enviar_whatsapp(r, "encuesta").estado_envio == N.EstadoEnvio.ENVIADO
    return enviados

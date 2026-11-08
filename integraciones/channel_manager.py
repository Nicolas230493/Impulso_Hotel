"""Interfaz con el channel manager (Booking.com y otros canales). Decisión abierta: proveedor a definir.

Mientras tanto, las reservas de Booking se cargan a mano (canal "booking") o se importan con
`importar_reservas` desde un listado. Esta interfaz define el contrato que deberá implementar el proveedor elegido.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class ChannelManager:
    def publicar_disponibilidad(self, hotel, desde, hasta):
        raise NotImplementedError

    def publicar_tarifas(self, hotel, desde, hasta):
        raise NotImplementedError

    def descargar_reservas(self, hotel):
        raise NotImplementedError


class ChannelManagerSimulado(ChannelManager):
    def publicar_disponibilidad(self, hotel, desde, hasta):
        from habitaciones.models import TipoHabitacion
        from habitaciones.services import habitaciones_disponibles

        datos = {
            t.nombre: habitaciones_disponibles(hotel, desde, hasta, tipo=t).count()
            for t in TipoHabitacion.objects.filter(hotel=hotel, activo=True)
        }
        logger.info("[Channel manager simulado] disponibilidad %s %s→%s: %s", hotel, desde, hasta, datos)
        return datos

    def publicar_tarifas(self, hotel, desde, hasta):
        logger.info("[Channel manager simulado] tarifas %s %s→%s", hotel, desde, hasta)
        return {}

    def descargar_reservas(self, hotel):
        return []


def obtener():
    if settings.CHANNEL_MANAGER_MODO == "simulado":
        return ChannelManagerSimulado()
    raise NotImplementedError(f"Channel manager «{settings.CHANNEL_MANAGER_MODO}» no implementado todavía.")

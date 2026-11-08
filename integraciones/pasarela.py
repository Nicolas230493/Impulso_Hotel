"""Pasarela de cobro recurrente de suscripciones (decisión abierta: Mercado Pago, Mobbex, etc.)."""

import uuid

from django.conf import settings


class PasarelaError(Exception):
    pass


def cobrar_suscripcion(suscripcion, importe):
    """Devuelve (aprobado, id_operacion, detalle)."""
    if settings.PASARELA_MODO == "simulado":
        if getattr(suscripcion, "medio_pago_token", "") == "rechazar":
            return False, "", "Tarjeta rechazada (simulado)"
        return True, f"sim-{uuid.uuid4().hex[:10]}", "Aprobado (simulado)"
    raise PasarelaError(f"Pasarela «{settings.PASARELA_MODO}» no implementada todavía.")

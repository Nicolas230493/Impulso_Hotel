"""WhatsApp Business Cloud API (oficial de Meta). En modo simulado no envía nada."""

import logging
import uuid

import requests
from django.conf import settings

logger = logging.getLogger(__name__)
API = "https://graph.facebook.com/v21.0/{phone_id}/messages"


class WhatsAppError(Exception):
    pass


def normalizar_telefono(telefono):
    digitos = "".join(c for c in telefono or "" if c.isdigit())
    if not digitos:
        raise WhatsAppError("El huésped no tiene teléfono cargado.")
    if digitos.startswith("0"):
        digitos = "54" + digitos[1:]
    if not digitos.startswith("54") and len(digitos) == 10:
        digitos = "549" + digitos
    return digitos


def enviar_plantilla(telefono, plantilla, idioma, parametros):
    """Envía una plantilla aprobada. Devuelve el id del mensaje."""
    destino = normalizar_telefono(telefono)
    if settings.WHATSAPP_MODO != "real":
        logger.info("[WhatsApp simulado] a %s plantilla %s %s", destino, plantilla, parametros)
        return f"simulado-{uuid.uuid4().hex[:12]}"
    if not (settings.WHATSAPP_TOKEN and settings.WHATSAPP_PHONE_ID):
        raise WhatsAppError("Falta configurar WHATSAPP_TOKEN y WHATSAPP_PHONE_ID.")
    cuerpo = {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "template",
        "template": {
            "name": plantilla,
            "language": {"code": idioma},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in parametros]}],
        },
    }
    try:
        resp = requests.post(
            API.format(phone_id=settings.WHATSAPP_PHONE_ID),
            json=cuerpo,
            timeout=20,
            headers={"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"},
        )
    except requests.RequestException as exc:
        raise WhatsAppError(str(exc)) from exc
    if resp.status_code >= 400:
        raise WhatsAppError(resp.text[:500])
    return resp.json().get("messages", [{}])[0].get("id", "")

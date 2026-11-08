from decimal import Decimal, InvalidOperation

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

COLORES = {
    # reservas
    "pendiente": "warning",
    "confirmada": "primary",
    "en_curso": "success",
    "finalizada": "secondary",
    "cancelada": "dark",
    "no_show": "danger",
    # habitaciones
    "libre": "success",
    "reservada": "info",
    "ocupada": "danger",
    "sucia": "warning",
    "limpia": "primary",
    "fuera_servicio": "dark",
    # facturas
    "borrador": "secondary",
    "autorizada": "success",
    "rechazada": "danger",
    "anulada": "dark",
    # caja
    "abierta": "success",
    "cerrada": "secondary",
    # incidencias / tareas
    "asignada": "info",
    "resuelta": "success",
    "cerrada_inc": "secondary",
    "terminada": "success",
    "omitida": "secondary",
    "realizado": "success",
    # suscripciones
    "prueba": "info",
    "activa": "success",
    "morosa": "warning",
    "suspendida": "danger",
    # compras
    "enviada": "info",
    "recibida": "primary",
    "recibida_parcial": "warning",
    "facturada": "info",
    "pagada": "success",
    "aprobada": "success",
    "convertida": "primary",
    # notificaciones
    "enviado": "success",
    "error": "danger",
    "bloqueado": "dark",
}


@register.filter
def pesos(valor, decimales=2):
    """Formato monetario argentino: $ 1.234,56"""
    if valor is None or valor == "":
        return "—"
    try:
        valor = Decimal(valor)
    except (InvalidOperation, TypeError, ValueError):
        return valor
    texto = f"{abs(valor):,.{int(decimales)}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if valor < 0 else ''}$ {texto}"


@register.filter
def numero(valor, decimales=0):
    if valor is None:
        return "—"
    try:
        valor = Decimal(valor)
    except (InvalidOperation, TypeError, ValueError):
        return valor
    return f"{valor:,.{int(decimales)}f}".replace(",", "X").replace(".", ",").replace("X", ".")


@register.filter
def color(estado):
    return COLORES.get(str(estado), "secondary")


@register.simple_tag
def badge(estado, texto=None):
    return mark_safe(f'<span class="badge text-bg-{COLORES.get(str(estado), "secondary")}">{texto or estado}</span>')


@register.filter
def get(diccionario, clave):
    if diccionario is None:
        return None
    return diccionario.get(clave) if hasattr(diccionario, "get") else None


@register.filter
def tiene_perm(usuario, perm):
    return usuario.has_perm(perm)


@register.filter
def tiene_rol(usuario, roles):
    return usuario.tiene_rol(*[r.strip() for r in roles.split(",")])


@register.simple_tag(takes_context=True)
def modulo(context, codigo):
    """True si el plan del hotel activo incluye el módulo (o si no hay suscripción)."""
    request = context.get("request")
    sus = getattr(request, "suscripcion", None)
    return sus is None or sus.plan.incluye(codigo)


@register.simple_tag(takes_context=True)
def url_con(context, **kwargs):
    """Mantiene los parámetros GET actuales reemplazando los indicados."""
    params = context["request"].GET.copy()
    for k, v in kwargs.items():
        params[k] = v
    return "?" + params.urlencode()

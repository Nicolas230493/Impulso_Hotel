from django.db.models.signals import post_migrate, post_save, pre_save
from django.dispatch import receiver

from . import auditoria
from .models import Auditoria, Hotel, ModeloHotel, Usuario


def _auditable(sender):
    if sender is Auditoria or getattr(sender, "auditar", True) is False:
        return False
    return issubclass(sender, ModeloHotel) or sender in (Hotel, Usuario)


@receiver(pre_save)
def capturar_estado_anterior(sender, instance, raw=False, **kwargs):
    if raw or not _auditable(sender) or not instance.pk:
        return
    anterior = sender._default_manager.filter(pk=instance.pk).first()
    instance._auditoria_antes = auditoria.serializar(anterior) if anterior else None


def _texto(instance):
    try:
        return str(instance)[:255]
    except (ValueError, TypeError, AttributeError):
        return f"{instance._meta.label} #{instance.pk}"


@receiver(post_save)
def registrar_cambio(sender, instance, created, raw=False, **kwargs):
    if raw or not _auditable(sender):
        return
    despues = auditoria.serializar(instance)
    if created:
        auditoria.registrar(Auditoria.Accion.CREAR, instance, _texto(instance), None, despues)
        return
    antes = getattr(instance, "_auditoria_antes", None) or {}
    cambios_antes = {k: v for k, v in antes.items() if despues.get(k) != v}
    if not cambios_antes:
        return
    cambios_despues = {k: despues.get(k) for k in cambios_antes}
    accion = Auditoria.Accion.MODIFICAR
    if cambios_despues.get("activo") is False:
        accion = Auditoria.Accion.BORRAR
    auditoria.registrar(accion, instance, _texto(instance), cambios_antes, cambios_despues)
    instance._auditoria_antes = despues


@receiver(post_migrate)
def crear_roles(sender, **kwargs):
    # Idempotente: se ejecuta tras cada app para que los permisos nuevos queden asignados.
    from .permisos import sincronizar_roles

    sincronizar_roles()

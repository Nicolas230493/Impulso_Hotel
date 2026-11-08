from django.db.models.signals import pre_save
from django.dispatch import receiver

from habitaciones.models import Habitacion

from .services import validar_limite_habitaciones


@receiver(pre_save, sender=Habitacion)
def limite_habitaciones(sender, instance, raw=False, **kwargs):
    if raw or instance.pk:
        return
    validar_limite_habitaciones(instance.hotel)

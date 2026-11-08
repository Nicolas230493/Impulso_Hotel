from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver
from django.utils import timezone


class BloqueoModelBackend(ModelBackend):
    """Autenticación estándar que rechaza usuarios bloqueados por intentos fallidos."""

    def user_can_authenticate(self, user):
        if getattr(user, "esta_bloqueado", False):
            return False
        return super().user_can_authenticate(user)


@receiver(user_login_failed)
def registrar_intento_fallido(sender, credentials, request=None, **kwargs):
    Usuario = get_user_model()
    username = credentials.get("username")
    if not username:
        return
    usuario = Usuario.objects.filter(username=username).first()
    if usuario is None or usuario.esta_bloqueado:
        return
    usuario.intentos_fallidos += 1
    if usuario.intentos_fallidos >= settings.LOGIN_MAX_INTENTOS:
        usuario.bloqueado_hasta = timezone.now() + timedelta(minutes=settings.LOGIN_MINUTOS_BLOQUEO)
        usuario.intentos_fallidos = 0
    usuario.save(update_fields=["intentos_fallidos", "bloqueado_hasta"])


@receiver(user_logged_in)
def reiniciar_intentos(sender, user, request=None, **kwargs):
    if user.intentos_fallidos or user.bloqueado_hasta:
        user.intentos_fallidos = 0
        user.bloqueado_hasta = None
        user.save(update_fields=["intentos_fallidos", "bloqueado_hasta"])

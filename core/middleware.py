from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

from . import actual
from .models import Hotel


def hotel_para_usuario(usuario, request=None):
    """Hotel activo del usuario: el elegido si tiene acceso, si no el primero permitido.

    El personal de Impulso (superadmin) solo entra a un hotel mediante un acceso de soporte auditado.
    """
    if not usuario.is_authenticated:
        return None
    if usuario.es_superadmin_impulso and not usuario.is_superuser:
        hotel_id = request.session.get("soporte_hotel") if request is not None else None
        return Hotel.objects.filter(pk=hotel_id, activo=True).first() if hotel_id else None
    hotel = usuario.hotel_activo
    if hotel is not None and hotel.activo and usuario.puede_acceder_hotel(hotel):
        return hotel
    hotel = usuario.hoteles.filter(activo=True).first()
    if hotel is None and usuario.is_superuser:
        hotel = Hotel.objects.filter(activo=True).first()
    return hotel


class HotelActivoMiddleware:
    """Fija el hotel activo del usuario; todos los querysets operativos filtran por él."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario = request.user if request.user.is_authenticated else None
        request.hotel = hotel_para_usuario(request.user, request) if usuario else None
        tokens = actual.fijar(request=request, hotel=request.hotel, usuario=usuario)
        try:
            return self.get_response(request)
        finally:
            actual.limpiar(tokens)


RUTAS_EXENTAS_2FA = ("/cuenta/", "/static/", "/media/", "/api/")


def requiere_doble_factor(usuario):
    from . import roles

    return usuario.is_superuser or usuario.es_superadmin_impulso or usuario.groups.filter(name=roles.ADMIN).exists()


class DobleFactorMiddleware:
    """Exige doble factor (TOTP) a los administradores cuando REQUIRE_2FA_ADMINS está activo."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            settings.REQUIRE_2FA_ADMINS
            and request.user.is_authenticated
            and not request.path.startswith(RUTAS_EXENTAS_2FA)
            and not request.user.is_verified()
            and requiere_doble_factor(request.user)
        ):
            from django_otp import devices_for_user

            if any(True for _ in devices_for_user(request.user, confirmed=True)):
                return redirect(f"{reverse('otp_verificar')}?next={request.path}")
            return redirect("otp_configurar")
        return self.get_response(request)

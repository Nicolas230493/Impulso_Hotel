from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.utils import timezone

from core import actual, roles
from core.models import Hotel, Usuario


@pytest.fixture(autouse=True)
def _ajustes(settings):
    settings.REQUIRE_2FA_ADMINS = False
    settings.ARCA_MODO = "simulado"
    settings.WHATSAPP_MODO = "simulado"
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.ALLOWED_HOSTS = ["*"]


@pytest.fixture
def hoy():
    return timezone.localdate()


@pytest.fixture
def hotel(db):
    from facturacion.models import PuntoVenta
    from inventario.models import Deposito

    h = Hotel.objects.create(nombre="Hotel Test", cuit="30712345678", condicion_iva="RI")
    PuntoVenta.objects.create(hotel=h, numero=1, tipos_habilitados=[1, 3, 6, 8, 11, 13], por_defecto=True)
    Deposito.objects.create(hotel=h, nombre="Principal")
    return h


@pytest.fixture
def otro_hotel(db):
    return Hotel.objects.create(nombre="Otro Hotel", cuit="30799999999")


def crear_usuario(hotel, username, rol):
    u = Usuario.objects.create_user(username=username, password="Clave-segura-123", hotel_activo=hotel)
    u.hoteles.add(hotel)
    u.groups.add(Group.objects.get(name=rol))
    return Usuario.objects.get(pk=u.pk)  # limpia la caché de permisos


@pytest.fixture
def admin(hotel):
    return crear_usuario(hotel, "admin_t", roles.ADMIN)


@pytest.fixture
def recepcion(hotel):
    return crear_usuario(hotel, "recep_t", roles.RECEPCION)


@pytest.fixture
def limpieza_user(hotel):
    return crear_usuario(hotel, "limp_t", roles.LIMPIEZA)


@pytest.fixture
def mant_user(hotel):
    return crear_usuario(hotel, "mant_t", roles.MANTENIMIENTO)


@pytest.fixture
def ctx(hotel, admin):
    with actual.contexto(hotel=hotel, usuario=admin):
        yield


@pytest.fixture
def tipos(hotel):
    from habitaciones.models import TipoHabitacion

    return {
        "doble": TipoHabitacion.objects.create(hotel=hotel, nombre="Doble", capacidad=2, precio_base=Decimal("10000")),
        "suite": TipoHabitacion.objects.create(hotel=hotel, nombre="Suite", capacidad=4, precio_base=Decimal("20000")),
    }


@pytest.fixture
def habs(hotel, tipos):
    from habitaciones.models import Habitacion

    return [
        Habitacion.objects.create(
            hotel=hotel, numero=str(100 + i), piso=1, tipo=tipos["doble"] if i < 3 else tipos["suite"]
        )
        for i in range(5)
    ]


@pytest.fixture
def huesped(hotel):
    from huespedes.models import Huesped

    return Huesped.objects.create(
        hotel=hotel,
        nombre="Ana",
        apellido="Pérez",
        nro_doc="30111222",
        telefono="+5491100000000",
        consentimiento_datos=True,
        consentimiento_whatsapp=True,
    )


@pytest.fixture
def reserva_confirmada(hotel, huesped, habs, admin, hoy):
    from reservas import services
    from reservas.models import Reserva

    return services.crear_reserva(
        hotel,
        huesped,
        hoy,
        hoy + timedelta(days=3),
        [{"habitacion": habs[0], "cantidad_huespedes": 2}],
        estado=Reserva.Estado.CONFIRMADA,
        usuario=admin,
    )


@pytest.fixture
def cliente_admin(client, admin):
    client.force_login(admin)
    return client

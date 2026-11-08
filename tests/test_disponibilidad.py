from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from habitaciones import services as hab
from habitaciones.models import BloqueoHabitacion, Tarifa
from reservas import services
from reservas.models import DetalleReserva, Reserva

pytestmark = pytest.mark.django_db


def test_no_permite_superposicion(hotel, huesped, habs, admin, hoy, reserva_confirmada):
    with pytest.raises(ValidationError, match="ya está reservada"):
        services.crear_reserva(
            hotel, huesped, hoy + timedelta(days=2), hoy + timedelta(days=5), [{"habitacion": habs[0]}], usuario=admin
        )


def test_salida_exclusiva_permite_encadenar(hotel, huesped, habs, admin, hoy, reserva_confirmada):
    r = services.crear_reserva(
        hotel, huesped, hoy + timedelta(days=3), hoy + timedelta(days=5), [{"habitacion": habs[0]}], usuario=admin
    )
    assert r.pk


def test_restriccion_de_base_de_datos_impide_sobre_reserva(hotel, habs, reserva_confirmada, hoy):
    """Aunque se saltee la validación del servicio, PostgreSQL rechaza la superposición."""
    det = reserva_confirmada.detalles.first()
    with pytest.raises(IntegrityError), transaction.atomic():
        DetalleReserva.objects.create(
            hotel=hotel,
            reserva=reserva_confirmada,
            habitacion=habs[0],
            tipo_habitacion=habs[0].tipo,
            fecha_entrada=hoy + timedelta(days=1),
            fecha_salida=hoy + timedelta(days=2),
            tarifa_aplicada=1,
            subtotal=1,
        )
    assert det.vigente


def test_cancelar_libera_la_habitacion(hotel, huesped, habs, admin, hoy, reserva_confirmada):
    services.cancelar(reserva_confirmada, "El huésped desistió", admin)
    r = services.crear_reserva(hotel, huesped, hoy, hoy + timedelta(days=2), [{"habitacion": habs[0]}], usuario=admin)
    assert r.pk


def test_capacidad_maxima(hotel, huesped, habs, admin, hoy):
    with pytest.raises(ValidationError, match="admite hasta 2"):
        services.crear_reserva(
            hotel,
            huesped,
            hoy,
            hoy + timedelta(days=1),
            [{"habitacion": habs[0], "cantidad_huespedes": 3}],
            usuario=admin,
        )


def test_fuera_de_servicio_no_es_reservable(hotel, huesped, habs, admin, hoy):
    BloqueoHabitacion.objects.create(
        hotel=hotel,
        habitacion=habs[1],
        fecha_desde=hoy + timedelta(days=1),
        fecha_hasta=hoy + timedelta(days=2),
        motivo="Pintura",
    )
    with pytest.raises(ValidationError, match="fuera de servicio"):
        services.crear_reserva(hotel, huesped, hoy, hoy + timedelta(days=3), [{"habitacion": habs[1]}], usuario=admin)
    disponibles = hab.habitaciones_disponibles(hotel, hoy, hoy + timedelta(days=3))
    assert habs[1] not in disponibles


def test_disponibilidad_excluye_ocupadas(hotel, habs, hoy, reserva_confirmada):
    disp = list(hab.habitaciones_disponibles(hotel, hoy, hoy + timedelta(days=1)))
    assert habs[0] not in disp and habs[1] in disp


def test_total_con_tarifa_de_temporada(hotel, huesped, habs, tipos, admin, hoy):
    Tarifa.objects.create(
        hotel=hotel,
        tipo_habitacion=tipos["doble"],
        temporada="Alta",
        fecha_desde=hoy + timedelta(days=1),
        fecha_hasta=hoy + timedelta(days=1),
        precio_noche=15000,
    )
    r = services.crear_reserva(hotel, huesped, hoy, hoy + timedelta(days=3), [{"habitacion": habs[1]}], usuario=admin)
    assert r.total == 10000 + 15000 + 10000


def test_reserva_de_dos_habitaciones(hotel, huesped, habs, admin, hoy):
    r = services.crear_reserva(
        hotel,
        huesped,
        hoy,
        hoy + timedelta(days=2),
        [{"habitacion": habs[1]}, {"habitacion": habs[3], "cantidad_huespedes": 3}],
        usuario=admin,
    )
    assert r.detalles.count() == 2 and r.total == 2 * 10000 + 2 * 20000


def test_modificar_reserva_revalida(hotel, huesped, habs, admin, hoy, reserva_confirmada):
    otra = services.crear_reserva(
        hotel, huesped, hoy + timedelta(days=5), hoy + timedelta(days=7), [{"habitacion": habs[0]}], usuario=admin
    )
    with pytest.raises(ValidationError):
        services.modificar_reserva(otra, hoy + timedelta(days=2), hoy + timedelta(days=7), [{"habitacion": habs[0]}])
    otra = services.modificar_reserva(otra, hoy + timedelta(days=3), hoy + timedelta(days=8), [{"habitacion": habs[0]}])
    assert otra.total == 50000 and otra.estado == Reserva.Estado.PENDIENTE

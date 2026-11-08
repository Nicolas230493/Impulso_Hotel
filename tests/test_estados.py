from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from caja import services as caja
from habitaciones.models import Habitacion
from reservas import services
from reservas.models import Reserva

pytestmark = pytest.mark.django_db


def test_flujo_completo(hotel, huesped, habs, admin, reserva_confirmada):
    r = services.checkin(reserva_confirmada, admin)
    assert r.estado == Reserva.Estado.EN_CURSO
    habs[0].refresh_from_db()
    assert habs[0].estado == Habitacion.Estado.OCUPADA
    assert caja.total_cargos(r) == 10000  # primera noche cargada
    caja.abrir_caja(hotel, admin, Decimal("0"))
    with pytest.raises(ValidationError, match="saldo pendiente"):
        services.checkout(r, admin)
    caja.registrar_pago(r, "efectivo", Decimal("10000"), admin)
    r = services.checkout(r, admin)  # salida anticipada: hoy (se cobra 1 noche)
    assert r.estado == Reserva.Estado.FINALIZADA
    habs[0].refresh_from_db()
    assert habs[0].estado == Habitacion.Estado.SUCIA
    assert r.estadias.first().hora_real_salida is not None


def test_checkin_exige_confirmada(hotel, huesped, habs, admin, hoy):
    r = services.crear_reserva(hotel, huesped, hoy, hoy + timedelta(days=1), [{"habitacion": habs[1]}], usuario=admin)
    with pytest.raises(ValidationError, match="confirmada"):
        services.checkin(r, admin)


def test_checkin_fuera_de_fecha(hotel, huesped, habs, admin, hoy):
    r = services.crear_reserva(
        hotel,
        huesped,
        hoy + timedelta(days=5),
        hoy + timedelta(days=6),
        [{"habitacion": habs[1]}],
        usuario=admin,
        estado=Reserva.Estado.CONFIRMADA,
    )
    with pytest.raises(ValidationError, match="corresponde"):
        services.checkin(r, admin)


def test_advertencia_habitacion_sucia(hotel, habs, admin, reserva_confirmada):
    habs[0].estado = Habitacion.Estado.SUCIA
    habs[0].save()
    with pytest.raises(ValidationError) as exc:
        services.checkin(reserva_confirmada, admin)
    assert exc.value.code == "habitacion_sucia"
    assert services.checkin(reserva_confirmada, admin, confirmar_sucia=True).estado == "en_curso"


def test_cancelacion_registra_motivo_y_usuario(admin, reserva_confirmada):
    with pytest.raises(ValidationError):
        services.cancelar(reserva_confirmada, "  ", admin)
    r = services.cancelar(reserva_confirmada, "Cambio de fecha", admin)
    assert r.motivo_cancelacion == "Cambio de fecha" and r.cancelada_por == admin and r.cancelada_en


def test_no_show(hotel, huesped, habs, admin, hoy):
    r = services.crear_reserva(
        hotel,
        huesped,
        hoy - timedelta(days=1),
        hoy + timedelta(days=2),
        [{"habitacion": habs[2]}],
        usuario=admin,
        estado=Reserva.Estado.CONFIRMADA,
        permitir_pasado=True,
    )
    assert services.marcar_no_shows() >= 1
    r.refresh_from_db()
    assert r.estado == Reserva.Estado.NO_SHOW
    assert not r.detalles.first().vigente


def test_walk_in(hotel, huesped, habs, admin, hoy):
    r = services.walk_in(hotel, huesped, hoy + timedelta(days=2), [{"habitacion": habs[4]}], usuario=admin)
    assert r.estado == Reserva.Estado.EN_CURSO and r.fecha_entrada == hoy


def test_checkout_con_autorizacion(hotel, admin, recepcion, reserva_confirmada):
    services.checkin(reserva_confirmada, admin)
    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        services.checkout(reserva_confirmada, recepcion, autorizar_saldo=True)
    r = services.checkout(reserva_confirmada, admin, autorizar_saldo=True)
    assert r.checkout_autorizado_por == admin


def test_cuenta_corriente_permite_salir_con_saldo(hotel, admin, reserva_confirmada):
    from caja.models import CuentaCorriente

    cc = CuentaCorriente.objects.create(hotel=hotel, razon_social="Empresa SA", cuit="30700000001")
    Reserva.objects.filter(pk=reserva_confirmada.pk).update(cuenta_corriente=cc)
    reserva_confirmada.refresh_from_db()
    services.checkin(reserva_confirmada, admin)
    assert services.checkout(reserva_confirmada, admin).estado == "finalizada"


def test_tarea_limpieza_generada_al_checkout(hotel, admin, reserva_confirmada):
    from limpieza.models import TareaLimpieza

    services.checkin(reserva_confirmada, admin)
    services.checkout(reserva_confirmada, admin, autorizar_saldo=True)
    assert TareaLimpieza.objects.filter(
        habitacion=reserva_confirmada.detalles.first().habitacion, fecha=timezone.localdate(), tipo="completa"
    ).exists()

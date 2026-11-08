from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from core.models import Auditoria
from habitaciones import services as hab
from habitaciones.models import Habitacion, Tarifa

pytestmark = pytest.mark.django_db


def test_limpieza_no_ve_caja_ni_precios(client, limpieza_user):
    client.force_login(limpieza_user)
    assert client.get(reverse("caja_mia")).status_code == 403
    assert client.get(reverse("tarifa_lista")).status_code == 403
    assert client.get(reverse("informes_economicos")).status_code == 403
    assert client.get(reverse("mapa_habitaciones")).status_code == 200


def test_limpieza_solo_marca_limpia(habs, limpieza_user):
    habs[0].estado = Habitacion.Estado.SUCIA
    habs[0].save()
    hab.cambiar_estado(habs[0], Habitacion.Estado.LIMPIA, limpieza_user)
    with pytest.raises(PermissionDenied):
        hab.cambiar_estado(habs[1], Habitacion.Estado.FUERA_SERVICIO, limpieza_user)


def test_mantenimiento_maneja_fuera_de_servicio(habs, mant_user, hoy):
    hab.cambiar_estado(habs[1], Habitacion.Estado.FUERA_SERVICIO, mant_user, "Pérdida de agua")
    assert hab.esta_bloqueada(habs[1], hoy, hoy + timedelta(days=1))
    hab.cambiar_estado(habs[1], Habitacion.Estado.SUCIA, mant_user)
    assert not hab.esta_bloqueada(habs[1], hoy, hoy + timedelta(days=1))


def test_recepcion_ve_tarifas_pero_no_las_edita(client, recepcion, tipos):
    client.force_login(recepcion)
    assert client.get(reverse("tarifa_lista")).status_code == 200
    assert client.get(reverse("tarifa_nuevo")).status_code == 403


def test_sobre_reserva_por_api_devuelve_error_claro(client, recepcion, huesped, habs, reserva_confirmada, hoy):
    client.force_login(recepcion)
    datos = {
        "titular": huesped.pk,
        "fecha_entrada": str(hoy + timedelta(days=1)),
        "fecha_salida": str(hoy + timedelta(days=2)),
        "habitaciones": [{"habitacion": habs[0].pk}],
    }
    resp = client.post("/api/v1/reservas/", datos, content_type="application/json")
    assert resp.status_code == 400
    assert "ya está reservada" in str(resp.json())


def test_sobre_reserva_por_web_devuelve_error_claro(client, recepcion, huesped, habs, reserva_confirmada, hoy):
    client.force_login(recepcion)
    resp = client.post(
        reverse("reserva_nueva"),
        {
            "tipo_doc": "DNI",
            "nro_doc": huesped.nro_doc,
            "nombre": "Ana",
            "apellido": "Pérez",
            "fecha_entrada": hoy + timedelta(days=1),
            "fecha_salida": hoy + timedelta(days=2),
            "canal": "directo",
            f"hab_{habs[0].pk}": "1",
            f"cant_{habs[0].pk}": "1",
        },
    )
    assert resp.status_code == 200
    assert "ya está reservada" in resp.content.decode()


def test_api_flujo_checkin_checkout(client, admin, huesped, habs, hoy):
    client.force_login(admin)
    r = client.post(
        "/api/v1/reservas/",
        {
            "titular": huesped.pk,
            "fecha_entrada": str(hoy),
            "fecha_salida": str(hoy + timedelta(days=1)),
            "confirmar": True,
            "habitaciones": [{"habitacion": habs[1].pk, "cantidad_huespedes": 2}],
        },
        content_type="application/json",
    )
    assert r.status_code == 201, r.content
    rid = r.json()["id"]
    assert client.post(f"/api/v1/reservas/{rid}/checkin/").json()["estado"] == "en_curso"
    resp = client.post(f"/api/v1/reservas/{rid}/checkout/", {}, content_type="application/json")
    assert resp.status_code == 400 and "saldo" in str(resp.json())
    resp = client.post(f"/api/v1/reservas/{rid}/checkout/", {"autorizar_saldo": True}, content_type="application/json")
    assert resp.json()["estado"] == "finalizada"


def test_api_disponibilidad(client, recepcion, habs, hoy, reserva_confirmada):
    client.force_login(recepcion)
    data = client.get(f"/api/v1/disponibilidad/?desde={hoy}&hasta={hoy + timedelta(days=2)}").json()
    numeros = [h["numero"] for h in data["disponibles"]]
    assert habs[0].numero not in numeros and len(numeros) == 4 and data["noches"] == 2


def test_api_limpieza_sin_permiso_de_reservas(client, limpieza_user):
    client.force_login(limpieza_user)
    assert client.get("/api/v1/reservas/").status_code == 403
    assert client.get("/api/v1/habitaciones/").status_code == 200


def test_api_cancelar_requiere_motivo(client, recepcion, reserva_confirmada):
    client.force_login(recepcion)
    assert client.post(f"/api/v1/reservas/{reserva_confirmada.pk}/cancelar/").status_code == 400
    r = client.post(
        f"/api/v1/reservas/{reserva_confirmada.pk}/cancelar/", {"motivo": "No viaja"}, content_type="application/json"
    )
    assert r.json()["estado"] == "cancelada"


def test_auditoria_de_reservas_y_tarifas(ctx, hotel, tipos, admin, reserva_confirmada):
    from reservas import services

    services.cancelar(reserva_confirmada, "Prueba", admin)
    assert Auditoria.objects.filter(
        modelo="reservas.Reserva", objeto_id=str(reserva_confirmada.pk), accion="modificar", usuario=admin
    ).exists()
    t = Tarifa.objects.create(
        hotel=hotel,
        tipo_habitacion=tipos["doble"],
        temporada="Alta",
        fecha_desde="2026-01-01",
        fecha_hasta="2026-01-31",
        precio_noche=1,
    )
    t.refresh_from_db()
    t.precio_noche = Decimal("2.00")
    t.save()
    reg = Auditoria.objects.filter(modelo="habitaciones.Tarifa", objeto_id=str(t.pk), accion="modificar").get()
    assert reg.antes["precio_noche"] == "1.00" and reg.despues["precio_noche"] == "2.00"


def test_bloqueo_tras_intentos_fallidos(client, admin, settings):
    settings.LOGIN_MAX_INTENTOS = 3
    for _ in range(3):
        client.post(reverse("login"), {"username": admin.username, "password": "mal"})
    admin.refresh_from_db()
    assert admin.esta_bloqueado
    resp = client.post(reverse("login"), {"username": admin.username, "password": "Clave-segura-123"})
    assert "bloqueado" in resp.content.decode()


def test_doble_factor_para_administradores(client, admin, settings):
    settings.REQUIRE_2FA_ADMINS = True
    client.force_login(admin)
    resp = client.get(reverse("panel_recepcion"))
    assert resp.status_code == 302 and "/cuenta/2fa/" in resp["Location"]


def test_pantallas_responsive(cliente_admin):
    html = cliente_admin.get(reverse("panel_recepcion")).content.decode()
    assert 'name="viewport" content="width=device-width, initial-scale=1"' in html

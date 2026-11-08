from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from bi import services as bi
from bi.models import Prediccion, RecomendacionTarifa
from caja.models import Cargo
from core.models import Empresa, Hotel
from habitaciones.models import Habitacion, Tarifa
from reservas import services
from reservas.models import Reserva

pytestmark = pytest.mark.django_db


def _historia(hotel, huesped, habs, admin, dias=30):
    """Una reserva finalizada de 2 noches cada 3 días en habs[0] y una cancelada."""
    hoy = timezone.localdate()
    inicio = hoy - timedelta(days=dias)
    d = inicio
    while d + timedelta(days=2) <= hoy:
        r = services.crear_reserva(
            hotel, huesped, d, d + timedelta(days=2), [{"habitacion": habs[0]}], usuario=admin, permitir_pasado=True
        )
        Reserva.objects.filter(pk=r.pk).update(estado="finalizada")
        r.refresh_from_db()
        from caja.services import cargar_noches_reserva

        cargar_noches_reserva(r)
        d += timedelta(days=3)
    c = services.crear_reserva(
        hotel,
        huesped,
        inicio + timedelta(days=1),
        inicio + timedelta(days=2),
        [{"habitacion": habs[1]}],
        usuario=admin,
        permitir_pasado=True,
    )
    services.cancelar(c, "x", admin)
    return inicio, hoy - timedelta(days=1)


def test_kpis_coinciden_con_calculo_manual(hotel, huesped, habs, admin):
    desde, hasta = _historia(hotel, huesped, habs, admin)
    k = bi.kpis(hotel, desde, hasta)
    dias = (hasta - desde).days + 1
    disponibles = dias * len(habs)
    # cálculo manual independiente
    noches = sum(1 for c in Cargo.objects.filter(hotel=hotel, origen="noche", fecha__gte=desde, fecha__lte=hasta))
    ingresos = sum(
        c.importe for c in Cargo.objects.filter(hotel=hotel, origen="noche", fecha__gte=desde, fecha__lte=hasta)
    )
    assert k["noches_disponibles"] == disponibles
    assert k["noches_ocupadas"] == noches
    assert k["ocupacion"] == round(noches / disponibles * 100, 2)
    assert k["adr"] == (ingresos / noches).quantize(Decimal("0.01"))
    assert k["revpar"] == (ingresos / disponibles).quantize(Decimal("0.01"))
    reservas = Reserva.objects.filter(hotel=hotel, fecha_entrada__gte=desde, fecha_entrada__lte=hasta)
    assert k["tasa_cancelacion"] == round(reservas.filter(estado="cancelada").count() / reservas.count() * 100, 2)
    assert k["estadia_promedio"] == 2


def test_prediccion_con_poca_historia_usa_reglas(hotel, huesped, habs, admin):
    _historia(hotel, huesped, habs, admin, dias=20)
    resumen = bi.predecir_demanda(hotel, dias=10)
    assert resumen["modelo"] == "reglas"
    assert Prediccion.objects.filter(hotel=hotel).count() == 10


def test_prediccion_linea_base_reporta_mape(hotel, huesped, habs, admin):
    _historia(hotel, huesped, habs, admin, dias=90)
    resumen = bi.predecir_demanda(hotel, dias=14)
    assert resumen["modelo"] == "linea_base" and resumen["mape_linea_base"] is not None
    p = Prediccion.objects.filter(hotel=hotel).first()
    assert p.mape_linea_base is not None and "en_cartera" in p.datos_base


def test_tarifa_sugerida_requiere_aprobacion_y_respeta_limites(hotel, huesped, habs, tipos, admin):
    hoy = timezone.localdate()
    tipos["doble"].precio_maximo = Decimal("11000")
    tipos["doble"].save()
    for h in habs[:3]:
        services.crear_reserva(
            hotel,
            huesped,
            hoy + timedelta(days=5),
            hoy + timedelta(days=6),
            [{"habitacion": h}],
            usuario=admin,
            estado="confirmada",
        )
    assert bi.recomendar_tarifas(hotel, dias=10) > 0
    rec = RecomendacionTarifa.objects.get(tipo_habitacion=tipos["doble"], fecha=hoy + timedelta(days=5))
    assert rec.precio_sugerido == Decimal("11000")  # tope del hotel
    assert rec.fundamento["razones"] and rec.estado == "pendiente"
    assert not Tarifa.objects.filter(temporada="Tarifa dinámica").exists()
    bi.decidir_recomendacion(rec, True, admin)
    from habitaciones.services import precio_noche

    assert precio_noche(tipos["doble"], rec.fecha)[0] == Decimal("11000")


def test_alertas_incidencias_repetidas_y_stock(hotel, admin, habs):
    from bi.models import Alerta
    from mantenimiento import services as mant

    for i in range(3):
        inc = mant.reportar(hotel, admin, f"Falla {i}", habitacion=habs[0])
        bi.alerta_incidencias_repetidas(inc)
    assert Alerta.objects.filter(tipo="incidencias_repetidas", resuelta=False).count() == 1
    a = Alerta.objects.get(tipo="incidencias_repetidas")
    assert len(a.datos_base["incidencias"]) == 3


def test_dashboard_y_exportaciones(cliente_admin):
    assert cliente_admin.get("/bi/?vista=mensual").status_code == 200
    assert cliente_admin.get("/bi/?formato=pdf").content[:4] == b"%PDF"
    assert cliente_admin.get("/bi/?formato=xlsx").content[:2] == b"PK"


def test_reporte_programado_por_email(hotel, mailoutbox):
    from bi.models import ReporteProgramado
    from bi.reportes import enviar_programados

    ReporteProgramado.objects.create(hotel=hotel, frecuencia="diario", destinatarios="dueno@hotel.com")
    assert enviar_programados() == 1
    assert mailoutbox and mailoutbox[0].attachments


# ------------------------------------------------------------------ Fase 5


@pytest.fixture
def planes(db):
    from saas.models import Plan

    return {
        "inicial": Plan.objects.create(nombre="Inicial", max_habitaciones=3, modulos=["reservas", "caja"]),
        "empresarial": Plan.objects.create(nombre="Empresarial", modulos=["reservas", "caja", "bi", "multi_hotel"]),
    }


def test_alta_autoservicio_operativa(client, planes):
    resp = client.post(
        "/registro/",
        {
            "razon_social": "Hostel Nuevo SRL",
            "cuit": "30-71234567-8",
            "nombre_hotel": "Hostel Nuevo",
            "plan": planes["inicial"].pk,
            "nombre": "Nora",
            "apellido": "Díaz",
            "email": "nora@hostel.com",
            "username": "nora",
            "password": "Una-clave-larga-99",
            "acepto": "on",
        },
    )
    assert resp.status_code == 302 and resp["Location"] == "/onboarding/"
    hotel = Hotel.objects.get(nombre="Hostel Nuevo")
    assert hotel.empresa.suscripcion.estado == "prueba"
    client.post(
        "/onboarding/?paso=2",
        {"tipo_nombre": "Doble", "capacidad": 2, "precio_base": "50000", "piso": 1, "desde": 1, "cantidad": 3},
    )
    assert Habitacion.objects.filter(hotel=hotel).count() == 3
    assert client.get("/recepcion/").status_code == 200


def test_limite_de_habitaciones_del_plan(hotel, tipos, planes):
    from saas.models import Suscripcion

    e = Empresa.objects.create(razon_social="E")
    hotel.empresa = e
    hotel.save()
    Suscripcion.objects.create(empresa=e, plan=planes["inicial"], estado="activa")
    for i in range(3):
        Habitacion.objects.create(hotel=hotel, numero=str(i), tipo=tipos["doble"])
    with pytest.raises(ValidationError, match="hasta 3"):
        Habitacion.objects.create(hotel=hotel, numero="99", tipo=tipos["doble"])


def test_aislamiento_entre_clientes(client, hotel, otro_hotel, admin, huesped):
    from huespedes.models import Huesped

    ajeno = Huesped.objects.create(hotel=otro_hotel, nombre="X", apellido="Ajeno", nro_doc="999")
    client.force_login(admin)
    assert client.get(f"/huespedes/{ajeno.pk}/").status_code == 404
    assert list(client.get("/huespedes/?q=Ajeno").context["page_obj"].object_list) == []
    ids = [h["id"] for h in client.get("/api/v1/huespedes/").json()["results"]]
    assert huesped.pk in ids and ajeno.pk not in ids
    assert client.get(f"/api/v1/huespedes/{ajeno.pk}/").status_code == 404
    # tampoco puede cambiarse a un hotel ajeno
    client.post("/hotel/cambiar/", {"hotel": otro_hotel.pk})
    admin.refresh_from_db()
    assert admin.hotel_activo == hotel


def test_suspension_solo_lectura_sin_borrar_datos(client, hotel, admin, huesped, planes):
    from saas import services as saas
    from saas.models import Suscripcion

    e = Empresa.objects.create(razon_social="E")
    hotel.empresa = e
    hotel.save()
    sus = Suscripcion.objects.create(
        empresa=e,
        plan=planes["empresarial"],
        estado="activa",
        proximo_cobro=timezone.localdate(),
        medio_pago_token="rechazar",
    )
    hoy = timezone.localdate()
    saas.revisar_suscripciones(hoy)
    sus.refresh_from_db()
    assert sus.estado == "morosa"
    saas.revisar_suscripciones(hoy + timedelta(days=8))
    sus.refresh_from_db()
    assert sus.estado == "suspendida"
    client.force_login(admin)
    assert client.get("/huespedes/").status_code == 200
    assert huesped.nombre in client.get(f"/huespedes/{huesped.pk}/").content.decode()
    resp = client.post("/huespedes/nuevo/", {"nombre": "Z"})
    assert resp.status_code == 403
    from huespedes.models import Huesped

    assert Huesped.objects.filter(pk=huesped.pk).exists()
    sus.medio_pago_token = ""
    sus.save()
    saas.revisar_suscripciones(hoy + timedelta(days=9))
    sus.refresh_from_db()
    assert sus.estado == "activa"


def test_modulo_no_incluido_en_plan(client, hotel, admin, planes):
    from saas.models import Suscripcion

    e = Empresa.objects.create(razon_social="E")
    hotel.empresa = e
    hotel.save()
    Suscripcion.objects.create(empresa=e, plan=planes["inicial"], estado="activa")
    client.force_login(admin)
    assert client.get("/bi/").status_code == 403
    assert client.get("/caja/").status_code == 200


def test_acceso_de_soporte_auditado(client, hotel, huesped):
    from core.models import Auditoria, Usuario

    sa = Usuario.objects.create_user("sop", password="x", es_superadmin_impulso=True)
    e = Empresa.objects.create(razon_social="E")
    hotel.empresa = e
    hotel.save()
    client.force_login(sa)
    assert client.get("/huespedes/").status_code in (403, 302, 200)
    assert huesped.apellido not in client.get("/huespedes/").content.decode()
    client.post(f"/saas/soporte/acceder/{hotel.pk}/", {"motivo": "Ticket #12"})
    assert Auditoria.objects.filter(accion="soporte", descripcion__contains="Ticket #12").exists()


def test_ml_solo_se_activa_si_mejora_la_linea_base(hotel, huesped, habs, admin):
    """Con 13 meses de historia se entrena el modelo; se activa solo si su MAPE es menor al de la línea base."""
    _historia(hotel, huesped, habs, admin, dias=400)
    resumen = bi.predecir_demanda(hotel, dias=14)
    assert resumen["mape_modelo"] is not None and resumen["mape_linea_base"] is not None
    esperado = "ml_gradient_boosting" if resumen["mape_modelo"] < resumen["mape_linea_base"] else "linea_base"
    assert resumen["modelo"] == esperado
    assert Prediccion.objects.filter(hotel=hotel, modelo=esperado).count() == 14


def test_proceso_nocturno_y_mantenimiento_predictivo(hotel, huesped, habs, admin):
    from mantenimiento import services as mant
    from mantenimiento.models import Activo, Incidencia

    activo = Activo.objects.create(hotel=hotel, nombre="Split", habitacion=habs[0], umbral_reemplazo=Decimal("1000"))
    for dias in (100, 70, 40, 5):
        inc = mant.reportar(hotel, admin, "No enfría", activo=activo)
        Incidencia.objects.filter(pk=inc.pk).update(reportada_en=timezone.now() - timedelta(days=dias))
    mant.registrar_trabajo(hotel, admin, "Recarga de gas", incidencia=inc, costo_mano_obra=Decimal("2000"))
    ranking = bi.ranking_riesgo(hotel)
    assert ranking[0]["activo"] == activo and ranking[0]["mtbf_dias"] == 31.7 and ranking[0]["fallas"] == 4
    assert bi.ranking_habitaciones(hotel)[0]["habitacion"] == habs[0]
    resultado = bi.proceso_nocturno(hotel)
    assert resultado["prediccion"]["modelo"] == "reglas"
    from bi.models import Alerta

    assert Alerta.objects.filter(hotel=hotel, tipo="ocupacion_baja").exists()
    assert bi.alerta_reemplazo_activo(activo) is not None or Alerta.objects.filter(tipo="reemplazo_activo").exists()


def test_consolidado_de_cadena(client, hotel, otro_hotel, admin):
    e = Empresa.objects.create(razon_social="Cadena")
    Hotel.objects.filter(pk__in=[hotel.pk, otro_hotel.pk]).update(empresa=e)
    admin.hoteles.add(otro_hotel)
    client.force_login(admin)
    resp = client.get("/bi/consolidado/")
    assert resp.status_code == 200 and len(resp.context["filas"]) == 2

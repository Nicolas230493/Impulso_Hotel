from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from compras import services as compras
from compras.models import CategoriaGasto, ItemCompra, OrdenCompra, Proveedor
from habitaciones import services as hab
from habitaciones.models import Habitacion
from inventario.models import Deposito, Producto
from limpieza import services as limpieza
from limpieza.models import ChecklistItem, TareaLimpieza
from mantenimiento import services as mant
from mantenimiento.models import Activo, Incidencia, Mantenimiento, PlanPreventivo
from notificaciones import services as notif
from notificaciones.models import Notificacion
from reservas import services

pytestmark = pytest.mark.django_db


def test_tareas_del_dia_y_jornada_de_mucama(hotel, admin, limpieza_user, habs, reserva_confirmada):
    services.checkin(reserva_confirmada, admin)
    habs[1].estado = Habitacion.Estado.SUCIA
    habs[1].save()
    ChecklistItem.objects.create(hotel=hotel, descripcion="Cambiar sábanas")
    assert limpieza.generar_tareas(hotel) == 2
    assert limpieza.generar_tareas(hotel) == 0  # idempotente
    t = TareaLimpieza.objects.get(habitacion=habs[1])
    assert t.tipo == "completa"
    assert TareaLimpieza.objects.get(habitacion=habs[0]).tipo == "repaso"
    limpieza.iniciar(t, limpieza_user)
    with pytest.raises(ValidationError, match="checklist"):
        limpieza.terminar(t, limpieza_user, {})
    item = ChecklistItem.objects.get()
    limpieza.terminar(t, limpieza_user, {str(item.pk): True})
    habs[1].refresh_from_db()
    assert habs[1].estado == Habitacion.Estado.LIMPIA and t.fin and t.minutos is not None


def test_jornada_de_mucama_desde_el_celular(client, hotel, limpieza_user, habs):
    habs[2].estado = Habitacion.Estado.SUCIA
    habs[2].save()
    limpieza.generar_tareas(hotel)
    t = TareaLimpieza.objects.get(habitacion=habs[2])
    client.force_login(limpieza_user)
    assert client.get("/limpieza/mis-tareas/").status_code == 200
    client.post(f"/limpieza/tareas/{t.pk}/", {"accion": "iniciar"})
    client.post(f"/limpieza/tareas/{t.pk}/", {"accion": "incidencia", "titulo": "Lámpara quemada"})
    client.post(f"/limpieza/tareas/{t.pk}/", {"accion": "objeto", "descripcion_objeto": "Anteojos"})
    client.post(f"/limpieza/tareas/{t.pk}/", {"accion": "terminar"})
    t.refresh_from_db()
    habs[2].refresh_from_db()
    assert t.estado == "terminada" and habs[2].estado == "limpia"
    assert Incidencia.objects.filter(habitacion=habs[2], origen="limpieza").exists()


def test_incidencia_notifica_al_tecnico_inmediatamente(hotel, admin, mant_user, habs):
    from django.db import transaction  # noqa: F401

    inc = mant.reportar(hotel, admin, "Pierde el inodoro", habitacion=habs[0], categoria="plomeria")
    mant._post_reporte(inc.pk)  # en producción corre al confirmar la transacción
    n = Notificacion.objects.filter(usuario=mant_user, titulo__startswith="Nueva incidencia").first()
    assert n is not None and (n.creado_en - inc.reportada_en) < timedelta(minutes=1)


def test_incidencia_bloqueante(hotel, admin, mant_user, habs, huesped, hoy):
    inc = mant.reportar(hotel, admin, "Sin agua caliente", habitacion=habs[1], bloqueante=True)
    habs[1].refresh_from_db()
    assert habs[1].estado == Habitacion.Estado.FUERA_SERVICIO
    with pytest.raises(ValidationError, match="fuera de servicio"):
        services.crear_reserva(hotel, huesped, hoy, hoy + timedelta(days=1), [{"habitacion": habs[1]}], usuario=admin)
    with pytest.raises(ValidationError):
        mant.cambiar_estado(inc, "cerrada", mant_user)  # transición inválida
    mant.cambiar_estado(inc, "en_curso", mant_user)
    mant.cambiar_estado(inc, "resuelta", mant_user, "Se cambió la resistencia")
    mant.cambiar_estado(inc, "cerrada", mant_user)
    habs[1].refresh_from_db()
    assert habs[1].estado == Habitacion.Estado.SUCIA
    assert not hab.esta_bloqueada(habs[1], hoy, hoy + timedelta(days=1))


def test_repuestos_descuentan_stock_y_costo_imputado(hotel, admin, mant_user, habs):
    rep = Producto.objects.create(hotel=hotel, nombre="Flexible", costo=Decimal("4000"))
    dep = Deposito.objects.get(hotel=hotel)
    from inventario.services import registrar_movimiento

    registrar_movimiento(rep, dep, "entrada", 5, "inicial")
    activo = Activo.objects.create(
        hotel=hotel, nombre="Termotanque", habitacion=habs[0], umbral_reemplazo=Decimal("10000")
    )
    inc = mant.reportar(hotel, admin, "Pierde agua", activo=activo)
    orden = mant.registrar_trabajo(
        hotel,
        mant_user,
        "Cambio de flexible",
        incidencia=inc,
        horas=1,
        costo_mano_obra=Decimal("8000"),
        repuestos=[(rep, dep, Decimal("1"))],
    )
    assert rep.stock_total == 4
    assert orden.costo_total == Decimal("12000") and orden.habitacion == habs[0]
    mant._post_trabajo(orden.pk)
    from bi.models import Alerta

    assert Alerta.objects.filter(tipo="reemplazo_activo").exists()


def test_plan_preventivo_genera_ordenes(hotel, habs, hoy):
    activo = Activo.objects.create(hotel=hotel, nombre="Split", habitacion=habs[0])
    plan = PlanPreventivo.objects.create(
        hotel=hotel, activo_relacionado=activo, tarea="Filtros", frecuencia_dias=90, proxima_fecha=hoy
    )
    assert mant.generar_ordenes_preventivas() == 1
    assert mant.generar_ordenes_preventivas() == 0
    plan.refresh_from_db()
    assert plan.proxima_fecha == hoy + timedelta(days=90)
    assert Mantenimiento.objects.filter(plan=plan, estado="pendiente").count() == 1


def test_circuito_de_compras_actualiza_stock(hotel, admin):
    prov = Proveedor.objects.create(hotel=hotel, razon_social="Prov SA", cuit="30700000001")
    p = Producto.objects.create(hotel=hotel, nombre="Lavandina")
    oc = OrdenCompra.objects.create(hotel=hotel, proveedor=prov, deposito=Deposito.objects.get(hotel=hotel))
    it = ItemCompra.objects.create(hotel=hotel, orden=oc, producto=p, cantidad=10, precio_unitario=Decimal("3000"))
    compras.enviar_orden(oc)
    compras.recibir(oc, {it.pk: Decimal("6")}, admin)
    oc.refresh_from_db()
    assert oc.estado == "recibida_parcial" and p.stock_total == 6
    compras.recibir(oc, {it.pk: Decimal("4")}, admin)
    oc.refresh_from_db()
    p.refresh_from_db()
    assert oc.estado == "recibida" and p.stock_total == 10 and p.costo == Decimal("3000")
    compras.registrar_factura_proveedor(oc, "0001-00001234", timezone.localdate(), Decimal("30000"))
    gasto = compras.pagar_orden(oc, admin)
    oc.refresh_from_db()
    assert oc.estado == "pagada" and gasto.importe == Decimal("30000")
    assert compras.comparar_precios(p)[0]["ultimo"] == Decimal("3000")


def test_gasto_en_efectivo_sale_de_caja(hotel, admin):
    from caja import services as caja

    c = caja.abrir_caja(hotel, admin, Decimal("1000"))
    cat = CategoriaGasto.objects.create(hotel=hotel, nombre="Varios")
    compras.registrar_gasto(hotel, admin, cat, "Ferretería", Decimal("300"), medio_pago="efectivo")
    assert caja.esperado_efectivo(c)["ARS"] == Decimal("700")


def test_whatsapp_requiere_consentimiento(hotel, admin, huesped, habs, hoy):
    from reservas.models import Reserva

    r = services.crear_reserva(hotel, huesped, hoy, hoy + timedelta(days=1), [{"habitacion": habs[0]}], usuario=admin)
    services.confirmar(r)
    services._al_confirmar(r.pk)
    assert Notificacion.objects.get(reserva=r, canal="whatsapp").estado_envio == "enviado"
    huesped.consentimiento_whatsapp = False
    huesped.save()
    r2 = services.crear_reserva(
        hotel,
        huesped,
        hoy + timedelta(days=3),
        hoy + timedelta(days=4),
        [{"habitacion": habs[0]}],
        usuario=admin,
        estado=Reserva.Estado.PENDIENTE,
    )
    n = notif.enviar_whatsapp(r2, "confirmacion")
    assert n.estado_envio == "bloqueado"


def test_mensajes_programados(hotel, admin, huesped, habs, hoy):
    from reservas.models import Reserva

    services.crear_reserva(
        hotel,
        huesped,
        hoy + timedelta(days=1),
        hoy + timedelta(days=2),
        [{"habitacion": habs[1]}],
        usuario=admin,
        estado=Reserva.Estado.CONFIRMADA,
    )
    assert notif.mensajes_programados() == 1
    assert notif.mensajes_programados() == 1  # idempotente: no duplica, reporta el ya enviado
    assert Notificacion.objects.filter(canal="whatsapp", titulo__icontains="Recordatorio").count() == 1


def test_licencia_impide_turno(hotel):
    from personal.models import Empleado, Licencia, Turno

    e = Empleado.objects.create(hotel=hotel, nombre="Eva", apellido="Ruiz", dni="1", puesto="Mucama", area="limpieza")
    hoy = timezone.localdate()
    Licencia.objects.create(hotel=hotel, empleado=e, tipo="vacaciones", desde=hoy, hasta=hoy, aprobada=True)
    t = Turno(hotel=hotel, empleado=e, fecha=hoy, hora_inicio="08:00", hora_fin="16:00")
    with pytest.raises(ValidationError, match="licencia"):
        t.full_clean()

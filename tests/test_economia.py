from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from caja import services as caja
from caja.models import Caja
from facturacion import services as fact
from facturacion.models import Factura
from inventario import services as inv
from inventario.models import Deposito, Producto
from reservas import services

pytestmark = pytest.mark.django_db


@pytest.fixture
def en_curso(admin, reserva_confirmada):
    return services.checkin(reserva_confirmada, admin)


def test_arqueo_cuadra_al_centavo(hotel, admin, en_curso):
    c = caja.abrir_caja(hotel, admin, Decimal("5000.00"), Decimal("100"))
    caja.registrar_pago(en_curso, "efectivo", Decimal("3333.33"), admin)
    caja.registrar_pago(en_curso, "efectivo", Decimal("50"), admin, moneda="USD", tipo_cambio=Decimal("1200"))
    caja.registrar_pago(en_curso, "credito", Decimal("4000"), admin)  # no es efectivo
    caja.registrar_pago(en_curso, "efectivo", Decimal("0.67"), admin, tipo="devolucion")
    caja.registrar_movimiento(c, "egreso", Decimal("1000.01"), "Retiro a caja fuerte", usuario=admin)
    c = caja.cerrar_caja(c, Decimal("7332.65"), admin, monto_contado_usd=Decimal("150"))
    assert c.monto_esperado == Decimal("7332.65") and c.diferencia == 0
    assert c.monto_esperado_usd == Decimal("150") and c.diferencia_usd == 0


def test_caja_cerrada_no_admite_movimientos(hotel, admin):
    c = caja.abrir_caja(hotel, admin)
    caja.cerrar_caja(c, 0, admin)
    with pytest.raises(ValidationError, match="cerrada"):
        caja.registrar_movimiento(c, "ingreso", 10, "x", usuario=admin)


def test_efectivo_requiere_caja_abierta(admin, en_curso):
    with pytest.raises(ValidationError, match="abrir su caja"):
        caja.registrar_pago(en_curso, "efectivo", 100, admin)
    assert caja.registrar_pago(en_curso, "transferencia", 100, admin).caja is None


def test_una_caja_abierta_por_usuario(hotel, admin):
    caja.abrir_caja(hotel, admin)
    with pytest.raises(ValidationError):
        caja.abrir_caja(hotel, admin)


def test_caja_general_solo_administracion(hotel, recepcion):
    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        caja.abrir_caja(hotel, recepcion, es_general=True)


def test_saldo_y_consumos_descuentan_stock(hotel, admin, en_curso):
    p = Producto.objects.create(hotel=hotel, nombre="Agua", precio_venta=Decimal("1500"), costo=500)
    dep = Deposito.objects.get(hotel=hotel)
    inv.registrar_movimiento(p, dep, "entrada", 10, "Inicial")
    caja.registrar_cargo(en_curso, "Agua", p.precio_venta, 2, "consumo", producto=p, deposito=dep)
    assert p.stock_total == 8
    assert caja.saldo(en_curso) == Decimal("10000") + Decimal("3000")


def test_stock_no_negativo(hotel):
    p = Producto.objects.create(hotel=hotel, nombre="Jabón")
    with pytest.raises(ValidationError, match="insuficiente"):
        inv.registrar_movimiento(p, None, "salida", 1)
    hotel.permitir_stock_negativo = True
    hotel.save()
    p.refresh_from_db()
    assert inv.registrar_movimiento(p, None, "salida", 1).saldo_resultante == -1


def test_factura_b_con_cae_simulado(admin, en_curso):
    f = fact.facturar_reserva(en_curso, emitir_ahora=False)
    assert f.tipo == 6 and f.letra == "B"
    f = fact.emitir(f)
    assert f.estado == Factura.Estado.AUTORIZADA and len(f.cae) == 14 and f.numero == 1
    assert f.neto_gravado + f.iva == f.total == Decimal("10000")
    assert f.iva == Decimal("1735.54")
    assert not en_curso.cargos.filter(factura__isnull=True).exists()
    with pytest.raises(ValidationError, match="ya fue facturado|No hay cargos"):
        fact.facturar_reserva(en_curso)


def test_factura_a_para_responsable_inscripto(admin, en_curso):
    h = en_curso.titular
    h.condicion_iva, h.cuit, h.razon_social = "RI", "30700000001", "Empresa SA"
    h.save()
    f = fact.emitir(fact.facturar_reserva(en_curso, emitir_ahora=False))
    assert f.tipo == 1 and f.receptor_doc_tipo == 80


def test_factura_c_para_monotributista(hotel, admin, en_curso):
    hotel.condicion_iva = "MT"
    hotel.save()
    en_curso.refresh_from_db()
    f = fact.emitir(fact.facturar_reserva(en_curso, emitir_ahora=False))
    assert f.tipo == 11 and f.iva == 0 and f.neto_gravado == f.total


def test_factura_con_cae_es_inmutable_y_nota_de_credito(admin, en_curso):
    f = fact.emitir(fact.facturar_reserva(en_curso, emitir_ahora=False))
    f.total = Decimal("1")
    with pytest.raises(ValidationError, match="inmutable"):
        f.save()
    f.refresh_from_db()
    with pytest.raises(ValidationError):
        f.delete()
    nc = fact.emitir(fact.nota_credito(f, "Error en tarifa", Decimal("2000"), emitir_ahora=False))
    assert nc.tipo == 8 and nc.estado == "autorizada" and nc.total == Decimal("2000")
    with pytest.raises(ValidationError):
        fact.nota_credito(f, "Exceso", Decimal("9000"))


def test_arca_caido_queda_en_cola_sin_bloquear(monkeypatch, admin, en_curso):
    from facturacion import arca

    def falla(*a, **k):
        raise arca.ArcaError("Timeout")

    monkeypatch.setattr(arca.ClienteSimulado, "ultimo_autorizado", falla)
    services.checkout(en_curso, admin, autorizar_saldo=True)
    f = fact.emitir(fact.facturar_reserva(en_curso, emitir_ahora=False))
    assert f.estado == Factura.Estado.PENDIENTE and f.intentos == 1 and f.proximo_intento
    from notificaciones.models import Notificacion

    assert Notificacion.objects.filter(titulo="Facturación electrónica").exists()
    monkeypatch.undo()
    Factura.objects.filter(pk=f.pk).update(proximo_intento=None)
    assert fact.reintentar_pendientes() == 1


def test_turista_extranjero_exento(admin, en_curso):
    f = fact.emitir(fact.facturar_reserva(en_curso, emitir_ahora=False, extranjero_exento=True))
    assert f.iva == 0 and f.exento == f.total


def test_qr_arca(admin, en_curso):
    f = fact.emitir(fact.facturar_reserva(en_curso, emitir_ahora=False))
    assert fact.qr_arca(f).startswith("https://www.afip.gob.ar/fe/qr/?p=")


def test_exportaciones_cierre(cliente_admin, hotel, admin, en_curso):
    c = caja.abrir_caja(hotel, admin, Decimal("100"))
    caja.registrar_pago(en_curso, "efectivo", Decimal("500"), admin)
    caja.cerrar_caja(c, Decimal("600"), admin)
    pdf = cliente_admin.get(f"/caja/cajas/{c.pk}/?formato=pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    xlsx = cliente_admin.get(f"/caja/cajas/{c.pk}/?formato=xlsx")
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    assert Caja.objects.get(pk=c.pk).diferencia == 0


def test_libro_iva(hotel, admin, en_curso, hoy):
    f = fact.emitir(fact.facturar_reserva(en_curso, emitir_ahora=False))
    fact.emitir(fact.nota_credito(f, "Ajuste", Decimal("1000"), emitir_ahora=False))
    filas, tot = fact.libro_iva_ventas(hotel, hoy - timedelta(days=1), hoy)
    assert len(filas) == 2 and tot["total"] == Decimal("9000")

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Deposito, MovimientoStock, Stock


def deposito_por_defecto(hotel):
    deposito = Deposito.objects.filter(hotel=hotel, activo=True).order_by("id").first()
    if deposito is None:
        deposito = Deposito.objects.create(hotel=hotel, nombre="Depósito principal")
    return deposito


@transaction.atomic
def registrar_movimiento(
    producto, deposito, tipo, cantidad, motivo="", usuario=None, referencia="", costo_unitario=None
):
    """Entrada, salida o ajuste. El stock no puede quedar negativo salvo que el hotel lo permita."""
    hotel = producto.hotel
    deposito = deposito or deposito_por_defecto(hotel)
    if deposito.hotel_id != hotel.id:
        raise ValidationError("El depósito no pertenece al hotel del producto.")
    cantidad = Decimal(cantidad)
    if tipo != MovimientoStock.Tipo.AJUSTE and cantidad <= 0:
        raise ValidationError("La cantidad debe ser mayor a cero.")
    stock, _ = Stock.objects.select_for_update().get_or_create(
        producto=producto, deposito=deposito, defaults={"hotel": hotel}
    )
    delta = -cantidad if tipo == MovimientoStock.Tipo.SALIDA else cantidad
    nuevo = stock.cantidad + delta
    if nuevo < 0 and not hotel.permitir_stock_negativo:
        raise ValidationError(
            f"Stock insuficiente de {producto} en {deposito}: hay {stock.cantidad}, se pidieron {cantidad}."
        )
    stock.cantidad = nuevo
    stock.save(update_fields=["cantidad", "actualizado_en"])
    if costo_unitario is not None and tipo == MovimientoStock.Tipo.ENTRADA:
        producto.costo = costo_unitario
        producto.save(update_fields=["costo", "actualizado_en"])
    mov = MovimientoStock.objects.create(
        hotel=hotel,
        producto=producto,
        deposito=deposito,
        tipo=tipo,
        cantidad=cantidad,
        motivo=motivo,
        referencia=referencia,
        costo_unitario=costo_unitario,
        saldo_resultante=nuevo,
        creado_por=usuario,
    )
    if nuevo <= producto.stock_minimo and producto.stock_minimo > 0:
        from bi import services as bi

        transaction.on_commit(lambda: bi.alerta_stock_bajo(producto))
    return mov


def productos_bajo_minimo(hotel):
    from django.db.models import DecimalField, F, Sum, Value
    from django.db.models.functions import Coalesce

    from .models import Producto

    return (
        Producto.objects.filter(hotel=hotel, activo=True, stock_minimo__gt=0)
        .annotate(total=Coalesce(Sum("stocks__cantidad"), Value(Decimal("0")), output_field=DecimalField()))
        .filter(total__lte=F("stock_minimo"))
    )

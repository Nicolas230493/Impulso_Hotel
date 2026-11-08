from decimal import Decimal

from django.db import models

from core.models import ModeloHotel


class Deposito(ModeloHotel):
    nombre = models.CharField(max_length=80)
    descripcion = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "depósito"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Producto(ModeloHotel):
    class Categoria(models.TextChoices):
        MINIBAR = "minibar", "Minibar / tienda"
        RESTAURANTE = "restaurante", "Restaurante / bar"
        LIMPIEZA = "limpieza", "Insumos de limpieza"
        AMENITIES = "amenities", "Amenities"
        BLANCOS = "blancos", "Ropa blanca"
        REPUESTOS = "repuestos", "Repuestos de mantenimiento"
        OFICINA = "oficina", "Librería / oficina"
        OTRO = "otro", "Otro"

    codigo = models.CharField("código", max_length=40, blank=True)
    nombre = models.CharField(max_length=150)
    categoria = models.CharField("categoría", max_length=15, choices=Categoria.choices, default=Categoria.OTRO)
    unidad = models.CharField(max_length=20, default="unidad")
    costo = models.DecimalField("último costo", max_digits=12, decimal_places=2, default=Decimal("0"))
    precio_venta = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Si se vende al huésped (minibar, restaurante).",
    )
    alicuota_iva = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("21"))
    stock_minimo = models.DecimalField("stock mínimo", max_digits=12, decimal_places=2, default=Decimal("0"))

    class Meta:
        ordering = ["nombre"]
        db_table = "productos"

    def __str__(self):
        return self.nombre

    @property
    def stock_total(self):
        return self.stocks.aggregate(t=models.Sum("cantidad"))["t"] or Decimal("0")

    @property
    def vendible(self):
        return self.precio_venta is not None


class Stock(ModeloHotel):
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="stocks")
    deposito = models.ForeignKey(Deposito, on_delete=models.PROTECT, related_name="stocks")
    cantidad = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    class Meta:
        db_table = "inventario"
        verbose_name = "stock por depósito"
        constraints = [models.UniqueConstraint(fields=["producto", "deposito"], name="stock_unico")]

    def __str__(self):
        return f"{self.producto} @ {self.deposito}: {self.cantidad}"


class MovimientoStock(ModeloHotel):
    class Tipo(models.TextChoices):
        ENTRADA = "entrada", "Entrada"
        SALIDA = "salida", "Salida"
        AJUSTE = "ajuste", "Ajuste (+/−)"

    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="movimientos")
    deposito = models.ForeignKey(Deposito, on_delete=models.PROTECT, related_name="movimientos")
    tipo = models.CharField(max_length=8, choices=Tipo.choices)
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)
    costo_unitario = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    motivo = models.CharField(max_length=200, blank=True)
    referencia = models.CharField(max_length=100, blank=True)
    saldo_resultante = models.DecimalField(max_digits=12, decimal_places=2, editable=False, default=Decimal("0"))

    class Meta:
        db_table = "movimientos_stock"
        verbose_name = "movimiento de stock"
        verbose_name_plural = "movimientos de stock"
        ordering = ["-creado_en"]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.cantidad} {self.producto}"

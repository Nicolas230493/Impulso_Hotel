from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import ModeloHotel


class Proveedor(ModeloHotel):
    class CondicionIVA(models.TextChoices):
        RESPONSABLE_INSCRIPTO = "RI", "Responsable inscripto"
        MONOTRIBUTO = "MT", "Monotributo"
        EXENTO = "EX", "IVA exento"
        CONSUMIDOR_FINAL = "CF", "Consumidor final"

    razon_social = models.CharField("razón social", max_length=200)
    cuit = models.CharField("CUIT", max_length=13)
    condicion_iva = models.CharField(
        "condición IVA", max_length=2, choices=CondicionIVA.choices, default=CondicionIVA.RESPONSABLE_INSCRIPTO
    )
    rubro = models.CharField(max_length=100, blank=True)
    contacto = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    telefono = models.CharField("teléfono", max_length=50, blank=True)
    direccion = models.CharField("dirección", max_length=250, blank=True)
    cbu_alias = models.CharField("CBU / alias", max_length=60, blank=True)

    class Meta:
        verbose_name_plural = "proveedores"
        ordering = ["razon_social"]
        db_table = "proveedores"
        constraints = [
            models.UniqueConstraint(
                fields=["hotel", "cuit"], condition=models.Q(activo=True), name="proveedor_cuit_unico_por_hotel"
            )
        ]

    def __str__(self):
        return self.razon_social


class CategoriaGasto(ModeloHotel):
    nombre = models.CharField(max_length=80)

    class Meta:
        verbose_name = "categoría de gasto"
        verbose_name_plural = "categorías de gasto"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Gasto(ModeloHotel):
    MEDIOS = [
        ("efectivo", "Efectivo"),
        ("transferencia", "Transferencia"),
        ("debito", "Débito"),
        ("credito", "Tarjeta de crédito"),
        ("cheque", "Cheque"),
        ("billetera", "Billetera virtual"),
    ]

    fecha = models.DateField(default=timezone.localdate)
    categoria = models.ForeignKey(
        CategoriaGasto, on_delete=models.PROTECT, related_name="gastos", verbose_name="categoría"
    )
    proveedor = models.ForeignKey(Proveedor, null=True, blank=True, on_delete=models.PROTECT, related_name="gastos")
    descripcion = models.CharField("descripción", max_length=250)
    importe = models.DecimalField(max_digits=12, decimal_places=2)
    moneda = models.CharField(max_length=3, default="ARS", choices=[("ARS", "ARS"), ("USD", "USD")])
    medio_pago = models.CharField(max_length=15, choices=MEDIOS, default="transferencia")
    nro_comprobante = models.CharField("Nº de comprobante", max_length=40, blank=True)
    comprobante = models.FileField(upload_to="comprobantes/%Y/%m/", blank=True)
    orden_compra = models.ForeignKey(
        "OrdenCompra", null=True, blank=True, on_delete=models.SET_NULL, related_name="pagos"
    )

    class Meta:
        db_table = "gastos"
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return f"{self.fecha:%d/%m/%Y} {self.descripcion} $ {self.importe}"


class SolicitudCompra(ModeloHotel):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        APROBADA = "aprobada", "Aprobada"
        RECHAZADA = "rechazada", "Rechazada"
        CONVERTIDA = "convertida", "Convertida en orden"

    fecha = models.DateField(default=timezone.localdate)
    solicitante = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    area = models.CharField("área", max_length=60, blank=True)
    motivo = models.TextField(blank=True)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PENDIENTE)

    class Meta:
        verbose_name = "solicitud de compra"
        verbose_name_plural = "solicitudes de compra"
        db_table = "solicitudes_compra"
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return f"Solicitud #{self.pk} ({self.get_estado_display()})"


class ItemSolicitud(ModeloHotel):
    solicitud = models.ForeignKey(SolicitudCompra, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey("inventario.Producto", on_delete=models.PROTECT, related_name="+")
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.cantidad} × {self.producto}"


class OrdenCompra(ModeloHotel):
    class Estado(models.TextChoices):
        BORRADOR = "borrador", "Borrador"
        ENVIADA = "enviada", "Enviada al proveedor"
        RECIBIDA_PARCIAL = "recibida_parcial", "Recibida parcialmente"
        RECIBIDA = "recibida", "Recibida"
        FACTURADA = "facturada", "Facturada"
        PAGADA = "pagada", "Pagada"
        ANULADA = "anulada", "Anulada"

    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name="ordenes")
    solicitud = models.ForeignKey(
        SolicitudCompra, null=True, blank=True, on_delete=models.SET_NULL, related_name="ordenes"
    )
    fecha = models.DateField(default=timezone.localdate)
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.BORRADOR)
    deposito = models.ForeignKey("inventario.Deposito", on_delete=models.PROTECT, related_name="+")
    observaciones = models.TextField(blank=True)
    # Factura del proveedor
    factura_numero = models.CharField(max_length=40, blank=True)
    factura_fecha = models.DateField(null=True, blank=True)
    factura_importe = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    factura_archivo = models.FileField(upload_to="facturas_proveedor/%Y/%m/", blank=True)

    class Meta:
        verbose_name = "orden de compra"
        verbose_name_plural = "órdenes de compra"
        db_table = "compras"
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return f"OC #{self.pk} · {self.proveedor}"

    @property
    def total(self):
        return sum((i.subtotal for i in self.items.filter(activo=True)), Decimal("0"))

    @property
    def total_pagado(self):
        return self.pagos.filter(activo=True).aggregate(t=models.Sum("importe"))["t"] or Decimal("0")


class ItemCompra(ModeloHotel):
    orden = models.ForeignKey(OrdenCompra, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey("inventario.Producto", on_delete=models.PROTECT, related_name="items_compra")
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    cantidad_recibida = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    class Meta:
        db_table = "items_compra"

    def __str__(self):
        return f"{self.cantidad} × {self.producto}"

    @property
    def subtotal(self):
        return (self.cantidad * self.precio_unitario).quantize(Decimal("0.01"))

    @property
    def pendiente(self):
        return self.cantidad - self.cantidad_recibida

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import ModeloHotel

MONEDAS = [("ARS", "ARS"), ("USD", "USD")]


class CuentaCorriente(ModeloHotel):
    """Empresa con cuenta corriente: puede retirarse con saldo pendiente y se le factura a ella."""

    razon_social = models.CharField(max_length=200)
    cuit = models.CharField("CUIT", max_length=13)
    condicion_iva = models.CharField(
        max_length=3,
        default="RI",
        choices=[
            ("RI", "Responsable inscripto"),
            ("MT", "Monotributo"),
            ("EX", "IVA exento"),
            ("CF", "Consumidor final"),
        ],
    )
    direccion = models.CharField(max_length=250, blank=True)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=50, blank=True)
    limite_credito = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "cuenta corriente de empresa"
        verbose_name_plural = "cuentas corrientes de empresas"
        ordering = ["razon_social"]

    def __str__(self):
        return f"{self.razon_social} ({self.cuit})"


class Cargo(ModeloHotel):
    class Origen(models.TextChoices):
        NOCHE = "noche", "Alojamiento (noche)"
        EXTRA = "extra", "Servicio extra"
        CONSUMO = "consumo", "Consumo (minibar / tienda)"
        RESTAURANTE = "restaurante", "Restaurante"
        AJUSTE = "ajuste", "Ajuste / descuento"

    reserva = models.ForeignKey("reservas.Reserva", on_delete=models.PROTECT, related_name="cargos")
    detalle = models.ForeignKey(
        "reservas.DetalleReserva", null=True, blank=True, on_delete=models.PROTECT, related_name="cargos"
    )
    concepto = models.CharField(max_length=200)
    fecha = models.DateField(default=timezone.localdate)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1"))
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    importe = models.DecimalField(max_digits=12, decimal_places=2)
    alicuota_iva = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("21"))
    origen = models.CharField(max_length=12, choices=Origen.choices, default=Origen.EXTRA)
    producto = models.ForeignKey(
        "inventario.Producto", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    factura = models.ForeignKey(
        "facturacion.Factura", null=True, blank=True, on_delete=models.SET_NULL, related_name="cargos"
    )

    class Meta:
        ordering = ["fecha", "id"]
        db_table = "cargos"
        constraints = [
            models.UniqueConstraint(
                fields=["detalle", "fecha"],
                condition=models.Q(origen="noche", activo=True),
                name="un_cargo_noche_por_habitacion_y_fecha",
            ),
        ]

    def __str__(self):
        return f"{self.fecha:%d/%m} {self.concepto} $ {self.importe}"

    def save(self, *args, **kwargs):
        self.importe = (Decimal(self.cantidad) * Decimal(self.precio_unitario)).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)


class Caja(ModeloHotel):
    class Estado(models.TextChoices):
        ABIERTA = "abierta", "Abierta"
        CERRADA = "cerrada", "Cerrada"

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cajas")
    es_general = models.BooleanField("caja general", default=False)
    turno = models.CharField(max_length=30, blank=True, help_text="Mañana, tarde, noche…")
    estado = models.CharField(max_length=8, choices=Estado.choices, default=Estado.ABIERTA)
    apertura = models.DateTimeField(default=timezone.now)
    cierre = models.DateTimeField(null=True, blank=True)
    monto_inicial = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    monto_inicial_usd = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    monto_esperado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    monto_esperado_usd = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    monto_contado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    monto_contado_usd = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    diferencia = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    diferencia_usd = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    observaciones = models.TextField(blank=True)

    class Meta:
        db_table = "cajas"
        ordering = ["-apertura"]
        permissions = [("ver_caja_general", "Puede ver la caja general y todas las cajas")]
        constraints = [
            models.UniqueConstraint(
                fields=["hotel", "usuario"],
                condition=models.Q(estado="abierta", activo=True),
                name="una_caja_abierta_por_usuario",
            ),
        ]

    def __str__(self):
        tipo = "General" if self.es_general else f"Caja {self.usuario}"
        return f"{tipo} · {timezone.localtime(self.apertura):%d/%m/%Y %H:%M}"


class Pago(ModeloHotel):
    class Medio(models.TextChoices):
        EFECTIVO = "efectivo", "Efectivo"
        DEBITO = "debito", "Tarjeta de débito"
        CREDITO = "credito", "Tarjeta de crédito"
        TRANSFERENCIA = "transferencia", "Transferencia"
        BILLETERA = "billetera", "Billetera virtual (Mercado Pago, MODO…)"
        CUENTA_CORRIENTE = "cta_cte", "Cuenta corriente"

    class Tipo(models.TextChoices):
        PAGO = "pago", "Pago"
        SENA = "sena", "Seña"
        DEVOLUCION = "devolucion", "Devolución"

    reserva = models.ForeignKey("reservas.Reserva", on_delete=models.PROTECT, related_name="pagos")
    fecha = models.DateTimeField(default=timezone.now)
    medio = models.CharField(max_length=15, choices=Medio.choices)
    tipo = models.CharField(max_length=12, choices=Tipo.choices, default=Tipo.PAGO)
    importe = models.DecimalField(max_digits=12, decimal_places=2, help_text="En la moneda del pago")
    moneda = models.CharField(max_length=3, choices=MONEDAS, default="ARS")
    tipo_cambio = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("1"))
    importe_ars = models.DecimalField(max_digits=12, decimal_places=2, editable=False)
    referencia = models.CharField(max_length=100, blank=True, help_text="Nº de cupón, transferencia, etc.")
    caja = models.ForeignKey(Caja, null=True, blank=True, on_delete=models.PROTECT, related_name="pagos")

    class Meta:
        db_table = "pagos"
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.moneda} {self.importe} ({self.get_medio_display()})"

    def save(self, *args, **kwargs):
        if self.moneda == "ARS":
            self.tipo_cambio = Decimal("1")
        self.importe_ars = (Decimal(self.importe) * Decimal(self.tipo_cambio)).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)

    @property
    def signo(self):
        return -1 if self.tipo == self.Tipo.DEVOLUCION else 1


class MovimientoCaja(ModeloHotel):
    class Tipo(models.TextChoices):
        INGRESO = "ingreso", "Ingreso"
        EGRESO = "egreso", "Egreso"

    caja = models.ForeignKey(Caja, on_delete=models.PROTECT, related_name="movimientos")
    fecha = models.DateTimeField(default=timezone.now)
    tipo = models.CharField(max_length=8, choices=Tipo.choices)
    medio = models.CharField(max_length=15, choices=Pago.Medio.choices, default=Pago.Medio.EFECTIVO)
    importe = models.DecimalField(max_digits=12, decimal_places=2)
    moneda = models.CharField(max_length=3, choices=MONEDAS, default="ARS")
    concepto = models.CharField(max_length=200)
    referencia = models.CharField(max_length=100, blank=True)
    pago = models.ForeignKey(Pago, null=True, blank=True, on_delete=models.PROTECT, related_name="movimientos")
    gasto = models.ForeignKey(
        "compras.Gasto", null=True, blank=True, on_delete=models.PROTECT, related_name="movimientos"
    )

    class Meta:
        db_table = "movimientos_caja"
        ordering = ["fecha"]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.moneda} {self.importe} · {self.concepto}"

    def save(self, *args, **kwargs):
        if not self.pk and self.caja.estado != Caja.Estado.ABIERTA:
            raise ValidationError("La caja está cerrada: no admite movimientos.")
        super().save(*args, **kwargs)

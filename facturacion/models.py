from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import ModeloHotel


class TipoComprobante(models.IntegerChoices):
    FACTURA_A = 1, "Factura A"
    NOTA_DEBITO_A = 2, "Nota de débito A"
    NOTA_CREDITO_A = 3, "Nota de crédito A"
    FACTURA_B = 6, "Factura B"
    NOTA_DEBITO_B = 7, "Nota de débito B"
    NOTA_CREDITO_B = 8, "Nota de crédito B"
    FACTURA_C = 11, "Factura C"
    NOTA_DEBITO_C = 12, "Nota de débito C"
    NOTA_CREDITO_C = 13, "Nota de crédito C"


NOTAS_CREDITO = {
    TipoComprobante.FACTURA_A: TipoComprobante.NOTA_CREDITO_A,
    TipoComprobante.FACTURA_B: TipoComprobante.NOTA_CREDITO_B,
    TipoComprobante.FACTURA_C: TipoComprobante.NOTA_CREDITO_C,
}

LETRA = {1: "A", 2: "A", 3: "A", 6: "B", 7: "B", 8: "B", 11: "C", 12: "C", 13: "C"}


class TipoDocumentoARCA(models.IntegerChoices):
    CUIT = 80, "CUIT"
    CUIL = 86, "CUIL"
    CDI = 87, "CDI"
    PASAPORTE = 94, "Pasaporte"
    DNI = 96, "DNI"
    SIN_IDENTIFICAR = 99, "Sin identificar / consumidor final"


class CondicionIVAReceptor(models.IntegerChoices):
    RESPONSABLE_INSCRIPTO = 1, "IVA Responsable inscripto"
    EXENTO = 4, "IVA Sujeto exento"
    CONSUMIDOR_FINAL = 5, "Consumidor final"
    MONOTRIBUTO = 6, "Responsable monotributo"
    NO_CATEGORIZADO = 7, "Sujeto no categorizado"
    CLIENTE_EXTERIOR = 9, "Cliente del exterior"


class PuntoVenta(ModeloHotel):
    numero = models.PositiveIntegerField("número")
    descripcion = models.CharField(max_length=100, blank=True)
    tipos_habilitados = models.JSONField(
        default=list, blank=True, help_text="Códigos ARCA habilitados, ej. [6, 8] para Factura B y NC B."
    )
    por_defecto = models.BooleanField(default=False)

    class Meta:
        verbose_name = "punto de venta"
        verbose_name_plural = "puntos de venta"
        db_table = "puntos_venta"
        ordering = ["numero"]
        constraints = [models.UniqueConstraint(fields=["hotel", "numero"], name="punto_venta_unico")]

    def __str__(self):
        return f"{self.numero:05d} {self.descripcion}".strip()


class Factura(ModeloHotel):
    class Estado(models.TextChoices):
        BORRADOR = "borrador", "Borrador"
        PENDIENTE = "pendiente", "En cola (ARCA no respondió)"
        AUTORIZADA = "autorizada", "Autorizada (con CAE)"
        RECHAZADA = "rechazada", "Rechazada por ARCA"
        ANULADA = "anulada", "Borrador anulado"

    CAMPOS_FISCALES = (
        "tipo",
        "punto_venta_id",
        "numero",
        "fecha",
        "receptor_nombre",
        "receptor_doc_tipo",
        "receptor_doc_nro",
        "receptor_condicion_iva",
        "neto_gravado",
        "exento",
        "iva",
        "total",
        "moneda",
        "cotizacion",
        "cae",
        "cae_vencimiento",
        "factura_asociada_id",
    )

    punto_venta = models.ForeignKey(PuntoVenta, on_delete=models.PROTECT, related_name="facturas")
    tipo = models.PositiveSmallIntegerField(choices=TipoComprobante.choices)
    numero = models.PositiveIntegerField("número", null=True, blank=True)
    fecha = models.DateField(default=timezone.localdate)
    concepto = models.PositiveSmallIntegerField(
        default=3, choices=[(1, "Productos"), (2, "Servicios"), (3, "Productos y servicios")]
    )
    servicio_desde = models.DateField(null=True, blank=True)
    servicio_hasta = models.DateField(null=True, blank=True)
    receptor_nombre = models.CharField(max_length=200)
    receptor_doc_tipo = models.PositiveSmallIntegerField(
        choices=TipoDocumentoARCA.choices, default=TipoDocumentoARCA.SIN_IDENTIFICAR
    )
    receptor_doc_nro = models.CharField(max_length=20, default="0")
    receptor_condicion_iva = models.PositiveSmallIntegerField(
        choices=CondicionIVAReceptor.choices, default=CondicionIVAReceptor.CONSUMIDOR_FINAL
    )
    receptor_domicilio = models.CharField(max_length=250, blank=True)
    neto_gravado = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    exento = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    iva = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    moneda = models.CharField(max_length=3, default="ARS")
    cotizacion = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("1"))
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.BORRADOR)
    cae = models.CharField("CAE", max_length=20, blank=True)
    cae_vencimiento = models.DateField("vencimiento CAE", null=True, blank=True)
    observaciones_arca = models.TextField(blank=True)
    intentos = models.PositiveSmallIntegerField(default=0)
    proximo_intento = models.DateTimeField(null=True, blank=True)
    reserva = models.ForeignKey(
        "reservas.Reserva", null=True, blank=True, on_delete=models.PROTECT, related_name="facturas"
    )
    factura_asociada = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="notas_credito"
    )
    motivo = models.CharField(max_length=250, blank=True, help_text="Motivo de la nota de crédito")
    simulada = models.BooleanField(default=False, help_text="Emitida en modo simulado (sin validez fiscal).")

    class Meta:
        db_table = "facturas"
        ordering = ["-fecha", "-id"]
        permissions = [("emitir_factura", "Puede emitir comprobantes electrónicos")]
        constraints = [
            models.UniqueConstraint(
                fields=["punto_venta", "tipo", "numero"],
                condition=models.Q(numero__isnull=False),
                name="numeracion_unica",
            ),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.numero_formateado}"

    @property
    def letra(self):
        return LETRA.get(self.tipo, "")

    @property
    def es_nota_credito(self):
        return self.tipo in (3, 8, 13)

    @property
    def numero_formateado(self):
        pv = self.punto_venta.numero if self.punto_venta_id else 0
        return f"{pv:05d}-{self.numero:08d}" if self.numero else f"{pv:05d}-(sin número)"

    def save(self, *args, **kwargs):
        if self.pk:
            original = Factura.objects.filter(pk=self.pk).values(*self.CAMPOS_FISCALES, "estado", "activo").first()
            if original and original["cae"]:
                for campo in self.CAMPOS_FISCALES:
                    if getattr(self, campo) != original[campo]:
                        raise ValidationError(
                            "Una factura con CAE es inmutable: corríjala emitiendo una nota de crédito."
                        )
                if not self.activo:
                    raise ValidationError("Una factura con CAE no se puede dar de baja.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.cae:
            raise ValidationError("Una factura con CAE no se puede eliminar: emita una nota de crédito.")
        super().delete(*args, **kwargs)


class ItemFactura(ModeloHotel):
    factura = models.ForeignKey(Factura, on_delete=models.PROTECT, related_name="items")
    descripcion = models.CharField("descripción", max_length=250)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1"))
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2, help_text="Precio final (IVA incluido)")
    alicuota_iva = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("21"), help_text="0 = exento")
    neto = models.DecimalField(max_digits=12, decimal_places=2)
    iva = models.DecimalField(max_digits=12, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = "items_factura"

    def __str__(self):
        return self.descripcion

    def save(self, *args, **kwargs):
        if self.pk and self.factura.cae:
            raise ValidationError("Los ítems de una factura con CAE son inmutables.")
        super().save(*args, **kwargs)


class TicketAcceso(models.Model):
    """Ticket de acceso de WSAA (token y sign), válido unas 12 horas."""

    cuit = models.CharField(max_length=11)
    servicio = models.CharField(max_length=20, default="wsfe")
    modo = models.CharField(max_length=15)
    token = models.TextField()
    sign = models.TextField()
    expiracion = models.DateTimeField()
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-expiracion"]

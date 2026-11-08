from django.db import models
from django.utils import timezone

from core.models import ModeloHotel


class Huesped(ModeloHotel):
    class TipoDoc(models.TextChoices):
        DNI = "DNI", "DNI"
        PASAPORTE = "PAS", "Pasaporte"
        CUIT = "CUIT", "CUIT"
        CUIL = "CUIL", "CUIL"
        LE = "LE", "Libreta de enrolamiento"
        LC = "LC", "Libreta cívica"
        CI = "CI", "Cédula de identidad extranjera"
        OTRO = "OTRO", "Otro"

    class CondicionIVA(models.TextChoices):
        CONSUMIDOR_FINAL = "CF", "Consumidor final"
        RESPONSABLE_INSCRIPTO = "RI", "Responsable inscripto"
        MONOTRIBUTO = "MT", "Monotributo"
        EXENTO = "EX", "IVA exento"
        EXTERIOR = "EXT", "Cliente del exterior"

    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    tipo_doc = models.CharField("tipo de documento", max_length=5, choices=TipoDoc.choices, default=TipoDoc.DNI)
    nro_doc = models.CharField("número de documento", max_length=30)
    nacionalidad = models.CharField(max_length=60, default="Argentina")
    email = models.EmailField(blank=True)
    telefono = models.CharField(
        "teléfono", max_length=50, blank=True, help_text="Con código de país, ej. +5491122334455"
    )
    fecha_nacimiento = models.DateField(null=True, blank=True)
    direccion = models.CharField("dirección", max_length=250, blank=True)
    localidad = models.CharField(max_length=120, blank=True)
    provincia = models.CharField(max_length=120, blank=True)
    pais_residencia = models.CharField("país de residencia", max_length=60, default="Argentina")
    condicion_iva = models.CharField(
        "condición frente al IVA", max_length=3, choices=CondicionIVA.choices, default=CondicionIVA.CONSUMIDOR_FINAL
    )
    cuit = models.CharField("CUIT para facturar", max_length=13, blank=True)
    razon_social = models.CharField("razón social para facturar", max_length=200, blank=True)
    preferencias = models.TextField(blank=True)
    notas_internas = models.TextField(blank=True)
    # Ley 25.326 de Protección de Datos Personales
    consentimiento_datos = models.BooleanField("consiente el tratamiento de sus datos", default=False)
    consentimiento_datos_fecha = models.DateTimeField(null=True, blank=True)
    consentimiento_whatsapp = models.BooleanField("acepta mensajes por WhatsApp", default=False)
    consentimiento_whatsapp_fecha = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "huésped"
        verbose_name_plural = "huéspedes"
        ordering = ["apellido", "nombre"]
        db_table = "huespedes"
        constraints = [
            models.UniqueConstraint(
                fields=["hotel", "tipo_doc", "nro_doc"],
                condition=models.Q(activo=True),
                name="huesped_documento_unico_por_hotel",
            ),
        ]
        indexes = [models.Index(fields=["hotel", "apellido"]), models.Index(fields=["hotel", "nro_doc"])]

    def __str__(self):
        return f"{self.apellido}, {self.nombre}"

    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}"

    @property
    def es_extranjero(self):
        return (self.pais_residencia or "").strip().lower() not in ("argentina", "ar", "")

    def save(self, *args, **kwargs):
        self.nro_doc = (self.nro_doc or "").replace(".", "").replace(" ", "").upper()
        ahora = timezone.now()
        if self.consentimiento_datos and not self.consentimiento_datos_fecha:
            self.consentimiento_datos_fecha = ahora
        if not self.consentimiento_datos:
            self.consentimiento_datos_fecha = None
        if self.consentimiento_whatsapp and not self.consentimiento_whatsapp_fecha:
            self.consentimiento_whatsapp_fecha = ahora
        if not self.consentimiento_whatsapp:
            self.consentimiento_whatsapp_fecha = None
        super().save(*args, **kwargs)

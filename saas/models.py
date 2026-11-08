from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

MODULOS = [
    ("reservas", "Reservas, recepción y huéspedes"),
    ("caja", "Caja, pagos y cuenta del huésped"),
    ("facturacion", "Facturación electrónica ARCA"),
    ("inventario", "Inventario"),
    ("compras", "Gastos, proveedores y compras"),
    ("limpieza", "Limpieza"),
    ("mantenimiento", "Mantenimiento"),
    ("personal", "Personal"),
    ("whatsapp", "WhatsApp Business"),
    ("bi", "Dashboards e inteligencia de negocios"),
    ("ia", "Predicción, tarifas inteligentes y mantenimiento predictivo"),
    ("multi_hotel", "Multi-hotel / consolidado de cadena"),
    ("api", "API REST"),
]


class Plan(models.Model):
    nombre = models.CharField(max_length=60, unique=True)
    publico_objetivo = models.CharField("público objetivo", max_length=150, blank=True)
    max_habitaciones = models.PositiveIntegerField(null=True, blank=True, help_text="Vacío = sin límite")
    max_hoteles = models.PositiveIntegerField(default=1)
    modulos = models.JSONField(default=list, help_text="Códigos de módulos incluidos")
    precio_mensual = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0"), help_text="A definir tras el estudio de competidores"
    )
    moneda = models.CharField(max_length=3, default="ARS")
    dias_prueba = models.PositiveSmallIntegerField(default=30)
    soporte_prioritario = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name_plural = "planes"
        ordering = ["orden"]

    def __str__(self):
        return self.nombre

    def incluye(self, modulo):
        return modulo in (self.modulos or [])


class Suscripcion(models.Model):
    class Estado(models.TextChoices):
        PRUEBA = "prueba", "Período de prueba"
        ACTIVA = "activa", "Activa"
        MOROSA = "morosa", "Pago pendiente (en gracia)"
        SUSPENDIDA = "suspendida", "Suspendida (solo lectura)"
        CANCELADA = "cancelada", "Cancelada (solo lectura)"

    ESTADOS_SOLO_LECTURA = (Estado.SUSPENDIDA, Estado.CANCELADA)
    DIAS_GRACIA = 7

    empresa = models.OneToOneField("core.Empresa", on_delete=models.PROTECT, related_name="suscripcion")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="suscripciones")
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PRUEBA)
    inicio = models.DateField(default=timezone.localdate)
    fin_prueba = models.DateField(null=True, blank=True)
    proximo_cobro = models.DateField(null=True, blank=True)
    moroso_desde = models.DateField(null=True, blank=True)
    medio_pago_token = models.CharField(
        max_length=200, blank=True, help_text="Token del medio de pago en la pasarela (nunca datos de tarjeta)"
    )
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "suscripción"
        verbose_name_plural = "suscripciones"

    def __str__(self):
        return f"{self.empresa} – {self.plan} ({self.get_estado_display()})"

    @property
    def solo_lectura(self):
        return self.estado in self.ESTADOS_SOLO_LECTURA


class CobroSuscripcion(models.Model):
    suscripcion = models.ForeignKey(Suscripcion, on_delete=models.PROTECT, related_name="cobros")
    fecha = models.DateTimeField(default=timezone.now)
    periodo = models.CharField(max_length=7, help_text="AAAA-MM")
    importe = models.DecimalField(max_digits=12, decimal_places=2)
    aprobado = models.BooleanField(default=False)
    id_operacion = models.CharField(max_length=120, blank=True)
    detalle = models.CharField(max_length=250, blank=True)

    class Meta:
        verbose_name = "cobro de suscripción"
        verbose_name_plural = "cobros de suscripción"
        ordering = ["-fecha"]


class EstadoOnboarding(models.Model):
    PASOS = [(1, "Datos del hotel"), (2, "Habitaciones"), (3, "Tarifas"), (4, "Usuarios"), (5, "Importar datos")]

    hotel = models.OneToOneField("core.Hotel", on_delete=models.CASCADE, related_name="onboarding")
    paso = models.PositiveSmallIntegerField(default=1, choices=PASOS)
    completo = models.BooleanField(default=False)


class TicketSoporte(models.Model):
    class Estado(models.TextChoices):
        ABIERTO = "abierto", "Abierto"
        EN_PROGRESO = "en_progreso", "En progreso"
        ESPERANDO = "esperando", "Esperando respuesta del cliente"
        RESUELTO = "resuelto", "Resuelto"
        CERRADO = "cerrado", "Cerrado"

    empresa = models.ForeignKey("core.Empresa", on_delete=models.PROTECT, related_name="tickets")
    hotel = models.ForeignKey("core.Hotel", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tickets")
    asunto = models.CharField(max_length=200)
    descripcion = models.TextField("descripción")
    prioridad = models.CharField(
        max_length=10,
        default="normal",
        choices=[("baja", "Baja"), ("normal", "Normal"), ("alta", "Alta"), ("urgente", "Urgente")],
    )
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.ABIERTO)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "ticket de soporte"
        verbose_name_plural = "tickets de soporte"
        ordering = ["-actualizado_en"]

    def __str__(self):
        return f"#{self.pk} {self.asunto}"


class MensajeTicket(models.Model):
    ticket = models.ForeignKey(TicketSoporte, on_delete=models.CASCADE, related_name="mensajes")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    texto = models.TextField()
    es_soporte = models.BooleanField(default=False)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["creado_en"]


class ArticuloConocimiento(models.Model):
    titulo = models.CharField("título", max_length=200)
    categoria = models.CharField("categoría", max_length=60)
    contenido = models.TextField()
    publicado = models.BooleanField(default=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "artículo de ayuda"
        verbose_name_plural = "base de conocimiento"
        ordering = ["categoria", "titulo"]

    def __str__(self):
        return self.titulo


class VersionCambio(models.Model):
    version = models.CharField("versión", max_length=20)
    fecha = models.DateField(default=timezone.localdate)
    titulo = models.CharField(max_length=200)
    descripcion = models.TextField("descripción")

    class Meta:
        verbose_name = "versión"
        verbose_name_plural = "historial de cambios"
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.version} – {self.titulo}"


class DocumentoLegal(models.Model):
    class Tipo(models.TextChoices):
        TERMINOS = "terminos", "Términos y condiciones"
        DATOS = "datos", "Contrato de tratamiento de datos personales"

    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    version = models.CharField("versión", max_length=20)
    contenido = models.TextField()
    vigente = models.BooleanField(default=True)
    publicado_en = models.DateField(default=timezone.localdate)

    class Meta:
        verbose_name = "documento legal"
        verbose_name_plural = "documentos legales"
        ordering = ["tipo", "-publicado_en"]

    def __str__(self):
        return f"{self.get_tipo_display()} v{self.version}"


class AceptacionLegal(models.Model):
    empresa = models.ForeignKey("core.Empresa", on_delete=models.PROTECT, related_name="aceptaciones")
    documento = models.ForeignKey(DocumentoLegal, on_delete=models.PROTECT, related_name="aceptaciones")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    fecha = models.DateTimeField(default=timezone.now)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "aceptación legal"
        verbose_name_plural = "aceptaciones legales"

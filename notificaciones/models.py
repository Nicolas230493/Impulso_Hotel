from django.conf import settings
from django.db import models

from core.models import ModeloHotel


class PlantillaMensaje(ModeloHotel):
    class Codigo(models.TextChoices):
        CONFIRMACION = "confirmacion", "Confirmación de reserva"
        RECORDATORIO = "recordatorio", "Recordatorio previo a la llegada"
        INFO_INGRESO = "info_ingreso", "Información de ingreso"
        ENCUESTA = "encuesta", "Encuesta posterior a la estadía"

    codigo = models.CharField("código", max_length=20, choices=Codigo.choices)
    canal = models.CharField(max_length=10, choices=[("whatsapp", "WhatsApp"), ("email", "Email")], default="whatsapp")
    nombre_plantilla_meta = models.CharField(
        "nombre de la plantilla aprobada en Meta",
        max_length=100,
        blank=True,
        help_text="WhatsApp solo permite iniciar conversaciones con plantillas aprobadas.",
    )
    idioma = models.CharField(max_length=10, default="es_AR")
    cuerpo = models.TextField(
        help_text="Texto con variables: {nombre}, {hotel}, {entrada}, {salida}, {codigo}, "
        "{checkin}, {checkout}, {direccion}, {encuesta_url}"
    )
    aprobada = models.BooleanField("aprobada por Meta", default=False)

    class Meta:
        db_table = "plantillas_mensaje"
        verbose_name = "plantilla de mensaje"
        verbose_name_plural = "plantillas de mensaje"
        constraints = [
            models.UniqueConstraint(
                fields=["hotel", "codigo", "canal"], condition=models.Q(activo=True), name="plantilla_unica"
            )
        ]

    def __str__(self):
        return f"{self.get_codigo_display()} ({self.canal})"


class Notificacion(ModeloHotel):
    auditar = False

    class Canal(models.TextChoices):
        INTERNA = "interna", "Interna (campana)"
        EMAIL = "email", "Email"
        WHATSAPP = "whatsapp", "WhatsApp"

    class EstadoEnvio(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        ENVIADO = "enviado", "Enviado"
        ERROR = "error", "Error"
        BLOQUEADO = "bloqueado", "Bloqueado (sin consentimiento)"

    canal = models.CharField(max_length=10, choices=Canal.choices, default=Canal.INTERNA)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="notificaciones"
    )
    huesped = models.ForeignKey(
        "huespedes.Huesped", null=True, blank=True, on_delete=models.SET_NULL, related_name="mensajes"
    )
    reserva = models.ForeignKey(
        "reservas.Reserva", null=True, blank=True, on_delete=models.SET_NULL, related_name="mensajes"
    )
    destinatario = models.CharField(max_length=200, blank=True, help_text="Email o teléfono para envíos externos")
    plantilla = models.ForeignKey(PlantillaMensaje, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    titulo = models.CharField("título", max_length=200)
    mensaje = models.TextField()
    url = models.CharField(max_length=250, blank=True)
    leida = models.BooleanField(default=False)
    estado_envio = models.CharField(max_length=10, choices=EstadoEnvio.choices, default=EstadoEnvio.PENDIENTE)
    error = models.TextField(blank=True)
    id_externo = models.CharField(max_length=120, blank=True)
    enviado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notificaciones"
        verbose_name = "notificación"
        verbose_name_plural = "notificaciones"
        ordering = ["-creado_en"]
        indexes = [models.Index(fields=["usuario", "leida"])]

    def __str__(self):
        return self.titulo

from django.conf import settings
from django.db import models

from core.models import ModeloHotel


class Prediccion(ModeloHotel):
    auditar = False

    class Tipo(models.TextChoices):
        OCUPACION = "ocupacion", "Ocupación (%)"

    tipo = models.CharField(max_length=15, choices=Tipo.choices, default=Tipo.OCUPACION)
    fecha_objetivo = models.DateField()
    valor = models.DecimalField(max_digits=8, decimal_places=2)
    modelo = models.CharField(max_length=40, help_text="linea_base | ml_gradient_boosting | reglas")
    mape_modelo = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    mape_linea_base = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    datos_base = models.JSONField(default=dict, blank=True)
    calculada_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "predicciones"
        verbose_name = "predicción"
        verbose_name_plural = "predicciones"
        ordering = ["fecha_objetivo"]
        constraints = [models.UniqueConstraint(fields=["hotel", "tipo", "fecha_objetivo"], name="prediccion_unica")]


class Alerta(ModeloHotel):
    auditar = False

    class Tipo(models.TextChoices):
        OCUPACION_BAJA = "ocupacion_baja", "Ocupación proyectada baja"
        DIFERENCIA_CAJA = "diferencia_caja", "Diferencia de caja"
        STOCK_BAJO = "stock_bajo", "Stock bajo"
        INCIDENCIAS_REPETIDAS = "incidencias_repetidas", "Incidencias repetidas"
        REEMPLAZO_ACTIVO = "reemplazo_activo", "Reemplazo de activo recomendado"
        RIESGO_FALLA = "riesgo_falla", "Riesgo de falla"

    class Nivel(models.TextChoices):
        INFO = "info", "Información"
        ADVERTENCIA = "warning", "Advertencia"
        CRITICA = "danger", "Crítica"

    tipo = models.CharField(max_length=25, choices=Tipo.choices)
    nivel = models.CharField(max_length=10, choices=Nivel.choices, default=Nivel.ADVERTENCIA)
    titulo = models.CharField(max_length=200)
    mensaje = models.TextField()
    datos_base = models.JSONField(default=dict, blank=True, help_text="Datos en los que se basa la alerta")
    clave = models.CharField(max_length=120, help_text="Evita duplicar la misma alerta abierta")
    resuelta = models.BooleanField(default=False)
    resuelta_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "alertas"
        ordering = ["resuelta", "-creado_en"]
        constraints = [
            models.UniqueConstraint(
                fields=["hotel", "clave"], condition=models.Q(resuelta=False), name="alerta_abierta_unica"
            )
        ]

    def __str__(self):
        return self.titulo


class RecomendacionTarifa(ModeloHotel):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente de aprobación"
        APROBADA = "aprobada", "Aprobada"
        RECHAZADA = "rechazada", "Rechazada"

    tipo_habitacion = models.ForeignKey("habitaciones.TipoHabitacion", on_delete=models.CASCADE, related_name="+")
    fecha = models.DateField()
    precio_actual = models.DecimalField(max_digits=12, decimal_places=2)
    precio_sugerido = models.DecimalField(max_digits=12, decimal_places=2)
    fundamento = models.JSONField(default=dict, help_text="Datos en los que se basa la recomendación")
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    decidida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decidida_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "recomendación de tarifa"
        verbose_name_plural = "recomendaciones de tarifa"
        ordering = ["fecha", "tipo_habitacion"]
        permissions = [
            ("ver_dashboard", "Puede ver el dashboard gerencial"),
            ("ver_informes_economicos", "Puede ver informes económicos"),
            ("aprobar_tarifa", "Puede aprobar recomendaciones de tarifa"),
        ]

    @property
    def variacion(self):
        if not self.precio_actual:
            return None
        return round((self.precio_sugerido / self.precio_actual - 1) * 100, 1)


class ReporteProgramado(ModeloHotel):
    class Frecuencia(models.TextChoices):
        DIARIO = "diario", "Diario"
        SEMANAL = "semanal", "Semanal (lunes)"
        MENSUAL = "mensual", "Mensual (día 1)"

    nombre = models.CharField(max_length=100, default="Resumen gerencial")
    frecuencia = models.CharField(max_length=10, choices=Frecuencia.choices, default=Frecuencia.SEMANAL)
    destinatarios = models.CharField(max_length=500, help_text="Emails separados por coma")
    formato = models.CharField(max_length=5, choices=[("pdf", "PDF"), ("xlsx", "Excel")], default="pdf")
    ultimo_envio = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "reporte programado"
        verbose_name_plural = "reportes programados"

    def __str__(self):
        return f"{self.nombre} ({self.get_frecuencia_display()})"

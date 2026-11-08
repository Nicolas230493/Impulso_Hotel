from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import ModeloHotel


class ChecklistItem(ModeloHotel):
    tipo_habitacion = models.ForeignKey(
        "habitaciones.TipoHabitacion",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="checklist",
        help_text="Vacío = aplica a todos los tipos de habitación",
    )
    tipo_tarea = models.CharField(
        max_length=10, blank=True, choices=[("", "Ambas"), ("completa", "Completa"), ("repaso", "Repaso")]
    )
    descripcion = models.CharField("descripción", max_length=200)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "ítem de checklist"
        verbose_name_plural = "checklist de limpieza"
        ordering = ["orden", "id"]

    def __str__(self):
        return self.descripcion


class TareaLimpieza(ModeloHotel):
    class Tipo(models.TextChoices):
        COMPLETA = "completa", "Limpieza completa (salida)"
        REPASO = "repaso", "Repaso (ocupada)"
        PROFUNDA = "profunda", "Limpieza profunda"

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        EN_CURSO = "en_curso", "En curso"
        TERMINADA = "terminada", "Terminada"
        OMITIDA = "omitida", "Omitida (no molestar)"

    habitacion = models.ForeignKey("habitaciones.Habitacion", on_delete=models.PROTECT, related_name="tareas_limpieza")
    fecha = models.DateField(default=timezone.localdate)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    asignada_a = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="tareas_limpieza"
    )
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    prioridad = models.PositiveSmallIntegerField(default=2, help_text="1 = urgente (llegada hoy)")
    inicio = models.DateTimeField(null=True, blank=True)
    fin = models.DateTimeField(null=True, blank=True)
    checklist = models.JSONField(default=dict, blank=True)
    observaciones = models.TextField(blank=True)

    class Meta:
        db_table = "tareas_limpieza"
        verbose_name = "tarea de limpieza"
        verbose_name_plural = "tareas de limpieza"
        ordering = ["fecha", "prioridad", "habitacion__piso", "habitacion__numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["habitacion", "fecha", "tipo"], condition=models.Q(activo=True), name="tarea_unica_por_dia"
            )
        ]

    def __str__(self):
        return f"{self.fecha:%d/%m} hab. {self.habitacion} – {self.get_tipo_display()}"

    @property
    def minutos(self):
        if self.inicio and self.fin:
            return int((self.fin - self.inicio).total_seconds() // 60)
        return None


class ObjetoOlvidado(ModeloHotel):
    class Estado(models.TextChoices):
        GUARDADO = "guardado", "Guardado"
        DEVUELTO = "devuelto", "Devuelto al huésped"
        DESCARTADO = "descartado", "Descartado / donado"

    habitacion = models.ForeignKey(
        "habitaciones.Habitacion", on_delete=models.PROTECT, related_name="objetos_olvidados"
    )
    fecha = models.DateField(default=timezone.localdate)
    descripcion = models.CharField("descripción", max_length=250)
    lugar_guardado = models.CharField(max_length=100, blank=True)
    reserva = models.ForeignKey("reservas.Reserva", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.GUARDADO)
    observaciones = models.TextField(blank=True)

    class Meta:
        verbose_name = "objeto olvidado"
        verbose_name_plural = "objetos olvidados"
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.descripcion} (hab. {self.habitacion})"

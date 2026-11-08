from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.models import ModeloHotel


class Empleado(ModeloHotel):
    class Area(models.TextChoices):
        RECEPCION = "recepcion", "Recepción"
        LIMPIEZA = "limpieza", "Limpieza / housekeeping"
        MANTENIMIENTO = "mantenimiento", "Mantenimiento"
        COCINA = "cocina", "Cocina / restaurante"
        ADMINISTRACION = "administracion", "Administración"
        GERENCIA = "gerencia", "Gerencia"
        OTRA = "otra", "Otra"

    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    dni = models.CharField("DNI", max_length=15)
    cuil = models.CharField("CUIL", max_length=13, blank=True)
    puesto = models.CharField(max_length=80)
    area = models.CharField("área", max_length=15, choices=Area.choices)
    telefono = models.CharField("teléfono", max_length=50, blank=True)
    email = models.EmailField(blank=True)
    fecha_ingreso = models.DateField(null=True, blank=True)
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="empleado",
        help_text="Usuario del sistema (opcional)",
    )

    class Meta:
        db_table = "empleados"
        ordering = ["apellido", "nombre"]

    def __str__(self):
        return f"{self.apellido}, {self.nombre}"


class Turno(ModeloHotel):
    empleado = models.ForeignKey(Empleado, on_delete=models.PROTECT, related_name="turnos")
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    area = models.CharField(max_length=15, choices=Empleado.Area.choices, blank=True)
    observaciones = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "turnos"
        ordering = ["fecha", "hora_inicio"]

    def __str__(self):
        return f"{self.empleado} {self.fecha:%d/%m} {self.hora_inicio:%H:%M}-{self.hora_fin:%H:%M}"

    def clean(self):
        if self.empleado_id and self.fecha:
            licencia = Licencia.objects.filter(
                empleado_id=self.empleado_id, activo=True, aprobada=True, desde__lte=self.fecha, hasta__gte=self.fecha
            ).first()
            if licencia:
                raise ValidationError(f"El empleado está de licencia ({licencia.get_tipo_display()}) ese día.")


class Licencia(ModeloHotel):
    class Tipo(models.TextChoices):
        VACACIONES = "vacaciones", "Vacaciones"
        ENFERMEDAD = "enfermedad", "Enfermedad"
        ESTUDIO = "estudio", "Examen / estudio"
        FRANCO = "franco", "Franco"
        PERSONAL = "personal", "Trámite personal"
        OTRA = "otra", "Otra"

    empleado = models.ForeignKey(Empleado, on_delete=models.PROTECT, related_name="licencias")
    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    desde = models.DateField()
    hasta = models.DateField()
    aprobada = models.BooleanField(default=False)
    observaciones = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "licencias"
        ordering = ["-desde"]

    def __str__(self):
        return f"{self.empleado} – {self.get_tipo_display()} {self.desde:%d/%m}→{self.hasta:%d/%m}"

    def clean(self):
        if self.desde and self.hasta and self.hasta < self.desde:
            raise ValidationError({"hasta": "Debe ser posterior a la fecha desde."})

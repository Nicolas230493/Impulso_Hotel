from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from core.models import ModeloHotel


class TipoHabitacion(ModeloHotel):
    nombre = models.CharField(max_length=80)
    capacidad = models.PositiveSmallIntegerField(default=2)
    camas = models.CharField(max_length=120, blank=True, help_text="Ej.: 1 cama doble, 2 camas simples")
    amenities = models.TextField(blank=True, help_text="Separados por coma: TV, aire acondicionado, frigobar…")
    descripcion = models.TextField("descripción", blank=True)
    precio_base = models.DecimalField(
        "precio base por noche",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Se usa cuando ninguna tarifa de temporada cubre la fecha.",
    )
    precio_minimo = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, help_text="Mínimo para tarifas inteligentes (Fase 4)."
    )
    precio_maximo = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, help_text="Máximo para tarifas inteligentes (Fase 4)."
    )

    class Meta:
        verbose_name = "tipo de habitación"
        verbose_name_plural = "tipos de habitación"
        ordering = ["nombre"]
        db_table = "tipos_habitacion"
        constraints = [
            models.UniqueConstraint(
                fields=["hotel", "nombre"], condition=models.Q(activo=True), name="tipo_habitacion_unico_por_hotel"
            ),
        ]

    def __str__(self):
        return self.nombre

    @property
    def lista_amenities(self):
        return [a.strip() for a in self.amenities.split(",") if a.strip()]


class Habitacion(ModeloHotel):
    class Estado(models.TextChoices):
        LIBRE = "libre", "Libre"
        RESERVADA = "reservada", "Reservada"
        OCUPADA = "ocupada", "Ocupada"
        SUCIA = "sucia", "Sucia"
        LIMPIA = "limpia", "Limpia"
        FUERA_SERVICIO = "fuera_servicio", "Fuera de servicio"

    numero = models.CharField("número", max_length=10)
    piso = models.SmallIntegerField(default=0)
    tipo = models.ForeignKey(TipoHabitacion, on_delete=models.PROTECT, related_name="habitaciones")
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.LIBRE)
    observaciones = models.TextField(blank=True)

    class Meta:
        verbose_name = "habitación"
        verbose_name_plural = "habitaciones"
        ordering = ["piso", "numero"]
        db_table = "habitaciones"
        permissions = [
            ("marcar_limpia", "Puede marcar una habitación sucia como limpia"),
            ("cambiar_fuera_servicio", "Puede marcar o liberar fuera de servicio"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["hotel", "numero"], condition=models.Q(activo=True), name="habitacion_numero_unico_por_hotel"
            ),
        ]

    def __str__(self):
        return f"{self.numero}"

    @property
    def disponible_para_ingreso(self):
        return self.estado in (self.Estado.LIBRE, self.Estado.LIMPIA, self.Estado.RESERVADA)


class Tarifa(ModeloHotel):
    tipo_habitacion = models.ForeignKey(TipoHabitacion, on_delete=models.PROTECT, related_name="tarifas")
    temporada = models.CharField(max_length=80, help_text="Ej.: Alta verano, Baja, Vacaciones de invierno")
    fecha_desde = models.DateField()
    fecha_hasta = models.DateField(help_text="Inclusive.")
    precio_noche = models.DecimalField("precio por noche", max_digits=12, decimal_places=2)
    moneda = models.CharField(max_length=3, default="ARS", choices=[("ARS", "ARS"), ("USD", "USD")])

    class Meta:
        ordering = ["tipo_habitacion", "fecha_desde"]
        db_table = "tarifas"

    def __str__(self):
        return f"{self.tipo_habitacion} · {self.temporada} ({self.fecha_desde:%d/%m/%Y}–{self.fecha_hasta:%d/%m/%Y})"

    def clean(self):
        if self.fecha_desde and self.fecha_hasta and self.fecha_hasta < self.fecha_desde:
            raise ValidationError({"fecha_hasta": "Debe ser posterior o igual a la fecha desde."})
        if self.precio_noche is not None and self.precio_noche < 0:
            raise ValidationError({"precio_noche": "El precio no puede ser negativo."})


class BloqueoHabitacion(ModeloHotel):
    """Período en que una habitación está fuera de servicio y no es reservable."""

    habitacion = models.ForeignKey(Habitacion, on_delete=models.PROTECT, related_name="bloqueos")
    fecha_desde = models.DateField()
    fecha_hasta = models.DateField(null=True, blank=True, help_text="Inclusive. Vacío = hasta nuevo aviso.")
    motivo = models.CharField(max_length=200)
    incidencia = models.ForeignKey(
        "mantenimiento.Incidencia", null=True, blank=True, on_delete=models.SET_NULL, related_name="bloqueos"
    )

    class Meta:
        verbose_name = "período fuera de servicio"
        verbose_name_plural = "períodos fuera de servicio"
        ordering = ["-fecha_desde"]

    def __str__(self):
        hasta = f"{self.fecha_hasta:%d/%m/%Y}" if self.fecha_hasta else "sin fecha"
        return f"Hab. {self.habitacion} fuera de servicio {self.fecha_desde:%d/%m/%Y} → {hasta}"

    def clean(self):
        if self.fecha_hasta and self.fecha_desde and self.fecha_hasta < self.fecha_desde:
            raise ValidationError({"fecha_hasta": "Debe ser posterior o igual a la fecha desde."})

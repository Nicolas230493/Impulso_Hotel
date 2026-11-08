import secrets
from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, RangeOperators
from django.db import models
from django.db.backends.postgresql.psycopg_any import DateRange

from core.models import ModeloHotel


class Reserva(ModeloHotel):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        CONFIRMADA = "confirmada", "Confirmada"
        EN_CURSO = "en_curso", "En curso"
        FINALIZADA = "finalizada", "Finalizada"
        CANCELADA = "cancelada", "Cancelada"
        NO_SHOW = "no_show", "No-show"

    class Canal(models.TextChoices):
        DIRECTO = "directo", "Directo / mostrador"
        TELEFONO = "telefono", "Teléfono"
        WHATSAPP = "whatsapp", "WhatsApp"
        EMAIL = "email", "Email"
        BOOKING = "booking", "Booking.com"
        WEB = "web", "Web del hotel"
        OTRO = "otro", "Otro canal"

    ESTADOS_VIGENTES = (Estado.PENDIENTE, Estado.CONFIRMADA, Estado.EN_CURSO, Estado.FINALIZADA)

    codigo = models.CharField(max_length=12, editable=False)
    titular = models.ForeignKey("huespedes.Huesped", on_delete=models.PROTECT, related_name="reservas")
    fecha_entrada = models.DateField()
    fecha_salida = models.DateField()
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PENDIENTE)
    canal = models.CharField(max_length=12, choices=Canal.choices, default=Canal.DIRECTO)
    referencia_canal = models.CharField(max_length=60, blank=True, help_text="Nº de reserva en Booking u otro canal")
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    sena = models.DecimalField("seña", max_digits=12, decimal_places=2, default=Decimal("0"))
    moneda = models.CharField(max_length=3, default="ARS")
    observaciones = models.TextField(blank=True)
    cuenta_corriente = models.ForeignKey(
        "caja.CuentaCorriente",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reservas",
        help_text="Empresa que paga la estadía",
    )
    motivo_cancelacion = models.TextField(blank=True)
    cancelada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    cancelada_en = models.DateTimeField(null=True, blank=True)
    checkout_autorizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-fecha_entrada"]
        db_table = "reservas"
        permissions = [
            ("checkin_reserva", "Puede hacer check-in"),
            ("checkout_reserva", "Puede hacer check-out"),
            ("cancelar_reserva", "Puede cancelar reservas"),
            ("autorizar_checkout_con_saldo", "Puede autorizar check-out con saldo pendiente"),
        ]
        indexes = [
            models.Index(fields=["hotel", "estado", "fecha_entrada"]),
            models.Index(fields=["hotel", "fecha_salida"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fecha_salida__gt=models.F("fecha_entrada")), name="reserva_salida_posterior_entrada"
            ),
        ]

    def __str__(self):
        return f"{self.codigo} · {self.titular}"

    def save(self, *args, **kwargs):
        if not self.codigo:
            self.codigo = secrets.token_hex(3).upper()
        super().save(*args, **kwargs)

    @property
    def noches(self):
        return (self.fecha_salida - self.fecha_entrada).days

    @property
    def vigente(self):
        return self.estado in self.ESTADOS_VIGENTES

    @property
    def cantidad_huespedes(self):
        return sum(d.cantidad_huespedes for d in self.detalles.all())


class DetalleReserva(ModeloHotel):
    reserva = models.ForeignKey(Reserva, on_delete=models.CASCADE, related_name="detalles")
    habitacion = models.ForeignKey("habitaciones.Habitacion", on_delete=models.PROTECT, related_name="detalles_reserva")
    tipo_habitacion = models.ForeignKey("habitaciones.TipoHabitacion", on_delete=models.PROTECT, related_name="+")
    fecha_entrada = models.DateField()
    fecha_salida = models.DateField()
    periodo = DateRangeField(editable=False)
    vigente = models.BooleanField(
        default=True,
        editable=False,
        help_text="Falso si la reserva está cancelada o es no-show (libera la habitación).",
    )
    tarifa_aplicada = models.DecimalField("tarifa promedio por noche", max_digits=12, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    cantidad_huespedes = models.PositiveSmallIntegerField(default=1)

    class Meta:
        verbose_name = "habitación de la reserva"
        verbose_name_plural = "habitaciones de la reserva"
        db_table = "detalle_reservas"
        constraints = [
            # Sin superposición de fechas en la misma habitación (la salida es exclusiva: rango [entrada, salida)).
            ExclusionConstraint(
                name="sin_superposicion_habitacion",
                expressions=[("habitacion", RangeOperators.EQUAL), ("periodo", RangeOperators.OVERLAPS)],
                condition=models.Q(vigente=True, activo=True),
            ),
        ]

    def __str__(self):
        return f"{self.reserva.codigo} · hab. {self.habitacion}"

    def save(self, *args, **kwargs):
        self.periodo = DateRange(self.fecha_entrada, self.fecha_salida, "[)")
        super().save(*args, **kwargs)


class Estadia(ModeloHotel):
    """Check-in / check-out real de cada habitación de una reserva."""

    reserva = models.ForeignKey(Reserva, on_delete=models.PROTECT, related_name="estadias")
    detalle = models.OneToOneField(DetalleReserva, on_delete=models.PROTECT, related_name="estadia")
    habitacion = models.ForeignKey("habitaciones.Habitacion", on_delete=models.PROTECT, related_name="estadias")
    hora_real_entrada = models.DateTimeField()
    hora_real_salida = models.DateTimeField(null=True, blank=True)
    acompanantes = models.ManyToManyField(
        "huespedes.Huesped", blank=True, related_name="estadias_como_acompanante", verbose_name="acompañantes"
    )
    registrado_entrada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    registrado_salida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "estadía (check-in/out)"
        verbose_name_plural = "estadías (check-in/out)"
        db_table = "checkin_checkout"
        ordering = ["-hora_real_entrada"]

    def __str__(self):
        return f"{self.reserva.codigo} · hab. {self.habitacion}"

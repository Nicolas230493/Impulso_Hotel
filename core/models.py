from datetime import time

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from .actual import hotel_actual, usuario_actual


class Empresa(models.Model):
    """Empresa cliente de Impulso. Puede tener uno o varios hoteles (cadena)."""

    razon_social = models.CharField(max_length=200)
    cuit = models.CharField("CUIT", max_length=13, blank=True)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=50, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "empresa"
        ordering = ["razon_social"]

    def __str__(self):
        return self.razon_social


class Hotel(models.Model):
    class CondicionIVA(models.TextChoices):
        RESPONSABLE_INSCRIPTO = "RI", "Responsable inscripto"
        MONOTRIBUTO = "MT", "Monotributo"
        EXENTO = "EX", "IVA exento"

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="hoteles", null=True, blank=True)
    nombre = models.CharField(max_length=200)
    cuit = models.CharField("CUIT", max_length=13, blank=True)
    condicion_iva = models.CharField(
        max_length=2, choices=CondicionIVA.choices, default=CondicionIVA.RESPONSABLE_INSCRIPTO
    )
    direccion = models.CharField("dirección", max_length=250, blank=True)
    localidad = models.CharField(max_length=120, blank=True)
    provincia = models.CharField(max_length=120, blank=True)
    telefono = models.CharField("teléfono", max_length=50, blank=True)
    email = models.EmailField(blank=True)
    sitio_web = models.URLField(blank=True)
    hora_checkin = models.TimeField("hora de check-in", default=time(14, 0))
    hora_checkout = models.TimeField("hora de check-out", default=time(10, 0))
    politica_cancelacion = models.TextField("política de cancelación", blank=True)
    tolerancia_checkin_dias = models.PositiveSmallIntegerField(
        "tolerancia de check-in (días)",
        default=1,
        help_text="Días de tolerancia para hacer check-in antes/después de la fecha de entrada.",
    )
    hora_limite_noshow = models.TimeField(
        "hora límite no-show",
        default=time(23, 59),
        help_text="Pasada esta hora del día de entrada, la reserva sin check-in es no-show.",
    )
    permitir_stock_negativo = models.BooleanField(default=False)
    moneda = models.CharField(max_length=3, default="ARS")
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "hotel"
        verbose_name_plural = "hoteles"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Usuario(AbstractUser):
    email = models.EmailField("email", blank=True)
    telefono = models.CharField(max_length=50, blank=True)
    hoteles = models.ManyToManyField(Hotel, related_name="usuarios", blank=True, verbose_name="hoteles permitidos")
    hotel_activo = models.ForeignKey(Hotel, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    es_superadmin_impulso = models.BooleanField(default=False)
    intentos_fallidos = models.PositiveSmallIntegerField(default=0)
    bloqueado_hasta = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "usuario"
        ordering = ["username"]

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def rol(self):
        grupo = self.groups.first()
        return grupo.name if grupo else ""

    def tiene_rol(self, *roles):
        if self.is_superuser:
            return True
        return self.groups.filter(name__in=roles).exists()

    def puede_acceder_hotel(self, hotel):
        if hotel is None:
            return False
        if self.is_superuser:
            return True
        return self.hoteles.filter(pk=hotel.pk).exists()

    @property
    def esta_bloqueado(self):
        return bool(self.bloqueado_hasta and self.bloqueado_hasta > timezone.now())


class HotelQuerySet(models.QuerySet):
    def del_hotel(self, hotel):
        return self.filter(hotel=hotel)

    def activos(self):
        return self.filter(activo=True)


class ModeloHotel(models.Model):
    """Modelo base abstracto: todo dato operativo pertenece a un hotel y se borra lógicamente."""

    hotel = models.ForeignKey(Hotel, on_delete=models.PROTECT, related_name="+")
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    activo = models.BooleanField(default=True)

    objects = HotelQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.hotel_id:
            hotel = hotel_actual()
            if hotel is not None:
                self.hotel = hotel
        if not self.pk and not self.creado_por_id:
            usuario = usuario_actual()
            if usuario is not None and usuario.is_authenticated:
                self.creado_por = usuario
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Borrado lógico: nunca se borran físicamente datos operativos."""
        self.activo = False
        self.save(update_fields=["activo", "actualizado_en"])


class Auditoria(models.Model):
    class Accion(models.TextChoices):
        CREAR = "crear", "Crear"
        MODIFICAR = "modificar", "Modificar"
        BORRAR = "borrar", "Borrar"
        ACCION = "accion", "Acción"
        LOGIN = "login", "Inicio de sesión"
        SOPORTE = "soporte", "Acceso de soporte"

    hotel = models.ForeignKey(Hotel, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    accion = models.CharField(max_length=20, choices=Accion.choices)
    modelo = models.CharField(max_length=100)
    objeto_id = models.CharField(max_length=64, blank=True)
    descripcion = models.CharField(max_length=255, blank=True)
    antes = models.JSONField(null=True, blank=True)
    despues = models.JSONField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    fecha = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "auditoria"
        verbose_name = "registro de auditoría"
        verbose_name_plural = "auditoría"
        ordering = ["-fecha"]
        indexes = [models.Index(fields=["modelo", "objeto_id"])]

    def __str__(self):
        return f"{self.fecha:%d/%m/%Y %H:%M} {self.usuario} {self.accion} {self.modelo}#{self.objeto_id}"

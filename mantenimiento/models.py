from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import ModeloHotel


class Activo(ModeloHotel):
    class Tipo(models.TextChoices):
        CLIMATIZACION = "climatizacion", "Climatización (aire, calefacción)"
        ELECTRODOMESTICO = "electrodomestico", "Electrodoméstico (heladera, TV)"
        SANITARIO = "sanitario", "Sanitario / grifería"
        TERMOTANQUE = "termotanque", "Termotanque / caldera"
        ELECTRICO = "electrico", "Instalación eléctrica"
        MOBILIARIO = "mobiliario", "Mobiliario"
        ASCENSOR = "ascensor", "Ascensor"
        PILETA = "pileta", "Pileta / spa"
        OTRO = "otro", "Otro"

    nombre = models.CharField(max_length=120)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.OTRO)
    habitacion = models.ForeignKey(
        "habitaciones.Habitacion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="activos",
        verbose_name="habitación",
    )
    area = models.CharField(
        "área / ubicación",
        max_length=100,
        blank=True,
        help_text="Si no está en una habitación: lobby, cocina, sala de máquinas…",
    )
    marca = models.CharField(max_length=80, blank=True)
    modelo = models.CharField(max_length=80, blank=True)
    numero_serie = models.CharField("número de serie", max_length=80, blank=True)
    fecha_instalacion = models.DateField("fecha de instalación", null=True, blank=True)
    costo_adquisicion = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    umbral_reemplazo = models.DecimalField(
        "umbral de reemplazo",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Alerta cuando el costo acumulado de mantenimiento supera este monto.",
    )

    class Meta:
        db_table = "activos"
        ordering = ["nombre"]

    def __str__(self):
        lugar = f"hab. {self.habitacion}" if self.habitacion_id else self.area
        return f"{self.nombre} ({lugar})" if lugar else self.nombre

    @property
    def ubicacion(self):
        return f"Hab. {self.habitacion}" if self.habitacion_id else self.area


class Incidencia(ModeloHotel):
    class Origen(models.TextChoices):
        LIMPIEZA = "limpieza", "Limpieza"
        RECEPCION = "recepcion", "Recepción"
        HUESPED = "huesped", "Huésped"
        MANTENIMIENTO = "mantenimiento", "Mantenimiento"
        PREVENTIVO = "preventivo", "Plan preventivo"

    class Categoria(models.TextChoices):
        PLOMERIA = "plomeria", "Plomería"
        ELECTRICA = "electrica", "Eléctrica"
        CLIMATIZACION = "climatizacion", "Climatización"
        CARPINTERIA = "carpinteria", "Carpintería / mobiliario"
        PINTURA = "pintura", "Pintura / albañilería"
        ELECTRODOMESTICOS = "electrodomesticos", "Electrodomésticos"
        CERRAJERIA = "cerrajeria", "Cerrajería"
        OTRA = "otra", "Otra"

    class Prioridad(models.IntegerChoices):
        URGENTE = 1, "Urgente"
        ALTA = 2, "Alta"
        MEDIA = 3, "Media"
        BAJA = 4, "Baja"

    class Estado(models.TextChoices):
        ABIERTA = "abierta", "Abierta"
        ASIGNADA = "asignada", "Asignada"
        EN_CURSO = "en_curso", "En curso"
        RESUELTA = "resuelta", "Resuelta"
        CERRADA = "cerrada", "Cerrada"

    TRANSICIONES = {
        "abierta": ["asignada", "en_curso", "resuelta"],
        "asignada": ["en_curso", "resuelta", "abierta"],
        "en_curso": ["resuelta", "asignada"],
        "resuelta": ["cerrada", "en_curso"],
        "cerrada": [],
    }

    habitacion = models.ForeignKey(
        "habitaciones.Habitacion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="incidencias",
        verbose_name="habitación",
    )
    activo_relacionado = models.ForeignKey(
        Activo,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="incidencias",
        verbose_name="activo / equipo",
    )
    titulo = models.CharField("título", max_length=150)
    descripcion = models.TextField("descripción", blank=True)
    origen = models.CharField(max_length=15, choices=Origen.choices, default=Origen.RECEPCION)
    categoria = models.CharField("categoría", max_length=20, choices=Categoria.choices, default=Categoria.OTRA)
    prioridad = models.PositiveSmallIntegerField(choices=Prioridad.choices, default=Prioridad.MEDIA)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ABIERTA)
    bloqueante = models.BooleanField(default=False, help_text="Pone la habitación fuera de servicio hasta el cierre.")
    asignada_a = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="incidencias_asignadas",
        verbose_name="técnico",
    )
    reportada_en = models.DateTimeField(default=timezone.now)
    resuelta_en = models.DateTimeField(null=True, blank=True)
    cerrada_en = models.DateTimeField(null=True, blank=True)
    solucion = models.TextField("solución", blank=True)

    class Meta:
        db_table = "incidencias"
        ordering = ["estado", "prioridad", "-reportada_en"]

    def __str__(self):
        return f"#{self.pk} {self.titulo}"

    def clean(self):
        if not self.habitacion_id and not self.activo_relacionado_id:
            raise ValidationError("Indique la habitación o el activo afectado.")
        if self.bloqueante and not (
            self.habitacion_id or (self.activo_relacionado_id and self.activo_relacionado.habitacion_id)
        ):
            raise ValidationError({"bloqueante": "Solo puede ser bloqueante si afecta a una habitación."})

    @property
    def habitacion_afectada(self):
        if self.habitacion_id:
            return self.habitacion
        if self.activo_relacionado_id:
            return self.activo_relacionado.habitacion
        return None

    @property
    def horas_resolucion(self):
        if self.resuelta_en:
            return round((self.resuelta_en - self.reportada_en).total_seconds() / 3600, 1)
        return None

    @property
    def costo_total(self):
        return sum((m.costo_total for m in self.mantenimientos.filter(activo=True)), Decimal("0"))


class FotoIncidencia(ModeloHotel):
    incidencia = models.ForeignKey(Incidencia, on_delete=models.CASCADE, related_name="fotos")
    imagen = models.FileField(upload_to="incidencias/%Y/%m/")

    def __str__(self):
        return self.imagen.name


class PlanPreventivo(ModeloHotel):
    activo_relacionado = models.ForeignKey(
        Activo, on_delete=models.PROTECT, related_name="planes", verbose_name="activo / equipo"
    )
    tarea = models.CharField(max_length=200, help_text="Ej.: limpieza de filtros, service anual")
    frecuencia_dias = models.PositiveIntegerField("frecuencia (días)")
    proxima_fecha = models.DateField("próxima fecha")
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "planes_preventivos"
        verbose_name = "plan preventivo"
        verbose_name_plural = "planes preventivos"
        ordering = ["proxima_fecha"]

    def __str__(self):
        return f"{self.tarea} – {self.activo_relacionado} (cada {self.frecuencia_dias} días)"


class Mantenimiento(ModeloHotel):
    """Orden de trabajo: correctiva (de una incidencia) o preventiva (de un plan)."""

    class Tipo(models.TextChoices):
        CORRECTIVO = "correctivo", "Correctivo"
        PREVENTIVO = "preventivo", "Preventivo"

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        REALIZADO = "realizado", "Realizado"
        CANCELADO = "cancelado", "Cancelado"

    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    incidencia = models.ForeignKey(
        Incidencia, null=True, blank=True, on_delete=models.PROTECT, related_name="mantenimientos"
    )
    plan = models.ForeignKey(PlanPreventivo, null=True, blank=True, on_delete=models.PROTECT, related_name="ordenes")
    activo_relacionado = models.ForeignKey(
        Activo, null=True, blank=True, on_delete=models.PROTECT, related_name="mantenimientos", verbose_name="activo"
    )
    habitacion = models.ForeignKey(
        "habitaciones.Habitacion", null=True, blank=True, on_delete=models.PROTECT, related_name="mantenimientos"
    )
    tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="mantenimientos"
    )
    fecha_programada = models.DateField(default=timezone.localdate)
    fecha_realizado = models.DateField(null=True, blank=True)
    descripcion = models.TextField("trabajo realizado", blank=True)
    horas = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0"))
    costo_mano_obra = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    costo_externo = models.DecimalField("costo de terceros", max_digits=12, decimal_places=2, default=Decimal("0"))

    class Meta:
        db_table = "mantenimientos"
        ordering = ["-fecha_programada"]

    def __str__(self):
        base = self.plan.tarea if self.plan_id else (self.incidencia.titulo if self.incidencia_id else "Mantenimiento")
        return f"{self.get_tipo_display()}: {base}"

    @property
    def costo_repuestos(self):
        return sum((r.costo_total for r in self.repuestos.filter(activo=True)), Decimal("0"))

    @property
    def costo_total(self):
        return self.costo_mano_obra + self.costo_externo + self.costo_repuestos


class RepuestoUsado(ModeloHotel):
    mantenimiento = models.ForeignKey(Mantenimiento, on_delete=models.CASCADE, related_name="repuestos")
    producto = models.ForeignKey("inventario.Producto", on_delete=models.PROTECT, related_name="+")
    deposito = models.ForeignKey("inventario.Deposito", on_delete=models.PROTECT, related_name="+")
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    costo_unitario = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "repuesto usado"
        verbose_name_plural = "repuestos usados"

    def __str__(self):
        return f"{self.cantidad} × {self.producto}"

    @property
    def costo_total(self):
        return self.cantidad * self.costo_unitario

from core.crud import Crud

from .models import BloqueoHabitacion, Habitacion, Tarifa, TipoHabitacion

tipos = Crud(
    TipoHabitacion,
    ["nombre", "capacidad", "camas", "amenities", "descripcion", "precio_base", "precio_minimo", "precio_maximo"],
    ["nombre", "capacidad", "camas", ("precio_base", "Precio base")],
    "tipohabitacion",
    "Tipos de habitación",
    buscar_en=["nombre"],
)
habitaciones = Crud(
    Habitacion,
    ["numero", "piso", "tipo", "observaciones"],
    [("numero", "Número"), "piso", "tipo", ("estado", "Estado")],
    "habitacion",
    "Habitaciones",
    buscar_en=["numero", "tipo__nombre"],
)
tarifas = Crud(
    Tarifa,
    ["tipo_habitacion", "temporada", "fecha_desde", "fecha_hasta", "precio_noche", "moneda"],
    [
        ("tipo_habitacion", "Tipo"),
        "temporada",
        ("fecha_desde", "Desde"),
        ("fecha_hasta", "Hasta"),
        ("precio_noche", "Precio/noche"),
        "moneda",
    ],
    "tarifa",
    "Tarifas y temporadas",
    buscar_en=["temporada", "tipo_habitacion__nombre"],
    orden=["-fecha_desde"],
)
bloqueos = Crud(
    BloqueoHabitacion,
    ["habitacion", "fecha_desde", "fecha_hasta", "motivo"],
    [("habitacion", "Habitación"), ("fecha_desde", "Desde"), ("fecha_hasta", "Hasta"), "motivo"],
    "bloqueo",
    "Períodos fuera de servicio",
    buscar_en=["motivo", "habitacion__numero"],
)

urlpatterns = (
    tipos.urls("tipos")
    + habitaciones.urls("habitaciones")
    + tarifas.urls("tarifas")
    + bloqueos.urls("fuera-de-servicio")
)

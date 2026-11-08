from django.urls import path

from core.crud import Crud

from . import views
from .models import Activo, PlanPreventivo

activos = Crud(
    Activo,
    [
        "nombre",
        "tipo",
        "habitacion",
        "area",
        "marca",
        "modelo",
        "numero_serie",
        "fecha_instalacion",
        "costo_adquisicion",
        "umbral_reemplazo",
    ],
    ["nombre", "tipo", ("ubicacion", "Ubicación"), "marca", ("fecha_instalacion", "Instalado")],
    "activo",
    "Activos y equipos",
    buscar_en=["nombre", "marca", "area"],
    acciones_extra=(),
)
planes = Crud(
    PlanPreventivo,
    ["activo_relacionado", "tarea", "frecuencia_dias", "proxima_fecha", "responsable"],
    [
        ("activo_relacionado", "Activo"),
        "tarea",
        ("frecuencia_dias", "Cada (días)"),
        ("proxima_fecha", "Próxima"),
        "responsable",
    ],
    "plan",
    "Planes preventivos",
    buscar_en=["tarea"],
    orden=["proxima_fecha"],
)

urlpatterns = (
    [
        path("incidencias/", views.tablero, name="incidencia_tablero"),
        path("incidencias/nueva/", views.nueva, name="incidencia_nueva"),
        path("incidencias/<int:pk>/", views.detalle, name="incidencia_detalle"),
        path("incidencias/<int:pk>/accion/", views.accion, name="incidencia_accion"),
        path("ordenes/", views.ordenes, name="orden_preventiva_lista"),
        path("ordenes/generar/", views.generar_preventivas, name="orden_preventiva_generar"),
        path("ordenes/<int:pk>/registrar/", views.orden_registrar, name="orden_preventiva_registrar"),
    ]
    + activos.urls("activos")
    + planes.urls("planes")
)

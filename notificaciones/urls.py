from django.urls import path

from core.crud import Crud

from . import views
from .models import PlantillaMensaje

plantillas = Crud(
    PlantillaMensaje,
    ["codigo", "canal", "nombre_plantilla_meta", "idioma", "cuerpo", "aprobada"],
    [("codigo", "Mensaje"), "canal", ("nombre_plantilla_meta", "Plantilla Meta"), "aprobada"],
    "plantilla",
    "Plantillas de mensajes",
)

urlpatterns = [
    path("", views.lista, name="notificacion_lista"),
    path("campana/", views.campana, name="notificacion_campana"),
    path("<int:pk>/", views.abrir, name="notificacion_abrir"),
    path("marcar-todas/", views.marcar_todas, name="notificacion_marcar_todas"),
] + plantillas.urls("plantillas")

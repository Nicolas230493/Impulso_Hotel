from django.urls import path

from core.crud import Crud

from . import views
from .models import ChecklistItem, ObjetoOlvidado

objetos = Crud(
    ObjetoOlvidado,
    ["habitacion", "fecha", "descripcion", "lugar_guardado", "reserva", "estado", "observaciones"],
    ["fecha", ("habitacion", "Hab."), ("descripcion", "Descripción"), ("lugar_guardado", "Guardado en"), "estado"],
    "objeto",
    "Objetos olvidados",
    buscar_en=["descripcion"],
    orden=["-fecha"],
)
checklist = Crud(
    ChecklistItem,
    ["descripcion", "tipo_habitacion", "tipo_tarea", "orden"],
    [("descripcion", "Ítem"), ("tipo_habitacion", "Tipo de habitación"), ("tipo_tarea", "Tarea"), "orden"],
    "checklist",
    "Checklist de limpieza",
    orden=["orden"],
)

urlpatterns = (
    [
        path("", views.tablero, name="limpieza_tablero"),
        path("generar/", views.generar, name="limpieza_generar"),
        path("mis-tareas/", views.mis_tareas, name="limpieza_mis_tareas"),
        path("tareas/<int:pk>/", views.tarea, name="limpieza_tarea"),
        path("tareas/<int:pk>/asignar/", views.asignar, name="limpieza_asignar"),
    ]
    + objetos.urls("objetos")
    + checklist.urls("checklist")
)

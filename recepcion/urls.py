from django.urls import path

from . import views

urlpatterns = [
    path("", views.panel, name="panel_recepcion"),
    path("rack/", views.rack, name="rack"),
    path("mapa/", views.mapa, name="mapa_habitaciones"),
    path("habitacion/<int:pk>/estado/", views.cambiar_estado_habitacion, name="habitacion_cambiar_estado"),
]

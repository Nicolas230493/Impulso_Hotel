from django.urls import path

from . import views

urlpatterns = [
    path("", views.lista, name="huesped_lista"),
    path("nuevo/", views.form, name="huesped_nuevo"),
    path("<int:pk>/", views.detalle, name="huesped_detalle"),
    path("<int:pk>/editar/", views.form, name="huesped_editar"),
    path("<int:pk>/exportar/", views.exportar_datos, name="huesped_exportar"),
    path("<int:pk>/suprimir/", views.suprimir, name="huesped_suprimir"),
]

from django.urls import path

from . import views

urlpatterns = [
    path("", views.lista, name="reserva_lista"),
    path("nueva/", views.nueva, name="reserva_nueva"),
    path("walk-in/", views.walk_in, name="walk_in"),
    path("disponibilidad/", views.disponibilidad, name="reserva_disponibilidad"),
    path("buscar-huesped/", views.buscar_huesped_doc, name="buscar_huesped_doc"),
    path("habitaciones.json", views.habitaciones_json, name="habitaciones_json"),
    path("<int:pk>/", views.detalle, name="reserva_detalle"),
    path("<int:pk>/editar/", views.editar, name="reserva_editar"),
    path("<int:pk>/confirmar/", views.confirmar, name="reserva_confirmar"),
    path("<int:pk>/cancelar/", views.cancelar, name="reserva_cancelar"),
    path("<int:pk>/checkin/", views.checkin, name="reserva_checkin"),
    path("<int:pk>/checkout/", views.checkout, name="reserva_checkout"),
    path("<int:pk>/pago/", views.registrar_pago, name="reserva_pago"),
    path("<int:pk>/cargo/", views.registrar_cargo, name="reserva_cargo"),
    path("<int:pk>/facturar/", views.facturar, name="reserva_facturar"),
]

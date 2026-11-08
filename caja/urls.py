from django.urls import path

from core.crud import Crud

from . import views
from .models import CuentaCorriente

cuentas = Crud(
    CuentaCorriente,
    ["razon_social", "cuit", "condicion_iva", "direccion", "email", "telefono", "limite_credito"],
    [("razon_social", "Razón social"), ("cuit", "CUIT"), ("condicion_iva", "Condición IVA"), "email"],
    "cuentacorriente",
    "Cuentas corrientes de empresas",
    buscar_en=["razon_social", "cuit"],
)

urlpatterns = [
    path("", views.mi_caja, name="caja_mia"),
    path("cajas/", views.lista, name="caja_lista"),
    path("cajas/<int:pk>/", views.detalle, name="caja_detalle"),
    path("cajas/<int:pk>/cerrar/", views.cerrar, name="caja_cerrar"),
    path("cajas/<int:pk>/movimiento/", views.movimiento, name="caja_movimiento"),
    path("informes/", views.informes, name="informes_economicos"),
] + cuentas.urls("cuentas-corrientes")

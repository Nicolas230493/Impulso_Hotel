from django.urls import path

from core.crud import Crud

from . import views
from .models import CategoriaGasto, Proveedor

proveedores = Crud(
    Proveedor,
    ["razon_social", "cuit", "condicion_iva", "rubro", "contacto", "email", "telefono", "direccion", "cbu_alias"],
    [
        ("razon_social", "Razón social"),
        ("cuit", "CUIT"),
        ("condicion_iva", "IVA"),
        "rubro",
        "contacto",
        ("telefono", "Teléfono"),
    ],
    "proveedor",
    "Proveedores",
    buscar_en=["razon_social", "cuit", "rubro"],
)
categorias = Crud(CategoriaGasto, ["nombre"], ["nombre"], "categoriagasto", "Categorías de gasto")

urlpatterns = (
    [
        path("gastos/", views.gasto_lista, name="gasto_lista"),
        path("gastos/nuevo/", views.gasto_nuevo, name="gasto_nuevo"),
        path("solicitudes/", views.solicitud_lista, name="solicitud_lista"),
        path("solicitudes/nueva/", views.solicitud_nueva, name="solicitud_nueva"),
        path("solicitudes/<int:pk>/accion/", views.solicitud_accion, name="solicitud_accion"),
        path("ordenes/", views.orden_lista, name="orden_lista"),
        path("ordenes/nueva/", views.orden_nueva, name="orden_nueva"),
        path("ordenes/<int:pk>/", views.orden_detalle, name="orden_detalle"),
        path("ordenes/<int:pk>/accion/", views.orden_accion, name="orden_accion"),
        path("comparar-precios/", views.comparar_precios, name="comparar_precios"),
    ]
    + proveedores.urls("proveedores")
    + categorias.urls("categorias")
)

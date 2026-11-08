from django.urls import path

from core.crud import Crud

from . import views
from .models import Deposito, Producto

productos = Crud(
    Producto,
    ["codigo", "nombre", "categoria", "unidad", "costo", "precio_venta", "alicuota_iva", "stock_minimo"],
    [
        ("codigo", "Código"),
        "nombre",
        ("categoria", "Categoría"),
        "unidad",
        "costo",
        ("precio_venta", "Precio venta"),
        ("stock_minimo", "Mínimo"),
        ("stock_total", "Stock"),
    ],
    "producto",
    "Productos e insumos",
    buscar_en=["nombre", "codigo"],
)
depositos = Crud(
    Deposito, ["nombre", "descripcion"], ["nombre", ("descripcion", "Descripción")], "deposito", "Depósitos"
)

urlpatterns = (
    [
        path("", views.stock, name="stock_lista"),
        path("movimiento/", views.movimiento, name="stock_movimiento"),
    ]
    + productos.urls("productos")
    + depositos.urls("depositos")
)

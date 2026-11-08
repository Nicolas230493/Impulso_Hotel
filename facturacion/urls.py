from django import forms
from django.urls import path

from core.crud import Crud
from core.forms import FormHotel

from . import views
from .models import PuntoVenta


class PuntoVentaForm(FormHotel):
    tipos_habilitados = forms.JSONField(
        required=False, initial=[1, 3, 6, 8, 11, 13], help_text="Códigos ARCA: 1 FA, 3 NCA, 6 FB, 8 NCB, 11 FC, 13 NCC"
    )

    class Meta:
        model = PuntoVenta
        fields = ["numero", "descripcion", "tipos_habilitados", "por_defecto"]


puntos = Crud(
    PuntoVenta,
    None,
    [
        ("numero", "Número"),
        ("descripcion", "Descripción"),
        ("tipos_habilitados", "Comprobantes"),
        ("por_defecto", "Por defecto"),
    ],
    "puntoventa",
    "Puntos de venta",
    form_class=PuntoVentaForm,
)

urlpatterns = [
    path("", views.lista, name="factura_lista"),
    path("reintentar/", views.reintentar_todas, name="factura_reintentar_todas"),
    path("<int:pk>/", views.detalle, name="factura_detalle"),
    path("<int:pk>/emitir/", views.emitir, name="factura_emitir"),
    path("<int:pk>/nota-credito/", views.nota_credito, name="factura_nota_credito"),
    path("<int:pk>/anular/", views.anular, name="factura_anular"),
] + puntos.urls("puntos-de-venta")

from django.urls import path

from core.crud import Crud

from . import views
from .models import ReporteProgramado

reportes = Crud(
    ReporteProgramado,
    ["nombre", "frecuencia", "destinatarios", "formato"],
    ["nombre", "frecuencia", "destinatarios", "formato", ("ultimo_envio", "Último envío")],
    "reporte",
    "Reportes programados por email",
)

urlpatterns = [
    path("", views.dashboard, name="bi_dashboard"),
    path("prediccion/", views.prediccion, name="bi_prediccion"),
    path("tarifas/", views.tarifas, name="bi_tarifas"),
    path("mantenimiento/", views.mant_predictivo, name="bi_mant_predictivo"),
    path("alertas/", views.alertas, name="bi_alertas"),
    path("alertas/<int:pk>/resolver/", views.alerta_resolver, name="bi_alerta_resolver"),
    path("consolidado/", views.consolidado, name="bi_consolidado"),
] + reportes.urls("reportes")

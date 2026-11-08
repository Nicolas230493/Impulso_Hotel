from django.urls import path

from . import views

urlpatterns = [
    path("registro/", views.registro, name="saas_registro"),
    path("legal/<str:tipo>/", views.legal, name="saas_legal"),
    path("onboarding/", views.onboarding, name="onboarding"),
    path("configuracion/importar/", views.importar, name="importar"),
    path("saas/suscripcion/", views.mi_suscripcion, name="saas_mi_suscripcion"),
    path("saas/clientes/", views.panel, name="saas_panel"),
    path("saas/clientes/<int:pk>/", views.empresa_detalle, name="saas_empresa"),
    path("saas/soporte/acceder/<int:hotel_id>/", views.soporte_acceder, name="saas_soporte_acceder"),
    path("saas/soporte/salir/", views.soporte_salir, name="saas_soporte_salir"),
    path("soporte/", views.soporte_lista, name="soporte_lista"),
    path("soporte/<int:pk>/", views.soporte_ticket, name="soporte_ticket"),
    path("ayuda/", views.ayuda, name="ayuda"),
]

from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import CambioPasswordForm

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("cuenta/login/", views.LoginView.as_view(), name="login"),
    path("cuenta/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "cuenta/recuperar/",
        auth_views.PasswordResetView.as_view(
            template_name="core/password_reset.html", email_template_name="core/password_reset_email.txt"
        ),
        name="password_reset",
    ),
    path(
        "cuenta/recuperar/enviado/",
        auth_views.PasswordResetDoneView.as_view(template_name="core/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "cuenta/recuperar/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="core/password_reset_confirm.html", form_class=CambioPasswordForm
        ),
        name="password_reset_confirm",
    ),
    path(
        "cuenta/recuperar/listo/",
        auth_views.PasswordResetCompleteView.as_view(template_name="core/password_reset_complete.html"),
        name="password_reset_complete",
    ),
    path("cuenta/2fa/configurar/", views.otp_configurar, name="otp_configurar"),
    path("cuenta/2fa/verificar/", views.otp_verificar, name="otp_verificar"),
    path("hotel/cambiar/", views.cambiar_hotel, name="cambiar_hotel"),
    path("configuracion/", views.configuracion, name="configuracion"),
    path("configuracion/hotel/", views.configuracion_hotel, name="configuracion_hotel"),
    path("configuracion/usuarios/", views.usuario_lista, name="usuario_lista"),
    path("configuracion/usuarios/nuevo/", views.usuario_form, name="usuario_nuevo"),
    path("configuracion/usuarios/<int:pk>/", views.usuario_form, name="usuario_editar"),
    path("configuracion/usuarios/<int:pk>/desbloquear/", views.usuario_desbloquear, name="usuario_desbloquear"),
    path("configuracion/usuarios/<int:pk>/baja/", views.usuario_baja, name="usuario_baja"),
    path("configuracion/auditoria/", views.auditoria_lista, name="auditoria_lista"),
]

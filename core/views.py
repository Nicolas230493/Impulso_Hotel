import base64
from io import BytesIO

import qrcode
from django import forms
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from . import roles
from .forms import BootstrapMixin, HotelForm, UsuarioForm
from .models import Auditoria, Usuario


class LoginForm(BootstrapMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilos()

    def clean(self):
        username = self.cleaned_data.get("username")
        usuario = Usuario.objects.filter(username=username).first() if username else None
        if usuario is not None and usuario.esta_bloqueado:
            minutos = int((usuario.bloqueado_hasta - timezone.now()).total_seconds() // 60) + 1
            raise forms.ValidationError(
                f"Usuario bloqueado por intentos fallidos. Intente nuevamente en {minutos} minuto(s).",
                code="bloqueado",
            )
        return super().clean()


class LoginView(auth_views.LoginView):
    template_name = "core/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


@login_required
def inicio(request):
    """Redirige a la pantalla principal de cada rol."""
    u = request.user
    if u.es_superadmin_impulso and not u.hoteles.exists():
        return redirect("saas_panel")
    if request.hotel is None:
        return render(request, "core/sin_hotel.html")
    if u.is_superuser or u.tiene_rol(roles.ADMIN, roles.RECEPCION):
        return redirect("panel_recepcion")
    if u.tiene_rol(roles.LIMPIEZA):
        return redirect("limpieza_mis_tareas")
    if u.tiene_rol(roles.MANTENIMIENTO):
        return redirect("incidencia_tablero")
    if u.tiene_rol(roles.DUENO):
        return redirect("bi_dashboard")
    if u.tiene_rol(roles.COMPRAS):
        return redirect("gasto_lista")
    return render(request, "core/sin_hotel.html")


@login_required
@require_POST
def cambiar_hotel(request):
    from .models import Hotel

    hotel = get_object_or_404(Hotel, pk=request.POST.get("hotel"), activo=True)
    if not request.user.puede_acceder_hotel(hotel):
        messages.error(request, "No tiene acceso a ese hotel.")
    else:
        request.user.hotel_activo = hotel
        request.user.save(update_fields=["hotel_activo"])
        messages.success(request, f"Hotel activo: {hotel}")
    return redirect("inicio")


@login_required
@permission_required("core.change_hotel", raise_exception=True)
def configuracion_hotel(request):
    form = HotelForm(request.POST or None, instance=request.hotel)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Datos del hotel actualizados.")
        return redirect("configuracion_hotel")
    return render(request, "core/hotel_form.html", {"form": form, "titulo": "Datos del establecimiento"})


@login_required
def configuracion(request):
    return render(request, "core/configuracion.html")


# --- Usuarios ---


def _usuarios_del_hotel(request):
    return Usuario.objects.filter(hoteles=request.hotel).prefetch_related("groups").order_by("username")


@login_required
@permission_required("core.view_usuario", raise_exception=True)
def usuario_lista(request):
    return render(request, "core/usuario_lista.html", {"usuarios": _usuarios_del_hotel(request)})


@login_required
@permission_required("core.add_usuario", raise_exception=True)
def usuario_form(request, pk=None):
    usuario = get_object_or_404(_usuarios_del_hotel(request), pk=pk) if pk else None
    if usuario and not request.user.has_perm("core.change_usuario"):
        messages.error(request, "Sin permiso para modificar usuarios.")
        return redirect("usuario_lista")
    form = UsuarioForm(request.POST or None, instance=usuario, hotel=request.hotel)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Usuario guardado.")
        return redirect("usuario_lista")
    return render(
        request, "crud/form.html", {"form": form, "titulo": "Usuario", "url_lista": "/configuracion/usuarios/"}
    )


@login_required
@permission_required("core.change_usuario", raise_exception=True)
@require_POST
def usuario_desbloquear(request, pk):
    usuario = get_object_or_404(_usuarios_del_hotel(request), pk=pk)
    usuario.bloqueado_hasta = None
    usuario.intentos_fallidos = 0
    usuario.save(update_fields=["bloqueado_hasta", "intentos_fallidos"])
    messages.success(request, f"Usuario {usuario.username} desbloqueado.")
    return redirect("usuario_lista")


@login_required
@permission_required("core.change_usuario", raise_exception=True)
@require_POST
def usuario_baja(request, pk):
    usuario = get_object_or_404(_usuarios_del_hotel(request), pk=pk)
    if usuario == request.user:
        messages.error(request, "No puede darse de baja a sí mismo.")
    else:
        usuario.is_active = False
        usuario.save(update_fields=["is_active"])
        messages.success(request, f"Usuario {usuario.username} dado de baja.")
    return redirect("usuario_lista")


# --- Auditoría ---


@login_required
@permission_required("core.view_auditoria", raise_exception=True)
def auditoria_lista(request):
    qs = Auditoria.objects.filter(hotel=request.hotel).select_related("usuario")
    modelo = request.GET.get("modelo", "")
    if modelo:
        qs = qs.filter(modelo__icontains=modelo)
    objeto = request.GET.get("objeto", "")
    if objeto:
        qs = qs.filter(objeto_id=objeto)
    pagina = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "core/auditoria.html", {"pagina": pagina, "modelo": modelo, "objeto": objeto})


# --- Doble factor (TOTP) ---


class TokenForm(BootstrapMixin, forms.Form):
    token = forms.CharField(label="Código de 6 dígitos", max_length=6)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilos()


@login_required
def otp_configurar(request):
    dispositivo, _ = TOTPDevice.objects.get_or_create(user=request.user, confirmed=False, defaults={"name": "default"})
    form = TokenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if dispositivo.verify_token(form.cleaned_data["token"]):
            dispositivo.confirmed = True
            dispositivo.save()
            TOTPDevice.objects.filter(user=request.user, confirmed=False).delete()
            otp_login(request, dispositivo)
            messages.success(request, "Doble factor activado.")
            return redirect("inicio")
        form.add_error("token", "Código incorrecto.")
    img = qrcode.make(dispositivo.config_url)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    qr = base64.b64encode(buffer.getvalue()).decode()
    return render(request, "core/otp_configurar.html", {"form": form, "qr": qr})


@login_required
def otp_verificar(request):
    form = TokenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        for dispositivo in TOTPDevice.objects.filter(user=request.user, confirmed=True):
            if dispositivo.verify_token(form.cleaned_data["token"]):
                otp_login(request, dispositivo)
                destino = request.GET.get("next", "")
                if not url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
                    destino = "inicio"
                return redirect(destino or "inicio")
        form.add_error("token", "Código incorrecto.")
    return render(request, "core/otp_verificar.html", {"form": form})

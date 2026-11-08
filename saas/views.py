from datetime import date, datetime
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core import actual, auditoria
from core.forms import BootstrapMixin, HotelForm, UsuarioForm
from core.models import Auditoria, Empresa, Hotel
from habitaciones.models import Habitacion, TipoHabitacion
from huespedes.models import Huesped

from . import services
from .models import (
    ArticuloConocimiento,
    DocumentoLegal,
    EstadoOnboarding,
    MensajeTicket,
    Plan,
    Suscripcion,
    TicketSoporte,
    VersionCambio,
)


def superadmin_requerido(vista):
    def envoltura(request, *args, **kwargs):
        if not (request.user.is_authenticated and (request.user.es_superadmin_impulso or request.user.is_superuser)):
            raise PermissionDenied
        return vista(request, *args, **kwargs)

    return envoltura


# ------------------------------------------------------------------ Registro y onboarding


class RegistroForm(BootstrapMixin, forms.Form):
    razon_social = forms.CharField(label="Razón social", max_length=200)
    cuit = forms.CharField(label="CUIT", max_length=13)
    nombre_hotel = forms.CharField(label="Nombre del hotel", max_length=200)
    plan = forms.ModelChoiceField(queryset=Plan.objects.filter(activo=True), empty_label=None)
    nombre = forms.CharField(max_length=100)
    apellido = forms.CharField(max_length=100)
    email = forms.EmailField()
    telefono = forms.CharField(label="Teléfono", max_length=50, required=False)
    username = forms.CharField(label="Usuario", max_length=150)
    password = forms.CharField(label="Contraseña", widget=forms.PasswordInput)
    acepto = forms.BooleanField(label="Acepto los términos y condiciones y el contrato de tratamiento de datos")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilos()

    def clean_cuit(self):
        cuit = "".join(c for c in self.cleaned_data["cuit"] if c.isdigit())
        if len(cuit) != 11:
            raise ValidationError("El CUIT debe tener 11 dígitos.")
        return cuit

    def clean_password(self):
        validate_password(self.cleaned_data["password"])
        return self.cleaned_data["password"]


def registro(request):
    form = RegistroForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            _, hotel, usuario = services.alta_cliente(
                d["razon_social"],
                d["cuit"],
                d["email"],
                d["nombre_hotel"],
                d["username"],
                d["password"],
                d["plan"],
                d["nombre"],
                d["apellido"],
                d["telefono"],
                ip=actual.ip_actual(),
            )
            login(request, usuario, backend="core.backends.BloqueoModelBackend")
            messages.success(request, f"¡Bienvenido/a! Su período de prueba de {d['plan'].dias_prueba} días comenzó.")
            return redirect("onboarding")
        except ValidationError as exc:
            for campo, errores in exc.message_dict.items():
                form.add_error(campo if campo in form.fields else None, errores)
    return render(
        request,
        "saas/registro.html",
        {
            "form": form,
            "planes": Plan.objects.filter(activo=True),
            "documentos": DocumentoLegal.objects.filter(vigente=True),
        },
    )


def legal(request, tipo):
    doc = DocumentoLegal.objects.filter(tipo=tipo, vigente=True).first()
    return render(request, "saas/legal.html", {"doc": doc})


class GeneradorHabitacionesForm(BootstrapMixin, forms.Form):
    tipo_nombre = forms.CharField(label="Tipo de habitación", max_length=80, initial="Doble")
    capacidad = forms.IntegerField(min_value=1, initial=2)
    camas = forms.CharField(max_length=120, required=False, initial="1 cama matrimonial")
    precio_base = forms.DecimalField(label="Precio base por noche", min_value=0, decimal_places=2)
    piso = forms.IntegerField(initial=1)
    desde = forms.IntegerField(label="Numeración desde", initial=101)
    cantidad = forms.IntegerField(min_value=1, max_value=200, initial=5)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilos()


@login_required
def onboarding(request):
    hotel = request.hotel
    if hotel is None or not request.user.has_perm("core.change_hotel"):
        raise PermissionDenied
    estado, _ = EstadoOnboarding.objects.get_or_create(hotel=hotel)
    paso = int(request.GET.get("paso") or estado.paso)
    ctx = {"estado": estado, "paso": paso, "pasos": EstadoOnboarding.PASOS}
    if paso == 1:
        form = HotelForm(request.POST or None, instance=hotel)
        if request.method == "POST" and form.is_valid():
            form.save()
            return _avanzar(estado, 2)
        ctx["form"] = form
    elif paso == 2:
        form = GeneradorHabitacionesForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            d = form.cleaned_data
            try:
                with transaction.atomic():
                    services.validar_limite_habitaciones(hotel, d["cantidad"])
                    tipo, _ = TipoHabitacion.objects.get_or_create(
                        hotel=hotel,
                        nombre=d["tipo_nombre"],
                        activo=True,
                        defaults={"capacidad": d["capacidad"], "camas": d["camas"], "precio_base": d["precio_base"]},
                    )
                    creadas = 0
                    for n in range(d["desde"], d["desde"] + d["cantidad"]):
                        if not Habitacion.objects.filter(hotel=hotel, numero=str(n), activo=True).exists():
                            Habitacion.objects.create(hotel=hotel, numero=str(n), piso=d["piso"], tipo=tipo)
                            creadas += 1
                messages.success(
                    request, f"{creadas} habitación/es «{tipo}» creada/s. Puede agregar otro tipo o seguir."
                )
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
            return redirect("/onboarding/?paso=2")
        ctx.update(
            {
                "form": form,
                "tipos": TipoHabitacion.objects.filter(hotel=hotel, activo=True),
                "total": Habitacion.objects.filter(hotel=hotel, activo=True).count(),
            }
        )
    elif paso == 3:
        tipos = TipoHabitacion.objects.filter(hotel=hotel, activo=True)
        if request.method == "POST":
            for t in tipos:
                valor = request.POST.get(f"precio_{t.pk}")
                if valor:
                    t.precio_base = Decimal(valor)
                    t.precio_minimo = Decimal(request.POST.get(f"min_{t.pk}") or 0) or None
                    t.precio_maximo = Decimal(request.POST.get(f"max_{t.pk}") or 0) or None
                    t.save()
            return _avanzar(estado, 4)
        ctx["tipos"] = tipos
    elif paso == 4:
        form = UsuarioForm(request.POST or None, hotel=hotel)
        if request.method == "POST":
            if request.POST.get("saltar"):
                return _avanzar(estado, 5)
            if form.is_valid():
                form.save()
                messages.success(request, "Usuario creado. Puede agregar otro o continuar.")
                return redirect("/onboarding/?paso=4")
        ctx.update({"form": form, "usuarios": hotel.usuarios.all()})
    elif paso == 5:
        if request.method == "POST":
            estado.completo = True
            estado.save()
            messages.success(request, "¡Configuración inicial completa! El hotel ya está operativo.")
            return redirect("inicio")
    return render(request, "saas/onboarding.html", ctx)


def _avanzar(estado, paso):
    estado.paso = max(estado.paso, paso)
    estado.save()
    return redirect(f"/onboarding/?paso={paso}")


# ------------------------------------------------------------------ Importación desde Excel


def _celda(v):
    if isinstance(v, datetime):
        return v.date()
    return v.strip() if isinstance(v, str) else v


@login_required
def importar(request):
    if not request.user.has_perm("huespedes.add_huesped"):
        raise PermissionDenied
    resultado = None
    if request.method == "POST" and request.FILES.get("archivo"):
        from openpyxl import load_workbook

        tipo = request.POST.get("tipo", "huespedes")
        try:
            wb = load_workbook(request.FILES["archivo"], read_only=True, data_only=True)
            ws = wb.active
            filas = list(ws.iter_rows(values_only=True))
            encabezados = [str(h or "").strip().lower() for h in filas[0]]
            registros = [dict(zip(encabezados, [_celda(v) for v in f])) for f in filas[1:] if any(f)]
            resultado = (_importar_huespedes if tipo == "huespedes" else _importar_reservas)(request, registros)
        except Exception as exc:  # noqa: BLE001 - archivo inválido: se informa al usuario
            messages.error(request, f"No se pudo leer el archivo: {exc}")
    return render(request, "saas/importar.html", {"resultado": resultado})


def _importar_huespedes(request, registros):
    creados = actualizados = 0
    errores = []
    for i, r in enumerate(registros, start=2):
        nro = str(r.get("nro_doc") or "").replace(".", "").strip().upper()
        if not (nro and r.get("nombre") and r.get("apellido")):
            errores.append(f"Fila {i}: faltan nombre, apellido o nro_doc.")
            continue
        tipo = (r.get("tipo_doc") or "DNI").upper()
        h, creado = Huesped.objects.get_or_create(
            hotel=request.hotel,
            tipo_doc=tipo,
            nro_doc=nro,
            activo=True,
            defaults={"nombre": r["nombre"], "apellido": r["apellido"]},
        )
        for campo in ("nombre", "apellido", "email", "telefono", "nacionalidad", "direccion", "localidad", "provincia"):
            if r.get(campo):
                setattr(h, campo, str(r[campo]))
        if isinstance(r.get("fecha_nacimiento"), date):
            h.fecha_nacimiento = r["fecha_nacimiento"]
        h.save()
        creados += creado
        actualizados += not creado
    return {"creados": creados, "actualizados": actualizados, "errores": errores}


def _importar_reservas(request, registros):
    from reservas import services as res
    from reservas.models import Reserva

    creados = 0
    errores = []
    for i, r in enumerate(registros, start=2):
        try:
            nro = str(r.get("nro_doc") or "").replace(".", "").strip().upper()
            titular = Huesped.objects.filter(hotel=request.hotel, nro_doc=nro, activo=True).first()
            if titular is None:
                if not (r.get("nombre") and r.get("apellido") and nro):
                    raise ValidationError("huésped inexistente y sin datos para crearlo")
                titular = Huesped.objects.create(
                    hotel=request.hotel,
                    nro_doc=nro,
                    nombre=r["nombre"],
                    apellido=r["apellido"],
                    tipo_doc=(r.get("tipo_doc") or "DNI").upper(),
                )
            hab = Habitacion.objects.filter(hotel=request.hotel, numero=str(r.get("habitacion")), activo=True).first()
            if hab is None:
                raise ValidationError(f"habitación {r.get('habitacion')} inexistente")
            canal = r.get("canal") if r.get("canal") in Reserva.Canal.values else Reserva.Canal.OTRO
            res.crear_reserva(
                request.hotel,
                titular,
                r["entrada"],
                r["salida"],
                [{"habitacion": hab, "cantidad_huespedes": int(r.get("huespedes") or 1)}],
                canal=canal,
                estado=Reserva.Estado.CONFIRMADA,
                usuario=request.user,
                referencia_canal=str(r.get("referencia") or ""),
                permitir_pasado=False,
            )
            creados += 1
        except (ValidationError, KeyError, TypeError, ValueError) as exc:
            errores.append(f"Fila {i}: {' '.join(getattr(exc, 'messages', [str(exc)]))}")
    return {"creados": creados, "actualizados": 0, "errores": errores}


# ------------------------------------------------------------------ Suscripción del cliente


@login_required
def mi_suscripcion(request):
    sus = services.suscripcion_de(request.hotel)
    if sus is None:
        return render(request, "saas/mi_suscripcion.html", {"sus": None})
    if request.method == "POST" and request.user.has_perm("core.change_hotel"):
        if request.POST.get("accion") == "pagar":
            ok = services.cobrar(sus)
            (messages.success if ok else messages.error)(
                request, "Pago aprobado: la cuenta está activa." if ok else "El pago fue rechazado."
            )
        elif request.POST.get("accion") == "medio":
            sus.medio_pago_token = request.POST.get("token", "")[:200]
            sus.save(update_fields=["medio_pago_token", "actualizado_en"])
            messages.success(request, "Medio de pago actualizado.")
        return redirect("saas_mi_suscripcion")
    return render(
        request,
        "saas/mi_suscripcion.html",
        {
            "sus": sus,
            "cobros": sus.cobros.all()[:12],
            "uso": services.metricas_uso(sus.empresa),
            "planes": Plan.objects.filter(activo=True),
        },
    )


# ------------------------------------------------------------------ Panel de Impulso (superadmin)


@superadmin_requerido
def panel(request):
    q = request.GET.get("q", "")
    empresas = Empresa.objects.select_related("suscripcion__plan").order_by("razon_social")
    if q:
        empresas = empresas.filter(Q(razon_social__icontains=q) | Q(cuit__icontains=q))
    filas = [{"e": e, "uso": services.metricas_uso(e), "sus": getattr(e, "suscripcion", None)} for e in empresas]
    resumen = {estado: Suscripcion.objects.filter(estado=estado).count() for estado, _ in Suscripcion.Estado.choices}
    return render(
        request,
        "saas/panel.html",
        {
            "filas": filas,
            "q": q,
            "resumen": resumen,
            "tickets_abiertos": TicketSoporte.objects.exclude(estado__in=["resuelto", "cerrado"]).count(),
        },
    )


@superadmin_requerido
def empresa_detalle(request, pk):
    e = get_object_or_404(Empresa, pk=pk)
    sus = getattr(e, "suscripcion", None)
    if request.method == "POST" and sus:
        accion = request.POST.get("accion")
        if accion == "plan":
            sus.plan = get_object_or_404(Plan, pk=request.POST.get("plan"))
        elif accion == "suspender":
            sus.estado = Suscripcion.Estado.SUSPENDIDA
        elif accion == "reactivar":
            sus.estado = Suscripcion.Estado.ACTIVA
            sus.moroso_desde = None
        sus.save()
        auditoria.registrar(Auditoria.Accion.ACCION, sus, f"Superadmin: {accion}", modelo="saas.Suscripcion")
        messages.success(request, "Suscripción actualizada.")
        return redirect("saas_empresa", pk)
    return render(
        request,
        "saas/empresa.html",
        {
            "e": e,
            "sus": sus,
            "uso": services.metricas_uso(e),
            "planes": Plan.objects.all(),
            "hoteles": e.hoteles.all(),
            "cobros": sus.cobros.all()[:12] if sus else [],
        },
    )


@superadmin_requerido
@require_POST
def soporte_acceder(request, hotel_id):
    """Acceso de soporte a un hotel: requiere motivo y queda auditado."""
    hotel = get_object_or_404(Hotel, pk=hotel_id)
    motivo = request.POST.get("motivo", "").strip()
    if not motivo:
        messages.error(request, "Indique el motivo del acceso de soporte.")
        return redirect("saas_empresa", hotel.empresa_id)
    request.session["soporte_hotel"] = hotel.pk
    auditoria.registrar(
        Auditoria.Accion.SOPORTE, hotel, f"Acceso de soporte: {motivo}", hotel=hotel, modelo="core.Hotel"
    )
    messages.info(request, f"Acceso de soporte a {hotel} iniciado.")
    return redirect("inicio")


@login_required
@require_POST
def soporte_salir(request):
    hotel_id = request.session.pop("soporte_hotel", None)
    if hotel_id:
        auditoria.registrar(
            Auditoria.Accion.SOPORTE,
            None,
            "Fin del acceso de soporte",
            hotel=Hotel.objects.filter(pk=hotel_id).first(),
            modelo="core.Hotel",
        )
    return redirect("saas_panel")


# ------------------------------------------------------------------ Mesa de ayuda y base de conocimiento


class TicketForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = TicketSoporte
        fields = ["asunto", "descripcion", "prioridad"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilos()


def _es_soporte(user):
    return user.es_superadmin_impulso or user.is_superuser


@login_required
def soporte_lista(request):
    if _es_soporte(request.user):
        tickets = TicketSoporte.objects.select_related("empresa", "usuario")
    else:
        empresa_id = request.hotel.empresa_id if request.hotel else None
        tickets = TicketSoporte.objects.filter(empresa_id=empresa_id)
    form = TicketForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if request.hotel is None or request.hotel.empresa_id is None:
            messages.error(request, "Su hotel no está asociado a una empresa cliente.")
        else:
            t = form.save(commit=False)
            t.empresa_id, t.hotel, t.usuario = request.hotel.empresa_id, request.hotel, request.user
            t.save()
            messages.success(request, f"Ticket #{t.pk} creado. Le responderemos a la brevedad.")
            return redirect("soporte_ticket", t.pk)
    return render(
        request, "saas/soporte.html", {"tickets": tickets[:100], "form": form, "es_soporte": _es_soporte(request.user)}
    )


@login_required
def soporte_ticket(request, pk):
    t = get_object_or_404(TicketSoporte, pk=pk)
    es_soporte = _es_soporte(request.user)
    if not es_soporte and (request.hotel is None or t.empresa_id != request.hotel.empresa_id):
        raise PermissionDenied
    if request.method == "POST":
        texto = request.POST.get("texto", "").strip()
        if texto:
            MensajeTicket.objects.create(ticket=t, autor=request.user, texto=texto, es_soporte=es_soporte)
        nuevo = request.POST.get("estado")
        if nuevo in TicketSoporte.Estado.values and (es_soporte or nuevo == "cerrado"):
            t.estado = nuevo
        elif texto:
            t.estado = TicketSoporte.Estado.ESPERANDO if es_soporte else TicketSoporte.Estado.ABIERTO
        t.save()
        return redirect("soporte_ticket", pk)
    return render(
        request, "saas/ticket.html", {"t": t, "es_soporte": es_soporte, "estados": TicketSoporte.Estado.choices}
    )


@login_required
def ayuda(request):
    q = request.GET.get("q", "")
    articulos = ArticuloConocimiento.objects.filter(publicado=True)
    if q:
        articulos = articulos.filter(Q(titulo__icontains=q) | Q(contenido__icontains=q))
    return render(
        request, "saas/ayuda.html", {"articulos": articulos, "q": q, "versiones": VersionCambio.objects.all()[:10]}
    )

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.exportar import respuesta_excel, respuesta_pdf
from core.forms import BootstrapMixin

from . import services
from .models import Caja, MovimientoCaja, Pago


def _err(exc):
    return " ".join(getattr(exc, "messages", [str(exc)]))


class AbrirForm(BootstrapMixin, forms.Form):
    turno = forms.ChoiceField(choices=[("Mañana", "Mañana"), ("Tarde", "Tarde"), ("Noche", "Noche")], required=False)
    monto_inicial = forms.DecimalField(label="Efectivo inicial ARS", min_value=0, initial=0, decimal_places=2)
    monto_inicial_usd = forms.DecimalField(label="Efectivo inicial USD", min_value=0, initial=0, decimal_places=2)
    es_general = forms.BooleanField(label="Caja general (administración)", required=False)

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not (usuario and usuario.has_perm("caja.ver_caja_general")):
            del self.fields["es_general"]
        self.aplicar_estilos()


class CerrarForm(BootstrapMixin, forms.Form):
    monto_contado = forms.DecimalField(label="Efectivo contado ARS", min_value=0, decimal_places=2)
    monto_contado_usd = forms.DecimalField(label="Efectivo contado USD", min_value=0, decimal_places=2, initial=0)
    observaciones = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilos()


class MovimientoForm(BootstrapMixin, forms.Form):
    tipo = forms.ChoiceField(choices=MovimientoCaja.Tipo.choices)
    importe = forms.DecimalField(min_value=0.01, decimal_places=2)
    moneda = forms.ChoiceField(choices=[("ARS", "ARS"), ("USD", "USD")])
    concepto = forms.CharField(max_length=200, help_text="Ej.: retiro a caja fuerte, cambio, propina")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilos()


@login_required
@permission_required("caja.add_caja", raise_exception=True)
def mi_caja(request):
    caja = services.caja_abierta(request.user, request.hotel)
    abrir = AbrirForm(request.POST or None, usuario=request.user) if caja is None else None
    if caja is None and request.method == "POST" and abrir.is_valid():
        d = abrir.cleaned_data
        try:
            services.abrir_caja(
                request.hotel,
                request.user,
                d["monto_inicial"],
                d["monto_inicial_usd"],
                d["turno"],
                es_general=d.get("es_general", False),
            )
            messages.success(request, "Caja abierta.")
            return redirect("caja_mia")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _err(exc))
    ultimas = Caja.objects.filter(hotel=request.hotel, usuario=request.user, activo=True).exclude(
        pk=caja.pk if caja else None
    )[:5]
    ctx = {"caja": caja, "abrir": abrir, "ultimas": ultimas}
    if caja:
        ctx.update(
            {
                "resumen": services.resumen(caja),
                "cerrar": CerrarForm(),
                "mov_form": MovimientoForm(),
                "movimientos": caja.movimientos.filter(activo=True).order_by("-fecha"),
            }
        )
    return render(request, "caja/mi_caja.html", ctx)


def _caja_visible(request, pk):
    caja = get_object_or_404(Caja, pk=pk, hotel=request.hotel, activo=True)
    if caja.usuario_id != request.user.pk and not request.user.has_perm("caja.ver_caja_general"):
        raise PermissionDenied
    return caja


@login_required
@require_POST
def cerrar(request, pk):
    caja = _caja_visible(request, pk)
    form = CerrarForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        try:
            caja = services.cerrar_caja(
                caja, d["monto_contado"], request.user, d["monto_contado_usd"] or 0, d["observaciones"]
            )
            nivel = messages.success if caja.diferencia == 0 and caja.diferencia_usd == 0 else messages.warning
            nivel(
                request,
                f"Caja cerrada. Esperado $ {caja.monto_esperado:,.2f}, contado $ {caja.monto_contado:,.2f}, "
                f"diferencia $ {caja.diferencia:,.2f}.",
            )
            return redirect("caja_detalle", caja.pk)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _err(exc))
    else:
        messages.error(request, form.errors.as_text())
    return redirect("caja_mia")


@login_required
@permission_required("caja.add_caja", raise_exception=True)
@require_POST
def movimiento(request, pk):
    caja = _caja_visible(request, pk)
    form = MovimientoForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        try:
            services.registrar_movimiento(
                caja, d["tipo"], d["importe"], d["concepto"], moneda=d["moneda"], usuario=request.user
            )
            messages.success(request, "Movimiento registrado.")
        except ValidationError as exc:
            messages.error(request, _err(exc))
    return redirect("caja_mia")


@login_required
@permission_required("caja.ver_caja_general", raise_exception=True)
def lista(request):
    qs = Caja.objects.filter(hotel=request.hotel, activo=True).select_related("usuario")
    pagina = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "caja/lista.html", {"page_obj": pagina})


@login_required
def detalle(request, pk):
    caja = _caja_visible(request, pk)
    ctx = {
        "caja": caja,
        "resumen": services.resumen(caja),
        "movimientos": caja.movimientos.filter(activo=True).order_by("fecha"),
    }
    formato = request.GET.get("formato")
    if formato == "pdf":
        return respuesta_pdf(f"cierre_caja_{caja.pk}", "caja/cierre_pdf.html", {**ctx, "hotel": request.hotel}, request)
    if formato == "xlsx":
        filas = [
            [
                timezone.localtime(m.fecha),
                m.get_tipo_display(),
                m.get_medio_display(),
                m.moneda,
                m.importe,
                m.concepto,
                m.referencia,
            ]
            for m in ctx["movimientos"]
        ]
        resumen = [
            ["Monto inicial ARS", caja.monto_inicial],
            ["Monto inicial USD", caja.monto_inicial_usd],
            ["Esperado ARS", caja.monto_esperado],
            ["Contado ARS", caja.monto_contado],
            ["Diferencia ARS", caja.diferencia],
            ["Esperado USD", caja.monto_esperado_usd],
            ["Contado USD", caja.monto_contado_usd],
            ["Diferencia USD", caja.diferencia_usd],
        ]
        return respuesta_excel(
            f"cierre_caja_{caja.pk}",
            [
                ("Arqueo", ["Concepto", "Importe"], resumen),
                ("Movimientos", ["Fecha", "Tipo", "Medio", "Moneda", "Importe", "Concepto", "Referencia"], filas),
            ],
        )
    return render(request, "caja/detalle.html", ctx)


@login_required
@permission_required("bi.ver_informes_economicos", raise_exception=True)
def informes(request):
    """Ingresos por día y medio de pago, cierres de caja, cuentas pendientes e IVA ventas."""
    from facturacion.services import libro_iva_ventas
    from reservas.models import Reserva

    hotel = request.hotel
    hoy = timezone.localdate()
    desde = parse_date(request.GET.get("desde", "") or "") or hoy.replace(day=1)
    hasta = parse_date(request.GET.get("hasta", "") or "") or hoy
    pagos = Pago.objects.filter(hotel=hotel, activo=True, fecha__date__gte=desde, fecha__date__lte=hasta)
    por_dia = defaultdict(lambda: defaultdict(lambda: Decimal("0")))
    medios = set()
    for p in pagos:
        dia = timezone.localtime(p.fecha).date()
        por_dia[dia][p.get_medio_display()] += p.importe_ars * p.signo
        medios.add(p.get_medio_display())
    medios = sorted(medios)
    filas_dia = [
        {"fecha": d, "valores": [por_dia[d][m] for m in medios], "total": sum(por_dia[d].values(), Decimal("0"))}
        for d in sorted(por_dia)
    ]
    totales_medio = [sum((por_dia[d][m] for d in por_dia), Decimal("0")) for m in medios]
    cierres = Caja.objects.filter(
        hotel=hotel, activo=True, estado=Caja.Estado.CERRADA, cierre__date__gte=desde, cierre__date__lte=hasta
    ).select_related("usuario")
    pendientes = []
    for r in (
        Reserva.objects.filter(hotel=hotel, activo=True, estado__in=["en_curso", "finalizada"])
        .select_related("titular", "cuenta_corriente")
        .filter(fecha_salida__gte=hoy - timedelta(days=365))
    ):
        s = services.saldo(r)
        if s > Decimal("0.009"):
            pendientes.append({"reserva": r, "saldo": s})
    iva_filas, iva_totales = libro_iva_ventas(hotel, desde, hasta)
    ctx = {
        "desde": desde,
        "hasta": hasta,
        "medios": medios,
        "filas_dia": filas_dia,
        "totales_medio": totales_medio,
        "total_general": sum(totales_medio, Decimal("0")),
        "cierres": cierres,
        "pendientes": pendientes,
        "iva_filas": iva_filas,
        "iva_totales": iva_totales,
        "hotel": hotel,
    }
    formato = request.GET.get("formato")
    if formato == "pdf":
        return respuesta_pdf(f"informe_economico_{desde}_{hasta}", "caja/informes_pdf.html", ctx, request)
    if formato == "xlsx":
        return respuesta_excel(
            f"informe_economico_{desde}_{hasta}",
            [
                (
                    "Ingresos por día",
                    ["Fecha"] + medios + ["Total"],
                    [[f["fecha"]] + f["valores"] + [f["total"]] for f in filas_dia],
                ),
                (
                    "Cierres de caja",
                    ["Apertura", "Cierre", "Usuario", "Esperado", "Contado", "Diferencia"],
                    [
                        [c.apertura, c.cierre, str(c.usuario), c.monto_esperado, c.monto_contado, c.diferencia]
                        for c in cierres
                    ],
                ),
                (
                    "Cuentas pendientes",
                    ["Reserva", "Titular", "Empresa", "Salida", "Saldo"],
                    [
                        [
                            p["reserva"].codigo,
                            str(p["reserva"].titular),
                            str(p["reserva"].cuenta_corriente or ""),
                            p["reserva"].fecha_salida,
                            p["saldo"],
                        ]
                        for p in pendientes
                    ],
                ),
                (
                    "IVA ventas",
                    ["Fecha", "Comprobante", "Receptor", "Doc.", "Neto", "IVA", "Exento", "Total"],
                    [
                        [
                            f["factura"].fecha,
                            str(f["factura"]),
                            f["factura"].receptor_nombre,
                            f["factura"].receptor_doc_nro,
                            f["neto"],
                            f["iva"],
                            f["exento"],
                            f["total"],
                        ]
                        for f in iva_filas
                    ],
                ),
            ],
        )
    return render(request, "caja/informes.html", ctx)

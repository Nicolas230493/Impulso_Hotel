import json

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core import auditoria
from core.forms import FormHotel
from core.models import Auditoria

from .models import Huesped


class HuespedForm(FormHotel):
    class Meta:
        model = Huesped
        fields = [
            "nombre",
            "apellido",
            "tipo_doc",
            "nro_doc",
            "nacionalidad",
            "fecha_nacimiento",
            "email",
            "telefono",
            "direccion",
            "localidad",
            "provincia",
            "pais_residencia",
            "condicion_iva",
            "cuit",
            "razon_social",
            "preferencias",
            "notas_internas",
            "consentimiento_datos",
            "consentimiento_whatsapp",
        ]

    def clean(self):
        datos = super().clean()
        nro = (datos.get("nro_doc") or "").replace(".", "").replace(" ", "").upper()
        if nro and self.hotel:
            dup = Huesped.objects.filter(hotel=self.hotel, activo=True, tipo_doc=datos.get("tipo_doc"), nro_doc=nro)
            if self.instance.pk:
                dup = dup.exclude(pk=self.instance.pk)
            if dup.exists():
                raise forms.ValidationError(
                    f"Ya existe un huésped con ese documento: {dup.first()} " f"(ficha #{dup.first().pk})."
                )
        return datos


@login_required
@permission_required("huespedes.view_huesped", raise_exception=True)
def lista(request):
    qs = Huesped.objects.filter(hotel=request.hotel, activo=True)
    q = request.GET.get("q", "").strip()
    if q:
        for palabra in q.split():
            qs = qs.filter(
                Q(nombre__icontains=palabra)
                | Q(apellido__icontains=palabra)
                | Q(nro_doc__icontains=palabra)
                | Q(email__icontains=palabra)
                | Q(telefono__icontains=palabra)
            )
    pagina = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "huespedes/lista.html", {"page_obj": pagina, "q": q})


@login_required
@permission_required("huespedes.view_huesped", raise_exception=True)
def detalle(request, pk):
    h = get_object_or_404(Huesped, pk=pk, hotel=request.hotel, activo=True)
    reservas = h.reservas.filter(activo=True).order_by("-fecha_entrada")
    como_acompanante = h.estadias_como_acompanante.select_related("reserva", "habitacion")
    noches = sum(r.noches for r in reservas if r.estado in ("en_curso", "finalizada"))
    return render(
        request, "huespedes/detalle.html", {"h": h, "reservas": reservas, "acomp": como_acompanante, "noches": noches}
    )


@login_required
@permission_required("huespedes.add_huesped", raise_exception=True)
def form(request, pk=None):
    h = get_object_or_404(Huesped, pk=pk, hotel=request.hotel, activo=True) if pk else None
    f = HuespedForm(request.POST or None, instance=h, hotel=request.hotel)
    if request.method == "POST" and f.is_valid():
        h = f.save()
        messages.success(request, "Huésped guardado.")
        return redirect("huesped_detalle", h.pk)
    return render(request, "crud/form.html", {"form": f, "titulo": "Huésped", "url_lista": "/huespedes/"})


@login_required
@permission_required("huespedes.change_huesped", raise_exception=True)
def exportar_datos(request, pk):
    """Derecho de acceso (Ley 25.326): exporta todos los datos personales del huésped."""
    h = get_object_or_404(Huesped, pk=pk, hotel=request.hotel)
    datos = {
        "huesped": auditoria.serializar(h),
        "reservas": [auditoria.serializar(r) for r in h.reservas.all()],
        "estadias_como_acompanante": [e.reserva.codigo for e in h.estadias_como_acompanante.all()],
        "mensajes": [{"fecha": m.creado_en, "canal": m.canal, "titulo": m.titulo} for m in h.mensajes.all()],
    }
    auditoria.registrar(Auditoria.Accion.ACCION, h, "Exportación de datos personales (derecho de acceso)")
    resp = HttpResponse(
        json.dumps(datos, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2),
        content_type="application/json; charset=utf-8",
    )
    resp["Content-Disposition"] = f'attachment; filename="datos_huesped_{h.pk}.json"'
    return resp


@login_required
@permission_required("huespedes.delete_huesped", raise_exception=True)
@require_POST
def suprimir(request, pk):
    """Derecho de supresión: anonimiza los datos personales y conserva lo exigido por normas fiscales."""
    h = get_object_or_404(Huesped, pk=pk, hotel=request.hotel, activo=True)
    if h.reservas.filter(estado__in=["pendiente", "confirmada", "en_curso"]).exists():
        messages.error(request, "El huésped tiene reservas vigentes: no se puede suprimir.")
        return redirect("huesped_detalle", pk)
    h.nombre, h.apellido = "Anonimizado", f"#{h.pk}"
    h.nro_doc = f"ANON-{h.pk}"
    h.tipo_doc = Huesped.TipoDoc.OTRO
    for campo in (
        "email",
        "telefono",
        "direccion",
        "localidad",
        "provincia",
        "preferencias",
        "notas_internas",
        "cuit",
        "razon_social",
    ):
        setattr(h, campo, "")
    h.fecha_nacimiento = None
    h.consentimiento_datos = h.consentimiento_whatsapp = False
    h.save()
    auditoria.registrar(Auditoria.Accion.ACCION, h, "Supresión de datos personales (Ley 25.326)")
    messages.success(request, "Datos personales anonimizados. Los comprobantes fiscales emitidos se conservan.")
    return redirect("huesped_detalle", pk)

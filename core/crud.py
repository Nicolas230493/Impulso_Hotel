"""CRUD genérico para pantallas de configuración y maestros (multi-hotel, con permisos y borrado lógico)."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Q
from django.forms import modelform_factory
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.views.generic import CreateView, ListView, UpdateView, View

from .forms import FormHotel


class Columna:
    def __init__(self, campo, etiqueta=None):
        self.campo = campo
        self.etiqueta = etiqueta or campo.replace("_", " ").replace("__", " ").capitalize()

    def valor(self, obj):
        valor = obj
        for parte in self.campo.split("__"):
            if valor is None:
                return ""
            display = getattr(valor, f"get_{parte}_display", None)
            valor = display() if display else getattr(valor, parte, "")
            if callable(valor):
                valor = valor()
        if valor is True:
            return "Sí"
        if valor is False:
            return "No"
        if valor is None:
            return ""
        return valor


class Crud:
    """Define un CRUD completo a partir de un modelo y genera sus URLs."""

    def __init__(
        self,
        modelo,
        campos,
        columnas,
        nombre,
        titulo,
        buscar_en=(),
        form_class=None,
        orden=None,
        plantilla_lista="crud/lista.html",
        acciones_extra=(),
    ):
        self.modelo = modelo
        self.campos = campos
        self.columnas = [
            c if isinstance(c, Columna) else Columna(*((c,) if isinstance(c, str) else c)) for c in columnas
        ]
        self.nombre = nombre
        self.titulo = titulo
        self.buscar_en = buscar_en
        self.form_class = form_class
        self.orden = orden
        self.plantilla_lista = plantilla_lista
        self.acciones_extra = acciones_extra
        meta = modelo._meta
        self.perm = lambda accion: f"{meta.app_label}.{accion}_{meta.model_name}"
        try:
            meta.get_field("hotel")
            self.por_hotel = True
        except FieldDoesNotExist:
            self.por_hotel = False

    # -- helpers --
    def queryset(self, request):
        qs = self.modelo._default_manager.all()
        if self.por_hotel:
            qs = qs.filter(hotel=request.hotel, activo=True)
        if self.orden:
            qs = qs.order_by(*self.orden)
        return qs

    def get_form_class(self):
        if self.form_class:
            return self.form_class
        return modelform_factory(self.modelo, form=FormHotel, fields=self.campos)

    def contexto(self):
        return {
            "crud": self,
            "titulo": self.titulo,
            "url_nuevo": reverse(f"{self.nombre}_nuevo"),
            "url_lista": reverse(f"{self.nombre}_lista"),
        }

    def urls(self, prefijo):
        crud = self

        class Lista(LoginRequiredMixin, PermissionRequiredMixin, ListView):
            permission_required = crud.perm("view")
            template_name = crud.plantilla_lista
            paginate_by = 25

            def get_queryset(self):
                qs = crud.queryset(self.request)
                q = self.request.GET.get("q", "").strip()
                if q and crud.buscar_en:
                    filtro = Q()
                    for campo in crud.buscar_en:
                        filtro |= Q(**{f"{campo}__icontains": q})
                    qs = qs.filter(filtro)
                return qs

            def get_context_data(self, **kwargs):
                ctx = super().get_context_data(**kwargs)
                ctx.update(crud.contexto())
                ctx["filas"] = [
                    {
                        "obj": o,
                        "celdas": [c.valor(o) for c in crud.columnas],
                        "url_editar": reverse(f"{crud.nombre}_editar", args=[o.pk]),
                        "url_borrar": reverse(f"{crud.nombre}_borrar", args=[o.pk]),
                    }
                    for o in ctx["object_list"]
                ]
                ctx["puede_agregar"] = self.request.user.has_perm(crud.perm("add"))
                ctx["puede_editar"] = self.request.user.has_perm(crud.perm("change"))
                ctx["puede_borrar"] = self.request.user.has_perm(crud.perm("delete"))
                ctx["q"] = self.request.GET.get("q", "")
                return ctx

        class FormMixin:
            template_name = "crud/form.html"

            def get_form_class(self):
                return crud.get_form_class()

            def get_form_kwargs(self):
                kwargs = super().get_form_kwargs()
                kwargs["hotel"] = self.request.hotel
                return kwargs

            def get_context_data(self, **kwargs):
                ctx = super().get_context_data(**kwargs)
                ctx.update(crud.contexto())
                return ctx

            def get_success_url(self):
                return reverse(f"{crud.nombre}_lista")

            def form_valid(self, form):
                messages.success(self.request, f"{crud.modelo._meta.verbose_name.capitalize()} guardado.")
                return super().form_valid(form)

        class Nuevo(LoginRequiredMixin, PermissionRequiredMixin, FormMixin, CreateView):
            permission_required = crud.perm("add")
            model = crud.modelo

        class Editar(LoginRequiredMixin, PermissionRequiredMixin, FormMixin, UpdateView):
            permission_required = crud.perm("change")

            def get_queryset(self):
                return crud.queryset(self.request)

        class Borrar(LoginRequiredMixin, PermissionRequiredMixin, View):
            permission_required = crud.perm("delete")

            def post(self, request, pk):
                obj = get_object_or_404(crud.queryset(request), pk=pk)
                obj.delete()
                messages.success(request, f"{crud.modelo._meta.verbose_name.capitalize()} dado de baja.")
                return redirect(f"{crud.nombre}_lista")

        return [
            path(f"{prefijo}/", Lista.as_view(), name=f"{self.nombre}_lista"),
            path(f"{prefijo}/nuevo/", Nuevo.as_view(), name=f"{self.nombre}_nuevo"),
            path(f"{prefijo}/<int:pk>/editar/", Editar.as_view(), name=f"{self.nombre}_editar"),
            path(f"{prefijo}/<int:pk>/borrar/", Borrar.as_view(), name=f"{self.nombre}_borrar"),
        ]

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import redirect, render

from core.exportar import respuesta_excel
from core.forms import BootstrapMixin

from . import services
from .models import Deposito, MovimientoStock, Producto, Stock


class MovimientoForm(BootstrapMixin, forms.Form):
    producto = forms.ModelChoiceField(queryset=Producto.objects.none())
    deposito = forms.ModelChoiceField(label="Depósito", queryset=Deposito.objects.none())
    tipo = forms.ChoiceField(choices=MovimientoStock.Tipo.choices)
    cantidad = forms.DecimalField(decimal_places=2, help_text="En ajustes, use negativo para restar")
    costo_unitario = forms.DecimalField(required=False, decimal_places=2)
    motivo = forms.CharField(max_length=200)

    def __init__(self, *args, hotel=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["producto"].queryset = Producto.objects.filter(hotel=hotel, activo=True)
        self.fields["deposito"].queryset = Deposito.objects.filter(hotel=hotel, activo=True)
        self.aplicar_estilos()


@login_required
@permission_required("inventario.view_producto", raise_exception=True)
def stock(request):
    hotel = request.hotel
    productos = Producto.objects.filter(hotel=hotel, activo=True).annotate(
        total=Coalesce(Sum("stocks__cantidad"), Value(0), output_field=DecimalField())
    )
    categoria = request.GET.get("categoria", "")
    if categoria:
        productos = productos.filter(categoria=categoria)
    depositos = list(Deposito.objects.filter(hotel=hotel, activo=True))
    stocks = {(s.producto_id, s.deposito_id): s.cantidad for s in Stock.objects.filter(hotel=hotel)}
    filas = [
        {
            "p": p,
            "por_deposito": [stocks.get((p.pk, d.pk), 0) for d in depositos],
            "bajo": p.stock_minimo > 0 and p.total <= p.stock_minimo,
        }
        for p in productos
    ]
    if request.GET.get("formato") == "xlsx":
        return respuesta_excel(
            "stock",
            [
                (
                    "Stock",
                    ["Producto", "Categoría", "Unidad"] + [d.nombre for d in depositos] + ["Total", "Mínimo", "Costo"],
                    [
                        [f["p"].nombre, f["p"].get_categoria_display(), f["p"].unidad]
                        + f["por_deposito"]
                        + [f["p"].total, f["p"].stock_minimo, f["p"].costo]
                        for f in filas
                    ],
                )
            ],
        )
    form = MovimientoForm(hotel=hotel)
    movimientos = MovimientoStock.objects.filter(hotel=hotel).select_related("producto", "deposito", "creado_por")[:30]
    return render(
        request,
        "inventario/stock.html",
        {
            "filas": filas,
            "depositos": depositos,
            "form": form,
            "movimientos": movimientos,
            "categoria": categoria,
            "categorias": Producto.Categoria.choices,
        },
    )


@login_required
@permission_required("inventario.add_movimientostock", raise_exception=True)
def movimiento(request):
    form = MovimientoForm(request.POST or None, hotel=request.hotel)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            services.registrar_movimiento(
                d["producto"],
                d["deposito"],
                d["tipo"],
                d["cantidad"],
                d["motivo"],
                usuario=request.user,
                costo_unitario=d["costo_unitario"],
            )
            messages.success(request, "Movimiento de stock registrado.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
    elif request.method == "POST":
        messages.error(request, form.errors.as_text())
    return redirect("stock_lista")

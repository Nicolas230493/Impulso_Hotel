from datetime import timedelta

from django import forms
from django.utils import timezone

from caja.models import CuentaCorriente, Pago
from core.forms import BootstrapMixin
from huespedes.models import Huesped

from .models import Reserva


class HuespedRapidoMixin(forms.Form):
    """Datos mínimos del titular. Si el documento ya existe en el hotel, se usa el huésped existente."""

    tipo_doc = forms.ChoiceField(label="Tipo doc.", choices=Huesped.TipoDoc.choices, initial="DNI")
    nro_doc = forms.CharField(label="Nº documento", max_length=30)
    nombre = forms.CharField(max_length=100)
    apellido = forms.CharField(max_length=100)
    telefono = forms.CharField(label="Teléfono (WhatsApp)", max_length=50, required=False)
    email = forms.EmailField(required=False)
    nacionalidad = forms.CharField(max_length=60, initial="Argentina", required=False)
    consentimiento_datos = forms.BooleanField(
        label="El huésped consiente el tratamiento de sus datos (Ley 25.326)", required=False
    )
    consentimiento_whatsapp = forms.BooleanField(label="Acepta recibir mensajes por WhatsApp", required=False)

    def obtener_huesped(self, hotel, usuario=None):
        d = self.cleaned_data
        nro = d["nro_doc"].replace(".", "").replace(" ", "").upper()
        h = Huesped.objects.filter(hotel=hotel, activo=True, tipo_doc=d["tipo_doc"], nro_doc=nro).first()
        if h is None:
            h = Huesped(hotel=hotel, tipo_doc=d["tipo_doc"], nro_doc=nro, creado_por=usuario)
        for campo in ("nombre", "apellido", "telefono", "email", "nacionalidad"):
            if d.get(campo):
                setattr(h, campo, d[campo])
        if d.get("consentimiento_datos"):
            h.consentimiento_datos = True
        if d.get("consentimiento_whatsapp"):
            h.consentimiento_whatsapp = True
        h.save()
        return h


class ReservaForm(BootstrapMixin, HuespedRapidoMixin):
    fecha_entrada = forms.DateField(label="Entrada")
    fecha_salida = forms.DateField(label="Salida")
    canal = forms.ChoiceField(choices=Reserva.Canal.choices, initial=Reserva.Canal.DIRECTO)
    referencia_canal = forms.CharField(label="Nº en el canal", required=False, max_length=60)
    sena = forms.DecimalField(label="Seña informada", required=False, min_value=0, decimal_places=2, initial=0)
    cuenta_corriente = forms.ModelChoiceField(
        label="Empresa (cuenta corriente)", required=False, queryset=CuentaCorriente.objects.none()
    )
    confirmar = forms.BooleanField(label="Reserva confirmada", required=False, initial=True)
    observaciones = forms.CharField(widget=forms.Textarea, required=False)

    def __init__(self, *args, hotel=None, walk_in=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.hotel = hotel
        self.walk_in = walk_in
        self.fields["cuenta_corriente"].queryset = CuentaCorriente.objects.filter(hotel=hotel, activo=True)
        if walk_in:
            del self.fields["fecha_entrada"]
            del self.fields["confirmar"]
            del self.fields["sena"]
        self.aplicar_estilos()

    def clean(self):
        datos = super().clean()
        entrada = timezone.localdate() if self.walk_in else datos.get("fecha_entrada")
        salida = datos.get("fecha_salida")
        if entrada and salida and salida <= entrada:
            self.add_error("fecha_salida", "Debe ser posterior a la entrada.")
        datos["fecha_entrada"] = entrada
        return datos


def habitaciones_elegidas(post, hotel):
    """Lee las habitaciones marcadas (hab_<id>) y su cantidad de huéspedes (cant_<id>)."""
    from habitaciones.models import Habitacion

    items = []
    ids = [int(k[4:]) for k in post if k.startswith("hab_") and k[4:].isdigit()]
    for hab in Habitacion.objects.filter(hotel=hotel, activo=True, pk__in=ids).select_related("tipo"):
        try:
            cant = int(post.get(f"cant_{hab.pk}") or 1)
        except ValueError:
            cant = 1
        items.append({"habitacion": hab, "cantidad_huespedes": cant})
    return items


class CancelarForm(BootstrapMixin, forms.Form):
    motivo = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilos()


class PagoForm(BootstrapMixin, forms.Form):
    tipo = forms.ChoiceField(choices=Pago.Tipo.choices, initial=Pago.Tipo.PAGO)
    medio = forms.ChoiceField(choices=[c for c in Pago.Medio.choices if c[0] != "cta_cte"])
    importe = forms.DecimalField(min_value=0.01, decimal_places=2)
    moneda = forms.ChoiceField(choices=[("ARS", "ARS"), ("USD", "USD")])
    tipo_cambio = forms.DecimalField(label="Tipo de cambio", required=False, decimal_places=4, initial=1)
    referencia = forms.CharField(required=False, max_length=100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilos()


class CargoForm(BootstrapMixin, forms.Form):
    origen = forms.ChoiceField(
        choices=[
            ("extra", "Servicio extra"),
            ("consumo", "Consumo (minibar / tienda)"),
            ("restaurante", "Restaurante"),
            ("ajuste", "Ajuste / descuento"),
        ]
    )
    producto = forms.ModelChoiceField(queryset=None, required=False, help_text="Opcional: descuenta stock")
    concepto = forms.CharField(max_length=200, required=False)
    cantidad = forms.DecimalField(min_value=0.01, initial=1, decimal_places=2)
    precio_unitario = forms.DecimalField(
        label="Precio unitario", decimal_places=2, required=False, help_text="Negativo solo para ajustes/descuentos"
    )

    def __init__(self, *args, hotel=None, **kwargs):
        super().__init__(*args, **kwargs)
        from inventario.models import Producto

        self.fields["producto"].queryset = Producto.objects.filter(hotel=hotel, activo=True, precio_venta__isnull=False)
        self.aplicar_estilos()

    def clean(self):
        d = super().clean()
        prod = d.get("producto")
        if prod is None and not d.get("concepto"):
            self.add_error("concepto", "Indique el concepto o elija un producto.")
        if prod is None and d.get("precio_unitario") is None:
            self.add_error("precio_unitario", "Indique el precio.")
        return d


def fecha_salida_por_defecto():
    return timezone.localdate() + timedelta(days=1)

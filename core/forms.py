from django import forms
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import Group

from . import roles
from .models import Hotel, Usuario


class BootstrapMixin:
    def aplicar_estilos(self):
        for campo in self.fields.values():
            w = campo.widget
            if isinstance(w, (forms.CheckboxInput,)):
                w.attrs.setdefault("class", "form-check-input")
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs.setdefault("class", "form-select")
            elif isinstance(w, forms.CheckboxSelectMultiple):
                pass
            else:
                w.attrs.setdefault("class", "form-control")
            if isinstance(w, forms.DateInput) or isinstance(campo, forms.DateField):
                campo.widget = forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d")
            elif isinstance(campo, forms.DateTimeField):
                campo.widget = forms.DateTimeInput(
                    attrs={"type": "datetime-local", "class": "form-control"}, format="%Y-%m-%dT%H:%M"
                )
            elif isinstance(campo, forms.TimeField):
                campo.widget = forms.TimeInput(attrs={"type": "time", "class": "form-control"}, format="%H:%M")
            elif isinstance(w, forms.Textarea):
                w.attrs.setdefault("rows", 3)


class FormHotel(BootstrapMixin, forms.ModelForm):
    """ModelForm que limita las FK al hotel activo y valida unicidad incluyendo el hotel."""

    def __init__(self, *args, hotel=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.hotel = hotel
        if hotel is not None and not getattr(self.instance, "hotel_id", None) and hasattr(self.instance, "hotel_id"):
            self.instance.hotel = hotel
        for campo in self.fields.values():
            qs = getattr(campo, "queryset", None)
            if qs is None or hotel is None:
                continue
            nombres = {f.name for f in qs.model._meta.fields}
            if "hotel" in nombres:
                qs = qs.filter(hotel=hotel)
                if "activo" in nombres:
                    qs = qs.filter(activo=True)
                campo.queryset = qs
            elif qs.model is Usuario:
                campo.queryset = qs.filter(hoteles=hotel, is_active=True)
        self.aplicar_estilos()

    def _get_validation_exclusions(self):
        exclusiones = super()._get_validation_exclusions()
        exclusiones.discard("hotel")
        return exclusiones


class HotelForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Hotel
        fields = [
            "nombre",
            "cuit",
            "condicion_iva",
            "direccion",
            "localidad",
            "provincia",
            "telefono",
            "email",
            "sitio_web",
            "hora_checkin",
            "hora_checkout",
            "tolerancia_checkin_dias",
            "hora_limite_noshow",
            "politica_cancelacion",
            "permitir_stock_negativo",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilos()


class UsuarioForm(BootstrapMixin, forms.ModelForm):
    rol = forms.ModelChoiceField(queryset=Group.objects.filter(name__in=roles.TODOS), required=True)
    password = forms.CharField(
        label="Contraseña", widget=forms.PasswordInput, required=False, help_text="Dejar vacío para no cambiarla."
    )

    class Meta:
        model = Usuario
        fields = ["username", "first_name", "last_name", "email", "telefono", "is_active"]

    def __init__(self, *args, hotel=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.hotel = hotel
        if self.instance.pk:
            self.fields["rol"].initial = self.instance.groups.first()
        else:
            self.fields["password"].required = True
        self.aplicar_estilos()

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if password:
            from django.contrib.auth.password_validation import validate_password

            validate_password(password, self.instance)
        return password

    def save(self, commit=True):
        usuario = super().save(commit=False)
        if self.cleaned_data.get("password"):
            usuario.set_password(self.cleaned_data["password"])
        usuario.save()
        usuario.groups.set([self.cleaned_data["rol"]])
        if self.hotel is not None:
            usuario.hoteles.add(self.hotel)
            if usuario.hotel_activo_id is None:
                usuario.hotel_activo = self.hotel
                usuario.save(update_fields=["hotel_activo"])
        return usuario


class CambioPasswordForm(BootstrapMixin, SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilos()

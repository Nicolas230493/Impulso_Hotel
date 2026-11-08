from rest_framework import serializers

from core.api import HotelSerializer, HotelViewSet

from .models import Huesped


class HuespedSerializer(HotelSerializer):
    class Meta:
        model = Huesped
        fields = [
            "id",
            "nombre",
            "apellido",
            "tipo_doc",
            "nro_doc",
            "nacionalidad",
            "email",
            "telefono",
            "fecha_nacimiento",
            "direccion",
            "localidad",
            "provincia",
            "pais_residencia",
            "condicion_iva",
            "cuit",
            "razon_social",
            "preferencias",
            "consentimiento_datos",
            "consentimiento_whatsapp",
        ]

    def validate(self, attrs):
        request = self.context["request"]
        tipo = attrs.get("tipo_doc", getattr(self.instance, "tipo_doc", "DNI"))
        nro = (
            (attrs.get("nro_doc", getattr(self.instance, "nro_doc", "")) or "")
            .replace(".", "")
            .replace(" ", "")
            .upper()
        )
        dup = Huesped.objects.filter(hotel=request.hotel, activo=True, tipo_doc=tipo, nro_doc=nro)
        if self.instance:
            dup = dup.exclude(pk=self.instance.pk)
        if dup.exists():
            raise serializers.ValidationError(
                {"nro_doc": f"Ya existe un huésped con ese documento (id {dup.first().pk})."}
            )
        return attrs


class HuespedViewSet(HotelViewSet):
    queryset = Huesped.objects.all()
    serializer_class = HuespedSerializer
    search_fields = ["apellido", "nombre", "nro_doc"]
    filterset_fields = ["tipo_doc", "nro_doc", "nacionalidad"]

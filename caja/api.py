from core.api import HotelSerializer, HotelViewSet

from . import services
from .models import Cargo, Pago


class CargoSerializer(HotelSerializer):
    class Meta:
        model = Cargo
        fields = [
            "id",
            "reserva",
            "concepto",
            "fecha",
            "cantidad",
            "precio_unitario",
            "importe",
            "origen",
            "producto",
            "factura",
        ]
        read_only_fields = ["importe", "factura", "fecha"]

    def create(self, d):
        return services.registrar_cargo(
            d["reserva"],
            d["concepto"],
            d["precio_unitario"],
            d.get("cantidad", 1),
            d.get("origen", "extra"),
            producto=d.get("producto"),
            usuario=self.context["request"].user,
        )


class PagoSerializer(HotelSerializer):
    class Meta:
        model = Pago
        fields = [
            "id",
            "reserva",
            "fecha",
            "medio",
            "tipo",
            "importe",
            "moneda",
            "tipo_cambio",
            "importe_ars",
            "referencia",
            "caja",
        ]
        read_only_fields = ["fecha", "importe_ars", "caja"]

    def create(self, d):
        return services.registrar_pago(
            d["reserva"],
            d["medio"],
            d["importe"],
            self.context["request"].user,
            moneda=d.get("moneda", "ARS"),
            tipo_cambio=d.get("tipo_cambio", 1),
            tipo=d.get("tipo", "pago"),
            referencia=d.get("referencia", ""),
        )


class _SinEdicion(HotelViewSet):
    http_method_names = ["get", "post", "head", "options"]


class CargoViewSet(_SinEdicion):
    queryset = Cargo.objects.all()
    serializer_class = CargoSerializer
    filterset_fields = ["reserva", "origen"]


class PagoViewSet(_SinEdicion):
    queryset = Pago.objects.all()
    serializer_class = PagoSerializer
    filterset_fields = ["reserva", "medio", "tipo"]

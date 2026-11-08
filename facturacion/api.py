from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from core.api import HotelViewSet

from . import services
from .models import Factura, ItemFactura


class ItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemFactura
        fields = ["descripcion", "cantidad", "precio_unitario", "alicuota_iva", "neto", "iva", "total"]


class FacturaSerializer(serializers.ModelSerializer):
    items = ItemSerializer(many=True, read_only=True)
    numero_formateado = serializers.CharField(read_only=True)
    tipo_nombre = serializers.CharField(source="get_tipo_display", read_only=True)

    class Meta:
        model = Factura
        fields = [
            "id",
            "tipo",
            "tipo_nombre",
            "numero_formateado",
            "numero",
            "fecha",
            "receptor_nombre",
            "receptor_doc_tipo",
            "receptor_doc_nro",
            "neto_gravado",
            "iva",
            "exento",
            "total",
            "estado",
            "cae",
            "cae_vencimiento",
            "observaciones_arca",
            "reserva",
            "factura_asociada",
            "simulada",
            "items",
        ]
        read_only_fields = fields


class FacturaViewSet(HotelViewSet):
    queryset = Factura.objects.select_related("punto_venta").prefetch_related("items")
    serializer_class = FacturaSerializer
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["estado", "tipo", "reserva"]
    permisos_por_accion = {
        "emitir": ["facturacion.emitir_factura"],
        "nota_credito": ["facturacion.emitir_factura"],
        "create": ["facturacion.emitir_factura"],
    }

    def create(self, request, *args, **kwargs):
        """POST {"reserva": id, "extranjero_exento": false}: factura los cargos pendientes de la reserva."""
        from reservas.models import Reserva

        reserva = Reserva.objects.get(pk=request.data.get("reserva"), hotel=request.hotel)
        f = services.facturar_reserva(
            reserva, emitir_ahora=False, extranjero_exento=bool(request.data.get("extranjero_exento"))
        )
        f = services.emitir(f)
        return Response(FacturaSerializer(f).data, status=201)

    @action(detail=True, methods=["post"])
    def emitir(self, request, pk=None):
        return Response(FacturaSerializer(services.emitir(self.get_object())).data)

    @action(detail=True, methods=["post"], url_path="nota-credito")
    def nota_credito(self, request, pk=None):
        nc = services.nota_credito(
            self.get_object(), request.data.get("motivo", ""), request.data.get("importe"), emitir_ahora=False
        )
        return Response(FacturaSerializer(services.emitir(nc)).data, status=201)

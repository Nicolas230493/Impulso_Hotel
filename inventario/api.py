from rest_framework import serializers

from core.api import HotelSerializer, HotelViewSet

from .models import Producto


class ProductoSerializer(HotelSerializer):
    stock_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Producto
        fields = [
            "id",
            "codigo",
            "nombre",
            "categoria",
            "unidad",
            "costo",
            "precio_venta",
            "alicuota_iva",
            "stock_minimo",
            "stock_total",
        ]


class ProductoViewSet(HotelViewSet):
    queryset = Producto.objects.all()
    serializer_class = ProductoSerializer
    filterset_fields = ["categoria"]

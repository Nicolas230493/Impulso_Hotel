from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import serializers
from rest_framework.response import Response
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.views import APIView

from core.api import HotelViewSet

from . import services
from .models import Alerta


class KpisView(APIView):
    """GET /api/v1/bi/kpis/?desde=&hasta=  (por defecto, el mes en curso)"""

    permisos_requeridos = ["bi.ver_dashboard"]

    @extend_schema(
        parameters=[OpenApiParameter("desde", str), OpenApiParameter("hasta", str)], responses=OpenApiTypes.OBJECT
    )
    def get(self, request):
        from core.middleware import hotel_para_usuario

        hotel = getattr(request._request, "hotel", None) or hotel_para_usuario(request.user, request._request)
        d, h = services.periodo("mensual", timezone.localdate())
        desde = parse_date(request.query_params.get("desde", "") or "") or d
        hasta = parse_date(request.query_params.get("hasta", "") or "") or h
        k = services.kpis(hotel, desde, hasta)
        return Response(k)


class AlertaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alerta
        fields = ["id", "tipo", "nivel", "titulo", "mensaje", "datos_base", "resuelta", "creado_en"]
        read_only_fields = fields


class AlertaViewSet(HotelViewSet):
    queryset = Alerta.objects.all()
    serializer_class = AlertaSerializer
    http_method_names = ["get", "head", "options"]
    filterset_fields = ["tipo", "resuelta"]

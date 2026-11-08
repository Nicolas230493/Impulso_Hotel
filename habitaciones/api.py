from django.utils.dateparse import parse_date
from rest_framework import serializers
from rest_framework.response import Response
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.views import APIView

from core.api import HotelSerializer, HotelViewSet

from . import services
from .models import Habitacion, Tarifa, TipoHabitacion


class TipoHabitacionSerializer(HotelSerializer):
    class Meta:
        model = TipoHabitacion
        fields = [
            "id",
            "nombre",
            "capacidad",
            "camas",
            "amenities",
            "descripcion",
            "precio_base",
            "precio_minimo",
            "precio_maximo",
        ]


class HabitacionSerializer(HotelSerializer):
    tipo_nombre = serializers.CharField(source="tipo.nombre", read_only=True)

    class Meta:
        model = Habitacion
        fields = ["id", "numero", "piso", "tipo", "tipo_nombre", "estado", "observaciones"]
        read_only_fields = ["estado"]


class TarifaSerializer(HotelSerializer):
    class Meta:
        model = Tarifa
        fields = ["id", "tipo_habitacion", "temporada", "fecha_desde", "fecha_hasta", "precio_noche", "moneda"]


class TipoHabitacionViewSet(HotelViewSet):
    queryset = TipoHabitacion.objects.all()
    serializer_class = TipoHabitacionSerializer


class HabitacionViewSet(HotelViewSet):
    queryset = Habitacion.objects.select_related("tipo")
    serializer_class = HabitacionSerializer
    filterset_fields = ["estado", "piso", "tipo"]


class TarifaViewSet(HotelViewSet):
    queryset = Tarifa.objects.all()
    serializer_class = TarifaSerializer
    filterset_fields = ["tipo_habitacion"]


class DisponibilidadView(APIView):
    """GET /api/v1/disponibilidad/?desde=AAAA-MM-DD&hasta=AAAA-MM-DD&tipo=<id>&huespedes=<n>"""

    permisos_requeridos = ["habitaciones.view_habitacion"]

    @extend_schema(
        parameters=[
            OpenApiParameter("desde", str, required=True),
            OpenApiParameter("hasta", str, required=True),
            OpenApiParameter("tipo", int),
            OpenApiParameter("huespedes", int),
        ],
        responses=OpenApiTypes.OBJECT,
    )
    def get(self, request):
        from core.middleware import hotel_para_usuario

        hotel = getattr(request._request, "hotel", None) or hotel_para_usuario(request.user, request._request)
        desde = parse_date(request.query_params.get("desde", "") or "")
        hasta = parse_date(request.query_params.get("hasta", "") or "")
        if not desde or not hasta or hasta <= desde:
            return Response({"detalle": "Indique 'desde' y 'hasta' (AAAA-MM-DD), con hasta > desde."}, status=400)
        tipo = None
        if request.query_params.get("tipo"):
            tipo = TipoHabitacion.objects.filter(hotel=hotel, pk=request.query_params["tipo"]).first()
            if tipo is None:
                return Response({"detalle": "Tipo de habitación inexistente."}, status=400)
        huespedes = int(request.query_params.get("huespedes") or 0) or None
        habs = services.habitaciones_disponibles(hotel, desde, hasta, tipo=tipo, huespedes=huespedes)
        cotizaciones = {}
        datos = []
        for h in habs:
            if h.tipo_id not in cotizaciones:
                total, detalle = services.cotizar(h.tipo, desde, hasta)
                cotizaciones[h.tipo_id] = (total, [{"fecha": d["fecha"], "precio": d["precio"]} for d in detalle])
            datos.append(
                {
                    "id": h.pk,
                    "numero": h.numero,
                    "piso": h.piso,
                    "tipo": h.tipo.nombre,
                    "capacidad": h.tipo.capacidad,
                    "estado": h.estado,
                    "total": cotizaciones[h.tipo_id][0],
                    "noches": cotizaciones[h.tipo_id][1],
                }
            )
        return Response({"desde": desde, "hasta": hasta, "noches": (hasta - desde).days, "disponibles": datos})

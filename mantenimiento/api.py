from rest_framework.decorators import action
from rest_framework.response import Response

from core.api import HotelSerializer, HotelViewSet

from . import services
from .models import Activo, Incidencia


class IncidenciaSerializer(HotelSerializer):
    class Meta:
        model = Incidencia
        fields = [
            "id",
            "habitacion",
            "activo_relacionado",
            "titulo",
            "descripcion",
            "origen",
            "categoria",
            "prioridad",
            "estado",
            "bloqueante",
            "asignada_a",
            "reportada_en",
            "resuelta_en",
            "solucion",
        ]
        read_only_fields = ["estado", "reportada_en", "resuelta_en", "asignada_a"]

    def create(self, d):
        request = self.context["request"]
        return services.reportar(
            request.hotel,
            request.user,
            d["titulo"],
            habitacion=d.get("habitacion"),
            activo=d.get("activo_relacionado"),
            descripcion=d.get("descripcion", ""),
            origen=d.get("origen", "recepcion"),
            categoria=d.get("categoria", "otra"),
            prioridad=d.get("prioridad", 3),
            bloqueante=d.get("bloqueante", False),
        )


class ActivoSerializer(HotelSerializer):
    class Meta:
        model = Activo
        fields = [
            "id",
            "nombre",
            "tipo",
            "habitacion",
            "area",
            "marca",
            "modelo",
            "numero_serie",
            "fecha_instalacion",
            "costo_adquisicion",
            "umbral_reemplazo",
        ]


class IncidenciaViewSet(HotelViewSet):
    queryset = Incidencia.objects.all()
    serializer_class = IncidenciaSerializer
    filterset_fields = ["estado", "habitacion", "prioridad", "asignada_a"]
    permisos_por_accion = {"estado": ["mantenimiento.change_incidencia"]}

    @action(detail=True, methods=["post"])
    def estado(self, request, pk=None):
        inc = services.cambiar_estado(
            self.get_object(), request.data.get("estado"), request.user, request.data.get("solucion", "")
        )
        return Response(IncidenciaSerializer(inc, context=self.get_serializer_context()).data)


class ActivoViewSet(HotelViewSet):
    queryset = Activo.objects.all()
    serializer_class = ActivoSerializer

from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from core.api import HotelSerializer, HotelViewSet

from . import services
from .models import TareaLimpieza


class TareaSerializer(HotelSerializer):
    habitacion_numero = serializers.CharField(source="habitacion.numero", read_only=True)

    class Meta:
        model = TareaLimpieza
        fields = [
            "id",
            "habitacion",
            "habitacion_numero",
            "fecha",
            "tipo",
            "asignada_a",
            "estado",
            "prioridad",
            "inicio",
            "fin",
            "observaciones",
        ]
        read_only_fields = ["estado", "inicio", "fin"]


class TareaLimpiezaViewSet(HotelViewSet):
    queryset = TareaLimpieza.objects.select_related("habitacion")
    serializer_class = TareaSerializer
    filterset_fields = ["fecha", "estado", "asignada_a"]
    permisos_por_accion = {"iniciar": ["limpieza.change_tarealimpieza"], "terminar": ["limpieza.change_tarealimpieza"]}

    @action(detail=True, methods=["post"])
    def iniciar(self, request, pk=None):
        return Response(
            TareaSerializer(
                services.iniciar(self.get_object(), request.user), context=self.get_serializer_context()
            ).data
        )

    @action(detail=True, methods=["post"])
    def terminar(self, request, pk=None):
        t = services.terminar(
            self.get_object(), request.user, request.data.get("checklist") or {}, request.data.get("observaciones", "")
        )
        return Response(TareaSerializer(t, context=self.get_serializer_context()).data)

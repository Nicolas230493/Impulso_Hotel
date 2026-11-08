from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from caja import services as caja_services
from core.api import HotelSerializer, HotelViewSet
from habitaciones.models import Habitacion
from huespedes.models import Huesped

from . import services
from .models import DetalleReserva, Reserva


class DetalleSerializer(serializers.ModelSerializer):
    habitacion_numero = serializers.CharField(source="habitacion.numero", read_only=True)

    class Meta:
        model = DetalleReserva
        fields = [
            "id",
            "habitacion",
            "habitacion_numero",
            "tipo_habitacion",
            "cantidad_huespedes",
            "tarifa_aplicada",
            "subtotal",
            "vigente",
        ]


class ItemSerializer(serializers.Serializer):
    habitacion = serializers.IntegerField()
    cantidad_huespedes = serializers.IntegerField(min_value=1, default=1)


class ReservaSerializer(HotelSerializer):
    detalles = DetalleSerializer(many=True, read_only=True)
    habitaciones = ItemSerializer(many=True, write_only=True)
    confirmar = serializers.BooleanField(write_only=True, default=False)
    saldo = serializers.SerializerMethodField()

    class Meta:
        model = Reserva
        fields = [
            "id",
            "codigo",
            "titular",
            "fecha_entrada",
            "fecha_salida",
            "estado",
            "canal",
            "referencia_canal",
            "total",
            "sena",
            "moneda",
            "observaciones",
            "cuenta_corriente",
            "detalles",
            "habitaciones",
            "confirmar",
            "saldo",
            "motivo_cancelacion",
            "creado_en",
        ]
        read_only_fields = ["codigo", "estado", "total", "motivo_cancelacion", "creado_en"]

    def get_saldo(self, obj):
        return caja_services.saldo(obj)

    def _items(self, datos):
        hotel = self.context["request"].hotel
        items = []
        for it in datos:
            hab = (
                Habitacion.objects.filter(hotel=hotel, activo=True, pk=it["habitacion"]).select_related("tipo").first()
            )
            if hab is None:
                raise serializers.ValidationError({"habitaciones": f"Habitación {it['habitacion']} inexistente."})
            items.append({"habitacion": hab, "cantidad_huespedes": it["cantidad_huespedes"]})
        return items

    def create(self, validated):
        request = self.context["request"]
        return services.crear_reserva(
            request.hotel,
            validated["titular"],
            validated["fecha_entrada"],
            validated["fecha_salida"],
            self._items(validated["habitaciones"]),
            canal=validated.get("canal", Reserva.Canal.DIRECTO),
            sena=validated.get("sena") or 0,
            observaciones=validated.get("observaciones", ""),
            usuario=request.user,
            estado=Reserva.Estado.CONFIRMADA if validated.get("confirmar") else Reserva.Estado.PENDIENTE,
            referencia_canal=validated.get("referencia_canal", ""),
            cuenta_corriente=validated.get("cuenta_corriente"),
        )

    def update(self, instance, validated):
        request = self.context["request"]
        items = (
            self._items(validated["habitaciones"])
            if "habitaciones" in validated
            else [
                {"habitacion": d.habitacion, "cantidad_huespedes": d.cantidad_huespedes}
                for d in instance.detalles.filter(activo=True, vigente=True)
            ]
        )
        otros = {
            k: v
            for k, v in validated.items()
            if k in ("canal", "referencia_canal", "sena", "observaciones", "cuenta_corriente", "titular")
        }
        r = services.modificar_reserva(
            instance,
            validated.get("fecha_entrada", instance.fecha_entrada),
            validated.get("fecha_salida", instance.fecha_salida),
            items,
            usuario=request.user,
            **otros,
        )
        if validated.get("confirmar") and r.estado == Reserva.Estado.PENDIENTE:
            services.confirmar(r, request.user)
        return r


class ReservaViewSet(HotelViewSet):
    queryset = Reserva.objects.select_related("titular").prefetch_related("detalles__habitacion")
    serializer_class = ReservaSerializer
    filterset_fields = ["estado", "canal", "fecha_entrada", "fecha_salida", "titular"]
    permisos_por_accion = {
        "checkin": ["reservas.checkin_reserva"],
        "checkout": ["reservas.checkout_reserva"],
        "cancelar": ["reservas.cancelar_reserva"],
        "confirmar": ["reservas.change_reserva"],
    }

    def perform_destroy(self, instance):
        services.cancelar(instance, "Baja por API", self.request.user)

    def _respuesta(self, reserva):
        reserva.refresh_from_db()
        return Response(ReservaSerializer(reserva, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def confirmar(self, request, pk=None):
        return self._respuesta(services.confirmar(self.get_object(), request.user))

    @action(detail=True, methods=["post"])
    def cancelar(self, request, pk=None):
        return self._respuesta(services.cancelar(self.get_object(), request.data.get("motivo", ""), request.user))

    @action(detail=True, methods=["post"])
    def checkin(self, request, pk=None):
        """Body opcional: {"acompanantes": {"<detalle_id>": [<huesped_id>, ...]}, "confirmar_sucia": true}"""
        r = self.get_object()
        acompanantes = {}
        for det_id, ids in (request.data.get("acompanantes") or {}).items():
            acompanantes[int(det_id)] = list(Huesped.objects.filter(hotel=request.hotel, pk__in=ids))
        return self._respuesta(
            services.checkin(
                r, request.user, acompanantes=acompanantes, confirmar_sucia=bool(request.data.get("confirmar_sucia"))
            )
        )

    @action(detail=True, methods=["post"])
    def checkout(self, request, pk=None):
        r = services.checkout(
            self.get_object(),
            request.user,
            autorizar_saldo=bool(request.data.get("autorizar_saldo")),
            facturar=bool(request.data.get("facturar")),
        )
        return self._respuesta(r)

    @action(detail=False, methods=["post"], url_path="walk-in")
    def walk_in(self, request):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        r = services.walk_in(
            request.hotel,
            d["titular"],
            d["fecha_salida"],
            s._items(d["habitaciones"]),
            usuario=request.user,
            canal=d.get("canal", Reserva.Canal.DIRECTO),
            confirmar_sucia=bool(request.data.get("confirmar_sucia")),
        )
        return Response(
            ReservaSerializer(r, context=self.get_serializer_context()).data, status=status.HTTP_201_CREATED
        )

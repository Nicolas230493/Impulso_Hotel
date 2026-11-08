"""Piezas comunes de la API REST: permisos por rol, viewset multi-hotel y manejo de errores."""

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.views import exception_handler

from . import actual
from .middleware import hotel_para_usuario
from .permisos_api import PermisoPorRol  # noqa: F401


class HotelViewSet(viewsets.ModelViewSet):
    """ViewSet que filtra siempre por el hotel activo y lo asigna al crear."""

    permisos_por_accion = {}

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        # La autenticación de DRF ocurre después del middleware: se fija el contexto aquí.
        request.hotel = getattr(request._request, "hotel", None) or hotel_para_usuario(request.user, request._request)
        self._tokens = actual.fijar(request=request._request, hotel=request.hotel, usuario=request.user)

    def finalize_response(self, request, response, *args, **kwargs):
        tokens = getattr(self, "_tokens", None)
        if tokens:
            actual.limpiar(tokens)
            self._tokens = None
        return super().finalize_response(request, response, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(hotel=self.request.hotel, activo=True)

    def perform_create(self, serializer):
        serializer.save(hotel=self.request.hotel, creado_por=self.request.user)

    def perform_destroy(self, instance):
        instance.delete()  # borrado lógico


class HotelSerializer(serializers.ModelSerializer):
    """Serializer que limita las claves foráneas al hotel activo."""

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        hotel = getattr(request, "hotel", None)
        for field in fields.values():
            qs = getattr(field, "queryset", None)
            if qs is None and hasattr(field, "child_relation"):
                qs = field.child_relation.queryset
                target = field.child_relation
            else:
                target = field
            if qs is not None and hotel is not None and "hotel" in [f.name for f in qs.model._meta.fields]:
                target.queryset = qs.filter(hotel=hotel)
        return fields


def manejador_excepciones(exc, context):
    if isinstance(exc, DjangoValidationError):
        detalle = exc.message_dict if hasattr(exc, "error_dict") else {"detalle": exc.messages}
        return Response(detalle, status=status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, DjangoPermissionDenied):
        return Response({"detalle": str(exc) or "Permiso denegado."}, status=status.HTTP_403_FORBIDDEN)
    if isinstance(exc, IntegrityError):
        return Response(
            {"detalle": "Conflicto de datos: " + str(exc).split("DETAIL:")[0].strip()}, status=status.HTTP_409_CONFLICT
        )
    return exception_handler(exc, context)

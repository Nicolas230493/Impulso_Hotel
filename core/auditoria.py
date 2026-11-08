import json

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.fields.files import FieldFile

from . import actual


def serializar(instancia):
    datos = {}
    for campo in instancia._meta.concrete_fields:
        if campo.name in ("actualizado_en", "password"):
            continue
        valor = getattr(instancia, campo.attname)
        if isinstance(valor, FieldFile):  # archivos
            valor = valor.name or ""
        elif hasattr(valor, "lower") and hasattr(valor, "upper") and hasattr(valor, "bounds"):  # rangos PostgreSQL
            valor = [valor.lower, valor.upper]
        datos[campo.attname] = valor
    return json.loads(json.dumps(datos, cls=DjangoJSONEncoder))


def registrar(accion, instancia=None, descripcion="", antes=None, despues=None, modelo=None, hotel=None, usuario=None):
    from .models import Auditoria

    usuario = usuario or actual.usuario_actual()
    if usuario is not None and not usuario.is_authenticated:
        usuario = None
    if hotel is None and instancia is not None:
        hotel = getattr(instancia, "hotel", None) if hasattr(instancia, "hotel_id") else None
    return Auditoria.objects.create(
        hotel=hotel or actual.hotel_actual(),
        usuario=usuario,
        accion=accion,
        modelo=modelo or (instancia._meta.label if instancia is not None else ""),
        objeto_id=str(instancia.pk) if instancia is not None else "",
        descripcion=descripcion[:255],
        antes=antes,
        despues=despues,
        ip=actual.ip_actual(),
    )

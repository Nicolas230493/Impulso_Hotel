"""Contexto de la petición en curso (usuario, hotel, IP) accesible desde modelos y señales."""

from contextlib import contextmanager
from contextvars import ContextVar

_request = ContextVar("impulso_request", default=None)
_hotel = ContextVar("impulso_hotel", default=None)
_usuario = ContextVar("impulso_usuario", default=None)


def fijar(request=None, hotel=None, usuario=None):
    return (_request.set(request), _hotel.set(hotel), _usuario.set(usuario))


def limpiar(tokens):
    for var, token in zip((_request, _hotel, _usuario), tokens):
        var.reset(token)


def request_actual():
    return _request.get()


def hotel_actual():
    return _hotel.get()


def usuario_actual():
    return _usuario.get()


def ip_actual():
    request = _request.get()
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@contextmanager
def contexto(hotel=None, usuario=None):
    """Para tareas programadas, comandos y tests: fija hotel y usuario temporalmente."""
    tokens = fijar(request=None, hotel=hotel, usuario=usuario)
    try:
        yield
    finally:
        limpiar(tokens)

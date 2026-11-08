"""Clase de permisos de la API (módulo liviano para evitar importaciones circulares de DRF)."""

from rest_framework import permissions


class PermisoPorRol(permissions.DjangoModelPermissions):
    """Permisos del rol (grupo) por modelo y acción. GET exige el permiso view_."""

    perms_map = {
        "GET": ["%(app_label)s.view_%(model_name)s"],
        "OPTIONS": [],
        "HEAD": ["%(app_label)s.view_%(model_name)s"],
        "POST": ["%(app_label)s.add_%(model_name)s"],
        "PUT": ["%(app_label)s.change_%(model_name)s"],
        "PATCH": ["%(app_label)s.change_%(model_name)s"],
        "DELETE": ["%(app_label)s.delete_%(model_name)s"],
    }

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        requeridos = getattr(view, "permisos_por_accion", {}).get(getattr(view, "action", None))
        if requeridos is None:
            requeridos = getattr(view, "permisos_requeridos", None)
        if requeridos is not None:
            return request.user.has_perms(requeridos)
        return super().has_permission(request, view)

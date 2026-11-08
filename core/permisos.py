from django.apps import apps
from django.contrib.auth.models import Group, Permission

from . import roles


def _buscar(codigo):
    app_label, codename = codigo.split(".", 1)
    return Permission.objects.filter(content_type__app_label=app_label, codename=codename).first()


def sincronizar_roles():
    """Crea los grupos de roles y les asigna sus permisos. Idempotente."""
    if not apps.is_installed("django.contrib.auth"):
        return
    admin, _ = Group.objects.get_or_create(name=roles.ADMIN)
    apps_propias = [a.label for a in apps.get_app_configs() if not a.name.startswith("django.")]
    admin.permissions.set(
        Permission.objects.filter(content_type__app_label__in=apps_propias).exclude(content_type__app_label="saas")
    )
    for nombre, codigos in roles.PERMISOS.items():
        grupo, _ = Group.objects.get_or_create(name=nombre)
        perms = [p for p in (_buscar(c) for c in codigos) if p is not None]
        grupo.permissions.set(perms)
    sa, _ = Group.objects.get_or_create(name=roles.SUPERADMIN)
    sa.permissions.set(Permission.objects.filter(content_type__app_label="saas"))

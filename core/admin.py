from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Auditoria, Empresa, Hotel, Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (
            "Impulso",
            {
                "fields": (
                    "telefono",
                    "hoteles",
                    "hotel_activo",
                    "es_superadmin_impulso",
                    "intentos_fallidos",
                    "bloqueado_hasta",
                )
            },
        ),
    )
    list_display = ("username", "email", "first_name", "last_name", "is_active", "es_superadmin_impulso")


admin.site.register(Empresa)
admin.site.register(Hotel)


@admin.register(Auditoria)
class AuditoriaAdmin(admin.ModelAdmin):
    list_display = ("fecha", "hotel", "usuario", "accion", "modelo", "objeto_id", "ip")
    list_filter = ("accion", "hotel")
    search_fields = ("modelo", "objeto_id", "descripcion")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

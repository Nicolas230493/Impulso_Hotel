def impulso(request):
    usuario = getattr(request, "user", None)
    if usuario is None or not usuario.is_authenticated:
        return {}
    from .models import Hotel

    if usuario.is_superuser:
        hoteles = Hotel.objects.filter(activo=True)
    else:
        hoteles = usuario.hoteles.filter(activo=True)
    no_leidas = 0
    try:
        from notificaciones.models import Notificacion

        no_leidas = Notificacion.objects.filter(usuario=usuario, leida=False, canal="interna").count()
    except Exception:  # noqa: BLE001 - durante migraciones iniciales la tabla puede no existir
        pass
    return {
        "hotel": getattr(request, "hotel", None),
        "hoteles_usuario": hoteles,
        "notificaciones_no_leidas": no_leidas,
        "modo_solo_lectura": getattr(request, "solo_lectura", False),
    }

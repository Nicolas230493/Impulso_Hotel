from django.shortcuts import render

from .services import suscripcion_de

# Prefijo de URL → módulo del plan requerido
MODULOS_POR_RUTA = [
    ("/facturacion/", "facturacion"),
    ("/caja/", "caja"),
    ("/inventario/", "inventario"),
    ("/compras/", "compras"),
    ("/limpieza/", "limpieza"),
    ("/mantenimiento/", "mantenimiento"),
    ("/personal/", "personal"),
    ("/bi/prediccion/", "ia"),
    ("/bi/tarifas/", "ia"),
    ("/bi/mantenimiento/", "ia"),
    ("/bi/consolidado/", "multi_hotel"),
    ("/bi/", "bi"),
    ("/api/", "api"),
]
RUTAS_LIBRES_SOLO_LECTURA = ("/cuenta/", "/saas/", "/soporte/", "/hotel/cambiar/")


class SuscripcionMiddleware:
    """Aplica el plan contratado (módulos) y el modo solo lectura ante falta de pago."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.solo_lectura = False
        request.suscripcion = None
        hotel = getattr(request, "hotel", None)
        usuario = getattr(request, "user", None)
        if hotel is not None and usuario is not None and usuario.is_authenticated and not usuario.es_superadmin_impulso:
            sus = suscripcion_de(hotel)
            request.suscripcion = sus
            if sus is not None:
                for prefijo, modulo in MODULOS_POR_RUTA:
                    if request.path.startswith(prefijo):
                        if not sus.plan.incluye(modulo):
                            return render(
                                request,
                                "saas/modulo_no_incluido.html",
                                {"modulo": modulo, "plan": sus.plan},
                                status=403,
                            )
                        break
                if sus.solo_lectura:
                    request.solo_lectura = True
                    if request.method not in ("GET", "HEAD", "OPTIONS") and not request.path.startswith(
                        RUTAS_LIBRES_SOLO_LECTURA
                    ):
                        return render(request, "saas/solo_lectura.html", {"suscripcion": sus}, status=403)
        return self.get_response(request)

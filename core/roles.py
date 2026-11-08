"""Roles del sistema (grupos de Django) y permisos por módulo y acción."""

ADMIN = "Administrador"
RECEPCION = "Recepción"
LIMPIEZA = "Limpieza"
MANTENIMIENTO = "Mantenimiento"
COMPRAS = "Administración y compras"
DUENO = "Dueño"
SUPERADMIN = "Superadmin Impulso"

TODOS = [ADMIN, RECEPCION, LIMPIEZA, MANTENIMIENTO, COMPRAS, DUENO]


def _crud(app, modelo, acciones="add,change,delete,view"):
    return [f"{app}.{a}_{modelo}" for a in acciones.split(",")]


def _ver(app, *modelos):
    return [f"{app}.view_{m}" for m in modelos]


# El administrador recibe todos los permisos; el resto, la lista explícita.
PERMISOS = {
    RECEPCION: [
        *_crud("reservas", "reserva"),
        *_crud("reservas", "detallereserva"),
        *_crud("reservas", "estadia"),
        "reservas.checkin_reserva",
        "reservas.checkout_reserva",
        "reservas.cancelar_reserva",
        *_crud("huespedes", "huesped"),
        *_ver("habitaciones", "habitacion", "tipohabitacion", "tarifa", "bloqueohabitacion"),
        *_crud("caja", "cargo", "add,view"),
        *_crud("caja", "pago", "add,view"),
        *_crud("caja", "caja", "add,change,view"),
        *_ver("caja", "movimientocaja", "cuentacorriente"),
        *_crud("facturacion", "factura", "add,view"),
        "facturacion.emitir_factura",
        *_ver("facturacion", "puntoventa"),
        *_ver("inventario", "producto"),
        *_crud("mantenimiento", "incidencia", "add,view"),
        *_crud("limpieza", "objetoolvidado"),
        *_ver("limpieza", "tarealimpieza"),
        *_ver("notificaciones", "notificacion"),
    ],
    LIMPIEZA: [
        *_ver("habitaciones", "habitacion"),
        "habitaciones.marcar_limpia",
        *_crud("limpieza", "tarealimpieza", "change,view"),
        *_crud("limpieza", "objetoolvidado", "add,view"),
        *_crud("mantenimiento", "incidencia", "add,view"),
        *_ver("notificaciones", "notificacion"),
    ],
    MANTENIMIENTO: [
        *_ver("habitaciones", "habitacion"),
        "habitaciones.cambiar_fuera_servicio",
        *_crud("habitaciones", "bloqueohabitacion"),
        *_crud("mantenimiento", "incidencia"),
        *_crud("mantenimiento", "mantenimiento"),
        *_crud("mantenimiento", "activo"),
        *_crud("mantenimiento", "planpreventivo"),
        *_crud("mantenimiento", "repuestousado"),
        *_ver("inventario", "producto", "stock"),
        *_ver("notificaciones", "notificacion"),
    ],
    COMPRAS: [
        *_crud("compras", "proveedor"),
        *_crud("compras", "gasto"),
        *_crud("compras", "categoriagasto"),
        *_crud("compras", "solicitudcompra"),
        *_crud("compras", "ordencompra"),
        *_crud("inventario", "producto"),
        *_crud("inventario", "deposito"),
        *_crud("inventario", "movimientostock"),
        *_ver("inventario", "stock"),
        *_ver("caja", "caja", "movimientocaja", "pago", "cargo"),
        "caja.ver_caja_general",
        *_crud("caja", "caja", "add,change,view"),
        *_ver("facturacion", "factura"),
        "bi.ver_informes_economicos",
        *_crud("personal", "empleado"),
        *_crud("personal", "turno"),
        *_crud("personal", "licencia"),
        *_ver("notificaciones", "notificacion"),
    ],
    DUENO: [
        "bi.ver_dashboard",
        "bi.ver_informes_economicos",
        *_ver("bi", "alerta", "prediccion", "recomendaciontarifa"),
        *_ver("reservas", "reserva"),
        *_ver("habitaciones", "habitacion", "tarifa"),
        *_ver("caja", "caja", "pago", "cargo"),
        "caja.ver_caja_general",
        *_ver("facturacion", "factura"),
        *_ver("notificaciones", "notificacion"),
    ],
}

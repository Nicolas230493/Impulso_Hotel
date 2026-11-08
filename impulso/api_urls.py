from django.urls import path
from rest_framework.routers import DefaultRouter

from bi.api import AlertaViewSet, KpisView
from caja.api import CargoViewSet, PagoViewSet
from facturacion.api import FacturaViewSet
from habitaciones.api import DisponibilidadView, HabitacionViewSet, TarifaViewSet, TipoHabitacionViewSet
from huespedes.api import HuespedViewSet
from inventario.api import ProductoViewSet
from limpieza.api import TareaLimpiezaViewSet
from mantenimiento.api import ActivoViewSet, IncidenciaViewSet
from reservas.api import ReservaViewSet

router = DefaultRouter()
router.register("tipos-habitacion", TipoHabitacionViewSet, basename="api-tipo")
router.register("habitaciones", HabitacionViewSet, basename="api-habitacion")
router.register("tarifas", TarifaViewSet, basename="api-tarifa")
router.register("huespedes", HuespedViewSet, basename="api-huesped")
router.register("reservas", ReservaViewSet, basename="api-reserva")
router.register("cargos", CargoViewSet, basename="api-cargo")
router.register("pagos", PagoViewSet, basename="api-pago")
router.register("facturas", FacturaViewSet, basename="api-factura")
router.register("productos", ProductoViewSet, basename="api-producto")
router.register("incidencias", IncidenciaViewSet, basename="api-incidencia")
router.register("activos", ActivoViewSet, basename="api-activo")
router.register("tareas-limpieza", TareaLimpiezaViewSet, basename="api-tarea")
router.register("alertas", AlertaViewSet, basename="api-alerta")

urlpatterns = [
    path("disponibilidad/", DisponibilidadView.as_view(), name="api-disponibilidad"),
    path("bi/kpis/", KpisView.as_view(), name="api-kpis"),
] + router.urls

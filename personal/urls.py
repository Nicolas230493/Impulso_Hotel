from django.urls import path

from core.crud import Crud

from . import views
from .models import Empleado, Licencia, Turno

empleados = Crud(
    Empleado,
    ["nombre", "apellido", "dni", "cuil", "puesto", "area", "telefono", "email", "fecha_ingreso", "usuario"],
    [("apellido", "Apellido"), "nombre", "puesto", ("area", "Área"), ("telefono", "Teléfono"), ("usuario", "Usuario")],
    "empleado",
    "Personal",
    buscar_en=["apellido", "nombre", "dni", "puesto"],
)
turnos = Crud(
    Turno,
    ["empleado", "fecha", "hora_inicio", "hora_fin", "area", "observaciones"],
    ["fecha", "empleado", ("hora_inicio", "Desde"), ("hora_fin", "Hasta"), ("area", "Área")],
    "turno",
    "Turnos",
    orden=["-fecha", "hora_inicio"],
    buscar_en=["empleado__apellido"],
)
licencias = Crud(
    Licencia,
    ["empleado", "tipo", "desde", "hasta", "aprobada", "observaciones"],
    ["empleado", "tipo", "desde", "hasta", "aprobada"],
    "licencia",
    "Permisos y licencias",
    orden=["-desde"],
    buscar_en=["empleado__apellido"],
)

urlpatterns = (
    [path("planilla/", views.planilla, name="turno_planilla")]
    + empleados.urls("empleados")
    + turnos.urls("turnos")
    + licencias.urls("licencias")
)

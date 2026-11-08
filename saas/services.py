from datetime import timedelta

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core import roles
from core.models import Empresa, Hotel, Usuario
from integraciones import pasarela

from .models import AceptacionLegal, CobroSuscripcion, DocumentoLegal, EstadoOnboarding, Suscripcion

S = Suscripcion.Estado


def suscripcion_de(hotel):
    if hotel is None or hotel.empresa_id is None:
        return None
    return Suscripcion.objects.filter(empresa_id=hotel.empresa_id).select_related("plan").first()


def modulo_habilitado(hotel, modulo):
    sus = suscripcion_de(hotel)
    if sus is None:
        return True  # instalaciones propias / piloto sin suscripción: todo habilitado
    return sus.plan.incluye(modulo)


def validar_limite_habitaciones(hotel, nuevas=1):
    from habitaciones.models import Habitacion

    sus = suscripcion_de(hotel)
    if sus is None or not sus.plan.max_habitaciones:
        return
    actuales = Habitacion.objects.filter(hotel__empresa_id=hotel.empresa_id, activo=True).count()
    if actuales + nuevas > sus.plan.max_habitaciones:
        raise ValidationError(
            f"Su plan {sus.plan} admite hasta {sus.plan.max_habitaciones} habitaciones. "
            "Mejore su plan para agregar más."
        )


def validar_limite_hoteles(empresa):
    sus = getattr(empresa, "suscripcion", None)
    if sus and empresa.hoteles.filter(activo=True).count() >= sus.plan.max_hoteles:
        raise ValidationError(f"Su plan {sus.plan} admite hasta {sus.plan.max_hoteles} hotel/es.")


@transaction.atomic
def alta_cliente(
    razon_social, cuit, email, nombre_hotel, username, password, plan, nombre="", apellido="", telefono="", ip=None
):
    """Alta autoservicio: empresa, hotel, usuario administrador, suscripción en prueba y aceptación legal."""
    if Usuario.objects.filter(username=username).exists():
        raise ValidationError({"username": "Ese nombre de usuario ya existe."})
    empresa = Empresa.objects.create(razon_social=razon_social, cuit=cuit, email=email, telefono=telefono)
    hotel = Hotel.objects.create(empresa=empresa, nombre=nombre_hotel, cuit=cuit, email=email, telefono=telefono)
    usuario = Usuario.objects.create_user(
        username=username, password=password, email=email, first_name=nombre, last_name=apellido, hotel_activo=hotel
    )
    usuario.hoteles.add(hotel)
    usuario.groups.add(Group.objects.get(name=roles.ADMIN))
    hoy = timezone.localdate()
    Suscripcion.objects.create(
        empresa=empresa,
        plan=plan,
        estado=S.PRUEBA,
        inicio=hoy,
        fin_prueba=hoy + timedelta(days=plan.dias_prueba),
        proximo_cobro=hoy + timedelta(days=plan.dias_prueba),
    )
    EstadoOnboarding.objects.create(hotel=hotel)
    for doc in DocumentoLegal.objects.filter(vigente=True):
        AceptacionLegal.objects.create(empresa=empresa, documento=doc, usuario=usuario, ip=ip)
    from facturacion.models import PuntoVenta
    from inventario.models import Deposito

    PuntoVenta.objects.create(
        hotel=hotel, numero=1, descripcion="Recepción", tipos_habilitados=[1, 3, 6, 8, 11, 13], por_defecto=True
    )
    Deposito.objects.create(hotel=hotel, nombre="Depósito principal")
    return empresa, hotel, usuario


def _sumar_mes(fecha):
    mes = fecha.month % 12 + 1
    anio = fecha.year + (fecha.month == 12)
    dia = min(fecha.day, 28)
    return fecha.replace(year=anio, month=mes, day=dia)


def cobrar(sus, hoy=None):
    hoy = hoy or timezone.localdate()
    aprobado, operacion, detalle = pasarela.cobrar_suscripcion(sus, sus.plan.precio_mensual)
    CobroSuscripcion.objects.create(
        suscripcion=sus,
        periodo=f"{hoy:%Y-%m}",
        importe=sus.plan.precio_mensual,
        aprobado=aprobado,
        id_operacion=operacion,
        detalle=detalle,
    )
    if aprobado:
        sus.estado = S.ACTIVA
        sus.moroso_desde = None
        sus.proximo_cobro = _sumar_mes(sus.proximo_cobro or hoy)
        while sus.proximo_cobro <= hoy:
            sus.proximo_cobro = _sumar_mes(sus.proximo_cobro)
    elif sus.estado in (S.PRUEBA, S.ACTIVA):
        sus.estado = S.MOROSA
        sus.moroso_desde = hoy
    sus.save()
    return aprobado


def revisar_suscripciones(hoy=None):
    """Cobro recurrente; tras los días de gracia sin pago la cuenta pasa a solo lectura (no se borran datos)."""
    hoy = hoy or timezone.localdate()
    for sus in Suscripcion.objects.exclude(estado=S.CANCELADA).select_related("plan"):
        if sus.estado in (S.PRUEBA, S.ACTIVA) and sus.proximo_cobro and sus.proximo_cobro <= hoy:
            cobrar(sus, hoy)
        elif sus.estado in (S.MOROSA, S.SUSPENDIDA):
            if (
                not cobrar(sus, hoy)
                and sus.estado == S.MOROSA
                and sus.moroso_desde
                and (hoy - sus.moroso_desde).days >= Suscripcion.DIAS_GRACIA
            ):
                sus.estado = S.SUSPENDIDA
                sus.save(update_fields=["estado", "actualizado_en"])


def metricas_uso(empresa):
    from django.db.models import Max

    from habitaciones.models import Habitacion
    from reservas.models import Reserva

    hace_30 = timezone.now() - timedelta(days=30)
    hoteles = empresa.hoteles.filter(activo=True)
    usuarios = Usuario.objects.filter(hoteles__in=hoteles).distinct()
    return {
        "hoteles": hoteles.count(),
        "habitaciones": Habitacion.objects.filter(hotel__in=hoteles, activo=True).count(),
        "usuarios": usuarios.count(),
        "reservas_30d": Reserva.objects.filter(hotel__in=hoteles, creado_en__gte=hace_30).count(),
        "ultimo_acceso": usuarios.aggregate(m=Max("last_login"))["m"],
    }

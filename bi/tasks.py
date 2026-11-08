import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def proceso_nocturno():
    from core.models import Hotel

    from .services import proceso_nocturno as proceso

    resultados = {}
    for hotel in Hotel.objects.filter(activo=True):
        try:
            resultados[hotel.pk] = proceso(hotel)
        except Exception:  # noqa: BLE001 - un hotel con error no debe frenar al resto
            logger.exception("Error en el proceso nocturno del hotel %s", hotel.pk)
    return str(resultados)


@shared_task
def enviar_reportes_programados():
    from .reportes import enviar_programados

    return enviar_programados()

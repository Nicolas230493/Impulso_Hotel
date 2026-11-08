from celery import shared_task


@shared_task
def revisar_suscripciones():
    from .services import revisar_suscripciones as tarea

    return tarea()

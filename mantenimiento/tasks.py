from celery import shared_task


@shared_task
def generar_ordenes_preventivas():
    from .services import generar_ordenes_preventivas as tarea

    return tarea()

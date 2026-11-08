from celery import shared_task


@shared_task
def mensajes_programados():
    from .services import mensajes_programados as tarea

    return tarea()

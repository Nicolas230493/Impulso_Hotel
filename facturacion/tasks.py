from celery import shared_task


@shared_task
def reintentar_pendientes():
    from .services import reintentar_pendientes as tarea

    return tarea()

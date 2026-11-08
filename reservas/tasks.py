from celery import shared_task


@shared_task
def marcar_no_shows():
    from .services import marcar_no_shows as tarea

    return tarea()

from celery import shared_task


@shared_task
def cargar_noches():
    from .services import cargar_noches as tarea

    return tarea()

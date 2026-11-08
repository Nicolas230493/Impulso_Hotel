from celery import shared_task


@shared_task
def generar_tareas_del_dia():
    from core.models import Hotel

    from .services import generar_tareas

    return sum(generar_tareas(h) for h in Hotel.objects.filter(activo=True))
